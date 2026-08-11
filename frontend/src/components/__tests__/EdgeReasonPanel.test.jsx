import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
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

// ── R26: the R11-3 code-evidence UI is removed (2026-08-11) ──────────
// The script panel already shows the full SQL with the clicked edge's
// anchor line highlighted — the evidence rows duplicated that with less
// context. A backend `mech` payload (if any) is simply ignored: the
// panel renders kind + anchor + reason only.
describe('EdgeReasonPanel — R26 (no code evidence)', () => {
  it('renders exactly kind + anchor + reason when the edge carries a mech payload', () => {
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
    const { container } = render(<EdgeReasonPanel edge={mechEdge} />);
    // Kind + anchor + reason string still render
    expect(screen.getByText('chain')).toBeInTheDocument();
    expect(screen.getByText('Anchor: L9')).toBeInTheDocument();
    expect(screen.getByText(/rollover_loan_info@L9/)).toBeInTheDocument();
    expect(container.querySelector('.edge-reason-segment').textContent).toBe('loan_final@L64');
    // No mech sentence, no evidence rows, no clickable line buttons
    expect(container.querySelector('.edge-reason-mech')).toBeNull();
    expect(container.querySelector('.edge-reason-sentence')).toBeNull();
    expect(container.querySelector('.edge-reason-evidence')).toBeNull();
    expect(container.querySelector('.edge-reason-evidence-row')).toBeNull();
    expect(container.querySelector('[data-line]')).toBeNull();
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
