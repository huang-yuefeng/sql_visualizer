/**
 * Compound Layout — SINGLE implementation for table + field positioning.
 * Used by both Snake and Pipeline modes. No duplicated logic elsewhere.
 */
import {
  TABLE_HDR_H, FIELD_RENDER_H, FIELD_H, FIELD_GAP, TABLE_MIN_H, TABLE_DEFAULT_W,
} from '../config/layout';

/**
 * Set table compound-node heights based on their field children,
 * then position field children relative to their parent table.
 * Called AFTER table nodes have been placed by a layout algorithm.
 */
export function positionCompoundChildren(cy) {
  if (!cy || cy.destroyed()) return;

  const tableHeights = {};       // tableId → computed height
  const fieldsByParent = {};     // parentId → [fieldIds]
  const fieldRelPos = {};        // fieldId → { rx, ry } relative to parent

  // ── Collect fields by parent ──
  cy.nodes('[type="field"]').forEach(f => {
    const parentId = f.data('parent');
    if (!parentId) return;
    if (!fieldsByParent[parentId]) fieldsByParent[parentId] = [];
    fieldsByParent[parentId].push(f.id());
  });

  // ── Generate placeholder fields for empty table nodes that have edges ──
  const edgeSources = new Set(cy.edges().map(e => e.data('source')));
  const edgeTargets = new Set(cy.edges().map(e => e.data('target')));
  let synthIdx = 0;

  cy.nodes('[type$="_table"], [type="query_output"], [type="cte_table"]').forEach(n => {
    const id = n.id();
    const hasFields = (fieldsByParent[id] || []).length > 0;
    const hasEdges = edgeSources.has(id) || edgeTargets.has(id);
    if (!hasFields && hasEdges) {
      synthIdx++;
      const synthId = `synth_fld_${synthIdx}_${id.substring(0, 8)}`;
      cy.add({
        group: 'nodes',
        data: {
          id: synthId, label: '…', type: 'field', variable_type: 'field',
          parent: id, field_group: 'indirect',
        }
      });
      if (!fieldsByParent[id]) fieldsByParent[id] = [];
      fieldsByParent[id].push(synthId);
    }
  });

  // ── Compute table heights based on field count ──
  cy.nodes('[type$="_table"], [type="query_output"], [type="cte_table"]').forEach(n => {
    const id = n.id();
    const fieldCount = (fieldsByParent[id] || []).length;
    // height = header + padding + fields * renderH + gaps + bottom padding
    const h = Math.max(
      TABLE_MIN_H,
      TABLE_HDR_H + 14 + fieldCount * FIELD_RENDER_H + Math.max(0, fieldCount - 1) * FIELD_GAP + 14
    );
    tableHeights[id] = h;
    n.data('_tableHeight', h);
    n.style('width', TABLE_DEFAULT_W + 'px');
    n.style('height', h + 'px');
  });

  // ── Position field children relative to parent ──
  Object.entries(fieldsByParent).forEach(([parentId, fieldIds]) => {
    const parentNode = cy.getElementById(parentId);
    if (!parentNode.length) return;
    const parentPos = parentNode.position();
    const h = tableHeights[parentId] || TABLE_MIN_H;
    const halfH = h / 2;
    const startY = -halfH + TABLE_HDR_H + 14 + FIELD_RENDER_H / 2;

    fieldIds.forEach((fid, i) => {
      fieldRelPos[fid] = { rx: 8, ry: startY + i * FIELD_H };
    });
  });

  // ── Apply positions in batch ──
  cy.batch(() => {
    cy.nodes('[type="field"]').forEach(f => {
      const rp = fieldRelPos[f.id()];
      if (rp) {
        f.position({ x: rp.rx, y: rp.ry });
        f.data('x', rp.rx);
        f.data('y', rp.ry);
      }
    });
  });
}

/**
 * After a layout algorithm positions table nodes, call this to
 * finalize compound sizing and child positions, then fit viewport.
 */
export function finalizeLayout(cy, fitPadding) {
  positionCompoundChildren(cy);
  if (cy && !cy.destroyed()) {
    cy.fit(undefined, fitPadding);
  }
}
