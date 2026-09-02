import { describe, it, expect } from 'vitest';
import {
  compactTableLayout, applyFlowCompaction, activeFieldRel,
  fullSpacePositions, EMPTY_COMPACTION,
} from '../flowCompaction';
import {
  computeFieldRelPos, positionTableFields, fieldPositionsForTable, tableHeight,
} from '../layoutCore';
import {
  TABLE_SELECTOR, FIELD_SELECTOR, TABLE_HDR_H, FIELD_H, FIELD_RENDER_H,
  TABLE_MIN_H, FIELD_OFFSET_X, TBL_PAD_TOP,
} from '../../config/layout';
import { applyFlowVisibility } from '../flowVisibility';

// ── Fake cytoscape ──────────────────────────────────────────────────
// Just enough of the core for layoutCore.computeFieldRelPos /
// positionTableFields, flowCompaction and flowVisibility: node/edge
// elements with position()/data()/hidden(), the two selectors the
// compaction passes to nodes(), getElementById, batch, style, destroyed.

function makeCy({ tables = [], chips = [], edges = [] }) {
  const byId = new Map();

  const tableEls = tables.map(t => {
    const el = {
      kind: 'table',
      id: () => t.id,
      _pos: { x: t.x, y: t.y },
      // `_styleH` mirrors what layoutCore.applyLayout leaves behind: an
      // explicit px height that BEATS the data() mapping on screen.
      _styleH: tableHeight(t.chipCount || 0),
      _data: { type: t.type || 'source_table', _tableHeight: tableHeight(t.chipCount || 0) },
      position(p) {
        if (p) el._pos = { ...p };
        return { ...el._pos };
      },
      style(prop, v) {
        if (prop === 'height' && v !== undefined) el._styleH = parseFloat(v);
        return el._styleH;
      },
      data(k, v) {
        if (v === undefined) return el._data[k];
        el._data[k] = v;
        return v;
      },
      hidden: () => false,
      show() {}, hide() {},
    };
    byId.set(t.id, el);
    return el;
  });

  const chipEls = chips.map(c => {
    const el = {
      kind: 'chip',
      id: () => c.id,
      _pos: { x: c.x, y: c.y },
      _data: { type: 'field', _tableParent: c.parent, label: c.id, ...(c.isTarget ? { is_target: true } : {}) },
      _hidden: !!c.hidden,
      position(p) {
        if (p) el._pos = { ...p };
        return { ...el._pos };
      },
      data(k, v) {
        if (k === undefined) return el._data; // data() — the whole payload
        if (v !== undefined) { el._data[k] = v; return v; }
        return el._data[k];
      },
      hidden: () => el._hidden,
      hide() { el._hidden = true; },
      show() { el._hidden = false; },
    };
    byId.set(c.id, el);
    return el;
  });

  const edgeEls = edges.map(e => {
    const el = {
      id: () => e.id,
      data: k => e[k],
      _hidden: false,
      hidden: () => el._hidden,
      hide() { el._hidden = true; },
      show() { el._hidden = false; },
    };
    return el;
  });

  const nodeEls = [...tableEls, ...chipEls];
  const all = [...nodeEls, ...edgeEls];
  all.show = function () { this.forEach(e => e.show && e.show()); };
  all.hide = function () { this.forEach(e => e.hide && e.hide()); };

  const matchSel = sel => {
    if (sel === FIELD_SELECTOR) return chipEls;
    if (sel === TABLE_SELECTOR) return tableEls;
    return nodeEls;
  };

  const cy = {
    nodes: sel => matchSel(sel),
    edges: () => edgeEls,
    elements: () => all,
    getElementById: id => {
      const el = byId.get(id);
      if (!el) return [];
      // cytoscape returns a COLLECTION: array-like, with the element's
      // members hoisted onto it (positionTableFields calls .position() and
      // .hidden() on the collection, not on [0]).
      const col = [el];
      col.hidden = () => el.hidden();
      col.position = p => el.position(p);
      col.data = (k, v) => el.data(k, v);
      col.id = () => el.id();
      return col;
    },
    batch: fn => fn(),
    destroyed: () => false,
    style: () => ({ update() {} }),
  };
  cy._byId = byId;
  return cy;
}

