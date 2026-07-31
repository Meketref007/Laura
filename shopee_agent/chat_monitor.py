"""
Monitor de chat da plataforma Shopee.

Polling periodico de mensagens nao lidas + integracao com
o sistema de workers para notificar no canal viluhshop.
"""

from __future__ import annotations

import os
import threading
import time

from shopee_agent.logger import error as log_error
from shopee_agent.logger import info, warning
from shopee_agent.paths import CHAT_IMAGES_DIR, CHAT_LAST_CHECK
from shopee_agent.vilu_workers import (
    chat_auto_respondida,
    chat_nova_mensagem,
    chat_precisa_ajuda,
)

POLL_INTERVAL = int(os.getenv("VILU_CHAT_POLL_INTERVAL", "120"))  # segundos
LAST_CHECK_FILE = str(CHAT_LAST_CHECK)


class ChatMonitor:
    """Monitora mensagens de chat nao lidas na Shopee."""

    def __init__(
        self,
        client,
        access_token: str,
        shop_id: int,
        auto_reply: bool = True,
        seller_center_client=None,
    ):
        self._client = client
        self._access_token = access_token
        self._shop_id = shop_id
        self._auto_reply = auto_reply
        self._seller_center = seller_center_client
        self._running = False
        self._thread: threading.Thread | None = None
        self._chat_auto = None
        self._last_check = self._load_last_check()

        if auto_reply:
            try:
                from shopee_agent.chat_auto import ChatAutomation
                self._chat_auto = ChatAutomation(client, access_token, shop_id)
            except Exception as e:
                warning(f"ChatAutomation nao disponivel: {e}")

    def _load_last_check(self) -> float:
        try:
            with open(LAST_CHECK_FILE) as f:
                return float(f.read().strip())
        except Exception:
            return time.time() - 3600

    def _save_last_check(self, ts: float) -> None:
        try:
            with open(LAST_CHECK_FILE, "w") as f:
                f.write(str(ts))
        except Exception:
            pass

    def _normalize_conversation(self, conv: dict) -> list[dict]:
        """Normaliza uma conversa do Seller Center em lista de mensagens."""
        messages = []
        buyer_name = (conv.get("buyer_name") or conv.get("user_name") or
                      conv.get("nickname", "") or "Cliente")
        buyer_id = (conv.get("buyer_id") or conv.get("user_id") or
                    conv.get("buyer_user_id", "") or "")
        conversation_id = (conv.get("conversation_id") or conv.get("id") or
                           conv.get("chat_id", "") or str(conv.get("shop_id", "")))

        raw_msgs = conv.get("messages", []) or conv.get("message_list", [])
        if raw_msgs:
            for m in raw_msgs:
                if isinstance(m, dict):
                    m["buyer_name"] = buyer_name
                    m["buyer_id"] = buyer_id
                    m["conversation_id"] = conversation_id
                    messages.append(m)
        else:
            msg_text = (conv.get("message") or conv.get("text") or
                        conv.get("last_message") or conv.get("content", ""))
            if msg_text or conv.get("image_url") or conv.get("image"):
                messages.append({
                    "buyer_name": buyer_name,
                    "buyer_id": buyer_id,
                    "conversation_id": conversation_id,
                    "message": msg_text,
                    "text": msg_text,
                    "content": msg_text,
                    "timestamp": (conv.get("timestamp") or conv.get("create_time") or
                                  conv.get("mtime", 0)),
                    "image_url": conv.get("image_url", "") or conv.get("image", ""),
                })
        return messages

    def _fetch_recent_conversations(self) -> list:
        """Busca conversas recentes via SellerCenterClient (fallback: ShopeeClient)."""
        # Try SellerCenterClient first (cookie-based, more reliable)
        if self._seller_center is not None:
            try:
                return self._fetch_via_seller_center()
            except Exception as e:
                log_error(f"SellerCenter chat fetch failed: {e}")

        # Fallback: try ShopeeClient Open API
        try:
            return self._fetch_via_open_api()
        except Exception:
            pass
        return []

    def _fetch_via_seller_center(self) -> list:
        """Busca conversas usando SellerCenterClient (cookies do navegador)."""
        conversations = []

        # Try get_chat_conversations first
        try:
            data = self._seller_center.get_chat_conversations()
            if data:
                for item in data:
                    convs = item if isinstance(item, list) else data
                    for c in convs if isinstance(convs, list) else [convs]:
                        conversations.extend(self._normalize_conversation(
                            c if isinstance(c, dict) else {}
                        ))
                if conversations:
                    info(f"SellerCenter: {len(conversations)} mensagens de chat_conversations")
                    return conversations
        except Exception:
            pass

        # Fallback to get_chat_management
        try:
            data = self._seller_center.get_chat_management(page=1, limit=20)
            if data:
                items = data if isinstance(data, list) else data.get("list", []) or data.get("data", [])
                for item in items:
                    conversations.extend(self._normalize_conversation(
                        item if isinstance(item, dict) else {}
                    ))
                info(f"SellerCenter: {len(conversations)} mensagens de chat_management")
        except Exception as e:
            log_error(f"SellerCenter chat_management failed: {e}")

        return conversations

    def _fetch_via_open_api(self) -> list:
        """Fallback: busca conversas usando ShopeeClient Open API."""
        try:
            conv_resp = self._client.get_conversation_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
                page_size=20,
            )
        except AttributeError:
            conv_resp = None

        conversations = []
        if conv_resp and hasattr(conv_resp, "data"):
            data = conv_resp.data if isinstance(conv_resp.data, dict) else {}
            conv_list = data.get("conversations", []) or data.get("list", []) or []
            for conv in conv_list[:10]:
                conv_id = conv.get("conversation_id") or conv.get("id")
                if not conv_id:
                    continue
                try:
                    hist = self._client.get_chat_history(
                        access_token=self._access_token,
                        shop_id=self._shop_id,
                        conversation_id=conv_id,
                        page_size=5,
                    )
                    if hist and hasattr(hist, "data"):
                        hist_data = hist.data if isinstance(hist.data, dict) else {}
                        msgs = hist_data.get("messages", []) or []
                        for m in msgs:
                            m["buyer_name"] = conv.get("buyer_name", "") or conv.get("user_name", "")
                            m["buyer_id"] = conv.get("buyer_id", "") or conv.get("user_id", "")
                        conversations.extend(msgs)
                except Exception:
                    continue
        return conversations

    def check_new_messages(self) -> int:
        """Verifica se ha mensagens novas. Retorna quantas foram processadas."""
        count = 0
        conversations = self._fetch_recent_conversations()
        if not conversations:
            return 0

        now = time.time()
        for conv in conversations:
            try:
                msg_time = conv.get("timestamp", 0) or conv.get("create_time", 0)
                if isinstance(msg_time, str):
                    try:
                        from datetime import datetime
                        msg_time = datetime.fromisoformat(msg_time.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        msg_time = 0

                if msg_time <= self._last_check:
                    continue

                buyer_name = conv.get("buyer_name", "") or conv.get("user_name", "") or "Cliente"
                message_text = conv.get("message", "") or conv.get("text", "") or conv.get("content", "")
                conversation_id = conv.get("conversation_id", "") or conv.get("id", "")
                buyer_id = conv.get("buyer_id", "") or conv.get("user_id", "")
                imagem_url = conv.get("image_url", "") or conv.get("image", "") or conv.get("img", "")

                if not message_text and not imagem_url:
                    continue

                intent = ""
                imagem_path = ""
                descricao_produto = ""
                variacao_produto = ""

                if imagem_url:
                    try:
                        import requests as req
                        img_dir = CHAT_IMAGES_DIR
                        img_dir.mkdir(parents=True, exist_ok=True)
                        img_name = f"{conversation_id}_{int(time.time())}.jpg"
                        img_local = str(img_dir / img_name)
                        r = req.get(imagem_url, timeout=30)
                        if r.status_code == 200:
                            with open(img_local, "wb") as f:
                                f.write(r.content)
                            imagem_path = img_local
                    except Exception:
                        pass

                if self._chat_auto and self._auto_reply:
                    try:
                        response = self._chat_auto.classify_and_respond(
                            conversation_id=conversation_id,
                            buyer_id=buyer_id,
                            message_text=message_text,
                            imagem_path=imagem_path,
                            descricao_produto=descricao_produto,
                            variacao_produto=variacao_produto,
                        )
                        if response and response.should_respond:
                            chat_auto_respondida(buyer_name, response.classified_intent, response.confidence)
                            intent = response.classified_intent
                        elif response and response.classified_intent != "outro":
                            chat_precisa_ajuda(buyer_name, response.classified_intent)
                        else:
                            intent = response.classified_intent if response else ""
                    except Exception:
                        chat_precisa_ajuda(buyer_name, "nao classificado")

                preview = message_text[:200] if message_text else ""
                if imagem_path:
                    preview += " [foto enviada]"
                chat_nova_mensagem(buyer_name, preview, intent)
                count += 1

            except Exception:
                continue

        self._last_check = now
        self._save_last_check(now)
        return count

    def _loop(self) -> None:
        info(f"ChatMonitor iniciado (intervalo: {POLL_INTERVAL}s)")
        while self._running:
            try:
                count = self.check_new_messages()
                if count > 0:
                    info(f"ChatMonitor: {count} nova(s) mensagem(ns) processada(s)")
            except Exception as e:
                log_error(f"ChatMonitor error: {e}")
            for _ in range(POLL_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        info("ChatMonitor iniciado")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
