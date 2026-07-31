import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';

export default function Workers() {
  const [workers, setWorkers] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.get('/api/status');
      const w = data.workers || [];
      setWorkers(Array.isArray(w) ? w : []);
    } catch (err) {
      setWorkers([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAction = async (workerId, action) => {
    setLoading(true);
    try {
      await api.post(`/api/workers/${workerId}/${action}`);
      await load();
    } catch (err) {
      alert(`Erro: ${err.message}`);
    }
    setLoading(false);
  };

  return (
    <div>
      <h1 className="page-title">Workers</h1>

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2 style={{ margin: 0 }}>Gerenciamento de Workers</h2>
          <button className="btn primary" onClick={load} disabled={loading}>
            Recarregar
          </button>
        </div>

        {workers.length === 0 ? (
          <div className="meta" style={{ textAlign: 'center', padding: 24 }}>
            Nenhum worker encontrado. Os workers aparecerão aqui quando estiverem ativos.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID / Nome</th>
                <th>Status</th>
                <th>Filas</th>
                <th>Processados</th>
                <th>Última Atividade</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {workers.map((w, i) => (
                <tr key={w.id || w.name || i}>
                  <td style={{ fontWeight: 600 }}>{w.name || w.id || `Worker #${i}`}</td>
                  <td>
                    <span className={`status ${w.running ? 'active' : 'inactive'}`}>
                      {w.running ? 'Rodando' : 'Parado'}
                    </span>
                  </td>
                  <td>{w.queues ? w.queues.join(', ') : '-'}</td>
                  <td>{w.processed ?? w.tasks_done ?? 0}</td>
                  <td>{w.last_active || w.updated_at || '-'}</td>
                  <td>
                    <div style={{ display: 'flex', gap: 6 }}>
                      {w.running ? (
                        <button className="btn outline" disabled={loading}
                          onClick={() => handleAction(w.id || w.name, 'pause')}>
                          Pausar
                        </button>
                      ) : (
                        <button className="btn green" disabled={loading}
                          onClick={() => handleAction(w.id || w.name, 'start')}>
                          Iniciar
                        </button>
                      )}
                      <button className="btn red" disabled={loading}
                        onClick={() => handleAction(w.id || w.name, 'stop')}>
                        Parar
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
