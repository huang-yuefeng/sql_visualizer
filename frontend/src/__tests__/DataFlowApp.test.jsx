import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import DataFlowApp from '../DataFlowApp';

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
vi.mock('../components/FilterPanel', () => ({ default: () => null }));
vi.mock('../components/ViewBar', () => ({ default: () => null }));
vi.mock('../components/ResolutionReport', () => ({ default: () => null }));
vi.mock('../components/DataFlowGraph', () => ({ default: () => null }));
vi.mock('../components/SqlPanel', () => ({ default: () => null }));
vi.mock('../components/LogPanel', () => ({ default: () => null }));
vi.mock('../api/client', () => ({
  closeWorkspace: vi.fn(),
  uploadWorkspace: vi.fn(),
  listViews: vi.fn(),
  saveLayout: vi.fn(),
  removeFromMyHistory: vi.fn(),
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
