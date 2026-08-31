import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import cytoscape from 'cytoscape';
import { renderHook, act } from '@testing-library/react';
import useCytoscapeGraph, { CY_CORE_OPTIONS } from '../../hooks/useCytoscapeGraph';
import { fitWholeGraph, FIT_ONLY_MIN_ZOOM } from '../../config/layout';

/**
 * FIT-only zoom exception (FTC E2E, user ruling 2026-08-31).
 *
 * The runtime floor (CY_CORE_OPTIONS.minZoom = 0.08) bounds MANUAL zooming.
 * A tall L2 closure needs less than that to be whole on screen, and clamping
 * a fit at 0.08 left 26–121px of the closure overflowing the viewport in 6/9
 * audited cases (tpcds q14 → item.i_brand_id).
 *
 * Contract under test:
 *   1. a plain cy.fit() at the runtime floor overflows a tall graph;
 *   2. fitWholeGraph() puts the WHOLE graph inside the viewport, even though
 *      the zoom it picks is below 0.08;
 *   3. the floor is RESTORED afterwards — a manual zoom below 0.08 is still
 *      clamped, so the exception is fit-only;
 *   4. a fit that does NOT need to go below the floor leaves the zoom
 *      untouched (no gratuitous shrink of an easy graph).
 *
 * Render harness: same posture as selfLoopFilterLabel.test.js — a real
 * cytoscape instance over a jsdom container stubbed to 1400x800.
 */

const VW = 1400;
const VH = 800;
const PAD = 24;

let ctxStub;
let containerEl;

function container() {
  containerEl = document.createElement('div');
  containerEl.getBoundingClientRect = () => ({ left: 0, top: 0, width: VW, height: VH });
  Object.defineProperty(containerEl, 'clientWidth', { value: VW });
  Object.defineProperty(containerEl, 'clientHeight', { value: VH });
  document.body.appendChild(containerEl);
  return containerEl;
}

/** A graph whose laid-out extent is `cols x rows` tables of 200x80 at 400x220
 *  pitch — wide/tall enough that fitting it needs a chosen zoom. */
function makeGrid(cols, rows) {
  const elements = [];
  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      elements.push({
        data: { id: `n${r}_${c}`, type: 'source_table', label: `T${r}_${c}` },
        position: { x: c * 400, y: r * 220 },
      });
    }
  }
  return elements;
}

function makeCy(elements) {
  return cytoscape({
    container: container(),
    layout: { name: 'preset' },
    minZoom: CY_CORE_OPTIONS.minZoom,
    maxZoom: CY_CORE_OPTIONS.maxZoom,
    style: [
      { selector: 'node', style: { width: 200, height: 80, shape: 'roundrectangle' } },
    ],
    elements,
  });
}

/** Overflow in px of the RENDERED graph against the viewport (positive =
 *  content sticks out past the visible area on that axis). Cytoscape's own
 *  renderedBoundingBox is screen-space, so this is exactly what the eye sees. */
function overflow(cy) {
  const rb = cy.elements().renderedBoundingBox();
  return {
    left: Math.round(-rb.x1),
    top: Math.round(-rb.y1),
    right: Math.round(rb.x2 - VW),
    bottom: Math.round(rb.y2 - VH),
  };
}

beforeEach(() => {
  stubCanvas();
});

/** jsdom draws nothing — hand cytoscape a permissive 2D context stub. */
function stubCanvas() {
  const ctx = {
    canvas: { width: VW, height: VH },
    clearRect: () => {},
    save: () => {},
    restore: () => {},
    translate: () => {},
    scale: () => {},
    rotate: () => {},
    beginPath: () => {},
    closePath: () => {},
    moveTo: () => {},
    lineTo: () => {},
    arc: () => {},
    fill: () => {},
    stroke: () => {},
    fillText: () => {},
    measureText: () => ({ width: 10 }),
    setTransform: () => {},
  };
  ctxStub = new Proxy(ctx, {
    get: (t, k) => (k in t ? t[k] : () => 0),
    set: () => true,
  });
  HTMLCanvasElement.prototype.getContext = function () { return ctxStub; };
}

