import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import DataFlowApp from '../DataFlowApp';
import {
  searchDataFlow, getLevel2Graph, addViewChild,
  resumeWorkspace, scanWorkspace, indexWorkspace, listViews,
} from '../api/client';

// All heavy children are mocked — this suite asserts the T8 (#295) left-panel
// composition: the embedded "My workspaces" section at the TOP of the
// debugger's left panel, wired to the debugger's open/upload/remove lifecycle.
vi.mock('../components/MyWorkspaces', () => ({
  default: (p) => (
    <div data-testid="my-workspaces">
      {`open=${p.open ? 'true' : 'false'};onOpen=${!!p.onOpen};onUpload=${!!p.onUpload};onRemove=${!!p.onRemove}`}
    </div>
  ),
}));
vi.mock('../components/WorkspacePanel', () => ({
  default: (p) => <div data-testid="workspace-panel">{p.showUploads ? 'uploads' : 'no-uploads'}</div>,
}));
vi.mock('../components/FolderTree', () => ({ default: () => null }));
// #400: the search entry point — the real FilterPanel needs the index UI, so
// the stub only has to expose the onSearch callback once a workspace is open
// (tableIndex populated). Existing composition tests never populate it.
vi.mock('../components/FilterPanel', () => ({
  default: (p) => (
    p.tableIndex && Object.keys(p.tableIndex).length > 0
      ? (
        <button
          type="button"
          data-testid="run-search"
          onClick={() => p.onSearch('tmp_km', 'BAL', 'downstream')}
        >
          run-search
        </button>
      )
      : null
  ),
}));
vi.mock('../components/ResolutionReport', () => ({ default: () => null }));
vi.mock('../components/DataFlowGraph', () => ({ default: () => null }));
vi.mock('../components/SqlPanel', () => ({ default: () => null }));
vi.mock('../components/LogPanel', () => ({ default: () => null }));
// ViewBar stub: renders the view/child tree so a test can navigate back to a
// parent view and count the created L2 children.
vi.mock('../components/ViewBar', () => ({
  default: (p) => (
    p.views && p.views.length > 0 ? (
      <div data-testid="view-bar">
        {p.views.map(v => (
          <div key={v.view_id} data-testid={`tab-${v.view_id}`} onClick={() => p.onSelect(v.view_id)}>
            {v.view_id}
            {(v.children || []).map(c => (
              <span key={c.view_id} data-testid={`child-${c.view_id.replace(/[^a-zA-Z0-9]/g, '_')}`}>
                {c.script_name}
              </span>
            ))}
          </div>
        ))}
        <span data-testid="active-view">{p.activeViewId}</span>
      </div>
    ) : null
  ),
}));
vi.mock('../api/client', () => ({
  addViewChild: vi.fn(),
  // the unmount cleanup awaits .catch on this — must resolve, never undefined
  closeWorkspace: vi.fn(async () => ({})),
  deleteView: vi.fn(),
  deleteViewChild: vi.fn(),
  getLevel2Graph: vi.fn(),
  getWorkspaceStatus: vi.fn(),
  indexWorkspace: vi.fn(),
  listViews: vi.fn(),
  removeFromMyHistory: vi.fn(),
  resumeWorkspace: vi.fn(),
  saveLayout: vi.fn(),
  scanWorkspace: vi.fn(),
  searchDataFlow: vi.fn(),
  uploadWorkspace: vi.fn(),
}));

