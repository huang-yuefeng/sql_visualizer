import React, { useRef, useState } from 'react';
import useCytoscapeGraph from '../hooks/useCytoscapeGraph';
import DataFlowLegend from './DataFlowLegend';
import { FIT_PADDING } from '../config/layout';

/**
 * L1/L2 Data Flow Graph — V4.1
 * Pure UI orchestration. Layout is handled inside useCytoscapeGraph.
 */
export default function DataFlowGraph(props) {
  const {
    graphData, level, layoutMode, onOpenL2, scriptInfo, onScriptInfoChange,
    onToggleFilter, l2Filtered, onEdgeClick, onToggleLayout, selectedEdgeId
  } = props;

  const containerRef = useRef(null);
  const [edgeHover, setEdgeHover] = useState(null);

  const { cyRef, fit, relayout } = useCytoscapeGraph(containerRef, graphData, {
    level: level || 'L1',
    layoutMode: layoutMode || 'snake',
    showRoleBadges: true,
    onEdgeTap: (e) => {
      const data = e.target.data();
      onEdgeClick?.({ id: e.target.id(), ...data, sql_range: data.sql_range || null });
    },
    onEdgeHover: (e) => {
      if (e.target.isEdge?.()) {
        setEdgeHover({
          type: e.target.data().edge_type || 'edge',
          desc: e.target.data().category || '',
          color: e.target.data().color || '#5DADE2'
        });
      }
    },
    onTap: (e) => {
      const data = e.target.data();
      if (level === 'L1' && data.type === 'script_node') {
        onScriptInfoChange?.({
          id: data.id, label: data.label || data.script_name,
          script_name: data.script_name, total_variables: data.total_variables,
          input_tables: data.input_tables, output_tables: data.output_tables,
          roles: data.roles || []
        });
      }
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
        if (cyRef.current && !cyRef.current.destroyed())
          fit(FIT_PADDING);
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
    <div className="dataflow-graph-container">
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
            <button className={`btn btn-sm ${currentMode === 'spore' ? 'btn-active' : 'btn-outline'}`}
              onClick={() => onToggleLayout('spore')}
              title="Spore: ELK layered + native overlap avoidance">
              🧬 Spore
            </button>
          </>
        )}
        {level === 'L2' && onToggleFilter && (
          <button className={`btn btn-sm ${l2Filtered ? 'btn-outline' : 'btn-active'}`}
            onClick={onToggleFilter}>
            {l2Filtered ? 'Show All' : 'Show Relevant'}
          </button>
        )}
      </div>
      <DataFlowLegend level={level === 'L2' ? 'L2' : 'L1'} />
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
          fontSize: '0.8rem', pointerEvents: 'none'
        }}>
          <span style={{ color: edgeHover.color, fontWeight: 'bold' }}>{edgeHover.type}</span>
          {edgeHover.desc && <span style={{ color: '#aaa', marginLeft: 8 }}>{edgeHover.desc}</span>}
        </div>
      )}
      {scriptInfo && level === 'L1' && (
        <div className="script-info-popup">
          <div className="sip-header">{scriptInfo.label}
            <button onClick={() => onScriptInfoChange?.(null)}>×</button>
          </div>
          <div>Variables: {scriptInfo.total_variables || '?'}</div>
          <div>Inputs: {(scriptInfo.input_tables || []).join(', ') || 'none'}</div>
          <div>Outputs: {(scriptInfo.output_tables || []).join(', ') || 'none'}</div>
        </div>
      )}
    </div>
  );
}
