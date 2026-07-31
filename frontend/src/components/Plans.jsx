import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';

export default function Plans() {
  const [graph, setGraph] = useState(null);
  const [events, setEvents] = useState([]);
  const [costHistory, setCostHistory] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const [g, e, c] = await Promise.all([
        api.get('/api/goap-graph'),
        api.get('/api/goap-timeline'),
        api.get('/api/goap-cost-history'),
      ]);
      if (g.error) { setError(g.error); return; }
      setGraph(g);
      setEvents(e.events || []);
      setCostHistory(c.cost_history || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (error) {
    return (
      <div>
        <h1 className="page-title">Planos (GOAP)</h1>
        <div className="card">
          <p style={{ color: 'var(--red)' }}>Erro ao carregar: {error}</p>
          <button className="btn primary" onClick={load} style={{ marginTop: 12 }}>Tentar novamente</button>
        </div>
      </div>
    );
  }

  if (!graph) {
    return (
      <div>
        <h1 className="page-title">Planos (GOAP)</h1>
        <div className="card"><p>Carregando...</p></div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="page-title">Planos (GOAP)</h1>

      <div className="section">
        <h3>Grafo de Ações ({graph.nodes?.length || 0} nodes, {graph.edges?.length || 0} edges)</h3>
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Skill / Ação</th>
                <th>Custo</th>
                <th>Prioridade</th>
                <th>Pré-condições</th>
                <th>Efeitos</th>
              </tr>
            </thead>
            <tbody>
              {(graph.nodes || []).map((n, i) => (
                <tr key={n.id || i}>
                  <td style={{ fontWeight: 600 }}>{n.id}</td>
                  <td>{n.cost ?? '-'}</td>
                  <td>{n.priority ?? 0}</td>
                  <td>{(n.preconditions || []).join(', ') || '-'}</td>
                  <td>{(n.effects || []).join(', ') || '-'}</td>
                </tr>
              ))}
              {(!graph.nodes || graph.nodes.length === 0) && (
                <tr><td colSpan={5} style={{ color: 'var(--text-dim)' }}>Nenhuma ação registrada</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="section">
        <h3>Histórico de Custo por Skill</h3>
        <div className="card">
          {costHistory.length === 0 ? (
            <p style={{ color: 'var(--text-dim)' }}>Nenhum dado de custo disponível</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Skill</th>
                  <th>Custo Atual</th>
                  <th>Execuções</th>
                  <th>Taxa de Sucesso</th>
                </tr>
              </thead>
              <tbody>
                {costHistory.map((c, i) => (
                  <tr key={c.skill || i}>
                    <td style={{ fontWeight: 600 }}>{c.skill}</td>
                    <td>{c.current_cost ?? '-'}</td>
                    <td>{c.executions ?? 0}</td>
                    <td>{c.success_rate != null ? `${c.success_rate}%` : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="section">
        <h3>Timeline de Execução ({events.length} eventos)</h3>
        <div className="card">
          <div className="log-box" style={{ maxHeight: 400 }}>
            {events.length === 0 ? (
              <div className="log-entry">Nenhum evento registrado</div>
            ) : (
              events.slice().reverse().map((e, i) => (
                <div key={i} className="log-entry">
                  <span className="ts">{(e.timestamp || '').slice(11, 19) || '--:--:--'}</span>
                  <span className="lv" style={{ color: e.ok ? 'var(--green)' : 'var(--red)' }}>
                    {e.ok ? 'OK' : 'FAIL'}
                  </span>
                  <span className="msg">{e.skill} — {e.elapsed}ms</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
