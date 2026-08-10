import React, { useRef, useEffect, useCallback, useState, useImperativeHandle } from 'react';
import * as api from '../api/client';

const DEFAULT_CONFIG = {
  include_ctes: true,
  include_temp_tables: true,
  wrap_transaction: false,
  add_header: true,
  context_lines: 3,
  include_dependencies: true,
  dialect: 'auto',
  format_output: false,
  include_comments: true,
  target_only: false,
};

const CONFIG_LABELS = {
  add_header: 'Add header comment',
  wrap_transaction: 'Wrap in BEGIN/COMMIT',
  include_comments: 'Include inline comments',
  include_ctes: 'Include CTE definitions',
  include_temp_tables: 'Include temp table DDL',
  include_dependencies: 'Include dependencies',
  format_output: 'Format SQL output',
  target_only: 'Target variable only (no context)',
};

const SqlPanel = React.forwardRef(function SqlPanel({ sqlText, sqlHighlightLine, scriptName, wsId, table, field }, ref) {
  const containerRef = useRef(null);
  const configRef = useRef(null);
  const [showConfig, setShowConfig] = useState(false);
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [saveStatus, setSaveStatus] = useState(''); // '', 'saving', 'saved', 'error'
  const debounceTimer = useRef(null);
  const [editingKey, setEditingKey] = useState(null);
  const [editValue, setEditValue] = useState('');

  useEffect(() => {
    if (!wsId || configLoaded) return;
    api.getExportConfig(wsId).then(cfg => {
      setConfig({ ...DEFAULT_CONFIG, ...cfg });
      setConfigLoaded(true);
    }).catch(() => setConfigLoaded(true));
  }, [wsId]);

  // R25/§8.8: the clicked edge's anchor is exactly ONE line — the
  // per-edge `highlight_line` is the single source of truth (the old
  // response-level `highlights` and per-edge range fields are gone).
  const edgeHighlightSet = new Set();
  if (Number.isInteger(sqlHighlightLine) && sqlHighlightLine >= 1) {
    edgeHighlightSet.add(sqlHighlightLine);
  }

  const lines = sqlText ? sqlText.split('\n') : [];

  // R11-3: imperative scroll API — the code-evidence rows in the reason
  // panel call scrollToLine(line) to bring that SQL line into view.
  const scrollToLine = useCallback((line) => {
    if (!containerRef.current || !Number.isInteger(line) || line < 1) return;
    const el = containerRef.current.querySelector(`[data-line="${line}"]`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, []);

  useImperativeHandle(ref, () => ({ scrollToLine }), [scrollToLine]);

  // Auto-scroll to the edge's anchor line when the selection changes
  useEffect(() => {
    if (Number.isInteger(sqlHighlightLine) && sqlHighlightLine >= 1) {
      scrollToLine(sqlHighlightLine);
    }
  }, [sqlHighlightLine, scrollToLine]);

  // ── Enhanced Export ──
  const handleExport = useCallback(() => {
    const allLines = lines;
    const ctx = config.context_lines || 3;

    // R25: the selected edge's anchor line is the only line source now —
    // export its context; without a selection, export the whole script.
    const anchor = (Number.isInteger(sqlHighlightLine) && sqlHighlightLine >= 1)
      ? sqlHighlightLine : null;
    const hls = anchor ? [[anchor, anchor]] : [[1, allLines.length]];

    const ranges = [];
    for (const h of hls) {
      ranges.push([Math.max(1, h[0] - ctx), Math.min(allLines.length, h[1] + ctx)]);
    }

    ranges.sort((a, b) => a[0] - b[0]);
    const merged = ranges.length ? [ranges[0]] : [];
    for (let i = 1; i < ranges.length; i++) {
      const last = merged[merged.length - 1];
      if (ranges[i][0] <= last[1] + 1) {
        merged[merged.length - 1][1] = Math.max(last[1], ranges[i][1]);
      } else {
        merged.push(ranges[i]);
      }
    }

    const parts = [];
    if (config.add_header) {
      parts.push('-- ============================================================');
      parts.push('-- Exported by SQL Data Flow Debugger v3.1');
      if (table && field) parts.push(`-- Target: ${table}.${field}`);
      if (scriptName) parts.push(`-- Source: ${scriptName}`);
      parts.push(`-- Exported: ${new Date().toISOString().replace('T', ' ').slice(0, 19)} UTC`);
      parts.push('-- ============================================================');
      parts.push('');
    }
    if (config.wrap_transaction) { parts.push('BEGIN;'); parts.push(''); }
    parts.push('-- ── Data Flow SQL ──');
    if (config.include_comments && table && field) parts.push(`-- Target: ${table}.${field}`);

    let prevEnd = 0;
    for (const [start, end] of merged) {
      if (start > prevEnd + 1 && prevEnd > 0) parts.push(`-- ... ${start - prevEnd - 1} lines omitted ...`);
      for (let j = start - 1; j < end; j++) {
        if (j < allLines.length) parts.push(allLines[j]);
      }
      prevEnd = end;
    }

    if (config.wrap_transaction) { parts.push(''); parts.push('COMMIT;'); }

    const blob = new Blob([parts.join('\n')], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = (scriptName || 'export') + '_relevant.sql';
    a.click();
    URL.revokeObjectURL(url);
  }, [sqlText, sqlHighlightLine, lines, scriptName, config, table, field]);

  // ── Config handlers ──
  const saveCfg = (newConfig) => {
    setConfig(newConfig);
    if (!wsId) return;
    // Debounce: clear previous timer
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    setSaveStatus('saving');
    debounceTimer.current = setTimeout(() => {
      api.saveExportConfig(wsId, newConfig)
        .then(() => setSaveStatus('saved'))
        .catch(() => setSaveStatus('error'));
      // Clear status after 2s
      setTimeout(() => setSaveStatus(s => s === 'saving' ? s : ''), 2000);
    }, 500);
  };

  const toggleBool = (key) => {
    saveCfg({ ...config, [key]: !config[key] });
  };

  const startEdit = (key) => {
    setEditingKey(key);
    setEditValue(String(config[key]));
  };

  const commitEdit = () => {
    if (!editingKey) return;
    let val = editValue;
    if (editingKey === 'context_lines') val = Math.max(0, Math.min(20, parseInt(val) || 0));
    else if (editingKey === 'dialect') val = String(val).trim() || 'auto';
    else if (typeof config[editingKey] === 'boolean') val = editValue === 'true';
    saveCfg({ ...config, [editingKey]: val });
    setEditingKey(null);
  };

  const handleUploadConfig = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !wsId) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const cfg = parsed.export_config || parsed;
      const saved = await api.saveExportConfig(wsId, cfg);
      setConfig({ ...DEFAULT_CONFIG, ...saved });
    } catch (err) {
      // Factual, per failure type: JSON parse errors vs API errors
      const msg = err && err.name === 'SyntaxError'
        ? 'Invalid config file — must be valid JSON.'
        : `Config upload failed: ${err && err.message ? err.message : 'HTTP error'}`;
      alert(msg);
    }
  };

  const handleResetConfig = async () => {
    if (!wsId) return;
    try {
      await api.resetExportConfig(wsId);
      setConfig({ ...DEFAULT_CONFIG });
    } catch (err) {
      // surface via the existing save-status indicator
      setSaveStatus('error');
    }
  };

  if (!sqlText) return null;

  const renderConfigRow = (key) => {
    const val = config[key];
    const isEditing = editingKey === key;
    const label = CONFIG_LABELS[key] || key;

    if (key === 'context_lines') {
      return (
        <div key={key} className="config-row">
          <span className="config-label" onClick={() => startEdit(key)}>
            {label}: <strong>{val}</strong>
          </span>
          {isEditing ? (
            <div className="config-edit-inline">
              <input type="number" min="0" max="20" value={editValue}
                onChange={e => setEditValue(e.target.value)}
                onBlur={commitEdit}
                onKeyDown={e => e.key === 'Enter' && commitEdit()}
                autoFocus style={{ width: 50 }} />
            </div>
          ) : (
            <input type="range" min="0" max="20" value={val}
              onChange={e => saveCfg({ ...config, context_lines: parseInt(e.target.value) })}
              className="config-slider" />
          )}
        </div>
      );
    }

    if (key === 'dialect') {
      return (
        <div key={key} className="config-row">
          <span className="config-label" onClick={() => startEdit(key)}>
            Dialect: <strong>{val}</strong>
          </span>
          {isEditing ? (
            <div className="config-edit-inline">
              <select value={editValue} onChange={e => { setEditValue(e.target.value); saveCfg({ ...config, dialect: e.target.value }); setEditingKey(null); }}
                autoFocus onBlur={() => setEditingKey(null)}>
                <option value="auto">auto</option>
                <option value="postgresql">postgresql</option>
                <option value="mysql">mysql</option>
                <option value="bigquery">bigquery</option>
                <option value="snowflake">snowflake</option>
                <option value="sqlserver">sqlserver</option>
              </select>
            </div>
          ) : null}
        </div>
      );
    }

    if (typeof val === 'boolean') {
      return (
        <div key={key} className="config-row config-row-bool">
          <label className="config-toggle" onClick={() => toggleBool(key)}>
            <input type="checkbox" checked={val} onChange={() => toggleBool(key)} />
            <span>{label}</span>
          </label>
        </div>
      );
    }

    return null;
  };

  const boolKeys = Object.keys(DEFAULT_CONFIG).filter(k => typeof DEFAULT_CONFIG[k] === 'boolean');
  const otherKeys = Object.keys(DEFAULT_CONFIG).filter(k => typeof DEFAULT_CONFIG[k] !== 'boolean');

  return (
    <div className="sql-panel">
      <div className="sql-panel-header">
        <h3>SQL</h3>
        <div className="sql-panel-actions">
          <button className="btn btn-outline btn-sm" onClick={handleExport}>⬇ Export</button>
          <button className="btn btn-outline btn-sm"
            onClick={() => setShowConfig(!showConfig)}
            style={showConfig ? { borderColor: '#F39C12', color: '#F39C12' } : {}}>
            ⚙ Config
          </button>
          {saveStatus && (
            <span className={`config-save-status config-save-${saveStatus}`} title={
              saveStatus === 'saved' ? 'Saved ✓' : saveStatus === 'error' ? 'Save failed ✗' : 'Saving…'
            }>
              {saveStatus === 'saving' ? '●' : saveStatus === 'saved' ? '✓' : '✗'}
            </span>
          )}
        </div>
      </div>

      {showConfig && (
        <div className="export-config-panel">
          <div className="config-section">
            {boolKeys.map(k => renderConfigRow(k))}
            {otherKeys.map(k => renderConfigRow(k))}
          </div>
          <div className="config-section config-upload">
            <label className="upload-btn upload-btn-sm">
              Upload Config (JSON)
              <input type="file" accept=".json" ref={configRef}
                onChange={handleUploadConfig} style={{ display: 'none' }} />
            </label>
            <button className="btn btn-outline btn-sm" onClick={handleResetConfig}>
              Reset Defaults
            </button>
          </div>
        </div>
      )}

      <div className="sql-content" ref={containerRef}>
        {lines.map((line, i) => {
          const lineNum = i + 1;
          const isEdgeHighlighted = edgeHighlightSet.has(lineNum);
          const className = [
            'sql-line',
            isEdgeHighlighted ? 'edge-highlighted' : ''
          ].filter(Boolean).join(' ');
          return (
            <div key={`${scriptName || "sql"}-${lineNum}`} data-line={lineNum}
              className={className}>
              <span className="line-num">{lineNum}</span>
              <span className="line-text">{line || ' '}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
});

export default SqlPanel;
