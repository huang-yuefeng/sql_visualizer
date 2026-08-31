import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ViewBar from '../ViewBar';

// ViewBar role gate + L2 child removal wiring (v3.3.194).
//
// The per-view close button and the L2 child close button are creator-only
// server-side (DELETE /views/{id} is #272-gated), so canManageViews={false}
// renders no destructive control at all -- it used to 403 silently for
// participants. The child close button is wired to DELETE /views/{childId}
// (see api/__tests__/client.test.js); here we assert the ViewBar hands the
// right ids to that call.

const CHILD = { view_id: 'p1_c1', type: 'script', script_name: '01.sql', label: '01.sql' };
const VIEWS = [{
  view_id: 'p1',
  table: 'ORDERS',
  field: 'amount',
  script_ids: ['a.sql'],
  children: [CHILD],
}];

function setup(props) {
  const handlers = {
    onRemove: vi.fn(),
    onRemoveChild: vi.fn(),
  };
  const utils = render(
    <ViewBar
      views={VIEWS}
      activeViewId="p1"
      canManageViews={props.canManageViews !== false}
      onRemove={handlers.onRemove}
      onRemoveChild={handlers.onRemoveChild}
    />
  );
  return { handlers, utils };
}

describe('ViewBar - creator can manage views', () => {
  it('renders both close controls and passes the view id on remove', () => {
    const { handlers } = setup({});

    expect(screen.getByTitle('Remove view')).toBeInTheDocument();
    expect(screen.getByTitle('Close L2')).toBeInTheDocument();

    fireEvent.click(screen.getByTitle('Remove view'));
    expect(handlers.onRemove).toHaveBeenCalledWith('p1');
  });

  it('the child close control asks to remove THAT child of ITS parent', () => {
    const { handlers } = setup({});

    fireEvent.click(screen.getByTitle('Close L2'));
    expect(handlers.onRemoveChild).toHaveBeenCalledWith('p1', 'p1_c1');
  });
});

describe('ViewBar - a participant sees no destructive controls', () => {
  it('renders neither close control and never fires a removal', () => {
    const { handlers } = setup({ canManageViews: false });

    expect(screen.getByText('ORDERS.amount')).toBeInTheDocument();
    expect(screen.queryByTitle('Remove view')).toBeNull();
    expect(screen.queryByTitle('Close L2')).toBeNull();

    fireEvent.click(screen.getByText('ORDERS.amount'));
    expect(handlers.onRemove).not.toHaveBeenCalled();
    expect(handlers.onRemoveChild).not.toHaveBeenCalled();
  });
});