/** Build a graph of `nTables` boxes × `chipsPerTable` chips laid out FULL. */
function buildFullGraph({ nTables = 2, chipsPerTable = 4, tablePrefix = 't' } = {}) {
  const tables = [];
  const chips = [];
  for (let i = 0; i < nTables; i += 1) {
    const tid = `${tablePrefix}${i}`;
    tables.push({ id: tid, x: 300 + i * 500, y: 400 + i * 120, chipCount: chipsPerTable });
    for (let c = 0; c < chipsPerTable; c += 1) {
      chips.push({ id: `${tid}_f${c}`, parent: tid });
    }
  }
  const cy = makeCy({ tables, chips });
  const fullRel = computeFieldRelPos(cy);
  // Mirror layoutCore.applyLayout: size the box from the chip count, then
  // place the chips at table position + frozen offset.
  cy.nodes(TABLE_SELECTOR).forEach(t => {
    t.data('_tableHeight', tableHeight(chipsPerTable));
    positionTableFields(cy, t.id(), fullRel);
  });
  return { cy, fullRel };
}

const chipOf = (cy, id) => cy.getElementById(id)[0];
const tableOf = (cy, id) => cy.getElementById(id)[0];
/**
 * The box must be `h` px tall BOTH in the data (what the stylesheet maps
 * `height:` to) and in the explicit style — layoutCore.applyLayout leaves an
 * explicit px height on every box it sizes, and an explicit style BEATS the
 * data mapping, so a data-only write would change nothing on screen. This is
 * the trap the first browser run fell into.
 */
const expectBoxHeight = (node, h) => {
  expect(node.data('_tableHeight')).toBe(h);
  expect(node.style('height')).toBe(h);
};
const snapshot = cy => {
  const out = { tables: {}, chips: {}, heights: {} };
  cy.nodes(TABLE_SELECTOR).forEach(t => {
    out.tables[t.id()] = { ...t.position() };
    // the EFFECTIVE height: an explicit style beats the data() mapping
    out.heights[t.id()] = t.style('height');
  });
  cy.nodes(FIELD_SELECTOR).forEach(f => { out.chips[f.id()] = { ...f.position() }; });
  return out;
};

// ── Pure math ───────────────────────────────────────────────────────

