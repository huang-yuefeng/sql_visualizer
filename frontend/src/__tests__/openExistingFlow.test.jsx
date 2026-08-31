import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DataFlowApp from '../DataFlowApp';
import {
  resumeWorkspace, getWorkspaceTree, scanWorkspace, indexWorkspace,
  getWorkspaceIndex, listViews, searchDataFlow, deleteViewChild,
} from '../api/client';

/**
 * P2 fast-open (v3.3.194) — a plain open NEVER rebuilds anything.
 *
 * The creator's automatic POST /scan + POST /index on open re-parsed every
 * script in the workspace (minutes of "parse"/"profile" in the log panel on
 * a 100-script folder) to recompute state the backend already persists. Both
 * roles now read: GET /workspace/{id}/tree + GET /workspace/{id}/index
 * (G3, since v3.3.192). There is NO manual re-index control (user ruling
 * 2026-08-31): changed scripts are caught up automatically in the background
 * (P1's payload), and only a never-indexed workspace still builds on open —
 * no stored tree means nothing to read.
 *
 * During that background catch-up the search panel is WITHHELD: the search
 * scope IS the index, so searching before the fresh content lands could
 * return a false no_matches. A one-line status explains the hold, and the
 * same honest progress bar the build path uses is shown.
 */

vi.mock('../components/MyWorkspaces', () => ({ default: () => null }));
vi.mock('../components/FolderTree', () => ({ default: () => null }));
vi.mock('../components/ResolutionReport', () => ({ default: () => null }));
vi.mock('../components/DataFlowGraph', () => ({ default: () => null }));
vi.mock('../components/SqlPanel', () => ({ default: () => null }));
vi.mock('../components/LogPanel', () => ({ default: () => null }));
// WorkspacePanel carries the open flow's progress display and the role-gated
// removal label, so the stub mirrors exactly what DataFlowApp passes down.
vi.mock('../components/WorkspacePanel', () => ({
  default: (p) => (
    <div data-testid="workspace-panel">
      <span data-testid="progress-state">{p.progress ? `progress:${p.progress.phase}` : 'idle'}</span>
      <span data-testid="loading-state">{p.loading ? 'loading' : 'settled'}</span>
      <span data-testid="indexed-at-echo">{p.indexedAt ?? 'none'}</span>
      <button type="button" data-testid="remove-workspace">{p.isCreator ? 'Delete Workspace' : 'Remove from my list'}</button>
    </div>
  ),
}));
// The per-view "×" is creator-only server-side (#272) — the stub surfaces the
// gate DataFlowApp hands down and exposes the FIRST L2 child's × so the child
// removal wiring can be driven (it disappears once the child is gone).
vi.mock('../components/ViewBar', () => ({
  default: (p) => {
    const parent = (p.views || [])[0];
    const child = parent && parent.children && parent.children[0];
    return (
      <div data-testid="view-bar" data-can-manage={String(!!p.canManageViews)}>
        {p.canManageViews && child ? (
          <button
            type="button"
            data-testid="child-x"
            onClick={() => p.onRemoveChild(parent.view_id, child.view_id)}
          >
            child-x
          </button>
        ) : null}
      </div>
    );
  },
}));
// The search UI mounts only once the index has been applied (indexed && the
// table index is non-empty) — its appearance IS "the open finished", and the
// echoed table keys ARE the index state (so a refresh is visible). Clicking
// it searches a fixed target, exactly what the real panel would dispatch.
vi.mock('../components/FilterPanel', () => ({
  default: (p) => (
    <button
      type="button"
      data-testid="run-search"
      data-tables={Object.keys(p.tableIndex || {}).sort().join(',')}
      onClick={() => p.onSearch('ORDERS', 'amount', 'downstream')}
    >
      run-search
    </button>
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

const TREE = {
  type: 'folder', name: 'ws',
  children: [{ type: 'file', path: 'a.sql', name: 'a.sql', is_sql: true }],
};
const INDEX = {
  table_index: { t: { fields: ['f'], scripts: ['a.sql'] } },
  field_index: { f: { tables: ['t'], scripts: ['a.sql'] } },
};
const REINDEXED = {
  table_index: { t: { fields: ['f'], scripts: ['a.sql'] }, added: { fields: ['g'], scripts: ['b.sql'] } },
  field_index: { f: { tables: ['t'], scripts: ['a.sql'] }, g: { tables: ['added'], scripts: ['b.sql'] } },
};
const CREATOR = 'creator@hsbc.com';
const PARTICIPANT = 'p@hsbc.com';
// The payload a successful search returns (the 409-replay test asserts on it).
const SEARCH_RESULT = {
  view_id: 'v1', table: 'ORDERS', field: 'amount', script_ids: ['a.sql'],
  l1_graph: { nodes: [], edges: [] }, match_mode: 'no_flow',
  message: 'No reading flow for ORDERS.amount', direction: 'downstream',
};

function deferred() {
  let resolve;
  const promise = new Promise(res => { resolve = res; });
  return { promise, resolve };
}

/** Mount with a resume row for `user` and wait until the open flow has
 *  reached the index step (whatever serves it). */
async function mountOpen({ asUser, creator, views = [] }) {
  resumeWorkspace.mockResolvedValue({
    state_version: 3, layouts: {}, creator_username: creator,
  });
  listViews.mockResolvedValue({ views });
  render(<DataFlowApp openWorkspaceId="ws1" username={asUser} />);
  return screen.findByTestId('run-search');
}

beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
  // clearAllMocks keeps mockResolvedValueOnce queues AND implementations, so a
  // leftover once-queue from an earlier test silently reorders what the next
  // test's open flow reads. Reset them, then install explicit defaults: a test
  // that forgets to stub a call fails LOUDLY instead of reading stale data.
  for (const m of [resumeWorkspace, getWorkspaceTree, scanWorkspace, indexWorkspace,
    getWorkspaceIndex, listViews, searchDataFlow, deleteViewChild]) m.mockReset();
  resumeWorkspace.mockResolvedValue({ state_version: 3, layouts: {}, creator_username: CREATOR });
  getWorkspaceTree.mockResolvedValue(null); // 409: no stored tree
  scanWorkspace.mockResolvedValue(TREE);
  indexWorkspace.mockRejectedValue(new Error('POST /index: no mock in this test'));
  getWorkspaceIndex.mockRejectedValue(new Error('GET /index: no mock in this test'));
  listViews.mockResolvedValue({ views: [] });
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
    expect(screen.getByTestId('progress-state').textContent).toBe('idle');

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

  it('renders no re-index control for a participant (none exists for anyone)', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockResolvedValue(INDEX);

    await mountOpen({ asUser: PARTICIPANT, creator: CREATOR });

    expect(screen.queryByTestId('reindex-btn')).toBeNull();
  });

  it('a participant sees "Remove from my list" and no view "×"', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockResolvedValue(INDEX);

    await mountOpen({ asUser: PARTICIPANT, creator: CREATOR });

    // her "delete" only drops her own link, and view deletion is
    // creator-only server-side — no destructive control, no silent no-op
    expect(screen.getByTestId('remove-workspace')).toHaveTextContent('Remove from my list');
    expect(screen.getByTestId('view-bar').dataset.canManage).toBe('false');
  });

  it('the creator keeps "Delete Workspace" and the view "×"', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockResolvedValue(INDEX);

    await mountOpen({ asUser: CREATOR, creator: CREATOR });

    expect(screen.getByTestId('remove-workspace')).toHaveTextContent('Delete Workspace');
    expect(screen.getByTestId('view-bar').dataset.canManage).toBe('true');
  });

  it('removing an L2 child issues the request for THAT child and the tab disappears', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockResolvedValue(INDEX);
    deleteViewChild.mockResolvedValue({ deleted: true });
    await mountOpen({
      asUser: CREATOR, creator: CREATOR,
      views: [{
        view_id: 'p1', type: 'search', table: 'ORDERS', field: 'amount',
        children: [{ view_id: 'p1_c1', type: 'script', script_name: '01.sql' }],
      }],
    });
    await screen.findByTestId('child-x');
    // the removal handler awaits its request before dropping the tab
    await actClick(screen.getByTestId('child-x'));

    // the child id is what is addressed — the parent id is not part of the URL
    expect(deleteViewChild).toHaveBeenCalledWith('ws1', 'p1', 'p1_c1');
    // the child is gone from the view tree, so its × is gone with it
    expect(screen.queryByTestId('child-x')).toBeNull();
  }, 20000);

  it('a participant has no L2 child × to press', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockResolvedValue(INDEX);
    await mountOpen({
      asUser: PARTICIPANT, creator: CREATOR,
      views: [{
        view_id: 'p1', type: 'search', table: 'ORDERS', field: 'amount',
        children: [{ view_id: 'p1_c1', type: 'script', script_name: '01.sql' }],
      }],
    });

    expect(screen.queryByTestId('child-x')).toBeNull();
    expect(deleteViewChild).not.toHaveBeenCalled();
  });
});

