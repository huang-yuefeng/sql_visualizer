import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import * as api from '../api/client';

// Consistent color palette for table names (16 colors)
const TABLE_COLORS = [
  '#4A90D9', '#2ECC71', '#E74C3C', '#F39C12', '#9B59B6',
  '#1ABC9C', '#E91E63', '#3498DB', '#E67E22', '#2C3E50',
  '#16A085', '#D35400', '#8E44AD', '#C0392B', '#27AE60', '#2980B9',
];
const tableColorCache = {};
function getTableColor(name) {
  if (tableColorCache[name]) return tableColorCache[name];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = ((hash << 5) - hash) + name.charCodeAt(i);
  tableColorCache[name] = TABLE_COLORS[Math.abs(hash) % TABLE_COLORS.length];
  return tableColorCache[name];
}

// Search history & pins from localStorage
function loadHistory() { try { return JSON.parse(localStorage.getItem('df_search_history') || '[]'); } catch { return []; } }
function saveHistory(h) { localStorage.setItem('df_search_history', JSON.stringify(h.slice(0, 20))); }
function loadPins() { try { return JSON.parse(localStorage.getItem('df_pinned_searches') || '[]'); } catch { return []; } }
function savePins(p) { localStorage.setItem('df_pinned_searches', JSON.stringify(p)); }

