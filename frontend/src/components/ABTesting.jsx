import React, { useState, useEffect, useCallback } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { api } from '../api';

export default function ABTesting() {
  const [tests, setTests] = useState(null);
  const [stats, setStats] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [promoting, setPromoting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([
        api.get('/api/ab-tests'),
        api.get('/api/ab-tests/stats'),
      ]);
      setTests(t);
      setStats(s);
    } catch (e) { /* ignore */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    api.get(`/api/ab-tests/${encodeURIComponent(selected)}`)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [selected]);

  const handlePromote = async () => {
    if (!selected || promoting) return;
    setPromoting(true);
    try {
      const r = await api.post(`/api/ab-tests/${encodeURIComponent(selected)}/promote`);
      if (r.promoted) {
        const d = await api.get(`/api/ab-tests/${encodeURIComponent(selected)}`);
        setDetail(d);
      }
      await load();
    } catch (e) { /* ignore */ }
    setPromoting(false);
  };

  const testEntries = Object.entries(tests || {});
  const totalExec = (t) => t.outcomes.control.executions + t.outcomes.variant.executions;
  const successRate = (outcomes) =>
    outcomes.executions ? (outcomes.successes / outcomes.executions * 100).toFixed(1) : '0.0';

  const chartData = detail ? [
    { name: detail.control, rate: detail.control_rate * 100, fills: '#6366f1' },
    { name: detail.variant, rate: detail.variant_rate * 100, fills: '#22c55e' },
  ] : [];

  return (
    <div>
      <h1 className="page-title">A/B Testing</h1>

      <div className="grid">
        <div className="card">
          <h2>Total Testes</h2>
          <div className="value indigo">{stats?.total_tests ?? 0}</div>
        </div>
        <div className="card">
          <h2>Ativos</h2>
          <div className="value green">{stats?.active ?? 0}</div>
        </div>
        <div className="card">
          <h2>Promovidos</h2>
          <div className="value" style={{ color: 'var(--indigo)' }}>{stats?.promoted ?? 0}</div>
        </div>
        <div className="card">
          <h2>Confiança Média</h2>
          <div className="value" style={{ color: 'var(--primary)' }}>
            {stats?.avg_confidence ? (stats.avg_confidence * 100).toFixed(1) + '%' : '--'}
          </div>
          <div className="meta">média dos testes com dados</div>
        </div>
      </div>

      <div className="section">
        <h3>Testes Registrados</h3>
        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>Teste</th>
                <th>Controle</th>
                <th>Variante</th>
                <th>Exec.</th>
                <th>Status</th>
                <th>Confiança</th>
              </tr>
            </thead>
            <tbody>
              {testEntries.length === 0 && (
                <tr><td colSpan={6} style={{ color: 'var(--text-dim)', textAlign: 'center', padding: 20 }}>Nenhum teste ativo</td></tr>
              )}
              {testEntries.map(([testId, t]) => {
                const c = t.outcomes.control;
                const v = t.outcomes.variant;
                const cRate = c.executions ? (c.successes / c.executions) : 0;
                const vRate = v.executions ? (v.successes / v.executions) : 0;
                let badge, badgeText;
                if (t.promoted_winner) {
                  badge = 'active'; badgeText = 'Promovido: ' + t.promoted_winner;
                } else if (t.winner) {
                  badge = 'active'; badgeText = 'Vencedor: ' + t.winner;
                } else if (c.executions < 10 || v.executions < 10) {
                  badge = 'pending'; badgeText = 'Poucos dados';
                } else {
                  badge = 'inactive'; badgeText = 'Empate';
                }
                return (
                  <tr
                    key={testId}
                    onClick={() => setSelected(selected === testId ? null : testId)}
                    style={{ cursor: 'pointer', background: selected === testId ? 'var(--surface-hover)' : '' }}
                  >
                    <td style={{ fontWeight: 600 }}>{testId}</td>
                    <td>{t.control}</td>
                    <td>{t.variant}</td>
                    <td>{totalExec(t)}</td>
                    <td><span className={`status ${badge}`}>{badgeText}</span></td>
                    <td>
                      <div className="bar-bg" style={{ width: 100, display: 'inline-block', verticalAlign: 'middle', marginRight: 8 }}>
                        <div className="bar-fill" style={{ width: `${Math.max(cRate, vRate) * 100}%`, background: cRate >= vRate ? 'var(--green)' : 'var(--primary)' }} />
                      </div>
                      <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{successRate(t.outcomes.control)}% / {successRate(t.outcomes.variant)}%</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {detail && (
        <div className="section">
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
              <h3 style={{ fontSize: 16, margin: 0 }}>{selected}</h3>
              <span className={`status ${detail.is_promoted ? 'active' : detail.winner ? 'active' : detail.outcomes?.control?.executions < 10 ? 'pending' : 'inactive'}`}>
                {detail.is_promoted ? `Promovido: ${detail.promoted_winner}` : detail.winner ? `Vencedor: ${detail.winner}` : 'Indefinido'}
              </span>
            </div>

            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
              <div className="card" style={{ textAlign: 'center', padding: 12 }}>
                <div className="value green" style={{ fontSize: 18 }}>{detail.outcomes?.control?.executions || 0}</div>
                <div className="meta">Exec. Controle</div>
              </div>
              <div className="card" style={{ textAlign: 'center', padding: 12 }}>
                <div className="value" style={{ fontSize: 18, color: 'var(--green)' }}>{detail.outcomes?.variant?.executions || 0}</div>
                <div className="meta">Exec. Variante</div>
              </div>
              <div className="card" style={{ textAlign: 'center', padding: 12 }}>
                <div className="value indigo" style={{ fontSize: 18 }}>{(detail.traffic_split * 100).toFixed(0)}%</div>
                <div className="meta">Traffic Split</div>
              </div>
              <div className="card" style={{ textAlign: 'center', padding: 12 }}>
                <div className="value" style={{ fontSize: 18, color: 'var(--primary)' }}>{detail.z_score?.toFixed(3) || '0.00'}</div>
                <div className="meta">Z-Score</div>
              </div>
            </div>

            <div style={{ marginTop: 16 }}>
              <h3 style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>Taxa de Sucesso: Controle vs Variante</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={chartData}>
                  <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                  <YAxis domain={[0, 'auto']} tick={{ fill: '#64748b', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                    formatter={(v) => v.toFixed(1) + '%'}
                  />
                  <Bar dataKey="rate" radius={[6, 6, 0, 0]} maxBarSize={80}>
                    {chartData.map((entry, i) => (
                      <Cell key={i} fill={entry.fills} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="gauge-wrap" style={{ marginTop: 16 }}>
              <svg className="gauge" viewBox="0 0 120 120">
                <circle className="bg" cx="60" cy="60" r="50"/>
                <circle className="fg" cx="60" cy="60" r="50"
                  strokeDasharray="314.159"
                  strokeDashoffset={314.159 * (1 - (detail.confidence || 0))}
                  stroke={detail.confidence >= 0.95 ? '#22c55e' : detail.confidence >= 0.8 ? '#eab308' : '#ef4444'}
                />
                <text x="60" y="60">{(detail.confidence * 100).toFixed(1)}%</text>
              </svg>
              <div className="meta">Confiança Estatística</div>
            </div>

            <div style={{ marginTop: 12 }}>
              <button className="btn primary" onClick={handlePromote} disabled={promoting}>
                {promoting ? 'Avaliando...' : 'Avaliar & Promover'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