describe('DataFlowApp — T8 (#295) embedded MyWorkspaces in the left panel', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it('renders the MyWorkspaces section at the top of the left panel when no workspace is open', () => {
    render(
      <DataFlowApp
        openWorkspaceId={null}
        username="alice@hsbc.com"
        onOpenWorkspace={vi.fn()}
      />
    );
    const ws = screen.getByTestId('my-workspaces');
    expect(ws).toBeInTheDocument();
    // open=true → the embedded list is always active (refetches on each mount);
    // the three lifecycle handlers are wired.
    expect(ws.textContent).toContain('open=true');
    expect(ws.textContent).toContain('onOpen=true');
    expect(ws.textContent).toContain('onUpload=true');
    expect(ws.textContent).toContain('onRemove=true');
  });

  it('passes showUploads={false} to WorkspacePanel so no second upload picker appears', () => {
    render(<DataFlowApp openWorkspaceId={null} />);
    expect(screen.getByTestId('workspace-panel').textContent).toBe('no-uploads');
  });

  it('keeps WorkspacePanel for the in-workspace display (showUploads false still rendered with a wsId)', () => {
    render(<DataFlowApp openWorkspaceId="ws1" />);
    expect(screen.getByTestId('workspace-panel')).toBeInTheDocument();
    expect(screen.getByTestId('workspace-panel').textContent).toBe('no-uploads');
  });
});

// ── #400: the no-flow search dead end ─────────────────────────────────
// A no_flow search matches scripts (view.script_ids) but its L1 is EMPTY —
// no script node to double-click — so the matched script's L2 was reachable
// only by hand-crafting the child view through the API. The banner now
// carries one "Open <script> full graph" affordance per matched script and
// calls the SAME path as the L1 double-click (handleOpenL2 → GET /level2 →
// POST .../children).
const NO_FLOW_RESULT = {
  view_id: 'v1',
  table: 'tmp_km',
  field: 'BAL',
  script_ids: ['sub/BDM_ACC_LOAN_INFO_RFN.sql', 'BDM_ACC_LOAN_INFO_PL.sql'],
  l1_graph: { nodes: [], edges: [] },
  match_mode: 'no_flow',
  message: 'No reading flow for tmp_km.BAL',
  direction: 'downstream',
};

const NOT_IN_FLOW_L2 = {
  graph: { nodes: [], edges: [] },
  full_graph: { nodes: [], edges: [] },
  sql_text: 'SELECT 1;',
  search_matched: false,
  message: 'tmp_km.BAL is not referenced in BDM_ACC_LOAN_INFO_RFN.sql - showing the full script graph',
  parse_errors: [],
};

async function mountWorkspaceSearcher() {
  resumeWorkspace.mockResolvedValue({ state_version: 0, layouts: {} });
  scanWorkspace.mockResolvedValue({ type: 'folder', name: 'ws', children: [] });
  indexWorkspace.mockResolvedValue({
    table_index: { tmp_km: { fields: ['BAL'], scripts: NO_FLOW_RESULT.script_ids } },
    field_index: { BAL: { tables: ['tmp_km'], scripts: NO_FLOW_RESULT.script_ids } },
  });
  listViews.mockResolvedValue({ views: [] });
  const view = render(<DataFlowApp openWorkspaceId="ws1" username="alice@hsbc.com" />);
  await screen.findByTestId('run-search');
  return view;
}

async function runSearch(result) {
  searchDataFlow.mockResolvedValue(result);
  await act(async () => { fireEvent.click(screen.getByTestId('run-search')); });
}

