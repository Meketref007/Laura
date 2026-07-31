"""CLI shell interativa com auto-complete - Laura."""
import json
import os
import sys
import atexit
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

COMMANDS = {
    "status": "Resumo do sistema Laura",
    "acoes": "Lista todas as acoes disponiveis",
    "pricing": "Sugestoes de precificacao",
    "estoque": "Previsao de reabastecimento",
    "sentimento": "Analise de sentimento das avaliacoes",
    "relatorio": "Gera relatorio semanal",
    "retirada": "Configuracao de retirada pelo comprador",
    "chat": "Mensagens de chat pendentes",
    "avaliacoes": "Avaliacoes pendentes de resposta",
    "dashboard": "Abrir dashboard web",
    "help": "Este menu de ajuda",
    "exit": "Sair",
}


def _print_help():
    print("Comandos disponiveis:")
    for cmd, desc in COMMANDS.items():
        print(f"  {cmd:15s} {desc}")
    print()


def _get_seller_client():
    try:
        from shopee_agent.seller_center import SellerCenterClient, load_cookies
        session = load_cookies()
        if session:
            return SellerCenterClient(session=session)
    except Exception:
        pass
    return None


def _cmd_status():
    sc = _get_seller_client()
    if not sc or not sc.is_authenticated():
        print("❌ Seller Center nao autenticado. Rode 'laura daemon' primeiro.")
        return
    try:
        info = sc.get_shop_info()
        todo = sc.get_todo_summary()
        print(f"Loja: {info.get('name', '?')}")
        print(f"Pedidos pendentes: {todo.get('shipment_to_process', 0)}")
        print(f"Devolucoes: {todo.get('order_return_refund_cancel', 0)}")
        print(f"Produtos banidos: {todo.get('product_banned_deboosted', 0)}")
    except Exception as e:
        print(f"Erro: {e}")


def _cmd_pricing():
    sc = _get_seller_client()
    if not sc:
        print("❌ Seller Center nao disponivel"); return
    try:
        from shopee_agent.pricing_automation import generate_pricing_report
        sug = generate_pricing_report(sc)
        if not sug:
            print("Sem dados de precificacao."); return
        print(f"{'Produto':40s} {'Atual':>10s} {'Sugerido':>10s} {'Direcao':>10s}")
        print("-" * 70)
        for s in sug[:10]:
            print(f"{s['name'][:38]:40s} R$ {s['current_price']:>7.2f} R$ {s['suggested_price']:>7.2f} {s['direction']:>10s}")
    except Exception as e:
        print(f"Erro: {e}")


def _cmd_estoque():
    sc = _get_seller_client()
    if not sc:
        print("❌ Seller Center nao disponivel"); return
    try:
        from shopee_agent.stock_predictor import predict_restock
        recs = predict_restock(sc)
        if not recs:
            print("Nenhum item precisa de reabastecimento."); return
        print(f"{'Produto':40s} {'Estoque':>8s} {'Dias':>6s} {'Prioridade':>10s}")
        print("-" * 65)
        for r in recs[:10]:
            print(f"{r['name'][:38]:40s} {r['current_stock']:>8d} {r['days_until_empty']:>5.1f}  {r['priority']:>10s}")
    except Exception as e:
        print(f"Erro: {e}")


def _cmd_sentimento():
    sc = _get_seller_client()
    if not sc:
        print("❌ Seller Center nao disponivel"); return
    try:
        from shopee_agent.sentiment_analyzer import analyze_ratings
        result = analyze_ratings(sc)
        print(f"Total avaliacoes: {result.get('total_ratings', 0)}")
        print(f"Media estrelas: {result.get('avg_stars', 0)}")
        print(f"Sentimento: {result.get('sentiment', {})}")
        if result.get("suggestions"):
            print("\nSugestoes:")
            for s in result["suggestions"]:
                print(f"  💡 {s}")
    except Exception as e:
        print(f"Erro: {e}")


def main():
    print("Laura Shell - Digite 'help' para comandos ou 'exit' para sair")
    print()

    if len(sys.argv) > 1 and sys.argv[1] == "--cmd":
        cmd = " ".join(sys.argv[2:])
        _execute(cmd)
        return

    while True:
        try:
            cmd = input("laura> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not cmd:
            continue
        _execute(cmd)


def _execute(cmd: str):
    parts = cmd.split()
    if not parts:
        return
    cmd_name = parts[0].lower()
    if cmd_name in ("exit", "quit", "sair"):
        print("Tchau!")
        sys.exit(0)
    elif cmd_name == "help":
        _print_help()
    elif cmd_name == "status":
        _cmd_status()
    elif cmd_name == "pricing":
        _cmd_pricing()
    elif cmd_name == "estoque":
        _cmd_estoque()
    elif cmd_name == "sentimento":
        _cmd_sentimento()
    elif cmd_name == "relatorio":
        print("📊 Gere relatorio via: laura daemon (automatico segundas)")
    elif cmd_name == "retirada":
        print("📦 Use: python tools/inspect_pickup_endpoint.py para descobrir o endpoint")
    elif cmd_name == "dashboard":
        print("🌐 Abra http://127.0.0.1:8888 no navegador")
    elif cmd_name == "acoes":
        print("\n".join(f"  {k} - {v}" for k, v in COMMANDS.items()))
    else:
        print(f"Comando desconhecido: {cmd_name}. Digite 'help'")


if __name__ == "__main__":
    main()
