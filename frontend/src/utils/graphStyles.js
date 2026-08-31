// Cytoscape.js stylesheet

// Single source of truth for the searched field's gold styling — shared by
// the field-is_target style rule below AND the L2 node-role legend swatch
// (DataFlowLegend.jsx), so the legend always matches the graph.
export const SEARCHED_FIELD_COLOR = '#FFD700';

export const NODE_STYLES = [
  // Default node style
  {
    selector: 'node',
    style: {
      'label': 'data(label)',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'font-size': 12,
      // R41: at overview zoom (<0.15) labels clamp to a 6px floor instead
      // of smearing into illegibility — the accepted boxes-only overview
      // (user ruling 2026-08-28). min-zoomed-font-size pins the floor, it
      // never hides.
      'min-zoomed-font-size': 6,
      'color': '#f0f0f0',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'border-width': 2,
      'border-color': '#333',
      'background-opacity': 0.9,
      'width': 30,
      'height': 30,
    },
  },
  // Node shapes by variable type
  { selector: 'node[variable_type="table"]', style: { 'shape': 'rectangle', 'width': 80, 'height': 30, 'background-color': '#4A90D9' } },
  { selector: 'node[variable_type="view"]', style: { 'shape': 'rectangle', 'width': 80, 'height': 30, 'background-color': '#5DADE2' } },
  { selector: 'node[variable_type="column"]', style: { 'shape': 'ellipse', 'width': 20, 'height': 24, 'background-color': '#A8D4FF' } },
  { selector: 'node[variable_type="cte"]', style: { 'shape': 'round-rectangle', 'width': 55, 'height': 30, 'background-color': '#5CB85C' } },
  { selector: 'node[variable_type="cte_column"]', style: { 'shape': 'triangle', 'width': 25, 'height': 25, 'background-color': '#8FD98F' } },
  { selector: 'node[variable_type="expression"]', style: { 'shape': 'diamond', 'width': 30, 'height': 30, 'background-color': '#F0AD4E' } },
  { selector: 'node[variable_type="window"]', style: { 'shape': 'hexagon', 'width': 30, 'height': 30, 'background-color': '#967ADC' } },
  { selector: 'node[variable_type="aggregate"]', style: { 'shape': 'triangle', 'width': 30, 'height': 30, 'background-color': '#37BC9B' } },
  { selector: 'node[variable_type="case"]', style: { 'shape': 'pentagon', 'width': 30, 'height': 30, 'background-color': '#D770AD' } },
  { selector: 'node[variable_type="transform"]', style: { 'shape': 'rhomboid', 'width': 30, 'height': 30, 'background-color': '#FFCE54' } },
  { selector: 'node[variable_type="merge_target"]', style: { 'shape': 'rectangle', 'width': 55, 'height': 30, 'background-color': '#DA4453', 'border-width': 3 } },
  { selector: 'node[variable_type="union_branch"]', style: { 'shape': 'vee', 'width': 30, 'height': 30, 'background-color': '#E6E9ED' } },
  { selector: 'node[variable_type="subquery"]', style: { 'shape': 'diamond', 'width': 35, 'height': 35, 'background-color': '#AC92EC' } },
  { selector: 'node[variable_type="virtual_table"]', style: { 'shape': 'round-rectangle', 'width': 65, 'height': 35, 'background-color': '#2ECC71' } },
  { selector: 'node[variable_type="literal"]', style: { 'shape': 'ellipse', 'width': 25, 'height': 25, 'background-color': '#CCCCCC' } },

  // Field children (L2 compound) — uniform styling, override variable_type shapes
  { selector: 'node[type="field"]', style: {
    'shape': 'ellipse', 'width': 14, 'height': 14,
    'background-color': '#A8D4FF', 'border-width': 1, 'border-color': '#5DADE2',
    'font-size': 10, 'color': '#ffffff', 'text-outline-color': '#1a1a2e', 'text-outline-width': 3,
    'text-valign': 'center', 'text-margin-y': 0,
  } },
  // Field children that are target → gold highlight (the searched seed
  // field, gold on the source table AND every alias/CTE/target copy)
  { selector: 'node[type="field"][is_target]', style: {
    'border-color': SEARCHED_FIELD_COLOR, 'border-width': 2, 'background-color': SEARCHED_FIELD_COLOR,
  } },

  // Highlighted / dimmed states
  {
    selector: '.highlighted',
    style: { 'border-color': '#FFD700', 'border-width': 3, 'background-opacity': 1 },
  },
  {
    selector: '.dimmed',
    style: { 'opacity': 0.15 },
  },
  // Tree color classes for multi-tree highlighting (layer mode)
  { selector: '.tree-0', style: { 'border-color': '#FF6B6B', 'border-width': 4, 'background-opacity': 1 } },
  { selector: '.tree-1', style: { 'border-color': '#4ECDC4', 'border-width': 4, 'background-opacity': 1 } },
  { selector: '.tree-2', style: { 'border-color': '#45B7D1', 'border-width': 4, 'background-opacity': 1 } },
  { selector: '.tree-3', style: { 'border-color': '#96CEB4', 'border-width': 4, 'background-opacity': 1 } },
  { selector: '.tree-4', style: { 'border-color': '#FFEAA7', 'border-width': 4, 'background-opacity': 1 } },
  { selector: '.tree-5', style: { 'border-color': '#DDA0DD', 'border-width': 4, 'background-opacity': 1 } },
  { selector: '.tree-6', style: { 'border-color': '#98D8C8', 'border-width': 4, 'background-opacity': 1 } },
  { selector: '.tree-7', style: { 'border-color': '#F39C12', 'border-width': 4, 'background-opacity': 1 } },
  // Tree-colored edges
  { selector: 'edge.tree-0', style: { 'line-color': '#FF6B6B', 'target-arrow-color': '#FF6B6B', 'width': 3 } },
  { selector: 'edge.tree-1', style: { 'line-color': '#4ECDC4', 'target-arrow-color': '#4ECDC4', 'width': 3 } },
  { selector: 'edge.tree-2', style: { 'line-color': '#45B7D1', 'target-arrow-color': '#45B7D1', 'width': 3 } },
  { selector: 'edge.tree-3', style: { 'line-color': '#96CEB4', 'target-arrow-color': '#96CEB4', 'width': 3 } },
  { selector: 'edge.tree-4', style: { 'line-color': '#FFEAA7', 'target-arrow-color': '#FFEAA7', 'width': 3 } },
  { selector: 'edge.tree-5', style: { 'line-color': '#DDA0DD', 'target-arrow-color': '#DDA0DD', 'width': 3 } },
  { selector: 'edge.tree-6', style: { 'line-color': '#98D8C8', 'target-arrow-color': '#98D8C8', 'width': 3 } },
  { selector: 'edge.tree-7', style: { 'line-color': '#F39C12', 'target-arrow-color': '#F39C12', 'width': 3 } },

  // Edge styles — default color (overridden by [color] selector below)
  {
    selector: 'edge',
    style: {
      'width': 2,
      'line-color': '#5DADE2',
      'target-arrow-color': '#5DADE2',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      // v3.3.182: enlarged from 0.8 — arrows were barely visible in L1.
      'arrow-scale': 1.6,
      'label': 'data(label)',
      'font-size': 9,
      'color': '#CCC',
      'text-outline-color': '#0a0a1a',
      'text-outline-width': 3,
      'text-background-color': '#0a0a1a',
      'text-background-opacity': 0.85,
      'text-background-shape': 'round-rectangle',
      'text-background-padding': 2,
      'text-rotation': 'autorotate',
      'text-margin-x': 4,
    },
  },
  // Data-driven edge colors (overrides default for edges with color field)
  {
    selector: 'edge[color]',
    style: {
      'line-color': 'data(color)',
      'target-arrow-color': 'data(color)',
    },
  },
  // Hover feedback — handled via events in useCytoscapeGraph (Cytoscape 3.30+ no :hover selector)

  {
    selector: 'edge[relationship="BELONGS_TO"]',
    style: { 'width': 1, 'line-style': 'dotted' },
  },
  {
    selector: 'edge[relationship="TRANSFORMATION"]',
    style: { 'width': 2, 'line-style': 'dashed' },
  },

  // ── Meta-graph flat styles (multi-script view) ────────────────────
  {
    selector: 'node[type="script_circle"]',
    style: {
      'shape': 'ellipse',
      'width': 24,
      'height': 24,
      'background-color': '#E67E22',
    },
  },
  // Meta-edges
  {
    selector: 'edge[edge_type="data_lineage"]',
    style: {
      'width': 3,
      'line-color': '#00FF88',
      'target-arrow-color': '#00FF88',
      'target-arrow-shape': 'triangle',
      'source-arrow-shape': 'none',
      'arrow-scale': 1.2,
      'line-style': 'solid',
      'font-size': 10,
      'color': '#00FF88',
      'text-outline-color': '#0a0a1a',
      'text-outline-width': 3,
      'text-rotation': 'autorotate',
    },
  },
  {
    selector: 'edge[edge_type="shared_input"]',
    style: {
      'width': 2,
      'line-color': '#5DADE2',
      'target-arrow-color': '#5DADE2',
      'target-arrow-shape': 'triangle',
      'source-arrow-shape': 'none',
      'arrow-scale': 0.8,
      'line-style': 'dashed',
      'font-size': 7,
      'color': '#5DADE2',
      'text-outline-color': '#0a0a1a',
      'text-outline-width': 2,
    },
  },
  // ── V3 L1 Pipeline Table Nodes (data-driven sizing) ────────────────
  // NOTE: width/height use data(_tableWidth)/data(_tableHeight) so
  // applyLayout() can control sizes dynamically. COMPOUND_STYLES below
  // will merge these with additional visual properties.
  {
    selector: 'node[type="source_table"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': '#4A90D9',
      'border-width': 2,
      'border-color': '#357ABD',
      'label': 'data(label)',
      'font-size': 10,
      'color': '#fff',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 2,
    },
  },
  {
    selector: 'node[type="intermediate_table"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': '#5a5a7a',
      'border-width': 2,
      'border-color': '#7a7a9a',
      'label': 'data(label)',
      'font-size': 10,
      'color': '#e0e0e0',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
    },
  },
  {
    selector: 'node[type="output_table"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': '#2ECC71',
      'border-width': 2,
      'border-color': '#27ae60',
      'label': 'data(label)',
      'font-size': 10,
      'color': '#000',
      'text-outline-color': '#e0ffe0',
      'text-outline-width': 1,
    },
  },

  // ── V3 L1 Pipeline Edges (formal §5.1: undirected table-script) ──
  {
    selector: 'edge[edge_type="table_script"]',
    style: {
      'width': 2,
      'line-color': '#5DADE2',
      'target-arrow-color': '#5DADE2',
      'target-arrow-shape': 'triangle',
      'source-arrow-shape': 'none',
      'arrow-scale': 0.9,
      'line-style': 'solid',
      'font-size': 7,
      'color': '#5DADE2',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 2,
      'text-rotation': 'autorotate',
    },
  },
  // Role edges: bold green with formal edge type label
  {
    selector: 'edge[role]',
    style: {
      'width': 3,
      'line-color': '#00FF88',
      'target-arrow-color': '#00FF88',
      'font-size': 8,
      'color': '#00FF88',
      'text-outline-color': '#0a0a1a',
      'text-outline-width': 3,
      'text-rotation': 'autorotate',
    },
  },

  // ── V3 L1 Script Node ─────────────────────────────────────────────
  {
    selector: 'node[type="script_node"]',
    style: {
      'shape': 'ellipse',
      'width': 28,
      'height': 28,
      'background-color': '#F39C12',
      'label': 'data(label)',
      'font-size': 8,
      'color': '#fff',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
    },
  },
  // V3 highlighted path
  {
    selector: '.path-highlighted',
    style: {
      'border-color': '#FFD700',
      'border-width': 4,
      'background-opacity': 1,
    },
  },

];

