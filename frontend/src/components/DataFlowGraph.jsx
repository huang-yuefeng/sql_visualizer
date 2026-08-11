import React, { useRef, useState, useMemo } from 'react';
import useCytoscapeGraph from '../hooks/useCytoscapeGraph';
import DataFlowLegend from './DataFlowLegend';
import { FIT_PADDING } from '../config/layout';
import { countStructureEdges } from '../utils/structureEdges';

/**
 * L1/L2 Data Flow Graph — V4.1
 * Pure UI orchestration. Layout is handled inside useCytoscapeGraph.
 */
export default function DataFlowGraph(props) {
  const {
    graphData, level, layoutMode, onOpenL2,
    onToggleFilter, l2Filtered, onEdgeClick, onToggleLayout, selectedEdgeId,
    onCanvasTap, showStructureEdges, onToggleStructureEdges
  } = props;

  const containerRef = useRef(null);
  const [edgeHover, setEdgeHover] = useState(null);

  // R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow — the
  // client-side count feeds the toggle badge + the legend note; the
  // edges stay in the graph model (payload untouched, nothing re-fetches).
  const structureEdgeCount = useMemo(() => countStructureEdges(graphData), [graphData]);

  const { cyRef, fit, relayout } = useCytoscapeGraph(containerRef, graphData, {
    level: level || 'L1',
    layoutMode: layoutMode || 'snake',
    showRoleBadges: true,
    showStructureEdges,
    onEdgeTap: (e) => {
      // R25/§8.8: the per-edge payload (highlight_line / flow_kind /
      // reason) is the single source of truth — pass the full edge data
      // through; no range fields exist anymore.
      onEdgeClick?.(e.target.data());
    },
    onEdgeHover: (e) => {
      if (e.target.isEdge?.()) {
        const d = e.target.data();
        setEdgeHover({
          type: d.edge_type || 'edge',
          kind: d.flow_kind || null,
          line: (Number.isInteger(d.highlight_line) && d.highlight_line >= 1) ? d.highlight_line : null,
          reason: d.reason || '',
          color: d.color || '#5DADE2'
        });
      }
    },
    onBgTap: () => onCanvasTap?.(),

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
    onHoverLeave: () => setEdgeHover(null),
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
          // with FIT_PADDING=200. Use 7% panel width for small panels.
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

  // Mode switch via relayout
  React.useEffect(() => {
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
        {level === 'L2' && onToggleFilter && (
          <button className={`btn btn-sm ${l2Filtered ? 'btn-outline' : 'btn-active'}`}
            onClick={onToggleFilter}>
            {l2Filtered ? 'Show All' : 'Show Relevant'}
          </button>
        )}
        {/* R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow.
            Display toggle (client-side only) — default OFF = hidden. The
            edge count on the button reflects what is hidden/shown. */}
        {level === 'L2' && (
          <button className={`btn btn-sm ${showStructureEdges ? 'btn-active' : 'btn-outline'}`}
            onClick={onToggleStructureEdges}
            title={showStructureEdges
              ? 'Structure edges visible — click to hide (SCHEMA containment is not data flow)'
              : 'Structure edges hidden — click to show (SCHEMA containment is not data flow)'}>
            Structure {showStructureEdges ? 'on' : 'off'}
            {structureEdgeCount > 0 ? ` (${structureEdgeCount})` : ''}
          </button>
        )}
      </div>
      <DataFlowLegend
        level={level === 'L2' ? 'L2' : 'L1'}
        structureEdgesHidden={level === 'L2' && !showStructureEdges}
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
      {edgeHover && (
        <div className="edge-tooltip" style={{
          position: 'absolute', bottom: 60, left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(0,0,0,0.9)', border: `2px solid ${edgeHover.color}`,
          borderRadius: 6, padding: '6px 14px', zIndex: 10, color: '#fff',
          fontSize: '0.8rem', pointerEvents: 'none', maxWidth: 420
        }}>
          <span style={{ color: edgeHover.color, fontWeight: 'bold' }}>{edgeHover.type}</span>
          {edgeHover.kind && <span style={{ color: '#fff', marginLeft: 8 }}>kind: {edgeHover.kind}</span>}
          {edgeHover.line && <span style={{ color: '#aaa', marginLeft: 8 }}>anchor: L{edgeHover.line}</span>}
          {edgeHover.reason && (
            <div style={{ color: '#aaa', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {edgeHover.reason}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
