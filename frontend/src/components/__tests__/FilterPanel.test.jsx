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

// F-B2 (S4 finding 9, 2026-08-29): the suggestions dropdown is an overlay that
// hangs below its own input — after typing a COMPLETE table name it covered
// the Field input and ate the click aimed at it. Once the typed name resolves
// to an index key, the dropdown must be gone.
describe('FilterPanel — dropdown closes once the typed name resolves (F-B2)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  function mountDrop() {
    return render(
      <FilterPanel
        wsId="ws1"
        tableIndex={{ TEMP_RFN: { fields: ['dkjjbm'] } }}
        fieldIndex={{ dkjjbm: { tables: ['TEMP_RFN'] } }}
        onSearch={() => {}}
        loading={false}
      />
    );
  }

  it('a complete table name renders no dropdown — the Field input stays clickable', () => {
    mountDrop();
    const tableInput = screen.getByPlaceholderText(/Type table name/);
    fireEvent.change(tableInput, { target: { value: 'TEMP_RFN' } });
    fireEvent.focus(tableInput);
    expect(document.querySelector('.autocomplete-dropdown')).toBeNull();
    expect(tableInput).toBeVisible();
  });

  it('a resolved wrong-case name also closes the table dropdown', () => {
    mountDrop();
    const tableInput = screen.getByPlaceholderText(/Type table name/);
    fireEvent.change(tableInput, { target: { value: 'temp_rfn' } });
    expect(document.querySelector('.autocomplete-dropdown')).toBeNull();
  });

  it('an incomplete name keeps the dropdown open (browsing still works)', () => {
    mountDrop();
    const tableInput = screen.getByPlaceholderText(/Type table name/);
    fireEvent.change(tableInput, { target: { value: 'TEMP' } });
    fireEvent.focus(tableInput);
    expect(document.querySelector('.autocomplete-dropdown')).not.toBeNull();
    expect(screen.getByText('TEMP_RFN')).toBeInTheDocument();
  });

  it('the same contract holds for the field dropdown', () => {
    mountDrop();
    const fieldInput = screen.getByPlaceholderText(/Type field name/);
    fireEvent.change(fieldInput, { target: { value: 'dkjjbm' } });
    fireEvent.focus(fieldInput);
    expect(document.querySelector('.autocomplete-dropdown')).toBeNull();
    fireEvent.change(fieldInput, { target: { value: 'dkjj' } });
    fireEvent.focus(fieldInput);
    expect(document.querySelector('.autocomplete-dropdown')).not.toBeNull();
  });
});

