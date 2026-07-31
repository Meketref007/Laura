import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';

export default function Goals() {
  const [goal, setGoal] = useState(null);
  const [params, setParams] = useState({ marginPct: 25, lowMargin: 0, lowStock: 0, refundPct: 0 });
  const [loading, setLoading] = useState(false);

  const synthesize = useCallback(async (p) => {
    setLoading(true);
    try {
      const res = await api.get(
        `/api/goal-synthesize?margin_pct=${p.marginPct}&low_margin=${p.lowMargin}&low_stock=${p.lowStock}&refund_pct=${p.refundPct}`
      );
      setGoal(res);
    } catch (err) {
      setGoal({ error: err.message });
    }
    setLoading(false);
  }, []);

  useEffect(() => { synthesize(params); }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    synthesize(params);
  };

  return (
    <div>
      <h1 className="page-title">Metas (GOAP)</h1>

      <div className="grid">
        <div className="card">
          <h2>Sintetizar Meta</h2>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label>Margem (%)</label>
              <input type="number" step="0.1" value={params.marginPct}
                onChange={e => setParams(p => ({ ...p, marginPct: +e.target.value }))} />
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Produtos margem baixa</label>
                <input type="number" value={params.lowMargin}
                  onChange={e => setParams(p => ({ ...p, lowMargin: +e.target.value }))} />
              </div>
              <div className="form-group">
                <label>Produtos estoque baixo</label>
                <input type="number" value={params.lowStock}
                  onChange={e => setParams(p => ({ ...p, lowStock: +e.target.value }))} />
              </div>
            </div>
            <div className="form-group">
              <label>Taxa de reembolso (%)</label>
              <input type="number" step="0.1" value={params.refundPct}
                onChange={e => setParams(p => ({ ...p, refundPct: +e.target.value }))} />
            </div>
            <button type="submit" className="btn primary" disabled={loading}>
              {loading ? 'Sintetizando...' : 'Sintetizar Meta'}
            </button>
          </form>
        </div>

        <div className="card">
          <h2>Meta Atual</h2>
          {goal ? (
            goal.error ? (
              <p style={{ color: 'var(--red)' }}>Erro: {goal.error}</p>
            ) : (
              <div>
                <div className="value green" style={{ fontSize: 16, marginBottom: 8 }}>
                  {goal.description || 'N/A'}
                </div>
                <pre>{JSON.stringify(goal.goal || {}, null, 2)}</pre>
              </div>
            )
          ) : (
            <p className="meta">Clique em sintetizar para gerar uma meta</p>
          )}
        </div>
      </div>

      <div className="section">
        <h3>Metas Ativas</h3>
        <div className="card">
          <p className="meta">
            Use o painel acima para sintetizar metas baseadas em KPIs de negócio.
            A meta gerada será usada pelo planejador GOAP para selecionar as melhores ações.
          </p>
        </div>
      </div>
    </div>
  );
}
