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
  { selector: 'node[variable_type="database_table"]', style: { 'shape': 'rectangle', 'width': 60, 'height': 30, 'background-color': '#4A90D9' } },
  { selector: 'node[variable_type="table_column"]', style: { 'shape': 'ellipse', 'width': 20, 'height': 20, 'background-color': '#A8D4FF' } },
  { selector: 'node[variable_type="cte_table"]', style: { 'shape': 'round-rectangle', 'width': 55, 'height': 30, 'background-color': '#5CB85C' } },
  { selector: 'node[variable_type="cte_column"]', style: { 'shape': 'triangle', 'width': 25, 'height': 25, 'background-color': '#8FD98F' } },
  { selector: 'node[variable_type="intermediate"]', style: { 'shape': 'diamond', 'width': 30, 'height': 30, 'background-color': '#F0AD4E' } },
  { selector: 'node[variable_type="window_result"]', style: { 'shape': 'hexagon', 'width': 30, 'height': 30, 'background-color': '#967ADC' } },
  { selector: 'node[variable_type="aggregate"]', style: { 'shape': 'triangle', 'width': 30, 'height': 30, 'background-color': '#37BC9B' } },
  { selector: 'node[variable_type="case_result"]', style: { 'shape': 'pentagon', 'width': 30, 'height': 30, 'background-color': '#D770AD' } },
  { selector: 'node[variable_type="function_result"]', style: { 'shape': 'rhomboid', 'width': 30, 'height': 30, 'background-color': '#FFCE54' } },
  { selector: 'node[variable_type="merge_target"]', style: { 'shape': 'rectangle', 'width': 55, 'height': 30, 'background-color': '#DA4453', 'border-width': 3 } },
  { selector: 'node[variable_type="union_branch"]', style: { 'shape': 'vee', 'width': 30, 'height': 30, 'background-color': '#E6E9ED' } },

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
];

// Layout options — compact, readable force-directed layout
export const LAYOUT_OPTIONS = {
  name: 'cose',
  animate: true,
  animationDuration: 800,
  fit: true,
  padding: 20,
  randomize: false,
  componentSpacing: 40,
  nodeRepulsion: () => 4000,
  edgeElasticity: () => 100,
  nestingFactor: 0.2,
  gravity: 0.3,
  numIter: 2000,
  initialTemp: 100,
  coolingFactor: 0.99,
  minTemp: 0.5,
  nodeOverlap: 12,
  idealEdgeLength: () => 60,
};