describe('FilterPanel — F5: case-insensitive search + inline missing message', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  // The audit F5 index shape: uppercase table key, mixed-case field keys.
  function mountF5(onSearch) {
    return render(
      <FilterPanel
        wsId="ws1"
        username="alice@hsbc.com"
        tableIndex={{ TEMP_RFN: { fields: ['dkjjbm', 'IGNDA'], scripts: ['rfn.sql'] } }}
        fieldIndex={{ dkjjbm: { tables: ['TEMP_RFN'], scripts: ['rfn.sql'] } }}
        onSearch={onSearch}
        loading={false}
      />
    );
  }

  it('searches with the canonical index key when typed in another casing', () => {
    const onSearch = vi.fn();
    mountF5(onSearch);
    fireEvent.change(screen.getByPlaceholderText(/Type table name/), { target: { value: 'temp_rfn' } });
    fireEvent.change(screen.getByPlaceholderText(/Type field name/), { target: { value: 'DKJJBM' } });
    // both names resolve case-insensitively — no missing messages
    expect(screen.queryByTestId('table-missing-msg')).toBeNull();
    expect(screen.queryByTestId('field-missing-msg')).toBeNull();
    expect(screen.getByRole('button', { name: 'Search' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(onSearch).toHaveBeenCalledWith('TEMP_RFN', 'dkjjbm', 'downstream');
  });

  it('echoes the canonical spelling into the inputs after the search', () => {
    const onSearch = vi.fn();
    mountF5(onSearch);
    fireEvent.change(screen.getByPlaceholderText(/Type table name/), { target: { value: 'temp_rfn' } });
    fireEvent.change(screen.getByPlaceholderText(/Type field name/), { target: { value: 'DKJJBM' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(screen.getByPlaceholderText(/Type table name/).value).toBe('TEMP_RFN');
    expect(screen.getByPlaceholderText(/Type field name/).value).toBe('dkjjbm');
  });

  it('Enter fires the search in wrong casing (was a silent no-op)', () => {
    const onSearch = vi.fn();
    mountF5(onSearch);
    fireEvent.change(screen.getByPlaceholderText(/Type table name/), { target: { value: 'temp_rfn' } });
    const fieldInput = screen.getByPlaceholderText(/Type field name/);
    fireEvent.change(fieldInput, { target: { value: 'dkjjbm' } });
    fireEvent.keyDown(fieldInput, { key: 'Enter' });
    expect(onSearch).toHaveBeenCalledWith('TEMP_RFN', 'dkjjbm', 'downstream');
  });

  it('shows the inline message for a field no casing matches — never a silent no-op', () => {
    const onSearch = vi.fn();
    mountF5(onSearch);
    fireEvent.change(screen.getByPlaceholderText(/Type table name/), { target: { value: 'temp_rfn' } });
    const fieldInput = screen.getByPlaceholderText(/Type field name/);
    fireEvent.change(fieldInput, { target: { value: 'pay_mode' } });
    expect(screen.getByTestId('field-missing-msg'))
      .toHaveTextContent(/no such table\.field in the index — check spelling/i);
    expect(screen.queryByTestId('table-missing-msg')).toBeNull();
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled();
    fireEvent.keyDown(fieldInput, { key: 'Enter' });
    expect(onSearch).not.toHaveBeenCalled();
  });

  it('shows the table-flavored message for an unknown table', () => {
    mountF5(vi.fn());
    fireEvent.change(screen.getByPlaceholderText(/Type table name/), { target: { value: 'no_such_table' } });
    expect(screen.getByTestId('table-missing-msg'))
      .toHaveTextContent(/no such table in the index — check spelling/i);
  });
});

// R3 finding 5 (2026-08-29): the ☆ pin pinned the RAW TYPED strings, so one
// search could produce two pins — ☆ on the typed casing, then doSearch echoes
// the canonical spelling into the inputs and a second ☆ stored the same pair
// again. Pin and compare the CANONICAL index key.
describe('FilterPanel — pins use the canonical index key (R3 finding 5)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  function mountCi(onSearch) {
    return render(
      <FilterPanel
        wsId="ws1"
        username="alice@hsbc.com"
        tableIndex={{ TEMP_RFN: { fields: ['dkjjbm', 'IGNDA'], scripts: ['rfn.sql'] } }}
        fieldIndex={{ dkjjbm: { tables: ['TEMP_RFN'], scripts: ['rfn.sql'] } }}
        onSearch={onSearch}
        loading={false}
      />
    );
  }

  it('stores the canonical key when the name was typed in another casing', () => {
    mountCi(vi.fn());
    fireEvent.change(screen.getByPlaceholderText(/Type table name/), { target: { value: 'temp_rfn' } });
    fireEvent.change(screen.getByPlaceholderText(/Type field name/), { target: { value: 'DKJJBM' } });
    fireEvent.click(screen.getByRole('button', { name: '☆' }));

    expect(screen.getByText('TEMP_RFN.dkjjbm')).toBeInTheDocument();
    const pins = JSON.parse(window.localStorage.getItem('df_pinned_searches:alice@hsbc.com'));
    expect(pins).toEqual([{ table: 'TEMP_RFN', field: 'dkjjbm' }]);
  });

  it('the CI-search echo cannot create a duplicate pin', () => {
    mountCi(vi.fn());
    const tableInput = screen.getByPlaceholderText(/Type table name/);
    const fieldInput = screen.getByPlaceholderText(/Type field name/);
    fireEvent.change(tableInput, { target: { value: 'temp_rfn' } });
    fireEvent.change(fieldInput, { target: { value: 'DKJJBM' } });
    // pin BEFORE the search echoed the canonical spelling into the inputs
    fireEvent.click(screen.getByRole('button', { name: '☆' }));
    // the search runs and echoes the canonical key into both inputs
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(tableInput.value).toBe('TEMP_RFN');
    expect(fieldInput.value).toBe('dkjjbm');

    // the same pair is already pinned → the button reads ★ and clicking it
    // UNPINS instead of storing a second, differently-cased copy
    expect(screen.getByRole('button', { name: '★' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '★' }));
    expect(screen.queryByText('TEMP_RFN.dkjjbm')).not.toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem('df_pinned_searches:alice@hsbc.com')))
      .toEqual([]);
  });

  it('pins an unresolvable pair as typed (no canonical form to resolve to)', () => {
    const onSearch = vi.fn();
    render(
      <FilterPanel
        wsId="ws1"
        username="alice@hsbc.com"
        tableIndex={{ TEMP_RFN: { fields: ['dkjjbm'], scripts: ['rfn.sql'] } }}
        fieldIndex={{ dkjjbm: { tables: ['TEMP_RFN'], scripts: ['rfn.sql'] } }}
        onSearch={onSearch}
        loading={false}
      />
    );
    fireEvent.change(screen.getByPlaceholderText(/Type table name/), { target: { value: 'TEMP_RFN' } });
    fireEvent.change(screen.getByPlaceholderText(/Type field name/), { target: { value: 'nope' } });
    expect(screen.getByTestId('field-missing-msg')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '☆' }));
    expect(JSON.parse(window.localStorage.getItem('df_pinned_searches:alice@hsbc.com')))
      .toEqual([{ table: 'TEMP_RFN', field: 'nope' }]);
  });
});

