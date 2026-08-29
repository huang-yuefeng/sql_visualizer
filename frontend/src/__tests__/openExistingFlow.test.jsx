import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import DataFlowApp from '../DataFlowApp';
import {
  resumeWorkspace, getWorkspaceTree, scanWorkspace, indexWorkspace,
  getWorkspaceIndex, listViews,
} from '../api/client';

/**
 * AD2-A frontend half (2026-08-29) — the open-existing flow is role-split.
 *
 * Scan + index are CREATOR-only on the backend (#272/#380 — both rewrite
 * shared workspace state), so a participant opening a shared workspace used
 * to 403 mid-open and land on an empty debugger. The open path now reads the
 * served tree (G3 GET /tree) with POST /scan as the creator's fallback, and
 * reads the index (GET /index) instead of building it (POST /index) for a
 * participant. The "analyzing…" progress spinner is creator-only: a single
 * GET is not an analysis, so showing one would be a lie.
 */

vi.mock('../components/MyWorkspaces', () => ({ default: () => null }));
vi.mock('../components/FolderTree', () => ({ default: () => null }));
vi.mock('../components/ResolutionReport', () => ({ default: () => null }));
vi.mock('../components/DataFlowGraph', () => ({ default: () => null }));
vi.mock('../components/SqlPanel', () => ({ default: () => null }));
vi.mock('../components/LogPanel', () => ({ default: () => null }));
vi.mock('../components/ViewBar', () => ({ default: () => null }));
// WorkspacePanel carries the open flow's progress spinner — its stub text is
// how a test asserts the analyzing phase is (and is not) shown.
vi.mock('../components/WorkspacePanel', () => ({
  default: (p) => (
    <div data-testid="workspace-panel">
      {p.progress ? `progress:${p.progress.phase}` : 'idle'}
    </div>
  ),
}));
// The search UI mounts only once the index has been applied (indexed && the
// table index is non-empty) — its appearance IS "the open finished".
vi.mock('../components/FilterPanel', () => ({
  default: () => <button type="button" data-testid="run-search">run-search</button>,
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

const TREE = {
  type: 'folder', name: 'ws',
  children: [{ type: 'file', path: 'a.sql', name: 'a.sql', is_sql: true }],
};
const INDEX = {
  table_index: { t: { fields: ['f'], scripts: ['a.sql'] } },
  field_index: { f: { tables: ['t'], scripts: ['a.sql'] } },
};
const CREATOR = 'creator@hsbc.com';
const PARTICIPANT = 'p@hsbc.com';

function deferred() {
  let resolve;
  const promise = new Promise(res => { resolve = res; });
  return { promise, resolve };
}

/** Mount with a resume row for `user` and wait until the open flow has
 *  reached the index step (whatever serves it). */
async function mountOpen({ asUser, creator }) {
  resumeWorkspace.mockResolvedValue({
    state_version: 3, layouts: {}, creator_username: creator,
  });
  listViews.mockResolvedValue({ views: [] });
  render(<DataFlowApp openWorkspaceId="ws1" username={asUser} />);
  return screen.findByTestId('run-search');
}

beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
});

describe('open-existing — participant reads, never writes (AD2-A)', () => {
  it('uses the served tree + GET /index and never scans, indexes or spins', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    const pending = deferred();
    getWorkspaceIndex.mockImplementation(() => pending.promise);

    const done = mountOpen({ asUser: PARTICIPANT, creator: CREATOR });

    // The index read is in flight: no "analyzing" spinner — a GET is not an
    // analysis, and the old flow never even reached this point for a
    // participant (the creator-only scan 403'd first).
    await vi.waitFor(() => expect(getWorkspaceIndex).toHaveBeenCalledWith('ws1'));
    expect(screen.getByTestId('workspace-panel').textContent).toBe('idle');

    await actResolve(pending, INDEX);
    await done;
    expect(screen.getByTestId('run-search')).toBeInTheDocument();

    expect(getWorkspaceTree).toHaveBeenCalledTimes(1);
    expect(scanWorkspace).not.toHaveBeenCalled();
    expect(indexWorkspace).not.toHaveBeenCalled();
  });

  it('falls back to nothing: no served tree and not the creator says why', async () => {
    getWorkspaceTree.mockResolvedValue(null); // 409 no-tree / pre-G3 / 403 → null

    render(<DataFlowApp openWorkspaceId="ws1" username={PARTICIPANT} />);

    // A clear message instead of a raw 403 from the creator-only scan.
    expect(await screen.findByText(/no file index yet/i)).toBeInTheDocument();
    expect(scanWorkspace).not.toHaveBeenCalled();
    expect(indexWorkspace).not.toHaveBeenCalled();
    expect(getWorkspaceIndex).not.toHaveBeenCalled();
    expect(screen.queryByTestId('run-search')).toBeNull();
  });

  it('surfaces a failing GET /index detail instead of dying silently', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockRejectedValue(new Error('index unavailable'));
    render(<DataFlowApp openWorkspaceId="ws1" username={PARTICIPANT} />);
    expect(await screen.findByText('index unavailable')).toBeInTheDocument();
  });
});

describe('open-existing — creator path is unchanged (scan → POST /index)', () => {
  it('scans and indexes when no tree is served (pre-G3 backend)', async () => {
    getWorkspaceTree.mockResolvedValue(null);
    scanWorkspace.mockResolvedValue(TREE);
    const pending = deferred();
    indexWorkspace.mockImplementation(() => pending.promise);

    const done = mountOpen({ asUser: CREATOR, creator: CREATOR });

    // The creator DOES get the analyzing spinner while its POST /index runs.
    await vi.waitFor(() => expect(indexWorkspace).toHaveBeenCalled());
    expect(screen.getByTestId('workspace-panel').textContent).toBe('progress:analyzing');

    await actResolve(pending, INDEX);
    await done;
    expect(screen.getByTestId('run-search')).toBeInTheDocument();

    expect(getWorkspaceTree).toHaveBeenCalledWith('ws1');
    expect(scanWorkspace).toHaveBeenCalledWith('ws1');
    // the tree was walked for the script list exactly as before
    expect(indexWorkspace).toHaveBeenCalledWith('ws1', ['a.sql']);
    expect(getWorkspaceIndex).not.toHaveBeenCalled();
  });

  it('skips the creator-only scan when the tree is already served', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    indexWorkspace.mockResolvedValue(INDEX);

    const done = mountOpen({ asUser: CREATOR, creator: CREATOR });
    await done;
    expect(screen.getByTestId('run-search')).toBeInTheDocument();

    expect(scanWorkspace).not.toHaveBeenCalled();
    expect(indexWorkspace).toHaveBeenCalledWith('ws1', ['a.sql']);
  });
});

async function actResolve(pending, value) {
  const { act } = await import('@testing-library/react');
  await act(async () => { pending.resolve(value); });
}
