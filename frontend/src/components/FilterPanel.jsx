import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import * as api from '../api/client';
import { filterNames, resolveNameCi } from '../utils/nameFilter';

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

// Search history & pins from localStorage — namespaced PER USER (E-M2/#277).
// The old global `df_search_history`/`df_pinned_searches` keys leaked user A's
// terms/pins into user B after a logout+login (nothing cleared them). The
// username flows in from AppShell → DataFlowApp → FilterPanel, so each user's
// history/pins live under `df_search_history:{username}`. A missing username
// (defensive) falls back to `:anon` — never the shared global key. Clear-on-
// logout is now unnecessary; the `theme` key and the R23 one-time
// `df_last_search_view` purge stay global and untouched.
function histKey(username) { return `df_search_history:${username || 'anon'}`; }
function pinsKey(username) { return `df_pinned_searches:${username || 'anon'}`; }
function loadHistory(username) { try { return JSON.parse(localStorage.getItem(histKey(username)) || '[]'); } catch { return []; } }
function saveHistory(username, h) { localStorage.setItem(histKey(username), JSON.stringify(h.slice(0, 20))); }
function loadPins(username) { try { return JSON.parse(localStorage.getItem(pinsKey(username)) || '[]'); } catch { return []; } }
function savePins(username, p) { localStorage.setItem(pinsKey(username), JSON.stringify(p)); }