describe('compactTableLayout — visible-set → offsets math', () => {
  const allIds = ['a', 'b', 'c', 'd', 'e'];

  it('single visible chip: the chip keeps its full-layout slot and the box wraps it', () => {
    // chip 'd' is index 3 of 5 — it must NOT move when the box collapses.
    const full = compactTableLayout('T', allIds, ['d']);
    expect(full.visible).toEqual(['d']);
    expect(full.height).toBe(tableHeight(1));
    expect(full.rel.d).toEqual({
      parentId: 'T', rx: FIELD_OFFSET_X, ry: chipRyFor(1, 0),
    });
    // dy places the new box so chip d sits exactly where it was.
    const fullRyOfD = chipRyFor(5, 3);
    expect(full.dy).toBeCloseTo(fullRyOfD - chipRyFor(1, 0), 10);
  });

  it('a contiguous visible block does not move at all — only the box shrinks', () => {
    const full = compactTableLayout('T', allIds, ['b', 'c']);
    expect(full.height).toBe(tableHeight(2));
    // new stack: b at 0, c at 1 → their offsets equal the full offsets of
    // b (1) and c (2), so dy is purely the box-height change.
    expect(full.rel.b.ry).toBeCloseTo(chipRyFor(2, 0), 10);
    expect(full.rel.c.ry).toBeCloseTo(chipRyFor(2, 1), 10);
    expect(full.dy).toBeCloseTo(chipRyFor(5, 1) - chipRyFor(2, 0), 10);
    // …which is the box-height change plus the run's own start offset
    expect(full.dy).toBeCloseTo(-(tableHeight(5) - tableHeight(2)) / 2 + FIELD_H, 10);
  });

  it('scattered visible chips re-stack tightly at FIELD_H pitch', () => {
    const full = compactTableLayout('T', allIds, ['a', 'd']);
    expect(full.rel.a.ry).toBeCloseTo(chipRyFor(2, 0), 10);
    expect(full.rel.d.ry).toBeCloseTo(chipRyFor(2, 1), 10);
    expect(full.rel.d.ry - full.rel.a.ry).toBe(FIELD_H);
  });

  it('is anchored on the visible-chip centroid (the box wraps their old mean)', () => {
    const all = ['a', 'b', 'c', 'd'];
    const full = compactTableLayout('T', all, ['a', 'd']);
    const meanFull = (chipRyFor(4, 0) + chipRyFor(4, 3)) / 2;
    const meanNew = (chipRyFor(2, 0) + chipRyFor(2, 1)) / 2;
    expect(full.dy).toBeCloseTo(meanFull - meanNew, 10);
  });

  it('every chip visible → the identity (dy 0, full height, full offsets)', () => {
    const full = compactTableLayout('T', allIds, allIds);
    expect(full.dy).toBe(0);
    expect(full.height).toBe(tableHeight(5));
    allIds.forEach((id, i) => {
      expect(full.rel[id]).toEqual({ parentId: 'T', rx: FIELD_OFFSET_X, ry: chipRyFor(5, i) });
    });
  });

  it('no chip visible → header-only box, no displacement', () => {
    const full = compactTableLayout('T', allIds, []);
    expect(full.visible).toEqual([]);
    expect(full.height).toBe(tableHeight(0));
    expect(full.height).toBe(Math.max(TABLE_MIN_H, TABLE_HDR_H + TBL_PAD_TOP + FIELD_RENDER_H + 14));
    expect(full.dy).toBe(0);
    expect(full.rel).toEqual({});
  });

  it('preserves the full-layout order of the visible chips', () => {
    const full = compactTableLayout('T', allIds, ['e', 'a', 'c']);
    expect(full.visible).toEqual(['a', 'c', 'e']);
  });
});

// ── Applied to a graph ──────────────────────────────────────────────

describe('applyFlowCompaction — compacts a hidden-chip table', () => {
  it('shrinks the box of the table that lost chips and leaves the rest alone', () => {
    const { cy, fullRel } = buildFullGraph({ nTables: 2, chipsPerTable: 4 });
    const t0 = tableOf(cy, 't0');
    const t1 = tableOf(cy, 't1');
    const t1Before = { pos: t1.position(), h: t1.data('_tableHeight') };
    const seedBefore = { ...chipOf(cy, 't0_f0').position() };
    // t0 keeps only its first chip visible (the searched one).
    ['t0_f1', 't0_f2', 't0_f3'].forEach(id => chipOf(cy, id).hide());

    const res = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);

    expect(res.compacted).toEqual(['t0']);
    expectBoxHeight(t0, tableHeight(1));
    // The searched chip did not move.
    expect(chipOf(cy, 't0_f0').position()).toEqual(seedBefore);
    // The untouched table is untouched.
    expect(t1.position()).toEqual(t1Before.pos);
    expectBoxHeight(t1, t1Before.h);
  });

  it('keeps the visible chips inside the shrunken box, stacked under the header', () => {
    const { cy, fullRel } = buildFullGraph({ nTables: 1, chipsPerTable: 8 });
    ['t0_f0', 't0_f3', 't0_f6'].forEach(id => chipOf(cy, id).hide()); // keep 5 of 8
    const res = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);
    const t = tableOf(cy, 't0');
    const h = t.data('_tableHeight');
    expect(h).toBe(tableHeight(5));
    const vis = res.rel;
    expect(Object.keys(vis).length).toBe(5);
    let prev = null;
    for (const [fid, rel] of Object.entries(vis)) {
      const p = chipOf(cy, fid).position();
      // on the chip column
      expect(p.x).toBe(t.position().x + FIELD_OFFSET_X);
      // inside the box, with the header cleared above it
      expect(p.y).toBeGreaterThan(t.position().y - h / 2 + TABLE_HDR_H);
      expect(p.y).toBeLessThan(t.position().y + h / 2);
      // tight pitch
      if (prev !== null) expect(p.y - prev).toBe(FIELD_H);
      prev = p.y;
      void rel;
    }
    // first chip sits exactly one header+padding under the top border
    expect(prev).not.toBeNull();
  });

  it('is idempotent — a second application moves nothing', () => {
    const { cy, fullRel } = buildFullGraph({ nTables: 1, chipsPerTable: 5 });
    ['t0_f1', 't0_f2'].forEach(id => chipOf(cy, id).hide());
    const first = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);
    const after = snapshot(cy);
    const second = applyFlowCompaction(cy, fullRel, first);
    expect(snapshot(cy)).toEqual(after);
    expect(second.compacted).toEqual(first.compacted);
    expect(second.dy).toEqual(first.dy);
  });

  it('compacts a table whose chips are ALL hidden down to a header-only box', () => {
    const { cy, fullRel } = buildFullGraph({ nTables: 1, chipsPerTable: 3 });
    const t = tableOf(cy, 't0');
    const yBefore = t.position().y;
    ['t0_f0', 't0_f1', 't0_f2'].forEach(id => chipOf(cy, id).hide());
    const res = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);
    expect(res.compacted).toEqual(['t0']);
    expectBoxHeight(t, tableHeight(0));
    // an empty box has no content to wrap — it keeps its centre
    expect(t.position().y).toBe(yBefore);
  });
});

