
import WorkspacePanel from './components/WorkspacePanel';
import MyWorkspaces from './components/MyWorkspaces';
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
import { resolveFlowOnly } from './utils/flowVisibility';
import { resumeLayoutKey } from './utils/layoutPersistence';
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useResizable } from './utils/useResizable';
import './styles/resizable.css';

export default function DataFlowApp({
  openWorkspaceId = null,
  onOpenWorkspace = null,
  onCloseWorkspace = null,
  username = null,
}) {
  const [wsId, setWsId] = useState(null);
  const [fileTree, setFileTree] = useState(null);
  const [selectedScripts, setSelectedScripts] = useState([]);
  const [tableIndex, setTableIndex] = useState({});
  const [fieldIndex, setFieldIndex] = useState({});
  const [fullTableIndex, setFullTableIndex] = useState({});
  const [fullFieldIndex, setFullFieldIndex] = useState({});
  const [indexed, setIndexed] = useState(false);
  const [views, setViews] = useState([]);
  const [activeViewId, setActiveViewId] = useState(null);
  const parentViewIdRef = useRef(null);
  const [graphLevel, setGraphLevel] = useState('L1');
  const [layoutMode, setLayoutMode] = useState('snake'); // 'snake' or 'pipeline'
  // R29: query direction — 'upstream' (writing flow, default) or 'downstream' (reading flow)
  const [direction, setDirection] = useState('upstream');
  const [l1Graph, setL1Graph] = useState(null);
  const [l2Graph, setL2Graph] = useState(null);
  const [sqlText, setSqlText] = useState('');
  const [currentScriptName, setCurrentScriptName] = useState('');
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [l2Result, setL2Result] = useState(null);
  // L2 view toggle (#331, four modes): 'flow' (closure — the default on a
  // matched search), 'full' (entire script graph), 'flow-merged' and
  // 'full-merged' (line-merged views — a distinct node+edge set, not a
  // client-side filter). null = disabled (no search seed or the search did
  // not match — always show the full graph).
  const [l2ViewMode, setL2ViewMode] = useState(null);
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

  // ── R31: layout persistence + concurrent-edit notice (A-M4/A-M5) ──
  // state_version drives the CAS save; resumeLayouts holds the shared
  // `{"l1": {node:[x,y]}, "l2:{script}": {...}}` map re-applied on render.
  const [stateVersion, setStateVersion] = useState(0);
  const [resumeLayouts, setResumeLayouts] = useState({});
  const [toast, setToast] = useState(null); // "state changed by X — refreshed"
  const wsIdRef = useRef(null);
  wsIdRef.current = wsId; // latest wsId for the unmount cleanup
  const stateVersionRef = useRef(0);
  // Coalesced pending saves keyed by (level, script) — L1 and L2 drags are
  // independent: an L2 drag arriving while an L1 save is already pending
  // must not clobber (and silently drop) the L1 save.
  const pendingLayoutRef = useRef(new Map()); // key -> {level, script, positions, version}
  const layoutTimerRef = useRef(null);
  const openedRef = useRef(null);          // guards the open-existing effect

  const setVersion = useCallback((v) => {
    stateVersionRef.current = v;
    setStateVersion(v);
  }, []);

  // Save the coalesced positions at most once per second (design §4 Q4 /
  // §10.18): drags accumulate into pendingLayoutRef, one PUT per debounce
  // window. On a 409 the server's fresh state is loaded and the pending edit
  // is re-applied on top of it (A-M4) with a "refreshed" notice.
  const flushLayoutSave = useCallback(async () => {
    if (layoutTimerRef.current) {
      clearTimeout(layoutTimerRef.current);
      layoutTimerRef.current = null;
    }
    if (!wsIdRef.current) return;
    const pending = pendingLayoutRef.current;
    if (!pending.size) return;
    // Snapshot + clear BEFORE the awaits: a drag that lands mid-save
    // re-coalesces into a fresh entry (and arms its own timer), so it is
    // never lost — each (level, script) key saves independently.
    const entries = [...pending.values()];
    pending.clear();
    for (const { level, script, positions, version } of entries) {
      try {
        const res = await api.saveLayout(wsIdRef.current, level, script, positions, version);
        if (res.status === 409) {
          const body = await res.json().catch(() => null);
          const fresh = body?.detail?.fresh;
          if (fresh && fresh.state_version != null) {
            setVersion(fresh.state_version);
            if (fresh.layouts) setResumeLayouts(fresh.layouts);
            // E-M9 (#284): overlay the just-dragged positions on the fresh
            // state too — they are being re-applied on top of it (A-M4), so a
            // re-open must reflect them, not the open-time snapshot.
            setResumeLayouts(prev => ({ ...prev, [resumeLayoutKey(level, script)]: positions }));
            setToast('State changed by another user - refreshed');
            // Re-apply the pending edit on top of the fresh state (A-M4).
            pendingLayoutRef.current.set(
              resumeLayoutKey(level, script),
              { level, script, positions, version: fresh.state_version },
            );
            if (!layoutTimerRef.current) {
              layoutTimerRef.current = setTimeout(() => {
                layoutTimerRef.current = null;
                flushLayoutSave();
              }, 1000);
            }
          }
        } else if (res.ok) {
          const body = await res.json().catch(() => null);
          if (body && body.state_version != null) setVersion(body.state_version);
          // E-M9 (#284): the server CONFIRMED these positions — fold them into
          // resumeLayouts so a later re-open/re-search re-applies the LATEST
          // drag, never the open-time snapshot (which would undo the drag).
          setResumeLayouts(prev => ({ ...prev, [resumeLayoutKey(level, script)]: positions }));
        }
        // other non-OK: silent failure (design: silent-fail handling)
      } catch { /* silent */ }
    }
  }, [setVersion]);

  const scheduleLayoutSave = useCallback((level, script, positions) => {
    if (!wsIdRef.current) return;
    // Key by (level, script): repeated drags of the SAME key coalesce into
    // the latest positions, while a DIFFERENT key (e.g. an L1 drag while an
    // L2 save is pending) gets its own slot — never clobbered by the other.
    pendingLayoutRef.current.set(
      resumeLayoutKey(level, script),
      { level, script, positions, version: stateVersionRef.current },
    );
    if (layoutTimerRef.current) return; // a save is already pending — coalesce
    layoutTimerRef.current = setTimeout(() => {
      layoutTimerRef.current = null;
      flushLayoutSave();
    }, 1000);
  }, [flushLayoutSave]);

  // Drag-end positions → debounced autosave for the CURRENT level+script.
  // #309: the level is passed EXPLICITLY per graph. The shared callback must
  // not derive it from the GLOBAL graphLevel — while an L2 is open (graphLevel
  // === 'L2') the L1 graph stays mounted + draggable side-by-side, so an L1
  // drag would otherwise be written under the L2 key and corrupt the layout.
  const handlePositionsChange = useCallback((level, positions) => {
    scheduleLayoutSave(
      level,
      level === 'l2' ? currentScriptName : null,
      positions,
    );
  }, [currentScriptName, scheduleLayoutSave]);

  // Final save on close: when the keyed DataFlowApp unmounts (close
  // workspace / switch workspace / logout), flush the coalesced layout save
  // and end the visit (design §4 Q4: "final write on close").
  useEffect(() => {
    return () => {
      if (!wsIdRef.current) return;
      flushLayoutSave();
      api.closeWorkspace(wsIdRef.current).catch(() => {});
    };
  }, [flushLayoutSave]);

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
    // L2 view toggle: default to 'flow' (the closure) whenever the response
    // carries the field-flow closure (matched search); null (disabled) when
    // there is no search seed or the search did not match.
    setL2ViewMode(resolveFlowOnly(result) === true ? 'flow' : null);
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

  // ── R31: full reset of debugger state (no workspace lifecycle calls —
  //     the keyed DataFlowApp remount already ends the previous visit) ──
  const resetWorkspaceState = useCallback(() => {
    setWsId(null); setFileTree(null); setSelectedScripts([]);
    setTableIndex({}); setFieldIndex({}); setFullTableIndex({}); setFullFieldIndex({});
    setIndexed(false); setViews([]); setActiveViewId(null); setL1Graph(null);
    setL2Graph(null); setL2Result(null); setL2ViewMode(null); setSqlText(''); setCurrentScriptName('');
    setError(null); setActiveL1Table(null); setSelectedEdge(null);
    setResolutionStats(null); setOrphanFieldSamples(null);
    setSchemaCandidates(null); setSchemaEvidence(null);
    setL2NotInFlow(false); setL2NotInFlowMessage(null); setL2ParseErrors([]);
    setProgress(null); setVersion(0); setResumeLayouts({});
    setShowLog(true);
  }, [setVersion]);

  // ── Upload (create) & Analyze ─────────────────────────────────────
  const handleUpload = useCallback(async (file) => {
    resetWorkspaceState();
    setLoading(true);
    try {
      // R31/A-M6: upload CREATES a new workspace (server UUID4 ws_id,
      // stamped creator, added to "my workspaces"). The previous workspace
      // is NOT deleted — the user manages their list on the dashboard
      // (remove-from-my-history is role-dependent, A-M2).
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
      setProgress(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [resetWorkspaceState]);

  // ── R31: open an existing workspace (dashboard Open / shared ?ws= link) ──
  // resume → scan → index. state_version + saved layouts come from resume so
  // the CAS save and saved-position re-application start from the shared state.
  const handleOpenExisting = useCallback(async (targetWsId) => {
    resetWorkspaceState();
    setLoading(true);
    try {
      const resume = await api.resumeWorkspace(targetWsId);
      setVersion(resume.state_version || 0);
      setResumeLayouts(resume.layouts || {});
      setWsId(targetWsId);
      const tree = await api.scanWorkspace(targetWsId);
      setFileTree(tree);
      const scripts = collectSqlFiles(tree);
      setSelectedScripts(scripts);
      setProgress({ current: 0, total: scripts.length, phase: 'analyzing' });
      const idxResult = await api.indexWorkspace(targetWsId, scripts);
      setTableIndex(idxResult.table_index || {});
      setFieldIndex(idxResult.field_index || {});
      setFullTableIndex(idxResult.table_index || {});
      setFullFieldIndex(idxResult.field_index || {});
      setResolutionStats(idxResult.resolution_stats || null);
      setOrphanFieldSamples(idxResult.orphan_field_samples || null);
      setSchemaCandidates(idxResult.schema_candidates_summary || null);
      setSchemaEvidence(idxResult.schema_evidence || null);
      setIndexed(true);
      setProgress(null);
      // #292: populate the persisted view tree (search views + their L2
      // children) from views.json so the left-panel ViewBar shows them.
      // R23 clean start: NO auto-activation — the user clicks a view to load
      // it. A view-list failure is non-critical (the tree just starts empty).
      try {
        const viewsRes = await api.listViews(targetWsId);
        setViews(Array.isArray(viewsRes?.views) ? viewsRes.views : []);
      } catch (e) { /* non-critical — views populate on the next search */ }
    } catch (e) {
      // Open failed (e.g. deleted/unknown id) — surface it and stay on the
      // empty debugger; the dashboard is one "Close" away.
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [resetWorkspaceState, setVersion]);

  // ── R31: open-existing entry — runs once when the workspace id arrives
  //     (dashboard Open or a shared ?ws= link). Guarded by openedRef so it
  //     never re-runs on unrelated re-renders.
  useEffect(() => {
    if (openWorkspaceId && openedRef.current !== openWorkspaceId) {
      openedRef.current = openWorkspaceId;
      handleOpenExisting(openWorkspaceId);
    }
  }, [openWorkspaceId, handleOpenExisting]);

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
  const handleSearch = useCallback(async (table, field, direction) => {
    if (!wsId) return;
    setL1Graph(null); setL2Graph(null); setL2Result(null); setL2ViewMode(null);
    setL2NotInFlow(false); setL2NotInFlowMessage(null);
    setL2ParseErrors([]);
    setLoading(true); setError(null);
    try {
      const result = await api.searchDataFlow(wsId, table, field, direction);
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
        // R29: the view tree keeps its direction so L2 follows it automatically
        direction,
      };
      setViews(prev => [...prev, newView]);
      setActiveViewId(result.view_id);
      parentViewIdRef.current = result.view_id;
      setL1Graph(result.l1_graph);
      setDirection(direction);
      setGraphLevel('L1');
      setL2Graph(null); setL2Result(null); setL2ViewMode(null);
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
    setL2Graph(null); setL2Result(null); setL2ViewMode(null);
    setLoading(true);
    try {
      const viewIdForApi = parentViewIdRef.current || activeViewId;
      // R29: L2 is the zoom-in of L1 — fetch in the parent view's direction
      const searchView = views.find(v => v.view_id === viewIdForApi);
      const result = await api.getLevel2Graph(wsId, viewIdForApi, scriptName, true, searchView?.direction || direction);
      applyL2Result(result);
      setSqlText(result.sql_text || '');
      setCurrentScriptName(scriptName);
      setGraphLevel('L2');

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
  }, [wsId, activeViewId, views, direction]);

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
      // Navigate to L2 — the L2 fetch is driven by entry.parent_view_id,
      // so a stale parentViewIdRef (left pointing at the last-searched
      // view) must not survive into a later L1 double-click (CR6).
      parentViewIdRef.current = null;
      setL2Graph(null); setL2Result(null); setL2ViewMode(null);
      try {
        const parentView = views.find(v => v.view_id === entry.parent_view_id);
        const result = await api.getLevel2Graph(wsId, entry.parent_view_id, entry.script_name, true, parentView?.direction || direction);
        applyL2Result(result);
        setSqlText(result.sql_text || '');
        setCurrentScriptName(entry.script_name);
        setGraphLevel('L2');
        setShowLog(true);
        setActiveL1Table(null);
      } catch (e) {
        setError(e.message);
      }
    } else {
      // Navigate to L1 — this view becomes the context for a subsequent
      // L2 open (double-click): keep parentViewIdRef in sync so handleOpenL2
      // resolves the right parent view + direction (CR6).
      parentViewIdRef.current = viewId;
      setL1Graph(entry.l1_graph_cache || { nodes: [], edges: [] });
      setGraphLevel('L1');
      setL2Graph(null); setL2Result(null); setL2ViewMode(null);
      setL2NotInFlow(false); setL2NotInFlowMessage(null);
      setL2ParseErrors([]);
      setSqlText('');
      setActiveL1Table(null);
      setSelectedEdge(null);
    }
  }, [views, wsId, direction]);

  // ── Remove from my history (R31 A-M1/A-M2) ────────────────────────
  // ONE role-dependent action — the backend decides: creator → physical
  // delete (server-global audit log written before removal), participant →
  // link removal only. The role-aware warning lives in the MyWorkspaces
  // panel; this in-app control shows a generic warning and returns to the
  // dashboard (the workspace is out of this user's list either way).
  const handleDeleteWorkspace = useCallback(async () => {
    if (!wsId) return;
    if (!window.confirm(
      'Remove this workspace from your history? If you created it, this DELETES the workspace and its files for everyone.'
    )) return;
    try {
      await api.removeFromMyHistory(wsId);
    } catch (e) {
      setError(e.message);
      return;
    }
    resetWorkspaceState();
    onCloseWorkspace?.();
  }, [wsId, resetWorkspaceState, onCloseWorkspace]);

  // ── T8 (#295): embedded "My workspaces" section (left panel) ──────
  // Upload creates a NEW workspace server-side, then opens it — the open
  // effect (handleOpenExisting) runs resume→scan→index ONCE on remount. We
  // deliberately do NOT call handleUpload's inline index path here (it would
  // double-index after the keyed remount).
  const handleSectionUpload = useCallback(async (file) => {
    const result = await api.uploadWorkspace(file);
    onOpenWorkspace?.(result.workspace_id);
    return result;
  }, [onOpenWorkspace]);

  // Remove-from-history (role-dependent, the backend decides: creator →
  // physical delete, participant → link removal). If it was the OPEN
  // workspace, drop back to the empty debugger.
  const handleSectionRemove = useCallback(async (w) => {
    try {
      await api.removeFromMyHistory(w.ws_id);
      if (w.ws_id === wsId) {
        resetWorkspaceState();
        onCloseWorkspace?.();
      }
    } catch (e) {
      setError(e.message);
      throw e; // let the embedded list surface the error line
    }
  }, [wsId, resetWorkspaceState, onCloseWorkspace]);

  // ── L1 Table lens click ─────────────────────────────────────────
  const handleTableClick = useCallback((tableName) => {
    setActiveL1Table(prev => prev === tableName ? null : tableName);
  }, []);

  const handleClearTableFilter = useCallback(() => {
    setActiveL1Table(null);
  }, []);

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

  // ── Clear edge selection ────────────────────────────────────────────
  // ── Delete view ───────────────────────────────────────────────────
  // E-M7 (#282): deleting the ACTIVE L2 child view (or its parent) must drop
  // the graph back to L1 — no stale L2 graph/header/SQL/toggle with no live
  // view. `clearL1` also clears the L1 nav (used when the deleted view WAS
  // the active L1 view); when only an L2 child is gone, the L1 nav stays.
  const dropToL1 = useCallback(({ clearL1 = false } = {}) => {
    if (clearL1) setL1Graph(null);
    setGraphLevel('L1');
    setL2Graph(null); setL2Result(null); setL2ViewMode(null);
    setL2NotInFlow(false); setL2NotInFlowMessage(null);
    setL2ParseErrors([]);
    setSqlText(''); setCurrentScriptName('');
    setSelectedEdge(null);
    setActiveViewId(null);
  }, []);

  const handleDeleteView = useCallback(async (viewId) => {
    if (!wsId) return;
    try { await api.deleteView(wsId, viewId); } catch (e) { /* ignore */ }
    // The ref must not keep pointing at a deleted view — handleOpenL2
    // prefers it over activeViewId, so a stale ref would address the API
    // with a dead view id (wrong parent chain / back navigation).
    if (parentViewIdRef.current === viewId) parentViewIdRef.current = null;
    // E-M7: capture what the ACTIVE view was BEFORE the setViews below —
    //   activeViewId === viewId            → the active view was deleted;
    //   activeViewId is a child of viewId  → the active L2's PARENT was
    //   deleted. Either way the active view no longer exists → drop to L1.
    const activeWasDeleted =
      activeViewId === viewId
      || (activeViewId && views.some(v =>
        v.view_id === viewId && (v.children || []).some(c => c.view_id === activeViewId)
      ));
    const activeViewIsAChild = activeViewId === viewId && views.some(v =>
      (v.children || []).some(c => c.view_id === viewId)
    );
    setViews(prev => {
      let newViews = prev.filter(v => v.view_id !== viewId);
      newViews = newViews.map(v => ({
        ...v,
        children: (v.children || []).filter(c => c.view_id !== viewId),
      }));
      return newViews;
    });
    if (activeWasDeleted) {
      // A deleted L2 child (or its deleted parent) → drop back to L1 and
      // keep the L1 nav; a deleted active L1 view → clear the L1 nav too.
      dropToL1({ clearL1: !activeViewIsAChild });
    }
  }, [wsId, activeViewId, views, dropToL1]);

  // Top panel always shows L1 as navigation graph (per requirement §3)
  const graphData = l1Graph;

  // ── #331: 4-way L2 view toggle ─────────────────────────────────────
  // 'flow' / 'full' share the FULL payload and toggle visibility client-side
  // (flowNodeIds/flowEdgeIds). 'flow-merged' / 'full-merged' are a DISTINCT
  // node+edge set (the line-merged pass), so they render from their own
  // payload — passing a different graphData rebuilds the cytoscape instance
  // and runs layout (never a client-side filter over the full graph).
  const isL2Merged = l2ViewMode === 'flow-merged' || l2ViewMode === 'full-merged';
  const l2GraphData = useMemo(() => {
    const full = (l2Result && l2Result.full_graph) || l2Graph;
    if (!l2Result) return l2Graph;
    const merged = l2ViewMode === 'flow-merged'
      ? l2Result.flow_only_merged
      : l2ViewMode === 'full-merged'
        ? l2Result.full_merged
        : null;
    // Defensive: only render a merged view when it actually carries nodes
    // (an empty/absent merged payload falls back to the full graph).
    if (merged && Array.isArray(merged.nodes) && merged.nodes.length > 0) return merged;
    return full;
  }, [l2Result, l2ViewMode, l2Graph]);

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

      {/* R31 concurrent-edit notice (A-M4) — shown on a layout 409: the
          server state changed by another user, our pending edit was re-applied
          on top of the fresh state. */}
      {toast && (
        <div className="concurrent-toast" onClick={() => setToast(null)} title="Dismiss">
          {toast} <span style={{ float: 'right', cursor: 'pointer', marginLeft: 8 }}>x</span>
        </div>
      )}

      {/* Wrapper for panels + graph (flex row) */}
      <div className="dataflow-main">
      {/* Left panel */}
      <div className="panel-left">
        {/* T8 (#295): "My workspaces" ALWAYS lives at the top of the
            debugger's left panel — list (role badges + quota + remove),
            📁 Select Folder, + Upload a folder (zip), and the open-by-id
            box. Each keyed remount refetches the list. Uploads create then
            open (handleOpenExisting runs resume→scan→index ONCE); the
            WorkspacePanel below no longer duplicates the upload pickers. */}
        <MyWorkspaces
          open
          onOpen={onOpenWorkspace}
          onUpload={handleSectionUpload}
          onRemove={handleSectionRemove}
        />
        <WorkspacePanel
          wsId={wsId} loading={loading} progress={progress}
          onUpload={handleUpload} onDelete={handleDeleteWorkspace}
          onError={setError}
          showUploads={false}
        />
        {fileTree && (
          <FolderTree
            tree={fileTree} selected={selectedScripts}
            onSelectionChange={setSelectedScripts}
            indexed={indexed}
          />
        )}
        {indexed && (
          <FilterPanel
            wsId={wsId}
            username={username}
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
              // E-M7 (#282): deleting the ACTIVE L2 child drops back to L1 —
              // no stale L2 graph/header/SQL/toggle with no live view.
              if (activeViewId === childId) dropToL1();
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
            backend message is shown verbatim. R29: no_flow (empty
            directional flow) renders the same way — the backend message
            ("No writing flow for T.F" / "No reading flow for T.F") is
            shown verbatim, never as an error. */}
        {activeView && (activeView.match_mode === 'no_matches' || activeView.match_mode === 'no_flow') && (
          <div className="no-match-banner">
            ⚠️ {activeView.match_mode === 'no_flow'
              ? `${activeView.message || 'no flow in this direction'} - empty result view`
              : `No matches: ${activeView.message || 'no tables in scope'} - empty result view`}
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
            onTableClick={handleTableClick}
            activeTable={activeL1Table}
            onClearTableFilter={handleClearTableFilter}
            onEdgeClick={handleEdgeClick}
            onCanvasTap={clearEdgeSelection}
            selectedEdgeId={selectedEdge?.id}
            refitKey={graphLevel}
            savedPositions={resumeLayouts['l1']}
            onPositionsChange={(positions) => handlePositionsChange('l1', positions)}
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
                    ⚠️ SQL parse error in statement {e.stmt_idx} - {e.detail || 'check the script syntax'}
                  </div>
                ))}
              </div>
            )}
            {/* L2 not-in-flow: search field not referenced in this script —
                backend message shown verbatim above the full-script graph */}
            {l2NotInFlow && (
              <div className="no-match-banner">
                ⚠️ {l2NotInFlowMessage || 'Field not in this script - showing the full script graph'}
              </div>
            )}
            <DataFlowGraph
              graphData={l2GraphData}
              level="L2"
              layoutMode={layoutMode}
              breadcrumb={[]}
              onEdgeClick={handleEdgeClick}
              onCanvasTap={clearEdgeSelection}
              selectedEdgeId={selectedEdge?.id}
              viewMode={l2ViewMode}
              onViewModeChange={setL2ViewMode}
              flowNodeIds={isL2Merged ? undefined : l2Result?.flow_node_ids}
              flowEdgeIds={isL2Merged ? undefined : l2Result?.flow_edge_ids}
              savedPositions={resumeLayouts[resumeLayoutKey('l2', currentScriptName)]}
              onPositionsChange={(positions) => handlePositionsChange('l2', positions)}
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