// Layout — cose defaults (no custom overrides)
export const LAYOUT_OPTIONS = {
  name: 'cose',
  animate: true,
  fit: true,
  padding: 30,
};

// Layout for multi-script meta-graph — breadthfirst for reliable visibility
export const META_LAYOUT_OPTIONS = {
  name: 'breadthfirst',
  fit: true,
  padding: 30,
  directed: true,
  spacingFactor: 1.3,
  animate: true,
  animationDuration: 600,
};

// Layout options for the detail mini-graph in the panel
export const MINI_LAYOUT_OPTIONS = {
  name: 'cose',
  animate: false,
  fit: true,
  padding: 10,
  componentSpacing: 20,
  nodeRepulsion: () => 2000,
  nestingFactor: 0.1,
  gravity: 0.2,
  numIter: 500,
  idealEdgeLength: () => 40,
};

// L2 table-node TYPE colors — color-only differentiation (2026-08-13):
// every L2 table compound renders a solid rectangle; the HUE is the only
// difference between the 5 types. Shared by the compound-type style rules
// below AND the L2 node-type legend (DataFlowLegend.jsx).
export const L2_TABLE_COLORS = {
  source:      { border: '#5DADE2', fill: '#4A90D9' },   // physical read table
  target:      { border: '#58D68D', fill: '#2ECC71' },   // flow destination / output
  withTable:   { border: '#AF7AC5', fill: '#9B59B6' },   // CTE (WITH ... AS) — was green
  anonymous:   { border: '#7a7a9a', fill: '#5a5a7a' },   // unnamed subquery result — neutral
  alias:       { border: '#3BB9C9', fill: '#17A2B8' },   // derived-table alias — was orange
};

