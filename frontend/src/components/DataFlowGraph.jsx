import React, { useRef, useMemo } from 'react';
import useCytoscapeGraph from '../hooks/useCytoscapeGraph';
import DataFlowLegend from './DataFlowLegend';
import { FIT_PADDING } from '../config/layout';
import { countStructureEdges } from '../utils/structureEdges';
import { L2_EDGE_CLASSES } from '../utils/graphStyles';

/**
 * R30/#222 — click-edge flow cone (L2 only).
 *
 * Clicking a value-flow edge u → v highlights its flow cone:
 *   - before (green)  = the value-flow edges UPSTREAM of u — "where the
 *     data came from" (BFS backward from u over edges whose target is the
 *     current node).
 *   - after  (blue)   = the value-flow edges DOWNSTREAM of v — "where the
 *     data goes" (BFS forward from v over edges whose source is the node).
 *   - pivot  (red)    = the clicked edge itself.
 *   - everything else = dimmed (focus mode).
 *
 * The cone is VALUE-FLOW only: structure edges (SCHEMA, ALIAS, SUBSET) are
 * never part of the traversal and never part of the cone. ROW_FLOW (the
 * new 17th edge type, row-level flow) is flow-class — included; unknown
 * edge types are treated as flow defensively. The traversal runs on the
 * current graph data (BFS over edges, respecting edge direction). The cone
 * is a transient focus state — cleared on canvas click / next edge click;
 * the existing edge-click → onEdgeClick (SQL highlight) behavior is kept.
 */
const STRUCTURE_EDGE_TYPES = new Set(['SCHEMA', 'ALIAS', 'SUBSET']);

export function isValueFlowEdge(edgeData) {
  if (!edgeData || typeof edgeData !== 'object') return false;
  const t = edgeData.edge_type || edgeData.relationship;
  if (!t) return true; // unknown type — treat as flow (defensive)
  return !STRUCTURE_EDGE_TYPES.has(t);
}

export function computeFlowCone(graphData, clickedEdgeId) {
  const result = { pivot: clickedEdgeId, before: [], after: [] };
  if (!graphData || !Array.isArray(graphData.edges)) return result;

  // Index the graph: edge-by-id + forward/backward adjacency restricted
  // to value-flow edges (structure edges never carry the cone).
  const byId = new Map();
  const outgoing = new Map(); // nodeId -> [edgeId] (edge.source === nodeId)
  const incoming = new Map(); // nodeId -> [edgeId] (edge.target === nodeId)
  for (const e of graphData.edges) {
    const d = e && e.data;
    if (!d || typeof d.id === 'undefined') continue;
    byId.set(d.id, e);
    if (!isValueFlowEdge(d)) continue;
    if (typeof d.source !== 'undefined') {
      if (!outgoing.has(d.source)) outgoing.set(d.source, []);
      outgoing.get(d.source).push(d.id);
    }
    if (typeof d.target !== 'undefined') {
      if (!incoming.has(d.target)) incoming.set(d.target, []);
      incoming.get(d.target).push(d.id);
    }
  }

  const clicked = byId.get(clickedEdgeId);
  if (!clicked || !clicked.data || !isValueFlowEdge(clicked.data)) return result;
  const { source: u, target: v } = clicked.data;

  // Upstream — BFS backward from the pivot's source u.
  if (typeof u !== 'undefined') {
    const found = new Set();
    const visited = new Set([u]);
    const queue = [u];
    while (queue.length) {
      const node = queue.shift();
      for (const eid of incoming.get(node) || []) {
        found.add(eid);
        const e = byId.get(eid);
        const s = e && e.data && e.data.source;
        if (typeof s !== 'undefined' && !visited.has(s)) {
          visited.add(s);
          queue.push(s);
        }
      }
    }
    result.before = [...found];
  }

  // Downstream — BFS forward from the pivot's target v.
  if (typeof v !== 'undefined') {
    const found = new Set();
    const visited = new Set([v]);
    const queue = [v];
    while (queue.length) {
      const node = queue.shift();
      for (const eid of outgoing.get(node) || []) {
        found.add(eid);
        const e = byId.get(eid);
        const t = e && e.data && e.data.target;
        if (typeof t !== 'undefined' && !visited.has(t)) {
          visited.add(t);
          queue.push(t);
        }
      }
    }
    result.after = [...found];
  }

  return result;
}

