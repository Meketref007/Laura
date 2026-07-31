"""
Auto-login Shopee Seller Center.

Usa link de verificacao do Gmail (enviado por info@security.shopee.com.br)
para autenticar automaticamente. Nao precisa de Chrome/CDP nem de OTP numerico.
"""

from __future__ import annotations

import os
import re
import signal
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests as req

from shopee_agent.paths import SECRETS_DIR

from .email_manager import EmailManager
from .logger import error as log_error
from .logger import info, warning
from .seller_center import (
    SELLER_CENTER_BASE,
    SellerCenterCookie,
    SellerCenterSession,
    load_cookies,
    save_cookies,
)

CREDENTIALS_FILE = os.getenv("SELLER_CENTER_CREDENTIALS_FILE", str(SECRETS_DIR / "seller_center_credentials.json"))
ACCOUNTS_BASE = "https://accounts.shopee.com.br"


def carregar_credenciais() -> dict:
    path = Path(CREDENTIALS_FILE)
    if path.exists():
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    # Fallback: ler de vars de ambiente
    email = os.getenv("SELLER_CENTER_EMAIL", "")
    password = os.getenv("SELLER_CENTER_PASSWORD", "")
    if email and password:
        return {"email": email, "password": password}
    return {}


def buscar_link_verificacao(aguardar_segundos: int = 60) -> str | None:
    """
    Busca no Gmail o link de confirmacao de login enviado por
    info@security.shopee.com.br. Aguarda ate aguardar_segundos pelo email.
    Retorna a URL de confirmacao ou None.
    """
    mgr = EmailManager.from_env()
    if not mgr:
        warning("EmailManager nao configurado")
        return None

    deadline = datetime.now(UTC) + timedelta(seconds=aguardar_segundos)

    while datetime.now(UTC) < deadline:
        msgs = mgr.list_messages(
            query="from:info@security.shopee.com.br subject:(Verifica OR confirm OR login) is:unread",
            max_results=5,
        )
        if not msgs:
            msgs = mgr.list_messages(
                query="from:info@security.shopee.com.br subject:(Verifica OR confirm OR login)",
                max_results=5,
            )

        for m in msgs:
            detail = mgr.get_message(m["id"])
            parsed = mgr.parse_message(detail)

            body = parsed.body_html or parsed.body_plain or parsed.snippet

            # Pattern: link de confirmacao no email
            # "Se é você, por favor clique aqui para confirmar" -> href="..."
            # ou link direto: https://accounts.shopee.com.br/verify/...
            for pattern in [
                r'https://accounts\.shopee\.com\.br/verify/[^\s"\'<>]+',
                r'https://shopee\.com\.br/verify/[^\s"\'<>]+',
                r'https://br\.shp\.ee/dlink/[^\s"\'<>]+',
                r'href=["\'](https://[^\s"\'<>]*(?:confirm|verify|approve|dlink)[^\s"\'<>]*)["\']',
            ]:
                match = re.search(pattern, body, re.IGNORECASE)
                if match:
                    url = match.group(1) if match.lastindex else match.group(0)
                    url = url.rstrip(".")
                    info("Link de verificacao encontrado no Gmail")
                    # Marcar como lido para nao re-processar
                    try:
                        mgr.mark_as_read(m["id"])
                    except Exception:
                        pass
                    return url

        if msgs:
            warning("Email de verificacao encontrado mas sem link reconhecivel")
        time.sleep(5)

    warning(f"Nenhum email de verificacao do Shopee encontrado em {aguardar_segundos}s")
    return None


