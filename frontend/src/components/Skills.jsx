import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';

export default function Skills() {
  const [skills, setSkills] = useState(null);
  const [health, setHealth] = useState(null);

  const load = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        api.get('/api/skills'),
        api.get('/api/skill-health'),
      ]);
      setSkills(s);
      setHealth(h);
    } catch (err) { /* ignore */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const skillHealthMap = health?.skills || {};

  return (
    <div>
      <h1 className="page-title">Skills</h1>

      <div className="grid">
        <div className="card">
          <h2>Skills Registradas</h2>
          <div className="value green">{skills?.registered_count ?? 0}</div>
          <div className="meta">Total de habilidades</div>
        </div>
        <div className="card">
          <h2>Execuções Totais</h2>
          <div className="value indigo">{skills?.total_executions ?? 0}</div>
          <div className="meta">Taxa de sucesso: {skills?.success_rate_pct ?? 0}%</div>
        </div>
        <div className="card">
          <h2>Skills Saudáveis</h2>
          <div className="value green">
            {Object.values(skillHealthMap).filter(s => s.circuit_state !== 'OPEN').length}
          </div>
          <div className="meta">
            {Object.values(skillHealthMap).filter(s => s.circuit_state === 'OPEN').length} em circuito aberto
          </div>
        </div>
      </div>

      <div className="section">
        <h3>Skills Registradas</h3>
        <div className="card">
          {(skills?.registered_skills || []).length === 0 ? (
            <p style={{ color: 'var(--text-dim)' }}>Nenhuma skill registrada</p>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {(skills?.registered_skills || []).map((name, i) => (
                <span key={i} className="status active" style={{ fontSize: 12 }}>{name}</span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="section">
        <h3>Métricas por Skill</h3>
        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>Skill</th>
                <th>Execuções</th>
                <th>Sucesso</th>
                <th>Erro</th>
                <th>Latência Média</th>
                <th>p50</th>
                <th>p95</th>
                <th>Circuito</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(skillHealthMap).length === 0 && (
                <tr><td colSpan={8} style={{ color: 'var(--text-dim)' }}>Nenhuma métrica disponível</td></tr>
              )}
              {Object.entries(skillHealthMap).map(([name, s]) => (
                <tr key={name}>
                  <td style={{ fontWeight: 600 }}>{name}</td>
                  <td>{s.executions}</td>
                  <td style={{ color: 'var(--green)' }}>{s.success_rate_pct}%</td>
                  <td style={{ color: 'var(--red)' }}>{s.error_rate_pct}%</td>
                  <td>{s.avg_latency_ms}ms</td>
                  <td>{s.p50_ms}ms</td>
                  <td>{s.p95_ms}ms</td>
                  <td>
                    <span className={`status ${s.circuit_state === 'OPEN' ? 'inactive' : 'active'}`}>
                      {s.circuit_state}
                    </span>
                  </td>
                </tr>
              ))}
              {(skills?.per_skill ? Object.keys(skills.per_skill).filter(k => !skillHealthMap[k]) : []).map(name => {
                const ps = skills.per_skill[name];
                return (
                  <tr key={name}>
                    <td style={{ fontWeight: 600 }}>{name}</td>
                    <td>{ps.executions}</td>
                    <td style={{ color: 'var(--green)' }}>{ps.success_rate_pct || 0}%</td>
                    <td style={{ color: 'var(--red)' }}>{ps.fail > 0 ? 'Sim' : 'Não'}</td>
                    <td colSpan={4}>—</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
