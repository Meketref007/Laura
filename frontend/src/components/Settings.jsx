import React, { useState, useEffect } from 'react';
import { getApiKey } from '../api';

export default function Settings() {
  const [apiKey, setApiKey] = useState(getApiKey() || '');
  const [theme, setTheme] = useState('dark');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const savedTheme = localStorage.getItem('laura_theme') || 'dark';
    setTheme(savedTheme);
    document.documentElement.setAttribute('data-theme', savedTheme);
  }, []);

  const handleSaveKey = () => {
    localStorage.setItem('laura_api_key', apiKey);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleClearKey = () => {
    localStorage.removeItem('laura_api_key');
    setApiKey('');
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleThemeChange = (t) => {
    setTheme(t);
    localStorage.setItem('laura_theme', t);
    document.documentElement.setAttribute('data-theme', t);
  };

  return (
    <div>
      <h1 className="page-title">Configurações</h1>

      <div className="grid">
        <div className="card">
          <h2>API Key</h2>
          <div className="form-group">
            <label>Chave de API para autenticação</label>
            <input
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder="Insira sua API key..."
            />
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button className="btn primary" onClick={handleSaveKey}>
              Salvar
            </button>
            <button className="btn outline" onClick={handleClearKey}>
              Limpar
            </button>
          </div>
          {saved && <p style={{ color: 'var(--green)', fontSize: 12, marginTop: 8 }}>Salvo!</p>}
        </div>

        <div className="card">
          <h2>Aparência</h2>
          <div className="form-group">
            <label>Tema</label>
            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <button
                className={`btn ${theme === 'dark' ? 'primary' : 'outline'}`}
                onClick={() => handleThemeChange('dark')}
              >
                Escuro
              </button>
              <button
                className={`btn ${theme === 'light' ? 'primary' : 'outline'}`}
                onClick={() => handleThemeChange('light')}
              >
                Claro
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="section">
        <h3>Sobre</h3>
        <div className="card">
          <div className="meta">
            <p><strong>Laura Dashboard</strong> v1.0.0</p>
            <p style={{ marginTop: 8 }}>
              Dashboard de monitoramento para o agente autônomo Laura.
              Conecta-se via WebSocket para atualizações em tempo real e
              usa a API REST para controle e consulta de métricas.
            </p>
            <p style={{ marginTop: 8 }}>
              WebSocket: <code>/ws/stream</code> | API: <code>/api/*</code>
            </p>
          </div>
        </div>
      </div>

      <div className="section">
        <h3>Informações do Navegador</h3>
        <div className="card">
          <pre>{JSON.stringify({
            userAgent: navigator.userAgent,
            language: navigator.language,
            online: navigator.onLine,
            cookiesEnabled: navigator.cookieEnabled,
            localStorage: !!window.localStorage,
            serviceWorker: 'serviceWorker' in navigator,
          }, null, 2)}</pre>
        </div>
      </div>
    </div>
  );
}
