import React from 'react';
import { L2_ROLE_COLORS } from '../utils/graphStyles';

const L2_LEGEND = [
  { label: 'Table', color: '#4A90D9', shape: '■' },
  { label: 'View', color: '#5DADE2', shape: '■' },
  { label: 'Column', color: '#A8D4FF', shape: '●' },
  { label: 'CTE', color: '#5CB85C', shape: '▣' },
  { label: 'CTE Col', color: '#8FD98F', shape: '▲' },
  { label: 'Expression', color: '#F0AD4E', shape: '◆' },
  { label: 'Window', color: '#967ADC', shape: '⬢' },
  { label: 'Aggregate', color: '#37BC9B', shape: '▲' },
  { label: 'Transform', color: '#FFCE54', shape: '▰' },
  { label: 'Case', color: '#D770AD', shape: '⬠' },
  { label: 'Merge', color: '#DA4453', shape: '■' },
  { label: 'Subquery', color: '#AC92EC', shape: '◆' },
  { label: 'Virtual', color: '#2ECC71', shape: '▣' },
  { label: 'Literal', color: '#CCCCCC', shape: '●' },
];

const L1_LEGEND = [
  { label: 'Source Table', color: '#4A90D9', shape: '■' },
  { label: 'Intermediate Table', color: '#5a5a7a', shape: '■' },
  { label: 'Output Table', color: '#2ECC71', shape: '■' },
  { label: 'Script', color: '#F39C12', shape: '●' },
  { label: 'Data Flow', color: '#FFD700', shape: '→', desc: 'Script→Script data lineage' },
  { label: 'Table↔Script', color: '#5DADE2', shape: '↔' },
  { label: 'Role Edge', color: '#00FF88', shape: '→' },
];

const EDGE_LEGEND = [
  { label: 'TABLE_FLOW', color: '#2ECC71', shape: '══', desc: 'Table feeds output' },
  { label: 'ALIAS', color: '#1ABC9C', shape: '- -', desc: 'Original → alias' },
  { label: 'REF', color: '#27AE60', shape: '—', desc: 'Column reference' },
  { label: 'AGGREGATE', color: '#8E44AD', shape: '══', desc: 'SUM/COUNT/AVG' },
  { label: 'TRANSFORM', color: '#D35400', shape: '- -', desc: 'COALESCE/CAST' },
  { label: 'WINDOW', color: '#9B59B6', shape: '- ·', desc: 'ROW_NUMBER/RANK' },
  { label: 'COMPUTED', color: '#E67E22', shape: '···', desc: 'CASE WHEN' },
  { label: 'SCHEMA', color: '#3498DB', shape: '···', desc: 'Table→Column' },
  { label: 'INDIRECT', color: '#C0392B', shape: '·-·', desc: 'HAVING→SELECT' },
  { label: 'FILTER', color: '#E74C3C', shape: '—', desc: 'WHERE condition' },
  { label: 'JOIN', color: '#E91E63', shape: '- -', desc: 'JOIN key' },
  { label: 'CORRELATED', color: '#FF5722', shape: '···', desc: 'Correlated subq' },
  { label: 'DML', color: '#2980B9', shape: '═╪', desc: 'INSERT/UPDATE' },
  { label: 'SET_OP', color: '#F1C40F', shape: '-- --', desc: 'UNION/INTERSECT' },
  { label: 'SUBQUERY', color: '#16A085', shape: '···', desc: 'Subquery ref' },
  { label: 'SUBSET', color: '#7F8C8D', shape: '· ·', desc: 'Bridge' },
];