// V2-N3 (2026-08-29): the missing-name message used to fire off the raw
// unresolved prefix, so typing `bdm_acc` rendered 12 live suggestions AND
// "no such table in the index" at once. The message is the terminal state of
// a name that resolves to nothing — the exact complement of the dropdown's
// own render condition (live suggestions), and of the F-B2 close-on-resolve
// rule (a resolved name shows neither).
describe('FilterPanel — missing-message waits for a dead-end name (V2-N3)', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  function mountMissing() {
    return render(
      <FilterPanel
        wsId="ws1"
        tableIndex={{ TEMP_RFN: { fields: ['dkjjbm'] } }}
        fieldIndex={{ dkjjbm: { tables: ['TEMP_RFN'] } }}
        onSearch={() => {}}
        loading={false}
      />
    );
  }

  it('a mid-prefix table with live suggestions shows the dropdown, NOT the message', () => {
    mountMissing();
    const tableInput = screen.getByPlaceholderText(/Type table name/);
    fireEvent.change(tableInput, { target: { value: 'TEMP' } });
    fireEvent.focus(tableInput);
    // the dropdown is the answer at this point …
    expect(document.querySelector('.autocomplete-dropdown')).not.toBeNull();
    expect(screen.getByText('TEMP_RFN')).toBeInTheDocument();
    // … and the "no such table" claim is nowhere on screen
    expect(screen.queryByTestId('table-missing-msg')).toBeNull();
  });

  it('the field message stays silent while the field prefix still suggests', () => {
    mountMissing();
    fireEvent.change(screen.getByPlaceholderText(/Type table name/), { target: { value: 'TEMP_RFN' } });
    const fieldInput = screen.getByPlaceholderText(/Type field name/);
    fireEvent.change(fieldInput, { target: { value: 'dkj' } });
    fireEvent.focus(fieldInput);
    expect(document.querySelector('.autocomplete-dropdown')).not.toBeNull();
    expect(screen.queryByTestId('field-missing-msg')).toBeNull();
  });

  it('a dead-end prefix (no suggestion left) still gets the message', () => {
    mountMissing();
    const tableInput = screen.getByPlaceholderText(/Type table name/);
    fireEvent.change(tableInput, { target: { value: 'zzz_no_such_table' } });
    fireEvent.focus(tableInput);
    expect(document.querySelector('.autocomplete-dropdown')).toBeNull();
    expect(screen.getByTestId('table-missing-msg'))
      .toHaveTextContent(/no such table in the index — check spelling/i);
  });

  it('message and dropdown are exact complements while typing and editing back', () => {
    mountMissing();
    const fieldInput = screen.getByPlaceholderText(/Type field name/);
    fireEvent.change(fieldInput, { target: { value: 'dk' } });
    fireEvent.focus(fieldInput);
    expect(screen.queryByTestId('field-missing-msg')).toBeNull();
    // dead end → message
    fireEvent.change(fieldInput, { target: { value: 'dkz' } });
    expect(screen.getByTestId('field-missing-msg')).toBeInTheDocument();
    // one more char makes it resolvable again → neither dropdown nor message
    fireEvent.change(fieldInput, { target: { value: 'dkjjbm' } });
    expect(screen.queryByTestId('field-missing-msg')).toBeNull();
    expect(document.querySelector('.autocomplete-dropdown')).toBeNull();
  });
});
