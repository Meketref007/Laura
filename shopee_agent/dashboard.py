"""dashboard.py - Dashboard web FastAPI para Laura.
Mostra status da loja, metricas, logs, filas de aprovacao.

Uso: laura dashboard
     ou: python -m shopee_agent.dashboard
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time as _time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from shopee_agent.ab_test_automator import ABTestAutomator, two_proportion_z_test
from shopee_agent.api_router import API_VERSIONS, VersionedRouter
from shopee_agent.logger import info, warning
from shopee_agent.multi_tenant import TenantManager
from shopee_agent.skills.ab_testing import get_ab_registry

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl(path: Path) -> list[dict]:
    items = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                items.append(json.loads(line))
    except Exception:
        pass
    return items


def _save_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(item, ensure_ascii=False) for item in items)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


RATING_PENDING = REPORTS_DIR / "rating_replies_pending.jsonl"
CHAT_PENDING = REPORTS_DIR / "chat_pending_responses.jsonl"

# PWA push subscriptions
PUSH_SUBS_FILE = REPORTS_DIR / "push_subscriptions.jsonl"
AUTH_FILE = REPORTS_DIR / "dashboard_auth.json"


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _load_auth() -> dict:
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"ws_secret": "", "ws_tokens": [], "api_key": ""}


def _save_auth(data: dict) -> None:
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_ws_secret() -> str:
    s = os.environ.get("WS_SECRET")
    if s:
        return s
    data = _load_auth()
    s = data.get("ws_secret", "")
    if not s:
        s = str(uuid.uuid4())
        data["ws_secret"] = s
        _save_auth(data)
    return s


def _get_api_key() -> str:
    k = os.environ.get("DASHBOARD_API_KEY")
    if k:
        return k
    data = _load_auth()
    k = data.get("api_key", "")
    if not k:
        k = secrets.token_urlsafe(32)
        data["api_key"] = k
        _save_auth(data)
    return k


def generate_ws_token() -> str:
    secret = _get_ws_secret()
    exp = datetime.now() + timedelta(hours=1)
    payload = f"{exp.isoformat()}:{secrets.token_hex(16)}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def websocket_authenticate(token: str) -> bool:
    parts = token.rsplit(":", 1)
    if len(parts) != 2:
        return False
    payload, sig = parts
    secret = _get_ws_secret()
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        exp = datetime.fromisoformat(payload.split(":")[0])
        return exp > datetime.now()
    except Exception:
        return False


app = FastAPI(title="Laura Dashboard")

v_router = VersionedRouter(app)
router_v1 = v_router.get_router("v1")
router_v2 = v_router.get_router("v2")

_ab_registry = get_ab_registry()
_ab_automator = ABTestAutomator(_ab_registry)

# ── Event buffer (in-memory ring buffer, max 100 entries) ───────────────────
event_buffer: list[dict] = []
EVENT_BUFFER_MAX = 100
_start_time: float = _time.time()

_PUBLIC_API_PATHS = {"/api/v1/push/subscribe", "/api/v1/push/send", "/api/push/subscribe", "/api/push/send"}


@app.middleware("http")
async def _api_auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in _PUBLIC_API_PATHS:
        api_key = os.environ.get("DASHBOARD_API_KEY")
        if not api_key:
            api_key = _load_auth().get("api_key", "")
        if api_key:
            auth = request.headers.get("Authorization", "")
            scheme, _, token = auth.partition(" ")
            if scheme.lower() != "bearer" or token != api_key:
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)


# --- PWA / Service Worker ---

@app.get("/sw.js")
async def service_worker():
    js = """self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(clients.claim()));
self.addEventListener('push', (e) => {
  const data = e.data.json();
  self.registration.showNotification(data.title || 'Laura', {
    body: data.body || '',
    icon: data.icon || '/favicon.ico',
    badge: data.badge || '/favicon.ico',
  });
});
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil(clients.openWindow('/'));
});
"""
    return Response(content=js, media_type="application/javascript")


@app.get("/manifest.json")
async def manifest():
    return {
        "name": "Laura Dashboard",
        "short_name": "Laura",
        "start_url": "/dashboard" if FRONTEND_DIST.exists() else "/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#0f172a",
        "icons": [{"src": "/favicon.ico", "sizes": "64x64", "type": "image/x-icon"}],
    }


@app.get("/favicon.ico")
async def favicon():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#6366f1"/><text x="32" y="44" text-anchor="middle" font-size="36" fill="white" font-family="system-ui">L</text></svg>"""
    return Response(content=svg, media_type="image/svg+xml")


if FRONTEND_DIST.exists():
    index_html = FRONTEND_DIST / "index.html"

    @app.get("/dashboard/{full_path:path}")
    async def dashboard_spa(full_path: str):
        file_path = FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        if index_html.is_file():
            return HTMLResponse(content=index_html.read_text(encoding="utf-8"))
        return HTMLResponse("Frontend not built yet", status_code=404)

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_index():
        if index_html.is_file():
            return HTMLResponse(content=index_html.read_text(encoding="utf-8"))
        return await _home_inline()

    @app.get("/", response_class=HTMLResponse)
    async def home_with_frontend():
        if index_html.is_file():
            return HTMLResponse(content=index_html.read_text(encoding="utf-8"))
        return await _home_inline()

    @app.get("/assets/{full_path:path}")
    async def frontend_assets(full_path: str):
        file_path = FRONTEND_DIST / "assets" / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return HTMLResponse("Not found", status_code=404)

else:
    @app.get("/", response_class=HTMLResponse)
    async def home():
        return await _home_inline()


@router_v1.post("/push/subscribe")
async def push_subscribe(request: Request):
    body = await request.json()
    _save_jsonl(PUSH_SUBS_FILE, _load_jsonl(PUSH_SUBS_FILE) + [body])
    return {"ok": True}


@router_v1.post("/push/send")
async def push_send(request: Request):
    """Envia notificacao push para todos os inscritos."""
    body = await request.json()
    title = body.get("title", "Laura")
    message = body.get("message", "")
    subs = _load_jsonl(PUSH_SUBS_FILE)
    count = 0
    for sub in subs:
        try:
            import requests as _req
            endpoint = sub.get("endpoint", "")
            if endpoint:
                _req.post(endpoint, json={"title": title, "body": message}, timeout=5)
                count += 1
        except Exception:
            pass
    return {"ok": True, "sent": count}


# --- Approval endpoints ---

