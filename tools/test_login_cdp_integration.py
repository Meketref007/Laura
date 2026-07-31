"""
Teste de integracao do login CDP + renovacao de cookies.
Requer: Brave aberto com sessao valida no seller.shopee.com.br

Uso: python tools/test_login_cdp_integration.py
"""
import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
os.environ["GMAIL_CREDENTIALS_FILE"] = "secrets/gmail_credentials.json"
os.environ["GMAIL_TOKEN_FILE"] = "secrets/gmail_token.json"

PASS = 0
FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")

print("=== Teste de Integracao: Login CDP + Cookies ===")
print()

# 1. Verificar CDP disponivel
import requests
try:
    v = requests.get("http://127.0.0.1:9222/json/version", timeout=5)
    test("CDP disponivel", v.status_code == 200)
except Exception as e:
    test("CDP disponivel", False, str(e))
    sys.exit(1)

# 2. EmailManager carrega
from shopee_agent.email_manager import EmailManager
mgr = EmailManager.from_env()
test("EmailManager.from_env() carrega", mgr is not None)

# 3. Credenciais Gmail existem
if mgr:
    test("Credentials file existe", mgr.credentials_file.exists(), str(mgr.credentials_file))
    test("Token file existe", mgr.token_file.exists(), str(mgr.token_file))

# 4. Seller center cookies atuais
from shopee_agent.seller_center import load_cookies, COOKIES_FILE, SellerCenterClient
from shopee_agent.config import load_config

session = load_cookies(COOKIES_FILE)
test("Cookies do Seller Center existem", session is not None)

if session:
    spc_si = session.get_cookie("SPC_SI")
    test("SPC_SI presente", spc_si is not None)
    test("SPC_SI nao expirado", spc_si and not spc_si.is_expired())
    test("Sessao valida (is_valid)", session.is_valid())

# 5. Renovar cookies via CDP
from shopee_agent.auto_login import renovar_cookies_via_cdp
result = renovar_cookies_via_cdp()
test("renovar_cookies_via_cdp() executou", result is not None)
test("renovar_cookies_via_cdp() sucesso", result is True)

# 6. Verificar cookies apos renovacao
session2 = load_cookies(COOKIES_FILE)
test("Cookies renovados existem", session2 is not None)
if session2:
    test("Sessao renovada e valida", session2.is_valid())
    total = len(session2.cookies)
    test(f"Cookies apos renovacao: {total}", total >= 10, f"{total} cookies")

# 7. SellerCenterClient autenticado
cfg = load_config()
client = SellerCenterClient(session2)
test("SellerCenterClient autenticado", client.is_authenticated())

# 8. Testar login_via_cdp_completo nao quebra (com sessao valida, deve tentar re-login mas detectar)
from shopee_agent.auto_login import login_via_cdp_completo
try:
    # Com sessao valida, login_via_cdp_completo ainda tenta logar
    # mas devemos pelo menos verificar que nao crasha
    result2 = login_via_cdp_completo()
    test("login_via_cdp_completo() executou sem crash", True)
except Exception as e:
    test("login_via_cdp_completo() executou sem crash", False, str(e))

print()
print(f"Resultado: {PASS} passaram, {FAIL} falharam")

if FAIL > 0:
    sys.exit(1)