describe('DataFlowApp — #400 no-flow banner opens the matched script’s full graph', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it('renders one full-graph affordance per matched script on a no_flow result', async () => {
    await mountWorkspaceSearcher();
    await runSearch(NO_FLOW_RESULT);

    // the backend message stays verbatim, with the continuation below it
    expect(await screen.findByText(/No reading flow for tmp_km\.BAL - empty result view/)).toBeInTheDocument();
    for (const script of NO_FLOW_RESULT.script_ids) {
      const name = script.split('/').pop();
      expect(screen.getByRole('button', { name: `Open ${name} full graph` })).toBeInTheDocument();
    }
  });

  it('clicking the affordance opens the L2 through the exact L1 double-click path', async () => {
    getLevel2Graph.mockResolvedValue(NOT_IN_FLOW_L2);
    await mountWorkspaceSearcher();
    await runSearch(NO_FLOW_RESULT);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Open BDM_ACC_LOAN_INFO_RFN.sql full graph' }));
    });

    // GET /level2 with the rel_path script + filter=true + downstream — the
    // very call the L1 script-node double-click makes.
    expect(getLevel2Graph).toHaveBeenCalledWith(
      'ws1', 'v1', 'sub/BDM_ACC_LOAN_INFO_RFN.sql', true, 'downstream');
    // the child view is persisted exactly as the L1 path persists it
    expect(addViewChild).toHaveBeenCalledTimes(1);
    expect(addViewChild).toHaveBeenCalledWith('ws1', 'v1', expect.objectContaining({
      view_id: 'v1_sub/BDM_ACC_LOAN_INFO_RFN.sql',
      type: 'script',
      parent_view_id: 'v1',
      script_id: 'sub/BDM_ACC_LOAN_INFO_RFN.sql',
      script_name: 'sub/BDM_ACC_LOAN_INFO_RFN.sql',
    }));
    // the L2 panel opened, the L1 banner is gone…
    expect(await screen.findByText(/Level 2 Detail/)).toBeInTheDocument();
    expect(screen.queryByText(/empty result view/)).not.toBeInTheDocument();
    // …and the child's own not-in-flow notice explains the full-graph render
    expect(
      await screen.findByText(/not referenced in BDM_ACC_LOAN_INFO_RFN\.sql/)
    ).toBeInTheDocument();
    // the active view is the new child (subtab in the view tree)
    expect(screen.getByTestId('active-view').textContent).toBe('v1_sub/BDM_ACC_LOAN_INFO_RFN.sql');
    expect(screen.getByTestId('child-v1_sub_BDM_ACC_LOAN_INFO_RFN_sql')).toBeInTheDocument();
  });

  it('re-clicking the same script after returning to L1 reuses the child view', async () => {
    getLevel2Graph.mockResolvedValue(NOT_IN_FLOW_L2);
    await mountWorkspaceSearcher();
    await runSearch(NO_FLOW_RESULT);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Open BDM_ACC_LOAN_INFO_RFN.sql full graph' }));
    });
    await screen.findByText(/Level 2 Detail/);

    // back to the parent (L1) view — the banner and its affordance return
    await act(async () => { fireEvent.click(screen.getByTestId('tab-v1')); });
    expect(await screen.findByText(/empty result view/)).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Open BDM_ACC_LOAN_INFO_RFN.sql full graph' }));
    });
    await screen.findByText(/Level 2 Detail/);

    // the L1 path re-fetches the graph but never duplicates the child entry
    expect(getLevel2Graph).toHaveBeenCalledTimes(2);
    expect(addViewChild).toHaveBeenCalledTimes(2);
    expect(screen.getAllByTestId('child-v1_sub_BDM_ACC_LOAN_INFO_RFN_sql')).toHaveLength(1);
    expect(screen.queryByTestId(/child-v1_sub_BDM_ACC_LOAN_INFO_RFN_sql_.+/)).toBeNull();
  });

  it('no_matches and in-flow searches never render the affordance', async () => {
    const { container } = await mountWorkspaceSearcher();

    await runSearch({
      ...NO_FLOW_RESULT,
      view_id: 'v2',
      match_mode: 'no_matches',
      message: 'No script in this workspace references tmp_km.BAL',
      script_ids: [],
    });
    expect(await screen.findByText(/No matches: No script in this workspace references tmp_km\.BAL/))
      .toBeInTheDocument();
    expect(container.querySelector('.no-match-banner-actions')).toBeNull();
    expect(screen.queryByRole('button', { name: /full graph/ })).toBeNull();

    // an in-flow search has no banner at all — and no button either
    await runSearch({
      view_id: 'v3',
      table: 'tmp_km',
      field: 'BAL',
      script_ids: ['a.sql'],
      l1_graph: {
        nodes: [{ data: { id: 's1', type: 'script_node', label: 'a.sql', script_name: 'a.sql' } }],
        edges: [],
      },
      match_mode: 'exact',
      direction: 'downstream',
    });
    await screen.findByTestId('tab-v3');
    expect(container.querySelector('.no-match-banner')).toBeNull();
    expect(screen.queryByRole('button', { name: /full graph/ })).toBeNull();
  });
});

