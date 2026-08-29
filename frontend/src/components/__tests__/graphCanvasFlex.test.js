import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

/**
 * AD2-D (2026-08-29) — the L2/L1 graph canvas no longer carries a hard-coded
 * height budget.
 *
 * The chrome above the canvas (toolbar + a legend that wraps) overran the
 * `height: calc(100% - 80px)` the canvas reserved for it, so the canvas
 * overflowed its container and its bottom band was clipped under the SQL
 * panel — 23-45px in every view mode. The container is a flex COLUMN now.
 *
 * A mounted render cannot measure a stylesheet in jsdom, so these are
 * source-contract checks — the same reasoning as nodeClickScroll.test.js.
 */
const readSrc = rel => readFileSync(new URL(rel, import.meta.url), 'utf8');
const css = readSrc('../../styles/app.css');
const graphSrc = readSrc('../../components/DataFlowGraph.jsx');

/** body of `selector { … }` from the stylesheet source (first match).
 *  `selector` is REGEX SOURCE — `\\.` for a literal dot. */
function ruleBody(src, selector) {
  return src.match(new RegExp(`${selector}\\s*\\{([\\s\\S]*?)\\}`))?.[1] || '';
}

describe('AD2-D — graph canvas is the flexible member of a flex column', () => {
  it('the container is a flex column', () => {
    const body = ruleBody(css, '\\.dataflow-graph-container');
    expect(body).toContain('display: flex');
    expect(body).toContain('flex-direction: column');
  });

  it('toolbar and legend are fixed-size rows', () => {
    expect(ruleBody(css, '\\.graph-toolbar')).toContain('flex: 0 0 auto');
    expect(ruleBody(css, '\\.dataflow-legend')).toContain('flex: 0 0 auto');
  });

  it('.graph-canvas flexes and may shrink — no height of its own', () => {
    const body = ruleBody(css, '\\.graph-canvas');
    expect(body).toContain('flex: 1 1 auto');
    expect(body).toContain('min-height: 0');
    // a real height on the flex item would re-introduce the budget this fix
    // removes — `height: auto` (deferring to the flex algorithm) is the only
    // declaration allowed here
    const h = body.match(/(?<![-a-z])height:\s*([^;]+);/);
    expect(!h || h[1].trim() === 'auto').toBe(true);
  });

  it('the canvas element carries no inline height any more', () => {
    // the only `calc(100% - 80px)` left in the file is the comment that
    // documents why it is gone — no style object may carry a height
    expect(graphSrc).not.toMatch(/height:\s*'calc\(/);
    expect(graphSrc).toMatch(/className="graph-canvas" style=\{\{ width: '100%' \}\}/);
  });

  it('cy.resize() runs when the canvas box changes (flex height is not a window resize)', () => {
    const effect = graphSrc.match(/ResizeObserver\(sync\)|new ResizeObserver\(/);
    expect(effect).not.toBeNull();
    // the observer body notifies the core, not just a debounced refit
    expect(graphSrc).toMatch(/cyRef\.current\.resize\(\)/);
  });

  it('the top-slot banner hangs off the MEASURED chrome height, not an 80px guess', () => {
    // the variable has a declared default on both banner hosts …
    expect(css).toMatch(/\.panel-center,\s*\n\.inline-l2-graph\s*\{\s*--graph-chrome-h:/);
    // … and the banner positions itself just below it
    expect(ruleBody(css, '\\.no-match-banner')).toMatch(/top:\s*calc\(var\(--graph-chrome-h/);
    expect(css).not.toMatch(/top:\s*84px/);
    // DataFlowGraph publishes the measured toolbar+legend height onto the host
    expect(graphSrc).toMatch(/--graph-chrome-h/);
    expect(graphSrc).toMatch(/\.panel-center, \.inline-l2-graph/);
  });
});
