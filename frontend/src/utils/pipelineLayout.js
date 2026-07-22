/**
 * Pipeline / Workflow Snake Layout — V3.2.25
 * 
 * Snake-wrapping pipeline layout with layer-based interleaved ordering.
 * Fixes from LAYOUT_ANALYSIS.md:
 *   - Params match backend (maxPerRow=3, nodeSpacing=320, rowHeight=300, TABLE_ROW_H=280)
 *   - Tables and scripts interleaved by layer (not separated)
 *   - Layer-based sort (uses node data 'layer', falls back to label)
 *   - Compound children positioned after layout
 */

import { getElk } from './elkLayout';

const ROW_HEIGHT = 300;        // matches backend SCRIPT_ROW_H
const NODE_SPACING = 320;      // matches backend NODE_SPACING
const MAX_PER_ROW = 3;         // matches backend MAX_PER_ROW
const TABLE_ROW_H = 280;       // matches backend TABLE_ROW_H

export async function applyWorkflowLayout(cy, options = {}) {
  const rowHeight = options.rowHeight || ROW_HEIGHT;
  const nodeSpacing = options.nodeSpacing || NODE_SPACING;
  const maxPerRow = options.maxNodesPerRow || MAX_PER_ROW;
  const usePipeline = options.useDataLineageOrder || false;

  if (cy.nodes().length === 0) return false;

  if (usePipeline) {
    _pipelineLayout(cy, maxPerRow, rowHeight, nodeSpacing, options);
    _positionCompoundChildren(cy);  // P2 fix: reposition compound children
    cy.fit(undefined, 80);
    return true;
  }

  const elk = await getElk();
  if (elk) {
    try {
      const { cytoscapeToElk } = await import('./elkLayout.js');
      const nodes = cy.nodes().map(n => ({
        data: { id: n.id(), label: n.data('label'), type: n.data('type'), parent: n.data('parent') },
      }));
      const edges = cy.edges().map(e => ({
        data: { id: e.id(), source: e.data('source'), target: e.data('target'), label: e.data('label') },
      }));
      const elkGraph = cytoscapeToElk(nodes, edges, { direction: 'RIGHT', spacingNodeNode: 60, spacingLayerLayer: 100 });
      const layouted = await Promise.race([
        elk.layout(elkGraph),
        new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 5000)),
      ]);
      const allNodes = [];
      (function collect(c) { for (const x of c||[]) { if (x.x!==undefined) allNodes.push(x); if (x.children) collect(x.children); } })(layouted.children||[]);
      cy.batch(() => { allNodes.forEach(n => { const node = cy.getElementById(n.id); if (node.length) node.position({x:n.x, y:n.y}); }); });
      _positionCompoundChildren(cy);
      cy.fit(undefined, 80);
      return true;
    } catch (e) {
      console.warn('ELK layout failed, using pipeline:', e.message);
    }
  }

  _pipelineLayout(cy, maxPerRow, rowHeight, nodeSpacing, options);
  _positionCompoundChildren(cy);
  cy.fit(undefined, 80);
  return true;
}

/**
 * P2 fix: Sort by layer field (backend provides it), fall back to label.
 */
function _sortKey(cy, nodeId) {
  const n = cy.getElementById(nodeId);
  if (!n.length) return nodeId;
  
  // Prefer layer field from backend for correct pipeline ordering
  const layer = n.data('layer');
  if (layer !== undefined && layer !== null) {
    return String(layer).padStart(6, '0');
  }
  
  // Fallback: try numeric prefix in label (e.g., "step1_...", "1_load...")
  const label = (n.data('label') || '').replace(/\n.*$/, '').trim();
  if (label) {
    const m = label.match(/(\d+)/);
    if (m) return String(m[1]).padStart(8, '0');
  }
  return label || nodeId;
}

/**
 * Simple topo sort — returns all top-level node IDs in dependency order.
 */
