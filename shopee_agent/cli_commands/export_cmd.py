"""Comando export - exporta dados da loja para CSV/Excel."""
import csv
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"


def register_export_parser(sub):
    p = sub.add_parser("export", help="Exporta dados da loja para CSV/Excel")
    p.add_argument("tipo", choices=["pedidos", "produtos", "avaliacoes", "tudo"],
                   help="Tipo de dado para exportar")
    p.add_argument("--formato", choices=["csv", "json"], default="csv",
                   help="Formato de saida (default: csv)")
    p.add_argument("--output", help="Arquivo de saida (opcional)")


def _get_orders() -> list[dict]:
    try:
        from shopee_agent.seller_center import SellerCenterClient, load_cookies
        session = load_cookies()
        if not session:
            return []
        sc = SellerCenterClient(session=session)
        data = sc.get_orders(limit=500)
        return data if isinstance(data, list) else data.get("orders", [])
    except Exception:
        return []


def _get_products() -> list[dict]:
    try:
        from shopee_agent.seller_center import SellerCenterClient, load_cookies
        session = load_cookies()
        if not session:
            return []
        sc = SellerCenterClient(session=session)
        data = sc.get_item_list(limit=500)
        return data.get("item_list", data.get("items", []))
    except Exception:
        return []


def _get_ratings() -> list[dict]:
    try:
        from shopee_agent.seller_center import SellerCenterClient, load_cookies
        session = load_cookies()
        if not session:
            return []
        sc = SellerCenterClient(session=session)
        data = sc.get_ratings(limit=500)
        return data if isinstance(data, list) else data.get("ratings", [])
    except Exception:
        return []


def _flatten(d: dict, parent_key: str = "", sep: str = "_") -> dict:
    items = []
    for k, v in d.items():
        nk = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten(v, nk, sep=sep).items())
        else:
            items.append((nk, v))
    return dict(items)


def _write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        print("Nenhum dado para exportar")
        return
    flat = [_flatten(r) for r in rows]
    keys = set()
    for r in flat:
        keys.update(r.keys())
    keys = sorted(keys)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in flat:
            w.writerow({k: str(r.get(k, "")) for k in keys})
    print(f"Exportado: {path} ({len(rows)} linhas)")


def _write_json(rows: list[dict], path: Path) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exportado: {path} ({len(rows)} registros)")


def handle_export(args):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = args.formato
    tipos = ["pedidos", "produtos", "avaliacoes"] if args.tipo == "tudo" else [args.tipo]
    writer = _write_csv if ext == "csv" else _write_json

    for tipo in tipos:
        output = args.output or str(REPORTS_DIR / f"export_{tipo}_{ts}.{ext}")
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)

        if tipo == "pedidos":
            data = _get_orders()
        elif tipo == "produtos":
            data = _get_products()
        elif tipo == "avaliacoes":
            data = _get_ratings()
        else:
            continue

        writer(data, path)