describe('open-existing — creator takes the same read-only path', () => {
  it('reads GET /tree + GET /index and never scans or indexes on a plain open', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    const pending = deferred();
    getWorkspaceIndex.mockImplementation(() => pending.promise);

    const done = mountOpen({ asUser: CREATOR, creator: CREATOR });

    // THIS is the fix: the creator used to fire POST /index here and spin
    // "analyzing" while every script re-parsed. A plain open reads instead —
    // no spinner, no scan, no index write.
    await vi.waitFor(() => expect(getWorkspaceIndex).toHaveBeenCalledWith('ws1'));
    expect(screen.getByTestId('progress-state').textContent).toBe('idle');

    await actResolve(pending, INDEX);
    await done;
    expect(screen.getByTestId('run-search')).toBeInTheDocument();

    expect(getWorkspaceTree).toHaveBeenCalledTimes(1);
    expect(scanWorkspace).not.toHaveBeenCalled();
    expect(indexWorkspace).not.toHaveBeenCalled();
  });

  it('falls back to scan → index when the workspace was never indexed', async () => {
    getWorkspaceTree.mockResolvedValue(null); // 409: no stored tree
    scanWorkspace.mockResolvedValue(TREE);
    const pending = deferred();
    indexWorkspace.mockImplementation(() => pending.promise);

    const done = mountOpen({ asUser: CREATOR, creator: CREATOR });

    // The honest spinner: a real build IS running on this path.
    await vi.waitFor(() => expect(indexWorkspace).toHaveBeenCalled());
    expect(screen.getByTestId('progress-state').textContent).toBe('progress:analyzing');

    await actResolve(pending, INDEX);
    await done;
    expect(screen.getByTestId('run-search')).toBeInTheDocument();

    expect(scanWorkspace).toHaveBeenCalledWith('ws1');
    expect(indexWorkspace).toHaveBeenCalledWith('ws1', ['a.sql']);
    expect(getWorkspaceIndex).not.toHaveBeenCalled();
  });

  it('builds once when a tree survives but the index caches are gone', async () => {
    // Wiped cache files with a surviving file_tree.json reads as
    // { indexed: false, ... } with empty indexes — the same never-indexed
    // case for a creator, not an empty debugger.
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockResolvedValue({ table_index: {}, field_index: {}, indexed: { indexed: false, script_count: 0 } });
    scanWorkspace.mockResolvedValue(TREE);
    indexWorkspace.mockResolvedValue(INDEX);

    await mountOpen({ asUser: CREATOR, creator: CREATOR });

    expect(indexWorkspace).toHaveBeenCalledWith('ws1', ['a.sql']);
    expect(screen.getByTestId('run-search')).toBeInTheDocument();
  });
});