// ── V2-N4: matched-but-not-in-flow scripts on a rendered L1 flow ──────
// matched != in flow: an exact-match search's `script_ids` are the scripts
// that QUERY the searched field, while the L1 graph renders only the
// directional flow's script nodes (P2.P_DT matched 4, its L1 rendered 2).
// The out-of-flow rest were reachable only through a no_flow banner, which an
// exact-match view never renders — so the L1 view now carries the same
// "Open <script> full graph" affordance for exactly the missing subset.
const IN_FLOW = ['BDM_ACC_LOAN_INFO_PL.sql', 'BDM_ACC_LOAN_INFO_SUP_M.sql'];
const OUT_OF_FLOW = ['sub/BDM_ACC_LOAN_INFO_Digitallending.sql'];

const PARTIAL_FLOW_RESULT = {
  view_id: 'v4',
  table: 'p2',
  field: 'P_DT',
  script_ids: [...IN_FLOW, ...OUT_OF_FLOW],
  l1_graph: {
    nodes: [
      ...IN_FLOW.map((name, i) => ({
        data: { id: `s${i}`, type: 'script_node', label: name, script_name: name },
      })),
      { data: { id: 't1', type: 'source_table', label: 'ODS_X' } },
    ],
    edges: [],
  },
  match_mode: 'exact',
  message: null,
  direction: 'downstream',
};

describe('DataFlowApp — out-of-flow strip on a partially-rendered L1 (V2-N4)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it('names exactly the matched scripts the L1 flow does not render', async () => {
    const { container } = await mountWorkspaceSearcher();
    await runSearch(PARTIAL_FLOW_RESULT);

    const strip = await screen.findByTestId('not-in-flow-strip');
    expect(strip).toBeInTheDocument();
    // only the missing one — never the scripts the L1 already renders
    expect(screen.getByRole('button', { name: 'Open BDM_ACC_LOAN_INFO_Digitallending.sql full graph' }))
      .toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Open BDM_ACC_LOAN_INFO_PL.sql full graph' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Open BDM_ACC_LOAN_INFO_SUP_M.sql full graph' })).toBeNull();
    // the strip is the slim L1 banner, not the no-match warning
    expect(strip.className).toContain('banner-strip');
    expect(container.querySelector('.no-match-banner:not(.banner-strip)')).toBeNull();
  });

  it('stays hidden when every matched script is in flow', async () => {
    const { container } = await mountWorkspaceSearcher();
    await runSearch({
      ...PARTIAL_FLOW_RESULT,
      view_id: 'v5',
      script_ids: IN_FLOW,
    });
    await screen.findByTestId('tab-v5');
    expect(screen.queryByTestId('not-in-flow-strip')).toBeNull();
    expect(container.querySelector('.banner-strip')).toBeNull();
    expect(screen.queryByRole('button', { name: /full graph/ })).toBeNull();
  });

  it('never competes with the #400 no-flow banner (empty L1 → banner owns the slot)', async () => {
    const { container } = await mountWorkspaceSearcher();
    await runSearch(NO_FLOW_RESULT);
    expect(await screen.findByText(/empty result view/)).toBeInTheDocument();
    expect(screen.queryByTestId('not-in-flow-strip')).toBeNull();
    // the no_flow banner's own affordances are untouched
    expect(container.querySelector('.no-match-banner-actions')).not.toBeNull();
  });

  it('the strip button opens the full graph through the same L1 double-click path', async () => {
    getLevel2Graph.mockResolvedValue(NOT_IN_FLOW_L2);
    await mountWorkspaceSearcher();
    await runSearch(PARTIAL_FLOW_RESULT);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Open BDM_ACC_LOAN_INFO_Digitallending.sql full graph' }));
    });

    expect(getLevel2Graph).toHaveBeenCalledWith(
      'ws1', 'v4', 'sub/BDM_ACC_LOAN_INFO_Digitallending.sql', true, 'downstream');
    expect(await screen.findByText(/Level 2 Detail/)).toBeInTheDocument();
  });
});
