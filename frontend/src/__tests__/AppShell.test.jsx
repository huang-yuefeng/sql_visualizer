import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import AppShell from '../AppShell';
import * as api from '../api/client';

vi.mock('../api/client', () => ({
  getMe: vi.fn(),
  onSessionExpired: vi.fn(() => () => {}),
  logout: vi.fn(),
}));

// Heavy / canvas-based children are mocked — this suite asserts the shell
// BRANCHING (logged-in → always DataFlowApp), not the debugger internals.
vi.mock('../App', () => ({ default: () => <div data-testid="mock-app">app</div> }));
vi.mock('../DataFlowApp', () => ({
  default: (props) => (
    <div
      data-testid="dataflow-app"
      data-ws={props.openWorkspaceId || ''}
      data-username={props.username || ''}
    >
      dataflow
    </div>
  ),
}));
vi.mock('../components/MyWorkspaces', () => ({ default: () => <div data-testid="my-workspaces">ws</div> }));
vi.mock('../components/LoginForm', () => ({ default: () => <div data-testid="login-form">login</div> }));
vi.mock('../components/NotificationBell', () => ({ default: () => null }));
vi.mock('../components/HistoryPanel', () => ({ default: () => null }));

/**
 * T8 (#295) — the standalone MyWorkspaces dashboard is RETIRED. When logged
 * in, the dataflow tab ALWAYS renders <DataFlowApp/> (workspace management
 * lives in the debugger's left panel). The logged-out branch (login form in
 * the left panel) is unchanged.
 */
describe('AppShell — T8 (#295) always renders DataFlowApp when logged in', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    api.getMe.mockResolvedValue({ username: 'alice@hsbc.com' });
  });

  it('renders DataFlowApp (not the standalone MyWorkspaces dashboard) when logged in with NO workspace', async () => {
    render(<AppShell />);
    expect(await screen.findByTestId('dataflow-app')).toBeInTheDocument();
    // The retired full-dashboard component must never mount on its own.
    expect(screen.queryByTestId('my-workspaces')).not.toBeInTheDocument();
  });

  it('passes the username and openWorkspaceId (from ?ws=) into DataFlowApp', async () => {
    window.history.replaceState({}, '', '/?ws=ws123');
    render(<AppShell />);
    const el = await screen.findByTestId('dataflow-app');
    await waitFor(() => expect(el.getAttribute('data-username')).toBe('alice@hsbc.com'));
    await waitFor(() => expect(el.getAttribute('data-ws')).toBe('ws123'));
  });

  it('still renders the login form in the left panel when logged out', async () => {
    api.getMe.mockResolvedValueOnce(null);
    render(<AppShell />);
    expect(await screen.findByTestId('login-form')).toBeInTheDocument();
    expect(screen.queryByTestId('dataflow-app')).not.toBeInTheDocument();
  });

  it('registers the E-M1 session-expired interceptor on mount', async () => {
    render(<AppShell />);
    await screen.findByTestId('dataflow-app');
    expect(api.onSessionExpired).toHaveBeenCalledTimes(1);
    expect(api.onSessionExpired).toHaveBeenCalledWith(expect.any(Function));
  });
});
