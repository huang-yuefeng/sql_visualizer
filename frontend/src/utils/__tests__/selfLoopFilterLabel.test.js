import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
// Namespace import on purpose: a NAMED import of an export that does not exist
// yet (this file ships alongside the feature and may run before it lands) is a
// module-link error that would kill the whole file. `import * as` yields
// undefined instead, so the landing-gated suites below can skip cleanly.
import * as graphStylesModule from '../graphStyles';

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

stylesSuite('FILTER_SELFLOOP_STYLES — self-loop filter-label rule', () => {
  const styles = graphStylesModule.FILTER_SELFLOOP_STYLES;

  it('is exported as a non-empty array', () => {
    expect(Array.isArray(styles)).toBe(true);
    expect(styles.length).toBeGreaterThan(0);
  });

  it('targets the decorated edges via the filterLabel attribute', () => {
    expect(styles.some(e => e.selector === 'edge[filterLabel]')).toBe(true);
  });

  it('binds label to data(filterLabel) and keeps it readable', () => {
    const entry = styles.find(e => e.selector === 'edge[filterLabel]');
    const style = (entry && entry.style) || {};
    const bound = Object.entries(style)
      .find(([k]) => /^label$/i.test(k));
    expect(bound).toBeDefined();
    // Case-insensitive: cytoscape style maps are lowercase-keyed here, while
    // the payload attribute is camelCased.
    expect(String(bound[1]).toLowerCase()).toBe('data(filterlabel)');
    const size = Object.entries(style)
      .find(([k]) => /^font-size$/i.test(k));
    expect(size).toBeDefined();
    expect(Number(size[1])).toBeGreaterThan(0);
  });
});

hookWiringSuite('useCytoscapeGraph — self-loop label wiring', () => {
  it('composes FILTER_SELFLOOP_STYLES into the cytoscape stylesheet', () => {
    expect(stylesheetArrayBody(hookSource)).toContain('FILTER_SELFLOOP_STYLES');
  });
});

describe('scope guards that survive the self-loop change', () => {
  it('keeps minZoom at the readable 0.28 floor', () => {
    expect(hookSource).toMatch(/minZoom:\s*0\.28\b/);
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
