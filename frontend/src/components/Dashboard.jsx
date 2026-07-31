import React, { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api';

function HealthGauge({ score }) {
  const circ = 2 * Math.PI * 50;
  const offset = score != null ? circ * (1 - Math.min(Math.max(score, 0), 100) / 100) : circ;
  const status = score >= 80 ? 'good' : score >= 50 ? 'fair' : 'poor';
  const label = score >= 80 ? 'Bom' : score >= 50 ? 'Regular' : 'Ruim';
  return (
    <div className="gauge-wrap">
      <svg className="gauge" viewBox="0 0 120 120">
        <circle className="bg" cx="60" cy="60" r="50" />
        <circle className="fg" cx="60" cy="60" r="50"
          strokeDasharray={circ} strokeDashoffset={offset}
          style={{ stroke: score >= 80 ? 'var(--green)' : score >= 50 ? 'var(--yellow)' : 'var(--red)' }} />
        <text x="60" y="60">{score != null ? Math.round(score) : '--'}</text>
      </svg>
      <div className={`badge ${status}`}>{label}</div>
    </div>
  );
}

function MetricCardSkeleton() {
  return (
    <div className="card" style={{ border: '1px solid var(--border)' }}>
      <div className="skeleton skeleton-text" style={{ width: '40%', height: 12 }} />
      <div className="skeleton skeleton-gauge" style={{ width: 80, height: 80, margin: '12px auto' }} />
      <div className="skeleton skeleton-text" style={{ width: '50%', marginTop: 8 }} />
    </div>
  );
}

function WorkerBar({ workers }) {
  if (!workers || workers.length === 0) return <div className="meta">Nenhum worker ativo</div>;
  return (
    <div>
      {workers.map((w, i) => (
        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 12 }}>
          <span>{w.name || w.id || `Worker ${i}`}</span>
          <span className={`status ${w.running ? 'active' : 'inactive'}`}>
            {w.running ? 'Rodando' : 'Parado'}
          </span>
        </div>
      ))}
    </div>
  );
}

function Trend({ value, goodDir = 'up' }) {
  if (value == null) return null;
  const up = goodDir === 'up';
  const isUp = value > 0;
  const isNeutral = value === 0;
  let cls = isNeutral ? 'neutral' : isUp === up ? 'up' : 'down';
  let arrow = isNeutral ? '→' : isUp ? '↑' : '↓';
  return <span className={`trend ${cls}`}>{arrow} {Math.abs(value)}</span>;
}

