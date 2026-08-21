/**
 * ELK.js Layout Algorithm — layered (pipeline) layout.
 */
import {
  computeFieldRelPos, computeTableInfo, applyLayout,
} from './layoutCore';
import { FIELD_SELECTOR, TABLE_SELECTOR } from '../config/layout';
import { runSnakeLayout } from './snakeLayout';
import {
  ELK_SPACING_NODE, ELK_SPACING_LAYER,
  ELK_DIRECTION, ELK_ALGORITHM, FIT_PADDING,
  TABLE_DEFAULT_W, SCRIPT_NODE_W, SCRIPT_NODE_H,
} from '../config/layout';

let elkInstance = null;
let elkLoading = null;

async function getElk() {
  if (elkInstance) return elkInstance;
  if (elkLoading) return elkLoading;
  elkLoading = (async () => {
    try {
      if (window.ELK) { elkInstance = new window.ELK(); return elkInstance; }
      const ELK = await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = '/elk.bundled.js';
        script.onload = () => window.ELK ? resolve(window.ELK) : reject(new Error('ELK not found'));
        script.onerror = () => reject(new Error('Failed to load elk.bundled.js'));
        document.head.appendChild(script);
      });
      elkInstance = new ELK();
      return elkInstance;
    } catch (e) { console.warn('ELK.js not available:', e.message); return null; }
  })();
  return elkLoading;
}