// Display-only: backend L2 node `type` -> legend label. The backend type
// strings are NOT changed (naming is a frontend/display concern).
export const L2_TABLE_TYPE_NAMES = {
  source_table:       'Source table',
  output_table:       'Target table',
  cte_table:          'With table',
  intermediate_table: 'Anonymous table',
  alias_table:        'Alias table',
};

// ══════════════════════════════════════════════════════════════════
// V3.2: Compound Table Nodes (parent) + Field Nodes (children)
// ══════════════════════════════════════════════════════════════════

export const COMPOUND_STYLES = [
  // Field nodes (children of table compound nodes)
  {
    selector: 'node[type="field"]',
    style: {
      'shape': 'round-rectangle',
      'width': 105,
      'height': 28,
      'background-color': '#A8D4FF',
      'border-width': 1,
      'border-color': '#5DADE2',
      'label': 'data(label)',
      'font-size': 10,
      'color': '#1a1a2e',
      'text-outline-color': '#A8D4FF',
      'text-outline-width': 1,
    },
  },
  // Target field (gold)
  {
    selector: 'node[is_target="true"]',
    style: {
      'border-color': '#FFD700',
      'border-width': 2,
      'background-color': '#FFF3CD',
    },
  },
  // Direct field (on path to/from target)
  {
    selector: 'node[field_group="direct"]',
    style: {
      'background-opacity': 1,
    },
  },
  // Indirect field (off-path, same table)
  {
    selector: 'node[field_group="indirect"]',
    style: {
      'background-opacity': 0.65,
      'border-style': 'dashed',
    },
  },
  // Source table (read-only, blue)
  {
    selector: 'node[type="source_table"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': L2_TABLE_COLORS.source.fill,
      'background-opacity': 0.5,
      'border-width': 3,
      'border-color': L2_TABLE_COLORS.source.border,
      'border-style': 'solid',
      'label': 'data(label)',
      'font-size': 12,
      'color': '#85C1E9',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'text-valign': 'top',
      'text-halign': 'center',
    },
  },
  // Intermediate table (gray)
  {
    selector: 'node[type="intermediate_table"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': L2_TABLE_COLORS.anonymous.fill,
      'background-opacity': 0.35,
      'border-width': 2,
      'border-color': L2_TABLE_COLORS.anonymous.border,
      'border-style': 'solid',
      'label': 'data(label)',
      'font-size': 12,
      'color': '#d0d0d0',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 2,
      'text-valign': 'top',
      'text-halign': 'center',
    },
  },
  // Output table (green)
  {
    selector: 'node[type="output_table"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': L2_TABLE_COLORS.target.fill,
      'background-opacity': 0.5,
      'border-width': 3,
      'border-color': L2_TABLE_COLORS.target.border,
      'border-style': 'solid',
      'label': 'data(label)',
      'font-size': 12,
      'color': '#82E0AA',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'text-valign': 'top',
      'text-halign': 'center',
    },
  },
  // CTE table (L2 only) — solid purple (was green dashed)
  {
    selector: 'node[type="cte_table"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': L2_TABLE_COLORS.withTable.fill,
      'background-opacity': 0.35,
      'border-width': 2,
      'border-style': 'solid',
      'border-color': L2_TABLE_COLORS.withTable.border,
      'label': 'data(label)',
      'font-size': 12,
      'color': '#C39BD3',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'text-valign': 'top',
      'text-halign': 'center',
    },
  },
  // Query output (L1/L2)
  {
    selector: 'node[type="query_output"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': '#E74C3C',
      'background-opacity': 0.35,
      'border-width': 2,
      'border-color': '#EC7063',
      'border-style': 'solid',
      'label': 'data(label)',
      'font-size': 12,
      'color': '#F5B7B1',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'text-valign': 'top',
      'text-halign': 'center',
    },
  },

  // Alias table (cyan, solid border — L2 only)
  {
    selector: 'node[type="alias_table"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': L2_TABLE_COLORS.alias.fill,
      'background-opacity': 0.35,
      'border-width': 2,
      'border-color': L2_TABLE_COLORS.alias.border,
      'border-style': 'solid',
      'label': 'data(label)',
      'font-size': 12,
      'color': '#9ADBE8',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'text-valign': 'top',
      'text-halign': 'center',
    },
  },
];

