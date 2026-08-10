import { createRef } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import SqlPanel from '../SqlPanel';

const SQL = 'SELECT a FROM t1\nWHERE b = 1\n  AND c = 2';

describe('SqlPanel — R25 single-line edge highlight', () => {
  beforeEach(() => {
    // jsdom has no layout — scrollIntoView is not implemented
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
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
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
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('scrollToLine scrolls the requested line into view', () => {
    const ref = createRef();
    render(<SqlPanel ref={ref} sqlText={SQL} scriptName="s.sql" />);
    ref.current.scrollToLine(2);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it('scrollToLine tolerates missing and out-of-range lines', () => {
    const ref = createRef();
    render(<SqlPanel ref={ref} sqlText={SQL} scriptName="s.sql" />);
    expect(() => ref.current.scrollToLine(99)).not.toThrow();
    expect(() => ref.current.scrollToLine(0)).not.toThrow();
    expect(() => ref.current.scrollToLine(-3)).not.toThrow();
    expect(() => ref.current.scrollToLine(null)).not.toThrow();
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });
});
