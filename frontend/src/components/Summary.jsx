import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';

function fmtUptime(s) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return `${h}h ${m}m ${sec}s`;
}

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

function ConicPie({ ok, total }) {
  const pct = total > 0 ? (ok / total * 100) : 0;
  const deg = pct * 3.6;
  return (
    <div
      className="pie-chart"
      style={{ background: `conic-gradient(var(--green) 0deg ${deg}deg, var(--red) ${deg}deg 360deg)` }}
    />
  );
}

export default function Summary({ wsData }) {
  const [metrics, setMetrics] = useState(null);
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState(null);

  const load = useCallback(async () => {
    try {
      const [m, e, s] = await Promise.all([
        api.get('/api/dashboard/metrics'),
        api.get('/api/dashboard/recent-events?limit=20'),
        api.get('/api/status'),
      ]);
      setMetrics(m);
      setEvents(e.events || []);
      setStatus(s);
    } catch (err) { /* ignore */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!wsData) return;
    const data = wsData.data || wsData;
    if (data.health_summary) {
      setStatus(prev => ({ ...prev, health: data.health_summary }));
    }
  }, [wsData]);

  const hs = metrics?.health?.score ?? status?.health?.health_score;
  const totalSkills = metrics?.skills?.total ?? 0;
  const okSkills = metrics?.skills?.ok ?? 0;
  const failSkills = metrics?.skills?.fail ?? 0;
  const planOk = metrics?.plans?.ok ?? 0;
  const planFail = metrics?.plans?.fail ?? 0;
  const planTotal = metrics?.plans?.total ?? 0;
  const planPct = planTotal > 0 ? (planOk / planTotal * 100) : 0;
  const eventsMin = metrics?.events_last_minute ?? 0;
  const uptime = metrics?.uptime_seconds ?? 0;

  return (
    <div>
      <h1 className="page-title">Sumário em Tempo Real</h1>
      <div className="grid">
        <div className="card">
          <h2>Saúde</h2>
          <HealthGauge score={hs} />
          <div className="meta" id="health-detail">
            {hs != null ? `Score: ${Number(hs).toFixed(1)}` : 'Carregando...'}
          </div>
        </div>
        <div className="card">
          <h2>Skills OK / Fail</h2>
          <ConicPie ok={okSkills} total={totalSkills} />
          <div className="meta">
            {okSkills} ok / {failSkills} fail
            {metrics?.skills?.avg_duration_ms ? ` | média ${metrics.skills.avg_duration_ms}ms` : ''}
          </div>
        </div>
        <div className="card">
          <h2>Planos</h2>
          <div className={`value ${planFail > 0 ? 'yellow' : 'green'}`}>{planOk}</div>
          <div className="meta">Sucesso</div>
          <div className="bar-bg">
            <div className="bar-fill" style={{ width: `${planPct}%`, background: 'var(--green)' }} />
          </div>
          <div className="meta">{planOk}/{planTotal} ({Math.round(planPct)}%) | {planFail} falhas</div>
        </div>
        <div className="card">
          <h2>Eventos / Uptime</h2>
          <div className="value indigo">{eventsMin}</div>
          <div className="meta">eventos no último minuto</div>
          <div className="value indigo" style={{ fontSize: 18 }}>{fmtUptime(uptime)}</div>
          <div className="meta">uptime</div>
        </div>
      </div>

      <div className="section">
        <h3>Eventos Recentes</h3>
        <div className="card">
          <div className="log-box">
            {events.length === 0 ? (
              <div className="log-entry">Aguardando dados...</div>
            ) : (
              events.slice(-20).reverse().map((e, i) => (
                <div key={i} className="log-entry">
                  <span className="ts">{(e.timestamp || '').slice(11, 19) || '--:--:--'}</span>
                  <span className="lv">{(e.type || 'EVENT').toUpperCase()}</span>
                  <span className="msg">
                    {e.health_score != null ? `health=${e.health_score}` :
                     e.total_executions != null ? `exec=${e.total_executions}` :
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