describe('open-existing — catching up on changed scripts (P1 payload)', () => {
  // A catch-up is whatever P1 flags as IN FLIGHT (`catching_up`, top level on
  // GET /index; the `indexed.catching_up` spelling is read too). Each case
  // here is the SAME behaviour: the open lands, then search is held behind
  // the honest bar until the flag clears — and the refreshed index is what
  // comes back. A creator also waits for `freshness.stale` to flip, so the
  // settled payloads report stale:false.
  const FRESH_DONE = { changed_count: 0, changed_scripts: [], stale: false, indexed_at: '2026-08-31T09:00:00Z' };
  const CATCHUP_BY_FLAG = { ...INDEX, catching_up: true, freshness: { changed_count: 2, changed_scripts: ['b.sql', 'c.sql'], stale: true } };
  const CATCHUP_BY_NESTED_FLAG = { ...INDEX, indexed: { indexed: true, catching_up: true } };
  const CAUGHT_UP = { ...REINDEXED, catching_up: false, freshness: FRESH_DONE };

  /** Mount and wait until the open flow has CONSUMED its first index read,
   *  without assuming search is available (a catch-up withholds it). */
  async function mountWithIndex(indexResponse, { asUser = CREATOR, creator = CREATOR } = {}) {
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockResolvedValueOnce(indexResponse).mockResolvedValue(CAUGHT_UP);
    resumeWorkspace.mockResolvedValue({ state_version: 3, layouts: {}, creator_username: creator });
    listViews.mockResolvedValue({ views: [] });
    render(<DataFlowApp openWorkspaceId="ws1" username={asUser} />);
    await vi.waitFor(() => expect(getWorkspaceIndex).toHaveBeenCalledTimes(1));
  }

  it.each([
    ['a top-level catching_up flag', CATCHUP_BY_FLAG],
    ['the indexed.catching_up spelling', CATCHUP_BY_NESTED_FLAG],
  ])('%s holds search with the honest bar, then enables + refreshes', async (_name, payload) => {
    await mountWithIndex(payload);

    // Search withheld + one-line status + the same honest progress bar.
    expect(await screen.findByTestId('catchup-panel')).toHaveTextContent('Catching up');
    expect(screen.getByTestId('progress-state').textContent).toBe('progress:catching up');
    expect(screen.queryByTestId('run-search')).toBeNull();

    // Completion: the poller confirms via GET /index, refreshes the state and
    // hands search back.
    await vi.waitFor(() => expect(screen.getByTestId('run-search')).toBeInTheDocument(), { timeout: 10000 });

    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    expect(screen.getByTestId('progress-state').textContent).toBe('idle');
    // the REFRESHED index is what came back (the new table is searchable)
    expect(screen.getByTestId('run-search').dataset.tables).toBe('added,t');
    // reads only — the client never writes during someone else's catch-up
    expect(scanWorkspace).not.toHaveBeenCalled();
    expect(indexWorkspace).not.toHaveBeenCalled();
  }, 20000);

  it('a zero-diff open never shows the bar, never withholds search', async () => {
    await mountWithIndex(INDEX);
    expect(await screen.findByTestId('run-search')).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    expect(screen.getByTestId('progress-state').textContent).toBe('idle');
  });

  it('an older backend with no catch-up fields at all behaves identically', async () => {
    // INDEX carries no catching_up / freshness fields — the pre-P1 payload.
    await mountWithIndex(INDEX, { asUser: PARTICIPANT, creator: CREATOR });
    expect(await screen.findByTestId('run-search')).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
  });

  it('a reported diff whose re-index already finished does NOT hold search', async () => {
    // An explicit flag wins over a stale hint: P1 may report the diff
    // historically while the incremental run has already landed.
    await mountWithIndex({
      ...REINDEXED,
      catching_up: false,
      freshness: { changed_count: 4, changed_scripts: ['x.sql'], stale: false },
    });
    expect(await screen.findByTestId('run-search')).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    // no extra polling started — nothing to wait for
    expect(getWorkspaceIndex).toHaveBeenCalledTimes(1);
  });

  it('holds search for a participant too (the false no_matches is role-blind)', async () => {
    await mountWithIndex(CATCHUP_BY_FLAG, { asUser: PARTICIPANT, creator: CREATOR });

    expect(await screen.findByTestId('catchup-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('run-search')).toBeNull();

    await vi.waitFor(() => expect(screen.getByTestId('run-search')).toBeInTheDocument(), { timeout: 10000 });
    expect(screen.getByTestId('run-search').dataset.tables).toBe('added,t');
  }, 20000);
});

describe('catch-up poller — the hold is never forever (P4)', () => {
  // X2 review, two real holes in the poller's catch/exit:
  //   1. `catch { /* retry */ }` treated EVERY failure as transient — a
  //      workspace deleted mid-hold (404) or an expired session (401) polled
  //      every 1.5s FOREVER: catchup-panel forever, search withheld forever,
  //      nothing surfaced.
  //   2. the exit `catching_up || (canFix && stale)` never fires when a
  //      further file lands on disk DURING the window — stale stays true with
  //      nothing in flight, so the poller never exits and never re-fires.
  // Every case here mounts the SAME hold (the served index reports a
  // catch-up in flight) and then makes the POLLS misbehave.
  const FRESH = { changed_count: 0, changed_scripts: [], stale: false, indexed_at: '2026-08-31T09:00:00Z' };
  const STILL_STALE = { changed_count: 2, changed_scripts: ['b.sql', 'c.sql'], stale: true };
  const CAUGHT_UP = { ...REINDEXED, catching_up: false, freshness: FRESH };
  const GONE = Object.assign(new Error('Workspace not found'), { status: 404 });
  const UNAUTH = Object.assign(new Error('Not logged in'), { status: 401 });
  const NETERR = new TypeError('Failed to fetch');
  // the payload that ARMS the hold: a rebuild in flight over a stale index
  const HELD = { ...INDEX, catching_up: true, freshness: STILL_STALE };

  /** Mount a hold, then hand the poller a queued sequence of poll results.
   *  Fake timers run with shouldAdvanceTime so findBy* still works on real
   *  time while the 1.5s ticks can be fast-forwarded deterministically. */
  async function mountHeld({
    asUser = CREATOR, creator = CREATOR, served = HELD,
  } = {}) {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    getWorkspaceTree.mockResolvedValue(TREE);
    resumeWorkspace.mockResolvedValue({ state_version: 3, layouts: {}, creator_username: creator });
    listViews.mockResolvedValue({ views: [] });
    // the open's own read arms the hold; everything AFTER it is a poll tick
    getWorkspaceIndex.mockResolvedValueOnce(served);
    render(<DataFlowApp openWorkspaceId="ws1" username={asUser} />);
    await vi.waitFor(() => expect(getWorkspaceIndex).toHaveBeenCalledTimes(1));
    await screen.findByTestId('catchup-panel');
    return screen.queryByTestId('run-search');
  }

  /** Fast-forward n poll ticks (1.5s each) inside act. */
  async function ticks(n) {
    const { act } = await import('@testing-library/react');
    await act(async () => { await vi.advanceTimersByTimeAsync(n * 1500); });
  }

  it('a workspace deleted mid-hold (404) exits the hold honestly and stops polling', async () => {
    await mountHeld();
    getWorkspaceIndex.mockRejectedValue(GONE);

    await ticks(1);

    // the honest message, not an eternal bar
    expect(await screen.findByText(/no longer available — it was deleted/i)).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    // reset to the no-workspace state: search is NOT handed back on a ghost
    expect(screen.queryByTestId('run-search')).toBeNull();

    // and the poller STOPPED — a deleted workspace is never polled again
    const calls = getWorkspaceIndex.mock.calls.length;
    await ticks(6);
    expect(getWorkspaceIndex.mock.calls.length).toBe(calls);
  }, 20000);

  it('an expired session (401) punts to the login path — no banner, hold dropped', async () => {
    await mountHeld();
    getWorkspaceIndex.mockRejectedValue(UNAUTH);

    await ticks(1);

    // the shared 401 interceptor (E-M1) owns the session-expired surface, so
    // the poller just stops holding: no error banner on top of the login form
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    expect(document.querySelector('.error-banner')).toBeNull();

    const calls = getWorkspaceIndex.mock.calls.length;
    await ticks(6);
    expect(getWorkspaceIndex.mock.calls.length).toBe(calls);
  }, 20000);

  it('transient poll failures retry within the budget and then hand search back', async () => {
    await mountHeld();
    getWorkspaceIndex
      .mockRejectedValueOnce(NETERR)
      .mockRejectedValueOnce(NETERR)
      .mockRejectedValueOnce(NETERR)
      .mockResolvedValue(CAUGHT_UP);

    await ticks(4);

    // a blip is ridden out, then the hold ends the NORMAL way: refreshed
    // index, search back, no scary message
    expect(await screen.findByTestId('run-search')).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    expect(screen.getByTestId('run-search').dataset.tables).toBe('added,t');
    expect(document.querySelector('.error-banner')).toBeNull();
  }, 20000);

  it('a poll that never succeeds exits the hold after the bounded budget, not never', async () => {
    await mountHeld();
    getWorkspaceIndex.mockRejectedValue(NETERR);

    // the whole budget (20 ticks ≈ 30s) of failures, plus one
    await ticks(21);

    expect(await screen.findByText(/Index refresh did not complete/i)).toBeInTheDocument();
    // search is handed back on the stale-but-usable index (the failed-refresh
    // contract) instead of being withheld until the tab closes
    expect(screen.getByTestId('run-search')).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    // BOUNDED: one open read + the 21 budgeted polls — never an endless loop
    expect(getWorkspaceIndex.mock.calls.length).toBe(22);
  }, 20000);

  it('stale with nothing in flight re-fires POST /index exactly once, then hands search back', async () => {
    await mountHeld();
    // the run being waited for is OVER, but a further file landed during the
    // window: nothing is in flight and the index still reads stale
    getWorkspaceIndex.mockResolvedValue({ ...INDEX, catching_up: false, freshness: STILL_STALE });
    indexWorkspace.mockResolvedValue(CAUGHT_UP);

    await ticks(1);

    expect(await screen.findByTestId('run-search')).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    // ONE re-fire — the auto-trigger path, idempotent and cheap
    expect(indexWorkspace).toHaveBeenCalledTimes(1);
    expect(indexWorkspace).toHaveBeenCalledWith('ws1', ['a.sql']);

    // polling stopped: the hold did not simply keep spinning instead
    const calls = getWorkspaceIndex.mock.calls.length;
    await ticks(4);
    expect(getWorkspaceIndex.mock.calls.length).toBe(calls);
    expect(indexWorkspace).toHaveBeenCalledTimes(1);
  }, 20000);

  it('a re-fire that still reports stale exits honestly — never a re-fire loop', async () => {
    await mountHeld();
    getWorkspaceIndex.mockResolvedValue({ ...INDEX, catching_up: false, freshness: STILL_STALE });
    indexWorkspace.mockResolvedValue({ ...INDEX, catching_up: false, freshness: STILL_STALE });

    await ticks(3);

    expect(await screen.findByText(/Changes remain after the refresh/i)).toBeInTheDocument();
    // search re-enabled on the stale-but-served index, the hint alongside it
    expect(screen.getByTestId('run-search')).toBeInTheDocument();
    expect(screen.getByTestId('stale-hint')).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    // one re-fire per open — the second stale read is NOT a second POST
    expect(indexWorkspace).toHaveBeenCalledTimes(1);
  }, 20000);

  it('a corrupt/empty index payload at the exit does NOT switch search on blindly', async () => {
    // {} is what a corrupt/missing index cache reads as: applying it must not
    // mount a search panel whose scope is guaranteed no_matches
    await mountHeld();
    getWorkspaceIndex.mockResolvedValue({});

    await ticks(1);

    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    expect(screen.queryByTestId('run-search')).toBeNull();
  }, 20000);
});

describe('open-existing — stale index auto-triggers the refresh (P1 index_change)', () => {
  const STALE_CHANGE = {
    changed_scripts: ['b.sql', 'c.sql'], changed_count: 2, added_count: 1, removed_count: 0,
    schema_changed_count: 0, total: 103, stale: true, reason: 'scripts_changed',
  };
  const FRESH_FRESHNESS = { ...STALE_CHANGE, stale: false, changed_count: 0, changed_scripts: [], indexed_at: '2026-08-31T09:00:00Z' };

  it('a stale open fires POST /index, holds search, then serves the fresh index', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    const pending = deferred();
    indexWorkspace.mockImplementation(() => pending.promise);
    resumeWorkspace.mockResolvedValue({ state_version: 3, layouts: {}, creator_username: CREATOR, index_change: STALE_CHANGE });
    listViews.mockResolvedValue({ views: [] });
    render(<DataFlowApp openWorkspaceId="ws1" username={CREATOR} />);

    // THIS is the gap the auto-trigger closes: without it the open would land
    // straight on the stale index with search enabled.
    await vi.waitFor(() => expect(indexWorkspace).toHaveBeenCalledWith('ws1', ['a.sql']));
    expect(await screen.findByTestId('catchup-panel')).toBeInTheDocument();
    expect(screen.getByTestId('progress-state').textContent).toBe('progress:catching up');
    expect(screen.queryByTestId('run-search')).toBeNull();
    // GET /index is not even needed — the build response IS the fresh index.
    expect(getWorkspaceIndex).not.toHaveBeenCalled();

    await actResolve(pending, { ...INDEX, freshness: FRESH_FRESHNESS, catching_up: false });
    await vi.waitFor(() => expect(screen.getByTestId('run-search')).toBeInTheDocument());
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    expect(screen.getByTestId('progress-state').textContent).toBe('idle');
    // the refreshed index is what came back, and the timestamp from its own
    // freshness object drives the staleness line
    expect(screen.getByTestId('run-search').dataset.tables).toBe('t');
    expect(screen.getByTestId('indexed-at-echo').textContent).toBe('2026-08-31T09:00:00Z');
    expect(scanWorkspace).not.toHaveBeenCalled();
  }, 20000);

  it('a stale open detected on GET /index alone (no index_change on resume) fires too', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    resumeWorkspace.mockResolvedValue({ state_version: 3, layouts: {}, creator_username: CREATOR });
    getWorkspaceIndex.mockResolvedValueOnce({
      ...INDEX, catching_up: false, freshness: { ...STALE_CHANGE },
    }).mockResolvedValue({ ...INDEX, freshness: FRESH_FRESHNESS, catching_up: false });

    const done = mountOpen({ asUser: CREATOR, creator: CREATOR });
    await vi.waitFor(() => expect(indexWorkspace).toHaveBeenCalledWith('ws1', ['a.sql']));
    await done;
    expect(screen.getByTestId('run-search')).toBeInTheDocument();
  }, 20000);

  it('a zero-diff open fires no rebuild at all', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockResolvedValue({ ...INDEX, freshness: FRESH_FRESHNESS, catching_up: false });
    resumeWorkspace.mockResolvedValue({
      state_version: 3, layouts: {}, creator_username: CREATOR,
      index_change: { ...STALE_CHANGE, stale: false, changed_count: 0, changed_scripts: [] },
    });

    const done = mountOpen({ asUser: CREATOR, creator: CREATOR });
    await done;

    expect(screen.getByTestId('run-search')).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    expect(indexWorkspace).not.toHaveBeenCalled();
    expect(scanWorkspace).not.toHaveBeenCalled();
  });

  it('a participant on a stale workspace gets the hint, not a block or a write', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockResolvedValue({ ...INDEX, freshness: { ...STALE_CHANGE } });
    resumeWorkspace.mockResolvedValue({
      state_version: 3, layouts: {}, creator_username: CREATOR, index_change: STALE_CHANGE,
    });

    const done = mountOpen({ asUser: PARTICIPANT, creator: CREATOR });
    expect(await screen.findByTestId('stale-hint')).toHaveTextContent(/index may be outdated/i);
    await done;

    // search stays available (no hold), and the participant never writes
    expect(screen.getByTestId('run-search')).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    expect(indexWorkspace).not.toHaveBeenCalled();
  }, 20000);

  it('a failed refresh surfaces the error and still serves the (stale) index', async () => {
    getWorkspaceTree.mockResolvedValue(TREE);
    indexWorkspace.mockRejectedValue(new Error('disk full'));
    getWorkspaceIndex.mockResolvedValue(INDEX);
    resumeWorkspace.mockResolvedValue({
      state_version: 3, layouts: {}, creator_username: CREATOR, index_change: STALE_CHANGE,
    });
    listViews.mockResolvedValue({ views: [] });
    const done = screen.findByTestId('run-search');
    render(<DataFlowApp openWorkspaceId="ws1" username={CREATOR} />);

    await vi.waitFor(() => expect(indexWorkspace).toHaveBeenCalled());
    expect(await screen.findByText(/Index refresh failed.*disk full/)).toBeInTheDocument();
    await done;

    expect(screen.getByTestId('run-search')).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
  }, 20000);
});

