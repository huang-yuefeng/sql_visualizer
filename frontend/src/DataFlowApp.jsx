
import WorkspacePanel from './components/WorkspacePanel';
import FolderTree from './components/FolderTree';
import FilterPanel from './components/FilterPanel';
import ViewBar from './components/ViewBar';
import DataFlowGraph from './components/DataFlowGraph';
import SqlPanel from './components/SqlPanel';
import EdgeReasonPanel from './components/EdgeReasonPanel';
import LogPanel from './components/LogPanel';
import ResolutionReport from './components/ResolutionReport';
import * as api from './api/client';
import pickAutoEdge from './utils/pickAutoEdge';
import { countStructureEdges } from './utils/structureEdges';
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useResizable } from './utils/useResizable';
import './styles/resizable.css';

export default function DataFlowApp() {
  const [wsId, setWsId] = useState(null);
  const [fileTree, setFileTree] = useState(null);
  const [selectedScripts, setSelectedScripts] = useState([]);
  const [tableIndex, setTableIndex] = useState({});
  const [fieldIndex, setFieldIndex] = useState({});
  const [fullTableIndex, setFullTableIndex] = useState({});
  const [fullFieldIndex, setFullFieldIndex] = useState({});
  const [indexed, setIndexed] = useState(false);
  const [stale, setStale] = useState(false);
  const [views, setViews] = useState([]);
  const [activeViewId, setActiveViewId] = useState(null);
  const parentViewIdRef = useRef(null);
  const [graphLevel, setGraphLevel] = useState('L1');
  // R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow — the
  // L2 graph hides them by default (toggle default OFF). Client-side
  // display preference only: the payload is untouched, nothing re-fetches.
  const [showStructureEdges, setShowStructureEdges] = useState(false);
  const [layoutMode, setLayoutMode] = useState('snake'); // 'snake' or 'pipeline'
  const [l1Graph, setL1Graph] = useState(null);
  const [l2Graph, setL2Graph] = useState(null);
  const [sqlText, setSqlText] = useState('');
  const [currentScriptName, setCurrentScriptName] = useState('');
  const [l2Filtered, setL2Filtered] = useState(true);
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [l2FullGraph, setL2FullGraph] = useState(null);
  const [l2Result, setL2Result] = useState(null);
  // L2 not-in-flow: the view's search field is not referenced in this
  // script — backend returns the FULL unfiltered script graph plus
  // search_matched:false + a message. Absence of search_matched = matched.
  const [l2NotInFlow, setL2NotInFlow] = useState(false);
  const [l2NotInFlowMessage, setL2NotInFlowMessage] = useState(null);
  // A3: statement-level parse errors from the level2 response
  // ({stmt_idx, detail}[]; [] when the script parses clean).
  const [l2ParseErrors, setL2ParseErrors] = useState([]);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const [activeL1Table, setActiveL1Table] = useState(null);
  const [showLog, setShowLog] = useState(true);
  // R20: index-time orphan resolution report (folder_index_service payload)
  const [resolutionStats, setResolutionStats] = useState(null);
  const [orphanFieldSamples, setOrphanFieldSamples] = useState(null);
  // R20/M11: schema_candidates_summary {total, unique_owner, r6_collision}
  const [schemaCandidates, setSchemaCandidates] = useState(null);
  // A1: schema_evidence {present, tables, columns} (index response)
  const [schemaEvidence, setSchemaEvidence] = useState(null);

  // ── Resizable panel state ─────────────────────────────────────────
  const [leftPanelWidth, setLeftPanelWidth] = useState(260);
  const [l2PanelHeight, setL2PanelHeight] = useState(420);
  const [l2PanelWidth, setL2PanelWidth] = useState(420);
  const [sqlPanelHeight, setSqlPanelHeight] = useState(250);
  // Issue 1 (fix 2026-08-11): the flow-reason panel has a CONSTANT height
  // in every state (empty / simple / with-evidence) until the user drags.
  // Content-driven height changes are impossible → an edge click never
  // changes the panel height → no flex reflow → the graph-canvas
  // ResizeObserver never fires on click → the L2 viewport stops
  // auto-refitting. After a drag the height is user-set — still constant
  // across clicks (height changes only when the user drags).
  const [reasonPanelHeight, setReasonPanelHeight] = useState(160);

  const leftResize = useResizable({
    direction: 'horizontal', value: leftPanelWidth, defaultValue: 260, min: 0, max: 9999,
    onResize: (v) => { setLeftPanelWidth(v); document.documentElement.style.setProperty('--left-width', v + 'px'); },
  });
  const l2Resize = useResizable({
    direction: 'horizontal', value: l2PanelWidth, defaultValue: 420, min: 0, max: 9999, invert: true,
    onResize: (v) => { setL2PanelWidth(v); document.documentElement.style.setProperty('--l2-width', v + 'px'); },
  });
  const sqlResize = useResizable({
    direction: 'vertical', value: sqlPanelHeight, defaultValue: 250, min: 0, max: 9999, invert: true,
    onResize: (v) => { setSqlPanelHeight(v); document.documentElement.style.setProperty('--sql-height', v + 'px'); },
  });
  // Issue 1: drag-to-resize handle on the reason panel's TOP edge (between
  // the SQL panel and the reason panel). Dragging squeezes the GRAPH (the
  // flex-1 item that gives up space) — the same behavior as the SQL-panel
  // handle. State not persisted (R23 clean start, like the SQL panel).
  const reasonResize = useResizable({
    direction: 'vertical', value: reasonPanelHeight, defaultValue: 160, min: 60, max: 9999, invert: true,
    onResize: setReasonPanelHeight,
  });

  const activeView = views.find(v => v.view_id === activeViewId)
    || views.flatMap(v => v.children || []).find(c => c.view_id === activeViewId);

  // ── Apply a level2 response: graph + result + not-in-flow banner state.
  // Every L2 entry path goes through here so the banner can never go stale.
  const applyL2Result = useCallback((result) => {
    setL2Graph(result.graph);
    setL2Result(result);
    // R25: every L2 entry path lands on a fresh graph — no stale edge
    // selection (and no reason-panel content) from a previous script.
    // R11-1: instead of leaving the reason panel stuck at "Click an edge
    // …", auto-select a sensible edge (seed-zone > chain > first).
    setSelectedEdge(pickAutoEdge(result));
    // Contract: search_matched === false → the search field is not in this
    // script (graph is the full unfiltered one); field absent from the
    // response means the search target matched (or none exists).
    const notInFlow = result.search_matched === false;
    setL2NotInFlow(notInFlow);
    setL2NotInFlowMessage(notInFlow ? (result.message || null) : null);
    // A3: parse_errors is a top-level array ({stmt_idx, detail}) — [] when none.
    setL2ParseErrors(result.parse_errors || []);
  }, []);

  // ── Upload & Analyze ──────────────────────────────────────────────
  const handleUpload = useCallback(async (file) => {
    setL1Graph(null); setL2Graph(null); setL2Result(null);
    setL2NotInFlow(false); setL2NotInFlowMessage(null);
    setL2ParseErrors([]);
    setLoading(true); setError(null);
    try {
      // Clean up old workspace before creating new one
      if (wsId) {
        try { await api.deleteWorkspace(wsId); } catch (e) { /* ignore */ }
        setWsId(null); setFileTree(null); setSelectedScripts([]);
        setTableIndex({}); setFieldIndex({}); setIndexed(false);
        setViews([]); setActiveViewId(null); setL1Graph(null);
        setL2Graph(null); setL2Result(null); setSqlText(''); setError(null);
        setActiveL1Table(null); setCurrentScriptName(''); setL2Filtered(true);
        setL2FullGraph(null); setResolutionStats(null); setOrphanFieldSamples(null);
        setSchemaCandidates(null); setSchemaEvidence(null);
        setSelectedEdge(null);
        setShowLog(true);
      }
      const result = await api.uploadWorkspace(file);
      setWsId(result.workspace_id);
      setFileTree(result.file_tree);

      // Auto-select all SQL files
      const scripts = collectSqlFiles(result.file_tree);
      setSelectedScripts(scripts);

      // Auto-index (fire-and-forget with polling)
      setProgress({ current: 0, total: scripts.length, phase: 'analyzing' });
      const idxResult = await api.indexWorkspace(result.workspace_id, scripts);
      setTableIndex(idxResult.table_index || {});
      setFieldIndex(idxResult.field_index || {});
      setFullTableIndex(idxResult.table_index || {});
      setFullFieldIndex(idxResult.field_index || {});
      setResolutionStats(idxResult.resolution_stats || null);
      setOrphanFieldSamples(idxResult.orphan_field_samples || null);
      setSchemaCandidates(idxResult.schema_candidates_summary || null);
      setSchemaEvidence(idxResult.schema_evidence || null);
      setIndexed(true);
      setStale(false);
      setProgress(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [wsId]);

  // ── Poll indexing progress ───────────────────────────────────────
  const progressTimerRef = useRef(null);
  useEffect(() => {
    if (!wsId || !progress) return;
    progressTimerRef.current = setInterval(async () => {
      try {
        const status = await api.getWorkspaceStatus(wsId);
        if (status.progress) {
          setProgress(status.progress);
          if (status.progress.phase === 'done') {
            clearInterval(progressTimerRef.current);
            setTimeout(() => setProgress(null), 1500);
          }
        }
      } catch (e) { /* ignore poll errors */ }
    }, 3000);
    return () => clearInterval(progressTimerRef.current);
  }, [wsId, progress?.phase]);

  // ── R23: clean start on load — never auto-restore a workspace/view.
  // The R3 mount-time restore was removed; this one-time purge drops its
  // localStorage key so saved state from older sessions can't resurface.
  useEffect(() => {
    try { localStorage.removeItem('df_last_search_view'); } catch { /* ignore */ }
  }, []);

  // ── Search ────────────────────────────────────────────────────────
  const handleSearch = useCallback(async (table, field) => {
    if (!wsId) return;
    setL1Graph(null); setL2Graph(null); setL2Result(null);
    setL2NotInFlow(false); setL2NotInFlowMessage(null);
    setL2ParseErrors([]);
    setLoading(true); setError(null);
    try {
      const result = await api.searchDataFlow(wsId, table, field);
      const newView = {
        view_id: result.view_id,
        type: 'search',
        table, field,
        script_ids: result.script_ids,
        l1_graph_cache: result.l1_graph,
        children: [],
        created_at: new Date().toISOString(),
        match_mode: result.match_mode,
        message: result.message,
      };
      setViews(prev => [...prev, newView]);
      setActiveViewId(result.view_id);
      parentViewIdRef.current = result.view_id;
      setL1Graph(result.l1_graph);
      setGraphLevel('L1');
      setL2Graph(null);
      setSqlText('');
      setActiveL1Table(null);
      setSelectedEdge(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [wsId]);

  // ── Open L2 (double-click on L1 script node) ──────────────────────
  const handleOpenL2 = useCallback(async (scriptId, scriptName) => {
    if (!wsId || !activeViewId) return;
    setL2Graph(null);
    setLoading(true);
    try {
      const viewIdForApi = parentViewIdRef.current || activeViewId;
      const result = await api.getLevel2Graph(wsId, viewIdForApi, scriptName);
      applyL2Result(result);
      setSqlText(result.sql_text || '');
      setCurrentScriptName(scriptName);
      setGraphLevel('L2');
      setL2Filtered(true);
      setL2FullGraph(null);

      // Add child entry to view tree AND persist to backend
      const childId = `${viewIdForApi}_${scriptId}`;
      const childEntry = {
        view_id: childId,
        type: 'script',
        parent_view_id: viewIdForApi,
        script_id: scriptId,
        script_name: scriptName,
        created_at: new Date().toISOString(),
      };
      setViews(prev => prev.map(v => {
        if (v.view_id === viewIdForApi) {
          if (v.children?.some(c => c.view_id === childId)) return v;
          return {
            ...v,
            children: [...(v.children || []), childEntry],
          };
        }
        return v;
      }));
      // Persist child to backend so it survives refresh and API lookups
      try {
        await api.addViewChild(wsId, viewIdForApi, childEntry);
      } catch (e) { /* non-critical: child exists in React state */ }
      setActiveViewId(childId);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [wsId, activeViewId]);

  // ── View Tree navigation ──────────────────────────────────────────
  const handleViewTreeClick = useCallback(async (viewId) => {
    setActiveViewId(viewId);
    setError(null);

    // Find the entry
    let entry = views.find(v => v.view_id === viewId);
    let isL2 = false;
    if (!entry) {
      for (const v of views) {
        const child = (v.children || []).find(c => c.view_id === viewId);
        if (child) { entry = child; isL2 = true; break; }
      }
    }

    if (!entry) return;

    if (isL2 && entry.type === 'script') {
      // Navigate to L2
      try {
        const parentView = views.find(v => v.view_id === entry.parent_view_id);
        const result = await api.getLevel2Graph(wsId, entry.parent_view_id, entry.script_name);
        applyL2Result(result);
        setSqlText(result.sql_text || '');
        setCurrentScriptName(entry.script_name);
        setGraphLevel('L2');
        setL2Filtered(true);
        setL2FullGraph(null);
        setShowLog(true);
        setActiveL1Table(null);
      } catch (e) {
        setError(e.message);
      }
    } else {
      // Navigate to L1
      setL1Graph(entry.l1_graph_cache || { nodes: [], edges: [] });
      setGraphLevel('L1');
      setL2Graph(null);
      setL2NotInFlow(false); setL2NotInFlowMessage(null);
      setL2ParseErrors([]);
      setSqlText('');
      setActiveL1Table(null);
      setSelectedEdge(null);
    }
  }, [views, wsId]);

  // ── Delete workspace ──────────────────────────────────────────────
  const handleDeleteWorkspace = useCallback(async () => {
    if (!wsId) return;
    try {
      await api.deleteWorkspace(wsId);
    } catch (e) { /* ignore */ }
    setWsId(null); setFileTree(null); setSelectedScripts([]);
    setTableIndex({}); setFieldIndex({}); setIndexed(false);
    setViews([]); setActiveViewId(null); setL1Graph(null);
    setL2Graph(null); setSqlText(''); setError(null);
    setResolutionStats(null); setOrphanFieldSamples(null);
    setSchemaCandidates(null); setSchemaEvidence(null);
    setSelectedEdge(null);
  }, [wsId]);

  // ── L1 Table lens click ─────────────────────────────────────────
  const handleTableClick = useCallback((tableName) => {
    setActiveL1Table(prev => prev === tableName ? null : tableName);
  }, []);

  const handleClearTableFilter = useCallback(() => {
    setActiveL1Table(null);
  }, []);

  // ── Toggle L2 relevance filter ─────────────────────────────────
  const handleToggleFilter = useCallback(async () => {
    if (!wsId || !activeViewId) return;
    // Derive the parent view ID: if activeViewId is a child, use its parent.
    // Child IDs have format "parentId_scriptId".
    let parentId = activeViewId;
    const parentView = views.find(v => v.view_id === activeViewId);
    if (!parentView) {
      // activeViewId is a child — find its parent entry
      for (const v of views) {
        const child = (v.children || []).find(c => c.view_id === activeViewId);
        if (child) { parentId = child.parent_view_id || v.view_id; break; }
      }
    }
    if (l2Filtered) {
      // Switching to "Show All": fetch unfiltered graph
      if (l2FullGraph) {
        // Cache the full unfiltered RESPONSE (not just the graph) so this
        // path routes through applyL2Result like the fetch path — edge
        // selection, not-in-flow banner and parse-error state can never
        // go stale from a previous view/script.
        applyL2Result(l2FullGraph);
        setL2Filtered(false);
      } else {
        try {
          const result = await api.getLevel2Graph(wsId, parentId, currentScriptName, false);
          setL2FullGraph(result);
          applyL2Result(result);
          setL2Filtered(false);
        } catch (e) { setError(e.message); }
      }
    } else {
      // Switching back to filtered
      try {
        const result = await api.getLevel2Graph(wsId, parentId, currentScriptName, true);
        applyL2Result(result);
        setL2Filtered(true);
      } catch (e) { setError(e.message); }
    }
  }, [wsId, activeViewId, currentScriptName, l2Filtered, l2FullGraph, views]);


  // ── Edge click → SQL highlight + reason panel (R25/§8.8) ───────────
  // The per-edge payload (highlight_line / flow_kind / reason) is the
  // single source of truth: the SQL panel lights exactly the anchor
  // line and the reason panel below it shows kind + anchor + reason.
  // The old response-level `highlights` and per-edge `sql_range` /
  // `sql_ranges` fields are gone from the API — nothing to pick from.
  const handleEdgeClick = useCallback((edgeData) => {
    setSelectedEdge(edgeData);
  }, []);

  const clearEdgeSelection = useCallback(() => {
    setSelectedEdge(null);
  }, []);

  // Single anchor line for the SQL panel — derived from the selection.
  const sqlHighlightLine = (selectedEdge && Number.isInteger(selectedEdge.highlight_line)
    && selectedEdge.highlight_line >= 1) ? selectedEdge.highlight_line : null;

  // R19.4/R19.6a: the Show All edge count reflects the structure toggle —
  // hidden SCHEMA edges are subtracted so the badge never claims edges
  // that aren't rendered (counts come from the SAME response graph that
  // is displayed — filtered vs full — so the arithmetic is exact).
  const currentL2Graph = l2Filtered ? l2Graph : (l2FullGraph ? l2FullGraph.graph : null);
  const structureEdgeCount = useMemo(() => countStructureEdges(currentL2Graph), [currentL2Graph]);
  const visibleEdgeCount = Math.max(0,
    (l2Result?.total_edges || 0) - (showStructureEdges ? 0 : structureEdgeCount));

  // ── Clear edge selection ────────────────────────────────────────────
  // ── Delete view ───────────────────────────────────────────────────
  const handleDeleteView = useCallback(async (viewId) => {
    if (!wsId) return;
    try { await api.deleteView(wsId, viewId); } catch (e) { /* ignore */ }
    // The ref must not keep pointing at a deleted view — handleOpenL2
    // prefers it over activeViewId, so a stale ref would address the API
    // with a dead view id (wrong parent chain / back navigation).
    if (parentViewIdRef.current === viewId) parentViewIdRef.current = null;
    setViews(prev => {
      let newViews = prev.filter(v => v.view_id !== viewId);
      newViews = newViews.map(v => ({
        ...v,
        children: (v.children || []).filter(c => c.view_id !== viewId),
      }));
      return newViews;
    });
    if (activeViewId === viewId) {
      setActiveViewId(null); setL1Graph(null); setL2Graph(null);
      setL2NotInFlow(false); setL2NotInFlowMessage(null);
      setL2ParseErrors([]);
      setSqlText('');
      setSelectedEdge(null);
    }
  }, [wsId, activeViewId]);

  // Top panel always shows L1 as navigation graph (per requirement §3)
  const graphData = l1Graph;

  // Breadcrumb navigation
  const breadcrumb = [];
  if (activeView) {
    // Walk up to parent view for table/field if this is a child entry
    const parentView = activeView.parent_view_id
      ? views.find(v => v.view_id === activeView.parent_view_id)
      : null;
    const displayView = parentView || activeView;
    breadcrumb.push({
      label: `${displayView.table || ''}.${displayView.field || ''}`,
      icon: '🔍',
      onClick: activeView.view_id ? () => handleViewTreeClick(activeView.view_id) : undefined,
      link: graphLevel === 'L2',
      title: 'Back to L1 view',
    });
  }
  if (graphLevel === 'L2' && currentScriptName) {
    breadcrumb.push({
      label: currentScriptName.split('/').pop(),
      icon: '📄',
      link: false,
      title: 'Current script',
    });
  }

  // Keyboard shortcuts (R12.5)
  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") {
        if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
        setGraphLevel("L1");
        setSelectedEdge(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <div className="dataflow-layout">
      {/* Error banner */}
      {error && (
        <div className="error-banner" onClick={() => setError(null)}>
          {error} <span style={{ float: 'right', cursor: 'pointer' }}>x</span>
        </div>
      )}

      {/* Wrapper for panels + graph (flex row) */}
      <div className="dataflow-main">
      {/* Left panel */}
      <div className="panel-left">
        <WorkspacePanel
          wsId={wsId} loading={loading} progress={progress}
          onUpload={handleUpload} onDelete={handleDeleteWorkspace}
          onError={setError}
        />
        {fileTree && (
          <FolderTree
            tree={fileTree} selected={selectedScripts}
            onSelectionChange={setSelectedScripts}
            indexed={indexed} stale={stale}
            onReindex={async () => {
              setL1Graph(null); setL2Graph(null); setL2Result(null);
              setL2NotInFlow(false); setL2NotInFlowMessage(null);
              setL2ParseErrors([]);
              setLoading(true);
              try {
                const idxResult = await api.indexWorkspace(wsId, selectedScripts);
                setResolutionStats(idxResult.resolution_stats || null);
                setOrphanFieldSamples(idxResult.orphan_field_samples || null);
                setSchemaCandidates(idxResult.schema_candidates_summary || null);
                setSchemaEvidence(idxResult.schema_evidence || null);
                setStale(false); setIndexed(true);
              } catch (e) { setError(e.message); }
              setLoading(false);
            }}
          />
        )}
        {indexed && !stale && (
          <FilterPanel
            wsId={wsId}
            tableIndex={tableIndex} fieldIndex={fieldIndex}
            onSearch={handleSearch} loading={loading}
            onError={setError}
            onFilterApplied={async (filterResult) => {
              if (filterResult && filterResult.filtered) {
                const ft = new Set(filterResult.filtered_tables || []);
                const ff = new Set(filterResult.filtered_fields || []);
                const filteredTI = {}; const filteredFI = {};
                for (const [k, v] of Object.entries(fullTableIndex)) {
                  if (ft.has(k)) filteredTI[k] = v;
                }
                for (const [k, v] of Object.entries(fullFieldIndex)) {
                  if (ff.has(k)) filteredFI[k] = v;
                }
                setTableIndex(filteredTI);
                setFieldIndex(filteredFI);
              } else {
                setTableIndex(fullTableIndex);
                setFieldIndex(fullFieldIndex);
              }
            }}
          />
        )}
        {/* R20: orphan resolution coverage report (index-time) */}
        {indexed && (
          <ResolutionReport
            stats={resolutionStats}
            orphanFieldSamples={orphanFieldSamples}
            schemaCandidates={schemaCandidates}
            schemaEvidence={schemaEvidence}
          />
        )}
        <ViewBar
          views={views} activeViewId={activeViewId}
          onSelect={handleViewTreeClick}
          onRemove={handleDeleteView}
          onRemoveChild={async (parentId, childId) => {
            try {
              await api.deleteViewChild(wsId, parentId, childId);
              setViews(prev => {
                const updated = [...prev];
                const parent = updated.find(v => v.view_id === parentId);
                if (parent && parent.children) {
                  parent.children = parent.children.filter(c => c.view_id !== childId);
                }
                return updated;
              });
              if (activeViewId === childId) setActiveViewId(null);
            } catch (e) { setError(e.message); }
          }}
        />
      </div>

      {/* Resize handle: left | center */}
      <div {...leftResize.handleProps} />

      {/* Center: graph */}
      <div className="panel-center">
        {/* R3: visible notice for empty no-match search results (F1).
            Renders whenever the active view is a no_matches search — the
            backend message is shown verbatim. */}
        {activeView?.match_mode === 'no_matches' && (
          <div className="no-match-banner">
            ⚠️ No matches: {activeView.message || 'no tables in scope'} — empty result view
          </div>
        )}
        {graphData && (
          <DataFlowGraph
            graphData={graphData}
            level="L1"
            layoutMode={layoutMode}
            breadcrumb={breadcrumb}
            onOpenL2={handleOpenL2}
            onToggleLayout={(mode) => { if (mode) { setLayoutMode(mode); } else { setLayoutMode(m => m === 'snake' ? 'pipeline' : 'snake'); }}}
            onToggleFilter={handleToggleFilter}
            l2Filtered={l2Filtered}
            l2TotalNodes={l2Result?.total_nodes || 0}
            l2FilteredNodes={l2Result?.filtered_nodes || 0}
            onTableClick={handleTableClick}
            activeTable={activeL1Table}
            onClearTableFilter={handleClearTableFilter}
            onEdgeClick={handleEdgeClick}
            onCanvasTap={clearEdgeSelection}
            selectedEdgeId={selectedEdge?.id}
            refitKey={graphLevel}
          />
        )}
        {loading && !graphData && (
          <div className="loading-skeleton">
            <div className="skeleton-header" />
            <div className="skeleton-graph">
              <div className="skeleton-node" style={{ top: '20%', left: '10%' }} />
              <div className="skeleton-node" style={{ top: '40%', left: '40%' }} />
              <div className="skeleton-node" style={{ top: '60%', left: '70%' }} />
              <div className="skeleton-node" style={{ top: '30%', left: '80%' }} />
              <div className="skeleton-edge" style={{ top: '35%', left: '20%', width: '25%' }} />
              <div className="skeleton-edge" style={{ top: '55%', left: '50%', width: '25%' }} />
            </div>
            <div className="skeleton-footer">Loading data flow...</div>
          </div>
        )}
        {!graphData && !wsId && !loading && (
          <div className="empty-state">Upload a folder to get started</div>
        )}
        {!graphData && wsId && indexed && !activeViewId && !loading && (
          <div className="empty-state">Search for a table.field to see data flow</div>
        )}
      </div>

      {/* Resize handle: L1 | L2 (vertical divider) */}
      {graphLevel === "L2" && <div {...l2Resize.handleProps} />}

      {/* L2 panel on the RIGHT of L1 (side-by-side) */}
      {graphLevel === 'L2' && (
        <div className="panel-inline-l2" style={{ width: l2PanelWidth, height: '100%' }}>
          <div className="inline-l2-header">
            <h3>📄 {currentScriptName?.split('/').pop() || 'Script'} — Level 2 Detail</h3>
            <div className="inline-l2-actions">
              {l2Result && (
                <button className="btn btn-outline btn-sm" onClick={handleToggleFilter}>
                  {l2Filtered ? `Show All (${l2Result.total_nodes || 0} nodes, ${visibleEdgeCount} edges)` : 'Show Relevant Only'}
                </button>
              )}
            </div>
          </div>
          <div className="inline-l2-graph">
            {/* A3: statement-level parse errors from the level2 response —
                one line per statement, backend detail shown verbatim. Uses the
                no-match-banner style; shifts down when the not-in-flow banner
                is also present so the two never overlap. */}
            {l2ParseErrors.length > 0 && (
              <div className="no-match-banner" style={l2NotInFlow ? { top: '44px' } : undefined}>
                {l2ParseErrors.map(e => (
                  <div key={e.stmt_idx}>
                    ⚠️ SQL parse error in statement {e.stmt_idx} — {e.detail || 'check the script syntax'}
                  </div>
                ))}
              </div>
            )}
            {/* L2 not-in-flow: search field not referenced in this script —
                backend message shown verbatim above the full-script graph */}
            {l2NotInFlow && (
              <div className="no-match-banner">
                ⚠️ {l2NotInFlowMessage || 'Field not in this script — showing the full script graph'}
              </div>
            )}
            <DataFlowGraph
              graphData={l2Filtered ? l2Graph : l2FullGraph.graph}
              level="L2"
              layoutMode={layoutMode}
              breadcrumb={[]}
              onEdgeClick={handleEdgeClick}
              onCanvasTap={clearEdgeSelection}
              selectedEdgeId={selectedEdge?.id}
              showStructureEdges={showStructureEdges}
              onToggleStructureEdges={() => setShowStructureEdges(v => !v)}
            />
          </div>
          {/* Resize handle: L2 graph | SQL panel */}
          <div {...sqlResize.handleProps} />
          {sqlText && (
            <>
              <div className="inline-l2-sql" style={{ height: sqlPanelHeight }}>
                <SqlPanel
                  sqlText={sqlText}
                  sqlHighlightLine={sqlHighlightLine}
                  scriptName={currentScriptName}
                  wsId={wsId}
                  table={activeView?.table || ""}
                  field={activeView?.field || ""}
                />
              </div>
              {/* R25/§8.8: flow reason panel BELOW the SQL panel — kind +
                  anchor line + the reason string with the clicked edge's
                  ‖…‖-wrapped segment emphasized; empty state when no edge
                  is selected. R26 (2026-08-11): the R11-3 "Code evidence"
                  block is gone — the script panel already shows the full
                  SQL with the anchor highlighted on edge click, so the
                  panel renders kind + anchor + reason only. R10-#18: only
                  rendered when there is a script (sqlText) to jump to.
                  Issue 1 (fix 2026-08-11): the panel's height is
                  CONSTANT in every state (reasonPanelHeight, like
                  sqlPanelHeight); it grows ONLY by dragging the handle
                  below. */}
              {/* Issue 1: drag-to-resize handle on the reason panel's TOP
                  edge (between SQL panel and reason panel). */}
              <div {...reasonResize.handleProps} />
              <EdgeReasonPanel
                edge={selectedEdge}
                height={reasonPanelHeight}
              />
            </>
          )}
        </div>
      )}

      </div>{/* end .dataflow-main */}
      {/* Log panel resize handle */}
      {/* Log panel — bottom bar, collapsible, resizable */}
      {wsId && showLog && <LogPanel wsId={wsId} visible={true} onClose={() => setShowLog(false)} />}
    </div>
  );
}

function collectSqlFiles(tree) {
  const paths = [];
  if (tree.type === 'file' && tree.is_sql) paths.push(tree.path);
  if (tree.children) tree.children.forEach(c => paths.push(...collectSqlFiles(c)));
  return paths;
}
