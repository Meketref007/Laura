"""Telegram & Chat commands: telegram-bot, telegram-setup, telegram-setup-token, chat-send, support-triage, support-summary."""
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from shopee_agent.logger import log_error

from ._utils import append_audit_line, ensure_no_api_error, int_from_env, print_json


def register_subparsers(sub):
    chat_send = sub.add_parser("chat-send", help="Envia mensagem ao comprador (wrapper para /api/v2/chat/send_message)")
    chat_send.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    chat_send.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    chat_send.add_argument("--buyer-id", required=True, help="ID do comprador/buyer_id")
    chat_send.add_argument("--message", required=True, help="Texto da mensagem a enviar")
    chat_send.add_argument("--dry-run", action="store_true", help="Não executa a alteração; apenas mostra o payload")
    telegram_bot = sub.add_parser("telegram-bot", help="Bot Telegram interativo da Laura (/status, /pedidos, /estoque, /margem, /aprovar)")
    telegram_bot.add_argument("--token", default=os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip() or None, help="Token do bot Telegram")
    telegram_bot.add_argument("--allowed-chat-id", default=os.getenv("LAURA_TELEGRAM_BOT_ALLOWED_CHAT_ID", "").strip() or os.getenv("LAURA_ALERT_TELEGRAM_CHAT_ID", "").strip() or None, help="Chat ID permitido para comandos")
    telegram_bot.add_argument("--poll-timeout-seconds", type=int, default=int_from_env("LAURA_TELEGRAM_BOT_POLL_TIMEOUT_SECONDS", 30), help="Timeout de long polling no getUpdates")
    telegram_bot.add_argument("--sleep-seconds", type=float, default=float(os.getenv("LAURA_TELEGRAM_BOT_SLEEP_SECONDS", "1.0") or "1.0"), help="Espera entre ciclos")
    telegram_bot.add_argument("--once", action="store_true", help="Processa um ciclo e sai (modo teste)")
    telegram_setup = sub.add_parser("telegram-setup", help="Conecta no Brave (CDP) e configura o bot Telegram via BotFather")
    telegram_setup.add_argument("--cdp-port", type=int, default=9222, help="Porta CDP do Brave (default: 9222)")
    telegram_setup_token = sub.add_parser("telegram-setup-token", help="Salva o token do bot Telegram (pegue no BotFather)")
    telegram_setup_token.add_argument("token", help="Token do bot (ex: 123456:ABC-def)")
    support_triage = sub.add_parser("support-triage", help="Classify a support message, recommend a response, and decide whether to escalate")
    support_triage.add_argument("--buyer-id", required=True, help="Buyer identifier")
    support_triage.add_argument("--message", required=True, help="Incoming support message")
    support_triage.add_argument("--order-id", default=None, help="Optional order identifier")
    support_triage.add_argument("--reports-dir", default="reports", help="Directory for support history and memory")
    support_triage.add_argument("--output", default=None, help="Optional JSON output file")
    support_summary = sub.add_parser("support-summary", help="Summarize support tickets, escalations, and customer memory")
    support_summary.add_argument("--reports-dir", default="reports", help="Directory for support history and memory")
    support_summary.add_argument("--days", type=int, default=30, help="Lookback window in days")
    support_summary.add_argument("--output", default=None, help="Optional JSON output file")


