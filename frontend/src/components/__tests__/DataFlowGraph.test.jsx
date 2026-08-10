import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import DataFlowGraph from '../DataFlowGraph';

// The cytoscape instance is canvas-based — not testable in jsdom. The
// hook is the graph lifecycle; capture the options the component hands
// it and drive the callbacks directly.
const { hookMock } = vi.hoisted(() => ({ hookMock: vi.fn() }));

vi.mock('../../hooks/useCytoscapeGraph', () => ({
  default: (...args) => {
    hookMock(...args);
    return { cyRef: { current: null }, fit: vi.fn(), relayout: vi.fn() };
  },
}));

const edgeData = {
  id: 'e1',
  source: 'n1',
  target: 'n2',
  edge_type: 'TABLE_FLOW',
  flow_kind: 'chain',
  highlight_line: 43,
  reason: 'chain — bdm_acc_loan_info.data_dt@L18 → ‖p1@L29 → p1.data_dt@L43‖ → ⟐subq@L0',
  color: '#2ECC71',
};

const graphData = {
  nodes: [{ data: { id: 'n1', label: 'a' } }, { data: { id: 'n2', label: 'b' } }],
  edges: [{ data: edgeData }],
};

function lastHookOptions() {
  return hookMock.mock.calls[hookMock.mock.calls.length - 1][2];
}

describe('DataFlowGraph — R25/§8.8 edge interactions', () => {
  beforeEach(() => {
    hookMock.mockClear();
    // jsdom has no ResizeObserver; the component uses it for auto-fit
    global.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  });

  it('forwards the full per-edge payload on edge tap (highlight_line/flow_kind/reason)', () => {
    const onEdgeClick = vi.fn();
    render(<DataFlowGraph graphData={graphData} level="L2" onEdgeClick={onEdgeClick} />);
    const options = lastHookOptions();
    options.onEdgeTap({ target: { data: () => edgeData } });
    expect(onEdgeClick).toHaveBeenCalledTimes(1);
    // The per-edge payload is the source of truth — passed through whole.
    expect(onEdgeClick.mock.calls[0][0]).toEqual(edgeData);
    expect(onEdgeClick.mock.calls[0][0].highlight_line).toBe(43);
    expect(onEdgeClick.mock.calls[0][0].flow_kind).toBe('chain');
    expect(onEdgeClick.mock.calls[0][0].reason).toContain('‖');
  });

  it('fires onCanvasTap on background taps (canvas click clears selection)', () => {
    const onCanvasTap = vi.fn();
    render(<DataFlowGraph graphData={graphData} level="L2" onCanvasTap={onCanvasTap} />);
    const options = lastHookOptions();
    options.onBgTap();
    expect(onCanvasTap).toHaveBeenCalledTimes(1);
  });

  it('hover tooltip shows edge type + flow kind + anchor line + reason preview', () => {
    const { container } = render(<DataFlowGraph graphData={graphData} level="L2" />);
    const options = lastHookOptions();
    act(() => {
      options.onEdgeHover({ target: { isEdge: () => true, data: () => edgeData } });
    });
    const tooltip = container.querySelector('.edge-tooltip');
    expect(tooltip).not.toBeNull();
    expect(tooltip.textContent).toContain('TABLE_FLOW');
    expect(tooltip.textContent).toContain('kind: chain');
    expect(tooltip.textContent).toContain('anchor: L43');
    expect(tooltip.textContent).toContain('bdm_acc_loan_info.data_dt@L18');
  });

  it('hovering a non-edge leaves the tooltip empty', () => {
    render(<DataFlowGraph graphData={graphData} level="L2" />);
    const options = lastHookOptions();
    act(() => {
      options.onEdgeHover({ target: { isEdge: () => false, data: () => ({}) } });
    });
    expect(screen.queryByText(/kind:/)).not.toBeInTheDocument();
  });
});