function _topoSort(cy) {
  const edges = cy.edges();
  const inDegree = {};
  const adj = {};
  const nodeIds = new Set();

  cy.nodes().forEach(n => {
    const type = n.data('type') || '';
    const parent = n.data('parent');
    if (parent || type === 'field') return;
    const id = n.id();
    inDegree[id] = 0;
    adj[id] = [];
    nodeIds.add(id);
  });

  edges.forEach(e => {
    const src = e.data('source');
    const tgt = e.data('target');
    const etype = e.data('edge_type');
    if (etype && etype !== 'turn' && nodeIds.has(src) && nodeIds.has(tgt)) {
      adj[src].push(tgt);
      inDegree[tgt] = (inDegree[tgt] || 0) + 1;
    }
  });

  const sortFn = (a, b) => {
    const ka = _sortKey(cy, a);
    const kb = _sortKey(cy, b);
    if (ka < kb) return -1;
    if (ka > kb) return 1;
    return 0;
  };

  const queue = [];
  for (const [id, deg] of Object.entries(inDegree)) {
    if (deg === 0 && nodeIds.has(id)) queue.push(id);
  }
  queue.sort(sortFn);

  const order = [];
  while (queue.length > 0) {
    const cur = queue.shift();
    order.push(cur);
    const nextBatch = [];
    for (const next of (adj[cur] || [])) {
      inDegree[next]--;
      if (inDegree[next] === 0) nextBatch.push(next);
    }
    nextBatch.sort(sortFn);
    for (const nb of nextBatch) {
      let insertIdx = queue.length;
      for (let i = 0; i < queue.length; i++) {
        if (sortFn(nb, queue[i]) < 0) { insertIdx = i; break; }
      }
      queue.splice(insertIdx, 0, nb);
    }
  }

  const remaining = [];
  for (const id of nodeIds) {
    if (!order.includes(id)) remaining.push(id);
  }
  remaining.sort(sortFn);
  for (const id of remaining) order.push(id);

  return order;
}

/**
 * P1 fix: Interleave tables and scripts by layer, snake-wrap as one combined list.
 * Uses a unified row height — all nodes (table or script) go into the same snake rows.
 */
function _pipelineLayout(cy, maxPerRow, rowHeight, nodeSpacing, options = {}) {
  // Collect ALL top-level nodes (tables + scripts, not fields/children)
  const allIds = [];
  const nodeInfo = {};

  cy.nodes().forEach(n => {
    const type = n.data('type') || '';
    const parent = n.data('parent');
    // Skip compound children and field nodes
    if (parent || type === 'field') return;
    
    const id = n.id();
    allIds.push(id);
    nodeInfo[id] = { type, layer: n.data('layer') };
  });

  // Sort combined list: prefer topo order, then layer, then label
  let order;
  try {
    order = _topoSort(cy);
    // Filter to only our ids in case topo sort missed some
    const orderedSet = new Set(order);
    const missing = allIds.filter(id => !orderedSet.has(id));
    order = order.filter(id => allIds.includes(id));
    // Append missing at end
    for (const id of missing) order.push(id);
  } catch (e) {
    // Fallback: sort by layer, then label
    order = [...allIds].sort((a, b) => _sortKey(cy, a).localeCompare(_sortKey(cy, b)));
  }

  // V3.3.14: Preserve backend Y positions, snake-wrap X within each Y row.
  // Backend provides Y via layer data.
  // Frontend only handles horizontal snake-wrap for overflow (>maxPerRow).
  // Group nodes by backend Y, then snake-wrap within each row.
  // V3.3.15: Simple snake-wrap — group by backend Y, no component offsets.
  const rows = {};  // backendY → [node_ids]
  order.forEach((id) => {
    const n = cy.getElementById(id);
    if (!n.length) return;
    const backendY = Math.round(n.data('y') || ((n.data('layer') || 0)) * rowHeight + 80);
    if (!rows[backendY]) rows[backendY] = [];
    rows[backendY].push(id);
  });

  cy.batch(() => {
    Object.entries(rows).sort((a,b) => parseFloat(a[0]) - parseFloat(b[0])).forEach(([yStr, ids]) => {
      const baseY = parseFloat(yStr);
      ids.forEach((id, idx) => {
        const col = idx % maxPerRow;
        const overflowRow = Math.floor(idx / maxPerRow);
        const x = col * nodeSpacing + 100;
        const y = baseY + overflowRow * rowHeight;
        const n = cy.getElementById(id);
        if (n.length) n.position({ x, y });
      });
    });

    // Remove old turn edges
    cy.edges('.turn-edge').remove();
  });

  // Hide individual field nodes in L1 (they're compound children of tables)
  // Show fields by default (inside table compound nodes). Only hide if explicitly requested.
  if (options.hideFields === true) {
    cy.nodes('[type="field"]').forEach(n => {
      n.style('display', 'none');
    });
  }

  // Turn edges removed: they connect unrelated nodes
}

