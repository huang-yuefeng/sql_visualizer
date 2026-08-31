import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import WorkspacePanel, { formatIndexedAge } from '../WorkspacePanel';

/**
 * P2 fast-open (v3.3.194) — the in-workspace panel carries the index
 * staleness line "Indexed <relative time>", rendered only when the index
 * payload actually carries a timestamp (P1 owns that field; it may not exist
 * yet — absence must render nothing, never a guess).
 *
 * There is deliberately NO manual re-index control here (user ruling
 * 2026-08-31): the automatic content-hash catch-up covers changed scripts
 * and the open path falls back to a full build when caches are gone.
 */

const base = {
  wsId: 'ws-1234',
  loading: false,
  progress: null,
  onUpload: vi.fn(),
  onDelete: vi.fn(),
  onError: vi.fn(),
  showUploads: false,
};

function isoAgo(secs, now = Date.now()) {
  return new Date(now - secs * 1000).toISOString();
}

describe('WorkspacePanel — the removal control says what it does for THIS role', () => {
  it('the creator deletes the workspace for everyone', () => {
    render(<WorkspacePanel {...base} isCreator />);
    const btn = screen.getByTestId('workspace-remove-btn');
    expect(btn).toHaveTextContent('Delete Workspace');
    expect(btn).toHaveAttribute('title', 'Delete this workspace and its files for everyone');
  });

  it('a participant only removes her own link, and the label says so', () => {
    render(<WorkspacePanel {...base} isCreator={false} />);
    const btn = screen.getByTestId('workspace-remove-btn');
    expect(btn).toHaveTextContent('Remove from my list');
    expect(btn).toHaveAttribute('title', 'Remove this shared workspace from your list only — the files stay');
  });

  it('no manual re-index control exists for anyone', () => {
    render(<WorkspacePanel {...base} isCreator />);
    expect(screen.queryByTestId('reindex-btn')).toBeNull();
  });

  it('a zero-total progress bar renders 0%, never NaN%', () => {
    const { container } = render(
      <WorkspacePanel {...base} progress={{ current: 0, total: 0, phase: 'catching up' }} />
    );
    expect(container.querySelector('.progress-fill').style.width).toBe('0%');
    expect(screen.getByText('0/0 catching up')).toBeInTheDocument();
  });
});

describe('WorkspacePanel — staleness line renders only on real data', () => {
  it('shows "Indexed just now" for a fresh timestamp', () => {
    render(<WorkspacePanel {...base} indexedAt={isoAgo(5)} />);
    expect(screen.getByTestId('indexed-at')).toHaveTextContent('Indexed just now');
  });

  it('shows minutes / hours / days, then falls back to the date', () => {
    const now = Date.now();
    const { rerender } = render(<WorkspacePanel {...base} indexedAt={isoAgo(90, now)} />);
    expect(screen.getByTestId('indexed-at')).toHaveTextContent('Indexed 1m ago');
    rerender(<WorkspacePanel {...base} indexedAt={isoAgo(3 * 3600, now)} />);
    expect(screen.getByTestId('indexed-at')).toHaveTextContent('Indexed 3h ago');
    rerender(<WorkspacePanel {...base} indexedAt={isoAgo(5 * 86400, now)} />);
    expect(screen.getByTestId('indexed-at')).toHaveTextContent('Indexed 5d ago');
    rerender(<WorkspacePanel {...base} indexedAt={isoAgo(90 * 86400, now)} />);
    expect(screen.getByTestId('indexed-at').textContent).toMatch(/Indexed \d{1,2}\/\d{1,2}\/\d{4}/);
  });

  it('renders nothing when the payload carries no timestamp (P1 field pending)', () => {
    render(<WorkspacePanel {...base} indexedAt={null} />);
    expect(screen.queryByTestId('indexed-at')).toBeNull();
  });
});

describe('formatIndexedAge — defensive on junk and clock skew', () => {
  it('returns null for absent/unparseable input', () => {
    expect(formatIndexedAge(null)).toBeNull();
    expect(formatIndexedAge(undefined)).toBeNull();
    expect(formatIndexedAge('')).toBeNull();
    expect(formatIndexedAge('not-a-date')).toBeNull();
  });

  it('never reports a negative age (server clock ahead)', () => {
    const future = new Date(Date.now() + 600_000).toISOString();
    expect(formatIndexedAge(future)).toBe('just now');
  });
});