describe('search during someone else’s catch-up — the 409 gate replays, never errors', () => {
  // MSC-1: the backend answers TWO different 409s on search. Only the index
  // catch-up ("Index is being updated for this workspace — retry in a
  // moment") is a hold-and-replay; the heavy gate's "system busy — please
  // wait" is a transient server condition that must surface, not spin.
  const CATCHUP_DETAIL = 'Index is being updated for this workspace — retry in a moment';
  // the same sentence with the ASCII dash the API has also spelled it with
  const CATCHUP_DETAIL_HYPHEN = 'Index is being updated for this workspace - retry in a moment';
  // the transient message a busy 409 must surface (matched as a substring —
  // the banner element carries a dismiss "x" beside the text)
  const BUSY_MESSAGE = /The service is busy — please retry in a moment/;

  function mountForSearch() {
    getWorkspaceTree.mockResolvedValue(TREE);
    getWorkspaceIndex.mockResolvedValue(INDEX);
    listViews.mockResolvedValue({ views: [] });
    resumeWorkspace.mockResolvedValue({ state_version: 3, layouts: {}, creator_username: CREATOR });
    return render(<DataFlowApp openWorkspaceId="ws1" username={CREATOR} />);
  }

  it.each([
    ['the served detail (em dash)', CATCHUP_DETAIL],
    ['the ASCII-dash spelling', CATCHUP_DETAIL_HYPHEN],
  ])('a catch-up 409 (%s) holds the search and replays it once the index is whole', async (_label, detail) => {
    mountForSearch();
    searchDataFlow
      .mockRejectedValueOnce(Object.assign(new Error(detail), { status: 409 }))
      .mockResolvedValue(SEARCH_RESULT);
    await screen.findByTestId('run-search');

    fireEvent.click(screen.getByTestId('run-search'));

    // the 409 is NOT surfaced as an error: the hold explains the wait instead
    expect(await screen.findByTestId('catchup-panel')).toBeInTheDocument();
    expect(screen.queryByText(detail)).toBeNull();
    expect(document.querySelector('.error-banner')).toBeNull();

    // the poller clears the hold → the SAME search is replayed and lands
    await vi.waitFor(() => expect(searchDataFlow).toHaveBeenCalledTimes(2), { timeout: 10000 });
    expect(await screen.findByText(/No reading flow for ORDERS\.amount/)).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    expect(searchDataFlow).toHaveBeenLastCalledWith('ws1', 'ORDERS', 'amount', 'downstream');
  }, 20000);

  it.each([
    ['the heavy gate’s detail', 'system busy — please wait'],
  ])('a busy 409 (%s) surfaces the transient message — no bar, no silent replay', async (_label, detail) => {
    mountForSearch();
    searchDataFlow
      .mockRejectedValueOnce(Object.assign(new Error(detail), { status: 409 }))
      .mockResolvedValue(SEARCH_RESULT);
    await screen.findByTestId('run-search');

    fireEvent.click(screen.getByTestId('run-search'));

    // the honest transient message, NOT the catch-up bar
    expect(await screen.findByText(BUSY_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
    expect(document.querySelector('.error-banner')).not.toBeNull();

    // nobody replays behind the user's back: one call, then it waits for them
    await new Promise(r => setTimeout(r, 100));
    expect(searchDataFlow).toHaveBeenCalledTimes(1);

    // the one manual retry is all it takes
    await actClick(screen.getByTestId('run-search'));
    expect(searchDataFlow).toHaveBeenCalledTimes(2);
    expect(await screen.findByText(/No reading flow for ORDERS\.amount/)).toBeInTheDocument();
    expect(screen.queryByText(BUSY_MESSAGE)).toBeNull();
  }, 20000);

  it('a busy 409 never holds search even when a catch-up is also armed', async () => {
    // the hold is armed first (a catch-up 409), the replay then meets a busy
    // server: the error surfaces and the hold is not silently re-armed.
    mountForSearch();
    searchDataFlow
      .mockRejectedValueOnce(Object.assign(new Error(CATCHUP_DETAIL), { status: 409 }))
      .mockRejectedValueOnce(Object.assign(new Error('system busy — please wait'), { status: 409 }))
      .mockResolvedValue(SEARCH_RESULT);
    await screen.findByTestId('run-search');

    fireEvent.click(screen.getByTestId('run-search'));
    expect(await screen.findByTestId('catchup-panel')).toBeInTheDocument();

    // the catch-up clears (GET /index stops reporting it) → the replay runs
    getWorkspaceIndex.mockResolvedValue(INDEX);
    await vi.waitFor(() => expect(searchDataFlow).toHaveBeenCalledTimes(2), { timeout: 10000 });
    expect(await screen.findByText(BUSY_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByTestId('catchup-panel')).toBeNull();
  }, 20000);
});

async function actResolve(pending, value) {
  const { act } = await import('@testing-library/react');
  await act(async () => { pending.resolve(value); });
}

/** Flush an async onClick (its handler awaits a request before updating state). */
async function actClick(el) {
  const { act } = await import('@testing-library/react');
  await act(async () => { fireEvent.click(el); });
}