def run(args, client=None, cfg=None):
    from shopee_agent.config import ConfigError, load_config
    if args.command in ("support-triage", "support-summary"):
        cfg = None
        client = None
    elif cfg is None:
        try:
            cfg = load_config()
        except ConfigError as exc:
            log_error("Config load failed", error=str(exc))
            print(str(exc), file=sys.stderr)
            return 1
    if client is None and args.command in ("chat-send", "telegram-bot"):
        from shopee_agent.client import ShopeeClient
        client = ShopeeClient(cfg)

    if args.command == "chat-send":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        payload = {"buyer_id": args.buyer_id, "message": args.message}
        if args.dry_run:
            print("DRY RUN: payload to send:")
            print_json(payload)
            return 0
        resp = client.send_chat_message(access_token=effective_access_token, shop_id=effective_shop_id, buyer_id=args.buyer_id, message=args.message)
        err = ensure_no_api_error(resp.data, "chat-send")
        if err:
            print(err, file=sys.stderr); return 1
        print_json(resp.data)
        append_audit_line(Path("reports/chat_outbound.jsonl"), {"timestamp": datetime.now(UTC).isoformat(), "action": "chat_send", "shop_id": effective_shop_id, "buyer_id": args.buyer_id, "message": args.message, "response": resp.data})
        return 0

    if args.command == "telegram-bot":
        token = args.token or os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            print("Token ausente: configure LAURA_ALERT_TELEGRAM_BOT_TOKEN ou use --token", file=sys.stderr); return 1
        from shopee_agent.telegram_bot import LauraTelegramBot
        effective_access_token = cfg.default_access_token
        effective_shop_id = cfg.default_shop_id
        email_manager = None
        try:
            from shopee_agent.email_manager import EmailManager
            email_manager = EmailManager.from_env()
        except Exception:
            pass
        bot = LauraTelegramBot(token=token, allowed_chat_id=args.allowed_chat_id, shopee_client=client, access_token=effective_access_token, shop_id=effective_shop_id, reports_dir=Path("reports"), poll_timeout_seconds=args.poll_timeout_seconds, sleep_seconds=args.sleep_seconds, email_manager=email_manager)
        print("Laura Telegram bot iniciado. Envie /start para o menu ou pergunte em linguagem natural!")
        return bot.run(once=bool(args.once))

    if args.command == "telegram-setup":
        print("Conectando no Brave (CDP) para configurar o Telegram...")
        print("= " * 30)
        print("1. O Brave precisa estar aberto com --remote-debugging-port=9222")
        print("2. Vou conectar na aba do Telegram Web")
        print("3. Vou guiar voce pelo BotFather para configurar o bot")
        print("= " * 30)
        from shopee_agent.telegram_web_setup import run as tg_setup_run
        result = tg_setup_run()
        if result.get("bot_token"):
            print(f"\nToken do bot: {result['bot_token']}")
            print("Adicione ao .env: LAURA_ALERT_TELEGRAM_BOT_TOKEN=" + result['bot_token'])
        if result.get("configured"):
            print("Token configurado!")
        if result.get("needs_token"):
            print("\nToken necessario. Vou orientar voce:")
            print("1. Va no BotFather no Telegram Web")
            print("2. Copie o token do bot")
            print("3. Execute: laura telegram-setup-token SEU_TOKEN")
        if result.get("success"):
            print("\nAgora inicie o bot com: laura telegram-bot")
        else:
            print(f"\nFalha: {result.get('error', 'erro desconhecido')}")
        return 0

    if args.command == "telegram-setup-token":
        from shopee_agent.telegram_web_setup import save_token_command
        save_token_command(args.token)
        print("Token salvo em secrets/telegram_setup.json")
        print("Agora execute: laura telegram-bot")
        return 0

    if args.command == "support-triage":
        from shopee_agent.support_center import SupportCenter
        center = SupportCenter(reports_dir=args.reports_dir)
        ticket = center.triage_message(buyer_id=args.buyer_id, message=args.message, order_id=args.order_id)
        if args.output:
            Path(args.output).write_text(json.dumps(ticket.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print_json(ticket.to_dict())
        return 0

    if args.command == "support-summary":
        from shopee_agent.support_center import SupportCenter, dump_support_summary
        center = SupportCenter(reports_dir=args.reports_dir)
        summary = center.summary(days=args.days)
        if args.output:
            output_path = dump_support_summary(summary, args.output)
            print(f"Wrote support summary to {output_path}")
        print_json(summary.to_dict())
        return 0

    return 2
