const BASE = '';

function getApiKey() {
  let key = localStorage.getItem('laura_api_key');
  if (!key) {
    const params = new URLSearchParams(window.location.search);
    key = params.get('api_key');
    if (key) localStorage.setItem('laura_api_key', key);
  }
  return key;
}

async function apiGet(path) {
  const headers = {};
  const key = getApiKey();
  if (key) headers['Authorization'] = `Bearer ${key}`;
  const res = await fetch(`${BASE}${path}`, { headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiPost(path, data) {
  const headers = { 'Content-Type': 'application/json' };
  const key = getApiKey();
  if (key) headers['Authorization'] = `Bearer ${key}`;
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

let _wsToken = null;
let _wsTokenPromise = null;

async function getWsToken() {
  if (_wsToken) return _wsToken;
  if (_wsTokenPromise) return _wsTokenPromise;
  _wsTokenPromise = (async () => {
    try {
      const data = await apiGet('/api/ws-token');
      _wsToken = data.token;
      return _wsToken;
    } catch (e) {
      return null;
    }
  })();
  return _wsTokenPromise;
}

function apiWs() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/stream`;
  const ws = new WebSocket(wsUrl);
  ws.onopen = async () => {
    const token = await getWsToken();
    if (token) {
      ws.send(JSON.stringify({ type: 'auth', token }));
    }
  };
  return ws;
}

export const api = { get: apiGet, post: apiPost, ws: apiWs };
export { getApiKey };
