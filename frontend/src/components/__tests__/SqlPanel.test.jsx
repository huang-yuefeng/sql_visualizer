import { createRef } from 'react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import SqlPanel from '../SqlPanel';

const SQL = 'SELECT a FROM t1\nWHERE b = 1\n  AND c = 2';

describe('SqlPanel — R25 single-line edge highlight', () => {
  beforeEach(() => {
    // jsdom has no layout and no Element.scrollTo — hand it a spy.
    Element.prototype.scrollTo = vi.fn();
    // TRIPWIRE: scrollIntoView is the ancestor-scrolling primitive the panel
    // must never use again (it is how the header left the slot).
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('renders one line per SQL line with data-line attributes', () => {
    const { container } = render(<SqlPanel sqlText={SQL} scriptName="s.sql" />);
    expect(screen.getByText('SELECT a FROM t1')).toBeInTheDocument();
    expect(container.querySelectorAll('.sql-line').length).toBe(3);
    expect(container.querySelector('[data-line="2"]').textContent).toContain('WHERE b = 1');
  });

  it('highlights EXACTLY the anchor line when sqlHighlightLine is set', () => {
    const { container } = render(<SqlPanel sqlText={SQL} scriptName="s.sql" sqlHighlightLine={2} />);
    const highlighted = container.querySelectorAll('.edge-highlighted');
    expect(highlighted.length).toBe(1);
    expect(highlighted[0].getAttribute('data-line')).toBe('2');
    // neighbours stay un-highlighted
    expect(container.querySelector('[data-line="1"]').classList.contains('edge-highlighted')).toBe(false);
    expect(container.querySelector('[data-line="3"]').classList.contains('edge-highlighted')).toBe(false);
  });

  it('highlights the last line and scrolls to it', () => {
    const { container } = render(<SqlPanel sqlText={SQL} scriptName="s.sql" sqlHighlightLine={3} />);
    expect(container.querySelectorAll('.edge-highlighted').length).toBe(1);
    expect(container.querySelector('.edge-highlighted').getAttribute('data-line')).toBe('3');
    expect(Element.prototype.scrollTo).toHaveBeenCalledTimes(1);
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled(); // never an ancestor scroll
  });

  it('ignores invalid highlight lines (missing / 0 / negative)', () => {
    const { container: c1 } = render(<SqlPanel sqlText={SQL} scriptName="s.sql" />);
    expect(c1.querySelectorAll('.edge-highlighted').length).toBe(0);
    const { container: c2 } = render(<SqlPanel sqlText={SQL} scriptName="s.sql" sqlHighlightLine={0} />);
    expect(c2.querySelectorAll('.edge-highlighted').length).toBe(0);
    const { container: c3 } = render(<SqlPanel sqlText={SQL} scriptName="s.sql" sqlHighlightLine={-4} />);
    expect(c3.querySelectorAll('.edge-highlighted').length).toBe(0);
  });

  it('no longer accepts the removed highlights prop (R25 — no field-level layer)', () => {
    // The old response-level `highlights` array is gone from the API; the
    // prop must not be part of the component surface anymore.
    const { container } = render(<SqlPanel sqlText={SQL} scriptName="s.sql" highlights={[[1, 2]]} />);
    expect(container.querySelectorAll('.highlighted').length).toBe(0);
  });
});

describe('SqlPanel — R11-3 scrollToLine imperative API', () => {
  beforeEach(() => {
    Element.prototype.scrollTo = vi.fn();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('scrollToLine scrolls the requested line into view', () => {
    const ref = createRef();
    render(<SqlPanel ref={ref} sqlText={SQL} scriptName="s.sql" />);
    ref.current.scrollToLine(2);
    expect(Element.prototype.scrollTo).toHaveBeenCalledTimes(1);
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it('scrollToLine tolerates missing and out-of-range lines', () => {
    const ref = createRef();
    render(<SqlPanel ref={ref} sqlText={SQL} scriptName="s.sql" />);
    expect(() => ref.current.scrollToLine(99)).not.toThrow();
    expect(() => ref.current.scrollToLine(0)).not.toThrow();
    expect(() => ref.current.scrollToLine(-3)).not.toThrow();
    expect(() => ref.current.scrollToLine(null)).not.toThrow();
    expect(Element.prototype.scrollTo).not.toHaveBeenCalled();
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });
});

// ── R40.13 — the naive string-match diff layer ─────────────────────────────
// Three coexisting channels: the R25/R37 engine highlight (amber LEFT border),
// the string-match band (green/red, RIGHT border) and the browse cursor
// (outline). Absent props render nothing extra — byte-compatible with the
// pre-R40.13 DOM.
describe('SqlPanel — R40.13 string-match diff layer', () => {
  beforeEach(() => {
    Element.prototype.scrollTo = vi.fn();
    Element.prototype.scrollIntoView = vi.fn();
  });
  const SQL12 = 'a\np_dt\nb\np_dt2\nc\np_dt\nd'; // 7 lines, matches at 2 and 6

  const line = (container, n) => container.querySelector(`[data-line="${n}"]`);
  const classes = (el) => (el ? el.className.split(/\s+/) : []);

  it('bands a covered line green and a missed line red', () => {
    const { container } = render(
      <SqlPanel sqlText={SQL12} scriptName="s.sql"
        stringMatchCovered={new Set([2])}
        stringMatchMissed={new Set([6])} />,
    );
    expect(classes(line(container, 2))).toEqual(expect.arrayContaining(['string-match', 'covered']));
    expect(classes(line(container, 6))).toEqual(expect.arrayContaining(['string-match', 'missed']));
    // a line in NEITHER set carries no band
    expect(classes(line(container, 1))).not.toContain('string-match');
    expect(classes(line(container, 4))).not.toContain('string-match');
  });

  it('keeps the engine channel untouched and coexisting on a shared line', () => {
    // The L41/L190 shape: the engine anchors a line the naive layer also
    // bands — BOTH class sets land on that one element.
    const { container } = render(
      <SqlPanel sqlText={SQL12} scriptName="s.sql" sqlHighlightLine={2}
        stringMatchCovered={new Set([2])}
        stringMatchMissed={new Set([6])} />,
    );
    expect(classes(line(container, 2)))
      .toEqual(expect.arrayContaining(['edge-highlighted', 'string-match', 'covered']));
    // the engine channel alone still renders exactly as before
    expect(container.querySelectorAll('.edge-highlighted')).toHaveLength(1);
    expect(classes(line(container, 6))).not.toContain('edge-highlighted');
  });

  it('marks EXACTLY ONE line as the active match', () => {
    const { container } = render(
      <SqlPanel sqlText={SQL12} scriptName="s.sql"
        stringMatchCovered={new Set([2])}
        stringMatchMissed={new Set([6])}
        stringMatchActiveLine={6} />,
    );
    expect(container.querySelectorAll('.string-match-active')).toHaveLength(1);
    expect(line(container, 6).classList.contains('string-match-active')).toBe(true);
  });

  it('scrolls to the active line WITHOUT moving the engine highlight', () => {
    // The engine channel is the ONLY scroll source at first (the cursor is
    // still inactive).
    const { container, rerender } = render(
      <SqlPanel sqlText={SQL12} scriptName="s.sql" sqlHighlightLine={2}
        stringMatchCovered={new Set([2])}
        stringMatchMissed={new Set([6])} />,
    );
    expect(Element.prototype.scrollTo).toHaveBeenCalledTimes(1);
    expect(container.querySelectorAll('.edge-highlighted')).toHaveLength(1);
    expect(container.querySelectorAll('.edge-highlighted')[0].getAttribute('data-line')).toBe('2');

    // the cursor activates, then moves → the panel scrolls again each time,
    // and the engine's amber line never follows it
    rerender(<SqlPanel sqlText={SQL12} scriptName="s.sql" sqlHighlightLine={2}
      stringMatchCovered={new Set([2])}
      stringMatchMissed={new Set([6])}
      stringMatchActiveLine={2} />);
    expect(Element.prototype.scrollTo).toHaveBeenCalledTimes(2);

    rerender(<SqlPanel sqlText={SQL12} scriptName="s.sql" sqlHighlightLine={2}
      stringMatchCovered={new Set([2])}
      stringMatchMissed={new Set([6])}
      stringMatchActiveLine={6} />);
    expect(Element.prototype.scrollTo).toHaveBeenCalledTimes(3);
    expect(container.querySelectorAll('.edge-highlighted')).toHaveLength(1);
    expect(container.querySelectorAll('.edge-highlighted')[0].getAttribute('data-line')).toBe('2');
    expect(container.querySelectorAll('.string-match-active')[0].getAttribute('data-line')).toBe('6');
  });

  it('ignores invalid active lines (0 / negative / non-integer)', () => {
    for (const bad of [0, -4, 1.5, null, undefined]) {
      const { container } = render(
        <SqlPanel sqlText={SQL12} scriptName="s.sql" stringMatchActiveLine={bad} />);
      expect(container.querySelectorAll('.string-match-active')).toHaveLength(0);
    }
    // scrolling never fires for an invalid line
    expect(Element.prototype.scrollTo).not.toHaveBeenCalled();
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it('renders nothing extra when the props are absent or empty (backwards compat)', () => {
    const { container } = render(<SqlPanel sqlText={SQL} scriptName="s.sql" />);
    expect(container.querySelectorAll('.string-match').length).toBe(0);
    expect(container.querySelectorAll('.string-match-active').length).toBe(0);

    const { container: c2 } = render(
      <SqlPanel sqlText={SQL} scriptName="s.sql"
        stringMatchCovered={new Set()} stringMatchMissed={new Set()} />,
    );
    expect(c2.querySelectorAll('.string-match').length).toBe(0);
  });

  it('leaves the .line-text DOM as a plain string (no per-token markup)', () => {
    const { container } = render(
      <SqlPanel sqlText={SQL12} scriptName="s.sql"
        stringMatchCovered={new Set([2])} stringMatchMissed={new Set([6])} />,
    );
    expect(line(container, 2).querySelector('.line-text').textContent).toBe('p_dt');
    expect(line(container, 2).querySelectorAll('span')).toHaveLength(2); // num + text
    expect(line(container, 4).querySelector('.line-text').textContent).toBe('p_dt2');
  });
});

/**
 * FTC E2E (v3.3.194) — the SQL panel's HEADER (Export / Config / status) used
 * to scroll out of the slot: `.inline-l2-sql` was the scroller, so scrolling
 * to a late highlighted line pushed the whole panel (header included) up and
 * away. The contract now is: only the LINE LIST scrolls, the header is pinned.
 *
 * jsdom does no layout, so the scrolling behaviour is pinned by two honest
 * proxies: the DOM shape (header and scroller are SIBLINGS, the header is
 * outside the scrolling box) and the stylesheet contract (the slot does not
 * scroll; the body is the scroller; the header cannot shrink) — the same
 * configuration-shaped posture selfLoopFilterLabel.test.js documents.
 */
describe('SqlPanel — the header stays reachable on a late-line highlight', () => {
  const css = readFileSync(resolve(process.cwd(), 'src/styles/app.css'), 'utf8');

  /** Body of a CSS rule: `.selector { … }` (last match wins, like the cascade). */
  function ruleBody(selector) {
    // FIRST match: .sql-panel-header is declared twice (base rule + a later
    // padding tweak) and the flex-shrink lives in the base rule, which the
    // cascade keeps applying.
    const idx = css.indexOf(selector + ' {');
    if (idx === -1) return '';
    const open = css.indexOf('{', idx);
    let depth = 0, end = open;
    for (; end < css.length; end += 1) {
      if (css[end] === '{') depth += 1;
      else if (css[end] === '}') { depth -= 1; if (depth === 0) break; }
    }
    return css.slice(open, end);
  }

  it('keeps the header OUTSIDE the scrolling box (siblings, not ancestor)', () => {
    const { container } = render(<SqlPanel sqlText={SQL} scriptName="s.sql" sqlHighlightLine={3} />);
    const header = container.querySelector('.sql-panel-header');
    const lines = container.querySelector('.sql-content');
    expect(header).not.toBeNull();
    expect(lines).not.toBeNull();
    // siblings under .sql-panel — the header is not wrapped in the scroller
    expect(header.parentElement).toBe(lines.parentElement);
    expect(header.contains(lines)).toBe(false);
    expect(lines.contains(header)).toBe(false);
  });

  it('the slot never scrolls; the line list is the only scroller; the header cannot shrink', () => {
    const slot = ruleBody('.inline-l2-sql');
    expect(slot).toContain('overflow: hidden');
    expect(slot).not.toContain('overflow-y: auto');
    expect(slot).toContain('flex-direction: column');

    const panel = ruleBody('.inline-l2-sql .sql-panel');
    expect(panel).toContain('height: 100%');
    expect(panel).toContain('max-height: none');

    const list = ruleBody('.inline-l2-sql .sql-content');
    expect(list).toContain('flex: 1 1 auto');
    expect(list).toContain('min-height: 0');
    expect(list).toContain('overflow-y: auto');

    expect(ruleBody('.sql-panel-header')).toContain('flex-shrink: 0');
  });

  it('a highlight near the script end still renders the Export/Config header', () => {
    const long = Array.from({ length: 400 }, (_, i) => `-- line ${i + 1}`).join('\n');
    const { container } = render(
      <SqlPanel sqlText={long} scriptName="q14.sql" sqlHighlightLine={400} />,
    );
    expect(screen.getByText(/Export/)).toBeInTheDocument();
    expect(screen.getByText(/Config/)).toBeInTheDocument();
    expect(container.querySelector('[data-line="400"]')).not.toBeNull();
  });

  // The behavioural half of the pin: the scroll WRITE lands on the line list
  // and on nothing above it. `scrollIntoView()` (the previous implementation)
  // would also move an `overflow: hidden` ancestor — browsers scroll those
  // programmatically — which is exactly how the header left the slot.
  it('centers the line with a scrollTop write on the LINE LIST, never an ancestor', () => {
    const ref = createRef();
    const long = Array.from({ length: 400 }, (_, i) => `-- line ${i + 1}`).join('\n');
    const { container } = render(
      // the real slot: an overflow:hidden scroll container around the panel
      <div className="inline-l2-sql">
        <SqlPanel ref={ref} sqlText={long} scriptName="q14.sql" />
      </div>,
    );
    const slot = container.querySelector('.inline-l2-sql');
    const panel = container.querySelector('.sql-panel');
    const list = container.querySelector('.sql-content');
    const last = container.querySelector('[data-line="400"]');

    // jsdom does no layout — hand the scroller and the target line a geometry:
    // a 250px-tall list whose content starts 100px down the page, 400 lines
    // of 18px each.
    const LINE_H = 18;
    const VIEW = 250;
    Object.defineProperty(list, 'clientHeight', { value: VIEW, configurable: true });
    list.getBoundingClientRect = () => ({ top: 100, height: VIEW });
    last.getBoundingClientRect = () => ({ top: 100 + 399 * LINE_H, height: LINE_H });
    slot.getBoundingClientRect = () => ({ top: 50, height: 400 });
    panel.getBoundingClientRect = () => ({ top: 50, height: 400 });

    ref.current.scrollToLine(400);

    // the line is centred: its top-in-content minus half the leftover space
    expect(Element.prototype.scrollTo).toHaveBeenCalledWith({
      top: 399 * LINE_H - (VIEW - LINE_H) / 2, behavior: 'smooth',
    });
    // no ancestor moved a pixel — the header cannot leave the slot
    expect(slot.scrollTop).toBe(0);
    expect(panel.scrollTop).toBe(0);
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it('never scrolls above line 1 (the clamp), and centres an early line at 0', () => {
    const ref = createRef();
    const { container } = render(
      <div className="inline-l2-sql"><SqlPanel ref={ref} sqlText={SQL} scriptName="s.sql" /></div>,
    );
    const list = container.querySelector('.sql-content');
    Object.defineProperty(list, 'clientHeight', { value: 250, configurable: true });
    list.getBoundingClientRect = () => ({ top: 0, height: 250 });
    container.querySelector('[data-line="1"]').getBoundingClientRect = () =>
      ({ top: 0, height: 18 });
    ref.current.scrollToLine(1);
    expect(Element.prototype.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
  });
});