// ══════════════════════════════════════════════════════════════════
// V3.2: 7-Category Edge Styles (formal §10.3)
// ══════════════════════════════════════════════════════════════════

export const L1_PIPELINE_EDGE_STYLES = [
  // reads_from: table → script (data flows into script)
  {
    selector: 'edge[edge_type="reads_from"]',
    style: {
      'width': 5,
      'line-style': 'solid',
      'line-color': '#5DADE2',
      'target-arrow-color': '#85C1E9',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.1,
      'curve-style': 'bezier',
      'font-size': 9,
    },
  },
  // writes_to: script → table (data flows out of script)
  {
    selector: 'edge[edge_type="writes_to"]',
    style: {
      'width': 5,
      'line-style': 'solid',
      'line-color': '#27AE60',
      'target-arrow-color': '#58D68D',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.1,
      'curve-style': 'bezier',
      'font-size': 9,
    },
  },
];


export const CATEGORY_EDGE_STYLES = [
  // Copy (REF)
  {
    selector: 'edge[category="copy"]',
    style: {
      'width': 3,
      'line-style': 'solid',
      'line-color': '#2ECC71',
      'target-arrow-color': '#58D68D',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.0,
    },
  },
  // Compute (TRANSFORM, COMPUTED)
  {
    selector: 'edge[category="compute"]',
    style: {
      'width': 3,
      'line-style': 'dashed',
      'line-color': '#F39C12',
      'target-arrow-color': '#F5B041',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.0,
    },
  },
  // Aggregate (AGGREGATE, WINDOW)
  {
    selector: 'edge[category="aggregate"]',
    style: {
      'width': 4,
      'line-style': 'solid',
      'line-color': '#9B59B6',
      'target-arrow-color': '#B39DDB',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.2,
    },
  },
  // Filter/Gate (FILTER, JOIN, INDIRECT)
  {
    selector: 'edge[category="filter"]',
    style: {
      'width': 3.5,
      'line-style': 'dashed',
      'line-color': '#E74C3C',
      'target-arrow-color': '#F1948A',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.0,
    },
  },
  // Combine (SET_OP, SUBQUERY)
  {
    selector: 'edge[category="combine"]',
    style: {
      'width': 3,
      'line-style': 'dashed',
      'line-color': '#E67E22',
      'target-arrow-color': '#F0B27A',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.0,
      'line-dash-pattern': [8, 3, 3, 3],
    },
  },
  // Write (DML)
  {
    selector: 'edge[category="write"]',
    style: {
      'width': 4,
      'line-style': 'solid', 'line-dash-pattern': [8, 2, 3, 2],
      'line-color': '#3498DB',
      'target-arrow-color': '#5DADE2',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.2,
    },
  },
  // ALIAS edges (use unbundled-bezier to reduce crossing)
  {
    selector: 'edge[edge_type="ALIAS"]',
    style: {
      'curve-style': 'unbundled-bezier',
      'control-point-distances': [-30, 30],
      'control-point-weights': [0.3, 0.7],
    },
  },
  // Value flow (TABLE_FLOW) — the primary "table feeds output" edge.
  // J12-23/R30: recategorized out of "structure" into "flow" (backend
  // CATEGORY_MAP); renders value-flow green instead of inheriting the
  // light-blue structure color. SCHEMA/ALIAS/SUBSET stay "structure".
  {
    selector: 'edge[category="flow"]',
    style: {
      'width': 3,
      'line-style': 'solid',
      'line-color': '#2ECC71',
      'target-arrow-color': '#2ECC71',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.0,
    },
  },
  // Structure (SCHEMA, ALIAS, SUBSET)
  {
    selector: 'edge[category="structure"]',
    style: {
      'width': 2.5,
      'line-style': 'solid',
      'line-color': '#AED6F1',
      'target-arrow-color': '#AED6F1',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.9,
      'opacity': 1.0,
    },
  },
  // J12-19 (render-only): field→own-table edges live INSIDE the table box
  // (fields sit at table.pos + frozen offset; the box paints an opaque
  // background, and Cytoscape draws edges below nodes by default). Raising
  // their z-index draws them above the box so they are visible + clickable.
  // The class is applied render-only in useCytoscapeGraph — payload untouched.
  {
    selector: 'edge.field-to-own-parent',
    style: {
      'z-index': 1,
    },
  },
  // Edge click → highlight (gold)
  {
    selector: 'edge.edge-selected',
    style: {
      'width': 4,
      'line-color': '#FFD700',
      'target-arrow-color': '#FFD700',
      'border-color': '#FFD700',
      'border-width': 1,
    },
  },
  // Turn edges (snake wrapping)
  {
    selector: 'edge[edge_type="turn"]',
    style: {
      'width': 3,
      'line-style': 'dashed',
      'line-color': '#888888',
      'target-arrow-color': '#888888',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.5,
    },
  },
  // Bundled edges (thicker)
  {
    selector: 'edge.bundled',
    style: {
      'width': 5,
      'line-style': 'solid',
    },
  },
  // Query output (L1/L2)
  {
    selector: 'node[type="query_output"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': '#E74C3C',
      'background-opacity': 0.35,
      'border-width': 2,
      'border-color': '#EC7063',
      'border-style': 'solid',
      'label': 'data(label)',
      'font-size': 12,
      'color': '#F5B7B1',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'text-valign': 'top',
      'text-halign': 'center',
    },
  },
  // ── R25/§8.8: flow-kind labels on L2 edges ─────────────────────────
  // Every L2 edge carries flow_kind (chain / field flow / read / write /
  // filter / structure / bridge — SCHEMA and residual SUBSET included,
  // no excluded category). The label shows the kind ONLY — never the
  // edge type, never SQL text — always visible at the edge midpoint,
  // colored with the edge's own category color (data(color) drives the
  // line color elsewhere; the label inherits the same value).
  {
    selector: 'edge[flow_kind]',
    style: {
      'label': 'data(flow_kind)',
      'font-size': 10,
      'color': 'data(color)',
      'text-outline-color': '#0a0a1a',
      'text-outline-width': 2,
      'text-background-color': '#0a0a1a',
      'text-background-opacity': 0.85,
      'text-background-shape': 'round-rectangle',
      'text-background-padding': 2,
      'text-rotation': 'autorotate',
      'text-valign': 'center',
      'text-halign': 'center',
    },
  },
  // R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow —
  // hidden by default via this class (toggled in useCytoscapeGraph; the
  // edges STAY in the graph model — the payload is untouched, nothing
  // re-fetches). Must come AFTER the category/type rules so the class
  // wins the specificity tie (class and attribute selectors tie in
  // cytoscape; the later rule wins).
  {
    selector: 'edge.structure-hidden',
    style: { 'display': 'none' },
  },
];

