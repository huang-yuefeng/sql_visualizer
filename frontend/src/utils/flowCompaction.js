/**
 * Flow-view table compaction — "compact the field size" (user ruling 2026-09-02).
 *
 * THE PROBLEM
 * ───────────
 * The L2 graph is built ONCE from the FULL payload and the flow-only /
 * merged views only HIDE elements (`flowVisibility.applyFlowVisibility` —
 * pure `.show()`/`.hide()`, never a layout, so positions survive a toggle).
 * A table box is sized from its TOTAL chip count (`layoutCore.tableHeight`)
 * and every chip holds a frozen slot, so a 30-chip table whose flow shows a
 * single chip rendered a tall box with one chip at the top and dead space
 * below — the searched box looked "too empty with only one field".
 *
 * THE FIX
 * ───────
 * After every visibility pass, each table is RE-SIZED to its VISIBLE chips
 * and those chips are re-stacked tightly under the header. Nothing is
 * deleted and no layout re-runs: the compact state is a pure projection of
 * (a) the FULL frozen offsets and (b) which chips are `display:none` right
 * now, so
 *   - it is recomputed from scratch on every call (no drift over toggles),
 *   - the full view restores exactly (all chips visible → the projection IS
 *     the frozen layout, dy = 0),
 *   - hidden chips are never touched (they keep their full-layout slots and
 *     come back exactly there).
 *
 * ANCHORING (the only non-obvious choice)
 * ───────────────────────────────────────
 * The compact box is centred on the CENTROID of its visible chips' existing
 * positions, i.e. the table moves by
 *
 *      dy = mean(full ry of the visible chips) − mean(ry of the new stack)
 *
 * so the visible content stays where it was and only the box shrinks around
 * it. Two properties fall out of that formula:
 *   - a single visible chip does not move AT ALL (the searched chip keeps
 *     its position, its SQL-line click target, and its incident edges);
 *   - a CONTIGUOUS run of visible chips does not move either (their mean
 *     equals the mean of the new stack offset by the same run's start).
 * Only chips separated by hidden siblings slide together, which is exactly
 * the "re-stack tightly" requirement. Keeping the content in place also
 * keeps edges sane: cytoscape re-terminates an edge on the moved box border,
 * and that border is now where the visible chips actually are, instead of
 * stretching across the empty band the hidden chips used to occupy.
 *
 * Width is untouched: every box is `TABLE_DEFAULT_W` wide and a chip's x is
 * always `table.x + FIELD_OFFSET_X`, so compaction is a height-only change.
 *
 * DRAG + PERSISTENCE CONTRACT
 * ───────────────────────────
 * `applyFlowCompaction` returns `{ dy, rel, compacted }`:
 *   - `dy[tableId]` is the displacement this application applied. The caller
 *     keeps it and hands it back on the NEXT call (`prev`), where it is
 *     subtracted first — so the bookkeeping composes across any sequence of
 *     compact → drag → compact → restore without accumulating error, and a
 *     drag made WHILE compacted survives both directions (the delta is
 *     position-independent: it depends only on the two chip sets).
 *   - `rel` is the offset map to drive chips BY while compacted — hand it to
 *     `layoutCore.positionTableFields` (the same helper the drag handler and
 *     `applyLayout` use) via `activeFieldRel()` so a dragged box carries its
 *     visible chips with it.
 *   - `compacted` lists the boxes that actually shrank; empty means the view
 *     shows every chip and the full frozen offsets are in force.
 * Saved layouts stay in FULL space: subtract `dy` before reporting a table
 * position (`fullSpacePositions`), so a drag while compacted can never pin a
 * compacted coordinate into the persisted resume layout.
 */
import {
  TABLE_HDR_H, FIELD_RENDER_H, FIELD_H, TBL_PAD_TOP,
  TABLE_SELECTOR, FIELD_SELECTOR, FIELD_OFFSET_X,
} from '../config/layout';
import { tableHeight, fieldPositionsForTable } from './layoutCore';

/** The no-op compaction: every box full, the frozen offsets in force. */
export const EMPTY_COMPACTION = Object.freeze({ dy: Object.freeze({}), rel: Object.freeze({}), compacted: Object.freeze([]) });

