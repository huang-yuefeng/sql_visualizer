import React from 'react';
import ReactDOM from 'react-dom/client';
import AppShell from './AppShell';
import './styles/app.css';

// J12-14: apply the stored theme (default LIGHT) before the first paint
// so the page never flashes the wrong theme — the CSS tokens resolve
// against [data-theme] on <html>. AppShell keeps it in sync afterwards.
try {
  document.documentElement.setAttribute('data-theme', localStorage.getItem('theme') || 'light');
} catch (e) { /* ignore storage access errors */ }

ReactDOM.createRoot(document.getElementById('root')).render(
  <AppShell />
);
