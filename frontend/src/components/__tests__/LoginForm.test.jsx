import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import LoginForm from '../LoginForm';
import { login } from '../../api/client';

vi.mock('../../api/client', () => ({
  login: vi.fn(),
}));

/**
 * R31/#293 — the login form embedded in the dataflow debugger's left panel.
 * The selectors asserted here (a <form>, username placeholder "you@hsbc.com",
 * one input[type="password"], submit button "Sign in") are the exact contract
 * the Playwright suite (tests/playwright/dataflow.spec.js login()) relies on —
 * they must never drift.
 */
describe('LoginForm', () => {
  const mockOnLogin = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders a form with the username/password fields and a "Sign in" submit button', () => {
    const { container } = render(<LoginForm onLogin={mockOnLogin} />);

    // Contract selectors (Playwright depends on these exact matches)
    expect(container.querySelector('form')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('you@hsbc.com')).toBeInTheDocument();
    expect(container.querySelector('input[type="password"]')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('calls onLogin with the trimmed username when api.login resolves', async () => {
    login.mockResolvedValueOnce({ username: 'alice@hsbc.com' });

    render(<LoginForm onLogin={mockOnLogin} />);
    fireEvent.change(screen.getByPlaceholderText('you@hsbc.com'), {
      target: { value: '  alice@hsbc.com  ' },
    });
    fireEvent.change(containerPasswordInput(), { target: { value: 'secret' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(login).toHaveBeenCalledTimes(1);
    expect(login).toHaveBeenCalledWith('alice@hsbc.com', 'secret');
    expect(mockOnLogin).toHaveBeenCalledTimes(1);
    expect(mockOnLogin).toHaveBeenCalledWith('alice@hsbc.com');
  });

  it('passes the api.login result username to onLogin when it differs from the input', async () => {
    login.mockResolvedValueOnce({ username: 'canonical@hsbc.com' });

    render(<LoginForm onLogin={mockOnLogin} />);
    fireEvent.change(screen.getByPlaceholderText('you@hsbc.com'), {
      target: { value: 'typed@hsbc.com' },
    });
    fireEvent.change(containerPasswordInput(), { target: { value: 'secret' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(mockOnLogin).toHaveBeenCalledWith('canonical@hsbc.com');
  });

  it('does NOT call onLogin and shows the error when api.login rejects', async () => {
    login.mockRejectedValueOnce(new Error('bad credentials'));

    render(<LoginForm onLogin={mockOnLogin} />);
    fireEvent.change(screen.getByPlaceholderText('you@hsbc.com'), {
      target: { value: 'alice@hsbc.com' },
    });
    fireEvent.change(containerPasswordInput(), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('bad credentials')).toBeInTheDocument();
    expect(mockOnLogin).not.toHaveBeenCalled();
  });
});

function containerPasswordInput() {
  return document.querySelector('input[type="password"]');
}