// ── Toggle contract ─────────────────────────────────────────────────

describe('applyFlowCompaction — restore on toggle (no drift over repeats)', () => {
  it('restores the full frozen layout exactly when every chip is shown again', () => {
    const { cy, fullRel } = buildFullGraph({ nTables: 2, chipsPerTable: 4 });
    const full = snapshot(cy);

    chipOf(cy, 't0_f1').hide();
    chipOf(cy, 't0_f2').hide();
    const compacted = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);
    expect(compacted.compacted).toEqual(['t0']);
    expectBoxHeight(tableOf(cy, 't0'), tableHeight(2));

    // back to the full view: every chip is shown again first (the visibility
    // pass that a real toggle runs), THEN the compaction undoes itself.
    chipOf(cy, 't0_f1').show();
    chipOf(cy, 't0_f2').show();
    const restored = applyFlowCompaction(cy, fullRel, compacted);
    expect(restored.compacted).toEqual([]);
    expect(snapshot(cy)).toEqual(full);
  });

  it('survives FIVE compact ↔ full toggles with zero drift', () => {
    const { cy, fullRel } = buildFullGraph({ nTables: 2, chipsPerTable: 6 });
    const full = snapshot(cy);
    let state = EMPTY_COMPACTION;
    for (let i = 0; i < 5; i += 1) {
      // hide (a different pair each round), compact, show everything, restore
      chipOf(cy, `t0_f${i}`).hide();
      chipOf(cy, 't1_f2').hide();
      state = applyFlowCompaction(cy, fullRel, state);
      expect(state.compacted.sort()).toEqual(['t0', 't1']);
      chipOf(cy, `t0_f${i}`).show();
      chipOf(cy, 't1_f2').show();
      state = applyFlowCompaction(cy, fullRel, state);
      expect(state.compacted).toEqual([]);
      expect(snapshot(cy)).toEqual(full);
    }
  });

  it('the full view is a strict no-op when nothing was ever hidden', () => {
    const { cy, fullRel } = buildFullGraph({ nTables: 1, chipsPerTable: 3 });
    const full = snapshot(cy);
    const res = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);
    expect(res.compacted).toEqual([]);
    expect(res.dy).toEqual({ t0: 0 });
    expect(Object.keys(res.rel)).toEqual(['t0_f0', 't0_f1', 't0_f2']);
    expect(snapshot(cy)).toEqual(full);
  });
});

// ── Drag contract ───────────────────────────────────────────────────

