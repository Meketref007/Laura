"""
chat_auto.py - Respostas automáticas para mensagens de chat via LLM

Este módulo detecta mensagens comuns de compradores (rastreamento, prazo, cancelamento)
e responde automaticamente usando classificação via LLM (Ollama, OpenAI, Anthropic).

Features:
- Classificação de intenção via LLMEngine (multi-provider) com fallback para Ollama local
- Respostas automáticas para: rastreamento, prazo, cancelamento
- Integração com webhook de chat da Shopee
- Log de todas as respostas enviadas
- Fallback a respostas heurísticas em caso de erro
- Persistência de estatísticas e templates customizados
- CLI completa via argparse
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .client import ShopeeClient
from .logger import debug, info, warning
from .logger import error as log_error

try:
    from .llm_providers import LLMEngine, extract_json
    HAS_LLM_ENGINE = True
except ImportError:
    HAS_LLM_ENGINE = False
    extract_json = None

try:
    from .llm_local import LauraOllamaAnalyzer
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

from .vision import analisar_reclamacao


@dataclass
class ChatMessage:
    """Representação de uma mensagem de chat"""
    conversation_id: str
    buyer_id: str
    message_text: str
    timestamp: int


@dataclass
class ChatResponse:
    """Resultado de classificação e resposta automática"""
    classified_intent: str  # rastreamento, prazo, cancelamento, produto, outro
    confidence: float
    should_respond: bool
    response_text: str
    reason: str


RECLAMACAO_TEMPLATE = (
    "Olá! Sinto muito pelo problema. 🤝\n\n"
    "Analisei a foto que você enviou e {analise}\n\n"
    "{orientacao}\n\n"
    "Se precisar de mais ajuda, estou aqui! 💙"
)

PREDEFINED_RESPONSES = {
    "rastreamento": (
        "Seu pedido foi enviado! 📦\n\n"
        "Para acompanhar a entrega, clique no botão 'Rastrear' no seu pedido.\n"
        "Prazo estimado: 10 dias úteis após a postagem.\n\n"
        "Dúvidas? Estou aqui para ajudar! 😊"
    ),
    "prazo": (
        "Ótima pergunta! ⏱️\n\n"
        "O prazo de entrega é de <b>10 dias úteis</b> após a confirmação do pagamento.\n"
        "Pode variar um pouco conforme a localização.\n\n"
        "Seu pedido está a caminho! 📬"
    ),
    "cancelamento": (
        "Para cancelar seu pedido:\n"
        "1. Acesse 'Meus Pedidos'\n"
        "2. Clique no pedido\n"
        "3. Clique em 'Cancelar'\n\n"
        "Se o pedido já foi enviado, não é possível cancelar.\n"
        "Nesse caso, você pode devolvê-lo após receber.\n\n"
        "Precisa de ajuda? Me chama! 🙋"
    ),
    "produto_info": (
        "Obrigado pelo interesse! 🛍️\n\n"
        "Para mais informações sobre o produto, veja a descrição completa no anúncio.\n"
        "Se tiver dúvidas específicas, fico feliz em responder! 😊"
    ),
    "reclamacao": "",  # Gerado dinamicamente com OCR
    "outro": (
        "Obrigado pela mensagem! 👋\n\n"
        "Vou analisar sua solicitação em breve.\n"
        "Você será notificado assim que eu responder! ✨"
    ),
}

CLASSIFICATION_PROMPT = """You are a customer support classifier for a Shopee store.
Classify the buyer's message into one of these intents:
- rastreamento: asking about tracking, delivery location, or package status
- prazo: asking about delivery time, deadlines, or how long something takes
- cancelamento: asking to cancel, refund, or return an order
- produto_info: asking about product details, size, color, material, compatibility
- reclamacao: complaining about wrong/damaged item, attaching photos
- outro: anything else