/**
 * ry of the i-th chip inside a box sized for `count` chips (model px,
 * relative to the table centre) — the same math as
 * `layoutCore.computeFieldRelPos`, expressed per chip.
 */
function chipRy(count, i) {
  const h = tableHeight(count);
  return -(h / 2) + TABLE_HDR_H + TBL_PAD_TOP + FIELD_RENDER_H / 2 + i * FIELD_H;
}

/** Mean ry of a full stack of `count` chips (0 for an empty box). */
function meanChipRy(count) {
  if (count <= 0) return 0;
  return chipRy(count, 0) + ((count - 1) / 2) * FIELD_H;
}

/**
 * Pure: the compact layout of ONE table.
 *
 * @param allIds     every chip of the table, in full-layout order
 * @param visibleIds the chips on screen right now (any order)
 * @returns {{ dy: number, height: number, rel: Object, visible: string[] }}
 *   dy      — table-centre displacement (new centre − current centre)
 *   height  — the box height the visible chips need
 *   rel     — { chipId: { parentId, rx, ry } } for the VISIBLE chips only
 *   visible — the visible chips in full-layout order
 *
 * All chips visible → the identity: dy 0, the full height, the full offsets
 * (guarded explicitly so the full view is a bit-exact no-op, not a
 * float-rounding accident).
 */
export function compactTableLayout(tableId, allIds, visibleIds) {
  const total = (allIds || []).length;
  const visSet = new Set(visibleIds || []);
  const visible = (allIds || []).filter(id => visSet.has(id));

  if (visible.length === total) {
    const rel = {};
    visible.forEach((fid, i) => {
      rel[fid] = { parentId: tableId, rx: FIELD_OFFSET_X, ry: chipRy(total, i) };
    });
    return { dy: 0, height: tableHeight(total), rel, visible };
  }

  const count = visible.length;
  if (count > 0) {
    // mean of the visible chips' FULL-layout offsets (index map — no O(n²))
    const idx = new Map((allIds || []).map((id, i) => [id, i]));
    const fullMean = visible.reduce((s, fid) => s + chipRy(total, idx.get(fid)), 0) / count;
    const dy = fullMean - meanChipRy(count);
    const rel = {};
    visible.forEach((fid, i) => {
      rel[fid] = { parentId: tableId, rx: FIELD_OFFSET_X, ry: chipRy(count, i) };
    });
    return { dy, height: tableHeight(count), rel, visible };
  }

  // Nothing visible at all: a header-only box with no content to wrap — it
  // keeps its centre (dy 0) and collapses to the header-plus-one-chip height (tableHeight clamps the count at 1, so a header-only box keeps ~56px of the one-chip band — see tableHeight's max(count, 1) clamp).
  return { dy: 0, height: tableHeight(0), rel: {}, visible };
}

/**
 * Offset map that should drive chip positioning right now: the compact map
 * while at least one box is compacted, the frozen full map otherwise (a full
 * view must keep using the original map so nothing can drift through it).
 */
export function activeFieldRel(compaction, fullFieldRel) {
  if (compaction && Array.isArray(compaction.compacted) && compaction.compacted.length > 0) {
    return compaction.rel;
  }
  return fullFieldRel;
}

/**
 * Table positions reported back to FULL space: a compacted box sits `dy`
 * away from the place the persisted layout knows about (the sign is
 * whichever way the surviving chips stack — frequently UP, since hidden
 * siblings below pull the survivors up), and the resume layout must never
 * learn a compacted coordinate.
 *
 * @returns {{ [tableId]: [x, y] }}
 */
export function fullSpacePositions(positionsByNode, compaction) {
  const dy = (compaction && compaction.dy) || {};
  const out = {};
  for (const [id, p] of Object.entries(positionsByNode || {})) {
    const d = dy[id] || 0;
    out[id] = [p[0], p[1] - d];
  }
  return out;
}

/**
 * Re-size every table box to its VISIBLE chips and re-stack those chips
 * tightly under the header. Pure visibility-projection work: no layout, no
 * fit, no element created or removed.
 *
 * @param cy       Cytoscape instance
 * @param fullFieldRel  `layoutCore.computeFieldRelPos()` output (the FULL
 *                      frozen offsets — always the full map, never compacted)
 * @param prev     the compaction object the PREVIOUS call returned, so its
 *                 displacements can be undone before the new ones apply
 * @returns the new compaction `{ dy, rel, compacted }`. With nothing hidden it
 *          is the identity (`compacted: []`, every dy 0, the full offsets) —
 *          the caller treats that as "the frozen full map is in force".
 */
