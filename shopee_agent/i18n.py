"""Internationalization for Laura dashboard and CLI messages."""

from __future__ import annotations

import os
import re
from typing import Any

# ── Built-in translations ─────────────────────────────────────────────────────

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en_US": {
        # Dashboard
        "dashboard.title": "Laura Dashboard",
        "dashboard.health": "Health",
        "dashboard.orders": "Orders",
        "dashboard.revenue": "Revenue",
        "dashboard.products": "Products",
        "dashboard.skills": "Skills",
        "dashboard.plans": "Plans",
        "dashboard.goals": "Goals",
        "dashboard.workers": "Workers",
        "dashboard.settings": "Settings",
        "dashboard.events": "Events",
        "dashboard.summary": "Summary",
        "dashboard.overview": "Overview",
        "dashboard.notifications": "Notifications",
        "dashboard.performance": "Performance",
        "dashboard.alerts": "Alerts",
        "dashboard.activity": "Activity Log",
        "dashboard.analytics": "Analytics",
        "dashboard.reports": "Reports",
        "dashboard.profitability": "Profitability",
        "dashboard.inventory": "Inventory",
        "dashboard.competitors": "Competitors",
        "dashboard.automation": "Automation",
        "dashboard.schedule": "Schedule",
        "dashboard.tasks": "Tasks",
        "dashboard.recommendations": "Recommendations",
        "dashboard.system": "System",
        "dashboard.metrics": "Metrics",
        "dashboard.charts": "Charts",
        "dashboard.export": "Export Data",
        "dashboard.last_update": "Last update",
        "dashboard.loading": "Loading dashboards...",
        "dashboard.no_data": "No data available",
        "dashboard.error_load": "Error loading dashboard data",
        "dashboard.refresh": "Refresh",
        "dashboard.time_range": "Time Range",
        "dashboard.today": "Today",
        "dashboard.week": "This Week",
        "dashboard.month": "This Month",
        "dashboard.quarter": "This Quarter",
        "dashboard.year": "This Year",
        "dashboard.custom_range": "Custom Range",
        "dashboard.dark_mode": "Dark Mode",
        "dashboard.language": "Language",
        "dashboard.logout": "Logout",
        # Common actions
        "common.save": "Save",
        "common.cancel": "Cancel",
        "common.delete": "Delete",
        "common.edit": "Edit",
        "common.search": "Search",
        "common.loading": "Loading...",
        "common.error": "Error",
        "common.success": "Success",
        "common.confirm": "Confirm",
        "common.back": "Back",
        "common.next": "Next",
        "common.close": "Close",
        "common.apply": "Apply",
        "common.reset": "Reset",
        "common.filter": "Filter",
        "common.sort": "Sort",
        "common.download": "Download",
        "common.upload": "Upload",
        "common.print": "Print",
        # Navigation
        "nav.home": "Home",
        "nav.summary": "Summary",
        "nav.plans": "Plans",
        "nav.skills": "Skills",
        "nav.goals": "Goals",
        "nav.workers": "Workers",
        "nav.settings": "Settings",
        "nav.ab_testing": "A/B Testing",
        "nav.history": "History",
        "nav.help": "Help",
        "nav.about": "About",
        "nav.profile": "Profile",
    },
    "pt_BR": {
        # Dashboard
        "dashboard.title": "Painel Laura",
        "dashboard.health": "Saúde",
        "dashboard.orders": "Pedidos",
        "dashboard.revenue": "Receita",
        "dashboard.products": "Produtos",
        "dashboard.skills": "Habilidades",
        "dashboard.plans": "Planos",
        "dashboard.goals": "Metas",
        "dashboard.workers": "Trabalhadores",
        "dashboard.settings": "Configurações",
        "dashboard.events": "Eventos",
        "dashboard.summary": "Resumo",
        "dashboard.overview": "Visão Geral",
        "dashboard.notifications": "Notificações",
        "dashboard.performance": "Desempenho",
        "dashboard.alerts": "Alertas",
        "dashboard.activity": "Registro de Atividades",
        "dashboard.analytics": "Análises",
        "dashboard.reports": "Relatórios",
        "dashboard.profitability": "Rentabilidade",
        "dashboard.inventory": "Estoque",
        "dashboard.competitors": "Concorrentes",
        "dashboard.automation": "Automação",
        "dashboard.schedule": "Agenda",
        "dashboard.tasks": "Tarefas",
        "dashboard.recommendations": "Recomendações",
        "dashboard.system": "Sistema",
        "dashboard.metrics": "Métricas",
        "dashboard.charts": "Gráficos",
        "dashboard.export": "Exportar Dados",
        "dashboard.last_update": "Última atualização",
        "dashboard.loading": "Carregando painéis...",
        "dashboard.no_data": "Nenhum dado disponível",
        "dashboard.error_load": "Erro ao carregar dados do painel",
        "dashboard.refresh": "Atualizar",
        "dashboard.time_range": "Período",
        "dashboard.today": "Hoje",
        "dashboard.week": "Esta Semana",
        "dashboard.month": "Este Mês",
        "dashboard.quarter": "Este Trimestre",
        "dashboard.year": "Este Ano",
        "dashboard.custom_range": "Período Personalizado",
        "dashboard.dark_mode": "Modo Escuro",
        "dashboard.language": "Idioma",
        "dashboard.logout": "Sair",
        # Common actions
        "common.save": "Salvar",
        "common.cancel": "Cancelar",
        "common.delete": "Excluir",
        "common.edit": "Editar",
        "common.search": "Pesquisar",
        "common.loading": "Carregando...",
        "common.error": "Erro",
        "common.success": "Sucesso",
        "common.confirm": "Confirmar",
        "common.back": "Voltar",
        "common.next": "Avançar",
        "common.close": "Fechar",
        "common.apply": "Aplicar",
        "common.reset": "Redefinir",
        "common.filter": "Filtrar",
        "common.sort": "Ordenar",
        "common.download": "Baixar",
        "common.upload": "Enviar",
        "common.print": "Imprimir",
        # Navigation
        "nav.home": "Início",
        "nav.summary": "Resumo",
        "nav.plans": "Planos",
        "nav.skills": "Habilidades",
        "nav.goals": "Metas",
        "nav.workers": "Trabalhadores",
        "nav.settings": "Configurações",
        "nav.ab_testing": "Teste A/B",
        "nav.history": "Histórico",
        "nav.help": "Ajuda",
        "nav.about": "Sobre",
        "nav.profile": "Perfil",
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────────

_INSTANCE: I18n | None = None


def _detect_locale() -> str:
    """Auto-detect locale from env var ``LAURA_LOCALE`` or system language."""
    env_locale = os.environ.get("LAURA_LOCALE", "").strip()
    if env_locale:
        return _normalize_locale(env_locale)

    # Try to detect from OS (simplified locale detection)
    lang = os.environ.get("LANG", "")
    if lang:
        locale_code = _normalize_locale(lang.split(".")[0].replace("-", "_"))
        if locale_code in _TRANSLATIONS:
            return locale_code

    # Check LC_ALL, LC_MESSAGES, LANGUAGE
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        val = os.environ.get(var, "")
        if val:
            locale_code = _normalize_locale(val.split(".")[0].replace("-", "_"))
            if locale_code in _TRANSLATIONS:
                return locale_code

    # Accept-Language header can be set as env var for server context
    accept_lang = os.environ.get("HTTP_ACCEPT_LANGUAGE", "")
    if accept_lang:
        # Parse first language tag from Accept-Language
        match = re.match(r"([a-zA-Z]{2,3}(?:[-_][a-zA-Z]{2,3})?)", accept_lang)
        if match:
            locale_code = _normalize_locale(match.group(1))
            if locale_code in _TRANSLATIONS:
                return locale_code

    return "pt_BR"


def _normalize_locale(locale: str) -> str:
    """Normalize locale string to ``xx_XX`` format."""
    parts = locale.replace("-", "_").split("_")
    if len(parts) >= 2:
        return f"{parts[0].lower()}_{parts[1].upper()}"
    if len(parts) == 1:
        lang = parts[0].lower()
        # Map common 2-letter codes to a default region
        mapping = {"en": "en_US", "pt": "pt_BR", "es": "es_ES", "fr": "fr_FR"}
        return mapping.get(lang, f"{lang}_{lang.upper()}")
    return locale


# ── I18n class ────────────────────────────────────────────────────────────────


class I18n:
    """Simple internationalization helper with plural/parameter support."""

    def __init__(self, locale: str = "pt_BR", fallback: str = "en_US") -> None:
        self._locale = locale
        self._fallback = fallback
        self._translations: dict[str, dict[str, str]] = {}
        # Copy built-in translations
        for loc, trans in _TRANSLATIONS.items():
            self._translations[loc] = dict(trans)

    def t(self, key: str, **kwargs: Any) -> str:
        """Translate *key* into the current locale.

        Falls back to *fallback* locale and then to the key itself.
        Supports ``{placeholder}`` substitution via keyword arguments.
        """
        # Try current locale
        trans = self._translations.get(self._locale, {})
        msg = trans.get(key)

        if msg is None and self._fallback != self._locale:
            # Try fallback locale
            fallback_trans = self._translations.get(self._fallback, {})
            msg = fallback_trans.get(key)

        if msg is None:
            msg = key

        if kwargs:
            try:
                msg = msg.format(**kwargs)
            except KeyError:
                pass

        return msg

    def set_locale(self, locale: str) -> None:
        """Switch the active locale at runtime."""
        normalized = _normalize_locale(locale)
        if normalized in self._translations:
            self._locale = normalized
        else:
            self._locale = locale

    def get_locale(self) -> str:
        """Return the currently active locale code."""
        return self._locale

    def add_translations(self, locale: str, translations: dict) -> None:
        """Add or override translations for a given locale."""
        if locale not in self._translations:
            self._translations[locale] = {}
        self._translations[locale].update(translations)

    def get_supported_locales(self) -> list[str]:
        """Return list of all supported locale codes."""
        return list(self._translations.keys())


# ── Factory ───────────────────────────────────────────────────────────────────


def get_i18n() -> I18n:
    """Return the singleton I18n instance, creating it on first call."""
    global _INSTANCE
    if _INSTANCE is None:
        locale = _detect_locale()
        _INSTANCE = I18n(locale=locale)
    return _INSTANCE
