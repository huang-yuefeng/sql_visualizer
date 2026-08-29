import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { decorateLabelWithLine } from '../labelDecoration';

const readSrc = rel => readFileSync(new URL(rel, import.meta.url), 'utf8');

// R27 (2026-08-11): "@L{line}" after L2 node names — display-only label
// decoration. The helper appends `@L{line_start}` to the RENDERED label
// (payload labels untouched); the call site (useCytoscapeGraph) passes
// the node's carried line_start. Compounds carry the keeper's
// first-occurrence line — decoration renders exactly that.
describe('decorateLabelWithLine — R27 @L{line} label decoration', () => {
  it('appends @L{line_start} to a plain label (table compounds, ⟐ output VTs)', () => {
    expect(decorateLabelWithLine('output', 160)).toBe('output@L160');
    expect(decorateLabelWithLine('output', 211)).toBe('output@L211');
    expect(decorateLabelWithLine('loan_final', 64)).toBe('loan_final@L64');
  });

  it('never double-appends — backend alias labels already end with @<digits>', () => {
    // `p1@29` is a backend display label; `@L160` is an already-decorated
    // label — both must pass through unchanged.
    expect(decorateLabelWithLine('p1@29', 29)).toBe('p1@29');
    expect(decorateLabelWithLine('output@L160', 160)).toBe('output@L160');
    // Never append to an already-decorated label, even for a different line
    expect(decorateLabelWithLine('p1@29', 42)).toBe('p1@29');
  });

  it('is idempotent across repeats (re-renders, display projections)', () => {
    const once = decorateLabelWithLine('output', 211);
    expect(decorateLabelWithLine(once, 211)).toBe(once);
  });

  it('renders the carried keeper/first-occurrence line for compounds', () => {
    // The compound node carries the KEEPER's line_start in the payload —
    // the caller passes it through, so a compound whose keeper opens at
    // L223 shows `sup@L223` (per-occurrence lines stay on the edges).
    expect(decorateLabelWithLine('sup', 223)).toBe('sup@L223');
  });

  it('passes through unchanged when line_start is missing or invalid — the renderer never guesses', () => {
    expect(decorateLabelWithLine('output', undefined)).toBe('output');
    expect(decorateLabelWithLine('output', 0)).toBe('output');
    expect(decorateLabelWithLine('output', -1)).toBe('output');
    expect(decorateLabelWithLine('output', 3.5)).toBe('output');
    expect(decorateLabelWithLine('output', NaN)).toBe('output');
    expect(decorateLabelWithLine('output', null)).toBe('output');
  });

  it('is defensive on non-string labels', () => {
    expect(decorateLabelWithLine('', 160)).toBe('');
    expect(decorateLabelWithLine(undefined, 160)).toBe(undefined);
    expect(decorateLabelWithLine(null, 160)).toBe(null);
  });
});

// F-B2 (K4 Ruling 1 companion, 2026-08-29): field chips must NEVER take the
// @L decoration. F-B1 puts a valid `line_start` on every chip, so the
// decoration pass — which appends to every L2 node with a valid line — would
// otherwise render `lending_ref@L22` on all of them. The suppression is a
// CALL-SITE rule (the helper is a pure label function and must stay one), so
// this is a source contract on the hook's decoration loop, same reasoning as
// nodeClickScroll.test.js.
describe('F-B2 — field chips are excluded from the @L decoration', () => {
  const hookSrc = readSrc('../../hooks/useCytoscapeGraph.js');

  it('the hook returns early for field-type nodes, before the decorate call', () => {
    const loop = hookSrc.match(/if \(isL2\) \{\s*cy\.nodes\(\)\.forEach\(n => \{[\s\S]*?decorateLabelWithLine[\s\S]*?\}\);\s*\}/)?.[0] || '';
    expect(loop).not.toBe('');
    const guardAt = loop.indexOf("d.type === 'field'");
    const decorateAt = loop.indexOf('decorateLabelWithLine(');
    expect(guardAt).toBeGreaterThan(-1);
    expect(decorateAt).toBeGreaterThan(guardAt);
  });

  it('chips carry `type: "field"` in the payload (the guarded key is the real one)', () => {
    // The guard must key on the field the payload actually uses — the same
    // key every other chip-aware consumer reads (flowVisibility
    // hideEdgelessFieldChips, DataFlowApp.selfLoopFilterLabels,
    // collectPositions).
    expect(hookSrc).toMatch(/n\.data\('type'\) === 'field'/);
    expect(hookSrc).toMatch(/if \(d\.type === 'field'\) return;/);
  });

  it('documents why the call-site guard is required: a chip line WOULD decorate', () => {
    // A field chip with a valid line_start is indistinguishable from a table
    // compound as far as the pure helper goes — so without the hook guard the
    // chip label would come out decorated.
    expect(decorateLabelWithLine('lending_ref', 22)).toBe('lending_ref@L22');
  });
});