def iniciar_login_por_email() -> req.Session | None:

    creds = carregar_credenciais()
    if not creds or not creds.get("email") or not creds.get("password"):
        return None

    session = req.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": ACCOUNTS_BASE,
        "Referer": f"{ACCOUNTS_BASE}/seller/login",
    })

    # Aquecer session
    try:
        session.get(f"{ACCOUNTS_BASE}/seller/login", timeout=10)
    except Exception:
        pass

    payload = {"email": creds["email"], "password": creds["password"]}

    # Tentar login nos endpoints do accounts
    for path in ("/api/v1/auth/login", "/api/v2/auth/login", "/api/v1/seller/login", "/api/v2/seller/login"):
        url = f"{ACCOUNTS_BASE}{path}"
        try:
            resp = session.post(url, json=payload, timeout=30)
            info(f"POST {url}: status={resp.status_code}, body={resp.text[:200]}")
            if resp.status_code in (200, 202):
                info(f"Login iniciado via {url}")
                return session
        except Exception as e:
            warning(f"Erro em {url}: {e}")

    # Fallback: POST direto para /seller/login (form-urlencoded)
    try:
        resp = session.post(
            f"{ACCOUNTS_BASE}/seller/login",
            data={"email": creds["email"], "password": creds["password"]},
            timeout=30,
        )
        info(f"POST /seller/login (form): status={resp.status_code}")
        if resp.status_code in (200, 302, 202):
            return session
    except Exception as e:
        warning(f"Erro em /seller/login: {e}")

    return None


def _extrair_cookies_de_session(session) -> list:
    cookies_obj = []
    for c in session.cookies:
        domain = c.domain if c.domain else ""
        if "shopee" in domain.lower():
            cookies_obj.append(SellerCenterCookie(
                name=c.name, value=c.value, domain=domain,
                path=c.path if c.path else "/",
                secure=c.secure if c.secure else True,
                expirationDate=c.expires if c.expires else None,
            ))
    return cookies_obj


def _salvar_cookies(session) -> bool:
    cookies_obj = _extrair_cookies_de_session(session)
    if not cookies_obj:
        return False
    save_cookies(SellerCenterSession(cookies=cookies_obj))
    info(f"Login: {len(cookies_obj)} cookies salvos")
    return True


def login_direto() -> bool:
    """
    Login direto no Seller Center sem Chrome/CDP.

    Fluxo:
    1. Carrega credenciais
    2. POST login para accounts.shopee.com.br
    3. Shopee envia email de verificacao para o Gmail
    4. Busca o link de confirmacao no Gmail
    5. GET no link de confirmacao
    6. Salva cookies da sessao autenticada
    """
    creds = carregar_credenciais()
    if not creds or not creds.get("email") or not creds.get("password"):
        warning(f"Credenciais nao encontradas em {CREDENTIALS_FILE}")
        return False

    session = iniciar_login_por_email()
    if not session:
        log_error("Nao foi possivel iniciar o login via accounts.shopee.com.br")
        return False

    info("Login iniciado. Buscando email de verificacao...")
    link = buscar_link_verificacao(aguardar_segundos=90)
    if not link:
        log_error("Link de verificacao nao encontrado no Gmail")
        return False

    info("Clicando no link de verificacao...")
    try:
        resp = session.get(link, timeout=30)
        info(f"Link de verificacao: status={resp.status_code}")
    except Exception as e:
        log_error(f"Erro ao acessar link de verificacao: {e}")
        return False

    # Visitar seller.shopee.com.br para consolidar cookies
    try:
        session.get(f"{SELLER_CENTER_BASE}/", timeout=15)
    except Exception:
        pass

    if _salvar_cookies(session):
        info("Login direto concluido com sucesso!")
        return True

    log_error("Login direto: nenhum cookie Shopee encontrado apos verificacao")
    return False


