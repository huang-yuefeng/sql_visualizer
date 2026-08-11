import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import EdgeReasonPanel from '../EdgeReasonPanel';

const edge = {
  id: 'e1',
  edge_type: 'TABLE_FLOW',
  flow_kind: 'chain',
  highlight_line: 43,
  reason: 'chain — bdm_acc_loan_info.data_dt@L18 → ‖p1@L29 → p1.data_dt@L43‖ → ⟐subq@L0',
  color: '#2ECC71',
};

describe('EdgeReasonPanel — R25/§8.8 (below the SQL panel)', () => {
  it('renders the empty state when no edge is selected', () => {
    render(<EdgeReasonPanel edge={null} />);
    expect(screen.getByText('Flow Reason')).toBeInTheDocument();
    expect(screen.getByText(/Click an edge to see its flow reason/)).toBeInTheDocument();
  });

  it('shows flow kind, anchor line, and the reason string', () => {
    render(<EdgeReasonPanel edge={edge} />);
    // (a) flow kind
    expect(screen.getByText('chain')).toBeInTheDocument();
    // (b) anchor line
    expect(screen.getByText('Anchor: L43')).toBeInTheDocument();
    // (c) reason string — full path, rendered as-is from extraction time
    expect(screen.getByText(/bdm_acc_loan_info\.data_dt@L18/)).toBeInTheDocument();
    expect(screen.getByText(/⟐subq@L0/)).toBeInTheDocument();
  });

  it('emphasizes the ‖…‖-wrapped current-edge segment (bold + edge color)', () => {
    const { container } = render(<EdgeReasonPanel edge={edge} />);
    const seg = container.querySelector('.edge-reason-segment');
    expect(seg).not.toBeNull();
    // The wrapper characters are stripped; the segment text is exact.
    expect(seg.textContent).toBe('p1@L29 → p1.data_dt@L43');
    expect(seg.textContent).not.toContain('‖');
    expect(seg.style.color).toBe('rgb(46, 204, 113)'); // #2ECC71 — edge category color
    // Everything outside the ‖…‖ segment stays un-emphasized
    const emphasized = container.querySelectorAll('.edge-reason-segment');
    expect(emphasized.length).toBe(1);
  });

  it('tolerates a reason string without a ‖…‖ segment (defensive)', () => {
    render(<EdgeReasonPanel edge={{ id: 'x', flow_kind: 'bridge', highlight_line: 7, reason: 'bridge — sup@L223 → rrcdm@L211', color: '#7F8C8D' }} />);
    expect(screen.getByText('bridge')).toBeInTheDocument();
    expect(screen.getByText('Anchor: L7')).toBeInTheDocument();
    expect(screen.getByText(/sup@L223 → rrcdm@L211/)).toBeInTheDocument();
    expect(screen.queryByText('—')).not.toBeInTheDocument();
  });

  it('falls back to a dash when the reason string is missing', () => {
    render(<EdgeReasonPanel edge={{ id: 'x' }} />);
    expect(screen.getByText('Flow Reason')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('exposes the reason area as a polite live region (a11y)', () => {
    // R10-#25: both states — empty hint and edge content — announce changes
    const { container, rerender } = render(<EdgeReasonPanel edge={null} />);
    const emptyPanel = container.querySelector('[data-testid="edge-reason-panel"]');
    expect(emptyPanel).toHaveAttribute('role', 'status');
    expect(emptyPanel).toHaveAttribute('aria-live', 'polite');
    rerender(<EdgeReasonPanel edge={edge} />);
    const contentPanel = container.querySelector('[data-testid="edge-reason-panel"]');
    expect(contentPanel).toHaveAttribute('role', 'status');
    expect(contentPanel).toHaveAttribute('aria-live', 'polite');
  });

  it('keeps a CONSTANT height in both states (Issue 1 — edge click never changes the panel height)', () => {
    // Issue 1 (fix 2026-08-11): the height prop (DataFlowApp's
    // reasonPanelHeight state) applies to the EMPTY state and the
    // content state alike. A constant height means an edge click causes
    // no flex reflow → the graph-canvas ResizeObserver never fires on
    // click → the L2 viewport never auto-refits. Content overflow
    // scrolls internally (overflow-y: auto in CSS).
    const { container, rerender } = render(<EdgeReasonPanel edge={null} height={160} />);
    const emptyPanel = container.querySelector('[data-testid="edge-reason-panel"]');
    expect(emptyPanel).toHaveStyle({ height: '160px' });
    rerender(<EdgeReasonPanel edge={edge} height={160} />);
    const contentPanel = container.querySelector('[data-testid="edge-reason-panel"]');
    expect(contentPanel).toHaveStyle({ height: '160px' });
    // Without the height prop no inline height is forced — the panel
    // falls back to the constant CSS default (.edge-reason-panel has a
    // fixed height, never height:auto).
    rerender(<EdgeReasonPanel edge={edge} />);
    expect(container.querySelector('[data-testid="edge-reason-panel"]')).not.toHaveStyle({ height: '160px' });
  });
});

// ── R11-3: code evidence (backend `mech` payload) ─────────────────────
const mechEdge = {
  id: 'e1',
  edge_type: 'TABLE_FLOW',
  flow_kind: 'chain',
  highlight_line: 9,
  reason: 'chain — rollover_loan_info@L9 → ‖loan_final@L64‖',
  color: '#2ECC71',
  mech: {
    clause: 'JOIN',
    ref_line: 155,
    alias: 'p6',
    use_lines: [82, 156],
    sentence: 'loan_final (L64) reads rollover_loan_info (L9) via LEFT JOIN at L155 (alias p6)',
  },
};

const SQL_TEXT = [
  'WITH rollover_loan_info AS (',
  '  SELECT id FROM raw',
  ')',
  'SELECT *',
  'FROM loan_final',
  'LEFT JOIN rollover_loan_info p6',
  '  ON p6.id = p1.id',
  'WHERE p6.lending_ref = 1',
  'INSERT OVERWRITE TABLE sup',
].join('\n');

describe('EdgeReasonPanel — R11-3 code evidence (mech payload)', () => {
  it('renders the flow sentence above the code evidence block', () => {
    render(<EdgeReasonPanel edge={mechEdge} sqlText={SQL_TEXT} />);
    expect(screen.getByText(/reads rollover_loan_info \(L9\) via LEFT JOIN at L155/)).toBeInTheDocument();
    expect(screen.getByText('Code evidence')).toBeInTheDocument();
  });

  it('renders one row per line — ref site, uses, def — sorted and labeled', () => {
    const { container } = render(<EdgeReasonPanel edge={mechEdge} sqlText={SQL_TEXT} />);
    const rows = container.querySelectorAll('.edge-reason-evidence-row');
    // highlight_line 9 (def of source) + ref_line 155 + use_lines 82, 156 → 4 rows, ascending
    expect(rows.length).toBe(4);
    expect(rows[0].getAttribute('data-line')).toBe('9');
    expect(rows[0].textContent).toContain('def of source');
    expect(rows[0].textContent).toContain('L9: INSERT OVERWRITE TABLE sup');
    expect(rows[1].getAttribute('data-line')).toBe('82');
    expect(rows[1].textContent).toContain('join key / value use');
    expect(rows[2].getAttribute('data-line')).toBe('155');
    expect(rows[2].textContent).toContain('reference site · JOIN');
    expect(rows[3].getAttribute('data-line')).toBe('156');
  });

  it('renders "(line not available)" for lines beyond the script text', () => {
    const { container } = render(<EdgeReasonPanel edge={mechEdge} sqlText={SQL_TEXT} />);
    const rows = container.querySelectorAll('.edge-reason-evidence-row');
    // Lines 82/155/156 lie beyond the 9-line script
    expect(rows[1].textContent).toContain('(line not available)');
    expect(rows[2].textContent).toContain('(line not available)');
    expect(rows[3].textContent).toContain('(line not available)');
  });

  it('dedupes lines that serve several roles (ref_line === highlight_line)', () => {
    const dupEdge = {
      ...mechEdge,
      highlight_line: 155,
      mech: { ...mechEdge.mech, ref_line: 155, use_lines: [156] },
    };
    const { container } = render(<EdgeReasonPanel edge={dupEdge} sqlText={SQL_TEXT} />);
    const rows = container.querySelectorAll('.edge-reason-evidence-row');
    expect(rows.length).toBe(2);
    expect(rows[0].getAttribute('data-line')).toBe('155');
    expect(rows[0].textContent).toContain('reference site · JOIN');
    expect(rows[1].getAttribute('data-line')).toBe('156');
  });

  it('calls onJumpToLine with the row line when clicked', () => {
    const onJumpToLine = vi.fn();
    const { container } = render(
      <EdgeReasonPanel edge={mechEdge} sqlText={SQL_TEXT} onJumpToLine={onJumpToLine} />
    );
    fireEvent.click(container.querySelector('[data-line="155"]'));
    expect(onJumpToLine).toHaveBeenCalledTimes(1);
    expect(onJumpToLine).toHaveBeenCalledWith(155);
    fireEvent.click(container.querySelector('[data-line="9"]'));
    expect(onJumpToLine).toHaveBeenCalledWith(9);
  });

  it('renders exactly the R25 output when mech is absent (backward compatible)', () => {
    const { container } = render(<EdgeReasonPanel edge={edge} />);
    expect(container.querySelector('.edge-reason-mech')).toBeNull();
    expect(screen.getByText('chain')).toBeInTheDocument();
    expect(screen.getByText('Anchor: L43')).toBeInTheDocument();
    // ‖…‖ emphasis untouched
    const seg = container.querySelector('.edge-reason-segment');
    expect(seg.textContent).toBe('p1@L29 → p1.data_dt@L43');
  });

  it('tolerates an empty sqlText (all rows out of range)', () => {
    const { container } = render(<EdgeReasonPanel edge={mechEdge} sqlText="" />);
    const rows = container.querySelectorAll('.edge-reason-evidence-row');
    expect(rows.length).toBe(4);
    expect(rows[0].textContent).toContain('(line not available)');
  });
});

// ── R20: path-scoped reasons (Team E) ────────────────────────────────
// The reason becomes the FULL source→target path with exactly ONE
// ‖…‖-wrapped segment (the edge's own, spanning two hops) in the middle,
// and the head may carry the path-scope role parenthetical:
//   `chain (CTE chain) — source@L… → … → ‖own1@L… → own2@L…‖ → … → target@L…`
// The emphasis (bold + edge color) must keep working for the longer string.
const pathEdge = {
  id: 'e-path',
  edge_type: 'TABLE_FLOW',
  flow_kind: 'chain',
  highlight_line: 64,
  reason: 'chain (CTE chain) — bdm_acc_loan_info.data_dt@L18 → loan_final.lending_ref@L9 → ‖loan_final@L64 → sup.lending_ref@L211‖ → sup.data_dt@L217',
  color: '#2ECC71',
};

describe('EdgeReasonPanel — R20 path-scoped reason (one ‖…‖ segment in the middle)', () => {
  it('emphasizes exactly the own ‖…‖ segment in the longer path-scoped string', () => {
    const { container } = render(<EdgeReasonPanel edge={pathEdge} />);
    const emphasized = container.querySelectorAll('.edge-reason-segment');
    expect(emphasized.length).toBe(1);
    // The wrapper characters are stripped; the own-segment text is exact
    // (the own segment spans two hops — the ‖…‖ wrapper still marks it).
    expect(emphasized[0].textContent).toBe('loan_final@L64 → sup.lending_ref@L211');
    expect(emphasized[0].textContent).not.toContain('‖');
    expect(emphasized[0].style.color).toBe('rgb(46, 204, 113)'); // #2ECC71 — edge color
    // The path endpoints + the role-bearing head stay plain (un-emphasized)
    expect(screen.getByText(/bdm_acc_loan_info\.data_dt@L18/)).toBeInTheDocument();
    expect(screen.getByText(/sup\.data_dt@L217/)).toBeInTheDocument();
    expect(screen.getByText(/chain \(CTE chain\)/)).toBeInTheDocument();
  });

  it('preserves the full reason text around the emphasized segment (‖ stripped only from the segment)', () => {
    const { container } = render(<EdgeReasonPanel edge={pathEdge} />);
    const textEl = container.querySelector('.edge-reason-text');
    expect(textEl.textContent).toBe(
      'chain (CTE chain) — bdm_acc_loan_info.data_dt@L18 → loan_final.lending_ref@L9 → loan_final@L64 → sup.lending_ref@L211 → sup.data_dt@L217'
    );
  });

  it('emphasizes every ‖…‖ segment when several exist (defensive)', () => {
    const { container } = render(<EdgeReasonPanel edge={{
      id: 'x', edge_type: 'REF', flow_kind: 'field flow', highlight_line: 3,
      reason: 'field flow — a@L1 → ‖b@L2‖ → c@L3 → ‖d@L4‖ → e@L5', color: '#27AE60',
    }} />);
    const emphasized = container.querySelectorAll('.edge-reason-segment');
    expect(emphasized.length).toBe(2);
    expect(emphasized[0].textContent).toBe('b@L2');
    expect(emphasized[1].textContent).toBe('d@L4');
  });

  it('renders an unmatched opening ‖ as plain text (defensive, no crash)', () => {
    const { container } = render(<EdgeReasonPanel edge={{
      id: 'x', flow_kind: 'chain', highlight_line: 3, reason: 'chain — ‖broken@L2', color: '#2ECC71',
    }} />);
    expect(container.querySelector('.edge-reason-text').textContent).toBe('chain — ‖broken@L2');
    expect(container.querySelectorAll('.edge-reason-segment').length).toBe(0);
  });

  it('keeps the fallback form (no path-style reason) rendered as today', () => {
    const { container } = render(<EdgeReasonPanel edge={{
      id: 'x', flow_kind: 'bridge', highlight_line: 7,
      reason: 'bridge — sup@L223 → rrcdm@L211', color: '#7F8C8D',
    }} />);
    expect(screen.getByText(/sup@L223 → rrcdm@L211/)).toBeInTheDocument();
    expect(container.querySelectorAll('.edge-reason-segment').length).toBe(0);
  });
});
