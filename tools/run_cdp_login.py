"""Run full CDP login to restore session."""
import io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
os.environ["GMAIL_CREDENTIALS_FILE"] = "secrets/gmail_credentials.json"
os.environ["GMAIL_TOKEN_FILE"] = "secrets/gmail_token.json"
os.environ["SELLER_CENTER_DRY_RUN"] = "0"

from shopee_agent.auto_login import login_via_cdp_completo

print("Tentando login completo via CDP...")
result = login_via_cdp_completo()
print(f"Resultado: {'SUCESSO' if result else 'FALHA'}")

if result:
    from shopee_agent.seller_center import load_cookies
    session = load_cookies()
    if session:
        print(f"Cookies: {len(session.cookies)} | Valida: {session.is_valid()}")