def auto_login_loop(
    credentials_file: str = "",
    token_file: str = "",
    interval_hours: int = 6,
) -> None:
    """
    Loop continuo de auto-login.
    Carrega credenciais Gmail, verifica cookies do Seller Center
    e tenta renovar se expirados. Repete a cada interval_hours.
    """
    credentials_file or os.getenv("GMAIL_CREDENTIALS_FILE", str(SECRETS_DIR / "gmail_credentials.json"))
    token_file or os.getenv("GMAIL_TOKEN_FILE", str(SECRETS_DIR / "gmail_token.json"))

    _shutdown = False
    def _handle_sig(*_):
        nonlocal _shutdown
        info("[AutoLogin] Sinal recebido, desligando...")
        _shutdown = True
    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    while not _shutdown:
        try:
            info("[AutoLogin] Verificando sessao do Seller Center...")
            ok = cookies_para_login()
            if not ok:
                info("[AutoLogin] Cookies expirados, tentando CDP completo...")
                cdp_ok = login_via_cdp_completo()
                if cdp_ok:
                    info("[AutoLogin] Cookies renovados via CDP login completo")
                else:
                    warning("[AutoLogin] CDP completo falhou, tentando renovar cookies...")
                    cdp_simple = renovar_cookies_via_cdp()
                    if cdp_simple:
                        info("[AutoLogin] Cookies renovados via CDP (extração simples)")
                    else:
                        warning("[AutoLogin] CDP simples falhou, tentando login direto...")
                        direto_ok = login_direto()
                        if direto_ok:
                            info("[AutoLogin] Cookies renovados via login direto")
                        else:
                            log_error("[AutoLogin] Todas as tentativas falharam")
            else:
                info("[AutoLogin] Sessao do Seller Center ativa")
        except Exception as e:
            log_error(f"[AutoLogin] Erro no loop: {e}")

        # Sleep interval com verificacao de shutdown a cada 30s
        for _ in range(interval_hours * 120):
            if _shutdown:
                break
            time.sleep(30)

    info("[AutoLogin] Loop encerrado.")


def cookies_para_login() -> bool:
    """
    Tenta fazer login automatico no Seller Center.
    1. Carrega cookies existentes
    2. Se validos, retorna True
    3. Se expirados, retorna False e orienta renovacao
    """
    session = load_cookies()
    if session and session.is_valid():
        info("Cookies do Seller Center ainda validos")
        return True

    warning("Cookies do Seller Center expirados ou ausentes")
    info("Para renovar manualmente: laura seller-center-import")
    info("Para renovar automaticamente: aguarde o ciclo CDP (auto_login_loop)")
    return False


def renovar_cookies_via_cdp() -> bool:
    """
    Tenta renovar cookies conectando via CDP ao Brave.
    Conecta via Chrome DevTools Protocol WebSocket, chama Network.getAllCookies,
    filtra cookies shopee.com.br e salva no arquivo de cookies do Seller Center.
    """
    try:
        import json
        import ssl

        import websocket

        # Check CDP is available
        version = req.get("http://127.0.0.1:9222/json/version", timeout=5)
        if version.status_code != 200:
            warning("CDP nao disponivel (Brave fechado?)")
            return False

        # Find existing seller.shopee.com.br tab or create one
        tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
        ws_url = None

        for tab in tabs:
            if "seller.shopee.com.br" in tab.get("url", ""):
                ws_url = tab.get("webSocketDebuggerUrl", "")
                info(f"Aba do Seller Center encontrada: {tab.get('title', '')[:60]}")
                break

        if not ws_url:
            info("Nenhuma aba do Seller Center encontrada. Criando nova aba...")
            resp = req.put(
                "http://127.0.0.1:9222/json/new?https://seller.shopee.com.br",
                timeout=10,
            )
            if resp.status_code != 200:
                warning("Falha ao criar nova aba via CDP")
                return False
            new_tab = resp.json()
            ws_url = new_tab.get("webSocketDebuggerUrl", "")
            if not ws_url:
                warning("Nova aba criada mas sem webSocketDebuggerUrl")
                return False
            time.sleep(5)

        if not ws_url:
            warning("Nao foi possivel obter URL do WebSocket debug")
            return False

        # Connect to CDP WebSocket
        ws = websocket.create_connection(
            ws_url,
            timeout=15,
            sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {},
        )

        # Enable Network domain (required to access cookies)
        ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        ws.recv()

        # Call Network.getAllCookies
        ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
        result_raw = ws.recv()
        ws.close()

        result = json.loads(result_raw)
        cookies_data = result.get("result", {}).get("cookies", [])

        if not cookies_data:
            warning("Nenhum cookie retornado pelo CDP Network.getAllCookies")
            return False

        # Filter only shopee.com.br cookies (includes seller.shopee.com.br)
        shopee_cookies = [
            c for c in cookies_data
            if "shopee.com.br" in c.get("domain", "")
        ]

        if not shopee_cookies:
            warning("Nenhum cookie shopee.com.br encontrado no navegador")
            return False

        info(f"CDP: {len(shopee_cookies)} cookies shopee.com.br extraidos")

        # Convert to SellerCenterCookie objects
        cookies_obj = []
        for c in shopee_cookies:
            cookie = SellerCenterCookie(
                name=c["name"],
                value=c["value"],
                domain=c.get("domain", ""),
                path=c.get("path", "/"),
                secure=c.get("secure", False),
                httpOnly=c.get("httpOnly", False),
                expirationDate=c.get("expires", None),
                sameSite=c.get("sameSite", None),
                session=c.get("session", False),
            )
            cookies_obj.append(cookie)

        session = SellerCenterSession(cookies=cookies_obj)
        save_cookies(session)
        info(f"Cookies renovados via CDP ({len(cookies_obj)} cookies salvos)")
        return True

    except ImportError as e:
        warning(f"Biblioteca necessaria nao disponivel: {e}")
    except Exception as e:
        log_error(f"Falha ao renovar cookies via CDP: {e}")

    return False