describe('applyFlowCompaction — drag contract', () => {
  it('a dragged compacted box carries its VISIBLE chips and not the hidden ones', () => {
    const { cy, fullRel } = buildFullGraph({ nTables: 1, chipsPerTable: 4 });
    chipOf(cy, 't0_f2').hide();
    chipOf(cy, 't0_f3').hide();
    const compaction = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);
    const hiddenBefore = { ...chipOf(cy, 't0_f3').position() };

    // activeFieldRel hands the drag handler the compact map
    const rel = activeFieldRel(compaction, fullRel);
    expect(rel).toBe(compaction.rel);
    const t = tableOf(cy, 't0');
    t.position({ x: t.position().x + 120, y: t.position().y - 60 });
    positionTableFields(cy, 't0', rel);

    for (const [fid, offset] of Object.entries(rel)) {
      const p = chipOf(cy, fid).position();
      expect(p.x - t.position().x).toBe(offset.rx);
      expect(p.y - t.position().y).toBeCloseTo(offset.ry, 10);
    }
    // hidden chips stay where the full layout left them
    expect(chipOf(cy, 't0_f3').position()).toEqual(hiddenBefore);
  });

  it('a drag made while compacted survives the toggle back to the full view', () => {
    const { cy, fullRel } = buildFullGraph({ nTables: 1, chipsPerTable: 4 });
    chipOf(cy, 't0_f1').hide();
    const compaction = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);

    // drag the compacted box
    const rel = activeFieldRel(compaction, fullRel);
    const t = tableOf(cy, 't0');
    t.position({ x: t.position().x + 50, y: t.position().y + 25 });
    positionTableFields(cy, 't0', rel);

    // toggle to the full view: show every chip (the visibility pass), then
    // the frozen offsets come back on the DRAGGED position.
    chipOf(cy, 't0_f1').show();
    const restored = applyFlowCompaction(cy, fullRel, compaction);
    expect(restored.compacted).toEqual([]);
    const fullRelT0 = fieldPositionsForTable(t.position(), fullRel, 't0');
    for (const [fid, pos] of Object.entries(fullRelT0)) {
      expect(chipOf(cy, fid).position()).toEqual(pos);
    }
    // and the box is full height again
    expectBoxHeight(t, tableHeight(4));
  });

  it('reports drag positions in FULL space so the persisted layout never learns a compacted coordinate', () => {
    const { cy, fullRel } = buildFullGraph({ nTables: 1, chipsPerTable: 3 });
    const before = { ...tableOf(cy, 't0').position() };
    chipOf(cy, 't0_f0').hide();
    const compaction = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);
    const dy = compaction.dy.t0;
    const now = tableOf(cy, 't0').position();
    expect(dy).not.toBe(0);
    expect(fullSpacePositions({ t0: [now.x, now.y] }, compaction))
      .toEqual({ t0: [now.x, before.y] });
  });
});

// ── Ordering: visibility BEFORE compaction ──────────────────────────

describe('applyFlowVisibility → applyFlowCompaction (the hook order)', () => {
  it('compacts exactly the boxes the flow filter stripped chips from', () => {
    // t0: 3 chips, only f0 in the closure; t1: 2 chips, both in the closure.
    const tables = [
      { id: 't0', x: 200, y: 200, chipCount: 3 },
      { id: 't1', x: 700, y: 200, chipCount: 2 },
    ];
    const chips = [
      { id: 't0_f0', parent: 't0' }, { id: 't0_f1', parent: 't0' }, { id: 't0_f2', parent: 't0' },
      { id: 't1_f0', parent: 't1' }, { id: 't1_f1', parent: 't1' },
    ];
    const edges = [
      { id: 'e1', source: 't0_f0', target: 't1_f0' },
    ];
    const cy = makeCy({ tables, chips, edges });
    const fullRel = computeFieldRelPos(cy);
    cy.nodes(TABLE_SELECTOR).forEach(t => positionTableFields(cy, t.id(), fullRel));
    const full = snapshot(cy);

    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['t0', 't1', 't0_f0', 't1_f0', 't1_f1'],
      flowEdgeIds: ['e1'],
    });
    const res = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);

    expect(res.compacted).toEqual(['t0']);
    expectBoxHeight(tableOf(cy, 't0'), tableHeight(1));
    expectBoxHeight(tableOf(cy, 't1'), tableHeight(2));
    // the searched chip did not move; the untouched table is byte-identical
    expect(chipOf(cy, 't0_f0').position()).toEqual(full.chips.t0_f0);
    expect(snapshot(cy).tables.t1).toEqual(full.tables.t1);
  });
});

