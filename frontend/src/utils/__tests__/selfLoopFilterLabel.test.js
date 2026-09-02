import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import cytoscape from 'cytoscape';
// Namespace import on purpose: a NAMED import of an export that does not exist
// yet (this file ships alongside the feature and may run before it lands) is a
// module-link error that would kill the whole file. `import * as` yields
// undefined instead, so the landing-gated suites below can skip cleanly.
import * as graphStylesModule from '../graphStyles';
import { applyFlowVisibility } from '../flowVisibility';
import { CY_CORE_OPTIONS } from '../../hooks/useCytoscapeGraph';

const readSrc = rel =>
  readFileSync(new URL(rel, import.meta.url), 'utf8');

// Source-contract reads (unit-level, no cytoscape render) — same posture as
// hoverEnlarge.test.js: these are configuration-shaped pieces (a stylesheet
// array, its registration call) plus one pure helper, so the contract is
// checked against text / direct calls rather than by mounting the graph.
const stylesSource = readSrc('../graphStyles.js');
const hookSource = readSrc('../../hooks/useCytoscapeGraph.js');
const appSource = readSrc('../../DataFlowApp.jsx');

/** Text between `style: [` and its matching `]`, for composition checks. */
function stylesheetArrayBody(src) {
  const open = src.search(/(?<![\w.])style:\s*\[/);
  if (open === -1) return '';
  let i = src.indexOf('[', open);
  let depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === '[') depth++;
    else if (src[i] === ']') { depth--; if (depth === 0) return src.slice(open, i); }
  }
  return '';
}

/** Text between `cytoscape({` and its matching `})`, for wiring checks. */
function cytoscapeOptionsBody(src) {
  const call = src.search(/(?<![\w.])cytoscape\(\s*\{/);
  if (call === -1) return '';
  const open = src.indexOf('{', call);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) return src.slice(open, i); }
  }
  return '';
}

/**
 * Load the REAL helper once it lands. Full module import is tried first
 * (the honest path — proves the helper is genuinely exported by DataFlowApp);
 * if that namespace has no such export or the module cannot be evaluated in
 * jsdom, fall back to reading the source text and evaluating the extracted
 * function declaration standalone. Returns `{ fn, via }` either way.
 */
async function loadSelfLoopFilterLabels() {
  try {
    const mod = await import('../../DataFlowApp.jsx');
    if (typeof mod.selfLoopFilterLabels === 'function')
      return { fn: mod.selfLoopFilterLabels, via: 'module import' };
  } catch (_e) {
    // Side-effect-heavy component module — fall through to the harness.
  }
  const re = /export\s+function\s+selfLoopFilterLabels/;
  const start = appSource.search(re);
  if (start === -1) throw new Error('selfLoopFilterLabels not found in source');
  let depth = 0;
  let opened = false;
  for (let i = appSource.indexOf('{', start); i < appSource.length; i++) {
    if (appSource[i] === '{') { depth++; opened = true; }
    else if (appSource[i] === '}') {
      depth--;
      if (opened && depth === 0) {
        const decl = appSource.slice(start, i + 1).replace(/^export\s+/, '');
        const fn = new Function(
          `"use strict"; ${decl}; return selfLoopFilterLabels;`
        )();
        return { fn, via: 'new Function source harness' };
      }
    }
  }
  throw new Error('unbalanced braces around selfLoopFilterLabels');
}

