import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ResolutionReport from '../ResolutionReport';

// The report body is collapsed by default — expand via the header click.
function expand() {
  fireEvent.click(screen.getByText('Orphan Resolution'));
}

describe('ResolutionReport', () => {
  beforeEach(() => {
    // localStorage pollution from other suites must not leak in
    window.localStorage.clear();
  });

  it('renders nothing when resolution_stats is absent (old cached data)', () => {
    const { container } = render(<ResolutionReport stats={null} orphanFieldSamples={null} />);
    expect(container.firstChild).toBeNull();
  });

  // ── M9: branch on the COUNT, not on name-list presence ──────────────
  it('M9: shows "N unresolved (details unavailable)" when names are omitted', () => {
    render(<ResolutionReport stats={{ total_columns: 10, unresolved: 3 }} orphanFieldSamples={null} />);
    expand();
    expect(screen.getByText('3 unresolved (details unavailable)')).toBeInTheDocument();
    expect(screen.queryByText('No unresolved columns')).not.toBeInTheDocument();
  });

  it('M9: shows "No unresolved columns" when the count is zero', () => {
    render(<ResolutionReport stats={{ total_columns: 5, unresolved: [] }} orphanFieldSamples={null} />);
    expand();
    expect(screen.getByText('No unresolved columns')).toBeInTheDocument();
    expect(screen.queryByText(/details unavailable/)).not.toBeInTheDocument();
  });

  it('M9: still renders the name list when names are present', () => {
    render(
      <ResolutionReport
        stats={{ total_columns: 10, unresolved: ['orphan_a', 'orphan_b'] }}
        orphanFieldSamples={null}
      />
    );
    expand();
    expect(screen.getByText('orphan_a')).toBeInTheDocument();
    expect(screen.getByText('orphan_b')).toBeInTheDocument();
  });

  // ── M10: coverage badge must not claim 100% on stale caches ────────
  it('M10: badge shows "—" when total=0 but unresolved>0 (backend pins coverage_pct=100)', () => {
    render(
      <ResolutionReport
        stats={{ total_columns: 0, unresolved: 3, coverage_pct: 100.0 }}
        orphanFieldSamples={null}
      />
    );
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('100.0%')).not.toBeInTheDocument();
  });

  it('M10: badge shows a computed percentage when inputs are healthy', () => {
    render(<ResolutionReport stats={{ total_columns: 200, unresolved: 4 }} orphanFieldSamples={null} />);
    expect(screen.getByText('98.0%')).toBeInTheDocument();
  });

  // ── L14: header count vs shown count ────────────────────────────────
  it('L14: header shows unresolvedCount and a "showing first N" note when the list is capped', () => {
    const samples = Array.from({ length: 20 }, (_, i) => `orphan_${i}`);
    render(
      <ResolutionReport
        stats={{ total_columns: 300, unresolved: 291, coverage_pct: 3.0 }}
        orphanFieldSamples={samples}
      />
    );
    expand();
    expect(screen.getByText('Unresolved columns (291) — showing first 20')).toBeInTheDocument();
  });

  it('L14: no truncation note when every unresolved name is shown', () => {
    render(
      <ResolutionReport
        stats={{ total_columns: 10, unresolved: ['orphan_a', 'orphan_b'] }}
        orphanFieldSamples={null}
      />
    );
    expand();
    expect(screen.getByText('Unresolved columns (2)')).toBeInTheDocument();
    expect(screen.queryByText(/showing first/)).not.toBeInTheDocument();
  });

  it('L14: extractor shape with more than 20 names still shows the cap note', () => {
    const names = Array.from({ length: 25 }, (_, i) => `orphan_${i}`);
    render(<ResolutionReport stats={{ total_columns: 30, unresolved: names }} orphanFieldSamples={null} />);
    expand();
    expect(screen.getByText('Unresolved columns (25) — showing first 20')).toBeInTheDocument();
  });

  // ── M11: schema_candidates_summary line ─────────────────────────────
  it('M11: renders the schema candidates line when the prop is present and expanded', () => {
    render(
      <ResolutionReport
        stats={{ total_columns: 10, unresolved: ['a'] }}
        orphanFieldSamples={null}
        schemaCandidates={{ total: 42, unique_owner: 38, r6_collision: 3 }}
      />
    );
    expect(screen.queryByText(/Schema candidates:/)).not.toBeInTheDocument();
    expand();
    expect(
      screen.getByText('Schema candidates: 42 (unique owner: 38) | r6: 3')
    ).toBeInTheDocument();
  });

  it('M11: omits the schema candidates line when the prop is absent', () => {
    render(<ResolutionReport stats={{ total_columns: 10, unresolved: ['a'] }} orphanFieldSamples={null} />);
    expand();
    expect(screen.queryByText(/Schema candidates:/)).not.toBeInTheDocument();
  });
});
