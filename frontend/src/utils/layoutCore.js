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
import { FIT_PADDING } from '../config/layout';

// ── Layout constants ───────────────────────────────────────────────
export const SCRIPT_W = 190, SCRIPT_H = 55;
export const TBL_W = 200;
export const TBL_HDR = 26;
export const TBL_MIN_H = 80;
export const FIELD_RENDER_H = 28;
export const FIELD_GAP = 24;
export const FIELD_H = 52;
export const TBL_PAD_TOP = 14;
export const TBL_PAD_BOT = 14;

// ── CSS selectors ──────────────────────────────────────────────────
export const TABLE_SELECTOR = '[type$="_table"], [type="query_output"], [type="cte_table"]';
export const FIELD_SELECTOR = '[type="field"]';

// ── Sizing helpers ─────────────────────────────────────────────────

/** Compute table height from field count (model pixels). */
export function tableHeight(fieldCount) {
  const fc = Math.max(fieldCount, 1);
  return Math.max(TBL_MIN_H,
    TBL_HDR + TBL_PAD_TOP + fc * FIELD_RENDER_H + Math.max(0, fc - 1) * FIELD_GAP + TBL_PAD_BOT);
}

/** Compute {w,h} for a node based on its type and field count. */
export function nodeSize(type, fieldCount) {
  const isTable = type && (type.endsWith('_table') || type === 'query_output' || type === 'cte_table');
  if (isTable) return { w: TBL_W, h: tableHeight(fieldCount || 1) };
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
    const startY = -(parentH / 2) + TBL_HDR + TBL_PAD_TOP + FIELD_RENDER_H / 2;
    fids.forEach((fid, i) => {
      rel[fid] = { parentId: pid, rx: 8, ry: startY + i * FIELD_H };
    });
  }

  return rel;
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
    info[n.id()] = { w: TBL_W, h: tableHeight(fc) };
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
 */
export function applyLayout(cy, tablePositions, fieldRel, tableInfo, fitPadding = FIT_PADDING) {
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

    // 4. Position fields at table + frozen offset
    if (fieldRel) {
      for (const [fid, { parentId, rx, ry }] of Object.entries(fieldRel)) {
        const table = cy.getElementById(parentId);
        const field = cy.getElementById(fid);
        if (table.length && field.length) {
          const tp = table.position();
          field.position({ x: tp.x + rx, y: tp.y + ry });
        }
      }
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

  cy.fit(undefined, fitPadding);

  // Force cytoscape to re-apply stylesheets with updated data values
  // (table _tableWidth/_tableHeight may change after batch)
  if (cy && !cy.destroyed() && cy.style) cy.style().update();
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