// ── EAST5-shaped fixture ────────────────────────────────────────────────────
//
//   east5(T) ── TABLE_FLOW @179 ── ⟐ output O1
//      └── field p_dt ── FILTER @190 ──▶ back into east5 (self-loop)
//      └── field a_field ── REF @205 ──▶ back into east5 (self-loop,
//                                        NOT filter kind)
//   rrcdm(R), ⟐ output O2 ride along so the fixture is not degenerate.
//
// Node/edge shapes mirror the L2 payload: nodes carry `{id, type, parent?,
// label}` (fields: `type: 'field'` + `parent`), edges carry
// `{id, source, target, edge_type, highlight_line}`.
function east5Fixture() {
  const fullNodes = [
    { data: { id: 'T', type: 'source_table', label: 'east5' } },
    { data: { id: 'T.p_dt', type: 'field', parent: 'T', label: 'p_dt' } },
    { data: { id: 'T.a_field', type: 'field', parent: 'T', label: 'a_field' } },
    { data: { id: 'R', type: 'source_table', label: 'rrcdm' } },
    { data: { id: 'O1', type: 'virtual_table', label: '⟐ output@179' } },
    { data: { id: 'O2', type: 'virtual_table', label: '⟐ output@205' } },
  ];
  const closureEdges = [
    // Absorbed self-loop AND filter-kind → the only permitted entry.
    { data: { id: 'E1', source: 'T.p_dt', target: 'T',
              edge_type: 'FILTER', highlight_line: 190 } },
    // Non-self-loop — never labelled even though a table endpoint exists.
    { data: { id: 'E2', source: 'T', target: 'O1',
              edge_type: 'TABLE_FLOW', highlight_line: 179 } },
    // Self-loop after table promotion, but not FILTER → gated out.
    { data: { id: 'E3', source: 'T.a_field', target: 'T',
              edge_type: 'REF', highlight_line: 205 } },
  ];
  return { fullNodes, closureEdges };
}

const labelsOf = v =>
  String(v == null ? '' : v).split(',').map(s => s.trim()).filter(Boolean);

// ── Landing gates ───────────────────────────────────────────────────────────
// This file may be merged before/after the merged-self-loop-label change.
// Every feature-dependent suite is gated on a signal in the source text so it
// passes pre-landing (as .skip) and enforces the contract afterwards.
const helperLanded =
  /export\s+function\s+selfLoopFilterLabels/.test(appSource);
const selfloopStylesLanded =
  /export\s+const\s+FILTER_SELFLOOP_STYLES/.test(stylesSource);
const selfloopHookWiringLanded =
  /FILTER_SELFLOOP_STYLES/.test(hookSource);

const helperSuite = helperLanded ? describe : describe.skip;
const stylesSuite = selfloopStylesLanded ? describe : describe.skip;
const hookWiringSuite = selfloopHookWiringLanded ? describe : describe.skip;

helperSuite('selfLoopFilterLabels — absorbed-filter labelling', () => {
  it('labels the FILTER-kind absorbed self-loop at its own table key', async () => {
    const { fn } = await loadSelfLoopFilterLabels();
    const { fullNodes, closureEdges } = east5Fixture();
    const map = fn(fullNodes, closureEdges);
    expect(map instanceof Map).toBe(true);
    expect(map.has('190|T')).toBe(true);
    expect(labelsOf(map.get('190|T'))).toContain('p_dt');
  });

  it('never labels a non-self-loop edge', async () => {
    const { fn } = await loadSelfLoopFilterLabels();
    const { fullNodes, closureEdges } = east5Fixture();
    const map = fn(fullNodes, closureEdges);
    const keyedOnLine179 = Array.from(map.keys())
      .filter(k => String(k).startsWith('179|'));
    expect(keyedOnLine179).toEqual([]);
  });

  it('gates on FILTER kind — a non-FILTER self-loop stays unlabelled', async () => {
    const { fn } = await loadSelfLoopFilterLabels();
    const { fullNodes, closureEdges } = east5Fixture();
    const map = fn(fullNodes, closureEdges);
    expect(Array.from(map.keys()).filter(k => String(k).startsWith('205|')))
      .toEqual([]);
    for (const v of map.values())
      expect(labelsOf(v)).not.toContain('a_field');
  });
});