const CATEGORY_LEGEND = [
  { label: 'Copy (REF)', color: '#2ECC71', shape: '══', desc: 'Value flows unchanged' },
  { label: 'Compute (TRAN/COMP)', color: '#F39C12', shape: '- -', desc: 'Transformation/function' },
  { label: 'Aggregate (SUM/RN)', color: '#967ADC', shape: '══', desc: 'SUM/COUNT/ROW_NUMBER' },
  { label: 'Filter (WHERE/JOIN)', color: '#E74C3C', shape: '···', desc: 'Row filtering/conditions' },
  { label: 'Combine (UNION/SQ)', color: '#E67E22', shape: '- -', desc: 'Set operations/subqueries' },
  { label: 'Write (DML)', color: '#3498DB', shape: '══', desc: 'INSERT/UPDATE/DELETE/MERGE' },
  { label: 'Structure (SCHEMA)', color: '#95A5A6', shape: '···', desc: 'Ownership/alias/bridge' },
];

// R28 (2026-08-11): the L2 legend is a NODE legend — the edge legend is
// gone because R25 rule 5 already labels EVERY edge at its midpoint with
// its flow kind in category color (the old legend only duplicated the
// graph). The node roles, by contrast, were only tiny S/T/W badges —
// never explained. Source and target are the emphasized entries; the
// swatch colors are L2_ROLE_COLORS from graphStyles.js — the SAME
// palette the L2_NODE_ROLE_STYLES stylesheet uses, so the legend always
// matches the graph. Edge kinds stay visible on the edges themselves +
// the hover tooltip (R25 secondary surface).
const L2_NODE_ROLE_LEGEND = [
  {
    role: 'source',
    label: 'Source node',
    color: L2_ROLE_COLORS.source.border,
    fill: L2_ROLE_COLORS.source.fill,
    strong: true,
    desc: "the searched table — the flow's start",
  },
  {
    role: 'target',
    label: 'Target node',
    color: L2_ROLE_COLORS.target.border,
    fill: L2_ROLE_COLORS.target.fill,
    strong: true,
    desc: 'flow destinations / output tables',
  },
  {
    role: 'waypoint',
    label: 'Waypoint',
    color: L2_ROLE_COLORS.waypoint.border,
    fill: L2_ROLE_COLORS.waypoint.fill,
    dashed: true,
    desc: 'intermediate tables on the flow path',
  },
];

function L2NodeRoleLegend({ structureEdgesHidden, structureEdgeCount }) {
  return (
    <div className="dataflow-legend" data-testid="legend-l2-node-roles">
      <span className="legend-title">L2 Node Roles</span>
      {L2_NODE_ROLE_LEGEND.map(item => (
        <span key={item.role} className="legend-item" title={item.desc}>
          <span style={{
            display: 'inline-block', width: 12, height: 12, borderRadius: 2,
            flexShrink: 0, verticalAlign: 'middle',
            background: item.fill,
            border: `2px ${item.dashed ? 'dashed' : 'solid'} ${item.color}`,
          }} />
          <span style={item.strong ? { fontWeight: 700 } : undefined}>{item.label}</span>
        </span>
      ))}
      {/* R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow —
          hidden by default; the legend reflects the toggle so the edge
          count is never misleading. */}
      {structureEdgesHidden && structureEdgeCount > 0 && (
        <span className="legend-structure-note" data-testid="legend-structure-note">
          structure edges hidden ({structureEdgeCount})
        </span>
      )}
    </div>
  );
}

export default function DataFlowLegend({ level, structureEdgesHidden, structureEdgeCount }) {
  let items, title;
  if (level === 'L1') {
    items = L1_LEGEND;
  } else if (level === 'L2') {
    return <L2NodeRoleLegend structureEdgesHidden={structureEdgesHidden} structureEdgeCount={structureEdgeCount} />;
  } else if (level === 'categories') {
    items = CATEGORY_LEGEND;
    title = '7 Edge Categories';
  } else {
    items = L2_LEGEND;
  }

  return (
    <div className="dataflow-legend">
      {title && <span className="legend-title">{title}</span>}
      {items.map(item => (
        <span key={item.label} className="legend-item" title={(item.desc || item.label)}>
          <span style={{ color: item.color, fontWeight: 'bold', fontSize: '0.8em' }}>
            {item.shape}
          </span>
          <span>{item.label}</span>
        </span>
      ))}
    </div>
  );
}
