import React, { useState, useEffect, useCallback, Component } from 'react';
import { Routes, Route, NavLink, Navigate } from 'react-router-dom';
import { api } from './api';
import Dashboard from './components/Dashboard';
import Summary from './components/Summary';
import Plans from './components/Plans';
import Skills from './components/Skills';
import Goals from './components/Goals';
import Workers from './components/Workers';
import Settings from './components/Settings';
import ABTesting from './components/ABTesting';

const NAV = [
  { path: '/', label: 'Dashboard', icon: '◉' },
  { path: '/summary', label: 'Sumário', icon: '◎' },
  { path: '/plans', label: 'Planos', icon: '⚡' },
  { path: '/skills', label: 'Skills', icon: '◆' },
  { path: '/ab-testing', label: 'A/B Test', icon: '⚗' },
  { path: '/goals', label: 'Metas', icon: '★' },
  { path: '/workers', label: 'Workers', icon: '⚙' },
  { path: '/settings', label: 'Config', icon: '☰' },
];

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="app-layout">
          <main className="main-content" style={{ marginLeft: 0, maxWidth: '100%' }}>
            <div className="error-state">
              <div className="icon">⚠</div>
              <p>Algo deu errado na interface.</p>
              <button className="btn primary" onClick={() => { this.setState({ hasError: false }); window.location.reload(); }}>
                Recarregar
              </button>
            </div>
          </main>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const [wsData, setWsData] = useState(null);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(true);
  const [offline, setOffline] = useState(false);

  const connectWs = useCallback(() => {
    setConnecting(true);
    try {
      const ws = api.ws();
      ws.onopen = () => {
        setConnected(true);
        setConnecting(false);
        setOffline(false);
        const key = localStorage.getItem('laura_api_key');
        if (key) ws.send(JSON.stringify({ type: 'auth', token: key }));
      };
      ws.onmessage = (ev) => {
        try { setWsData(JSON.parse(ev.data)); } catch (e) { /* ignore */ }
      };
      ws.onclose = () => {
        setConnected(false);
        setConnecting(false);
        setTimeout(connectWs, 3000);
      };
      ws.onerror = () => {
        ws.close();
        setOffline(true);
      };
    } catch (e) {
      setConnecting(false);
      setOffline(true);
      setTimeout(connectWs, 5000);
    }
  }, []);

  useEffect(() => { connectWs(); }, [connectWs]);

  return (
    <ErrorBoundary>
      <div className={`offline-banner ${offline ? 'visible' : ''}`}>
        API indisponível — tentando reconectar...
      </div>
      <div className="app-layout">
        <aside className="sidebar">
          <div className="sidebar-logo">
            <span>✦</span> Laura
          </div>
          <nav className="sidebar-nav">
            {NAV.map(({ path, label, icon }) => (
              <NavLink
                key={path}
                to={path}
                end={path === '/'}
                className={({ isActive }) => 'sidebar-link' + (isActive ? ' active' : '')}
              >
                <span className="icon">{icon}</span>
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-footer">
            {connecting ? (
              <span><span className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5, marginRight: 4, verticalAlign: 'middle' }} /> Conectando...</span>
            ) : connected ? (
              <span><span className="live-dot" style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: 'var(--green)', marginRight: 4 }} /> Conectado</span>
            ) : (
              <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: 'var(--red)', marginRight: 4 }} /> Desconectado</span>
            )}
          </div>
        </aside>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard wsData={wsData} />} />
            <Route path="/summary" element={<Summary wsData={wsData} />} />
            <Route path="/plans" element={<Plans />} />
            <Route path="/skills" element={<Skills />} />
            <Route path="/ab-testing" element={<ABTesting />} />
            <Route path="/goals" element={<Goals />} />
            <Route path="/workers" element={<Workers />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </ErrorBoundary>
  );
}