// V3.3: Turn Edge Styles (snake wrapping)
// ══════════════════════════════════════════════════
// Turn edges are where a pipeline wraps from row N to row N+1.
// They use dashed lines with a large direction arrow.

export const TURN_EDGE_STYLES = [
  {
    selector: 'edge.turn-edge',
    style: {
      'line-style': 'dashed',
      'line-dash-pattern': [10, 5],
      'width': 3,
      'line-color': '#F39C12',
      'target-arrow-color': '#F39C12',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 2.0,
      'curve-style': 'unbundled-bezier',
    },
  },
  // Query output (L1/L2)
  {
    selector: 'node[type="query_output"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': '#E74C3C',
      'background-opacity': 0.35,
      'border-width': 2,
      'border-color': '#EC7063',
      'border-style': 'solid',
      'label': 'data(label)',
      'font-size': 12,
      'color': '#F5B7B1',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'text-valign': 'top',
      'text-halign': 'center',
    },
  },
];

// V3.3: Bundled Edge Styles (edge bundling §4.5)
export const BUNDLED_EDGE_STYLES = [
  {
    selector: 'edge.bundled-edge',
    style: {
      'width': 6,
      'line-color': '#F39C12',
      'line-style': 'solid',
      'target-arrow-color': '#F39C12',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.5,
      'curve-style': 'bezier',
      'opacity': 0.8,
    },
  },
  // Query output (L1/L2)
  {
    selector: 'node[type="query_output"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': '#E74C3C',
      'background-opacity': 0.35,
      'border-width': 2,
      'border-color': '#EC7063',
      'border-style': 'solid',
      'label': 'data(label)',
      'font-size': 12,
      'color': '#F5B7B1',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'text-valign': 'top',
      'text-halign': 'center',
    },
  },
];

// V3.3: Script Node Cards (design §5.2)
// R6.1-6.8: Orange rounded-rect cards with metadata + operation badges
export const SCRIPT_CARD_STYLES = [
  {
    selector: 'node[type="script_node"]',
    style: {
      'shape': 'round-rectangle',
      'width': 220,
      'height': 65,
      'background-color': '#F39C12',
      'border-width': 1,
      'border-color': '#E67E22',
      'label': 'data(label)',
      'font-size': 10,
      'color': '#ffffff',
      'text-outline-color': '#F39C12',
      'text-outline-width': 1,
      'text-wrap': 'ellipsis',
      'text-max-width': '170px',
      'padding': 4,
    },
  },
  // Active script (L2 is open)
  {
    selector: 'node[type="script_node"].active-script',
    style: {
      'border-color': '#FFD700',
      'border-width': 3,
    },
  },
  // Query output (L1/L2)
  {
    selector: 'node[type="query_output"]',
    style: {
      'shape': 'rectangle',
      'width': 'data(_tableWidth)',
      'height': 'data(_tableHeight)',
      'background-color': '#E74C3C',
      'background-opacity': 0.35,
      'border-width': 2,
      'border-color': '#EC7063',
      'border-style': 'solid',
      'label': 'data(label)',
      'font-size': 12,
      'color': '#F5B7B1',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'text-valign': 'top',
      'text-halign': 'center',
    },
  },
];

// V3.3: Operation Nodes (design §5.3.1) — L2 only
// Small colored pills between input/output fields
export const OPERATION_NODE_STYLES = [
  {
    selector: 'node.operation-node',
    style: {
      'shape': 'round-rectangle',
      'width': 80,
      'height': 24,
      'background-opacity': 0.3,
      'border-width': 1,
      'label': 'data(label)',
      'font-size': 7,
      'text-wrap': 'none',
      'text-valign': 'center',
      'text-halign': 'center',
      'display': 'none',  // Hidden by default, shown on toggle
    },
  },
  {
    selector: 'node.operation-node.visible',
    style: { 'display': 'element' },
  },
];

// R8: L2 Field detail node types (design §5.4)
// NOTE (v3.3.157): the cte_table entry was REMOVED here — it overrode the
// COMPOUND_STYLES rule (this array assembles AFTER it in the L2 stylesheet) with
// the legacy green/dashed style. CTE tables now render per COMPOUND_STYLES:
// solid purple rectangle (color-only differentiation).
export const L2_DETAIL_STYLES = [
  { selector: 'node[type="subquery_output"]', style: { 'shape': 'round-rectangle', 'border-style': 'dotted', 'border-color': '#C4B4F0', 'background-color': '#AC92EC', 'background-opacity': 0.35, 'border-width': 2 } },
  { selector: 'node[type="virtual_table"]', style: { 'shape': 'rectangle', 'border-width': 2, 'border-color': '#58D68D', 'background-color': '#2ECC71', 'background-opacity': 0.35 } },
  { selector: 'node[type="expression"]', style: { 'shape': 'diamond', 'background-color': '#F0AD4E', 'width': 30, 'height': 30 } },
  { selector: 'node[type="aggregate"]', style: { 'shape': 'triangle', 'background-color': '#37BC9B', 'width': 30, 'height': 30 } },
  { selector: 'node[type="window"]', style: { 'shape': 'hexagon', 'background-color': '#967ADC', 'width': 30, 'height': 30 } },
  { selector: 'node[type="literal"]', style: { 'shape': 'ellipse', 'background-color': '#CCCCCC', 'width': 15, 'height': 15 } },
];

