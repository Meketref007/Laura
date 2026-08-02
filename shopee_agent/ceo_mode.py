"""Modo CEO (LAURA_CEO_MODE=1): autonomia total da Laura.

Quando ativo, a Laura executa decisoes e acoes sem aprovacao humana:
- Auto-aprova e executa decisoes geradas pelo decision engine
- Executa skills de alta prioridade (HIGH/CRITICAL) sem intervencao
- Aprova envio de pedidos prontos automaticamente
- Envia respostas de chat sem aprovacao manual (chat_auto)

Desativado por padrao: toda acao requer aprovacao humana explicita.
"""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on", "sim", "ativado"}


def ceo_mode_enabled() -> bool:
    """True se LAURA_CEO_MODE estiver ativo (1/true/yes/on)."""
    raw = os.getenv("LAURA_CEO_MODE", "0")
    return str(raw).strip().lower() in _TRUTHY
