import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import DataFlowApp from '../DataFlowApp';
import {
  resumeWorkspace, getWorkspaceTree, scanWorkspace, indexWorkspace,
  listViews, searchDataFlow, getLevel2Graph,
} from '../api/client';

/**
 * R3 finding 4 (2026-08-29) — a Field Story step whose line IS valid must
 * clear a stale "this element has no SQL line" notice.
 *
 * The R37 SQL-highlight channel is written by edge clicks, node clicks AND
 * story steps; the F-B2 notice rides on that channel and self-clears on every
 * valid writer. applyStoryStep wrote the line but left the notice up, so a
 * story walked after a zero-line click kept saying "no SQL line" while the
 * SQL panel sat on the step's line — a contradiction on screen.
 */

vi.mock('../components/MyWorkspaces', () => ({ default: () => null }));
vi.mock('../components/FolderTree', () => ({ default: () => null }));
vi.mock('../components/ResolutionReport', () => ({ default: () => null }));
vi.mock('../components/SqlPanel', () => ({ default: () => null }));
vi.mock('../components/LogPanel', () => ({ default: () => null }));
vi.mock('../components/ViewBar', () => ({ default: () => null }));
vi.mock('../components/WorkspacePanel', () => ({ default: () => null }));
// Search entry stub — the real panel is not under test here; it only has to
// expose onSearch once the workspace is open (its mount = indexed).
vi.mock('../components/FilterPanel', () => ({
  default: (p) => (
    <button
      type="button"
      data-testid="run-search"
      onClick={() => p.onSearch('ORDERS', 'amount', 'downstream')}
    >
      run-search
    </button>
  ),
}));
// Graph stub: exposes the two R37 writers so a test can drive the SQL
// channel without a real cytoscape instance. FieldStoryBar stays REAL —
// this suite walks its step chips.
vi.mock('../components/DataFlowGraph', () => ({
  default: (p) => (
    <div data-testid="graph-stub">
      <button
        type="button"
        data-testid="tap-zero-line-edge"
        onClick={() => p.onEdgeClick && p.onEdgeClick({ id: 'e-zero', highlight_line: 0 })}
      >
        tap-edge
      </button>
      <button
        type="button"
        data-testid="tap-line-edge"
        onClick={() => p.onEdgeClick && p.onEdgeClick({ id: 'e-ok', highlight_line: 8 })}
      >
        tap-edge-ok
      </button>
    </div>
  ),
}));

vi.mock('../api/client', () => ({
  addViewChild: vi.fn(),
  closeWorkspace: vi.fn(async () => ({})),
  deleteView: vi.fn(),
  deleteViewChild: vi.fn(),
  getLevel2Graph: vi.fn(),
  getWorkspaceStatus: vi.fn(),
  getWorkspaceTree: vi.fn(),
  getWorkspaceIndex: vi.fn(),
  indexWorkspace: vi.fn(),
  listViews: vi.fn(),
  removeFromMyHistory: vi.fn(),
  resumeWorkspace: vi.fn(),
  saveLayout: vi.fn(),
  scanWorkspace: vi.fn(),
  searchDataFlow: vi.fn(),
  uploadWorkspace: vi.fn(),
}));