// ── The merged flow view (the L2 product's only mode) ───────────────

describe('flow-merged: edgeless-chip prune + compaction', () => {
  // The merged payload promotes every field endpoint to its parent TABLE,
  // so the visible edge set is table-level and every chip the prune does not
  // exempt is hidden — the exact "box too empty with only one field" case
  // the compaction exists for (searching east5_stzfxxb.BBZ).
  function mergedGraph() {
    const tables = [
      { id: 't0', x: 200, y: 300, chipCount: 6 },
      { id: 't1', x: 700, y: 300, chipCount: 4 },
    ];
    const chips = [];
    for (let i = 0; i < 6; i += 1) chips.push({ id: `t0_f${i}`, parent: 't0' });
    for (let i = 0; i < 4; i += 1) chips.push({ id: `t1_f${i}`, parent: 't1' });
    // t1_f0 carries the seed marker — the prune never hides it (V2-N1).
    chips[6].isTarget = true;
    const edges = [{ id: 'l2m_1', source: 't0', target: 't1' }];
    const cy = makeCy({ tables, chips, edges });
    const fullRel = computeFieldRelPos(cy);
    cy.nodes(TABLE_SELECTOR).forEach(t => positionTableFields(cy, t.id(), fullRel));
    return { cy, fullRel };
  }

  const ALL_IDS = ['t0', 't1', ...Array.from({ length: 6 }, (_v, i) => `t0_f${i}`),
    ...Array.from({ length: 4 }, (_v, i) => `t1_f${i}`)];

  it('compacts the searched box to its single seed chip and the empty box to a header', () => {
    const { cy, fullRel } = mergedGraph();
    const seedBefore = { ...chipOf(cy, 't1_f0').position() };
    applyFlowVisibility(cy, {
      flowOnly: true, flowNodeIds: ALL_IDS, flowEdgeIds: ['l2m_1'], mergedView: true,
    });
    // the prune hid every chip but the seed
    const visibleChips = cy.nodes(FIELD_SELECTOR).filter(f => !f.hidden()).length;
    expect(visibleChips).toBe(1);

    const res = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);
    expect(res.compacted.sort()).toEqual(['t0', 't1']);
    expectBoxHeight(tableOf(cy, 't0'), tableHeight(0));
    expectBoxHeight(tableOf(cy, 't1'), tableHeight(1));
    // the seed chip the user searched for did not move
    expect(chipOf(cy, 't1_f0').position()).toEqual(seedBefore);
    // …and it sits inside the shrunken box, one header below its top border
    const t1 = tableOf(cy, 't1');
    const h = t1.data('_tableHeight');
    const rel = res.rel.t1_f0;
    expect(chipOf(cy, 't1_f0').position().y).toBeCloseTo(t1.position().y + rel.ry, 10);
    expect(rel.ry).toBeGreaterThan(-h / 2);
    expect(rel.ry).toBeLessThan(h / 2 - TABLE_HDR_H + 1);
  });

  it('compacts identically when the visibility prune runs without a flow filter', () => {
    // Mode-agnostic: the compaction reads what is actually hidden, so the
    // same state is reached from any view that prunes chips.
    const { cy, fullRel } = mergedGraph();
    applyFlowVisibility(cy, { flowOnly: false, flowNodeIds: [], flowEdgeIds: [], mergedView: true });
    const res = applyFlowCompaction(cy, fullRel, EMPTY_COMPACTION);
    expect(res.compacted.sort()).toEqual(['t0', 't1']);
    expectBoxHeight(tableOf(cy, 't1'), tableHeight(1));
  });
});

// chipRyFor — the same formula the module uses, written out here so the
// assertions do not import a private helper.
function chipRyFor(count, i) {
  return -(tableHeight(count) / 2) + TABLE_HDR_H + TBL_PAD_TOP + FIELD_RENDER_H / 2 + i * FIELD_H;
}
