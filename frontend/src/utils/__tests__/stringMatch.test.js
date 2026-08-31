import { describe, it, expect } from 'vitest';
import {
  buildBoundaryRegex,
  computeStringMatches,
  classifyMatches,
  flowLineSet,
  formatStringMatchSummary,
} from '../stringMatch';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// ── R40.13 — the naive string-match diff layer ──────────────────────────────
// Test plan: wiki/REQUIREMENTS_TRACEABILITY.md §"R40.13 — string-match diff
// layer + browse controls (solution & test plan)". The util is pure (no React,
// no parsing, no network): split lines + ONE boundary regex.

const matchLines = (sql, name) => computeStringMatches(sql, name).map(m => m.line);

describe('stringMatch — boundary rule (the frozen lookaround, not \\b)', () => {
  it('does NOT match trailing digits (p_dt vs p_dt2)', () => {
    expect(matchLines("SELECT p_dt2 FROM t", 'p_dt')).toEqual([]);
    expect(buildBoundaryRegex('p_dt').test('p_dt2')).toBe(false);
  });

  it('does NOT match a longer underscore name (p_dt vs p_dt_backup)', () => {
    expect(matchLines("SELECT p_dt_backup FROM t", 'p_dt')).toEqual([]);
  });

  it('does NOT match $-joined identifiers — the case \\b gets WRONG', () => {
    // `$` is an identifier character in Hive/ODPS but a regex NON-word char,
    // so `\b` claims a boundary between `t` and `$`. The frozen lookaround
    // class `[A-Za-z0-9_$]` keeps `p_dt$x` / `x$p_dt` one token.
    expect(matchLines("SELECT p_dt$x FROM t", 'p_dt')).toEqual([]);
    expect(matchLines("SELECT x$p_dt FROM t", 'p_dt')).toEqual([]);
  });

  it('documents the \\b parity probe: trailing digits agree, $ disagrees', () => {
    // The ruling's rationale is precise: the two rules AGREE on trailing
    // digits and disagree ONLY on `$`-adjacency — that disagreement is why the
    // lookaround form (not `\b`) is frozen.
    const wordBoundary = /\bp_dt\b/;
    expect(wordBoundary.test('p_dt2')).toBe(false);      // agrees with lookaround
    expect(buildBoundaryRegex('p_dt').test('p_dt2')).toBe(false);
    expect(wordBoundary.test('p_dt$x')).toBe(true);      // WRONG — \b accepts it
    expect(buildBoundaryRegex('p_dt').test('p_dt$x')).toBe(false);
    expect(wordBoundary.test('x$p_dt')).toBe(true);      // WRONG — \b accepts it
    expect(buildBoundaryRegex('p_dt').test('x$p_dt')).toBe(false);
  });

  it('treats # as a boundary — the frozen class covers $ only (ambiguity a)', () => {
    // Encoded exactly as frozen: `#` is NOT in `[A-Za-z0-9_$]`, so `p_dt#x`
    // matches. Changing the class needs a new user ruling — never silently.
    expect(matchLines("SELECT p_dt#x FROM t", 'p_dt')).toEqual([1]);
  });

  it('matches a plain occurrence, case-insensitively (P_DT / p_Dt / p_dt)', () => {
    const sql = "SELECT P_DT FROM t\nSELECT p_Dt FROM u\nSELECT p_dt FROM v";
    expect(matchLines(sql, 'p_dt')).toEqual([1, 2, 3]);
    expect(matchLines(sql.toUpperCase(), 'P_DT')).toEqual([1, 2, 3]);
  });

  it('escapes regex metacharacters in the field name (matches literally)', () => {
    expect(() => computeStringMatches("SELECT count(*) FROM t", 'count(*)')).not.toThrow();
    expect(matchLines("SELECT count(*) FROM t", 'count(*)')).toEqual([1]);
    expect(matchLines("SELECT countx FROM t", 'count(*)')).toEqual([]);
    // a name that IS a regex fragment must not widen the match
    expect(matchLines("SELECT a.b FROM t", 'a.b')).toEqual([1]);
    expect(matchLines("SELECT aXb FROM t", 'a.b')).toEqual([]);
  });
});

