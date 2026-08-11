import { describe, it, expect } from 'vitest';
import { decorateLabelWithLine } from '../labelDecoration';

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
