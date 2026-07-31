"""Run direct login to refresh cookies."""
import io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

os.environ["GMAIL_CREDENTIALS_FILE"] = "secrets/gmail_credentials.json"
os.environ["GMAIL_TOKEN_FILE"] = "secrets/gmail_token.json"

from shopee_agent.auto_login import login_direto

print("Tentando login direto para renovar cookies...")
result = login_direto()
print(f"Resultado: {'SUCESSO' if result else 'FALHA'}")

if result:
    from shopee_agent.seller_center import load_cookies
    session = load_cookies()
    if session:
        print(f"Cookies: {len(session.cookies)} | Valida: {session.is_valid()}")
    else:
        print("Nao foi possivel carregar cookies apos login")
