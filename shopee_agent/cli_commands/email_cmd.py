"""Email commands: email (with subcommands: auth-url, auth-callback, profile, list-unread, search-otp, send)."""
import sys

from ._utils import print_json


def register_subparsers(sub):
    email_parser = sub.add_parser("email", help="Gerenciamento de email (Gmail) - ler, enviar, buscar OTPs")
    email_sub = email_parser.add_subparsers(dest="email_command", required=True)
    email_sub.add_parser("auth-url", help="Gerar URL de autorizacao Gmail")
    email_auth_callback = email_sub.add_parser("auth-callback", help="Trocar code por token Gmail")
    email_auth_callback.add_argument("--code", required=True, help="Codigo de autorizacao")
    email_sub.add_parser("profile", help="Mostrar perfil do Gmail")
    email_unread = email_sub.add_parser("list-unread", help="Listar emails nao lidos")
    email_unread.add_argument("--limit", type=int, default=10, help="Maximo de emails")
    email_search_otp = email_sub.add_parser("search-otp", help="Buscar codigos OTP em emails")
    email_search_otp.add_argument("--sender", default="", help="Filtrar por remetente (ex: shopee)")
    email_search_otp.add_argument("--limit", type=int, default=10, help="Maximo de resultados")
    email_send = email_sub.add_parser("send", help="Enviar email")
    email_send.add_argument("--to", required=True, help="Destinatario")
    email_send.add_argument("--subject", required=True, help="Assunto")
    email_send.add_argument("--body", required=True, help="Corpo do email")


def run(args, client=None, cfg=None):
    if args.command != "email":
        return 2

    email_cmd = args.email_command

    if email_cmd == "auth-url":
        from shopee_agent.email_manager import EmailManager
        mgr = EmailManager.from_env()
        if not mgr:
            print("GMAIL_CREDENTIALS_FILE nao configurado no .env", file=sys.stderr); return 1
        url = mgr.authorization_url()
        print("Autorize o Gmail acessando esta URL:")
        print(url)
        return 0

    if email_cmd == "auth-callback":
        from shopee_agent.email_manager import EmailManager
        mgr = EmailManager.from_env()
        if not mgr:
            print("GMAIL_CREDENTIALS_FILE nao configurado no .env", file=sys.stderr); return 1
        code = args.code
        if not code:
            print("Use --code para passar o codigo de autorizacao", file=sys.stderr); return 1
        result = mgr.exchange_code(code)
        print("Gmail autorizado com sucesso!")
        print_json(result)
        return 0

    if email_cmd == "profile":
        from shopee_agent.email_manager import EmailManager
        mgr = EmailManager.from_env()
        if not mgr:
            print("GMAIL_CREDENTIALS_FILE nao configurado no .env", file=sys.stderr); return 1
        profile = mgr.get_profile()
        print_json(profile)
        return 0

    if email_cmd == "list-unread":
        from shopee_agent.email_manager import EmailManager
        mgr = EmailManager.from_env()
        if not mgr:
            print("GMAIL_CREDENTIALS_FILE nao configurado no .env", file=sys.stderr); return 1
        limit = args.limit or 10
        emails = mgr.fetch_unseen()
        if not emails:
            print("Nenhum email nao lido.")
        else:
            print(f"\n{len(emails)} email(s) nao lido(s) (mostrando ate {limit}):")
            for mail in emails[:limit]:
                print(f"\n  De: {mail.sender}")
                print(f"  Assunto: {mail.subject}")
                print(f"  Data: {mail.date}")
                print(f"  {mail.snippet[:150]}")
        return 0

    if email_cmd == "search-otp":
        from shopee_agent.email_manager import EmailManager
        mgr = EmailManager.from_env()
        if not mgr:
            print("GMAIL_CREDENTIALS_FILE nao configurado no .env", file=sys.stderr); return 1
        sender = args.sender or ""
        results = mgr.search_otp_codes(sender=sender, max_results=args.limit or 10)
        if not results:
            print("Nenhum codigo OTP encontrado.")
        else:
            print(f"\n{len(results)} OTP(s) encontrado(s):")
            for r in results:
                codes = ", ".join(r.get("codes_found", []))
                print(f"  De: {r['from'][:40]}")
                print(f"  Assunto: {r['subject'][:60]}")
                print(f"  Codigos: {codes}")
                print()
        return 0

    if email_cmd == "send":
        from shopee_agent.email_manager import EmailManager
        mgr = EmailManager.from_env()
        if not mgr:
            print("GMAIL_CREDENTIALS_FILE nao configurado no .env", file=sys.stderr); return 1
        to = args.to
        subject = args.subject
        body = args.body
        if not to or not subject or not body:
            print("Use --to, --subject e --body", file=sys.stderr); return 1
        mgr.send_email(to=to, subject=subject, body=body)
        print(f"Email enviado para {to}")
        return 0

    return 2