function _snakeWrap(cy, maxPerRow, rowHeight, nodeSpacing) {
  const nodes = cy.nodes();
  const positions = {};
  nodes.forEach(n => { const p = n.position(); positions[n.id()] = { x: p.x, y: p.y, node: n }; });

  const sorted = Object.entries(positions)
    .map(([id, p]) => ({ id, ...p }))
    .sort((a, b) => a.y - b.y || a.x - b.x);

  let row = 0, col = 0;
  let prevY = sorted[0]?.y || 0;

  cy.batch(() => {
    sorted.forEach((item, i) => {
      if (i > 0 && Math.abs(item.y - prevY) > rowHeight * 0.7) {
        row++;
        col = 0;
      }
      const x = col * nodeSpacing + 100;
      item.node.position({ x, y: row * rowHeight + 80 });
      col++;
      prevY = item.y;
      if (col >= maxPerRow) { row++; col = 0; }
    });
    // 2.3: Remove artificial turn edges — they confuse users
    cy.edges('.turn-edge').remove();
  });

  // Turn edges disabled — they mislead users into thinking they represent data flow
}

/* _addTurnEdges removed (V3.3.10) — artificial turn edges confuse users */

/**
 * Position compound children (field nodes) within their parent table nodes.
 */
function _positionCompoundChildren(cy) {
  const FIELD_H = 44;  /* FIELD_RENDER_H(28) + 16px gap */
  const FIELD_RENDER_H = 28;
  const TABLE_HDR_H = 26;
  const TABLE_MIN_H = 80;

  const childrenByParent = {};
  
  cy.nodes().forEach(n => {
    const parent = n.data("_tableParent");
    if (parent) {
      if (!childrenByParent[parent]) childrenByParent[parent] = [];
      childrenByParent[parent].push(n);
    }
  });
  
  cy.batch(() => {
    for (const [parentId, children] of Object.entries(childrenByParent)) {
      const parentNode = cy.getElementById(parentId);
      if (!parentNode.length) continue;
      
      const parentPos = parentNode.position();
      const n = children.length;
      const th = Math.max(TABLE_MIN_H, TABLE_HDR_H + 14 + n * FIELD_RENDER_H + Math.max(0, n - 1) * 8 + 14);
      const halfH = th / 2;
      const startY = -halfH + TABLE_HDR_H + 14 + FIELD_RENDER_H / 2;
      
      children.sort((a, b) => (a.data("label") || "").localeCompare(b.data("label") || ""));
      children.forEach((child, i) => {
        const ax = parentPos.x + 8;
        const ay = parentPos.y + startY + i * (FIELD_RENDER_H + 16);
        child.position({ x: ax, y: ay });
        child.data("x", ax);
        child.data("y", ay);
      });
      
      parentNode.data("_tableHeight", th);
      parentNode.style("height", th);
    }
  });
}

export { _pipelineLayout, _topoSort, _snakeWrap, _positionCompoundChildren };