// ══════════════════════════════════════════════════════════════════
// R28: L2 node-role styles (2026-08-11) — source / target / waypoint
// ══════════════════════════════════════════════════════════════════
// Single source of truth for the role palette: the node styles AND the
// L2 node-role legend swatches (DataFlowLegend.jsx imports this). All
// colors come from the existing token palette — no new color system:
// source = the source/accent blue family (L1 "Source Table"), target =
// the output green family (L1 "Output Table"), waypoint = the neutral
// intermediate gray.
export const L2_ROLE_COLORS = {
  source: { border: '#5DADE2', fill: '#4A90D9' },
  target: { border: '#58D68D', fill: '#2ECC71' },
  waypoint: { border: '#7a7a9a', fill: '#5a5a7a' },
};

// Data-driven from the payload — the renderer never guesses:
//   - full view (no search): `flow_role` ("source"|"target"|"waypoint")
//     on physical table compounds (CTE/derived/VT compounds stay
//     neutral), per the R19.5 net-flow classification.
//   - filtered view: `flow_source` / `flow_target` booleans on the
//     searched seed's table keeper and the closure's DML write targets.
// Seed-copy FIELDS (is_target, v3.3.140 P1 MOVE→COPY) keep their
// existing gold styling — untouched.
//
// These rules must sit AFTER the compound-type styles in the assembled
// sheet (useCytoscapeGraph appends L2_NODE_ROLE_STYLES last) so the
// attribute selectors win the specificity tie against
// `node[type="source_table"]` / `node[type="output_table"]`.
//
// Order within this array matters for dual-role nodes (a table can be
// both flow_source and flow_target — sup: write leg in, read leg out):
// the SOURCE rule comes last so the searched seed identity wins the
// visual tie (matching the "S/T" badge's primary reading).
export const L2_NODE_ROLE_STYLES = [
  // Target — flow destinations / DML write targets (filtered view
  // flow_target, full view flow_role "target"): output-green border
  // + fill tint.
  {
    selector: 'node[flow_role="target"], node[flow_target]',
    style: {
      'border-width': 4,
      'border-color': L2_ROLE_COLORS.target.border,
      'border-style': 'solid',
      'background-color': L2_ROLE_COLORS.target.fill,
      'background-opacity': 0.5,
    },
  },
  // Source — the searched table, the flow's start (filtered view
  // flow_source, full view flow_role "source"): strong source-blue
  // border + fill tint.
  {
    selector: 'node[flow_role="source"], node[flow_source]',
    style: {
      'border-width': 4,
      'border-color': L2_ROLE_COLORS.source.border,
      'border-style': 'solid',
      'background-color': L2_ROLE_COLORS.source.fill,
      'background-opacity': 0.6,
    },
  },
  // Waypoint — intermediate tables on the flow path (full view
  // flow_role "waypoint" only): neutral dashed border, type fill kept.
  {
    selector: 'node[flow_role="waypoint"]',
    style: {
      'border-width': 3,
      'border-color': L2_ROLE_COLORS.waypoint.border,
      'border-style': 'dashed',
    },
  },
];

// ══════════════════════════════════════════════════════════════════
// R30/#224-#225: L2 uniform edge style + mid-point arrow
// (2026-08-13) — every L2 edge renders ONE uniform line (single color,
// single width, single line-style, NO edge text label) with a
// MID-POINT direction arrow (native `mid-target-arrow-shape`, oriented
// source → target). Supersedes the per-type colors and the R25
// flow_kind mid-edge labels for L2. L1 is untouched: the uniform class
// is added to every L2 edge in useCytoscapeGraph; L1 edges never carry
// it. MUST be appended LAST in the assembled sheet so it wins the
// specificity tie against `edge[color]` / `edge[category=...]` /
// `edge[flow_kind]` (element+attribute == element+class in cytoscape;
// the later rule wins).
// ══════════════════════════════════════════════════════════════════

// Class-name constants — single source of truth shared by the
// stylesheet selectors (here) and the class application (DataFlowGraph).
// Recolor #239 (v3.3.159): the cone went from amber/cyan/gold to RGB
// primaries (green/blue/red) — COLOR ONLY; these class names did NOT
// change (the pivot is still `flow-cone-pivot`).
export const L2_EDGE_CLASSES = {
  uniform: 'l2-uniform',
  coneBefore: 'flow-cone-before',   // green #2ECC71 — upstream of the pivot
  coneAfter: 'flow-cone-after',     // blue  #2196F3 — downstream of the pivot
  conePivot: 'flow-cone-pivot',     // red   #FF3B30 — the clicked edge itself
  coneDimmed: 'flow-cone-dimmed',   // focus mode — everything outside the cone
};

export const L2_UNIFORM_EDGE_COLOR = '#7F8C8D';

export const L2_FLOW_CONE_COLORS = {
  before: '#2ECC71',
  after: '#2196F3',
  pivot: '#FF3B30',
};

