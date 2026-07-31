"""Auto Support skill — auto-responds to simple buyer messages."""

from __future__ import annotations

from .registry import Skill, default_registry


class AutoSupportSkill(Skill):
    name = "auto_support"
    risk_level = "LOW"
    preconditions = {}
    effects = {"support_handled": True}
    cost = 0.5
    priority = 0

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    RESPONSES = {
        "rastreamento": "Seu pedido foi enviado! O prazo de entrega é de até 10 dias úteis.",
        "prazo": "O prazo de entrega é de até 10 dias úteis após a postagem.",
        "cancelamento": "Para cancelar, acesse Meus Pedidos > Cancelar. Se já passou do prazo, me avise que eu ajudo!",
        "troca": "Para troca, entre em contato conosco pelo chat que resolvemos rapidinho.",
        "devolucao": "Você pode solicitar a devolução em Meus Pedidos > Devolver. Estamos aqui para ajudar!",
    }

    def run(self, message: str = "", buyer_id: str = "", **kwargs) -> dict:
        """Classify message and return auto-response if possible."""
        msg_lower = message.lower()
        for keyword, reply in self.RESPONSES.items():
            if keyword in msg_lower:
                return {
                    "buyer_id": buyer_id,
                    "classified_as": keyword,
                    "response": reply,
                    "auto_replied": True,
                }
        return {
            "buyer_id": buyer_id,
            "classified_as": "unknown",
            "response": "",
            "auto_replied": False,
        }


default_registry.register(AutoSupportSkill)