export default function Dashboard({ wsData }) {
  const [status, setStatus] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const intervalRef = useRef(null);

  const load = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const [s, m, e] = await Promise.all([
        api.get('/api/status'),
        api.get('/api/dashboard/metrics'),
        api.get('/api/dashboard/recent-events?limit=20'),
      ]);
      setStatus(s);
      setMetrics(m);
      setEvents(e.events || []);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err.message || 'Falha ao carregar dados');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(true); }, [load]);

  useEffect(() => {
    intervalRef.current = setInterval(() => load(), 30000);
    return () => clearInterval(intervalRef.current);
  }, [load]);

  useEffect(() => {
    if (!wsData) return;
    if (wsData.type === 'state_update' || wsData.type === 'collect') {
      const data = wsData.data || wsData;
      if (data.health_summary) {
        setStatus(prev => ({ ...prev, health: data.health_summary }));
        setLastUpdated(new Date());
      }
      if (data.daemon_state) {
        setStatus(prev => ({ ...prev, ...data.daemon_state }));
      }
      if (data.recent_events && data.recent_events.length) {
        setEvents(data.recent_events);
      }
    }
  }, [wsData]);

  if (loading && !status) {
    return (
      <div>
        <h1 className="page-title">Dashboard</h1>
        <div className="grid">
          {[1, 2, 3, 4].map(i => <MetricCardSkeleton key={i} />)}
        </div>
        <div className="section">
          <h3>Status dos Workers</h3>
          <div className="card"><div className="skeleton skeleton-text" /><div className="skeleton skeleton-text short" /></div>
        </div>
        <div className="section">
          <h3>Eventos Recentes</h3>
          <div className="card"><div className="skeleton skeleton-text" /><div className="skeleton skeleton-text" /><div className="skeleton skeleton-text short" /></div>
        </div>
      </div>
    );
  }

  if (error && !status) {
    return (
      <div>
        <h1 className="page-title">Dashboard</h1>
        <div className="error-state">
          <div className="icon">⚠</div>
          <p>{error}</p>
          <button className="btn primary" onClick={() => load(true)}>Tentar novamente</button>
        </div>
      </div>
    );
  }

  const healthScore = status?.health?.health_score;
  const sellerAuthed = status?.seller_center;
  const daemonRunning = status?.running ?? status?.daemon_state?.running;
  const pendingRatings = status?.pending_ratings ?? 0;
  const pendingChats = status?.pending_chats ?? 0;
  const totalPending = pendingRatings + pendingChats;
  const margin = status?.health?.metrics?.margin_pct;
  const cycles = status?.health?.cycle_count ?? metrics?.plans?.total ?? 0;
  const errors = status?.health?.error_count ?? 0;

  return (
    <div>
      <h1 className="page-title">Dashboard</h1>
      <div className="last-updated">
        <span className="live-dot" />
        {lastUpdated ? `Última atualização: ${lastUpdated.toLocaleTimeString('pt-BR')}` : 'Carregando...'}
        {intervalRef.current && (
          <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-dim)' }}>
            (auto 30s)
          </span>
        )}
      </div>

      <div className="grid">
        <div className="card">
          <h2>Saúde da Loja</h2>
          <HealthGauge score={healthScore} />
          <div className="meta">
            Seller Center: <span className={`status ${sellerAuthed ? 'active' : 'inactive'}`}>
              {sellerAuthed ? 'Autenticado' : 'Não autenticado'}
            </span>
          </div>
        </div>
        <div className="card">
          <h2>Margem</h2>
          <div className={`value ${margin != null ? (margin > 15 ? 'green' : 'yellow') : 'red'}`}>
            {margin != null ? `${Number(margin).toFixed(1)}%` : 'N/A'}
            {margin != null && <Trend value={margin - (status?.health?.previous_margin ?? margin)} />}
          </div>
          <div className="meta">Decisão: {status?.health?.action_key ?? status?.health?.decision ?? 'N/A'}</div>
          {margin != null && (
            <div className="meta">Meta: &gt;15% {margin > 15 ? '✓' : '✗'}</div>
          )}
        </div>
        <div className="card">
          <h2>Daemon</h2>
          <div className={`value ${daemonRunning ? 'green' : errors > 5 ? 'red' : 'yellow'}`}>
            {daemonRunning ? 'Rodando' : 'Parado'}
          </div>
          <div className="meta">{cycles} ciclos | {errors} erros</div>
          <div className="meta">Último: {status?.health?.last_cycle ?? 'N/A'}</div>
        </div>
        <div className="card">
          <h2>Aprovações Pendentes</h2>
          <div className={`value ${totalPending > 0 ? 'yellow' : 'green'}`}>{totalPending}</div>
          <div className="meta">{pendingRatings} avaliações | {pendingChats} chats</div>
          {totalPending > 0 && <div className="meta" style={{ color: 'var(--yellow)' }}>Ações necessárias</div>}
        </div>
      </div>

      {!metrics && !error ? (
        <div className="section">
          <h3>Status dos Workers</h3>
          <div className="card"><div className="skeleton skeleton-text" style={{ width: '30%' }} /></div>
        </div>
      ) : (
        <>
          {metrics?.workers || status?.workers ? (
            <div className="section">
              <h3>Status dos Workers</h3>
              <div className="card">
                <WorkerBar workers={status?.workers || metrics?.workers} />
              </div>
            </div>
          ) : null}
        </>
      )}

      <div className="section">
        <h3>Eventos Recentes</h3>
        <div className="card">
          <div className="log-box">
            {events.length === 0 ? (
              <div className="empty-state" style={{ padding: '12px 0' }}>
                <p>Nenhum evento registrado ainda.</p>
              </div>
            ) : (
              events.slice(-20).reverse().map((e, i) => (
                <div key={i} className="log-entry">
                  <span className="ts">{(e.timestamp || '').slice(11, 19) || '--:--:--'}</span>
                  <span className="lv">{(e.type || 'EVENT').toUpperCase()}</span>
                  <span className="msg">
                    {e.health_score != null ? `health=${e.health_score}` :
                     e.total_executions != null ? `exec=${e.total_executions}` :
                     e.daemon_running != null ? `daemon=${e.daemon_running}` :
                     (e.message || e.type || '')}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