export function applyFlowCompaction(cy, fullFieldRel, prev) {
  if (!cy || (typeof cy.destroyed === 'function' && cy.destroyed())) return EMPTY_COMPACTION;

  // 1. Split each table's chips into all / visible, in full-layout order —
  //    the same `cy.nodes(FIELD_SELECTOR)` order computeFieldRelPos used, so
  //    the compact stack preserves the full stack's relative order.
  const allByTable = new Map();
  const visibleByTable = new Map();
  cy.nodes(FIELD_SELECTOR).forEach(f => {
    const pid = typeof f.data === 'function' ? f.data('_tableParent') : undefined;
    if (!pid) return;
    if (!allByTable.has(pid)) { allByTable.set(pid, []); visibleByTable.set(pid, []); }
    allByTable.get(pid).push(f.id());
    const hidden = typeof f.hidden === 'function' ? f.hidden() : false;
    if (!hidden) visibleByTable.get(pid).push(f.id());
  });

  const prevDy = (prev && prev.dy) || {};
  const out = { dy: {}, rel: {}, compacted: [] };
  const work = [];

  cy.nodes(TABLE_SELECTOR).forEach(t => {
    const tid = typeof t.id === 'function' ? t.id() : t.id;
    const allIds = allByTable.get(tid) || [];
    if (allIds.length === 0) return; // no chips → nothing to compact around
    const layout = compactTableLayout(tid, allIds, visibleByTable.get(tid) || []);
    const dyBefore = prevDy[tid] || 0;
    out.dy[tid] = layout.dy;
    Object.assign(out.rel, layout.rel);
    // "compacted" = the box shows fewer chips than it was built for. A
    // fully-hidden box has dy 0 (no content to wrap) but still shrinks, so
    // the test is on the chip SET, not on the displacement.
    if (layout.visible.length !== allIds.length) out.compacted.push(tid);
    // A table whose visible chips happen to share the full stack's centroid
    // gets dy 0 while its HEIGHT still changes (e.g. 4 chips, the middle 2
    // hidden) — so "nothing to do" has to check the height too, not just the
    // displacement.
    const heightChanged = layout.height !== t.data('_tableHeight');
    work.push({ node: t, tid, layout, shift: layout.dy - dyBefore, heightChanged });
  });

  // Every box still shows all its chips and nothing is left to undo → the
  // identity. Reporting early keeps a FULL view a strict no-op (no position
  // write, no data churn).
  if (out.compacted.length === 0
    && work.every(w => w.shift === 0 && !w.heightChanged)) return out;

  cy.batch(() => {
    for (const w of work) {
      const node = w.node;
      // 2. Box: shrink to the visible chips and slide onto them. BOTH the
      // data (what the stylesheet maps `height:` to) and an explicit style
      // must be written — layoutCore.applyLayout leaves an explicit px
      // height on every box it sizes, and an explicit style beats the
      // data() mapping, so data alone would change nothing on screen.
      node.data('_tableHeight', w.layout.height);
      node.style('height', `${w.layout.height}px`);
      if (w.shift !== 0) {
        const p = node.position();
        node.position({ x: p.x, y: p.y + w.shift });
      }
      // 3. Chips: table centre + the (compact or full) frozen offsets — the
      //    shared helper, so the math is literally the one the drag handler
      //    and applyLayout use. Hidden chips are absent from `rel` and keep
      //    their full-layout slot untouched.
      const positions = fieldPositionsForTable(node.position(), w.layout.rel, w.tid);
      for (const [fid, pos] of Object.entries(positions)) {
        const f = cy.getElementById(fid);
        if (f && f.length) f.position(pos);
      }
    }
  });

  // The box height is a data-driven mapping (`data(_tableHeight)` in
  // graphStyles) — force the recalc the same way layoutCore.applyLayout does
  // after writing the same data.
  try {
    if (cy.style && typeof cy.style === 'function') cy.style().update();
  } catch (_) { /* a fake cy in unit tests has no stylesheet */ }

  return out;
}
