import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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

    // Expand the filter panel so the file inputs exist
    fireEvent.click(screen.getByText('Narrow Index (optional)'));

    // Attach a CSV to the Script→Table input, then apply the filter
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

    fireEvent.click(screen.getByText('Narrow Index (optional)'));

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

    // Expand the filter panel so the file inputs exist
    fireEvent.click(screen.getByText('Narrow Index (optional)'));

    const fileInputs = screen.getAllByLabelText(/SCRIPT_NAME, TABLE_NAME/i);
    fireEvent.change(fileInputs[0], {
      target: { files: [new File(['s,orders\n'], 'st.csv')] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Filter' }));

    // banner header reflects the active filter once the upload resolves
    expect(await screen.findByText('Index Filter ACTIVE — 12 tables, 80 fields')).toBeInTheDocument();
    expect(screen.queryByText(/⚠️/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ignored:/)).not.toBeInTheDocument();
  });
});
