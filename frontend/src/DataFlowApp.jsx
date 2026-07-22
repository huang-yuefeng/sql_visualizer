
import WorkspacePanel from './components/WorkspacePanel';
import FolderTree from './components/FolderTree';
import FilterPanel from './components/FilterPanel';
import ViewBar from './components/ViewBar';
import DataFlowGraph from './components/DataFlowGraph';
import SqlPanel from './components/SqlPanel';
import * as api from './api/client';
import { useState, useEffect, useCallback, useRef } from 'react';
import { useResizable } from './utils/useResizable';
import './styles/resizable.css';

export default function DataFlowApp() {
  const [wsId, setWsId] = useState(null);
  const [fileTree, setFileTree] = useState(null);
  const [selectedScripts, setSelectedScripts] = useState([]);
  const [tableIndex, setTableIndex] = useState({});
  const [fieldIndex, setFieldIndex] = useState({});
  const [indexed, setIndexed] = useState(false);
  const [stale, setStale] = useState(false);
  const [views, setViews] = useState([]);
  const [activeViewId, setActiveViewId] = useState(null);
  const parentViewIdRef = useRef(null);
  const [graphLevel, setGraphLevel] = useState('L1');
  const [layoutMode, setLayoutMode] = useState('snake'); // 'snake' or 'pipeline'
  const [l1Graph, setL1Graph] = useState(null);
  const [l2Graph, setL2Graph] = useState(null);
  const [sqlText, setSqlText] = useState('');
  const [currentScriptName, setCurrentScriptName] = useState('');
  const [l2Filtered, setL2Filtered] = useState(true);
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [l2FullGraph, setL2FullGraph] = useState(null);
  const [l2Result, setL2Result] = useState(null);
  const [highlights, setHighlights] = useState([]);
  const [sqlHighlightRange, setSqlHighlightRange] = useState(null);
  const [scriptInfo, setScriptInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const [activeL1Table, setActiveL1Table] = useState(null);

  // ── Resizable panel state ─────────────────────────────────────────
  const [leftPanelWidth, setLeftPanelWidth] = useState(260);
  const [l2PanelHeight, setL2PanelHeight] = useState(420);
  const [l2PanelWidth, setL2PanelWidth] = useState(420);
  const [sqlPanelHeight, setSqlPanelHeight] = useState(250);

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

  const activeView = views.find(v => v.view_id === activeViewId)
    || views.flatMap(v => v.children || []).find(c => c.view_id === activeViewId);

  // ── Upload & Analyze ──────────────────────────────────────────────
  const handleUpload = useCallback(async (file) => {
    setLoading(true); setError(null);
    try {
      // Clean up old workspace before creating new one
      if (wsId) {
        try { await api.deleteWorkspace(wsId); } catch (e) { /* ignore */ }
        setWsId(null); setFileTree(null); setSelectedScripts([]);
        setTableIndex({}); setFieldIndex({}); setIndexed(false);
        setViews([]); setActiveViewId(null); setL1Graph(null);
        setL2Graph(null); setL2Result(null); setSqlText(''); setError(null);
        setScriptInfo(null); setActiveL1Table(null); setCurrentScriptName(''); setL2Filtered(true);
        setL2FullGraph(null);
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

  // ── Search ────────────────────────────────────────────────────────
  const handleSearch = useCallback(async (table, field) => {
    if (!wsId) return;
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
      };
      setViews(prev => [...prev, newView]);
      setActiveViewId(result.view_id);
      parentViewIdRef.current = result.view_id;
      setL1Graph(result.l1_graph);
      setGraphLevel('L1');
      setL2Graph(null);
      setSqlText('');
      setScriptInfo(null); setActiveL1Table(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [wsId]);

  // ── Open L2 (double-click on L1 script node) ──────────────────────
  const handleOpenL2 = useCallback(async (scriptId, scriptName) => {
    if (!wsId || !activeViewId) return;
    setLoading(true);
    try {
      const viewIdForApi = parentViewIdRef.current || activeViewId;
      const result = await api.getLevel2Graph(wsId, viewIdForApi, scriptName);
      setL2Graph(result.graph);
      setL2Result(result);
      setSqlText(result.sql_text || '');
      setHighlights(result.highlights || []);
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
        setL2Graph(result.graph);
        setL2Result(result);
        setSqlText(result.sql_text || '');
        setHighlights(result.highlights || []);
        setCurrentScriptName(entry.script_name);
        setGraphLevel('L2');
        setL2Filtered(true);
        setL2FullGraph(null);
        setScriptInfo(null); setActiveL1Table(null);
      } catch (e) {
        setError(e.message);
      }
    } else {
      // Navigate to L1
      setL1Graph(entry.l1_graph_cache || { nodes: [], edges: [] });
      setGraphLevel('L1');
      setL2Graph(null);
      setSqlText('');
      setScriptInfo(null); setActiveL1Table(null);
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
        setL2Graph(l2FullGraph);
        setL2Filtered(false);
      } else {
        try {
          const result = await api.getLevel2Graph(wsId, parentId, currentScriptName, false);
          setL2FullGraph(result.graph);
          setL2Graph(result.graph);
          setL2Result(result);
          setL2Filtered(false);
        } catch (e) { setError(e.message); }
      }
    } else {
      // Switching back to filtered
      try {
        const result = await api.getLevel2Graph(wsId, parentId, currentScriptName, true);
        setL2Graph(result.graph);
        setL2Result(result);
        setL2Filtered(true);
      } catch (e) { setError(e.message); }
    }
  }, [wsId, activeViewId, currentScriptName, l2Filtered, l2FullGraph, views]);

  // ── Edge click → SQL highlighting ──────────────────────────────────
  const handleEdgeClick = useCallback((edgeData) => {
    setSelectedEdge(edgeData);
    if (edgeData.sql_range) {
      setSqlHighlightRange(edgeData.sql_range);
    }
  }, []);

  // ── Clear edge selection ────────────────────────────────────────────
  // ── Delete view ───────────────────────────────────────────────────
  const handleDeleteView = useCallback(async (viewId) => {
    if (!wsId) return;
    try { await api.deleteView(wsId, viewId); } catch (e) { /* ignore */ }
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
      setSqlText(''); setScriptInfo(null);
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
        setSqlHighlightRange(null);
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

      {/* Left panel */}
      <div className="panel-left">
        <WorkspacePanel
          wsId={wsId} loading={loading} progress={progress}
          onUpload={handleUpload} onDelete={handleDeleteWorkspace}
        />
        {fileTree && (
          <FolderTree
            tree={fileTree} selected={selectedScripts}
            onSelectionChange={setSelectedScripts}
            indexed={indexed} stale={stale}
            onReindex={async () => {
              setLoading(true);
              try {
                await api.indexWorkspace(wsId, selectedScripts);
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
            onFilterApplied={async () => {
              setLoading(true);
              try {
                const idxResult = await api.indexWorkspace(wsId, selectedScripts);
                setTableIndex(idxResult.table_index || {});
                setFieldIndex(idxResult.field_index || {});
              } catch (e) { setError(e.message); }
              setLoading(false);
            }}
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
        {graphData && (
          <DataFlowGraph
            graphData={graphData}
            level="L1"
            layoutMode={layoutMode}
            breadcrumb={breadcrumb}
            onOpenL2={handleOpenL2}
            onToggleLayout={(mode) => { if (mode) { setLayoutMode(mode); } else { setLayoutMode(m => {
    if (m === 'snake') return 'pipeline';
    if (m === 'pipeline') return 'spore';
    return 'snake'; // spore → snake
  }); }}}
            scriptInfo={scriptInfo}
            onScriptInfoChange={setScriptInfo}
            onToggleFilter={handleToggleFilter}
            l2Filtered={l2Filtered}
            l2TotalNodes={l2Result?.total_nodes || 0}
            l2FilteredNodes={l2Result?.filtered_nodes || 0}
            onTableClick={handleTableClick}
            activeTable={activeL1Table}
            onClearTableFilter={handleClearTableFilter}
            onEdgeClick={handleEdgeClick}
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
                  {l2Filtered ? `Show All (${l2Result.total_nodes || 0} nodes, ${l2Result.total_edges || 0} edges)` : 'Show Relevant Only'}
                </button>
              )}
            </div>
          </div>
          <div className="inline-l2-graph">
            <DataFlowGraph
              graphData={l2Filtered ? l2Graph : l2FullGraph}
              level="L2"
              layoutMode={layoutMode}
              breadcrumb={[]}
              onEdgeClick={(edgeData) => {
                setSelectedEdge(edgeData);
                if (edgeData?.sql_range) setSqlHighlightRange(edgeData.sql_range);
              }}
              selectedEdgeId={selectedEdge?.id}
            />
          </div>
          {/* Resize handle: L2 graph | SQL panel */}
          <div {...sqlResize.handleProps} />
          {sqlText && (
            <div className="inline-l2-sql" style={{ height: sqlPanelHeight }}>
              <SqlPanel
                sqlText={sqlText}
                highlights={highlights}
                scriptName={currentScriptName}
                wsId={wsId}
                table={activeView?.table || ""}
                field={activeView?.field || ""}
                l2Result={l2Result}
                selectedEdge={selectedEdge}
                sqlHighlightRange={sqlHighlightRange}
                onClearEdge={() => { setSelectedEdge(null); setSqlHighlightRange(null); }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function collectSqlFiles(tree) {
  const paths = [];
  if (tree.type === 'file' && tree.is_sql) paths.push(tree.path);
  if (tree.children) tree.children.forEach(c => paths.push(...collectSqlFiles(c)));
  return paths;
}