stylesSuite('FILTER_SELFLOOP_STYLES / FILTER_CAPTION_STYLES — caption retirement', () => {
  // v3.3.194 (user ruling 2026-08-31): the ⟂ caption is retired. It was
  // painted TWICE — the edge label below the loop AND the v3.3.190 caption
  // node above it, both at the loop midpoint, and neither covered by a node
  // fill any more once the loop grew past the table border. The curve stays;
  // the text goes.
  it('FILTER_SELFLOOP_STYLES renders no label', () => {
    const styles = graphStylesModule.FILTER_SELFLOOP_STYLES;
    expect(Array.isArray(styles)).toBe(true);
    expect(styles).toEqual([]);
  });

  it('FILTER_CAPTION_STYLES styles no caption node', () => {
    const styles = graphStylesModule.FILTER_CAPTION_STYLES;
    expect(Array.isArray(styles)).toBe(true);
    expect(styles).toEqual([]);
  });

  it('no stylesheet rule binds a label to data(filterLabel)', () => {
    expect(stylesSource).not.toMatch(/['"]label['"]\s*:\s*['"]data\(filterLabel\)/);
  });

  it('no stylesheet rule targets a caption node any more', () => {
    expect(stylesSource).not.toMatch(/selector:\s*['"]node\[type=["']caption["']\]/);
  });

  it('the loop geometry rule keeps the curve (bezier + loop properties)', () => {
    const geom = graphStylesModule.FILTER_LOOP_GEOM_STYLES
      .find(r => r.selector === 'edge.filter-selfloop');
    expect(geom).toBeDefined();
    expect(geom.style['curve-style']).toBe('bezier');
    expect(geom.style['control-point-step-size']).toBe('data(loopstep)');
    // v3.3.194: the axis is per-edge data so parallel loops can alternate
    // sides instead of drawing on top of each other.
    expect(geom.style['loop-direction']).toBe('data(loopdir)');
    expect(geom.style['loop-sweep']).toBe('-90deg');
  });

  it('the loop wears the UNIFORM edge style — no special red (ruling 2026-09-02)', () => {
    const geom = graphStylesModule.FILTER_LOOP_GEOM_STYLES
      .find(r => r.selector === 'edge.filter-selfloop');
    expect(geom.style['line-color']).toBe(graphStylesModule.L2_UNIFORM_EDGE_COLOR);
    expect(geom.style['width']).toBe(2);
    // the special story-step red is gone too: the generic story-active
    // rule (width 5 > the loop's 2) is the only emphasis, with no colour
    const story = graphStylesModule.STORY_STYLES;
    expect(story.some(r => (r.selector || '').includes('filter-selfloop'))).toBe(false);
    const composed = JSON.stringify({ geom, story });
    expect(composed).not.toContain('#E74C3C');
    expect(composed).not.toContain('#FF6B6B');
  });

  it('flowVisibility no longer mints caption nodes', () => {
    const visSource = readSrc('../flowVisibility.js');
    expect(visSource).not.toMatch(/upsertFilterCaptions/);
    expect(visSource).not.toMatch(/type:\s*'caption'/);
    expect(visSource).not.toMatch(/'cap_'\s*\+/);
  });
});

hookWiringSuite('useCytoscapeGraph — self-loop wiring survives the retirement', () => {
  it('still composes FILTER_SELFLOOP_STYLES into the cytoscape stylesheet', () => {
    // The spread stays (the export is now empty, so it contributes no rule).
    // Keeping it means a future re-introduction of a loop rule composes in
    // the same, last-wins position instead of silently changing the sheet.
    expect(stylesheetArrayBody(hookSource)).toContain('FILTER_SELFLOOP_STYLES');
  });
});

describe('self-loop CURVE geometry (real cytoscape render pass)', () => {
  // jsdom has no canvas backend, so cytoscape's canvas renderer cannot get a
  // 2d context. A Proxy stub absorbs every context call — enough for the
  // RENDER pass to run, and the render pass is exactly what computes the
  // loop control points this suite measures (`edge.controlPoints()`).
  const ctxStub = new Proxy({}, {
    get: (_t, k) => (k === 'canvas' ? { width: 1400, height: 800 } : () => 0),
    set: () => true,
  });
  HTMLCanvasElement.prototype.getContext = function () { return ctxStub; };

  const container = () => {
    const el = document.createElement('div');
    el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1400, height: 800 });
    Object.defineProperty(el, 'clientWidth', { value: 1400 });
    Object.defineProperty(el, 'clientHeight', { value: 800 });
    return el;
  };

  /**
   * Real merged-view pass over a table box carrying `n` visible self-loops.
   * `neighbours` places ordinary (non-self-loop) traffic beside the table so
   * the border-score rule has something to measure:
   *   { side: 'left'|'right'|'below', label?: boolean, tagged?: boolean }
   * `tagged` on a loop index marks that loop as the absorbed-filter one
   * (`data.filterLabel`).
   */
  function mergedTableWithSelfLoops(n, tableW = 200, { neighbours = [], tagged = -1 } = {}) {
    const elements = [
      { data: { id: 'T', label: 'east5' }, position: { x: 500, y: 500 } },
      ...Array.from({ length: n }, (_v, i) => ({
        data: {
          id: 'e' + i, source: 'T', target: 'T', highlight_line: 100 + i,
          ...(i === tagged ? { filterLabel: '⟂ p_dt (filtered @L190)' } : {}),
        },
      })),
    ];
    neighbours.forEach((nb, i) => {
      const id = 'N' + i;
      // `dist` = centre-to-border gap; 100 puts the box INSIDE the arc band
      // (an actual occluder), 200 keeps it clear of it (edge traffic only).
      const dist = nb.dist ?? 200;
      const x = nb.side === 'left' ? 500 - tableW - dist
        : nb.side === 'right' ? 500 + tableW + dist : 500;
      const y = nb.side === 'below' ? 500 + 300 : 500;
      elements.push({ data: { id, label: 'n' + i }, position: { x, y } });
      // Ordinary traffic into/out of the table — the edge whose endpoint faces
      // the neighbour's side of the box.
      elements.push({ data: { id: 'x' + i, source: nb.side === 'left' ? id : 'T',
        target: nb.side === 'left' ? 'T' : id } });
    });
    const cy = cytoscape({
      container: container(),
      layout: { name: 'preset' },
      style: [
        { selector: 'node', style: { width: tableW, height: 60, shape: 'roundrectangle' } },
        { selector: 'edge', style: { width: 7 } },
        ...graphStylesModule.FILTER_LOOP_GEOM_STYLES,
      ],
      elements,
    });
    applyFlowVisibility(cy, { flowOnly: false, mergedView: true });
    return cy;
  }

  /** Model units the drawn arc reaches past the nearest vertical border. */
  function bulge(cy, id) {
    const e = cy.getElementById(id);
    const left = e.source().position().x - e.source().width() / 2;
    const right = e.source().position().x + e.source().width() / 2;
    const xs = (e.controlPoints() || []).map(p => p.x);
    const ctrlX = Math.min(...xs);
    const side = ctrlX < left ? 'left' : 'right';
    const border = side === 'left' ? left : right;
    // Cubic bezier P0=P3 on the border, P1=P2 at the control x: extreme at
    // u = t(1-t) = 1/4 → 3/4 of the control-point reach is the drawn curve.
    const reach = Math.abs(ctrlX - border) * 0.75;
    return { side, reach };
  }

  it('tags every visible merged self-loop with loopstep + loopdir data', () => {
    const cy = mergedTableWithSelfLoops(2);
    for (const id of ['e0', 'e1']) {
      const d = cy.getElementById(id).data();
      // halfW (100; boundingBox reads the 200-wide box as ~202) + BULGE 150.
      expect(Math.abs(d.loopstep - 250)).toBeLessThanOrEqual(4);
      expect(['-90deg', '90deg']).toContain(d.loopdir);
      expect(cy.getElementById(id).hasClass('filter-selfloop')).toBe(true);
    }
  });

  it('a single loop bulges ~111 model units past its border (measured 110.6 at step 250)', () => {
    const cy = mergedTableWithSelfLoops(1, 200);
    const g = bulge(cy, 'e0');
    expect(g.side).toBe('left');   // the established filter side
    expect(g.reach).toBeGreaterThan(95);
    expect(g.reach).toBeLessThan(130);
  });

  it('two parallel loops alternate sides — never the same arc twice', () => {
    const cy = mergedTableWithSelfLoops(2, 200);
    const a = bulge(cy, 'e0');
    const b = bulge(cy, 'e1');
    expect(a.side).toBe('left');
    expect(b.side).toBe('right');
  });

  it('a third loop returns to the first side and nests larger (cytoscape dirCounts)', () => {
    const cy = mergedTableWithSelfLoops(3, 200);
    expect(bulge(cy, 'e0').side).toBe('left');
    expect(bulge(cy, 'e1').side).toBe('right');
    expect(bulge(cy, 'e2').side).toBe('left');
    expect(bulge(cy, 'e2').reach).toBeGreaterThan(bulge(cy, 'e0').reach);
  });

  // ── border choice (H2 pixel count: a loop behind a neighbour box loses ~7x
  //    of its pixels — 377 vs 2730 — so the labelled loop takes the freer
  //    border; v3.3.195 compares BOTH assignments by summed visibility instead
  //    of forcing the sibling to alternate into an occupied border) ──────────
  it('the labelled loop anchors the EMPTIER border even when it is not the first loop', () => {
    // Two neighbours attaching on the LEFT (their boxes stay outside the arc
    // band, so this is edge traffic — 0.10) → the right border is freer, so
    // the labelled (2nd, @190) loop takes the RIGHT and its sibling keeps off
    // it: dodging 0.10 of traffic is not worth the 0.30 nesting cost.
    const cy = mergedTableWithSelfLoops(2, 200, {
      neighbours: [{ side: 'left' }, { side: 'left' }],
      tagged: 1,
    });
    expect(cy.getElementById('e1').data('filterLabel')).toBeDefined();
    expect(bulge(cy, 'e1').side).toBe('right');   // labelled → freer border
    expect(bulge(cy, 'e0').side).toBe('left');    // sibling on the cheap border
  });

  it('the REGRESSION case: an occupied far border never exiles the sibling loop', () => {
    // The measured east5_stzfxxb shape, on the fixture's coordinates: the
    // labelled loop's own border is free and the OPPOSITE band holds one
    // neighbour box (there: bdm_acc_entrusted_payment, which left the @86 loop
    // 14.3% of its stroke). Alternation would put the sibling behind that box;
    // the assignment optimum keeps both loops on the free border, where
    // cytoscape nests them 62 model units apart instead of hiding one.
    const cy = mergedTableWithSelfLoops(2, 200, {
      neighbours: [{ side: 'right', dist: 100 }],
      tagged: 1,
    });
    expect(bulge(cy, 'e1').side).toBe('left');    // labelled → free border
    expect(bulge(cy, 'e0').side).toBe('left');    // sibling: same free border
  });

  it('keeps Flow-only behavior: an uncluttered single loop stays LEFT (tie → left)', () => {
    const cy = mergedTableWithSelfLoops(1, 200);
    expect(bulge(cy, 'e0').side).toBe('left');
    expect(cy.getElementById('e0').data('loopdir')).toBe('-90deg');
  });

  // ── v3.3.195 assignment optimum (alternation is the fallback, not the rule) ──
  it('the optimum keeps ALTERNATION when both borders cost the same', () => {
    // One light crossing edge per border (0.05 each): sharing would pay the
    // 0.30 nesting cost to dodge a 0.05 one, so the loops still separate.
    const cy = mergedTableWithSelfLoops(2, 200, {
      neighbours: [{ side: 'left' }, { side: 'right' }],
    });
    expect(bulge(cy, 'e0').side).toBe('left');
    expect(bulge(cy, 'e1').side).toBe('right');
  });

  it('two EQUALLY busy borders keep the loops apart (sharing cannot win)', () => {
    // One occluding box per band: separating costs 0.75 + 0.75, sharing 1.5 +
    // 0.30 — the no-share rule survives wherever it is not free.
    const cy = mergedTableWithSelfLoops(2, 200, {
      neighbours: [{ side: 'left', dist: 100 }, { side: 'right', dist: 100 }],
    });
    expect(bulge(cy, 'e0').side).toBe('left');
    expect(bulge(cy, 'e1').side).toBe('right');
  });

  it('when both borders are occluded the loops share the LESSER one', () => {
    // One box in the left band against two in the right: separating strands a
    // loop in the worse band (0.75 + 1.45), sharing keeps both in the better
    // one (2 × 0.75 + 0.30 nesting).
    const cy = mergedTableWithSelfLoops(2, 200, {
      neighbours: [{ side: 'left', dist: 100 },
        { side: 'right', dist: 100 }, { side: 'right', dist: 100 }],
    });
    expect(bulge(cy, 'e0').side).toBe('left');
    expect(bulge(cy, 'e1').side).toBe('left');
    // …and the two same-side arcs still separate by cytoscape's nesting.
    expect(bulge(cy, 'e1').reach).toBeGreaterThan(bulge(cy, 'e0').reach);
  });

  it('a single loop moves to the right border when only the left is occupied', () => {
    const cy = mergedTableWithSelfLoops(1, 200, {
      neighbours: [{ side: 'left' }, { side: 'left' }],
    });
    expect(bulge(cy, 'e0').side).toBe('right');
  });

  it('a neighbour BOX in the arc band outranks edge traffic (nodes paint above edges)', () => {
    // One box sitting INSIDE the left band (dist 100) beats two right-hand
    // edges: nodes paint above edges, so the box is the real occluder.
    const cy = mergedTableWithSelfLoops(1, 200, {
      neighbours: [{ side: 'left', dist: 100 }, { side: 'right' }, { side: 'right' }],
    });
    expect(bulge(cy, 'e0').side).toBe('right');
  });

  it('a vertically aligned neighbour occupies neither border (snake columns)', () => {
    const cy = mergedTableWithSelfLoops(1, 200, { neighbours: [{ side: 'below' }] });
    expect(bulge(cy, 'e0').side).toBe('left');
  });

  it('mints no synthetic caption node (retirement)', () => {
    const cy = mergedTableWithSelfLoops(2, 200);
    expect(cy.nodes().filter(nn => nn.data('type') === 'caption').length).toBe(0);
    expect(cy.nodes().filter(nn => nn.data('synthetic')).length).toBe(0);
  });
});