function cytoscapeToElk(nodes, edges, options = {}) {
  const { direction = ELK_DIRECTION, algorithm = ELK_ALGORITHM,
    spacingNodeNode = ELK_SPACING_NODE, spacingLayerLayer = ELK_SPACING_LAYER } = options;
  const nodeMap = {};
  const topLevel = [];
  const children = {};

  for (const n of nodes) {
    const data = n.data || n;
    const id = data.id;
    if (id == null || id === '') continue;
    const parent = data.parent || null;
    const elkNode = {
      id: String(id), labels: [{ text: data.label || String(id) }],
      width: data.width || _defaultWidth(data.type),
      height: data.height || _defaultHeight(data.type),
      properties: { type: data.type },
    };
    nodeMap[id] = elkNode;
    if (parent) {
      if (!children[parent]) children[parent] = [];
      children[parent].push(elkNode);
    } else { topLevel.push(elkNode); }
  }

  for (const [parentId, childNodes] of Object.entries(children)) {
    if (nodeMap[parentId]) {
      nodeMap[parentId].children = childNodes;
      nodeMap[parentId].layoutOptions = {
        'elk.padding': '[top=28,left=8,bottom=8,right=8]',
      };
      nodeMap[parentId].width = Math.min(nodeMap[parentId].width || TABLE_DEFAULT_W, 400);
    } else { topLevel.push(...childNodes); }
  }

  const elkEdges = edges
    .filter(e => {
      const d = e.data || e;
      return d.id != null && d.source != null && d.target != null;
    })
    .map(e => {
      const d = e.data || e;
      return { id: String(d.id), sources: [String(d.source)], targets: [String(d.target)] };
    });

  const layoutOpts = {
    'elk.algorithm': algorithm, 'elk.direction': direction,
    'elk.layered.spacing.nodeNodeBetweenLayers': String(spacingLayerLayer),
    'elk.layered.spacing.nodeNode': String(spacingNodeNode),
    'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  };


  return {
    id: 'root',
    layoutOptions: layoutOpts,
    children: topLevel, edges: elkEdges,
  };
}

function _defaultWidth(type) {
  if (type && (type.endsWith('_table') || type.includes('table'))) return TABLE_DEFAULT_W;
  if (type === 'script_node') return SCRIPT_NODE_W;
  return 80;
}
function _defaultHeight(type) {
  if (type && type.endsWith('_table')) return 120;
  if (type === 'script_node') return SCRIPT_NODE_H;
  return 30;
}

/**
 * Post-ELK collision resolution.
 * Detects overlapping table nodes and pushes them apart.
 * Also clamps any offscreen nodes to reasonable bounds.
 */
function resolveLayoutCollisions(positions, tableInfo, cy, pad = 80) {
  const entries = Object.entries(positions).map(([id, pos]) => ({
    id, x: pos.x, y: pos.y,
    w: (tableInfo[id] ? tableInfo[id].w : (cy.getElementById(id).length ? 190 : 80)),
    h: (tableInfo[id] ? tableInfo[id].h : (cy.getElementById(id).length ? 55 : 30)),
  }));

  if (entries.length < 2) return;

  // Clamp offscreen nodes (ELK can produce extreme coordinates)
  const MAX_COORD = 20000;
  entries.forEach(e => {
    if (Math.abs(e.x) > MAX_COORD || Math.abs(e.y) > MAX_COORD) {
      const sorted = entries.filter(x => Math.abs(x.x) <= MAX_COORD && Math.abs(x.y) <= MAX_COORD);
      if (sorted.length > 0) {
        const avgX = sorted.reduce((s, n) => s + n.x, 0) / sorted.length;
        const avgY = sorted.reduce((s, n) => s + n.y, 0) / sorted.length;
        e.x = avgX + 500 + Math.random() * 200;
        e.y = avgY + Math.random() * 200 - 100;
      } else {
        e.x = 100 + Math.random() * 400;
        e.y = 100 + Math.random() * 400;
      }
      positions[e.id] = { x: e.x, y: e.y };
    }
  });

  // Detect and resolve overlaps (push-apart, 5 iterations for dense graphs)
  const PAD = pad;
  for (let iter = 0; iter < 5; iter++) {
    let anyOverlap = false;
    for (let i = 0; i < entries.length; i++) {
      for (let j = i + 1; j < entries.length; j++) {
        const a = entries[i], b = entries[j];
        const dx = Math.abs(a.x - b.x);
        const dy = Math.abs(a.y - b.y);
        const minDx = (a.w + b.w) / 2 + PAD;
        const minDy = (a.h + b.h) / 2 + PAD;
        if (dx < minDx && dy < minDy) {
          anyOverlap = true;
          const pushX = (minDx - dx) * 0.55;
          a.x -= pushX * 0.5;
          b.x += pushX * 0.5;
          const pushY = (minDy - dy) * 0.1;
          a.y -= pushY * 0.5;
          b.y += pushY * 0.5;
          positions[a.id] = { x: a.x, y: a.y };
          positions[b.id] = { x: b.x, y: b.y };
        }
      }
    }
    if (!anyOverlap) break;
  }
}

/**
 * Apply ELK layout to a Cytoscape instance.
 *
 * @param {object} cy - Cytoscape instance
 * @param {object} options - Layout options
 * @param {function} [onFit] - optional callback invoked after the deferred
 *   cy.fit completes (see layoutCore.applyLayout) — callers use it to apply
 *   flow visibility AFTER the fit has seen the full graph (D-H2).
 */
export async function applyElkLayout(cy, options = {}, onFit) {
  const elk = await getElk();
  if (!elk) { runSnakeLayout(cy, onFit); return false; }

  const fieldRel = computeFieldRelPos(cy);
  const tableInfo = computeTableInfo(cy, fieldRel);

  const fieldIds = new Set(cy.nodes(FIELD_SELECTOR).map(n => n.id()));
  const nonFieldNodes = cy.nodes().filter(n => !fieldIds.has(n.id())).map(n => {
    const ti = tableInfo[n.id()];
    return {
      data: { id: n.id(), label: n.data('label'), type: n.data('type'), parent: null },
      width: ti ? ti.w : (n.renderedOuterWidth ? n.renderedOuterWidth() : undefined),
      height: ti ? ti.h : (n.renderedOuterHeight ? n.renderedOuterHeight() : undefined),
    };
  });
  const nonFieldEdges = cy.edges().filter(e => {
    const s = e.data('source'), t = e.data('target');
    return !fieldIds.has(s) && !fieldIds.has(t);
  });

  try {
    // Adaptive spacing: viewport-responsive node spacing
    const vw = cy.container()?.offsetWidth || 1440;
    const adaptiveNodeSpacing = Math.max(ELK_SPACING_NODE, Math.round(vw / 5));
    const adaptiveLayerSpacing = Math.max(ELK_SPACING_LAYER, Math.round(vw / 7));
    const adaptiveOptions = {
      ...options,
      spacingNodeNode: adaptiveNodeSpacing,
      spacingLayerLayer: adaptiveLayerSpacing,
    };
    const elkGraph = cytoscapeToElk(nonFieldNodes, nonFieldEdges, adaptiveOptions);
    const layouted = await Promise.race([
      elk.layout(elkGraph),
      new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 8000)),
    ]);

    const tablePositions = {};
    (function collect(c) {
      for (const x of (c || [])) {
        if (x.x !== undefined) tablePositions[x.id] = { x: x.x, y: x.y };
        if (x.children) collect(x.children);
      }
    })(layouted.children || []);

    // Fill in missing script node positions
    cy.nodes('[type="script_node"]').forEach(n => {
      if (!tablePositions[n.id()]) {
        tablePositions[n.id()] = { x: 100 + Math.random() * 400, y: 100 + Math.random() * 400 };
      }
    });

    // Post-ELK collision resolution
    resolveLayoutCollisions(tablePositions, tableInfo, cy);

    applyLayout(cy, tablePositions, fieldRel, tableInfo, FIT_PADDING, onFit);
    return true;
  } catch (e) {
    console.warn('ELK layout failed:', e.message);
    runSnakeLayout(cy, onFit);
    return false;
  }
}

export { getElk, cytoscapeToElk };