/** Apply the flow-cone focus classes to a cytoscape instance (L2). */
export function applyFlowCone(cy, graphData, clickedEdgeId) {
  if (!cy || (typeof cy.destroyed === 'function' && cy.destroyed())) return;
  const cone = computeFlowCone(graphData, clickedEdgeId);
  const before = new Set(cone.before);
  const after = new Set(cone.after);
  const edges = cy.edges();
  if (!edges || typeof edges.removeClass !== 'function') return;
  edges.removeClass(`${L2_EDGE_CLASSES.coneBefore} ${L2_EDGE_CLASSES.coneAfter} ${L2_EDGE_CLASSES.conePivot} ${L2_EDGE_CLASSES.coneDimmed}`);
  edges.forEach(e => {
    const id = typeof e.id === 'function' ? e.id() : e.id;
    if (id === clickedEdgeId) e.addClass(L2_EDGE_CLASSES.conePivot);
    else if (before.has(id)) e.addClass(L2_EDGE_CLASSES.coneBefore);
    else if (after.has(id)) e.addClass(L2_EDGE_CLASSES.coneAfter);
    else e.addClass(L2_EDGE_CLASSES.coneDimmed);
  });
}

/** Clear the flow-cone focus classes (canvas click / graph reload). */
export function clearFlowCone(cy) {
  if (!cy || (typeof cy.destroyed === 'function' && cy.destroyed())) return;
  const edges = cy.edges();
  if (!edges || typeof edges.removeClass !== 'function') return;
  edges.removeClass(`${L2_EDGE_CLASSES.coneBefore} ${L2_EDGE_CLASSES.coneAfter} ${L2_EDGE_CLASSES.conePivot} ${L2_EDGE_CLASSES.coneDimmed}`);
}

/**
 * L1/L2 Data Flow Graph — V4.1
 * Pure UI orchestration. Layout is handled inside useCytoscapeGraph.
 */
