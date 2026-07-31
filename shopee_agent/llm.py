"""
Integração com Claude 3.5 Sonnet via Anthropic API.

Este módulo fornece abstração limpa para comunicação com Claude,
incluindo cache de prompts, tratamento de erros, e logging.
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import anthropic

from .prompts import get_system_prompt

# GUARD: Prevent accidental use of paid LLM API without explicit opt-in
_allow_paid_llm = os.getenv("LAURA_ALLOW_PAID_LLM", "0")
if _allow_paid_llm != "1":
    raise RuntimeError(
        "llm.py uses Anthropic Claude API (PAID). "
        "To use free LLM, use llm_local.py (Ollama) instead. "
        "To explicitly enable paid API, set LAURA_ALLOW_PAID_LLM=1 in .env"
    )


@dataclass
class LLMAnalysisResult:
    """Resultado de uma análise via LLM."""

    decision: str
    action: str
    priority: str
    mode: str
    metrics: dict[str, float]
    reasoning: str
    next_steps: str
    confidence: float
    timestamp: str
    raw_response: str
    tokens_used: int
    model: str
    prompt_type: str


class LauraLLMAnalyzer:
    """
    Analisador de profitabilidade usando Claude 3.5 Sonnet.
    
    Features:
    - Análise de profitabilidade com decisões estruturadas
    - Múltiplos tipos de análise (profitabilidade, reembolsos, oportunidades, etc)
    - Tratamento seguro de erros e respostas inválidas
    - Logging estruturado
    - Cache de prompts para reduzir custos
    """

    MODEL = "claude-3-5-sonnet-20241022"
    DEFAULT_MAX_TOKENS = 1024

    def __init__(self, api_key: str | None = None):
        """
        Inicializa o analisador LLM.
        
        Args:
            api_key: Chave da API Anthropic. Se não fornecida, tenta ler ANTHROPIC_API_KEY
        
        Raises:
            ValueError: Se nenhuma chave API for fornecida
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY não configurada. "
                "Defina a variável de ambiente ou passe api_key ao construtor."
            )

        self.client = anthropic.Anthropic(api_key=self.api_key)

    def analyze_profitability(
        self,
        metrics: dict[str, Any],
        prompt_type: str = "profitability_analyzer",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> LLMAnalysisResult:
        """
        Analisa métricas de profitabilidade usando Claude.
        
        Args:
            metrics: Dicionário com métricas:
                - revenue (R$)
                - cogs (R$)
                - ad_spend (R$)
                - shipping_subsidy (R$)
                - refunds (R$)
                - orders (int)
                - products (opcional, list)
            
            prompt_type: Tipo de análise ("profitability_analyzer", etc)
            max_tokens: Limite de tokens na resposta
        
        Returns:
            LLMAnalysisResult com decisão estruturada
        
        Raises:
            ValueError: Se métricas inválidas ou resposta não parsear
            anthropic.APIError: Se erro da API Anthropic
        """
        # Validar métricas
        required_fields = ["revenue", "cogs", "ad_spend", "shipping_subsidy", "refunds", "orders"]
        missing = [f for f in required_fields if f not in metrics]
        if missing:
            raise ValueError(f"Métricas incompletas. Faltam: {missing}")

        # Preparar prompt do sistema
        system_prompt = get_system_prompt(prompt_type)

        # Construir mensagem do usuário com métricas
        user_message = self._build_user_message(metrics, prompt_type)

        # Chamar Claude com cache de prompts para economia
        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": user_message
                }
            ]
        )

        # Extrair resposta
        raw_response = response.content[0].text

        # Parsear resultado
        result = self._parse_response(raw_response, prompt_type)

        # Enriquecer com metadata
        result.raw_response = raw_response
        result.tokens_used = response.usage.output_tokens + response.usage.input_tokens
        result.model = self.MODEL
        result.prompt_type = prompt_type
        result.timestamp = datetime.now(UTC).isoformat()

        return result

    def _build_user_message(self, metrics: dict[str, Any], prompt_type: str) -> str:
        """Constrói a mensagem do usuário formatada."""

        # Calcular métricas derivadas
        revenue = metrics.get("revenue", 0)
        cogs = metrics.get("cogs", 0)
        ad_spend = metrics.get("ad_spend", 0)
        shipping_subsidy = metrics.get("shipping_subsidy", 0)
        refunds = metrics.get("refunds", 0)
        orders = metrics.get("orders", 0)

        # Calcular percentuais
        gross_profit = revenue - cogs - ad_spend - shipping_subsidy - refunds
        margin_pct = (gross_profit / revenue * 100) if revenue > 0 else 0
        roas = (revenue / ad_spend) if ad_spend > 0 else 0
        refund_rate = (refunds / revenue * 100) if revenue > 0 else 0

        vision_context = metrics.get("vision_context", "")
        vision_section = f"""
## Análise Visual dos Produtos
{vision_context}
""" if vision_context else ""

        # Formatar dados
        metrics_summary = f"""
# Dados de Entrada

## Período
Data/hora da análise: {datetime.now(UTC).isoformat()}

## Métricas Financeiras (últimos 7 dias)
- Receita Total: R$ {revenue:,.2f}
- COGS (Custo de Bens Vendidos): R$ {cogs:,.2f}
- Gastos em Publicidade: R$ {ad_spend:,.2f}
- Subsídio de Frete: R$ {shipping_subsidy:,.2f}
- Reembolsos: R$ {refunds:,.2f}
- Lucro Bruto: R$ {gross_profit:,.2f}

## Métricas Calculadas
- Margem de Lucro: {margin_pct:.1f}%
- ROAS (Return on Ad Spend): {roas:.2f}x
- Taxa de Reembolsos: {refund_rate:.1f}%
- Volume de Pedidos: {orders} pedidos

## Dados Adicionais
{json.dumps(metrics.get("products", []), indent=2, ensure_ascii=False) if metrics.get("products") else "Sem dados de produtos detalhados"}
{vision_section}
---

# Análise Solicitada
Por favor, analise os dados acima e forneça uma decisão estruturada no formato JSON especificado.
"""

        return metrics_summary

    def _parse_response(self, raw_response: str, prompt_type: str) -> LLMAnalysisResult:
        """
        Parseia a resposta do Claude extraindo o JSON.
        
        Args:
            raw_response: Texto bruto da resposta
            prompt_type: Tipo de análise usado
        
        Returns:
            LLMAnalysisResult
        
        Raises:
            ValueError: Se não conseguir extrair JSON válido
        """
        # Tentar extrair JSON da resposta
        # Claude pode envolver o JSON em marcadores de código
        json_str = raw_response

        # Procurar por bloco de código JSON
        if "```json" in raw_response:
            start = raw_response.find("```json") + len("```json")
            end = raw_response.find("```", start)
            if end > start:
                json_str = raw_response[start:end].strip()
        elif "```" in raw_response:
            start = raw_response.find("```") + len("```")
            end = raw_response.find("```", start)
            if end > start:
                json_str = raw_response[start:end].strip()

        # Parsear JSON
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Falha ao parsear resposta JSON: {e}\nResposta: {json_str[:500]}")

        # Validar campos obrigatórios
        required_fields = ["decision", "action", "priority", "mode", "metrics", "reasoning", "next_steps", "confidence"]
        missing = [f for f in required_fields if f not in data]
        if missing:
            raise ValueError(f"Resposta incompleta. Faltam campos: {missing}")

        # Criar resultado
        return LLMAnalysisResult(
            decision=data.get("decision", ""),
            action=data.get("action", ""),
            priority=data.get("priority", ""),
            mode=data.get("mode", ""),
            metrics=data.get("metrics", {}),
            reasoning=data.get("reasoning", ""),
            next_steps=data.get("next_steps", ""),
            confidence=float(data.get("confidence", 0.0)),
            timestamp=data.get("timestamp", datetime.now(UTC).isoformat()),
            raw_response="",  # Será preenchido depois
            tokens_used=0,  # Será preenchido depois
            model="",  # Será preenchido depois
            prompt_type=prompt_type,
        )

    def to_dict(self, result: LLMAnalysisResult) -> dict[str, Any]:
        """Converte resultado para dicionário."""
        return asdict(result)


def create_analyzer(api_key: str | None = None) -> LauraLLMAnalyzer:
    """
    Factory para criar analisador LLM.
    
    Args:
        api_key: Chave API (opcional, default usa env var ANTHROPIC_API_KEY)
    
    Returns:
        LauraLLMAnalyzer pronto para usar
    """
    return LauraLLMAnalyzer(api_key=api_key)
