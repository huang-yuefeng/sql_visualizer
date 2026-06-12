// Cytoscape.js stylesheet
export const NODE_STYLES = [
  // Default node style
  {
    selector: 'node',
    style: {
      'label': 'data(label)',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'font-size': 9,
      'color': '#e0e0e0',
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
  { selector: 'node[variable_type="table"]', style: { 'shape': 'rectangle', 'width': 60, 'height': 30, 'background-color': '#4A90D9' } },
  { selector: 'node[variable_type="view"]', style: { 'shape': 'rectangle', 'width': 60, 'height': 30, 'background-color': '#5DADE2' } },
  { selector: 'node[variable_type="column"]', style: { 'shape': 'ellipse', 'width': 20, 'height': 20, 'background-color': '#A8D4FF' } },
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

  // Highlighted / dimmed states
  {
    selector: '.highlighted',
    style: { 'border-color': '#FFD700', 'border-width': 3, 'background-opacity': 1 },
  },
  {
    selector: '.dimmed',
    style: { 'opacity': 0.3 },
  },

  // Edge styles — color from data.color
  {
    selector: 'edge',
    style: {
      'width': 1.5,
      'line-color': 'data(color)',
      'target-arrow-color': 'data(color)',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      'arrow-scale': 0.8,
      'label': 'data(label)',
      'font-size': 7,
      'color': '#888',
      'text-outline-color': '#1a1a2e',
      'text-outline-width': 1,
      'text-rotation': 'autorotate',
      'text-margin-x': 4,
    },
  },
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
      'arrow-scale': 1.2,
      'line-style': 'solid',
      'font-size': 9,
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
      'line-style': 'dashed',
      'font-size': 7,
      'color': '#5DADE2',
      'text-outline-color': '#0a0a1a',
      'text-outline-width': 2,
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
