import { describe, it, expect } from 'vitest';
import { summarizeResolutionStats, strategyLabel, STRATEGY_ORDER } from '../resolutionReport';

describe('summarizeResolutionStats', () => {
  it('normalizes the extractor/analysis shape (unresolved as name list)', () => {
    const s = summarizeResolutionStats({
      total_columns: 40,
      resolved_by: { plain_alias: 10, expr_alias: 5, scope: 20, schema: 0, sys: 2, other: 1 },
      unresolved: ['orphan_a', 'orphan_b'],
    });
    expect(s).not.toBeNull();
    expect(s.total).toBe(40);
    expect(s.unresolvedCount).toBe(2);
    expect(s.names).toEqual(['orphan_a', 'orphan_b']);
    expect(s.coveragePct).toBe(95); // 1 - 2/40 = 0.95
    expect(s.byStrategy.plain_alias).toBe(10);
  });

  it('normalizes the index shape (unresolved as count, names via fallback)', () => {
    const s = summarizeResolutionStats(
      {
        total_columns: 100,
        resolved: 90,
        unresolved: 10,
        container_resolved: 3,
        coverage_pct: 90.0,
        by_strategy: { plain_alias: 30, expr_alias: 20, scope: 35, schema: 5, sys: 0, other: 0 },
      },
      ['orphan_1', 'orphan_2', 'orphan_3'],
    );
    expect(s.total).toBe(100);
    expect(s.unresolvedCount).toBe(10);
    expect(s.names).toEqual(['orphan_1', 'orphan_2', 'orphan_3']);
    expect(s.coveragePct).toBe(90);
    expect(s.byStrategy.scope).toBe(35);
  });

  it('computes coverage = 1 - len(unresolved)/total_columns', () => {
    const s = summarizeResolutionStats({ total_columns: 200, unresolved: ['a', 'b', 'c', 'd'] });
    expect(s.coveragePct).toBe(98); // 1 - 4/200 = 0.98
  });

  it('guards division by zero (total_columns = 0 → no coverage)', () => {
    const s = summarizeResolutionStats({ total_columns: 0, unresolved: [] });
    expect(s.coveragePct).toBeNull();
  });

  it('falls back to backend coverage_pct when inputs are missing', () => {
    const s = summarizeResolutionStats({ total_columns: 0, unresolved: 3, coverage_pct: 87.5 });
    expect(s.coveragePct).toBe(87.5);
  });

  it('returns null when stats are missing (old cached data)', () => {
    expect(summarizeResolutionStats(null)).toBeNull();
    expect(summarizeResolutionStats(undefined)).toBeNull();
    expect(summarizeResolutionStats('nope')).toBeNull();
  });

  it('returns null coverage when unresolved is entirely absent', () => {
    const s = summarizeResolutionStats({ total_columns: 10 });
    expect(s.unresolvedCount).toBeNull();
    expect(s.coveragePct).toBeNull();
  });

  it('exposes the six strategy buckets in fixed order', () => {
    expect(STRATEGY_ORDER).toEqual(['plain_alias', 'expr_alias', 'scope', 'schema', 'sys', 'other']);
    expect(strategyLabel('plain_alias')).toContain('plain alias');
    expect(strategyLabel('unknown_key')).toBe('unknown_key');
  });
});