export const L2_UNIFORM_EDGE_STYLES = [
  // Uniform base — every L2 edge (the `.l2-uniform` class is applied in
  // useCytoscapeGraph). Keeps `curve-style` from the per-type rules
  // (ALIAS unbundled-bezier) — "uniform" is about color/width/line-style,
  // not curve shape.
  {
    selector: `edge.${L2_EDGE_CLASSES.uniform}`,
    style: {
      'width': 2,
      'line-color': L2_UNIFORM_EDGE_COLOR,
      'line-style': 'solid',
      // Mid-point direction arrow, oriented source → target (R30):
      // the target-END arrow is removed, the MID arrow shows direction.
      'target-arrow-shape': 'none',
      'mid-target-arrow-shape': 'triangle',
      'mid-target-arrow-color': L2_UNIFORM_EDGE_COLOR,
      // v3.3.182: 0.8 was sub-perceivable at the 0.28 zoom floor — 1.8 keeps
      // the direction triangle readable (cone classes inherit it).
      'arrow-scale': 1.8,
      // NO edge text label (supersedes R25 flow_kind mid-edge labels).
      'label': '',
    },
  },
  // ── Click-edge flow cone (R30/#222) — transient focus state ──────
  // These rules must sit AFTER the uniform rule (equal specificity, the
  // later rule wins) so the cone colors override the uniform base.
  {
    selector: `edge.${L2_EDGE_CLASSES.coneBefore}`,
    style: {
      'line-color': L2_FLOW_CONE_COLORS.before,
      'mid-target-arrow-color': L2_FLOW_CONE_COLORS.before,
    },
  },
  {
    selector: `edge.${L2_EDGE_CLASSES.coneAfter}`,
    style: {
      'line-color': L2_FLOW_CONE_COLORS.after,
      'mid-target-arrow-color': L2_FLOW_CONE_COLORS.after,
    },
  },
  {
    selector: `edge.${L2_EDGE_CLASSES.conePivot}`,
    style: {
      'width': 4,
      'line-color': L2_FLOW_CONE_COLORS.pivot,
      'mid-target-arrow-color': L2_FLOW_CONE_COLORS.pivot,
    },
  },
  {
    selector: `edge.${L2_EDGE_CLASSES.coneDimmed}`,
    style: {
      'opacity': 0.15,
    },
  },
];

// ══════════════════════════════════════════════════════════════════
// R32: self-loop FILTER captions on the line-merged views (2026-08-27) —
// RETIRED v3.3.194 (user ruling 2026-08-31).
//
// WHY IT EXISTED: the R32 merge pass promotes every absorbed field edge to
// its parent table, so a filter whose endpoints both live on one table
// collapses into that table's SELF-LOOP (build_line_merged_edges rule 4) —
// e.g. `p_dt → east5` @190 becomes `east5_stzfxxb → east5_stzfxxb`. The
// merged edge is untyped ("FLOW", label "FLOW"), and the rule below painted
// `⟂ <fields> (filtered @L<line>)` on it (DataFlowApp's l2GraphData memo
// recomputes WHICH fields were absorbed from payloads it already holds and
// writes `data.filterLabel`; backend payloads, snapshots and benchmarks are
// untouched).
//
// WHY IT IS GONE: the same text was painted TWICE. v3.3.190 added a caption
// NODE (FILTER_CAPTION_STYLES) because edge labels paint beneath node fills
// — but the enlarged loop's midpoint lies OUTSIDE the table box, so nothing
// covered the edge label any more and both copies rendered at the same
// midpoint: the user saw two identical `⟂ p_dt (filtered @L190)` texts on
// one loop. The loop's line is now its only on-canvas form; the absorbed
// line number still travels through the single click→SQL channel (R37) and
// the Field Story "Filtered" step. The export stays (useCytoscapeGraph
// spreads it) but the array is empty, so no rule matches `edge[filterLabel]`
// and the residual `data.filterLabel` written by DataFlowApp renders
// nothing.
export const FILTER_SELFLOOP_STYLES = [];

// ══════════════════════════════════════════════════════════════════
// Dynamic hover-enlarge (2026-08-27) — display-only emphasis.
// Hovering a NODE adds `.label-emph` to that node PLUS every field chip
// belonging to the same table box (fields are separate top-level nodes
// whose parent was moved into `_tableParent`, so they carry the class
// individually); hovering an EDGE adds it to the edge's two endpoints.
// useCytoscapeGraph wires the mouseover/mouseout classes — the payload
// is untouched and a label size never feeds the layout, so nothing
// re-layouts. MUST be appended LAST in the assembled sheet (this file
// exports it; useCytoscapeGraph spreads it after every other group) so
// font-size/text-outline-width win the specificity tie against the
// per-type rules (`node[type="field"]`, the table compounds, script
// cards…): class == attribute selector specificity in cytoscape, the
// later rule wins (same reasoning as edge.structure-hidden above).
// ══════════════════════════════════════════════════════════════════
// v3.3.183 — merged-view filter caption node: RETIRED v3.3.194 together with
// the edge-label copy above (see FILTER_SELFLOOP_STYLES for the duplicate-
// caption root cause). flowVisibility no longer mints `cap_` nodes, so no
// `node[type="caption"]` can exist; the export stays empty because
// useCytoscapeGraph spreads it.
export const FILTER_CAPTION_STYLES = [];

