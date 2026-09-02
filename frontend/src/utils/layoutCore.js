/**
 * Layout Core — shared by all layout algorithms.
 *
 * Architecture:
 *   1. computeFieldRelPos()  — frozen relative field positions (layout-independent)
 *   2. computeTableInfo()    — table {w,h} from field counts
 *   3. Layout algo           — computes {nodeId: {x,y}} for tables+scripts only
 *   4. applyLayout()         — single cy.batch(): sizes + table positions + field positions
 *
 * Every layout algorithm (snake, ELK, …) only computes table/script coordinates.
 * Everything else is handled here.
 */
import {
  FIT_PADDING, TABLE_HDR_H, FIELD_RENDER_H, FIELD_H, FIELD_GAP,
  TABLE_MIN_H, TABLE_DEFAULT_W, SCRIPT_W, SCRIPT_H,
  TBL_PAD_TOP, TBL_PAD_BOT, TABLE_SELECTOR, FIELD_SELECTOR, FIELD_OFFSET_X,
  fitWholeGraph,
} from '../config/layout';

// ── Layout constants — imported from config/layout.js ──────────────
// (no local definitions — single source of truth)

// ── Sizing helpers ─────────────────────────────────────────────────

/** Compute table height from field count (model pixels). */
export function tableHeight(fieldCount) {
  const fc = Math.max(fieldCount, 1);
  return Math.max(TABLE_MIN_H,
    TABLE_HDR_H + TBL_PAD_TOP + fc * FIELD_RENDER_H + Math.max(0, fc - 1) * FIELD_GAP + TBL_PAD_BOT);
}

/** Compute {w,h} for a node based on its type and field count. */
export function nodeSize(type, fieldCount) {
  const isTable = type && (type.endsWith('_table') || type === 'query_output' || type === 'cte_table');
  if (isTable) return { w: TABLE_DEFAULT_W, h: tableHeight(fieldCount || 1) };
  return { w: SCRIPT_W, h: SCRIPT_H };
}

// ── Field relative positions ───────────────────────────────────────

/**
 * Compute frozen relative positions for all field nodes.
 * These are layout-independent: they only depend on field count per table.
 *
 * @returns {{ [fieldId]: { parentId: string, rx: number, ry: number } }}
 *   rx, ry are offsets from parent TABLE center (model pixels).
 */
export function computeFieldRelPos(cy) {
  if (!cy || cy.destroyed()) return {};
  const rel = {};
  const fieldsByParent = {};

  cy.nodes(FIELD_SELECTOR).forEach(f => {
    const pid = f.data('_tableParent');
    if (pid) {
      if (!fieldsByParent[pid]) fieldsByParent[pid] = [];
      fieldsByParent[pid].push(f.id());
    }
  });

  for (const [pid, fids] of Object.entries(fieldsByParent)) {
    const parentH = tableHeight(fids.length);
    const startY = -(parentH / 2) + TABLE_HDR_H + TBL_PAD_TOP + FIELD_RENDER_H / 2;
    fids.forEach((fid, i) => {
      rel[fid] = { parentId: pid, rx: FIELD_OFFSET_X, ry: startY + i * FIELD_H };
    });
  }

  return rel;
}

/**
 * Pure: absolute positions for one table's fields, from the table's
 * center position + the frozen relative offsets.
 *
 * @param tablePos  {x, y} — table model position
 * @param fieldRel  from computeFieldRelPos()
 * @param tableId   parent table node id
 * @returns {{ [fieldId]: {x, y} }}
 */
export function fieldPositionsForTable(tablePos, fieldRel, tableId) {
  const out = {};
  for (const [fid, rel] of Object.entries(fieldRel || {})) {
    if (rel.parentId === tableId) {
      out[fid] = { x: tablePos.x + rel.rx, y: tablePos.y + rel.ry };
    }
  }
  return out;
}

/**
 * Reposition a table's field nodes at table.position() + frozen offsets.
 *
 * SINGLE source for field placement: applyLayout() and the table drag
 * handler (useCytoscapeGraph) both call this, so field positions are
 * always re-derived from the table position + frozen offsets — they can
 * never drift, no matter how the table moved (drag, layout, collision
 * push). Recomputing (instead of accumulating drag deltas) also snaps
 * back any pre-existing discrepancy (a directly-dragged field, a
 * coalesced drag frame).
 */
export function positionTableFields(cy, tableId, fieldRel) {
  if (!cy || cy.destroyed()) return;
  const table = cy.getElementById(tableId);
  if (!table || !table.length) return;
  const positions = fieldPositionsForTable(table.position(), fieldRel, tableId);
  for (const [fid, pos] of Object.entries(positions)) {
    const field = cy.getElementById(fid);
    if (field && field.length) field.position(pos);
  }
}

/**
 * Compute table → {w, h} map from fieldRel.
 * Tables without fields get a default height for 1 field.
 */
export function computeTableInfo(cy, fieldRel) {
  if (!cy || cy.destroyed()) return {};
  const fieldByParent = {};
  for (const [, { parentId }] of Object.entries(fieldRel)) {
    if (!fieldByParent[parentId]) fieldByParent[parentId] = 0;
    fieldByParent[parentId]++;
  }
  const info = {};
  cy.nodes(TABLE_SELECTOR).forEach(n => {
    const fc = fieldByParent[n.id()] || 1;
    info[n.id()] = { w: TABLE_DEFAULT_W, h: tableHeight(fc) };
  });
  return info;
}

// ── Apply layout ───────────────────────────────────────────────────

