import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// ── Landing gate ────────────────────────────────────────────────────────────
// Team B ships src/components/FieldStoryBar.jsx alongside this suite; it may
// not exist when this file first runs. Gated the same way as
// fieldStory.test.js / selfLoopFilterLabel.test.js (source read + dynamic
// import) so the suite skips cleanly pre-landing and enforces the contract
// afterwards.
// v3.3.188: cwd-based read — see fieldStory.test.js for why the
// import.meta.url URL form does not work under this vitest install.
const BAR_URL = resolve(process.cwd(), 'src/components/FieldStoryBar.jsx');
const barSrc = existsSync(BAR_URL) ? readFileSync(BAR_URL, 'utf8') : '';
const barLanded = barSrc !== '' && /FieldStoryBar/.test(barSrc);
const barSuite = barLanded ? describe : describe.skip;

async function loadFieldStoryBar() {
  const mod = await import('../../components/FieldStoryBar.jsx');
  const C = mod.default || mod.FieldStoryBar;
  if (!C) throw new Error('FieldStoryBar.jsx landed without a default/named export');
  return C;
}

// Four fake steps, deliberately digit-free in title/detail so the chip-number
// matcher below can never collide with stray digits inside prose.
const STEPS = [
  { id: 's1', kind: 'birth', title: 'Born', line: 41, edgeIds: ['e1', 'e2'],
    nodeIds: ['east5.p_dt'], detail: 'INSERT INTO east5' },
  { id: 's2', kind: 'written', title: 'Written', line: 41, edgeIds: ['e3'],
    nodeIds: ['east5'], detail: 'output@41 writes east5' },
  { id: 's3', kind: 'read', title: 'Read downstream', line: 189, edgeIds: ['e4'],
    nodeIds: ['out179'], detail: 'east5 feeds the chain' },
  { id: 's4', kind: 'filtered', title: 'Filtered', line: 190, edgeIds: ['e7'],
    nodeIds: ['east5'], detail: 'WHERE p_dt' },
];

const textOf = el => String((el && el.textContent) || '').trim();
const clickable = c => [...c.querySelectorAll('button, [role="button"], [class*="chip"]')];

// Chip number n = the clickable element whose text contains n as a standalone
// number token ("1", "Step 1", "1 · Born" all match; "41" does not match 1/4).
const numToken = n => new RegExp(`(^|[^0-9])${n}([^0-9]|$)`);
function chipByNumber(container, n) {
  return clickable(container).filter(el => numToken(n).test(textOf(el)));
}

// Active = aria-current (any value) or a class containing "active".
const isActive = el =>
  (el.getAttribute && el.getAttribute('aria-current')) != null
  || /active/i.test(String(el.className || ''));

// Arrow/toggle buttons: matched by glyph text OR aria-label, so either
// implementation style satisfies the contract. The autoplay toggle is only
// probed in autoplay renders, where it shows ⏸ and cannot collide with the
// ▶ next button.
function buttonBy(container, { glyph, labelRe }) {
  return clickable(container).find(el =>
    textOf(el).includes(glyph)
    || labelRe.test((el.getAttribute && el.getAttribute('aria-label')) || ''));
}

const PROPS = extra => ({
  steps: STEPS,
  activeIndex: 0,
  onStep: vi.fn(),
  onPrev: vi.fn(),
  onNext: vi.fn(),
  autoplay: false,
  onToggleAutoplay: vi.fn(),
  ...extra,
});

barSuite('FieldStoryBar — step-chip navigation bar', () => {
  it('renders one numbered chip per step (1..N)', async () => {
    const FieldStoryBar = await loadFieldStoryBar();
    const { container } = render(<FieldStoryBar {...PROPS()} />);

    [1, 2, 3, 4].forEach(n => {
      const matches = chipByNumber(container, n);
      expect(matches).toHaveLength(1); // exactly one chip per step number
    });
  });

  it('distinguishes the active chip (aria-current or active class)', async () => {
    const FieldStoryBar = await loadFieldStoryBar();
    const { container, rerender } = render(
      <FieldStoryBar {...PROPS({ activeIndex: 1 })} />);

    const chips = [1, 2, 3, 4].map(n => chipByNumber(container, n)[0]);
    const activeChips = chips.filter(isActive);
    expect(activeChips).toHaveLength(1);   // exactly one active chip
    expect(isActive(chips[1])).toBe(true); // …and it is step 2 (activeIndex 1)
    expect(isActive(chips[0])).toBe(false);

    // The active chip FOLLOWS the prop — rerender moves the marker.
    rerender(<FieldStoryBar {...PROPS({ activeIndex: 3 })} />);
    const chipsAfter = [1, 2, 3, 4].map(n => chipByNumber(container, n)[0]);
    expect(chipsAfter.filter(isActive)).toHaveLength(1);
    expect(isActive(chipsAfter[3])).toBe(true);
    expect(isActive(chipsAfter[1])).toBe(false);
  });

  it('fires onStep when a chip is clicked', async () => {
    const FieldStoryBar = await loadFieldStoryBar();
    const onStep = vi.fn();
    const { container } = render(<FieldStoryBar {...PROPS({ onStep })} />);

    fireEvent.click(chipByNumber(container, 3)[0]);

    expect(onStep).toHaveBeenCalledTimes(1);
    // Chip 3 → 0-based index 2 somewhere in the args (covers both
    // onStep(2) and onStep(step, 2) call shapes).
    expect(onStep.mock.calls[0]).toContain(2);
  });

  it('fires onPrev/onNext from the ◀ ▶ buttons', async () => {
    const FieldStoryBar = await loadFieldStoryBar();
    const onPrev = vi.fn();
    const onNext = vi.fn();
    // autoplay=true → the toggle shows ⏸, so ▶ can only be the NEXT
    // button. activeIndex=1 keeps ◀ ENABLED (B's bar disables it at
    // index 0/null — correct UX) and ▶ enabled (not the last step).
    const { container } = render(
      <FieldStoryBar {...PROPS({ autoplay: true, activeIndex: 1, onPrev, onNext })} />);

    const prev = buttonBy(container, { glyph: '◀', labelRe: /prev|backward/i });
    const next = buttonBy(container, { glyph: '▶', labelRe: /next|forward/i });
    expect(prev).toBeTruthy();
    expect(next).toBeTruthy();

    fireEvent.click(prev);
    expect(onPrev).toHaveBeenCalledTimes(1);
    expect(onNext).not.toHaveBeenCalled();

    fireEvent.click(next);
    expect(onNext).toHaveBeenCalledTimes(1);
    expect(onPrev).toHaveBeenCalledTimes(1); // still just the one prev click
  });

  it('fires onToggleAutoplay from the ▶/⏸ autoplay toggle', async () => {
    const FieldStoryBar = await loadFieldStoryBar();
    const onToggleAutoplay = vi.fn();
    const onPrev = vi.fn();
    const onNext = vi.fn();
    const onStep = vi.fn();
    const { container } = render(
      <FieldStoryBar {...PROPS({ autoplay: true, onToggleAutoplay, onPrev, onNext, onStep })} />);

    // autoplay=true → the toggle is the ⏸ button.
    const toggle = buttonBy(container, { glyph: '⏸', labelRe: /pause|play|autoplay/i });
    expect(toggle).toBeTruthy();

    fireEvent.click(toggle);
    expect(onToggleAutoplay).toHaveBeenCalledTimes(1);
    // The toggle is its own control — no navigation side effects.
    expect(onPrev).not.toHaveBeenCalled();
    expect(onNext).not.toHaveBeenCalled();
    expect(onStep).not.toHaveBeenCalled();
  });
});