// v3.3.191 — the enlarged filter self-loop, for real this time.
//
// The v3.3.185 attempt styled `curve-style: segments` + `segment-points:
// data(segp)`. Both halves were inert: (a) cytoscape 3.34 HAS NO
// `segment-points` property (segments are driven by `segment-weights` +
// `segment-distances`) — the parsed stylesheet silently drops the unknown
// property, so the segp data never reached the renderer; (b) even a working
// `segments` curve-style cannot bend a self-edge: in the renderer's dispatch
// the `source === target` branch (findLoopPoints) runs BEFORE the
// segments/taxi branches, whatever curve-style says. A self-loop's ONLY
// geometry levers are the loop properties: `control-point-step-size` (loop
// radius), `loop-direction` (which side of the node it sprouts from) and
// `loop-sweep` (arc span). Default step 40 measured 8×8 px at the 0.28 zoom
// floor — invisible and un-clickable beneath the table box (nodes paint
// above edges). This rule makes the REAL edge the big visible curve:
//   - `control-point-step-size: data(loopstep)` — flowVisibility measures the
//     table box and writes a per-edge step, because cytoscape scales the loop
//     from the node CENTRE (1.4 × step along the loop axis): a fixed step
//     that clears a small chip disappears inside a wide table box. The
//     per-edge step targets a ~111 model-unit bulge past the LEFT border
//     (≈31 px at the 0.28 zoom floor) for every table size — measured with
//     `edge.controlPoints()`: control points reach 0.99 × step from the node
//     centre, the drawn bezier 0.7425 × step − 0.75 × halfW.
//   - `loop-direction: data(loopdir)` + sweep -90deg → the arc attaches to a
//     table BORDER. The first loop on a box keeps the established LEFT side
//     (loopdir -90deg, where the retired v3.3.186 bracket sat); further
//     parallel loops alternate to the RIGHT (loopdir 90deg) so two absorbed
//     filters on one table draw as two separate mirror arcs instead of
//     coincident lines (v3.3.194 — measured: cytoscape's own nesting only
//     separates same-side loops by 62 model units, ~5 px at the 0.08 floor).
// `edge.filter-selfloop` is composed AFTER L2_UNIFORM_EDGE_STYLES in the
// assembled sheet (useCytoscapeGraph), so width/colour win the usual
// specificity tie. flowVisibility.enlargeFilterSelfLoops writes the data and
// mints the class (data first, then class — the mapping resolves on the
// style recalc that follows the batch).
export const FILTER_LOOP_GEOM_STYLES = [
  {
    selector: 'edge.filter-selfloop',
    style: {
      'curve-style': 'bezier',
      'control-point-step-size': 'data(loopstep)',
      'loop-direction': 'data(loopdir)',
      'loop-sweep': '-90deg',
      'width': 7,
      'line-color': '#E74C3C',
      'target-arrow-color': '#E74C3C',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.6,
      'z-index': 30,
    },
  },
];

// v3.3.186 — RETIRED in v3.3.191. This styled the synthetic `capL_` bracket:
// a straight node-node line drawn beside the table BECAUSE the real self-loop
// could not be enlarged (the inert segment-points hack above). With the real
// edge now carrying the visible curve, flowVisibility no longer mints the
// bracket or its anchors — nothing matches this selector. The block stays
// composed (useCytoscapeGraph) so stale classes on a resumed graph render
// benignly instead of falling back to defaults.
export const FILTER_LOOPLINE_STYLES = [
  {
    selector: 'edge.filter-loopline',
    style: {
      'width': 7,
      'line-color': '#E74C3C',
      'target-arrow-color': '#E74C3C',
      'source-arrow-color': '#E74C3C',
      'target-arrow-shape': 'triangle',
      'source-arrow-shape': 'triangle',
      'arrow-scale': 1.6,
      'curve-style': 'bezier',
      'z-index': 30,
      'events': 'no',
      'label': '',
    },
  },
];

export const HOVER_EMPHASIS_STYLES = [
  // Generic node emphasis — ~2× the table/script-title base (12 → 24).
  {
    selector: 'node.label-emph',
    style: { 'font-size': 24, 'text-outline-width': 5, 'z-index': 30 },
  },
  // Field chips sit on a smaller base (10), so their emphasis is pinned
  // separately to keep the user-requested "twice the usual size" honest
  // per tier (10 → 20). The attribute+class rule outranks the generic
  // class rule above, so chips get this one.
  {
    selector: 'node.label-emph[type="field"]',
    style: { 'font-size': 20, 'text-outline-width': 4, 'z-index': 30 },
  },
];

// ══════════════════════════════════════════════════════════════════
// Field Story step-through bar (2026-08-27) — display-only classes.
//
// FieldStoryBar steps through the searched field's story; DataFlowGraph
// receives the active step as `storyFocus` and, inside one cy.batch,
// adds `story-active` to the step's edges, `label-emph` (the existing
// hover-emphasis class — same enlarged-label read) to the step's nodes,
// and `story-dim` to EVERY element the step does not involve. Classes
// only: nothing here feeds a layout, so stepping never re-layouts.
//
// This array is NOT composed by useCytoscapeGraph — DataFlowGraph
// appends it to the LIVE stylesheet at runtime
// (`cy.style().append(...).update()`, once per cy instance), which
// composes it AFTER every group above so it wins the usual specificity
// ties: `edge.story-active`'s width beats `.l2-uniform`'s 2, and
// `.story-dim`'s opacity matches the `.dimmed`/cone-dim 0.15 convention.
// ══════════════════════════════════════════════════════════════════
export const STORY_STYLES = [
  { selector: '.story-dim', style: { opacity: 0.15 } },
  { selector: 'edge.story-active', style: { width: 5, 'z-index': 25 } },
  // Guard (f648 finding, updated v3.3.191): in merged views the Filtered
  // step's visible form is the REAL self-loop edge (edge.filter-selfloop,
  // the big border curve) — the synthetic loop-line bracket is retired and,
  // since v3.3.194, so is the ⟂ caption node that used to sit above it (see
  // FILTER_SELFLOOP_STYLES). A story step lights the self-loop through its
  // merged edge id, and it must GROW, never shrink (edge.story-active
  // width 5 < selfloop's 7): later rule wins the specificity tie. The legacy
  // loop-line guard is kept for resumed graphs that still carry the class.
  { selector: 'edge.filter-selfloop.story-active',
    style: { width: 9, 'z-index': 36, 'line-color': '#FF6B6B',
             'target-arrow-color': '#FF6B6B' } },
  { selector: 'edge.filter-loopline.story-active',
    style: { width: 9, 'z-index': 36, 'line-color': '#FF6B6B',
             'target-arrow-color': '#FF6B6B', 'source-arrow-color': '#FF6B6B' } },
];