export default function FilterPanel({ wsId, username, tableIndex, fieldIndex, onSearch, loading, onFilterApplied, onError, recover }) {
  const [table, setTable] = useState('');
  const [field, setField] = useState('');
  const [tableSuggestions, setTableSuggestions] = useState([]);
  const [fieldSuggestions, setFieldSuggestions] = useState([]);
  const [showTableDrop, setShowTableDrop] = useState(false);
  const [showFieldDrop, setShowFieldDrop] = useState(false);
  const [filterActive, setFilterActive] = useState(false);
  const [filterStats, setFilterStats] = useState(null);
  const [filterWarning, setFilterWarning] = useState(null);   // F4/R2: payload.warning
  const [filterIgnored, setFilterIgnored] = useState([]);     // F4/R2: payload.ignored_tables
  const [filterIgnoredRows, setFilterIgnoredRows] = useState(null); // D2: payload.ignored_rows
  const [uploadingFilter, setUploadingFilter] = useState(false);
  const [searchHistory, setSearchHistory] = useState(() => loadHistory(username));
  const [pinnedSearches, setPinnedSearches] = useState(() => loadPins(username));
  const [showHistory, setShowHistory] = useState(false);
  // R38 ruling (2026-08-27): the direction toggle is REMOVED — every search
  // runs downstream (reading flow), the only direction. The onSearch signature
  // keeps its third argument so the DataFlowApp contract is untouched.

  const stRef = useRef(null);
  const tcRef = useRef(null);

  // Search recovery (2026-08-27): opening a PERSISTED view (old workspace →
  // tree → L1/L2) must show WHICH table.field it belongs to — the panel is
  // per-session state, so the values ride in via the `recover` prop keyed by
  // a nonce (DataFlowApp bumps it on every tree navigation). Fires ONLY on
  // the nonce, never on value identity: an in-flight user edit is never
  // clobbered unless a view was actually opened.
  useEffect(() => {
    if (!recover || !recover.nonce) return;
    if (recover.table && recover.field) {
      setTable(recover.table);
      setField(recover.field);
    }
  }, [recover && recover.nonce]);  // eslint-disable-line react-hooks/exhaustive-deps

  const tableNames = Object.keys(tableIndex || {});
  const fieldNames = Object.keys(fieldIndex || {});

  // Autocomplete: table
  useEffect(() => {
    setTableSuggestions(filterNames(tableNames, table));
  }, [table, tableIndex]);

  // Autocomplete: field
  useEffect(() => {
    setFieldSuggestions(filterNames(fieldNames, field));
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

  // F5 (audit #383): the index keys are case-sensitive (each script's own
  // casing — TEMP_RFN vs temp_rfn), and the backend search matches them
  // EXACTLY, so a name typed in a different casing used to silently
  // disable search (canSearch required exact keys; Enter was a no-op with
  // no message). Resolve typed names case-insensitively to the canonical
  // index key (exact spelling wins, then unique case-variant) — search,
  // history and pins always run with the canonical key, and the inputs
  // echo it so the panel shows what was actually searched.
  const resolvedTable = resolveNameCi(tableNames, table);
  const resolvedField = resolveNameCi(fieldNames, field);

  // F-B2 (S4 finding 9): the suggestions dropdown is an absolutely-positioned
  // overlay that hangs over whatever sits below its input — after typing a
  // complete table name it covered the Field input and ATE the click aimed at
  // it (the item won, the input never got focus). Blur + click-outside already
  // closed it, but only once the user clicked elsewhere. Once the typed name
  // RESOLVES to an index key (exact spelling or unique case-variant) the
  // suggestions have nothing left to offer — close it then; the next edit
  // (onChange) or focus reopens it, so browsing alternatives still works.
  useEffect(() => {
    if (resolvedTable) setShowTableDrop(false);
  }, [resolvedTable]);
  useEffect(() => {
    if (resolvedField) setShowFieldDrop(false);
  }, [resolvedField]);

  // Filter field options by selected table (resolved — a wrong-case table
  // still narrows the field dropdown to that table's fields)
  const getFieldOptions = () => {
    if (resolvedTable && tableIndex[resolvedTable]) {
      const tableFields = filterNames(tableIndex[resolvedTable].fields || [], field);
      if (tableFields.length > 0) return tableFields;
    }
    return filterNames(fieldNames, field);
  };

  // Filter table options by selected field
  const getTableOptions = () => {
    if (!resolvedField || !fieldIndex[resolvedField]) return tableSuggestions;
    const filtered = filterNames(fieldIndex[resolvedField].tables || [], table);
    // Bug 49: fall back to full suggestions when the field has no indexed tables
    // (e.g. field only seen under an alias) — otherwise the dropdown is empty
    return filtered.length > 0 ? filtered : tableSuggestions;
  };

  // F5 (audit #383) + V2-N3 (2026-08-29): "no such table/field in the index"
  // is the TERMINAL state of a name that resolves to nothing — not a
  // mid-prefix state. While the typed prefix still has live suggestions the
  // dropdown is the right answer, and the message must stay silent: typing
  // `bdm_acc` used to render 12 suggestions AND the missing-message at the
  // same time. The gate is therefore the dropdown's own option list — the
  // exact complement of the `…Options().length > 0` render condition (and of
  // the F-B2 close-on-resolve rule: a RESOLVED name shows neither). The
  // message does not depend on focus, so it survives blur like before.
  const tableMissing = table.length > 0 && !resolvedTable && getTableOptions().length === 0;
  const fieldMissing = field.length > 0 && !resolvedField && getFieldOptions().length === 0;

  const canSearch = Boolean(resolvedTable && resolvedField);

  // Search trigger — adds to history, updates pins
  const doSearch = (t, f) => {
    const rt = resolveNameCi(tableNames, t);
    const rf = resolveNameCi(fieldNames, f);
    if (!rt || !rf) return;
    if (rt !== t) setTable(rt);   // echo the canonical spelling
    if (rf !== f) setField(rf);
    const entry = { table: rt, field: rf, time: Date.now() };
    const newHistory = [entry, ...searchHistory.filter(h => !(h.table === rt && h.field === rf))];
    setSearchHistory(newHistory);
    saveHistory(username, newHistory);
    onSearch(rt, rf, 'downstream');
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
    savePins(username, newPins);
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
        setFilterWarning(null);
        setFilterIgnored([]);
        setFilterIgnoredRows(null);
      } catch (e) { onError?.(e && e.message ? e.message : 'Filter clear failed'); }
      setUploadingFilter(false);
      return;
    }
    setUploadingFilter(true);
    try {
      const result = await api.uploadFilterConfig(wsId, stFile, tcFile);
      setFilterActive(result.filtered);
      setFilterStats(`${result.table_count} tables, ${result.field_count} fields`);
      // F4/R2 + D2: surface warning, ignored tables and ignored rows from the payload
      setFilterWarning(result.warning || null);
      setFilterIgnored(Array.isArray(result.ignored_tables) ? result.ignored_tables : []);
      setFilterIgnoredRows(typeof result.ignored_rows === 'number' ? result.ignored_rows : null);
      if (onFilterApplied) await onFilterApplied(result);
    } catch (e) { onError?.(e && e.message ? e.message : 'Filter apply failed'); }
    setUploadingFilter(false);
  };

  const handleClearFilter = async () => {
    if (!wsId) return;
    try {
      await api.uploadFilterConfig(wsId, null, null);
      setFilterActive(false);
      setFilterStats(null);
      setFilterWarning(null);
      setFilterIgnored([]);
      setFilterIgnoredRows(null);
      if (onFilterApplied) await onFilterApplied(null);
    } catch (e) { onError?.(e && e.message ? e.message : 'Filter clear failed'); }
  };

  return (
    <div className="filter-panel">
      <h3>Search Data Flow</h3>

      {/* ── FILTER area — upload CSVs to narrow the autocomplete index ── */}
      <section className={`filter-area ${filterActive ? 'active' : ''}`} data-testid="filter-area">
        <div className="area-header">
          <span className="area-icon">📋</span>
          <span className="area-title">Filter</span>
          {filterActive && filterStats && (
            <span className="area-status">ACTIVE — {filterStats}</span>
          )}
        </div>
        {/* F4/R2 + D2: warn when the filter dropped rows/tables */}
        {(filterWarning || filterIgnoredRows > 0) && (
          <div className="filter-warning">
            <span className="fw-icon">⚠️</span>
            <div className="fw-text">
              {filterWarning}
              {filterIgnoredRows > 0 && (
                <div className="fw-ignored">{filterIgnoredRows} rows ignored</div>
              )}
              {filterIgnored.length > 0 && (
                <div className="fw-ignored">
                  {filterIgnored.length} table{filterIgnored.length > 1 ? 's' : ''} ignored:{' '}
                  {filterIgnored.slice(0, 10).join(', ')}
                  {filterIgnored.length > 10 && ` … +${filterIgnored.length - 10} more`}
                </div>
              )}
            </div>
          </div>
        )}
        <div className="filter-area-body">
          <p className="filter-hint">
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
          <div className="filter-actions">
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
        </div>
      </section>

      {/* ── SEARCH area — table/field + direction + search ── */}
      <section className="search-area" data-testid="search-area">
        <div className="area-header">
          <span className="area-icon">🔍</span>
          <span className="area-title">Search</span>
        </div>
        <div className="search-area-body">

      <div className="autocomplete-wrapper">
        <label>Table</label>
        <input value={table} onChange={e => { setTable(e.target.value); setShowTableDrop(true); }}
          onFocus={() => setShowTableDrop(true)} onFocusCapture={() => setShowFieldDrop(false)}
          onBlur={() => setShowTableDrop(false)}
          placeholder="Type table name..." />
        {/* `!resolvedTable` — F-B2 (S4 finding 9): a resolved name renders no
            overlay, so the Field input below is never covered or click-blocked. */}
        {showTableDrop && !resolvedTable && getTableOptions().length > 0 && (
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
        {/* F5 (audit #383) + V2-N3: a typed table that resolves to no index
            key (any casing) AND has no live suggestion gets an inline message
            — never a silent no-op, never a mid-prefix false alarm. */}
        {tableMissing && (
          <div className="search-name-missing" data-testid="table-missing-msg">
            no such table in the index — check spelling
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
        {/* `!resolvedField` — same contract as the table dropdown above. */}
        {showFieldDrop && !resolvedField && getFieldOptions().length > 0 && (
          <div className="autocomplete-dropdown">
            {getFieldOptions().map(f => (
              <div key={f} className="ac-item" onMouseDown={() => { setField(f); setShowFieldDrop(false); }}>
                <span className="ac-color-dot" style={{
                  display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                  background: fieldIndex[f]?.tables?.[0] ? getTableColor(fieldIndex[f].tables[0]) : 'var(--ink-400)',
                  marginRight: 6, flexShrink: 0
                }} />
                {f}
              </div>
            ))}
          </div>
        )}
        {/* F5 (audit #383) + V2-N3: same contract for the field — an
            unresolvable name with no live suggestion shows WHY Enter did
            nothing, instead of disabling search silently. */}
        {fieldMissing && (
          <div className="search-name-missing" data-testid="field-missing-msg">
            no such table.field in the index — check spelling
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
        </div>
      </section>

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