/**
 * Apply a computed layout to Cytoscape in a single batch.
 *
 * @param cy             Cytoscape instance
 * @param tablePositions  { nodeId: {x, y} } — absolute positions for tables+scripts
 * @param fieldRel        from computeFieldRelPos()
 * @param tableInfo       from computeTableInfo()
 * @param fitPadding      padding for cy.fit() (default FIT_PADDING)
 * @param onFit           optional callback invoked after the deferred cy.fit
 *                        completes — lets callers apply post-fit work (e.g.
 *                        flow-visibility hiding) only AFTER the fit has seen
 *                        the FULL graph (D-H2).
 */
export function applyLayout(cy, tablePositions, fieldRel, tableInfo, fitPadding = FIT_PADDING, onFit) {
  if (!cy || cy.destroyed()) return;

  cy.batch(() => {
    // 1. Set table data (for stylesheet) and sizes
    for (const [id, ti] of Object.entries(tableInfo)) {
      const node = cy.getElementById(id);
      if (node && node.length) {
        node.data('_tableHeight', ti.h);
        node.data('_tableWidth', ti.w);
        node.style('width', ti.w + 'px');
        node.style('height', ti.h + 'px');
      }
    }

    // 2. Set script node sizes (not in tableInfo)
    cy.nodes('[type="script_node"]').forEach(n => {
      if (!tableInfo[n.id()]) {
        n.style('width', SCRIPT_W + 'px');
        n.style('height', SCRIPT_H + 'px');
      }
    });

    // 3. Position all non-field nodes
    for (const [id, pos] of Object.entries(tablePositions)) {
      const node = cy.getElementById(id);
      if (node && node.length) node.position(pos);
    }

    // 4. Position fields at table + frozen offset — via the shared helper
    // (same math as the drag handler in useCytoscapeGraph, so there is a
    // single field-positioning site instead of one per layout algorithm)
    if (fieldRel) {
      const parentIds = new Set();
      for (const rel of Object.values(fieldRel)) parentIds.add(rel.parentId);
      for (const pid of parentIds) positionTableFields(cy, pid, fieldRel);
    }

    // 5. Set table node size via rendered element CSS (cytoscape ignores style() for non-compound nodes)
    for (const [id, ti] of Object.entries(tableInfo)) {
      const node = cy.getElementById(id);
      if (node && node.length) {
        node.style('width', ti.w + 'px');
        node.style('height', ti.h + 'px');
        // Direct DOM access: cytoscape stores rendered elements in node._private
        try {
          const el = node[0];
          if (el && el.style) {
            el.style.width = ti.w + 'px';
            el.style.height = ti.h + 'px';
            el.style.minWidth = ti.w + 'px';
            el.style.minHeight = ti.h + 'px';
          }
        } catch(_) {}
      }
    }
  });

  // Force cytoscape to re-apply stylesheets with updated data values
  // (table _tableWidth/_tableHeight may change after batch)
  if (cy && !cy.destroyed() && cy.style) cy.style().update();

  // Bug 1+4 fix: defer fit with setTimeout so Cytoscape completes positioning.
  // requestAnimationFrame (16ms) is too early — Cytoscape's internal layout
  // cycle may not have flushed batch updates yet. 100ms is reliable.
  // Bug 4: adaptive padding — L2 spends the window on content: 5% of panel
  // width, floored at 16 (synced with useCytoscapeGraph + DataFlowGraph).
  setTimeout(() => {
    if (!cy || cy.destroyed()) return;
    const level = (cy.container()?.closest?.('[data-level]')?.dataset?.level) || 'L1';
    const panelW = cy.container()?.offsetWidth || 800;
    // L2: 5% of panel width, L1: use full fitPadding
    const effectivePadding = level === 'L2'
      ? Math.max(16, Math.floor(panelW * 0.05))
      : fitPadding;
    if (level === 'L2') {
      // FIT-only zoom exception: the initial view of a tall L2 closure needs
      // less than the manual floor to be whole on screen (see config/layout).
      fitWholeGraph(cy, effectivePadding);
    } else {
      // Same exception on L1 — a 100-script workspace needs < 0.08 for every
      // script node to be reachable on screen (measured: q14 sat at x=3124 in
      // a 1200px canvas with the floor clamped).
      const nonFieldNodes = cy.nodes().filter(n => n.data('type') !== 'field');
      if (nonFieldNodes.length > 0) {
        fitWholeGraph(cy, effectivePadding, nonFieldNodes);
      } else {
        fitWholeGraph(cy, effectivePadding);
      }
    }
    // D-H2: signal the caller that the deferred fit is done. This fit runs
    // on the FULL graph — no flow elements are hidden yet — so the viewport
    // spans every node and both flow-only (View 1) and full (View 2) render
    // inside it. Callers must apply flow-visibility hiding only here, AFTER
    // the fit: cy.fit excludes display:none elements, so hiding first would
    // clip the viewport to the closure and push non-closure nodes off-screen.
    onFit?.(cy);
  }, 100);
}

// ── Data prep ──────────────────────────────────────────────────────

/**
 * Strip "parent" from field nodes before Cytoscape sees them.
 * Renames parent → _tableParent so no compound auto-centering occurs.
 */
export function stripFieldParents(nodes) {
  return nodes.map(n => {
    const d = n.data;
    if (d && d.type === 'field' && d.parent) {
      return { ...n, data: { ...d, parent: undefined, _tableParent: d.parent } };
    }
    return n;
  });
}
