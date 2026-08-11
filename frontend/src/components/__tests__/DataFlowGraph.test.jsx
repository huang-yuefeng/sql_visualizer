import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
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

// ── R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow ─────
// The display toggle (default OFF = hidden) lives in the L2 toolbar next
// to the legend; the hook gets the option, the toggle badge and the
// legend note carry the structure-edge count.
const withSchema = {
  nodes: graphData.nodes,
  edges: [
    ...graphData.edges,
    { data: { id: 's1', source: 'n1', target: 'n2', edge_type: 'SCHEMA' } },
  ],
};

describe('DataFlowGraph — R19.4/R19.6a structure-edge toggle', () => {
  it('renders the Structure toggle for L2 and reports clicks', () => {
    const onToggle = vi.fn();
    render(<DataFlowGraph graphData={graphData} level="L2"
      showStructureEdges={false} onToggleStructureEdges={onToggle} />);
    const btn = screen.getByRole('button', { name: /Structure off/ });
    fireEvent.click(btn);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('passes showStructureEdges into the cytoscape hook options', () => {
    render(<DataFlowGraph graphData={graphData} level="L2"
      showStructureEdges={true} onToggleStructureEdges={vi.fn()} />);
    expect(lastHookOptions().showStructureEdges).toBe(true);
    render(<DataFlowGraph graphData={graphData} level="L2"
      showStructureEdges={false} onToggleStructureEdges={vi.fn()} />);
    expect(lastHookOptions().showStructureEdges).toBe(false);
  });

  it('shows the structure-edge count in the toggle badge', () => {
    render(<DataFlowGraph graphData={withSchema} level="L2"
      showStructureEdges={false} onToggleStructureEdges={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Structure off \(1\)/ })).toBeInTheDocument();
  });

  it('does not render the Structure toggle for L1', () => {
    render(<DataFlowGraph graphData={graphData} level="L1" />);
    expect(screen.queryByRole('button', { name: /Structure/ })).not.toBeInTheDocument();
  });

  it('legend note appears only while structure edges are hidden', () => {
    const { rerender } = render(<DataFlowGraph graphData={withSchema} level="L2"
      showStructureEdges={false} onToggleStructureEdges={vi.fn()} />);
    expect(screen.getByTestId('legend-structure-note')).toBeInTheDocument();
    expect(screen.getByTestId('legend-structure-note').textContent).toContain('(1)');
    rerender(<DataFlowGraph graphData={withSchema} level="L2"
      showStructureEdges={true} onToggleStructureEdges={vi.fn()} />);
    expect(screen.queryByTestId('legend-structure-note')).not.toBeInTheDocument();
  });

  it('no legend note when the graph has no structure edges', () => {
    render(<DataFlowGraph graphData={graphData} level="L2" showStructureEdges={false} />);
    expect(screen.queryByTestId('legend-structure-note')).not.toBeInTheDocument();
  });
});