// ── L2 payload: the searched field's closure as story-worthy edges ──────
// (same shape the fieldStory suite's EAST5 fixture documents: nodes carry
// { id, type, parent?, label, line_start }; edges carry highlight_line.)
function l2Payload() {
  const nodes = [
    { data: { id: 'orders', type: 'source_table', label: 'ORDERS', line_start: 5 } },
    { data: { id: 'orders.amount', type: 'field', parent: 'orders', label: 'amount', line_start: 5 } },
    { data: { id: 'out5', type: 'virtual_table', label: '⟐ output@5', line_start: 5 } },
    { data: { id: 'tgt', type: 'target_table', label: 'TGT', line_start: 9 } },
    { data: { id: 'out9', type: 'virtual_table', label: '⟐ output@9', line_start: 9 } },
  ];
  const edges = [
    { data: { id: 'e-ref-5', source: 'orders.amount', target: 'out5', edge_type: 'REF', highlight_line: 5 } },
    { data: { id: 'e-write-5', source: 'out5', target: 'orders', edge_type: 'TABLE_FLOW', flow_kind: 'write', highlight_line: 5 } },
    { data: { id: 'e-chain-8', source: 'orders', target: 'out9', edge_type: 'TABLE_FLOW', flow_kind: 'chain', highlight_line: 8 } },
    { data: { id: 'e-ref-8', source: 'orders.amount', target: 'orders', edge_type: 'REF', flow_kind: 'read', highlight_line: 8 } },
    { data: { id: 'e-write-9', source: 'out9', target: 'tgt', edge_type: 'TABLE_FLOW', flow_kind: 'write', highlight_line: 9 } },
  ];
  const graph = { nodes, edges };
  return {
    graph,
    full_graph: graph,
    sql_text: 'SELECT 1;\n',
    search_matched: true,
    flow_node_ids: ['orders.amount'],
    flow_edge_ids: edges.map(e => e.data.id),
    parse_errors: [],
  };
}

const NO_FLOW_SEARCH = {
  view_id: 'v1',
  table: 'ORDERS',
  field: 'amount',
  script_ids: ['a.sql'],
  l1_graph: { nodes: [], edges: [] },
  match_mode: 'no_flow',
  message: 'No reading flow for ORDERS.amount',
  direction: 'downstream',
};

async function mountToL2() {
  resumeWorkspace.mockResolvedValue({ state_version: 0, layouts: {}, creator_username: 'u@hsbc.com' });
  getWorkspaceTree.mockResolvedValue(null);
  scanWorkspace.mockResolvedValue({ type: 'folder', name: 'ws', children: [] });
  indexWorkspace.mockResolvedValue({ table_index: { ORDERS: { fields: ['amount'] } }, field_index: { amount: { tables: ['ORDERS'] } } });
  listViews.mockResolvedValue({ views: [] });
  render(<DataFlowApp openWorkspaceId="ws1" username="u@hsbc.com" />);
  await screen.findByTestId('run-search');
  searchDataFlow.mockResolvedValue(NO_FLOW_SEARCH);
  await act(async () => { fireEvent.click(screen.getByTestId('run-search')); });
  getLevel2Graph.mockResolvedValue(l2Payload());
  // the #400 banner's continuation — the same path an L1 double-click takes
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Open a.sql full graph' }));
  });
  await screen.findByText(/Level 2 Detail/);
}

beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
});

describe('Field Story step clears a stale no-SQL-line notice (R3 finding 4)', () => {
  it('the story bar renders and a step click clears the notice', async () => {
    await mountToL2();

    // the story is derived for the searched ORDERS.amount
    expect(await screen.findByText(/steps - click a number to walk/)).toBeInTheDocument();

    // a zero-line edge click says so …
    await act(async () => { fireEvent.click(screen.getAllByTestId('tap-zero-line-edge')[0]); });
    expect(await screen.findByRole('status')).toHaveTextContent('this element has no SQL line');

    // … and walking the story (a valid step line) clears it again
    await act(async () => { fireEvent.click(screen.getByTitle(/Step 1:/)); });
    expect(screen.queryByRole('status')).toBeNull();
    // the step is the active one now (gold chip, title in the bar)
    expect(screen.getByTitle(/Step 1:/)).toHaveAttribute('aria-current', 'step');
  });

  it('a later zero-line click still restores the notice (channel last-wins)', async () => {
    await mountToL2();
    expect(await screen.findByText(/steps - click a number to walk/)).toBeInTheDocument();

    await act(async () => { fireEvent.click(screen.getAllByTestId('tap-zero-line-edge')[0]); });
    expect(await screen.findByRole('status')).toBeInTheDocument();

    await act(async () => { fireEvent.click(screen.getByTitle(/Step 1:/)); });
    expect(screen.queryByRole('status')).toBeNull();

    await act(async () => { fireEvent.click(screen.getAllByTestId('tap-zero-line-edge')[0]); });
    expect(await screen.findByRole('status')).toHaveTextContent('this element has no SQL line');
  });
});
