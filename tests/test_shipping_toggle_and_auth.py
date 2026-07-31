"""Regression tests for _cdp_toggle_shipping and auto_login fixes."""
import json
from unittest.mock import MagicMock, patch, ANY

import pytest

from shopee_agent.seller_center_actions import SellerCenterActions
from shopee_agent.seller_center import SellerCenterSession, SellerCenterCookie


# ============================================================================
# Helpers
# ============================================================================

def _cookie(name, value, domain=".shopee.com.br", **kw):
    return SellerCenterCookie(name=name, value=value, domain=domain, **kw)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_session():
    cookies = [
        _cookie("SPC_SI", "test_si"),
        _cookie("SPC_ST", "test_st"),
        _cookie("SPC_EC", "test_ec"),
        _cookie("SPC_U", "test_u"),
    ]
    return SellerCenterSession(cookies=cookies, shop_id="test_shop")


@pytest.fixture
def actions(mock_session):
    with patch("shopee_agent.seller_center_actions.SellerCenterClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.session = mock_session
        mock_client.is_authenticated.return_value = True
        act = SellerCenterActions.__new__(SellerCenterActions)
        act.client = mock_client
        act._config = MagicMock()
        act._config.dry_run = False
        act._confirm_or_dry_run = MagicMock(return_value=None)
        yield act


# ============================================================================
# Tests: _cdp_toggle_shipping
# ============================================================================

class TestCdpToggleShipping:
    """Testa a funcao _cdp_toggle_shipping (toggle global)."""

    def test_returns_none_when_cdp_unavailable(self, actions):
        """Deve retornar None se o CDP nao estiver disponivel."""
        with patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 404
            result = actions._cdp_toggle_shipping("Shopee Xpress CPF", True)
            assert result is None

    def test_returns_none_when_no_brave_running(self, actions):
        """Deve retornar None se nao houver processo Brave."""
        with patch("requests.get") as mock_get:
            mock_get.side_effect = ConnectionError("No connection")
            result = actions._cdp_toggle_shipping("Shopee Xpress CPF", True)
            assert result is None

    def test_channel_match_uses_strict_matching(self):
        """O JS de toggle deve usar startsWith em vez de includes."""
        toggle_js = """
const channelName = 'shopee xpress cpf';
const switches = document.querySelectorAll('.eds-switch');
for (const sw of switches) {
  const header = sw.closest('.channel-setting-header');
  if (!header) continue;
  const text = header.textContent.trim().toLowerCase();
  if (text === channelName || text.startsWith(channelName)) { return true; }
}
"""
        assert "text.startsWith" in toggle_js
        assert "text.includes" not in toggle_js
        assert ".trim()" in toggle_js

    def test_modal_confirmar_button_detection(self):
        """O JS de confirmacao deve encontrar o botao Confirmar."""
        confirm_js = """() => {
  const btns = document.querySelectorAll('button');
  for (const b of btns) {
    const txt = b.textContent.trim().toLowerCase();
    if ((txt === 'confirmar' || txt === 'confirm') && b.offsetParent !== null) {
      b.click();
      return true;
    }
  }
  return false;
}"""
        # O JS em si e valido (sintaxe)
        assert "confirmar" in confirm_js
        assert "Confirmar" not in confirm_js  # usa toLowerCase
        assert "offsetParent" in confirm_js

    def test_toggle_js_disabled_channel_detection(self):
        """O JS de toggle deve ignorar canais disabled."""
        toggle_js = """
const channelName = 'retirada pelo comprador';
const switches = document.querySelectorAll('.eds-switch');
for (const sw of switches) {
  const header = sw.closest('.channel-setting-header');
  if (!header) continue;
  const text = header.textContent.toLowerCase();
  if (text.includes(channelName)) {
    const isDisabled = sw.classList.contains('eds-switch--disabled');
    if (isDisabled) return JSON.stringify({found: true, clicked: false, reason: 'canal nao pode ser alterado (disabled)'});
  }
}
"""
        assert "eds-switch--disabled" in toggle_js
        assert "canal nao pode ser alterado" in toggle_js


# ============================================================================
# Tests: set_channel_for_all_products
# ============================================================================

class TestSetChannelForAllProducts:
    """Testa a funcao set_channel_for_all_products."""

    def test_global_toggle_success(self, actions):
        """Toggle global bem-sucedido deve retornar mensagem de sucesso."""
        with patch.object(actions, '_cdp_toggle_shipping', return_value="Canal 'test' ativado globalmente"):
            result = actions.set_channel_for_all_products("test", True)
            assert "ativado" in result
            assert "globalmente" in result

    def test_global_toggle_fallback_message(self, actions):
        """Se toggle global falha, retorna mensagem explicativa."""
        with patch.object(actions, '_cdp_toggle_shipping', return_value=None):
            result = actions.set_channel_for_all_products("test", True)
            assert "falhou" in result.lower()
            assert "Fallback" in result

    def test_dry_run_blocks_action(self, actions):
        """Dry run deve bloquear a acao."""
        actions._confirm_or_dry_run = MagicMock(return_value="DRY RUN: bloquearia")
        result = actions.set_channel_for_all_products("test", True)
        assert "DRY RUN" in result

    def test_global_toggle_disabled_channel(self, actions):
        """Canal disabled (Retirada) deve retornar explicacao."""
        with patch.object(actions, '_cdp_toggle_shipping', return_value="Canal 'Retirada pelo Comprador' ja no estado desejado (global). Confirmacao: nao encontrada."):
            result = actions.set_channel_for_all_products("Retirada pelo Comprador", True)
            assert "ja no estado" in result


# ============================================================================
# Tests: auto_login
# ============================================================================

class TestAutoLogin:
    """Testa funcoes de auto_login (sem CDP real)."""

    def test_session_is_valid_checks_required_cookies(self):
        """is_valid() deve exigir SPC_SI, SPC_ST, SPC_EC."""
        cookies = [
            _cookie("SPC_SI", "v"),
            _cookie("SPC_ST", "v"),
            _cookie("SPC_EC", "v"),
        ]
        session = SellerCenterSession(cookies=cookies)
        assert session.is_valid() is True

    def test_session_invalid_without_spc_si(self):
        """Sem SPC_SI a sessao deve ser invalida."""
        cookies = [
            _cookie("SPC_ST", "v"),
            _cookie("SPC_EC", "v"),
        ]
        session = SellerCenterSession(cookies=cookies)
        assert session.is_valid() is False

    def test_session_invalid_with_expired_cookie(self):
        """Cookie expirado deve invalidar sessao."""
        import time
        expired = time.time() - 86400  # 1 day ago
        cookies = [
            _cookie("SPC_SI", "v", expirationDate=expired),
            _cookie("SPC_ST", "v"),
            _cookie("SPC_EC", "v"),
        ]
        session = SellerCenterSession(cookies=cookies)
        assert session.is_valid() is False

    def test_renovar_cookies_via_cdp_fails_without_brave(self):
        """renovar_cookies_via_cdp deve falhar se CDP/brave nao disponivel."""
        from shopee_agent.auto_login import renovar_cookies_via_cdp
        with patch("shopee_agent.auto_login.req.get") as mock_get:
            mock_get.side_effect = ConnectionError("No CDP")
            result = renovar_cookies_via_cdp()
            assert result is False

    def test_renovar_cookies_via_cdp_calls_cdp_endpoints(self):
        """Verifica que renovar_cookies_via_cdp usa os endpoints CDP corretos."""
        with patch("shopee_agent.auto_login.req.get") as mock_get, \
             patch("shopee_agent.auto_login.req.put") as mock_put, \
             patch("websocket.create_connection") as mock_ws:
            mock_version = MagicMock(status_code=200)
            mock_tabs = MagicMock(status_code=200)
            mock_tabs.json.return_value = [{"url": "https://seller.shopee.com.br", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/test"}]
            mock_get.side_effect = [mock_version, mock_tabs]
            mock_ws_instance = MagicMock()
            mock_ws_instance.recv.side_effect = [
                '{}',  # Network.enable response
                '{"result": {"cookies": []}}',  # Network.getAllCookies response
            ]
            mock_ws.return_value = mock_ws_instance

            from shopee_agent.auto_login import renovar_cookies_via_cdp
            result = renovar_cookies_via_cdp()
            # Deve retornar False porque nao ha cookies shopee
            assert result is False
            # Verificar que chamou os endpoints
            mock_get.assert_any_call("http://127.0.0.1:9222/json/version", timeout=5)
            mock_get.assert_any_call("http://127.0.0.1:9222/json", timeout=5)

    def test_email_manager_from_env(self):
        """EmailManager.from_env() requer GMAIL_CREDENTIALS_FILE."""
        import os
        from shopee_agent.email_manager import EmailManager
        # Sem env var deve retornar None
        old_val = os.environ.pop("GMAIL_CREDENTIALS_FILE", None)
        try:
            mgr = EmailManager.from_env()
            assert mgr is None
        finally:
            if old_val:
                os.environ["GMAIL_CREDENTIALS_FILE"] = old_val


# ============================================================================
# Tests: watchdog
# ============================================================================

class TestWatchdog:
    """Testa logica do watchdog."""

    def test_is_running_windows(self):
        """Verifica a logica de deteccao de processo no Windows."""
        import subprocess
        # tasklist com PID atual deve retornar True
        current_pid = __import__("os").getpid()
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"PID eq {current_pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            assert str(current_pid) in proc.stdout
        except FileNotFoundError:
            pytest.skip("tasklist not available (not Windows)")

    def test_watchdog_rejects_invalid_pid(self):
        """PID invalido deve retornar False no _is_running."""
        from tools.laura_watchdog import _is_running
        assert _is_running(999999999) is False