describe('scope guards that survive the self-loop change', () => {
  it('keeps minZoom at the R41 0.08 floor (overview reachable; labels hide via min-zoomed-font-size)', () => {
    // Runtime assertion (review M21): the option object the hook actually
    // spreads into cytoscape(...), read through the import — and pushed
    // through a REAL headless cytoscape instance so the value is proven
    // to be a live cytoscape option, not just a field on a literal.
    const cy = cytoscape({ headless: true, elements: [], ...CY_CORE_OPTIONS });
    try {
      expect(cy.minZoom()).toBe(0.08);
      expect(cy.maxZoom()).toBe(5);
    } finally {
      cy.destroy();
    }
    // ...and the hook really spreads that object into the cytoscape call
    // (a wiring check by identity — a VALUE change never trips it, only
    // dropping the spread does).
    expect(cytoscapeOptionsBody(hookSource)).toContain('...CY_CORE_OPTIONS');
  });

  it('keeps the annotation client-side — captions derive from client-held payloads', () => {
    // The labelling must be computed IN the browser from the payloads the
    // client already holds, never fetched or ported from the backend pass.
    // Naming `build_line_merged_edges` in a doc comment is fine (that is
    // prose describing which backend rule is being captioned over); what
    // this guard forbids is the module linkage / payload addition itself.
    expect(appSource).toMatch(/export\s+function\s+selfLoopFilterLabels/);
    expect(appSource).not.toMatch(/^\s*import[^\n]*l2_builder\b/m);
    expect(appSource).not.toMatch(/build_line_merged_edges\s*\(/);
  });
});