async def _home_inline():
    api_key = _get_api_key() or ""
    health = _load_json(REPORTS_DIR / "laura_health_latest.json")
    profit = _load_json(REPORTS_DIR / "laura_profitability_latest.json")
    daemon_state = _load_json(REPORTS_DIR / "laura_daemon_state.json")

    cookie_file = BASE_DIR / "secrets" / "seller_center_cookies.json"
    seller_authed = False
    if cookie_file.exists():
        try:
            data = json.loads(cookie_file.read_text(encoding="utf-8"))
            seller_authed = bool(data.get("cookies"))
        except Exception:
            pass

    margin = "N/A"
    if isinstance(profit.get("metrics"), dict):
        m = profit["metrics"].get("margin_pct")
        if m is not None:
            margin = f"{float(m):.1f}%"

    ratings_pending = len(_load_jsonl(RATING_PENDING))
    chat_pending = len(_load_jsonl(CHAT_PENDING))

    logs = _load_jsonl(REPORTS_DIR / "laura_logs.jsonl")[:20]

    daemon_cycles = daemon_state.get('cycle_count', 0)
    daemon_errors = daemon_state.get('error_count', 0)
    daemon_health = 'green' if daemon_state.get('running') else ('red' if daemon_errors > 5 else 'yellow')

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
  <meta name="theme-color" content="#6366f1">
  <link rel="manifest" href="/manifest.json">
  <title>Laura Dashboard</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:system-ui,-apple-system,sans-serif; background:#0f172a; color:#e2e8f0; padding:20px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:16px; }}
    .card {{ background:#1e293b; border-radius:12px; padding:20px; }}
    .card h2 {{ font-size:14px; text-transform:uppercase; letter-spacing:0.5px; color:#94a3b8; margin-bottom:12px; }}
    .value {{ font-size:28px; font-weight:700; }}
    .value.green {{ color:#22c55e; }}
    .value.yellow {{ color:#eab308; }}
    .value.red {{ color:#ef4444; }}
    .status {{ display:inline-block; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:600; }}
    .status.active {{ background:#22c55e20; color:#22c55e; border:1px solid #22c55e; }}
    .status.inactive {{ background:#ef444420; color:#ef4444; border:1px solid #ef4444; }}
    .meta {{ font-size:12px; color:#64748b; margin-top:8px; }}
    .section {{ margin-top:24px; }}
    .section h3 {{ font-size:13px; color:#94a3b8; margin-bottom:8px; text-transform:uppercase; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ padding:8px 12px; text-align:left; border-bottom:1px solid #334155; }}
    th {{ color:#94a3b8; font-size:11px; text-transform:uppercase; }}
    tr:hover {{ background:#1e293b; }}
    .btn {{ display:inline-block; padding:6px 16px; border-radius:6px; font-size:12px; font-weight:600; cursor:pointer; border:none; transition:opacity .2s; }}
    .btn:hover {{ opacity:.8; }}
    .btn.approve {{ background:#22c55e; color:#0f172a; }}
    .btn.reject {{ background:#ef4444; color:#fff; }}
    .btn.reload {{ background:#6366f1; color:#fff; }}
    pre {{ background:#0f172a; padding:12px; border-radius:8px; overflow-x:auto; font-size:12px; color:#a5b4fc; }}
    .tabs {{ display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }}
    .tab {{ padding:8px 16px; border-radius:6px; cursor:pointer; font-size:13px; background:#1e293b; color:#94a3b8; }}
    .tab.active {{ background:#6366f1; color:#fff; }}
    .tab-content {{ display:none; }}
    .tab-content.active {{ display:block; }}
    .log-line {{ display:flex; gap:8px; font-size:11px; color:#94a3b8; padding:2px 0; }}
    .log-line .ts {{ color:#64748b; min-width:60px; }}
    .log-line .lvl {{ min-width:40px; font-weight:600; }}
    .log-line .lvl.INFO {{ color:#22c55e; }}
    .log-line .lvl.WARN {{ color:#eab308; }}
    .log-line .lvl.ERROR {{ color:#ef4444; }}
    .log-line .msg {{ color:#e2e8f0; }}
    .toast {{ position:fixed; bottom:20px; right:20px; background:#1e293b; border:1px solid #334155; border-radius:8px; padding:12px 20px; font-size:13px; opacity:0; transition:opacity .3s; pointer-events:none; z-index:100; }}
    .toast.show {{ opacity:1; }}
    @media (max-width:600px) {{ .grid {{ grid-template-columns:1fr; }} body {{ padding:12px; }} }}
  </style>
</head>
<body>
  <h1 style="margin-bottom:12px; font-size:22px;">Laura Dashboard</h1>
  <div class="store-selector" style="display:flex;align-items:center;gap:8px;margin-bottom:16px;flex-wrap:wrap">
    <label for="dash-store-select" style="font-size:12px;color:#94a3b8;text-transform:uppercase">Loja:</label>
    <select id="dash-store-select" onchange="location.href='/summary?store='+this.value" style="padding:8px 12px;border-radius:6px;background:#1e293b;color:#e2e8f0;border:1px solid #334155;font-size:13px;min-width:200px">
      <option value="">Todas</option>
    </select>
  </div>
  <div class="grid">
    <div class="card">
      <h2>Saude da Loja</h2>
      <div class="value green" id="health-score">{health.get('health_score', 'N/A')}</div>
      <div class="meta">Seller Center: <span class="status {'active' if seller_authed else 'inactive'}" id="seller-status">{'Autenticado' if seller_authed else 'Nao autenticado'}</span></div>
    </div>
    <div class="card">
      <h2>Margem</h2>
      <div class="value {'green' if margin != 'N/A' and float(margin.replace('%','')) > 15 else 'yellow' if margin != 'N/A' else 'red'}" id="margin-value">{margin}</div>
      <div class="meta" id="margin-decision">Decisao: {profit.get('action_key', profit.get('decision', 'N/A'))}</div>
    </div>
    <div class="card">
      <h2>Daemon</h2>
      <div class="value {daemon_health}" id="daemon-status">{'Rodando' if daemon_state.get('running') else 'Parado'}</div>
      <div class="meta" id="daemon-meta">{daemon_cycles} ciclos | {daemon_errors} erros</div>
      <div class="meta" id="daemon-last-cycle">Ultimo: {daemon_state.get('last_cycle', 'N/A')}</div>
    </div>
    <div class="card">
      <h2>Aprovacoes Pendentes</h2>
      <div class="value {'yellow' if ratings_pending > 0 else 'green'}" id="pending-count">{ratings_pending + chat_pending}</div>
      <div class="meta" id="pending-meta">{ratings_pending} avaliacoes | {chat_pending} chats</div>
    </div>
  </div>

  <div style="margin-top:8px;text-align:right;font-size:11px;color:#475569;" id="refresh-timestamp">Ultima atualizacao: agora</div>

  <div class="section">
    <h3>Filas de Aprovacao</h3>
    <div class="tabs">
      <div class="tab active" onclick="switchTab('ratings', this)">Avaliacoes ({ratings_pending})</div>
      <div class="tab" onclick="switchTab('chats', this)">Chats ({chat_pending})</div>
    </div>

    <div id="tab-ratings" class="tab-content active">
      <table>
        <tr><th>Comprador</th><th>Estrelas</th><th>Comentario</th><th>Resposta</th><th>Acao</th></tr>
        {_rating_table()}
      </table>
    </div>

    <div id="tab-chats" class="tab-content">
      <table>
        <tr><th>Comprador</th><th>Mensagem</th><th>Resposta</th><th>Acao</th></tr>
        {_chat_table()}
      </table>
    </div>
  </div>

  <div class="section">
    <h3>Ultimos Eventos</h3>
    <div id="log-list">
    {''.join(f'<div class="log-line"><span class="ts">{l.get("time","")[-8:]}</span><span class="lvl {l.get("level","INFO")}">{l.get("level","INFO")}</span><span class="msg">{l.get("message","")[:80]}</span></div>' for l in logs)}
    </div>
  </div>

  <div class="section">
    <h3>Metricas Detalhadas</h3>
    <pre>{json.dumps(health, indent=2, ensure_ascii=False)[:1000]}</pre>
  </div>

  <div style="margin-top:24px; text-align:center; font-size:12px; color:#475569;">
    <button class="btn reload" onclick="location.reload()">Atualizar</button>
    <button class="btn" style="background:#6366f1;color:#fff;" onclick="subscribePush()">Ativar Notificacoes</button>
  </div>

  <div id="toast" class="toast"></div>

  <script>
  const API_KEY = '{api_key}';
  const _origFetch = window.fetch;
  window.fetch = function(url, opts) {{
    if (typeof url === 'string' && url.startsWith('/api/') && !url.includes('/push/')) {{
      opts = opts || {{}};
      opts.headers = opts.headers || {{}};
      opts.headers['Authorization'] = 'Bearer ' + API_KEY;
    }}
    return _origFetch.call(window, url, opts);
  }};
  if('serviceWorker' in navigator) {{
    navigator.serviceWorker.register('/sw.js');
  }}
  // Load stores for dashboard selector
  fetch('/api/stores').then(r=>r.json()).then(d => {{
    const sel = document.getElementById('dash-store-select');
    if (sel) {{
      (d.stores || []).forEach(s => {{
        const opt = document.createElement('option');
        opt.value = s.store_id;
        opt.textContent = s.store_id;
        sel.appendChild(opt);
      }});
    }}
  }}).catch(()=>{{}});

  // Helper functions for auto-refresh
  function _q(id) {{ return document.getElementById(id); }}
  function _st(id, text) {{ const e=_q(id); if(e) e.textContent = text; }}
  function _sc(id, cls) {{ const e=_q(id); if(e) e.className = cls; }}

  // Auto-refresh a cada 30s — atualiza o DOM e mostra toast
  setInterval(() => {{ fetch('/api/status').then(r=>r.json()).then(d => {{
    const h = d.health || {{}};
    _st('health-score', h.health_score ?? 'N/A');
    const sa = !!d.seller_center;
    _st('seller-status', sa ? 'Autenticado' : 'Nao autenticado');
    _sc('seller-status', 'status ' + (sa ? 'active' : 'inactive'));
    const mp = h.metrics?.margin_pct;
    if (mp != null) {{ _st('margin-value', Number(mp).toFixed(1) + '%'); _sc('margin-value', 'value ' + (mp > 15 ? 'green' : 'yellow')); }}
    else {{ _st('margin-value', 'N/A'); _sc('margin-value', 'value red'); }}
    const run = !!d.running;
    _st('daemon-status', run ? 'Rodando' : 'Parado');
    _sc('daemon-status', 'value ' + (run ? 'green' : 'red'));
    _st('daemon-meta', (h.cycle_count ?? 0) + ' ciclos | ' + (h.error_count ?? 0) + ' erros');
    _st('daemon-last-cycle', 'Ultimo: ' + (h.last_cycle ?? 'N/A'));
    const pend = d.pending_ratings + d.pending_chats;
    _st('pending-count', pend);
    _sc('pending-count', 'value ' + (pend > 0 ? 'yellow' : 'green'));
    _st('pending-meta', d.pending_ratings + ' avaliacoes | ' + d.pending_chats + ' chats');
    _st('refresh-timestamp', 'Ultima atualizacao: ' + new Date().toLocaleTimeString());
    showToast('Dados atualizados ' + new Date().toLocaleTimeString());
  }}).catch(()=>{{}}); }}, 30000);

  async function subscribePush() {{
    try {{
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({{userVisibleOnly: true, applicationServerKey: null}});
      await fetch('/api/push/subscribe', {{method:'POST', body: JSON.stringify(sub.toJSON()), headers:{{'Content-Type':'application/json'}}}});
      showToast('Notificacoes ativadas!');
    }} catch(e) {{
      showToast('Erro: ' + e.message);
    }}
  }}

  function switchTab(name, el) {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    el.classList.add('active');
    document.getElementById('tab-' + name).classList.add('active');
  }}

  function approve(action, idx) {{
    fetch('/api/approve/' + action + '/' + idx, {{method:'POST'}})
      .then(r => r.json()).then(d => {{ if(d.ok) location.reload(); else showToast('Erro: '+d.error); }})
      .catch(e => showToast('Erro: '+e.message));
  }}

  function reject(action, idx) {{
    fetch('/api/reject/' + action + '/' + idx, {{method:'POST'}})
      .then(r => r.json()).then(d => {{ if(d.ok) location.reload(); else showToast('Erro: '+d.error); }})
      .catch(e => showToast('Erro: '+e.message));
  }}

  function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
  }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


def _rating_table() -> str:
    rows = []
    for i, item in enumerate(_load_jsonl(RATING_PENDING)):
        rows.append(f"""<tr>
<td>{item.get('buyer', '?')}</td>
<td>{item.get('stars', '?')}</td>
<td>{item.get('comment', '')[:60]}</td>
<td>{item.get('reply', '')[:60]}</td>
<td>
  <button class="btn approve" onclick="approve('rating',{i})">Aprovar</button>
  <button class="btn reject" onclick="reject('rating',{i})">Rejeitar</button>
</td></tr>""")
    if not rows:
        return '<tr><td colspan="5">Nenhuma pendente</td></tr>'
    return "".join(rows)


def _chat_table() -> str:
    rows = []
    for i, item in enumerate(_load_jsonl(CHAT_PENDING)):
        rows.append(f"""<tr>
<td>{item.get('buyer_name', item.get('buyer_id', '?'))}</td>
<td>{item.get('message', '')[:60]}</td>
<td>{item.get('response', '')[:60]}</td>
<td>
  <button class="btn approve" onclick="approve('chat',{i})">Aprovar</button>
  <button class="btn reject" onclick="reject('chat',{i})">Rejeitar</button>
</td></tr>""")
    if not rows:
        return '<tr><td colspan="4">Nenhuma pendente</td></tr>'
    return "".join(rows)


@router_v1.post("/approve/rating/{idx}")
async def approve_rating(idx: int):
    items = _load_jsonl(RATING_PENDING)
    if idx < 0 or idx >= len(items):
        return {"ok": False, "error": "indice invalido"}
    item = items.pop(idx)
    _save_jsonl(RATING_PENDING, items)
    try:
        from shopee_agent.rating_reply import enviar_resposta_avaliacao
        r = enviar_resposta_avaliacao(item.get("order_sn", ""), item.get("reply", ""))
        return {"ok": True, "result": r}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router_v1.post("/reject/rating/{idx}")
async def reject_rating(idx: int):
    items = _load_jsonl(RATING_PENDING)
    if idx < 0 or idx >= len(items):
        return {"ok": False, "error": "indice invalido"}
    item = items.pop(idx)
    _save_jsonl(RATING_PENDING, items)
    return {"ok": True, "rejected": item.get("order_sn", "")}


@router_v1.post("/approve/chat/{idx}")
async def approve_chat(idx: int):
    items = _load_jsonl(CHAT_PENDING)
    if idx < 0 or idx >= len(items):
        return {"ok": False, "error": "indice invalido"}
    item = items.pop(idx)
    _save_jsonl(CHAT_PENDING, items)
    try:
        from shopee_agent.chat_auto import send_chat_response
        r = send_chat_response(item.get("buyer_id", ""), item.get("response", ""))
        return {"ok": True, "result": r}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router_v1.post("/reject/chat/{idx}")
async def reject_chat(idx: int):
    items = _load_jsonl(CHAT_PENDING)
    if idx < 0 or idx >= len(items):
        return {"ok": False, "error": "indice invalido"}
    item = items.pop(idx)
    _save_jsonl(CHAT_PENDING, items)
    return {"ok": True, "rejected": item.get("buyer_id", "")}


@router_v1.get("/stores")
async def api_stores():
    try:
        manager = TenantManager()
        stores = manager.list_tenants()
        return {"stores": stores, "total": len(stores)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router_v1.get("/stores/{store_id}/summary")
async def api_store_summary(store_id: str):
    try:
        manager = TenantManager()
        tenant = manager.get_tenant(store_id)
        if tenant is None:
            return JSONResponse(status_code=404, content={"error": f"Store '{store_id}' not found"})
        tenant_dir = manager.tenant_dir(store_id)
        health = _load_json(tenant_dir / "reports" / "laura_health_latest.json")
        profit = _load_json(tenant_dir / "reports" / "laura_profitability_latest.json")
        daemon = _load_json(tenant_dir / "reports" / "laura_daemon_state.json")
        return {
            "store_id": store_id,
            "enabled": tenant.enabled,
            "shop_id": tenant.shop_id,
            "created_at": tenant.created_at,
            "last_active": tenant.last_active,
            "health": health,
            "profitability": profit,
            "daemon_state": daemon,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router_v1.get("/health")
async def api_health():
    return _load_json(REPORTS_DIR / "laura_health_latest.json")


@router_v1.get("/profitability")
async def api_profitability():
    return _load_json(REPORTS_DIR / "laura_profitability_latest.json")


@router_v1.get("/skills")
async def api_skills():
    """Skill metrics: registered skills, history summary, learning data."""
    import json as _json
    from pathlib import Path as _Path

    reports = _Path("reports")
    history_file = reports / "skill_execution_history.jsonl"
    learning_file = reports / "goap_learning.json"

    registered: list[str] = []
    try:
        from shopee_agent.skills.loader import discover_and_register
        from shopee_agent.skills.registry import default_registry
        discover_and_register()
        registered = default_registry.list()
    except Exception:
        pass

    history: list[dict] = []
    total_executions = 0
    if history_file.exists():
        try:
            lines = history_file.read_text(encoding="utf-8").splitlines()
            total_executions = len(lines)
            for line in lines[-100:]:
                if line.strip():
                    history.append(_json.loads(line))
        except Exception:
            pass

    success_rate = 0.0
    if history:
        ok_count = sum(1 for h in history if h.get("ok"))
        success_rate = round(ok_count / len(history) * 100, 1)

    learning = {}
    if learning_file.exists():
        try:
            learning = _json.loads(learning_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    per_skill: dict[str, dict] = {}
    for h in history:
        name = h.get("skill", "unknown")
        if name not in per_skill:
            per_skill[name] = {"executions": 0, "ok": 0, "fail": 0, "total_elapsed_ms": 0}
        per_skill[name]["executions"] += 1
        if h.get("ok"):
            per_skill[name]["ok"] += 1
        else:
            per_skill[name]["fail"] += 1

    for name, stats in per_skill.items():
        stats["success_rate_pct"] = round(stats["ok"] / stats["executions"] * 100, 1) if stats["executions"] else 0

    return {
        "registered_skills": registered,
        "registered_count": len(registered),
        "total_executions": total_executions,
        "success_rate_pct": success_rate,
        "per_skill": per_skill,
        "learning": learning,
        "recent_history": history[-20:],
    }


@router_v1.get("/skill-health")
async def api_skill_health():
    """Health metrics per skill: latency p50/p95, error rate, circuit breaker status."""
    import json as _j
    from pathlib import Path as _P

    from shopee_agent.skills.sandbox import _breakers, _rate_limiter

    reports = _P("reports")
    history_file = reports / "skill_execution_history.jsonl"

    per_skill: dict[str, dict] = {}
    latencies: dict[str, list[float]] = {}

    if history_file.exists():
        try:
            lines = history_file.read_text(encoding="utf-8").splitlines()
            for line in lines:
                if not line.strip():
                    continue
                entry = _j.loads(line)
                name = entry.get("skill", "unknown")
                if name not in per_skill:
                    per_skill[name] = {"executions": 0, "ok": 0, "fail": 0, "total_elapsed_ms": 0.0}
                    latencies[name] = []
                per_skill[name]["executions"] += 1
                if entry.get("ok"):
                    per_skill[name]["ok"] += 1
                else:
                    per_skill[name]["fail"] += 1
                elapsed = float(entry.get("elapsed", 0) or 0)
                per_skill[name]["total_elapsed_ms"] += elapsed
                latencies[name].append(elapsed)
        except Exception:
            pass

    result: dict[str, Any] = {}
    for name, stats in per_skill.items():
        total = stats["executions"]
        errors = stats["fail"]
        error_rate = round(errors / total * 100, 1) if total else 0.0
        avg_latency = round(stats["total_elapsed_ms"] / total, 2) if total else 0.0
        lats = sorted(latencies.get(name, []))
        p50 = round(lats[len(lats) // 2], 3) if lats else 0.0
        p95 = round(lats[int(len(lats) * 0.95)], 3) if len(lats) >= 20 else (lats[-1] if lats else 0.0)
        breaker = _breakers.get(name)
        circuit_state = str(breaker.state.name) if breaker else "closed"
        remaining = _rate_limiter.remaining(name)
        result[name] = {
            "executions": total,
            "error_rate_pct": error_rate,
            "success_rate_pct": round(stats["ok"] / total * 100, 1) if total else 0.0,
            "avg_latency_ms": avg_latency,
            "p50_ms": p50,
            "p95_ms": p95,
            "circuit_state": circuit_state,
            "rate_remaining": remaining,
        }

    return {"skills": result, "total_skills": len(result)}


@router_v1.get("/goap-graph")
async def api_goap_graph():
    """Return GOAP action graph as nodes + edges for visualization."""
    try:
        from shopee_agent.skills.loader import discover_and_register
        from shopee_agent.skills.registry import default_registry
        discover_and_register()
        nodes: list[dict] = []
        edges: list[dict] = []
        for name in default_registry.list():
            cls = default_registry.get(name)
            if cls is None:
                continue
            pre = dict(getattr(cls, "preconditions", {}))
            eff = dict(getattr(cls, "effects", {}))
            cost = float(getattr(cls, "cost", 1.0))
            prio = int(getattr(cls, "priority", 0))
            nodes.append({"id": name, "cost": cost, "priority": prio, "preconditions": list(pre.keys()), "effects": list(eff.keys())})
            for pk in pre:
                edges.append({"from": pk, "to": name, "label": f"pre:{pre[pk]}"})
            for ek in eff:
                edges.append({"from": name, "to": ek, "label": f"eff:{eff[ek]}"})
        return {"nodes": nodes, "edges": edges}
    except Exception as exc:
        return {"error": str(exc)}


@router_v1.get("/goap-timeline")
async def api_goap_timeline():
    """Return GOAP plan execution timeline for visualization."""
    import json as _j
    from pathlib import Path as _P
    reports = _P("reports")
    history_file = reports / "skill_execution_history.jsonl"
    events: list[dict] = []
    if history_file.exists():
        try:
            lines = history_file.read_text(encoding="utf-8").splitlines()
            for line in lines[-100:]:
                if line.strip():
                    entry = _j.loads(line)
                    events.append({
                        "timestamp": entry.get("timestamp", ""),
                        "skill": entry.get("skill", ""),
                        "ok": entry.get("ok", False),
                        "elapsed": entry.get("elapsed", 0),
                    })
        except Exception:
            pass
    return {"events": events}


@router_v1.get("/goap-cost-history")
async def api_goap_cost_history(skill_name: str = ""):
    """Return cost history from LearningDB for charting."""
    try:
        from shopee_agent.goap_planner import GOAPPlanner
        planner = GOAPPlanner(use_sqlite=True)
        if skill_name:
            stats = planner.get_learning_stats(skill_name)
            return {"cost_history": [stats]}
        summary = planner.get_learning_summary()
        overrides = summary.get("cost_overrides", {})
        if isinstance(overrides, dict):
            data = []
            for sname, info in overrides.items():
                if isinstance(info, dict):
                    data.append({"skill": sname, "current_cost": info.get("current_cost", 0), "executions": info.get("executions", 0), "success_rate": info.get("success_rate", 0)})
                else:
                    data.append({"skill": sname, "current_cost": float(info), "executions": 0, "success_rate": 0.0})
            return {"cost_history": data, "total": len(data)}
        return {"cost_history": []}
    except Exception as exc:
        return {"cost_history": [], "error": str(exc)}


@router_v1.get("/goal-synthesize")
async def api_goal_synthesize(margin_pct: float = 25.0, low_margin: int = 0, low_stock: int = 0, refund_pct: float = 0.0):
    """Synthesize a GOAP goal from business KPIs."""
    from shopee_agent.skills.goal_synthesizer import synthesize_goal
    goal = synthesize_goal(
        margin_pct=margin_pct,
        low_margin_count=low_margin,
        low_stock_count=low_stock,
        refund_rate_pct=refund_pct,
    )
    return {"goal": goal, "description": " + ".join(goal.keys())}


@router_v1.get("/ws-token")
async def api_ws_token():
    """Return a valid WebSocket auth token."""
    return {"token": generate_ws_token()}


# ── A/B Testing API ──────────────────────────────────────────────────────────


@router_v1.get("/ab-tests/stats")
async def api_ab_tests_stats():
    """Aggregated A/B test statistics."""
    summary = _ab_registry.summary()
    total = len(summary)
    active = 0
    promoted = 0
    total_confidence = 0.0
    confidence_count = 0
    for test_id, test in summary.items():
        if _ab_automator._is_promoted(test_id):
            promoted += 1
        else:
            active += 1
        c = test["outcomes"]["control"]
        v = test["outcomes"]["variant"]
        if c["executions"] >= 10 and v["executions"] >= 10:
            try:
                _, p_value = two_proportion_z_test(
                    c["successes"], c["executions"],
                    v["successes"], v["executions"],
                )
                total_confidence += 1.0 - p_value
                confidence_count += 1
            except Exception:
                pass
    avg_confidence = round(total_confidence / confidence_count, 4) if confidence_count else 0.0
    return {
        "total_tests": total,
        "active": active,
        "promoted": promoted,
        "avg_confidence": avg_confidence,
    }


@router_v1.get("/ab-tests")
async def api_ab_tests():
    """Return all A/B tests from the registry."""
    return _ab_registry.summary()


@router_v1.get("/ab-tests/{test_id}")
async def api_ab_test_detail(test_id: str):
    """Return detailed data for a single A/B test."""
    summary = _ab_registry.summary()
    if test_id not in summary:
        return JSONResponse(status_code=404, content={"error": f"Test '{test_id}' not found"})
    test = summary[test_id]
    is_promoted = _ab_automator._is_promoted(test_id)
    c = test["outcomes"]["control"]
    v = test["outcomes"]["variant"]
    confidence = 0.0
    z_score = 0.0
    if c["executions"] > 0 and v["executions"] > 0:
        try:
            z, p = two_proportion_z_test(c["successes"], c["executions"], v["successes"], v["executions"])
            z_score = round(z, 4)
            confidence = round(1.0 - p, 4)
        except Exception:
            pass
    return {
        **test,
        "test_id": test_id,
        "is_promoted": is_promoted,
        "confidence": confidence,
        "z_score": z_score,
        "control_rate": round(c["successes"] / c["executions"], 4) if c["executions"] else 0,
        "variant_rate": round(v["successes"] / v["executions"], 4) if v["executions"] else 0,
    }


@router_v1.post("/ab-tests/{test_id}/promote")
async def api_ab_test_promote(test_id: str):
    """Manually trigger promotion evaluation for a test."""
    result = _ab_automator.evaluate_and_promote(test_id)
    result["test_id"] = test_id
    return result


_AB_TESTING_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Laura — A/B Testing</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;padding:16px}
h1{font-size:20px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-bottom:16px}
.card{background:#1e293b;border-radius:10px;padding:16px}
.card h2{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;margin-bottom:8px}
.val{font-size:24px;font-weight:700}
.val.green{color:#22c55e}
.val.yellow{color:#eab308}
.val.red{color:#ef4444}
.val.indigo{color:#a5b4fc}
.sub{font-size:11px;color:#64748b;margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #334155}
th{color:#94a3b8;font-size:11px;text-transform:uppercase}
tr:hover{background:#1e293b;cursor:pointer}
tr.selected{background:#273549}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600}
.badge.active{background:rgba(34,197,94,.12);color:#22c55e;border:1px solid #22c55e}
.badge.promoted{background:rgba(99,102,241,.12);color:#a5b4fc;border:1px solid #a5b4fc}
.badge.pending{background:rgba(234,179,8,.12);color:#eab308;border:1px solid #eab308}
.badge.insufficient{background:rgba(100,116,139,.12);color:#94a3b8;border:1px solid #334155}
.bar-bg{background:#334155;border-radius:4px;height:16px;overflow:hidden;margin:4px 0}
.bar-fill{height:100%;border-radius:4px;transition:width .5s}
.btn{display:inline-block;padding:8px 16px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;border:none;transition:opacity .2s}
.btn:hover{opacity:.85}
.btn.primary{background:#6366f1;color:#fff}
.btn.green{background:#22c55e;color:#0f172a}
.btn:disabled{opacity:.4;cursor:not-allowed}
.detail-panel{display:none;margin-top:16px}
.detail-panel.visible{display:block}
.chart-wrap{display:flex;gap:24px;flex-wrap:wrap;align-items:flex-end;margin:12px 0;min-height:180px}
.chart-col{flex:1;min-width:200px;text-align:center}
.chart-col .label{font-size:12px;color:#94a3b8;margin-bottom:4px}
.chart-col .bar{width:60px;margin:0 auto;border-radius:6px 6px 0 0;transition:height .5s;min-height:4px}
.chart-col .bar.control{background:#6366f1}
.chart-col .bar.variant{background:#22c55e}
.chart-col .bar-val{font-size:14px;font-weight:700;margin-top:4px}
.gauge-wrap{text-align:center;margin:12px 0}
.gauge-svg{width:140px;height:140px}
.gauge-svg circle{fill:none;stroke-width:10}
.gauge-svg .bg{stroke:#334155}
.gauge-svg .fg{stroke:#22c55e;stroke-linecap:round;transform:rotate(-90deg);transform-origin:center}
.gauge-svg text{font-size:22px;font-weight:700;fill:#e2e8f0;text-anchor:middle;dominant-baseline:central}
.gauge-label{font-size:12px;color:#94a3b8;margin-top:4px}
.row{display:flex;gap:16px;flex-wrap:wrap;margin:8px 0}
.stat-box{background:#0f172a;border-radius:6px;padding:10px 14px;text-align:center;flex:1;min-width:100px}
.stat-box .num{font-size:18px;font-weight:700}
.stat-box .lbl{font-size:10px;color:#64748b;text-transform:uppercase}
.mt-8{margin-top:8px}
.toast{position:fixed;bottom:20px;right:20px;background:#1e293b;border:1px solid #334155;border-radius:8px;padding:12px 20px;font-size:13px;opacity:0;transition:opacity .3s;pointer-events:none;z-index:100}
.toast.show{opacity:1}
</style>
</head>
<body>
<h1>A/B Testing</h1>
<div class="grid" id="stats-grid">
  <div class="card"><h2>Total Testes</h2><div class="val indigo" id="stat-total">--</div></div>
  <div class="card"><h2>Ativos</h2><div class="val green" id="stat-active">--</div></div>
  <div class="card"><h2>Promovidos</h2><div class="val" id="stat-promoted" style="color:#a5b4fc">--</div></div>
  <div class="card"><h2>Confianca Media</h2><div class="val" id="stat-confidence">--</div><div class="sub">media dos testes com dados</div></div>
</div>

<div class="card" style="padding:0;overflow:auto">
  <table id="tests-table">
    <thead><tr><th>Teste</th><th>Controle</th><th>Variante</th><th>Exec.</th><th>Status</th><th>Confianca</th></tr></thead>
    <tbody id="tests-body"><tr><td colspan="6" style="color:#64748b;text-align:center;padding:20px">Carregando...</td></tr></tbody>
  </table>
</div>

<div class="detail-panel card" id="detail-panel">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px">
    <h3 id="detail-title" style="font-size:16px">--</h3>
    <span class="badge" id="detail-badge">--</span>
  </div>
  <div class="row">
    <div class="stat-box"><div class="num" id="detail-exec-control">0</div><div class="lbl">Exec. Controle</div></div>
    <div class="stat-box"><div class="num" id="detail-exec-variant">0</div><div class="lbl">Exec. Variante</div></div>
    <div class="stat-box"><div class="num" id="detail-split">50%</div><div class="lbl">Traffic Split</div></div>
    <div class="stat-box"><div class="num" id="detail-zscore">0.00</div><div class="lbl">Z-Score</div></div>
  </div>
  <div class="chart-wrap">
    <div class="chart-col">
      <div class="label">Controle</div>
      <div class="bar control" id="bar-control" style="height:4px"></div>
      <div class="bar-val" id="bar-control-val" style="color:#a5b4fc">0%</div>
    </div>
    <div class="chart-col">
      <div class="label">Variante</div>
      <div class="bar variant" id="bar-variant" style="height:4px"></div>
      <div class="bar-val" id="bar-variant-val" style="color:#22c55e">0%</div>
    </div>
  </div>
  <div class="gauge-wrap">
    <svg class="gauge-svg" viewBox="0 0 120 120">
      <circle class="bg" cx="60" cy="60" r="50"/>
      <circle class="fg" id="gauge-arc" cx="60" cy="60" r="50" stroke-dasharray="314.159" stroke-dashoffset="314.159"/>
      <text x="60" y="60" id="gauge-text">0%</text>
    </svg>
    <div class="gauge-label">Confianca Estatistica</div>
  </div>
  <div id="detail-reason" style="font-size:12px;color:#94a3b8;margin:8px 0"></div>
  <button class="btn primary" id="promote-btn" onclick="promoteTest()">Avaliar & Promover</button>
  <span id="promote-result" style="margin-left:12px;font-size:12px"></span>
</div>

<div id="toast" class="toast"></div>

<script>
const API_KEY = '__API_KEY__';
const _fetch = window.fetch;
window.fetch = function(url, opts) {
  if (typeof url === 'string' && url.startsWith('/api/')) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers['Authorization'] = 'Bearer ' + API_KEY;
  }
  return _fetch.call(window, url, opts);
};

let _testsData = {};
let _selectedTest = null;

function fmtPct(v) { return (v * 100).toFixed(1) + '%'; }
function showToast(msg) { const t=document.getElementById('toast'); t.textContent=msg; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),3000); }

async function loadStats() {
  try {
    const s = await fetch('/api/ab-tests/stats').then(r=>r.json());
    document.getElementById('stat-total').textContent = s.total_tests ?? 0;
    document.getElementById('stat-active').textContent = s.active ?? 0;
    document.getElementById('stat-promoted').textContent = s.promoted ?? 0;
    document.getElementById('stat-confidence').textContent = (s.avg_confidence * 100).toFixed(1) + '%';
  } catch(e) { showToast('Erro ao carregar stats'); }
}

async function loadTests() {
  try {
    const data = await fetch('/api/ab-tests').then(r=>r.json());
    _testsData = data;
    const tbody = document.getElementById('tests-body');
    const keys = Object.keys(data);
    if (keys.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:#64748b;text-align:center;padding:20px">Nenhum teste ativo</td></tr>';
      return;
    }
    let html = '';
    for (const testId of keys) {
      const t = data[testId];
      const c = t.outcomes.control;
      const v = t.outcomes.variant;
      const totalExec = c.executions + v.executions;
      const cRate = c.executions ? (c.successes / c.executions * 100).toFixed(1) : '0.0';
      const vRate = v.executions ? (v.successes / v.executions * 100).toFixed(1) : '0.0';
      const winner = t.winner;
      let badge, badgeText;
      const isPromoted = !!t.promoted_winner;
      if (isPromoted) { badge='promoted'; badgeText='Promovido: '+t.promoted_winner; }
      else if (winner) { badge='active'; badgeText='Vencedor: '+winner; }
      else if (c.executions < 10 || v.executions < 10) { badge='insufficient'; badgeText='Poucos dados'; }
      else { badge='pending'; badgeText='Empate'; }
      html += '<tr onclick="selectTest(\'' + testId + '\')" data-id="' + testId + '">' +
        '<td style="font-weight:600">' + testId + '</td>' +
        '<td>' + t.control + '</td>' +
        '<td>' + t.variant + '</td>' +
        '<td>' + totalExec + '</td>' +
        '<td><span class="badge ' + badge + '">' + badgeText + '</span></td>' +
        '<td>' + (c.executions >= 10 && v.executions >= 10 ? cRate + '% / ' + vRate + '%' : '--') + '</td>' +
        '</tr>';
    }
    tbody.innerHTML = html;
  } catch(e) { showToast('Erro ao carregar testes'); }
}

async function selectTest(testId) {
  _selectedTest = testId;
  document.querySelectorAll('#tests-body tr').forEach(r => r.classList.remove('selected'));
  const row = document.querySelector('[data-id="' + testId + '"]');
  if (row) row.classList.add('selected');
  try {
    const detail = await fetch('/api/ab-tests/' + encodeURIComponent(testId)).then(r=>r.json());
    const panel = document.getElementById('detail-panel');
    panel.classList.add('visible');
    panel.scrollIntoView({behavior:'smooth', block:'nearest'});
    document.getElementById('detail-title').textContent = testId;
    const c = detail.outcomes.control;
    const v = detail.outcomes.variant;
    document.getElementById('detail-exec-control').textContent = c.executions;
    document.getElementById('detail-exec-variant').textContent = v.executions;
    document.getElementById('detail-split').textContent = (detail.traffic_split * 100).toFixed(0) + '%';
    document.getElementById('detail-zscore').textContent = detail.z_score.toFixed(3);
    const cRate = c.executions ? (c.successes / c.executions) : 0;
    const vRate = v.executions ? (v.successes / v.executions) : 0;
    const maxH = Math.max(cRate, vRate, 0.01) * 160;
    document.getElementById('bar-control').style.height = Math.max(cRate * 160, 4) + 'px';
    document.getElementById('bar-variant').style.height = Math.max(vRate * 160, 4) + 'px';
    document.getElementById('bar-control-val').textContent = fmtPct(cRate);
    document.getElementById('bar-variant-val').textContent = fmtPct(vRate);
    const badge = document.getElementById('detail-badge');
    if (detail.is_promoted) {
      badge.className = 'badge promoted';
      badge.textContent = 'Promovido: ' + detail.promoted_winner;
    } else if (detail.winner) {
      badge.className = 'badge active';
      badge.textContent = 'Vencedor: ' + detail.winner;
    } else if (c.executions < 10 || v.executions < 10) {
      badge.className = 'badge insufficient';
      badge.textContent = 'Dados insuficientes';
    } else {
      badge.className = 'badge pending';
      badge.textContent = 'Sem vencedor';
    }
    const gaugeArc = document.getElementById('gauge-arc');
    const circ = 2 * Math.PI * 50;
    const confidence = detail.confidence || 0;
    const offset = circ * (1 - confidence);
    gaugeArc.setAttribute('stroke-dasharray', circ);
    gaugeArc.setAttribute('stroke-dashoffset', offset);
    gaugeArc.setAttribute('stroke', confidence >= 0.95 ? '#22c55e' : confidence >= 0.8 ? '#eab308' : '#ef4444');
    document.getElementById('gauge-text').textContent = (confidence * 100).toFixed(1) + '%';
    document.getElementById('detail-reason').textContent = '';
    document.getElementById('promote-result').textContent = '';
    document.getElementById('promote-btn').disabled = false;
  } catch(e) { showToast('Erro ao carregar detalhe'); }
}

async function promoteTest() {
  if (!_selectedTest) return;
  const btn = document.getElementById('promote-btn');
  const resultEl = document.getElementById('promote-result');
  btn.disabled = true;
  resultEl.textContent = 'Avaliando...';
  try {
    const r = await fetch('/api/ab-tests/' + encodeURIComponent(_selectedTest) + '/promote', {method:'POST'}).then(r=>r.json());
    if (r.promoted) {
      resultEl.innerHTML = '<span style="color:#22c55e">Promovido: ' + r.winner + ' (' + (r.confidence*100).toFixed(1) + '% confianca)</span>';
      showToast('Teste promovido com sucesso!');
    } else {
      resultEl.innerHTML = '<span style="color:#eab308">' + r.reason + '</span>';
    }
    await Promise.all([loadStats(), loadTests()]);
    if (_selectedTest) selectTest(_selectedTest);
  } catch(e) {
    resultEl.textContent = 'Erro: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

loadStats();
loadTests();
</script>
</body>
</html>"""


# ── Web UI Pages ─────────────────────────────────────────────────────────────

@app.get("/goap", response_class=HTMLResponse)
async def goap_page():
    return HTMLResponse(_GOAP_HTML)


@app.get("/skill-health", response_class=HTMLResponse)
async def skill_health_page():
    return HTMLResponse(_SKILL_HEALTH_HTML)


@app.get("/goap-graph", response_class=HTMLResponse)
async def goap_graph_page():
    return HTMLResponse(_GOAP_GRAPH_HTML)


@app.get("/ws-demo", response_class=HTMLResponse)
async def ws_demo_page():
    token = generate_ws_token()
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><title>WS Stream</title>
<style>body{{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:20px}}
#log{{white-space:pre-wrap;font-size:12px;max-height:80vh;overflow-y:auto}}
h1{{color:#58a6ff}}</style></head><body>
<h1>Real-time State Stream</h1>
<div id="log">Connecting...</div>
<script>
const ws=new WebSocket('ws://'+location.host+'/ws/stream');
const log=document.getElementById('log');
ws.onmessage=(ev)=>{{log.innerHTML+=ev.data+'\\n';log.scrollTop=log.scrollHeight}};
ws.onopen=()=>{{ws.send(JSON.stringify({{type:'auth',token:'{token}'}}));log.innerHTML='Connected\\n'}};
ws.onclose=()=>{{log.innerHTML+='\\nDisconnected'}};
</script></body></html>""")


_connected_websockets: list[WebSocket] = []


@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket):
    await websocket.accept()
    authed = False
    try:
        msg = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        if msg.get("type") == "auth" and websocket_authenticate(msg.get("token", "")):
            authed = True
    except (TimeoutError, Exception):
        pass
    if not authed:
        await websocket.close(code=4001)
        return
    _connected_websockets.append(websocket)
    try:
        while True:
            await asyncio.sleep(2)
            payload: dict[str, Any] = {
                "type": "state_update",
                "timestamp": datetime.now().isoformat(),
                "health_summary": _load_json(REPORTS_DIR / "laura_health_latest.json"),
                "daemon_state": _load_json(REPORTS_DIR / "laura_daemon_state.json"),
                "pending_ratings": len(_load_jsonl(RATING_PENDING)),
                "pending_chats": len(_load_jsonl(CHAT_PENDING)),
                "recent_events": event_buffer[-10:] if event_buffer else [],
            }
            goap = Path("reports/goap_state.json")
            if goap.exists():
                try:
                    payload["goap_state"] = json.loads(goap.read_text(encoding="utf-8"))
                except Exception:
                    pass
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
    except WebSocketDisconnect:
        _connected_websockets.remove(websocket)
    except Exception:
        if websocket in _connected_websockets:
            _connected_websockets.remove(websocket)


async def broadcast(message: str) -> None:
    for ws in _connected_websockets[:]:
        try:
            await ws.send_text(message)
        except Exception:
            _connected_websockets.remove(ws)


# ── Startup background collector ────────────────────────────────────────────


@app.on_event("startup")
async def _startup_collector():
    """Periodically collect metrics and push to event_buffer + broadcast."""
    async def _collect():
        cycle = 0
        while True:
            await asyncio.sleep(30)
            cycle += 1
            health = _load_json(REPORTS_DIR / "laura_health_latest.json")
            daemon = _load_json(REPORTS_DIR / "laura_daemon_state.json")
            profit = _load_json(REPORTS_DIR / "laura_profitability_latest.json")
            history = _load_jsonl(REPORTS_DIR / "skill_execution_history.jsonl")

            event = {
                "type": "collect",
                "timestamp": datetime.now().isoformat(),
                "health_score": health.get("health_score"),
                "daemon_running": daemon.get("running"),
                "cycle_count": daemon.get("cycle_count", 0),
                "error_count": daemon.get("error_count", 0),
                "margin_pct": (profit.get("metrics") or {}).get("margin_pct"),
                "total_executions": len(history),
                "ok_executions": sum(1 for h in history if h.get("ok")),
            }
            event_buffer.append(event)
            if len(event_buffer) > EVENT_BUFFER_MAX:
                event_buffer[:] = event_buffer[-EVENT_BUFFER_MAX:]

            try:
                await broadcast(json.dumps({"type": "collect", "data": event}, ensure_ascii=False))
            except Exception:
                pass

            if cycle % 2 == 0:
                cutoff_ts = _time.time() - 300
                event_buffer[:] = [
                    e for e in event_buffer
                    if isinstance(e.get("timestamp"), str)
                    and datetime.fromisoformat(e["timestamp"]).timestamp() > cutoff_ts
                ]

    asyncio.create_task(_collect())


_GOAP_HTML = """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><title>GOAP Timeline</title>
<style>
body{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:20px}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #30363d;padding:8px;text-align:left}
th{background:#161b22}
.ok{color:#3fb950}
.fail{color:#f85149}
h1{color:#58a6ff}
</style></head><body>
<h1>GOAP Execution Timeline</h1>
<div id="content">Loading...</div>
<script>
async function load(){const r=await fetch('/api/goap-timeline');const d=await r.json();
let h='<table><tr><th>Time</th><th>Skill</th><th>Status</th><th>Elapsed</th></tr>';
for(const e of(d.events||[])){h+=`<tr><td>${e.timestamp}</td><td>${e.skill}</td><td class="${e.ok?'ok':'fail'}">${e.ok?'OK':'FAIL'}</td><td>${e.elapsed}ms</td></tr>`}
h+='</table>';document.getElementById('content').innerHTML=h;}
load();setInterval(load,5000);
</script></body></html>"""

_SKILL_HEALTH_HTML = """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><title>Skill Health</title>
<style>
body{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:20px}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #30363d;padding:8px;text-align:left}
th{background:#161b22}
.ok{color:#3fb950}.warn{color:#d29922}.err{color:#f85149}
h1{color:#58a6ff}
</style></head><body>
<h1>Skill Health Dashboard</h1>
<div id="content">Loading...</div>
<script>
async function load(){const r=await fetch('/api/skill-health');const d=await r.json();
const skills=Object.entries(d.skills||{});
let h='<table><tr><th>Skill</th><th>Exec</th><th>Success%</th><th>Error%</th><th>Avg ms</th><th>p50</th><th>p95</th><th>Circuit</th><th>Rate</th></tr>';
for(const[name,s]of skills){const cls=s.circuit_state==='OPEN'?'err':s.error_rate_pct>10?'warn':'ok';
h+=`<tr><td>${name}</td><td>${s.executions}</td><td>${s.success_rate_pct}%</td><td>${s.error_rate_pct}%</td><td>${s.avg_latency_ms}</td><td>${s.p50_ms}</td><td>${s.p95_ms}</td><td class="${cls}">${s.circuit_state}</td><td>${s.rate_remaining}</td></tr>`}
h+='</table>';document.getElementById('content').innerHTML=h;}
load();setInterval(load,10000);
</script></body></html>"""

_GOAP_GRAPH_HTML = """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><title>GOAP Graph</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
body{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:20px;margin:0}
.node circle{fill:#58a6ff;stroke:#1f6feb;stroke-width:2px}
.node text{fill:#c9d1d9;font-size:11px}
.link{stroke:#30363d;stroke-width:1.5px;fill:none}
.link-label{fill:#8b949e;font-size:9px}
h1{color:#58a6ff}
</style></head><body>
<h1>GOAP Skill Dependency Graph</h1>
<div id="graph" style="width:100%;height:80vh"></div>
<script>
async function load(){const r=await fetch('/api/goap-graph');const d=await r.json();
const width=document.getElementById('graph').clientWidth,height=document.getElementById('graph').clientHeight;
const svg=d3.select('#graph').append('svg').attr('width',width).attr('height',height);
const g=svg.append('g');
const zoom=d3.zoom().on('zoom',(ev)=>g.attr('transform',ev.transform));
svg.call(zoom);
const sim=d3.forceSimulation(d.nodes).force('link',d3.forceLink(d.edges).id(d=>d.id).distance(100)).force('charge',d3.forceManyBody().strength(-200)).force('center',d3.forceCenter(width/2,height/2));
const link=g.append('g').selectAll('line').data(d.edges).join('line').attr('class','link');
const linkLabel=g.append('g').selectAll('text').data(d.edges).join('text').attr('class','link-label').text(d=>d.label).attr('dy',-3);
const node=g.append('g').selectAll('g').data(d.nodes).join('g').call(d3.drag().on('start',(ev,d)=>{if(!ev.active)sim.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y}).on('drag',(ev,d)=>{d.fx=ev.x;d.fy=ev.y}).on('end',(ev,d)=>{if(!ev.active)sim.alphaTarget(0);d.fx=null;d.fy=null}));
node.append('circle').attr('r',8);
node.append('text').attr('dx',12).attr('dy',4).text(d=>d.id);
sim.on('tick',()=>{link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y).attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);linkLabel.attr('x',d=>(d.source.x+d.target.x)/2).attr('y',d=>(d.source.y+d.target.y)/2);node.attr('transform',d=>'translate('+d.x+','+d.y+')')});}
load();
</script></body></html>"""


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus-formatted metrics endpoint."""
    lines = [
        "# HELP laura_plans_total Total plans created",
        "# TYPE laura_plans_total counter",
        f"laura_plans_total {len(_load_jsonl(REPORTS_DIR / 'skill_execution_history.jsonl'))}",
        "",
        "# HELP laura_skills_registered Number of registered skills",
        "# TYPE laura_skills_registered gauge",
    ]
    try:
        from shopee_agent.skills.registry import default_registry
        skills = default_registry.list()
        lines.append(f"laura_skills_registered {len(skills)}")
    except Exception:
        lines.append("laura_skills_registered 0")

    lines.extend([
        "",
        "# HELP laura_skill_executions_total Total skill executions",
        "# TYPE laura_skill_executions_total counter",
    ])
    history = _load_jsonl(REPORTS_DIR / "skill_execution_history.jsonl")
    ok_count = sum(1 for h in history if h.get("ok"))
    fail_count = sum(1 for h in history if not h.get("ok"))
    lines.append(f"laura_skill_executions_total{{status=\"ok\"}} {ok_count}")
    lines.append(f"laura_skill_executions_total{{status=\"fail\"}} {fail_count}")

    lines.extend([
        "",
        "# HELP laura_daemon_running Whether the daemon is running",
        "# TYPE laura_daemon_running gauge",
        f"laura_daemon_running {1 if _load_json(REPORTS_DIR / 'laura_daemon_state.json').get('running', False) else 0}",
    ])

    return Response(content="\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")


@router_v1.get("/status")
async def api_status():
    return {
        "running": _load_json(REPORTS_DIR / "laura_daemon_state.json").get("running", False),
        "seller_center": _load_json(BASE_DIR / "secrets" / "seller_center_cookies.json").get("cookies") is not None,
        "health": _load_json(REPORTS_DIR / "laura_health_latest.json"),
        "pending_ratings": len(_load_jsonl(RATING_PENDING)),
        "pending_chats": len(_load_jsonl(CHAT_PENDING)),
        "updated": datetime.now().isoformat(),
    }


# ── Aggregated dashboard endpoints ──────────────────────────────────────────


@router_v1.get("/dashboard/metrics")
async def api_dashboard_metrics():
    """Return aggregated metrics from event buffer + file reads."""
    health = _load_json(REPORTS_DIR / "laura_health_latest.json")
    _load_json(REPORTS_DIR / "laura_daemon_state.json")
    history = _load_jsonl(REPORTS_DIR / "skill_execution_history.jsonl")

    total_plans = len(history)
    ok_plans = sum(1 for h in history if h.get("ok"))
    fail_plans = total_plans - ok_plans

    per_skill: dict[str, dict] = {}
    for h in history:
        name = h.get("skill", "unknown")
        if name not in per_skill:
            per_skill[name] = {"executions": 0, "ok": 0, "fail": 0, "total_elapsed_ms": 0.0}
        per_skill[name]["executions"] += 1
        if h.get("ok"):
            per_skill[name]["ok"] += 1
        else:
            per_skill[name]["fail"] += 1
        per_skill[name]["total_elapsed_ms"] += float(h.get("elapsed", 0) or 0)

    total_skills = len(per_skill)
    ok_skills = sum(1 for s in per_skill.values() if s["fail"] == 0)
    fail_skills = total_skills - ok_skills
    avg_skill_dur = round(
        sum(s["total_elapsed_ms"] for s in per_skill.values()) / total_skills, 1
    ) if total_skills else 0.0

    health_score = health.get("health_score")
    if health_score is not None:
        hs = float(health_score)
        hstatus = "good" if hs >= 80 else "fair" if hs >= 50 else "poor"
    else:
        hs = 0
        hstatus = "unknown"

    now_ts = datetime.now().timestamp()
    events_last_min = sum(
        1 for e in event_buffer
        if isinstance(e.get("timestamp"), str)
        and (now_ts - datetime.fromisoformat(e["timestamp"]).timestamp()) < 60
    ) if event_buffer else 0

    return {
        "skills": {"total": total_skills, "ok": ok_skills, "fail": fail_skills, "avg_duration_ms": avg_skill_dur},
        "plans": {"total": total_plans, "ok": ok_plans, "fail": fail_plans},
        "health": {"score": round(hs, 1), "status": hstatus},
        "events_last_minute": events_last_min,
        "uptime_seconds": int(_time.time() - _start_time),
    }


@router_v1.get("/dashboard/recent-events")
async def api_dashboard_recent_events(limit: int = 20):
    """Return recent events from the in-memory buffer."""
    return {"events": event_buffer[-limit:] if event_buffer else []}


_SUMMARY_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Laura — Sumario</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;padding:16px}
h1{font-size:20px;margin-bottom:16px;color:#e2e8f0}
.store-selector{display:flex;align-items:center;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.store-selector select{padding:8px 12px;border-radius:6px;background:#1e293b;color:#e2e8f0;border:1px solid #334155;font-size:13px;min-width:200px}
.store-selector select:focus{outline:none;border-color:#6366f1}
.store-selector label{font-size:12px;color:#94a3b8;text-transform:uppercase}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-bottom:16px}
.card{background:#1e293b;border-radius:10px;padding:16px}
.card h2{font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#94a3b8;margin-bottom:8px}
.card .val{font-size:24px;font-weight:700}
.card .val.green{color:#22c55e}
.card .val.yellow{color:#eab308}
.card .val.red{color:#ef4444}
.card .sub{font-size:11px;color:#64748b;margin-top:4px}
.pie{width:80px;height:80px;border-radius:50%;margin:8px auto}
.bar-bg{background:#334155;border-radius:4px;height:16px;overflow:hidden;margin:4px 0}
.bar-fill{height:100%;border-radius:4px;transition:width .5s}
.gauge{width:100px;height:100px;margin:8px auto}
.gauge circle{fill:none;stroke-width:10}
.gauge .bg{stroke:#334155}
.gauge .fg{stroke:#22c55e;stroke-linecap:round;transform:rotate(-90deg);transform-origin:center}
.gauge text{font-size:20px;font-weight:700;fill:#e2e8f0;text-anchor:middle;dominant-baseline:central}
.log-box{background:#0f172a;border-radius:6px;padding:8px;max-height:240px;overflow-y:auto;font-size:11px;font-family:monospace}
.log-entry{display:flex;gap:6px;padding:2px 0;color:#94a3b8}
.log-entry .ts{color:#64748b;min-width:65px}
.log-entry .lv{min-width:36px;font-weight:600}
.log-entry .lv.INFO{color:#22c55e}
.log-entry .lv.WARN{color:#eab308}
.log-entry .lv.ERROR{color:#ef4444}
.log-entry .msg{color:#e2e8f0}
.health-gauge-wrap{text-align:center}
.status-badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:600;margin-top:4px}
.status-badge.good{background:#22c55e20;color:#22c55e;border:1px solid #22c55e}
.status-badge.fair{background:#eab30820;color:#eab308;border:1px solid #eab308}
.status-badge.poor{background:#ef444420;color:#ef4444;border:1px solid #ef4444}
.store-card{border-left:3px solid #6366f1}
</style>
</head>
<body>
<h1>Laura — Sumario em Tempo Real</h1>
<div class="store-selector">
  <label for="store-select">Loja:</label>
  <select id="store-select" onchange="onStoreChange(this.value)">
    <option value="">Todas as lojas</option>
  </select>
  <span id="store-info" style="font-size:12px;color:#64748b"></span>
</div>
<div class="grid" id="main-grid">
  <div class="card">
    <h2>Saude</h2>
    <div class="health-gauge-wrap">
      <svg class="gauge" viewBox="0 0 120 120">
        <circle class="bg" cx="60" cy="60" r="50"/>
        <circle class="fg" id="gauge-arc" cx="60" cy="60" r="50" stroke-dasharray="314.159" stroke-dashoffset="0"/>
        <text x="60" y="60" id="gauge-text">--</text>
      </svg>
      <div id="health-badge" class="status-badge">--</div>
    </div>
    <div class="sub" id="health-detail">Carregando...</div>
  </div>
  <div class="card">
    <h2>Skills OK / Fail</h2>
    <div class="pie" id="skills-pie" style="background:conic-gradient(#22c55e 0deg, #ef4444 0deg)"></div>
    <div class="sub" id="skills-detail">Carregando...</div>
  </div>
  <div class="card">
    <h2>Planos</h2>
    <div class="val green" id="plans-ok">--</div>
    <div class="sub">Sucesso</div>
    <div class="bar-bg"><div class="bar-fill" id="plans-bar" style="width:0%;background:#22c55e"></div></div>
    <div class="sub" id="plans-detail">Carregando...</div>
  </div>
  <div class="card">
    <h2>Eventos / Uptime</h2>
    <div class="val" id="events-count" style="color:#a5b4fc">--</div>
    <div class="sub">eventos no ultimo minuto</div>
    <div class="val" id="uptime-display" style="color:#a5b4fc;font-size:18px">--</div>
    <div class="sub">uptime</div>
  </div>
</div>
<div id="store-cards" class="grid"></div>
<div class="card">
  <h2>Eventos Recentes (ultimos 20)</h2>
  <div class="log-box" id="events-log"><div class="log-entry">Aguardando dados...</div></div>
</div>
<script>
const WS_TOKEN = '__WS_TOKEN__';
const API_KEY = '__API_KEY__';
const _fetch = window.fetch;
window.fetch = function(url, opts) {
  if (typeof url === 'string' && url.startsWith('/api/') && !url.includes('/push/')) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers['Authorization'] = 'Bearer ' + API_KEY;
  }
  return _fetch.call(window, url, opts);
};
const ws = new WebSocket('ws://' + location.host + '/ws/stream');
const log = document.getElementById('events-log');
let _selectedStore = '';

function fmtUptime(s) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h + 'h ' + m + 'm ' + sec + 's';
}

async function loadStores() {
  try {
    const r = await fetch('/api/stores');
    const d = await r.json();
    const sel = document.getElementById('store-select');
    sel.innerHTML = '<option value="">Todas as lojas</option>';
    (d.stores || []).forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.store_id;
      opt.textContent = s.store_id + (s.enabled ? '' : ' (desabilitada)');
      sel.appendChild(opt);
    });
  } catch(e) {}
}

async function onStoreChange(storeId) {
  _selectedStore = storeId;
  const info = document.getElementById('store-info');
  const cards = document.getElementById('store-cards');
  if (!storeId) {
    info.textContent = '';
    cards.innerHTML = '';
    return;
  }
  try {
    const r = await fetch('/api/stores/' + encodeURIComponent(storeId) + '/summary');
    const d = await r.json();
    info.textContent = 'Shop #' + d.shop_id + ' | Criada: ' + (d.created_at || '').slice(0,10);
    const health = d.health || {};
    const profit = d.profitability || {};
    const ds = d.daemon_state || {};
    const margin = profit.metrics ? profit.metrics.margin_pct : null;
    cards.innerHTML =
      '<div class="card store-card"><h2>' + storeId + ' — Saude</h2><div class="val ' + (health.health_score >= 80 ? 'green' : health.health_score >= 50 ? 'yellow' : 'red') + '">' + (health.health_score ?? 'N/A') + '</div><div class="sub">' + (health.status || '') + '</div></div>' +
      '<div class="card store-card"><h2>' + storeId + ' — Margem</h2><div class="val ' + (margin != null && margin > 15 ? 'green' : margin != null ? 'yellow' : 'red') + '">' + (margin != null ? margin.toFixed(1) + '%' : 'N/A') + '</div><div class="sub">Decisao: ' + (profit.action_key || 'N/A') + '</div></div>' +
      '<div class="card store-card"><h2>' + storeId + ' — Daemon</h2><div class="val ' + (ds.running ? 'green' : 'red') + '">' + (ds.running ? 'Rodando' : 'Parado') + '</div><div class="sub">' + (ds.cycle_count || 0) + ' ciclos</div></div>';
  } catch(e) {
    info.textContent = 'Erro ao carregar dados da loja';
    cards.innerHTML = '';
  }
}

function updateMetrics(d) {
  const data = d.type === 'collect' ? d.data : d;
  const hs = data.health_summary || data;
  const ds = data.daemon_state || data;

  const score = hs.health_score != null ? Number(hs.health_score) : null;
  if (score != null) {
    const circ = 2 * Math.PI * 50;
    const offset = circ * (1 - score / 100);
    document.getElementById('gauge-arc').setAttribute('stroke-dasharray', circ);
    document.getElementById('gauge-arc').setAttribute('stroke-dashoffset', offset);
    document.getElementById('gauge-text').textContent = Math.round(score);
    const badge = document.getElementById('health-badge');
    const st = score >= 80 ? 'good' : score >= 50 ? 'fair' : 'poor';
    badge.textContent = st === 'good' ? 'Bom' : st === 'fair' ? 'Regular' : 'Ruim';
    badge.className = 'status-badge ' + st;
  }

  fetch('/api/dashboard/metrics').then(r=>r.json()).then(m => {
    const sk = m.skills || {};
    const total = sk.total || 0;
    const ok = sk.ok || 0;
    const fail = sk.fail || 0;
    const pct = total > 0 ? (ok / total * 100) : 0;
    const deg = pct * 3.6;
    document.getElementById('skills-pie').style.background =
      'conic-gradient(#22c55e 0deg ' + deg + 'deg, #ef4444 ' + deg + 'deg 360deg)';
    document.getElementById('skills-detail').textContent =
      ok + ' ok / ' + fail + ' fail' + (sk.avg_duration_ms ? ' | media ' + sk.avg_duration_ms + 'ms' : '');

    const pl = m.plans || {};
    const planOk = pl.ok || 0, planFail = pl.fail || 0, planTotal = pl.total || 0;
    document.getElementById('plans-ok').textContent = planOk;
    document.getElementById('plans-ok').className = 'val ' + (planFail > 0 ? 'yellow' : 'green');
    const planPct = planTotal > 0 ? (planOk / planTotal * 100) : 0;
    document.getElementById('plans-bar').style.width = planPct + '%';
    document.getElementById('plans-detail').textContent =
      planOk + '/' + planTotal + ' (' + Math.round(planPct) + '%) | ' + planFail + ' falhas';

    document.getElementById('events-count').textContent = m.events_last_minute || 0;
    document.getElementById('uptime-display').textContent = fmtUptime(m.uptime_seconds || 0);
  }).catch(() => {});

  const events = d.recent_events || [];
  if (events.length) {
    let html = '';
    events.slice(-20).forEach(function(e) {
      const ts = (e.timestamp || '').slice(11, 19) || '--:--:--';
      const tp = (e.type || 'event').toUpperCase();
      const msg = e.health_score != null ? 'health=' + e.health_score : (e.total_executions != null ? 'exec=' + e.total_executions : tp);
      html += '<div class="log-entry"><span class="ts">' + ts + '</span><span class="lv">' + tp + '</span><span class="msg">' + msg + '</span></div>';
    });
    log.innerHTML = html;
    log.scrollTop = log.scrollHeight;
  }
}

// Initial load
loadStores();
fetch('/api/dashboard/metrics').then(r=>r.json()).then(updateMetrics).catch(()=>{});
ws.onmessage = function(ev) {
  try { updateMetrics(JSON.parse(ev.data)); } catch(e) {}
};
ws.onopen = function() {
  ws.send(JSON.stringify({type: 'auth', token: WS_TOKEN}));
  log.innerHTML = '<div class="log-entry">Conectado ao stream</div>';
};
ws.onclose = function() { log.innerHTML += '<div class="log-entry">Desconectado</div>'; };
</script>
</body>
</html>"""


@app.get("/summary", response_class=HTMLResponse)
async def summary_page():
    html = _SUMMARY_HTML.replace("__WS_TOKEN__", generate_ws_token())
    html = html.replace("__API_KEY__", _get_api_key() or "")
    return HTMLResponse(html)


@app.get("/ab-testing", response_class=HTMLResponse)
async def ab_testing_page():
    html = _AB_TESTING_HTML.replace("__API_KEY__", _get_api_key() or "")
    return HTMLResponse(html)


# ── API versioning ────────────────────────────────────────────────────────────
# v1 version endpoint
@router_v1.get("/version")
async def api_v1_version():
    return {"version": "v1", "latest": v_router.latest, "status": "stable"}

# v2 endpoints
@router_v2.get("/version")
async def api_v2_version():
    return {"version": "v2", "latest": v_router.latest, "status": "stable"}

@router_v2.get("/health")
async def api_v2_health():
    return _load_json(REPORTS_DIR / "laura_health_latest.json")

# Global version info
@app.get("/api/version")
async def api_version_info():
    return {"versions": API_VERSIONS, "latest": v_router.latest}

# Include versioned routers
v_router.include_all()

# ── Backward compatibility redirects (old /api/... → /api/v1/...) ──────────

from fastapi.responses import RedirectResponse as _R


@app.post("/api/push/subscribe")
async def _rdr_push_subscribe(): return _R(url="/api/v1/push/subscribe")
@app.post("/api/push/send")
async def _rdr_push_send(): return _R(url="/api/v1/push/send")
@app.post("/api/approve/rating/{idx}")
async def _rdr_approve_rating(idx: int): return _R(url=f"/api/v1/approve/rating/{idx}")
@app.post("/api/reject/rating/{idx}")
async def _rdr_reject_rating(idx: int): return _R(url=f"/api/v1/reject/rating/{idx}")
@app.post("/api/approve/chat/{idx}")
async def _rdr_approve_chat(idx: int): return _R(url=f"/api/v1/approve/chat/{idx}")
@app.post("/api/reject/chat/{idx}")
async def _rdr_reject_chat(idx: int): return _R(url=f"/api/v1/reject/chat/{idx}")
@app.get("/api/stores")
async def _rdr_stores(): return _R(url="/api/v1/stores")
@app.get("/api/stores/{store_id}/summary")
async def _rdr_store_summary(store_id: str): return _R(url=f"/api/v1/stores/{store_id}/summary")
@app.get("/api/health")
async def _rdr_health(): return _R(url="/api/v1/health")
@app.get("/api/profitability")
async def _rdr_profitability(): return _R(url="/api/v1/profitability")
@app.get("/api/skills")
async def _rdr_skills(): return _R(url="/api/v1/skills")
@app.get("/api/skill-health")
async def _rdr_skill_health(): return _R(url="/api/v1/skill-health")
@app.get("/api/goap-graph")
async def _rdr_goap_graph(): return _R(url="/api/v1/goap-graph")
@app.get("/api/goap-timeline")
async def _rdr_goap_timeline(): return _R(url="/api/v1/goap-timeline")
@app.get("/api/goap-cost-history")
async def _rdr_goap_cost_history(): return _R(url="/api/v1/goap-cost-history")
@app.get("/api/goal-synthesize")
async def _rdr_goal_synthesize(): return _R(url="/api/v1/goal-synthesize")
@app.get("/api/ws-token")
async def _rdr_ws_token(): return _R(url="/api/v1/ws-token")
@app.get("/api/ab-tests/stats")
async def _rdr_ab_tests_stats(): return _R(url="/api/v1/ab-tests/stats")
@app.get("/api/ab-tests")
async def _rdr_ab_tests(): return _R(url="/api/v1/ab-tests")
@app.get("/api/ab-tests/{test_id}")
async def _rdr_ab_test_detail(test_id: str): return _R(url=f"/api/v1/ab-tests/{test_id}")
@app.post("/api/ab-tests/{test_id}/promote")
async def _rdr_ab_test_promote(test_id: str): return _R(url=f"/api/v1/ab-tests/{test_id}/promote")
@app.get("/api/status")
async def _rdr_status(): return _R(url="/api/v1/status")
@app.get("/api/dashboard/metrics")
async def _rdr_dashboard_metrics(): return _R(url="/api/v1/dashboard/metrics")
@app.get("/api/dashboard/recent-events")
async def _rdr_dashboard_recent_events(): return _R(url="/api/v1/dashboard/recent-events")

# ── Deprecation middleware for v1 ──────────────────────────────────────────
@app.middleware("http")
async def _api_deprecation_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/"):
        response.headers["X-API-Version"] = "v1"
        response.headers["X-API-Deprecated"] = "true"
    return response


def start(host: str = "127.0.0.1", port: int = 8888, build_frontend: bool = False, auto_build: bool = True):
    if build_frontend:
        _build_frontend()
    elif auto_build and not _ensure_frontend_built(BASE_DIR):
        warning("Auto-build indisponivel: node/npm ausente ou build falhou. Usando fallback inline.")
    info(f"Dashboard em http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


def _frontend_is_stale(project_root: Path) -> bool:
    """True if frontend/dist/index.html is missing or older than any src file."""
    frontend_dir = project_root / "frontend"
    dist_index = frontend_dir / "dist" / "index.html"
    if not dist_index.is_file():
        return True
    dist_mtime = dist_index.stat().st_mtime
    candidates = list((frontend_dir / "src").rglob("*")) if (frontend_dir / "src").is_dir() else []
    candidates += [frontend_dir / n for n in ("index.html", "package.json", "vite.config.js", "vite.config.ts")]
    return any(p.is_file() and p.stat().st_mtime > dist_mtime for p in candidates)


def _ensure_frontend_built(project_root: Path) -> bool:
    """Ensure the frontend is built. Fast mtime check; builds only if stale/missing.

    Returns True if the frontend is ready (already built or build succeeded),
    False otherwise (node/npm unavailable or build failed).
    """
    import shutil
    import subprocess

    frontend_dir = project_root / "frontend"
    if not frontend_dir.exists():
        return False
    try:
        if not _frontend_is_stale(project_root):
            return True
    except OSError:
        return False
    if shutil.which("npm") is None:
        return False
    try:
        if not (frontend_dir / "node_modules").is_dir():
            install = subprocess.run(
                ["npm", "install"],
                cwd=str(frontend_dir),
                capture_output=True,
                text=True,
            )
            if install.returncode != 0:
                info(f"Frontend npm install failed (code {install.returncode}).")
                return False
        build = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    if build.returncode == 0:
        info("Frontend auto-build concluido.")
        return True
    info(f"Frontend build failed (code {build.returncode}): {build.stderr}")
    return False


def _build_frontend():
    """Run 'npm run build' in the frontend directory."""
    import subprocess
    frontend_dir = BASE_DIR / "frontend"
    if not frontend_dir.exists():
        info("Frontend directory not found, skipping build.")
        return
    info("Building frontend...")
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(frontend_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        info("Frontend built successfully.")
    else:
        info(f"Frontend build failed (code {result.returncode}): {result.stderr}")


if __name__ == "__main__":
    import sys as _sys
    if "--ws-token" in _sys.argv:
        print(generate_ws_token())
        _sys.exit(0)
    if "--api-key" in _sys.argv:
        print(_get_api_key())
        _sys.exit(0)
    build = "--build-frontend" in _sys.argv
    auto = "--no-auto-build" not in _sys.argv
    start(build_frontend=build, auto_build=auto)