describe('stringMatch — the naive baseline (whole script, comments + strings in)', () => {
  const SQL = [
    '-- p_dt is the daily partition (a COMMENT line)',          // 1
    'INSERT OVERWRITE TABLE east5 PARTITION(p_dt=\'$(load_date)\')', // 2
    "WHERE x = 'p_dt'",                                          // 3
    'ALTER TABLE east5 ADD PARTITION (P_DT=\'$(load_date)\');',  // 4
    'SELECT other_col FROM src',                                 // 5
  ].join('\n');

  it('includes comment lines and string-literal lines', () => {
    // That inclusion is the point: the layer is the "what would a dumb grep
    // see" baseline, not a semantic opinion.
    expect(matchLines(SQL, 'p_dt')).toEqual([1, 2, 3, 4]);
  });

  it('includes the searched chip\'s own definition line (naive by ruling)', () => {
    expect(matchLines("SELECT p_dt FROM east5", 'p_dt')).toEqual([1]);
  });

  it('yields ONE entry per LINE even with several occurrences on it (AC3)', () => {
    const matches = computeStringMatches(
      "SELECT p_dt, p_dt, p_dt FROM t WHERE z = p_dt", 'p_dt');
    expect(matches).toHaveLength(1);
    expect(matches[0]).toEqual({ line: 1, text: 'SELECT p_dt, p_dt, p_dt FROM t WHERE z = p_dt' });
  });

  it('returns ascending 1-based lines with the source text', () => {
    const matches = computeStringMatches("a\np_dt\nb\np_dt", 'p_dt');
    expect(matches.map(m => m.line)).toEqual([2, 4]);
    expect(matches[0].text).toBe('p_dt');
  });

  it('returns [] for 0 matches, empty/whitespace names and null input', () => {
    expect(computeStringMatches('SELECT a FROM t', 'p_dt')).toEqual([]);
    expect(computeStringMatches('SELECT a FROM t', '')).toEqual([]);
    expect(computeStringMatches('SELECT a FROM t', '   ')).toEqual([]);
    expect(computeStringMatches(null, 'p_dt')).toEqual([]);
    expect(computeStringMatches(undefined, 'p_dt')).toEqual([]);
    expect(computeStringMatches('', 'p_dt')).toEqual([]);
    expect(computeStringMatches('SELECT a FROM t', null)).toEqual([]);
  });
});

describe('stringMatch — classifyMatches against the flow baseline', () => {
  // A synthetic script whose `p_dt` lines are 2, 5 and 9.
  const MATCHES = computeStringMatches(
    ['a', 'p_dt', 'b', 'c', 'p_dt', 'd', 'e', 'f', 'p_dt'].join('\n'), 'p_dt');

  it('fixture sanity: the naive lines are 2, 5 and 9', () => {
    expect(MATCHES.map(m => m.line)).toEqual([2, 5, 9]);
  });

  it('partitions covered vs missed and keeps them disjoint', () => {
    const { covered, missed } = classifyMatches(MATCHES, new Set([5, 9]));
    expect([...covered]).toEqual([5, 9]);
    expect([...missed]).toEqual([2]);
    for (const l of covered) expect(missed.has(l)).toBe(false);
  });

  it('classifies EVERYTHING as missed against an empty baseline (not-in-flow)', () => {
    const { covered, missed } = classifyMatches(MATCHES, new Set());
    expect(covered.size).toBe(0);
    expect([...missed]).toEqual([2, 5, 9]);
  });

  it('drops non-integer / < 1 entries from the baseline (INV-2 guard)', () => {
    const { covered, missed } = classifyMatches(
      MATCHES, [0, -3, 1.5, null, undefined, '2', 9]);
    expect([...covered]).toEqual([9]); // only the integer ≥ 1 entry survives
    expect([...missed]).toEqual([2, 5]);
  });

  it('accepts any iterable baseline and returns ascending outputs', () => {
    // a plain array in DESCENDING order still yields ascending outputs
    const { covered, missed } = classifyMatches(MATCHES, [9, 5]);
    expect([...covered]).toEqual([5, 9]);
    expect([...missed]).toEqual([2]);
  });

  it('tolerates absent / malformed inputs', () => {
    expect(classifyMatches(null, null)).toEqual({ covered: new Set(), missed: new Set() });
    expect(classifyMatches([{ line: 0 }, { line: -2 }, {}], [1])).toEqual({
      covered: new Set(), missed: new Set(),
    });
    // plain numbers are accepted too (a caller that kept only line numbers)
    expect([...classifyMatches([2, 9], [9]).missed]).toEqual([2]);
    expect([...classifyMatches([2, 9], [9]).covered]).toEqual([9]);
  });
});

