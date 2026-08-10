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
});
