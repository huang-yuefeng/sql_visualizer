import React, { useState, useRef, useEffect } from 'react';
import App from './App';
import DataFlowApp from './DataFlowApp';

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null }; }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center', color: '#e0e0e0', background: '#1a1a2e', minHeight: '100vh' }}>
          <h2>Something went wrong</h2>
          <p style={{ color: '#DA4453' }}>{this.state.error?.message || 'Unknown error'}</p>
          <button onClick={() => { this.setState({ hasError: false }); window.location.reload(); }}
            style={{ padding: '8px 20px', marginTop: 16, cursor: 'pointer', background: '#2ECC71', border: 'none', borderRadius: 4, color: '#000' }}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// Persist children so React never unmounts them
function PersistentPanel({ show, children }) {
  const [hasMounted, setHasMounted] = useState(show);
  useEffect(() => { if (show) setHasMounted(true); }, [show]);
  
  if (!hasMounted) return null;
  
  return (
    <div style={{ display: show ? 'block' : 'none' }}>
      {children}
    </div>
  );
}

export default function AppShell() {
  const [mode, setMode] = useState('dataflow');
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'dark');
  
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  return (
    <ErrorBoundary>
      <div className="mode-tabs">
        <button className={mode === 'dataflow' ? 'active' : ''} onClick={() => setMode('dataflow')}>
          Data Flow Debugger
        </button>
        <button className={mode === 'analysis' ? 'active' : ''} onClick={() => setMode('analysis')}>
          SQL Analysis
        </button>
        <button className="theme-toggle" onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
      </div>
      <PersistentPanel show={mode === 'dataflow'}>
        <DataFlowApp />
      </PersistentPanel>
      <PersistentPanel show={mode === 'analysis'}>
        <App />
      </PersistentPanel>
    </ErrorBoundary>
  );
}
