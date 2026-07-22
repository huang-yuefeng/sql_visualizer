/**
 * Snake Layout Algorithm — workflow-style 2-column wrapping layout.
 *
 * Only computes {nodeId → {x,y}} for tables+scripts.
 * All field positioning is handled by layoutCore.applyLayout().
 */
import {
  TBL_W, SCRIPT_W, SCRIPT_H,
  computeFieldRelPos, computeTableInfo, applyLayout, nodeSize,
} from './layoutCore';
import { FIT_PADDING } from '../config/layout';

const SNAKE_MAX = 2;
const START_X = 80, START_Y = 80;
const GAP_X = 60, GAP_Y = 60;

/**
 * Pure function: given sorted topNodes and tableInfo,
 * compute absolute {nodeId: {x,y}} positions.
 */
export function computeSnakePositions(topNodes, tableInfo) {
  if (topNodes.length === 0) return {};

  const nodeSz = {};
  topNodes.forEach(n => {
    const type = n.data('type') || '';
    const isTable = /_table$/.test(type) || type === 'query_output' || type === 'cte_table';
    if (isTable) {
      const ti = tableInfo[n.id()];
      nodeSz[n.id()] = ti || nodeSize(type, 1);
    } else {
      nodeSz[n.id()] = { w: SCRIPT_W, h: SCRIPT_H };
    }
  });

  const rows = [];
  for (let i = 0; i < topNodes.length; i++) {
    const col = i % SNAKE_MAX;
    if (col === 0) rows.push([]);
    rows[rows.length - 1].push({ node: topNodes[i], size: nodeSz[topNodes[i].id()], origCol: col });
  }

  const rowMaxH = rows.map(row => Math.max(...row.map(it => it.size.h)));
  const colMaxW = {};
  for (const row of rows)
    for (const it of row)
      colMaxW[it.origCol] = Math.max(colMaxW[it.origCol] || 0, it.size.w);

  const colCenter = {};
  let cx = START_X;
  for (let c = 0; c < SNAKE_MAX; c++) {
    const cw = colMaxW[c] || TBL_W;
    colCenter[c] = cx + cw / 2;
    cx += cw + GAP_X;
  }

  const rowCenter = [];
  let cy = START_Y;
  for (let r = 0; r < rows.length; r++) {
    rowCenter[r] = cy + rowMaxH[r] / 2;
    cy += rowMaxH[r] + GAP_Y;
  }

  const positions = {};
  for (let r = 0; r < rows.length; r++) {
    const isEvenRow = (r % 2 === 0);
    for (const it of rows[r]) {
      const displayCol = isEvenRow ? it.origCol : (SNAKE_MAX - 1 - it.origCol);
      positions[it.node.id()] = { x: colCenter[displayCol], y: rowCenter[r] };
    }
  }

  return positions;
}

/**
 * Run the full snake layout on a Cytoscape instance.
 */
export function runSnakeLayout(cy) {
  if (!cy || cy.destroyed()) return;
  if (cy.nodes().length === 0) return;

  const fieldRel = computeFieldRelPos(cy);
  const tableInfo = computeTableInfo(cy, fieldRel);

  const topNodes = [];
  cy.nodes().forEach(n => {
    const type = n.data('type') || '';
    if (type === 'field') return;
    topNodes.push(n);
  });

  if (topNodes.length === 0) { cy.fit(undefined, FIT_PADDING); return; }

  topNodes.sort((a, b) => {
    const al = a.data('layer'), bl = b.data('layer');
    if (al !== undefined && bl !== undefined && al !== bl) return al - bl;
    const aN = parseInt((a.data('label') || '').match(/(\d+)/)?.[0] || '9999');
    const bN = parseInt((b.data('label') || '').match(/(\d+)/)?.[0] || '9999');
    if (aN !== bN) return aN - bN;
    return (a.data('label') || '').localeCompare(b.data('label') || '');
  });

  const tablePositions = computeSnakePositions(topNodes, tableInfo);
  applyLayout(cy, tablePositions, fieldRel, tableInfo, FIT_PADDING);
}