def _cdp_execute(ws_url: str, method: str, params: dict | None = None, timeout: int = 15) -> dict | None:
    """Send CDP command via WebSocket and return result."""
    import json as _json
    import ssl as _ssl

    import websocket as _ws
    try:
        ws = _ws.create_connection(
            ws_url, timeout=timeout,
            sslopt={"cert_reqs": _ssl.CERT_NONE} if ws_url.startswith("wss") else {},
        )
        msg = _json.dumps({"id": 1, "method": method, "params": params or {}})
        ws.send(msg)
        raw = ws.recv()
        ws.close()
        return _json.loads(raw)
    except Exception:
        return None


def login_via_cdp_completo() -> bool:
    """
    Login completo no Seller Center via CDP (Chrome DevTools Protocol).

    Fluxo:
    1. Conecta no Brave via CDP
    2. Navega para accounts.shopee.com.br/seller/login
    3. Preenche email e senha via JavaScript
    4. Clica em 'Entrar'
    5. Aguarda email de verificacao no Gmail
    6. Navega para o link de verificacao via CDP
    7. Aguarda redirect para Seller Center
    8. Extrai cookies e salva
    """
    creds = carregar_credenciais()
    if not creds or not creds.get("email") or not creds.get("password"):
        warning("Credenciais nao encontradas para CDP login")
        return False

    try:
        import json as _json
        import ssl as _ssl

        import websocket as _ws

        # Verificar CDP disponivel
        version = req.get("http://127.0.0.1:9222/json/version", timeout=5)
        if version.status_code != 200:
            warning("CDP nao disponivel para login completo")
            return False

        # Criar nova aba para login
        resp = req.put("http://127.0.0.1:9222/json/new", timeout=10)
        if resp.status_code != 200:
            warning("Falha ao criar aba para login")
            return False
        tab = resp.json()
        ws_url = tab.get("webSocketDebuggerUrl", "")
        if not ws_url:
            warning("Nova aba sem webSocketDebuggerUrl")
            return False

        ws = _ws.create_connection(
            ws_url, timeout=15,
            sslopt={"cert_reqs": _ssl.CERT_NONE} if ws_url.startswith("wss") else {},
        )

        cdp_msg_id = 0
        def _cdp(method: str, params: dict | None = None) -> dict | None:
            nonlocal ws, cdp_msg_id
            cdp_msg_id += 1
            _id = cdp_msg_id
            ws.send(_json.dumps({"id": _id, "method": method, "params": params or {}}))
            while True:
                raw = ws.recv()
                data = _json.loads(raw)
                if data.get("id") == _id:
                    return data

        # Navegar para login page
        info("CDP: Navegando para pagina de login...")
        _cdp("Page.enable")
        _cdp("Page.navigate", {"url": "https://accounts.shopee.com.br/seller/login"})
        time.sleep(5)

        # Preencher email
        email_js = "document.querySelector('input[name=\"email\"]') || document.querySelector('input[type=\"email\"]')"
        safe_email = _json.dumps(creds['email'])[1:-1]
        _cdp("Runtime.evaluate", {
            "expression": f"const el = {email_js}; if(el) {{ el.value = '{safe_email}'.replace(/['\"\\\\]/g, ''); el.dispatchEvent(new Event('input', {{bubbles:true}})) }}",
        })
        time.sleep(1)

        # Preencher senha
        pwd_js = "document.querySelector('input[name=\"password\"]') || document.querySelector('input[type=\"password\"]')"
        safe_pwd = _json.dumps(creds['password'])[1:-1]
        _cdp("Runtime.evaluate", {
            "expression": f"const el = {pwd_js}; if(el) {{ el.value = '{safe_pwd}'.replace(/['\"\\\\]/g, ''); el.dispatchEvent(new Event('input', {{bubbles:true}})) }}",
        })
        time.sleep(1)

        # Clicar em Entrar
        btn_js = "document.querySelector('button[type=\"submit\"]') || document.querySelector('.login-btn') || document.querySelector('button:contains(\"Entrar\")')"
        _cdp("Runtime.evaluate", {"expression": f"({btn_js})?.click()"})
        info("CDP: Credenciais preenchidas, botao de login clicado")
        time.sleep(5)

        ws.close()

        # Buscar link de verificacao no Gmail
        info("CDP: Aguardando email de verificacao...")
        link = buscar_link_verificacao(aguardar_segundos=120)
        if not link:
            log_error("CDP: Link de verificacao nao encontrado apos login")
            # Tentar extrair cookies mesmo sem confirmacao
            _salvar_cookies_se_possivel()
            return False

        info("CDP: Link de verificacao encontrado, navegando...")

        # Navegar para o link de verificacao via CDP (nova conexao)
        ws2 = _ws.create_connection(
            ws_url, timeout=15,
            sslopt={"cert_reqs": _ssl.CERT_NONE} if ws_url.startswith("wss") else {},
        )

        cdp2_msg_id = 0
        def _cdp2(method: str, params: dict | None = None) -> dict | None:
            nonlocal ws2, cdp2_msg_id
            cdp2_msg_id += 1
            _id = cdp2_msg_id
            ws2.send(_json.dumps({"id": _id, "method": method, "params": params or {}}))
            while True:
                raw = ws2.recv()
                data = _json.loads(raw)
                if data.get("id") == _id:
                    return data

        _cdp2("Page.enable")
        _cdp2("Page.navigate", {"url": link})
        info("CDP: Navegou para link de verificacao")
        time.sleep(8)
        ws2.close()

        # Extrair cookies
        info("CDP: Extraindo cookies apos login...")
        if _salvar_cookies_se_possivel():
            info("Login via CDP concluido com sucesso!")
            return True

        log_error("Login via CDP: cookie extraction failed")
        return False

    except ImportError as e:
        warning(f"Biblioteca necessaria nao disponivel: {e}")
    except Exception as e:
        log_error(f"Falha no login via CDP completo: {e}")

    return False


def _salvar_cookies_se_possivel() -> bool:
    """Tenta extrair cookies do navegador via CDP e salvar."""
    try:
        version = req.get("http://127.0.0.1:9222/json/version", timeout=5)
        if version.status_code != 200:
            return False
        return renovar_cookies_via_cdp()
    except Exception:
        return False