export default function DataFlowGraph(props) {
  const {
    graphData, level, layoutMode, onOpenL2,
    onEdgeClick, onToggleLayout, selectedEdgeId,
    onCanvasTap,
    // L2 flow toggle (#331, four modes): flowNodeIds / flowEdgeIds are the
    // target-field flow closure from the L2 response (used by the flow-only
    // members' client-side filter — flowNodeIds is shared by both pairs, the
    // edge ids differ: unmerged for 'flow', line-merged for 'flow-merged');
    // viewMode selects the view — 'flow-merged' | 'full-merged' | 'flow' |
    // 'full' | null (disabled); onViewModeChange notifies the parent.
    flowNodeIds, flowEdgeIds, viewMode, onViewModeChange,
    // R31/A-M5 layout persistence: savedPositions = {nodeId: [x,y]} re-applied
    // on a fresh graph (resume); onPositionsChange reports drag-end positions.
    savedPositions, onPositionsChange,
  } = props;

  const containerRef = useRef(null);

  // The cytoscape hook takes a boolean flowOnly (client-side filter over a
  // single FULL payload). Both pairs — detailed ('flow'/'full') and merged
  // ('flow-merged'/'full-merged') — render from ONE payload and filter
  // client-side, so the flow-only member hides non-closure elements without
  // a re-layout (node positions stay byte-identical within each pair).
  const flowOnly = (viewMode === 'flow' || viewMode === 'flow-merged') ? true
    : (viewMode === 'full' || viewMode === 'full-merged') ? false : null;

  // R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow — the
  // client-side count feeds the toggle badge + the legend note; the
  // edges stay in the graph model (payload untouched, nothing re-fetches).
  const structureEdgeCount = useMemo(() => countStructureEdges(graphData), [graphData]);

  const { cyRef, fit, relayout } = useCytoscapeGraph(containerRef, graphData, {
    level: level || 'L1',
    layoutMode: layoutMode || 'snake',
    showRoleBadges: true,
    // L2 flow toggle — the hook builds the FULL graph and hides/shows the
    // closure client-side (never a re-fetch, never a re-layout).
    flowNodeIds,
    flowEdgeIds,
    flowOnly,
    // R31/A-M5: resume re-applies saved positions; drag-ends report positions.
    savedPositions,
    onPositionsChange,
    onEdgeTap: (e) => {
      const edgeData = e.target.data();
      // R25/§8.8: the per-edge payload (highlight_line / flow_kind /
      // reason) is the single source of truth — pass the full edge data
      // through; no range fields exist anymore.
      onEdgeClick?.(edgeData);
      // R30/#222: L2 edge click highlights its flow cone (upstream green,
      // downstream blue, pivot red, rest dimmed). L1 is untouched.
      if (level === 'L2') {
        applyFlowCone(cyRef.current, graphData, edgeData.id);
      }
    },
    onBgTap: () => {
      onCanvasTap?.();
      // R30/#222: canvas click clears the transient flow-cone focus state.
      if (level === 'L2') clearFlowCone(cyRef.current);
    },

    onDblTap: (e) => {
      if (level === 'L1' && e.target.data().type === 'script_node') {
        const sn = e.target.data().script_name || (e.target.data('label') || '').replace(/\n.*$/, '').trim();
        if (sn) onOpenL2?.(e.target.data().id, sn);
      }
    },
    onHoverEnter: (e) => {
      if (level === 'L1') {
        const d = e.target.data();
        if (d.type === 'script_node' || d.type?.endsWith?.('_table'))
          e.target.style('cursor', 'pointer');
      }
    },
  });

  // Keyboard 'f' → fit
  React.useEffect(() => {
    const h = (e) => {
      if ((e.key === 'f' || e.key === 'F') && cyRef.current &&
        e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
        fit(FIT_PADDING);
      }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [fit]);

  // Resize → auto-fit
  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let t;
    const ro = new ResizeObserver(() => {
      clearTimeout(t);
      t = setTimeout(() => {
        if (cyRef.current && !cyRef.current.destroyed()) {
          // Bug 4 fix: adaptive padding — L2 panel (~420px) collapses
          // with the FIT_PADDING constant. Use 7% panel width for small panels.
          const panelW = el.offsetWidth || 800;
          const pad = panelW < 600
            ? Math.max(30, Math.floor(panelW * 0.07))
            : FIT_PADDING;
          fit(pad);
        }
      }, 200);
    });
    ro.observe(el);
    return () => { ro.disconnect(); clearTimeout(t); };
  }, [fit]);

  // Mode switch via relayout — D-H2: skip the initial mount. The hook's
  // cy.ready runs the initial layout+fit itself (gated on layoutDoneRef
  // internally); this effect only re-runs a layout when layoutMode changes
  // after mount. Without the skip, the mount-time relayout would hide flow
  // elements before the initial deferred cy.fit has seen the full graph.
  const firstMountRef = useRef(true);
  React.useEffect(() => {
    if (firstMountRef.current) {
      firstMountRef.current = false;
      return;
    }
    if (layoutMode && relayout) relayout(layoutMode);
  }, [layoutMode, relayout]);

  const currentMode = (layoutMode || "snake");

  // Highlight selected edge in graph
  React.useEffect(() => {
    const cy = cyRef.current;
    if (!cy || cy.destroyed()) return;
    cy.edges().removeClass('highlighted');
    if (selectedEdgeId) {
      const edge = cy.getElementById(selectedEdgeId);
      if (edge.length) edge.addClass('highlighted');
    }
  }, [selectedEdgeId]);

  return (
    <div className="dataflow-graph-container" data-level={level}>
      <div className="graph-toolbar">
        <span className="graph-level-badge">
          {level === 'L2' ? '📄 Per-Script Detail' : '🔄 Cross-Script Pipeline'}
        </span>
        <button className="btn btn-outline btn-sm" onClick={() => fit(FIT_PADDING)} title="Fit to view (F)">Fit</button>
        {onToggleLayout && (
          <>
            <button className={`btn btn-sm ${currentMode === 'snake' ? 'btn-active' : 'btn-outline'}`}
              onClick={() => onToggleLayout('snake')}
              title="Snake: 2-column workflow layout">
              🐍 Snake
            </button>
            <button className={`btn btn-sm ${currentMode === 'pipeline' ? 'btn-active' : 'btn-outline'}`}
              onClick={() => onToggleLayout('pipeline')}
              title="Pipeline: ELK layered layout">
              📐 Pipeline
            </button>
          </>
        )}
        {level === 'L2' && viewMode !== null && onViewModeChange && (
          <label
            className="flow-mode-toggle"
            title="L2 view: Flow only / Full toggle positions without re-layout; the merged views render one SQL line per edge, the detailed views render every edge."
          >
            <select
              className="flow-mode-select"
              value={viewMode}
              onChange={(e) => onViewModeChange(e.target.value)}
            >
              <option value="flow-merged">Flow only</option>
              <option value="full-merged">Full</option>
              <option value="flow">Flow only (detailed)</option>
              <option value="full">Full (detailed)</option>
            </select>
          </label>
        )}
      </div>
      <DataFlowLegend
        level={level === 'L2' ? 'L2' : 'L1'}
        structureEdgesHidden={level === 'L2'}
        structureEdgeCount={structureEdgeCount}
      />
      <div className="graph-extra-controls">
        <button className="btn btn-outline btn-sm" onClick={() => fit(FIT_PADDING)} title="Fit (F)">🗺</button>
        <button className="btn btn-outline btn-sm" onClick={() => {
          const c = cyRef.current; if (!c) return;
          const a = document.createElement('a');
          a.href = c.png({ full: true, scale: 2, bg: '#1a1a2e' });
          a.download = `dataflow-${level}-${new Date().toISOString().slice(0, 10)}.png`;
          a.click();
        }} title="Export PNG">📷</button>
      </div>
      <div ref={containerRef} className="graph-canvas"
        style={{ width: '100%', height: 'calc(100% - 80px)' }} />
    </div>
  );
}
