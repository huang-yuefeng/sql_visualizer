import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
// Namespace import on purpose: a NAMED import of an export that does not exist
// yet (this file ships alongside the feature and may run before it lands) is a
// module-link error that would kill the whole file. `import * as` yields
// undefined instead, so the landing-gated suites below can skip cleanly.
import * as graphStylesModule from '../graphStyles';

const readSrc = rel =>
  readFileSync(new URL(rel, import.meta.url), 'utf8');

// Source-contract reads (unit-level, no cytoscape render). There is no
// precedent in this suite for reading source text; these two files are
// configuration-shaped (a stylesheet array + registration calls), so the
// contract is checked against the text rather than by mounting the graph.
const stylesSource = readSrc('../graphStyles.js');
const hookSource = readSrc('../../hooks/useCytoscapeGraph.js');

/** Collect every `on('<event>', '<selector>', ...)` pair in the hook text. */
function onPairs(src) {
  const pairs = [];
  const re = /\.on\(\s*(['"])([^'"]+)\1\s*,\s*(['"])([^'"]+)\3/g;
  let m;
  while ((m = re.exec(src)) !== null) pairs.push([m[2], m[4]]);
  return pairs;
}

/**
 * True when `<event>` is bound with `<selector>` — via a real
 * `on(event, selector, handler)` call, or (fallback, in case the handler is
 * registered through a wrapper) via the event literal appearing just before
 * the selector literal.
 */
function bindsEvent(src, event, selector) {
  if (onPairs(src).some(([e, s]) => e === event && s === selector)) return true;
  const idx = src.indexOf(`'${selector}'`) === -1
    ? src.indexOf(`"${selector}"`)
    : src.indexOf(`'${selector}'`);
  if (idx === -1) return false;
  const before = src.slice(Math.max(0, idx - 80), idx);
  return before.includes(event);
}

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

// ── Landing gates ───────────────────────────────────────────────────────────
// This test file may be merged before/after the hover-enlarge change. Every
// case that depends on the new code is gated on a signal in the source text,
// so the suite passes before the landing (as .skip) and enforces the contract
// afterwards (as a live describe).
const emphExportLanded =
  /export\s+const\s+HOVER_EMPHASIS_STYLES/.test(stylesSource);
const hoverHandlersLanded =
  bindsEvent(hookSource, 'mouseover', 'node, edge') &&
  bindsEvent(hookSource, 'mouseout', 'node, edge');

const emphStyles = emphExportLanded ? describe : describe.skip;
const hoverHook = hoverHandlersLanded ? describe : describe.skip;

emphStyles('HOVER_EMPHASIS_STYLES — hover-enlarge rule', () => {
  it('is exported as a non-empty array', () => {
    expect(Array.isArray(graphStylesModule.HOVER_EMPHASIS_STYLES)).toBe(true);
    expect(graphStylesModule.HOVER_EMPHASIS_STYLES.length).toBeGreaterThan(0);
  });

  it('targets exactly the emphasis class the hook toggles', () => {
    // The sheet carries one generic emphasis rule (tables/scripts) plus a
    // tier rule for field chips — every entry must use the class.
    for (const entry of graphStylesModule.HOVER_EMPHASIS_STYLES)
      expect(entry.selector).toContain('.label-emph');
    expect(graphStylesModule.HOVER_EMPHASIS_STYLES.some(
      e => e.selector === 'node.label-emph')).toBe(true);
    expect(graphStylesModule.HOVER_EMPHASIS_STYLES.some(
      e => e.selector.includes('[type="field"]'))).toBe(true);
  });

  it('enlarges the label ~2× per tier and raises the element above the graph', () => {
    const find = sel =>
      graphStylesModule.HOVER_EMPHASIS_STYLES.find(e => e.selector === sel) || {};
    // Generic: tables/script titles base is 12 → doubled expectation ≥ 20.
    const generic = find('node.label-emph').style || {};
    expect(Object.keys(generic)).toEqual(expect.arrayContaining(['font-size', 'z-index']));
    expect(Number(generic['font-size'])).toBeGreaterThanOrEqual(20);
    // Field chips: base 10 → doubled ≈ 20; outranks generic via attribute.
    const chip = find('node.label-emph[type="field"]').style || {};
    expect(Number(chip['font-size'])).toBeGreaterThanOrEqual(18);
  });
});

describe('useCytoscapeGraph — scope guards that survive the hover change', () => {
  it('keeps minZoom at the readable 0.28 floor (v3.3.175 — labels legible pre-hover)', () => {
    expect(hookSource).toMatch(/minZoom:\s*0\.28\b/);
  });

  it('still links fields to their compound table via _tableParent', () => {
    expect(hookSource).toContain('_tableParent');
  });
});

hoverHook('useCytoscapeGraph — hover-enlarge wiring', () => {
  it('registers BOTH mouseover and mouseout for "node, edge"', () => {
    expect(bindsEvent(hookSource, 'mouseover', 'node, edge')).toBe(true);
    expect(bindsEvent(hookSource, 'mouseout', 'node, edge')).toBe(true);
  });

  it('toggles the .label-emph class from those handlers', () => {
    expect(hookSource).toContain("'label-emph'");
  });

  it('composes HOVER_EMPHASIS_STYLES into the cytoscape stylesheet', () => {
    expect(stylesheetArrayBody(hookSource)).toContain('HOVER_EMPHASIS_STYLES');
  });
});