Respond in JSON format:
{"intent": "<intent>", "confidence": <0.0-1.0>, "reason": "<brief explanation>"}"""


class ChatAutomation:
    """Automação de respostas de chat com classificação via LLM"""

    def __init__(
        self,
        client: ShopeeClient | None = None,
        access_token: str | None = None,
        shop_id: int | None = None,
        reports_dir: Path = Path("reports"),
        use_ollama: bool = True,
        cooldown_minutes: int = 60,
        max_responses_per_hour: int = 20,
        human_approval: bool = True,
    ):
        self.client = client
        self.access_token = access_token
        self.shop_id = shop_id
        self.reports_dir = reports_dir
        self.use_ollama = use_ollama
        self.cooldown_minutes = cooldown_minutes
        self.max_responses_per_hour = max_responses_per_hour
        self.human_approval = human_approval

        self._last_response: dict[str, float] = {}
        self._response_timestamps: list[float] = []
        self._responded_messages: set[str] = set()
        self._enabled: bool = True

        self._stats: dict = self._load_stats()
        self._custom_templates: dict[str, str] = self._load_templates()

        self.llm_engine = None
        self.analyzer = None

        if use_ollama:
            if HAS_LLM_ENGINE:
                try:
                    self.llm_engine = LLMEngine()
                    debug("ChatAutomation initialized with LLMEngine")
                except Exception as exc:
                    log_error("Failed to initialize LLMEngine", error=str(exc))
                    self.llm_engine = None

            if self.llm_engine is None and HAS_OLLAMA:
                try:
                    self.analyzer = LauraOllamaAnalyzer(model=os.getenv("LAURA_LLM_MODEL", "tinyllama"))
                    debug("ChatAutomation initialized with Ollama")
                except Exception as exc:
                    log_error("Failed to initialize Ollama analyzer", error=str(exc))

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #

    def _stats_path(self) -> Path:
        return self.reports_dir / "chat_stats.json"

    def _templates_path(self) -> Path:
        return self.reports_dir / "chat_templates.json"

    def _load_stats(self) -> dict:
        path = self._stats_path()
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "total_classified": 0,
            "total_responded": 0,
            "total_errors": 0,
            "by_intent": {},
            "successful_responses": 0,
            "failed_responses": 0,
            "started_at": datetime.now(UTC).isoformat(),
        }

    def _save_stats(self) -> None:
        try:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            with open(self._stats_path(), "w", encoding="utf-8") as f:
                json.dump(self._stats, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log_error("Failed to save chat stats", error=str(exc))

    def _load_templates(self) -> dict[str, str]:
        path = self._templates_path()
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_templates(self) -> None:
        try:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            with open(self._templates_path(), "w", encoding="utf-8") as f:
                json.dump(self._custom_templates, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log_error("Failed to save chat templates", error=str(exc))

    def _get_response_for_intent(self, intent: str) -> str:
        if intent in self._custom_templates:
            return self._custom_templates[intent]
        return PREDEFINED_RESPONSES.get(intent, "")

    # ------------------------------------------------------------------ #
    # LLM classification
    # ------------------------------------------------------------------ #

    def _classify_message_with_ollama(self, message: str) -> ChatResponse:
        if self.llm_engine:
            try:
                context = {"message": message, "intents": list(PREDEFINED_RESPONSES.keys())}
                result = self.llm_engine.analyze(
                    prompt_type="general_agent",
                    context=context,
                )
                if result.get("success", True) and not result.get("error"):
                    intent = str(result.get("intent", "outro")).strip().lower()
                    confidence = float(result.get("confidence", 0.5))
                    if intent not in PREDEFINED_RESPONSES:
                        intent = "outro"
                    should_respond = confidence >= 0.6 and intent != "outro"
                    response_text = self._get_response_for_intent(intent)
                    return ChatResponse(
                        classified_intent=intent,
                        confidence=confidence,
                        should_respond=should_respond,
                        response_text=response_text,
                        reason=f"LLMEngine classification (confidence={confidence:.2f})",
                    )
            except Exception as exc:
                log_error("LLMEngine classification failed", error=str(exc))

        if self.analyzer:
            try:
                metrics = {"message": message}
                result = self.analyzer.analyze(
                    metrics=metrics,
                    prompt_type="general_agent",
                    max_tokens=100,
                    fallback_on_error=True,
                )
                raw_text = result.get("raw_response", "")
                try:
                    import json as json_module
                    json_start = raw_text.find("{")
                    json_end = raw_text.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = raw_text[json_start:json_end]
                        parsed = json_module.loads(json_str)
                        intent = parsed.get("intent", "outro").strip().lower()
                        confidence = float(parsed.get("confidence", 0.5))
                        if intent not in PREDEFINED_RESPONSES:
                            intent = "outro"
                        should_respond = confidence >= 0.6 and intent != "outro"
                        response_text = self._get_response_for_intent(intent)
                        return ChatResponse(
                            classified_intent=intent,
                            confidence=confidence,
                            should_respond=should_respond,
                            response_text=response_text,
                            reason=f"Ollama classification (confidence={confidence:.2f})",
                        )
                except Exception as e:
                    debug("Failed to parse Ollama JSON response", error=str(e), raw=raw_text[:200])
            except Exception as exc:
                log_error("Ollama classification failed", error=str(exc))

        return self._classify_message_heuristic(message)

    def _classify_message_heuristic(self, message: str) -> ChatResponse:
        """Classificação heurística (fallback sem LLM)"""
        msg_lower = message.lower()

        if any(w in msg_lower for w in ["rastreamento", "rastrear", "tracking", "onde", "chegou", "entrega", "caixa postal", "sedex"]):
            return ChatResponse(
                classified_intent="rastreamento",
                confidence=0.85,
                should_respond=True,
                response_text=self._get_response_for_intent("rastreamento"),
                reason="Heuristic: rastreamento keywords detected",
            )

        if any(w in msg_lower for w in ["quanto tempo", "prazo", "demora", "quando", "tempo de entrega", "dias", "semana", "mês"]):
            return ChatResponse(
                classified_intent="prazo",
                confidence=0.85,
                should_respond=True,
                response_text=self._get_response_for_intent("prazo"),
                reason="Heuristic: tempo/prazo keywords detected",
            )

        if any(w in msg_lower for w in ["cancelar", "devolver", "reembolso", "reaver", "devolução", "refund", "cancel"]):
            return ChatResponse(
                classified_intent="cancelamento",
                confidence=0.85,
                should_respond=True,
                response_text=self._get_response_for_intent("cancelamento"),
                reason="Heuristic: cancelamento keywords detected",
            )

        if any(w in msg_lower for w in ["tamanho", "cor", "material", "especificação", "voltagem", "compatível", "garante", "garantia"]):
            return ChatResponse(
                classified_intent="produto_info",
                confidence=0.8,
                should_respond=True,
                response_text=self._get_response_for_intent("produto_info"),
                reason="Heuristic: product question keywords detected",
            )

        if len(msg_lower) < 5:
            return ChatResponse(
                classified_intent="outro",
                confidence=0.5,
                should_respond=False,
                response_text="",
                reason="Heuristic: message too short",
            )

        return ChatResponse(
            classified_intent="outro",
            confidence=0.5,
            should_respond=False,
            response_text="",
            reason="Heuristic: no keywords matched",
        )

    # ------------------------------------------------------------------ #
    # Image analysis
    # ------------------------------------------------------------------ #

    def analisar_imagem_reclamacao(
        self, imagem_path: str, descricao_produto: str, variacao: str = ""
    ) -> str:
        try:
            resultado = analisar_reclamacao(imagem_path, descricao_produto, variacao)
            corresponde = resultado.get("corresponde", "nao_analisado")
            analise = resultado.get("analise", "")
            precisa = resultado.get("precisa_atencao", False)

            if corresponde == "sim" and not precisa:
                analise_texto = "o produto na foto parece estar correto."
                orientacao = (
                    "Verifique se escolheu a variacao certa no anuncio. "
                    "Se precisar de ajuda, me mande mais detalhes!"
                )
            elif precisa:
                analise_texto = f"identifiquei possivel problema: {analise[:200]}"
                orientacao = (
                    "Sinto muito pelo transtorno! Vou encaminhar para "
                    "nosso time de suporte resolver o mais rapido possivel."
                )
            else:
                analise_texto = f"analisei a foto: {analise[:200]}"
                orientacao = (
                    "Vou verificar com nosso estoque e retorno em breve!"
                )

            return RECLAMACAO_TEMPLATE.format(analise=analise_texto, orientacao=orientacao)

        except Exception as e:
            log_error("Erro ao analisar imagem", error=str(e))
            return (
                "Recebemos sua foto! 📸\n\n"
                "Vou analisar e retorno em breve com uma solucao."
            )

    # ------------------------------------------------------------------ #
    # Core classification & response
    # ------------------------------------------------------------------ #

    def classify_and_respond(
        self,
        conversation_id: str,
        buyer_id: str,
        message_text: str,
        imagem_path: str = "",
        descricao_produto: str = "",
        variacao_produto: str = "",
    ) -> ChatResponse:
        """
        Classifica mensagem e envia resposta automática se apropriado.

        Args:
            conversation_id: ID da conversa
            buyer_id: ID do comprador
            message_text: Texto da mensagem
            imagem_path: Caminho para imagem enviada pelo cliente
            descricao_produto: Descricao do produto comprado
            variacao_produto: Variacao escolhida

        Returns:
            ChatResponse com classificação, confiança e ação tomada
        """
        self._stats["total_classified"] += 1
        intent_count = self._stats["by_intent"]
        now = time.time()

        if not self._enabled:
            return ChatResponse(
                classified_intent="outro",
                confidence=0.0,
                should_respond=False,
                response_text="",
                reason="Auto-responder disabled",
            )

        # Rate limit por comprador
        if buyer_id in self._last_response:
            elapsed = (now - self._last_response[buyer_id]) / 60
            if elapsed < self.cooldown_minutes:
                debug(
                    "Skipping auto-response (cooldown)",
                    buyer_id=buyer_id,
                    elapsed_minutes=round(elapsed, 1),
                    cooldown_minutes=self.cooldown_minutes,
                )
                return ChatResponse(
                    classified_intent="outro",
                    confidence=0.0,
                    should_respond=False,
                    response_text="",
                    reason=f"Cooldown de {self.cooldown_minutes}min para este comprador",
                )

        # Rate limit global por hora
        cutoff = now - 3600
        self._response_timestamps = [t for t in self._response_timestamps if t > cutoff]
        if len(self._response_timestamps) >= self.max_responses_per_hour:
            warning(
                "Rate limit global atingido",
                max_per_hour=self.max_responses_per_hour,
            )
            return ChatResponse(
                classified_intent="outro",
                confidence=0.0,
                should_respond=False,
                response_text="",
                reason=f"Limite de {self.max_responses_per_hour} respostas/hora atingido",
            )

        # Classificar
        classification = (
            self._classify_message_with_ollama(message_text)
            if self.use_ollama and (self.llm_engine or self.analyzer)
            else self._classify_message_heuristic(message_text)
        )

        # Track intent
        intent_count[classification.classified_intent] = intent_count.get(classification.classified_intent, 0) + 1

        # Se tem imagem e a intencao parece ser reclamacao, usa OCR
        if imagem_path and classification.classified_intent in ("reclamacao", "cancelamento", "outro"):
            if any(w in message_text.lower() for w in ["errado", "trocado", "diferente", "defeito", "quebrou", "avariado", "rasgado", "foto", "olha", "veja"]):
                response_text = self.analisar_imagem_reclamacao(
                    imagem_path, descricao_produto, variacao_produto
                )
                classification.response_text = response_text
                classification.classified_intent = "reclamacao"
                classification.should_respond = True
                classification.confidence = 0.9
                classification.reason = "OCR + image analysis applied"

        # Se deve responder, enviar mensagem ou enfileirar para revisao
        if classification.should_respond and classification.response_text:
            if self.human_approval:
                pending_file = self.reports_dir / "chat_pending_responses.jsonl"
                pending_entry = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "conversation_id": conversation_id,
                    "buyer_id": buyer_id,
                    "message": message_text[:200],
                    "intent": classification.classified_intent,
                    "confidence": classification.confidence,
                    "suggested_response": classification.response_text,
                    "status": "pending",
                }
                try:
                    self.reports_dir.mkdir(parents=True, exist_ok=True)
                    with open(pending_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(pending_entry, ensure_ascii=False) + "\n")
                except Exception as e:
                    log_error("Failed to queue chat response", error=str(e))
                classification.reason = "Queued for human approval"
                self._save_stats()
                return classification

            try:
                dedup_key = f"{conversation_id}:{message_text[:100]}"
                if dedup_key in self._responded_messages:
                    debug("Skipping duplicate response", conversation_id=conversation_id)
                    self._save_stats()
                    return classification
                self._responded_messages.add(dedup_key)
                if len(self._responded_messages) > 1000:
                    self._responded_messages = set(list(self._responded_messages)[-500:])

                resp = self.client.send_chat_message(
                    access_token=self.access_token,
                    shop_id=self.shop_id,
                    buyer_id=buyer_id,
                    message=classification.response_text,
                )

                if resp.status_code == 200:
                    self._last_response[buyer_id] = time.time()
                    self._response_timestamps.append(time.time())
                    self._stats["total_responded"] += 1
                    self._stats["successful_responses"] += 1
                    info(
                        "Auto-response sent",
                        conversation_id=conversation_id,
                        buyer_id=buyer_id,
                        intent=classification.classified_intent,
                        confidence=classification.confidence,
                    )
                    self._log_response(
                        conversation_id,
                        buyer_id,
                        message_text,
                        classification,
                        success=True,
                    )
                else:
                    self._stats["failed_responses"] += 1
                    warning(
                        "Failed to send auto-response",
                        status_code=resp.status_code,
                        error=resp.data,
                    )
                    self._log_response(
                        conversation_id,
                        buyer_id,
                        message_text,
                        classification,
                        success=False,
                    )
            except Exception as exc:
                self._stats["total_errors"] += 1
                self._stats["failed_responses"] += 1
                log_error("Error sending auto-response", error=str(exc))
                self._log_response(
                    conversation_id,
                    buyer_id,
                    message_text,
                    classification,
                    success=False,
                )
        else:
            debug(
                "Skipping auto-response",
                reason=classification.reason,
                confidence=classification.confidence,
            )
            self._log_response(
                conversation_id,
                buyer_id,
                message_text,
                classification,
                success=None,
            )

        self._save_stats()
        return classification

    # ------------------------------------------------------------------ #
    # New public methods
    # ------------------------------------------------------------------ #

    def respond_to_message(self, conversation_id: str, message_text: str, buyer_id: str = "") -> ChatResponse:
        """Classify and respond to a single chat message."""
        if not buyer_id:
            buyer_id = conversation_id
        return self.classify_and_respond(
            conversation_id=conversation_id,
            buyer_id=buyer_id,
            message_text=message_text,
        )

    def get_conversation_history(self, conversation_id: str) -> list[dict]:
        """Get recent messages from a conversation from Shopee API."""
        if not self.client or not self.access_token or self.shop_id is None:
            debug("ChatAutomation: client/credentials not available for history")
            return []
        try:
            resp = self.client.get_chat_history(
                access_token=self.access_token,
                shop_id=self.shop_id,
                conversation_id=conversation_id,
                page_size=50,
            )
            body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            messages = body.get("messages", []) if isinstance(body, dict) else []
            return messages if isinstance(messages, list) else []
        except Exception as exc:
            log_error("Failed to fetch conversation history", conversation_id=conversation_id, error=str(exc))
            return []

    def send_reply(self, conversation_id: str, text: str) -> bool:
        """Send a reply to a conversation via Shopee API."""
        if not self.client or not self.access_token or self.shop_id is None:
            debug("ChatAutomation: client/credentials not available for send_reply")
            return False
        try:
            # Extract buyer_id from conversation_id (or use as-is if it's already a buyer_id)
            buyer_id = conversation_id
            resp = self.client.send_chat_message(
                access_token=self.access_token,
                shop_id=self.shop_id,
                buyer_id=buyer_id,
                message=text,
            )
            success = resp.status_code == 200
            if success:
                self._stats["total_responded"] += 1
                self._stats["successful_responses"] += 1
                self._save_stats()
                info("Reply sent", conversation_id=conversation_id)
            else:
                warning("Failed to send reply", conversation_id=conversation_id, status_code=resp.status_code)
            return success
        except Exception as exc:
            self._stats["total_errors"] += 1
            self._stats["failed_responses"] += 1
            self._save_stats()
            log_error("Error sending reply", conversation_id=conversation_id, error=str(exc))
            return False

    def process_pending_messages(self, max_messages: int = 20) -> list[ChatResponse]:
        """Process all unread messages from Shopee chat API."""
        results: list[ChatResponse] = []
        conversations = _get_unread_conversations(self, max_age_minutes=30)
        if not conversations:
            debug("ChatAutomation: no pending messages to process")
            return results

        count = 0
        for conv_id, buyer_id, msg_text in conversations:
            if count >= max_messages:
                break
            if not msg_text.strip():
                continue

            result = self.classify_and_respond(
                conversation_id=conv_id,
                buyer_id=buyer_id,
                message_text=msg_text,
            )
            results.append(result)
            count += 1

        info(
            "Pending messages processed",
            processed=len(results),
            max_messages=max_messages,
        )
        return results

    def get_stats(self) -> dict:
        """Get auto-responder statistics (total, by intent, success rate)."""
        stats = dict(self._stats)
        stats.get("total_classified", 0)
        responded = stats.get("successful_responses", 0)
        failed = stats.get("failed_responses", 0)
        stats["success_rate"] = (responded / (responded + failed) * 100) if (responded + failed) > 0 else 0.0
        stats["auto_response_enabled"] = self._enabled
        stats["cooldown_minutes"] = self.cooldown_minutes
        stats["max_responses_per_hour"] = self.max_responses_per_hour
        stats["human_approval"] = self.human_approval
        stats["custom_templates_count"] = len(self._custom_templates)
        return stats

    def set_auto_response(self, enabled: bool) -> None:
        """Enable or disable auto-responding."""
        self._enabled = enabled
        info("Auto-response toggled", enabled=enabled)

    def add_response_template(self, intent: str, template: str) -> None:
        """Add a custom response template for an intent."""
        if intent not in PREDEFINED_RESPONSES and intent != "outro":
            raise ValueError(f"Invalid intent '{intent}'. Valid intents: {', '.join(PREDEFINED_RESPONSES.keys())}")
        self._custom_templates[intent] = template
        self._save_templates()
        info("Custom response template added", intent=intent)

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #

    def _log_response(
        self,
        conversation_id: str,
        buyer_id: str,
        original_message: str,
        classification: ChatResponse,
        success: bool | None,
    ) -> None:
        """Registra tentativa de resposta automática em log"""
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.reports_dir / "laura_chat_auto_log.jsonl"

        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "conversation_id": conversation_id,
            "buyer_id": buyer_id,
            "original_message": original_message[:500],
            "classified_intent": classification.classified_intent,
            "confidence": classification.confidence,
            "should_respond": classification.should_respond,
            "response_sent": success,
            "reason": classification.reason,
        }

        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            log_error("Failed to write chat auto log", error=str(exc))


# ------------------------------------------------------------------ #
# Module-level helpers
# ------------------------------------------------------------------ #

def _get_unread_conversations(
    chat_auto: ChatAutomation,
    max_age_minutes: int = 30,
) -> list[tuple[str, str, str]]:
    """Busca conversas com mensagens recentes não respondidas.

    Returns:
        Lista de (conversation_id, buyer_id, latest_message)
    """
    if not chat_auto.client or not chat_auto.access_token or chat_auto.shop_id is None:
        debug("ChatAutomation: client/credentials not available")
        return []

    try:
        resp = chat_auto.client.get_conversation_list(
            access_token=chat_auto.access_token,
            shop_id=chat_auto.shop_id,
            page_size=20,
        )
        body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
        conversations = body.get("conversation_list", []) if isinstance(body, dict) else []
        if not isinstance(conversations, list):
            return []

        now_ts = int(datetime.now(UTC).timestamp())
        cutoff = now_ts - (max_age_minutes * 60)
        results: list[tuple[str, str, str]] = []

        for conv in conversations:
            conv_id = conv.get("conversation_id", "")
            buyer_id = conv.get("buyer_id", "")
            if not conv_id or not buyer_id:
                continue

            latest = conv.get("latest_message") or {}
            msg_text = latest.get("message", "") if isinstance(latest, dict) else ""
            msg_ts = latest.get("timestamp", 0) if isinstance(latest, dict) else 0

            if msg_ts < cutoff:
                continue

            results.append((conv_id, buyer_id, msg_text))

        debug(f"ChatAutomation: found {len(results)} recent conversations")
        return results

    except Exception as exc:
        log_error("ChatAutomation: failed to fetch conversations", error=str(exc))
        return []


def integrate_chat_automation_to_loop(
    loop,
    chat_auto: ChatAutomation | None = None,
) -> None:
    """
    Integra automação de chat ao loop autônomo.

    Busca mensagens não respondidas, classifica e responde automaticamente.
    """
    if not chat_auto:
        return

    conversations = _get_unread_conversations(chat_auto, max_age_minutes=30)
    if not conversations:
        debug("ChatAutomation: no recent conversations to process")
        return

    responded = 0
    skipped = 0
    for conv_id, buyer_id, msg_text in conversations:
        if not msg_text.strip():
            skipped += 1
            continue

        result = chat_auto.classify_and_respond(
            conversation_id=conv_id,
            buyer_id=buyer_id,
            message_text=msg_text,
        )

        if result.should_respond and result.response_text:
            responded += 1
        else:
            skipped += 1

    info(
        "Chat automation cycle complete",
        conversations_found=len(conversations),
        responded=responded,
        skipped=skipped,
    )


# ------------------------------------------------------------------ #
# CLI parser
# ------------------------------------------------------------------ #

def build_parser(subparsers) -> None:
    """Build CLI subparsers for chat automation commands."""
    chat_parser = subparsers.add_parser("chat", help="Chat automation commands")
    chat_subparsers = chat_parser.add_subparsers(dest="chat_command", required=True)

    # chat auto
    auto_parser = chat_subparsers.add_parser("auto", help="Toggle auto-responder")
    auto_parser.add_argument("--enable", action="store_true", help="Enable auto-responder")
    auto_parser.add_argument("--disable", action="store_true", help="Disable auto-responder")

    # chat respond
    respond_parser = chat_subparsers.add_parser("respond", help="Classify and respond to a message")
    respond_parser.add_argument("conversation_id", help="Conversation ID")
    respond_parser.add_argument("message", help="Message text")
    respond_parser.add_argument("--buyer-id", default="", help="Buyer ID")

    # chat process
    process_parser = chat_subparsers.add_parser("process", help="Process all pending messages")
    process_parser.add_argument("--max", type=int, default=20, help="Max messages to process")

    # chat stats
    chat_subparsers.add_parser("stats", help="Show auto-responder statistics")

    # chat history
    history_parser = chat_subparsers.add_parser("history", help="Show conversation history")
    history_parser.add_argument("conversation_id", help="Conversation ID")

    # chat template
    template_parser = chat_subparsers.add_parser("template", help="Manage response templates")
    template_subparsers = template_parser.add_subparsers(dest="template_command", required=True)
    template_add_parser = template_subparsers.add_parser("add", help="Add a response template")
    template_add_parser.add_argument("intent", help="Intent name")
    template_add_parser.add_argument("template", help="Response template text")
    template_subparsers.add_parser("list", help="List all templates")


def handle_chat_command(args, automation: ChatAutomation | None = None) -> None:
    """Handle parsed chat CLI command."""
    if automation is None:
        automation = ChatAutomation()

    cmd = args.chat_command

    if cmd == "auto":
        if args.enable:
            automation.set_auto_response(True)
            print("Auto-responder enabled")
        elif args.disable:
            automation.set_auto_response(False)
            print("Auto-responder disabled")
        else:
            stats = automation.get_stats()
            enabled = stats.get("auto_response_enabled", True)
            print(f"Auto-responder is {'enabled' if enabled else 'disabled'}")

    elif cmd == "respond":
        result = automation.respond_to_message(
            conversation_id=args.conversation_id,
            message_text=args.message,
            buyer_id=args.buyer_id,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))

    elif cmd == "process":
        results = automation.process_pending_messages(max_messages=args.max)
        print(f"Processed {len(results)} messages:")
        for r in results:
            print(f"  [{r.classified_intent}] (conf={r.confidence:.2f}) respond={r.should_respond}: {r.reason}")

    elif cmd == "stats":
        stats = automation.get_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    elif cmd == "history":
        messages = automation.get_conversation_history(args.conversation_id)
        if not messages:
            print("No messages found or unable to fetch history.")
        else:
            print(json.dumps(messages, ensure_ascii=False, indent=2))

    elif cmd == "template":
        if args.template_command == "add":
            try:
                automation.add_response_template(args.intent, args.template)
                print(f"Template added for intent '{args.intent}'")
            except ValueError as e:
                print(f"Error: {e}")
        elif args.template_command == "list":
            templates = dict(PREDEFINED_RESPONSES)
            templates.update(automation._custom_templates)
            for intent, text in templates.items():
                preview = text[:80].replace("\n", " ") + ("..." if len(text) > 80 else "")
                custom_mark = " (custom)" if intent in automation._custom_templates else ""
                print(f"  {intent}:{custom_mark} {preview}")


# ------------------------------------------------------------------ #
# Main entry point
# ------------------------------------------------------------------ #

def main() -> None:
    parser = argparse.ArgumentParser(description="Shopee Chat Automation")
    subparsers = parser.add_subparsers(dest="command")
    build_parser(subparsers)

    args = parser.parse_args()
    if hasattr(args, "chat_command"):
        handle_chat_command(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