export default function FilterPanel({ wsId, tableIndex, fieldIndex, onSearch, loading, onFilterApplied }) {
  const [table, setTable] = useState('');
  const [field, setField] = useState('');
  const [tableSuggestions, setTableSuggestions] = useState([]);
  const [fieldSuggestions, setFieldSuggestions] = useState([]);
  const [showTableDrop, setShowTableDrop] = useState(false);
  const [showFieldDrop, setShowFieldDrop] = useState(false);
  const [filterActive, setFilterActive] = useState(false);
  const [filterStats, setFilterStats] = useState(null);
  const [uploadingFilter, setUploadingFilter] = useState(false);
  const [filterExpanded, setFilterExpanded] = useState(false);
  const [searchHistory, setSearchHistory] = useState(loadHistory);
  const [pinnedSearches, setPinnedSearches] = useState(loadPins);
  const [showHistory, setShowHistory] = useState(false);

  const stRef = useRef(null);
  const tcRef = useRef(null);

  const tableNames = Object.keys(tableIndex || {});
  const fieldNames = Object.keys(fieldIndex || {});

  // Autocomplete: table
  useEffect(() => {
    if (!table) { setTableSuggestions(tableNames.slice(0, 20)); return; }
    const q = table.toLowerCase();
    setTableSuggestions(tableNames.filter(n => n.toLowerCase().includes(q)).slice(0, 20));
  }, [table, tableIndex]);

  // Autocomplete: field
  useEffect(() => {
    if (!field) { setFieldSuggestions(fieldNames.slice(0, 20)); return; }
    const q = field.toLowerCase();
    setFieldSuggestions(fieldNames.filter(n => n.toLowerCase().includes(q)).slice(0, 20));
  }, [field, fieldIndex]);

  // Click-away: close autocomplete dropdowns when clicking outside
  useEffect(() => {
    const handler = (e) => {
      if (!e.target.closest('.autocomplete-wrapper')) {
        setShowTableDrop(false);
        setShowFieldDrop(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Filter field options by selected table
  const getFieldOptions = () => {
    const filterFn = (f) => !field || f.toLowerCase().includes(field.toLowerCase());
    if (table && tableIndex[table]) {
      const tableFields = (tableIndex[table].fields || []).filter(filterFn);
      if (tableFields.length > 0) return tableFields;
    }
    return fieldNames.filter(filterFn).slice(0, 20);
  };

  // Filter table options by selected field
  const getTableOptions = () => {
    if (!field || !fieldIndex[field]) return tableSuggestions;
    return (fieldIndex[field].tables || []).filter(t =>
      !table || t.toLowerCase().includes(table.toLowerCase())
    );
  };

  const canSearch = table && field && tableIndex[table] && fieldIndex[field];

  // Search trigger — adds to history, updates pins
  const doSearch = (t, f) => {
    if (!t || !f) return;
    const entry = { table: t, field: f, time: Date.now() };
    const newHistory = [entry, ...searchHistory.filter(h => !(h.table === t && h.field === f))];
    setSearchHistory(newHistory);
    saveHistory(newHistory);
    onSearch(t, f);
  };

  // Enter key in field input triggers search
  const handleFieldKeyDown = (e) => {
    if (e.key === 'Enter' && canSearch) doSearch(table, field);
  };

  // Pin/unpin a search
  const togglePin = (t, f) => {
    const key = `${t}.${f}`;
    const existing = pinnedSearches.find(p => p.table === t && p.field === f);
    let newPins;
    if (existing) newPins = pinnedSearches.filter(p => !(p.table === t && p.field === f));
    else newPins = [...pinnedSearches, { table: t, field: f }];
    setPinnedSearches(newPins);
    savePins(newPins);
  };
  const isPinned = (t, f) => pinnedSearches.some(p => p.table === t && p.field === f);

  // ── CSV Filter Upload ────────────────────────────────────────────
  const handleUploadFilter = async () => {
    if (!wsId) return;
    const stFile = stRef.current?.files?.[0];
    const tcFile = tcRef.current?.files?.[0];
    if (!stFile && !tcFile) {
      setUploadingFilter(true);
      try {
        await api.uploadFilterConfig(wsId, null, null);
        setFilterActive(false);
        setFilterStats(null);
      } catch (e) { console.error(e); }
      setUploadingFilter(false);
      return;
    }
    setUploadingFilter(true);
    try {
      const result = await api.uploadFilterConfig(wsId, stFile, tcFile);
      setFilterActive(result.filtered);
      setFilterStats(`${result.table_count} tables, ${result.field_count} fields`);
      if (onFilterApplied) await onFilterApplied(result);
    } catch (e) { console.error(e); }
    setUploadingFilter(false);
  };

  const handleClearFilter = async () => {
    if (!wsId) return;
    try {
      await api.uploadFilterConfig(wsId, null, null);
      setFilterActive(false);
      setFilterStats(null);
      if (onFilterApplied) await onFilterApplied(null);
    } catch (e) { console.error(e); }
  };

  return (
    <div className="filter-panel">
      <h3>Search Data Flow</h3>

      {/* ── Prominent Index Filter Banner ── */}
      <div className={`index-filter-banner ${filterActive ? 'active' : ''}`}>
        <div className="ifb-header" onClick={() => setFilterExpanded(!filterExpanded)}>
          <span className="ifb-icon">{filterActive ? '🔍' : '📋'}</span>
          <span className="ifb-title">
            {filterActive 
              ? `Index Filter ACTIVE — ${filterStats || ''}` 
              : 'Narrow Index (optional)'}
          </span>
          <span className="ifb-toggle">{filterExpanded ? '▲' : '▼'}</span>
        </div>
        {filterExpanded && (
          <div className="ifb-body">
            <p className="ifb-hint">
              Upload CSVs to limit which tables/fields appear in autocomplete.
              If your project has hundreds of tables, this makes search much faster.
            </p>
            <label className="filter-file-label">
              Script→Table CSV (SCRIPT_NAME, TABLE_NAME)
              <input type="file" accept=".csv,.txt" ref={stRef} />
            </label>
            <label className="filter-file-label">
              Table→Column CSV (SYSTEM, TABLE_NAME, COL_NAME, COL_COMMENT)
              <input type="file" accept=".csv,.txt" ref={tcRef} />
            </label>
            <div className="ifb-actions">
              <button className="btn btn-primary btn-sm" onClick={handleUploadFilter}
                disabled={uploadingFilter}>
                {uploadingFilter ? 'Applying...' : 'Apply Filter'}
              </button>
              {filterActive && (
                <button className="btn btn-outline btn-sm" onClick={handleClearFilter}>
                  Clear Filter
                </button>
              )}
            </div>
            {filterStats && <div className="filter-stats">{filterStats}</div>}
          </div>
        )}
      </div>

      <div className="autocomplete-wrapper">
        <label>Table</label>
        <input value={table} onChange={e => { setTable(e.target.value); setShowTableDrop(true); }}
          onFocus={() => setShowTableDrop(true)} onFocusCapture={() => setShowFieldDrop(false)}
          onBlur={() => setShowTableDrop(false)}
          placeholder="Type table name..." />
        {showTableDrop && getTableOptions().length > 0 && (
          <div className="autocomplete-dropdown">
            {getTableOptions().map(t => (
              <div key={t} className="ac-item" onMouseDown={() => { setTable(t); setShowTableDrop(false); }}>
                <span className="ac-color-dot" style={{ 
                  display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                  background: getTableColor(t), marginRight: 6, flexShrink: 0
                }} />
                {t}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="autocomplete-wrapper">
        <label>Field</label>
        <input value={field} onChange={e => { setField(e.target.value); setShowFieldDrop(true); }}
          onFocus={() => setShowFieldDrop(true)} onFocusCapture={() => setShowTableDrop(false)}
          onBlur={() => setShowFieldDrop(false)}
          onKeyDown={handleFieldKeyDown}
          placeholder="Type field name... (Enter to search)" />
        {showFieldDrop && getFieldOptions().length > 0 && (
          <div className="autocomplete-dropdown">
            {getFieldOptions().map(f => (
              <div key={f} className="ac-item" onMouseDown={() => { setField(f); setShowFieldDrop(false); }}>
                <span className="ac-color-dot" style={{ 
                  display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                  background: fieldIndex[f]?.tables?.[0] ? getTableColor(fieldIndex[f].tables[0]) : '#666',
                  marginRight: 6, flexShrink: 0
                }} />
                {f}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="search-actions">
        <button className="btn btn-primary" disabled={!canSearch || loading}
          onClick={() => doSearch(table, field)}>
          {loading ? 'Searching...' : 'Search'}
        </button>
        {table && field && (
          <button className={`btn btn-sm ${isPinned(table, field) ? 'btn-active' : 'btn-outline'}`}
            onClick={() => togglePin(table, field)}
            title={isPinned(table, field) ? 'Unpin this search' : 'Pin this search for quick access'}>
            {isPinned(table, field) ? '★' : '☆'}
          </button>
        )}
      </div>

      {/* Pinned searches quick access */}
      {pinnedSearches.length > 0 && (
        <div className="pinned-searches">
          <div className="pinned-label">Pinned:</div>
          {pinnedSearches.map(p => (
            <button key={`${p.table}.${p.field}`} className="btn btn-sm btn-outline pinned-chip"
              onClick={() => { setTable(p.table); setField(p.field); doSearch(p.table, p.field); }}
              title="Click to search">
              {p.table}.{p.field}
              <span className="pin-remove" onClick={(e) => { e.stopPropagation(); togglePin(p.table, p.field); }}>×</span>
            </button>
          ))}
        </div>
      )}

      {/* Search history dropdown */}
      {searchHistory.length > 0 && (
        <div className="search-history">
          <div className="history-toggle" onClick={() => setShowHistory(!showHistory)}>
            🕐 Recent {showHistory ? '▲' : '▼'}
          </div>
          {showHistory && (
            <div className="history-dropdown">
              {searchHistory.slice(0, 10).map((h, i) => (
                <div key={i} className="history-item"
                  onMouseDown={() => { setTable(h.table); setField(h.field); setShowHistory(false); }}>
                  <span className="ac-color-dot" style={{ background: getTableColor(h.table) }} />
                  {h.table}.{h.field}
                  <span className="history-time">{new Date(h.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