describe('stringMatch — flowLineSet (the engine\'s claim, detailed namespace only)', () => {
  const RESULT = {
    graph: {
      nodes: [
        { data: { id: 'seed', line_start: 41 } },
        { data: { id: 'out', line_start: 0 } },      // INV-2: line 0 dropped
        { data: { id: 'not_in_flow', line_start: 77 } },
        { data: { id: 'bad', line_start: '12' } },   // non-integer dropped
      ],
      edges: [
        { data: { id: 'e1', highlight_line: 190 } },
        { data: { id: 'e2', highlight_line: 188 } }, // not in the closure
        { data: { id: 'e3', highlight_line: -1 } },  // dropped
      ],
    },
    flow_node_ids: ['seed', 'out'],
    flow_edge_ids: ['e1', 'e3'],
  };

  it('unions closure-edge highlight_line with closure-node line_start (int ≥ 1)', () => {
    expect([...flowLineSet(RESULT)]).toEqual([41, 190]);
  });

  it('returns an EMPTY set when the flow sets are absent or empty', () => {
    expect(flowLineSet({ ...RESULT, flow_node_ids: [], flow_edge_ids: [] })).toEqual(new Set());
    expect(flowLineSet({ graph: RESULT.graph })).toEqual(new Set());
    expect(flowLineSet(null)).toEqual(new Set());
    expect(flowLineSet({})).toEqual(new Set());
    expect(flowLineSet({ flow_node_ids: ['seed'], flow_edge_ids: ['e1'] })).toEqual(new Set());
  });

  it('accepts Set-valued flow ids and tolerates bare (data-less) elements', () => {
    const bare = {
      graph: {
        nodes: [{ id: 'seed', line_start: 41 }],
        edges: [{ id: 'e1', highlight_line: 190 }],
      },
      flow_node_ids: new Set(['seed']),
      flow_edge_ids: new Set(['e1']),
    };
    expect([...flowLineSet(bare)]).toEqual([41, 190]);
  });
});

describe('stringMatch — formatStringMatchSummary (the bar counter)', () => {
  it('reads `N string matches · M in flow · K not in flow` with N = M + K', () => {
    expect(formatStringMatchSummary({ total: 12, inFlow: 2, notInFlow: 10 }))
      .toBe('12 string matches · 2 in flow · 10 not in flow');
  });

  it('omits the M/K suffix at 0 matches', () => {
    expect(formatStringMatchSummary({ total: 0, inFlow: 0, notInFlow: 0 }))
      .toBe('0 string matches');
    expect(formatStringMatchSummary(null)).toBe('0 string matches');
    expect(formatStringMatchSummary({})).toBe('0 string matches');
  });
});

// ── The documented east5 fixture ────────────────────────────────────────────
// Engine claim from the committed closure snapshot
// (backend/tests/snapshots/l2_snapshot_04_EAST5_STZFXXB_M.sql.json): the
// east5_stzfxxb.p_dt flow closure highlights {41, 179, 189, 190}; the naive
// scan sees 12 lines. Gated like fieldStoryBar.test.jsx so a checkout without
// samples/ skips cleanly instead of failing.
const EAST5 = resolve(process.cwd(), '../samples/sql_sample_v1/EAST5_STZFXXB_M.sql');
const east5Sql = existsSync(EAST5) ? readFileSync(EAST5, 'utf8') : null;
const east5Suite = east5Sql ? describe : describe.skip;

east5Suite('stringMatch — east5_stzfxxb.p_dt fixture (documented assertion)', () => {
  const matches = computeStringMatches(east5Sql, 'p_dt');
  const FLOW_LINES = new Set([41, 179, 189, 190]);
  const { covered, missed } = classifyMatches(matches, FLOW_LINES);

  it('finds exactly 12 naive match lines (the ten partition DDL lines + L41 + L190)', () => {
    expect(matches.map(m => m.line))
      .toEqual([41, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 190]);
  });

  it('classifies 2 in flow (L41/L190) and 10 not in flow (L166–175)', () => {
    expect([...covered]).toEqual([41, 190]);
    expect([...missed]).toEqual([166, 167, 168, 169, 170, 171, 172, 173, 174, 175]);
  });

  it('renders the documented counter "12 string matches · 2 in flow · 10 not in flow"', () => {
    expect(formatStringMatchSummary({
      total: matches.length,
      inFlow: covered.size,
      notInFlow: missed.size,
    })).toBe('12 string matches · 2 in flow · 10 not in flow');
  });

  it('leaves the engine\'s own anchors (L179/L189) out of the naive layer', () => {
    // The flow passes through rrcdm_job_log_exec_par there — the engine
    // legitimately anchors lines the dumb grep sees nothing on. NOT a defect:
    // the layer surfaces the difference, adjudication stays with the human.
    const lines = new Set(matches.map(m => m.line));
    expect(lines.has(179)).toBe(false);
    expect(lines.has(189)).toBe(false);
  });
});