describe('FIT-only zoom exception', () => {
  it('the runtime floor is the manual limit (0.08) and the fit exception is lower', () => {
    expect(CY_CORE_OPTIONS.minZoom).toBe(0.08);
    expect(FIT_ONLY_MIN_ZOOM).toBeLessThan(CY_CORE_OPTIONS.minZoom);
  });

  it('a plain fit at the runtime floor overflows a tall graph (the defect)', () => {
    const cy = makeCy(makeGrid(3, 60)); // tall: ~2860 model px high
    cy.fit(undefined, PAD);
    expect(cy.zoom()).toBeCloseTo(CY_CORE_OPTIONS.minZoom, 5); // bottoms out
    const o = overflow(cy);
    expect(o.bottom).toBeGreaterThan(0); // content sticks out below the fold
    cy.destroy();
  });

  it('fitWholeGraph puts the whole tall graph on screen, below the floor', () => {
    const cy = makeCy(makeGrid(3, 60));
    const z = fitWholeGraph(cy, PAD);
    const o = overflow(cy);
    expect(o.left).toBeLessThanOrEqual(1);
    expect(o.top).toBeLessThanOrEqual(1);
    expect(o.right).toBeLessThanOrEqual(1);
    expect(o.bottom).toBeLessThanOrEqual(1);
    expect(z).toBeLessThan(CY_CORE_OPTIONS.minZoom); // the exception was needed
    cy.destroy();
  });

  it('the floor is restored afterwards: manual zoom still clamps at 0.08', () => {
    const cy = makeCy(makeGrid(3, 60));
    fitWholeGraph(cy, PAD);
    expect(cy.minZoom()).toBe(CY_CORE_OPTIONS.minZoom); // restored
    expect(cy.zoom()).toBeLessThan(CY_CORE_OPTIONS.minZoom); // the fit survives

    // a user wheel/pinch below the floor is clamped back to 0.08
    cy.zoom(0.01);
    expect(cy.zoom()).toBeCloseTo(CY_CORE_OPTIONS.minZoom, 5);
    cy.destroy();
  });

  it('an easy graph fits without going below the floor (no gratuitous shrink)', () => {
    const cy = makeCy(makeGrid(3, 2));
    const z = fitWholeGraph(cy, PAD);
    expect(z).toBeGreaterThanOrEqual(CY_CORE_OPTIONS.minZoom);
    const o = overflow(cy);
    expect(o.bottom).toBeLessThanOrEqual(1);
    cy.destroy();
  });
});

/**
 * The USER-facing fit entry. `useCytoscapeGraph().fit()` is the one function
 * behind the Fit button, the `F` key and the resize auto-fit — for BOTH
 * levels (DataFlowGraph renders L1 and the inline L2 and hands each the same
 * callback), so this is where "the fit may go below the floor, the manual
 * zoom may not" has to hold for L1 as much as for L2. The L2 flow-only
 * branch (fitAllElements) must be under the same lifted floor.
 */
describe('FIT-only zoom exception — the hook fit path (L1 and L2)', () => {
  beforeEach(() => { stubCanvas(); });

  it('fits both levels below the floor and restores the manual floor', () => {
    for (const level of ['L1', 'L2']) {
      const ref = { current: container() }; // stable identity across renders
      const { result, unmount } = renderHook(
        () => useCytoscapeGraph(ref, { nodes: makeGrid(3, 60), edges: [] },
          { level, layoutMode: 'snake' }),
      );
      expect(result.current.cyRef.current).toBeTruthy();
      act(() => { result.current.fit(PAD); });
      const cy = result.current.cyRef.current;

      // the whole graph is on screen at a zoom BELOW the manual floor
      const o = overflow(cy);
      expect(o.left).toBeLessThanOrEqual(1);
      expect(o.top).toBeLessThanOrEqual(1);
      expect(o.right).toBeLessThanOrEqual(1);
      expect(o.bottom).toBeLessThanOrEqual(1);
      expect(cy.zoom()).toBeLessThan(CY_CORE_OPTIONS.minZoom);

      // …and the exception ended with the call: the manual floor is back
      expect(cy.minZoom()).toBe(CY_CORE_OPTIONS.minZoom);
      cy.zoom(0.01);
      expect(cy.zoom()).toBeCloseTo(CY_CORE_OPTIONS.minZoom, 5);
      unmount();
    }
  });

  it('the L2 flow-only branch (fitAllElements) is under the same lifted floor', () => {
    const elements = makeGrid(3, 60);
    const ref = { current: container() };
    const { result, unmount } = renderHook(
      () => useCytoscapeGraph(ref, { nodes: elements, edges: [] },
        { level: 'L2', layoutMode: 'snake',
          flowOnly: true,
          flowNodeIds: elements.map(n => n.data.id),
          flowEdgeIds: [] }),
    );
    act(() => { result.current.fit(PAD); });
    const cy = result.current.cyRef.current;
    expect(cy.zoom()).toBeLessThan(CY_CORE_OPTIONS.minZoom);
    expect(cy.minZoom()).toBe(CY_CORE_OPTIONS.minZoom);
    unmount();
  });
});
