import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import FilterPanel from '../FilterPanel';
import { uploadFilterConfig } from '../../api/client';

vi.mock('../../api/client', () => ({
  uploadFilterConfig: vi.fn(),
}));

function mountPanel() {
  return render(
    <FilterPanel
      wsId="ws1"
      tableIndex={{}}
      fieldIndex={{}}
      onSearch={() => {}}
      loading={false}
    />
  );
}

describe('FilterPanel — F4/R2 warning banner', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it('renders the warning banner when the filter payload carries a warning', async () => {
    uploadFilterConfig.mockResolvedValue({
      filtered: true,
      table_count: 12,
      field_count: 80,
      warning: '5 tables dropped by the filter',
      ignored_tables: ['sys_meta', 'logs'],
    });
    mountPanel();

    // The upload inputs are always visible — no Narrow Index dropdown to expand
    const fileInputs = screen.getAllByLabelText(/SCRIPT_NAME, TABLE_NAME/i);
    fireEvent.change(fileInputs[0], {
      target: { files: [new File(['s,orders\n'], 'st.csv')] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Filter' }));

    expect(await screen.findByText('5 tables dropped by the filter')).toBeInTheDocument();
    // ignored tables summary follows the warning text
    expect(await screen.findByText(/2 tables ignored:/)).toBeInTheDocument();
    expect(uploadFilterConfig).toHaveBeenCalledTimes(1);
    const [ws, stFile, tcFile] = uploadFilterConfig.mock.calls[0];
    expect(ws).toBe('ws1');
    expect(stFile).toBeInstanceOf(File);
    expect(stFile.name).toBe('st.csv');
    expect(tcFile).toBeUndefined();
  });

  it('D2: renders the ignored-rows line when the payload carries ignored_rows', async () => {
    uploadFilterConfig.mockResolvedValue({
      filtered: true,
      table_count: 12,
      field_count: 80,
      warning: '5 tables dropped by the filter',
      ignored_tables: ['sys_meta'],
      ignored_rows: 120,
    });
    mountPanel();

    const fileInputs = screen.getAllByLabelText(/SCRIPT_NAME, TABLE_NAME/i);
    fireEvent.change(fileInputs[0], {
      target: { files: [new File(['s,orders\n'], 'st.csv')] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Filter' }));

    expect(await screen.findByText('5 tables dropped by the filter')).toBeInTheDocument();
    expect(await screen.findByText('120 rows ignored')).toBeInTheDocument();
    expect(await screen.findByText(/1 table ignored:/)).toBeInTheDocument();
  });

  it('renders no warning banner without a payload warning', async () => {
    uploadFilterConfig.mockResolvedValue({
      filtered: true,
      table_count: 12,
      field_count: 80,
      warning: null,
      ignored_tables: [],
    });
    mountPanel();

    const fileInputs = screen.getAllByLabelText(/SCRIPT_NAME, TABLE_NAME/i);
    fireEvent.change(fileInputs[0], {
      target: { files: [new File(['s,orders\n'], 'st.csv')] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Filter' }));

    // filter-area status reflects the active filter once the upload resolves
    expect(await screen.findByText('ACTIVE — 12 tables, 80 fields')).toBeInTheDocument();
    expect(screen.queryByText(/⚠️/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ignored:/)).not.toBeInTheDocument();
  });
});

describe('FilterPanel — two-area layout + direction', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it('renders distinct Filter and Search areas with upload inputs visible by default', () => {
    mountPanel();
    const filterArea = screen.getByTestId('filter-area');
    const searchArea = screen.getByTestId('search-area');
    expect(filterArea).toBeInTheDocument();
    expect(searchArea).toBeInTheDocument();
    expect(filterArea.querySelector('.area-title')).toHaveTextContent('Filter');
    expect(searchArea.querySelector('.area-title')).toHaveTextContent('Search');
    // upload inputs are visible without expanding anything (no Narrow Index banner)
    expect(screen.getAllByLabelText(/SCRIPT_NAME, TABLE_NAME/i).length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText(/SYSTEM, TABLE_NAME, COL_NAME, COL_COMMENT/i).length).toBeGreaterThan(0);
    expect(screen.queryByText('Narrow Index (optional)')).not.toBeInTheDocument();
  });

  it('search click calls onSearch with downstream (R38: the only direction)', () => {
    const onSearch = vi.fn();
    render(
      <FilterPanel
        wsId="ws1"
        username="alice@hsbc.com"
        tableIndex={{ orders: { fields: ['amount'] } }}
        fieldIndex={{ amount: { tables: ['orders'] } }}
        onSearch={onSearch}
        loading={false}
      />
    );
    fireEvent.change(screen.getByPlaceholderText(/Type table name/), { target: { value: 'orders' } });
    fireEvent.change(screen.getByPlaceholderText(/Type field name/), { target: { value: 'amount' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(onSearch).toHaveBeenCalledWith('orders', 'amount', 'downstream');
  });

  it('R38: renders NO direction toggle — downstream is the only direction', () => {
    render(
      <FilterPanel
        wsId="ws1"
        username="alice@hsbc.com"
        tableIndex={{}}
        fieldIndex={{}}
        onSearch={() => {}}
        loading={false}
      />
    );
    expect(screen.queryByRole('button', { name: /Upstream/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Downstream/ })).toBeNull();
    expect(screen.queryByText('Direction')).toBeNull();
  });
});

describe('FilterPanel — username-namespaced localStorage (E-M2/#277)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  function mountUser(username) {
    return render(
      <FilterPanel
        wsId="ws1"
        username={username}
        tableIndex={{ orders: { fields: ['amount'] }, a: { fields: ['f'] } }}
        fieldIndex={{ amount: { tables: ['orders'] }, f: { tables: ['a'] } }}
        onSearch={() => {}}
        loading={false}
      />
    );
  }

  it('saves search history under the per-user key, never the old global key', () => {
    const onSearch = vi.fn();
    render(
      <FilterPanel
        wsId="ws1"
        username="alice@hsbc.com"
        tableIndex={{ orders: { fields: ['amount'] } }}
        fieldIndex={{ amount: { tables: ['orders'] } }}
        onSearch={onSearch}
        loading={false}
      />
    );
    fireEvent.change(screen.getByPlaceholderText(/Type table name/), { target: { value: 'orders' } });
    fireEvent.change(screen.getByPlaceholderText(/Type field name/), { target: { value: 'amount' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    expect(onSearch).toHaveBeenCalledWith('orders', 'amount', 'downstream');
    const stored = JSON.parse(window.localStorage.getItem('df_search_history:alice@hsbc.com'));
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({ table: 'orders', field: 'amount' });
    // the legacy global key must never be written anymore
    expect(window.localStorage.getItem('df_search_history')).toBeNull();
  });

  it('does not leak another user\'s pins into the panel', () => {
    // user B's pins live under their own key — user A must not see them
    window.localStorage.setItem(
      'df_pinned_searches:bob@hsbc.com',
      JSON.stringify([{ table: 'bob_t', field: 'bob_f' }])
    );
    mountUser('alice@hsbc.com');
    expect(screen.queryByText('bob_t.bob_f')).not.toBeInTheDocument();
  });

  it('restores this user\'s own pins from the per-user key', () => {
    window.localStorage.setItem(
      'df_pinned_searches:alice@hsbc.com',
      JSON.stringify([{ table: 'orders', field: 'amount' }])
    );
    mountUser('alice@hsbc.com');
    expect(screen.getByText('orders.amount')).toBeInTheDocument();
  });
});

describe('FilterPanel — typo-tolerant autocomplete (Fix B)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  function mountTypo() {
    return render(
      <FilterPanel
        wsId="ws1"
        tableIndex={{
          east5_stzfxxb: { fields: ['east5_stzfxxb', 'stzfje'] },
        }}
        fieldIndex={{
          east5_stzfxxb: { tables: ['east5_stzfxxb'], scripts: ['s'] },
          stzfje: { tables: ['east5_stzfxxb'], scripts: ['s'] },
        }}
        onSearch={() => {}}
        loading={false}
      />
    );
  }

  it('surfaces the one-char-off field name in the popup', () => {
    mountTypo();
    const fieldInput = screen.getByPlaceholderText(/Type field name/);
    fireEvent.change(fieldInput, { target: { value: 'EAST5_SSTZFXXB' } });
    fireEvent.focus(fieldInput);
    // query has an extra S — the real field east5_stzfxxb is suggested via
    // the Levenshtein<=1 fallback, not substring (which returns nothing).
    expect(screen.getByText('east5_stzfxxb')).toBeInTheDocument();
  });

  it('keeps plain substring suggestions (no fallback when >=2 hits)', () => {
    mountTypo();
    const fieldInput = screen.getByPlaceholderText(/Type field name/);
    fireEvent.change(fieldInput, { target: { value: 'stzf' } });
    fireEvent.focus(fieldInput);
    expect(screen.getByText('east5_stzfxxb')).toBeInTheDocument();
    expect(screen.getByText('stzfje')).toBeInTheDocument();
  });
});
