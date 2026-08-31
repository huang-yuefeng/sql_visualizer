/**
 * R40.13 — the NAIVE string-match diff layer (pure functions, no React).
 *
 * After a search the SQL panel also renders a dumb case-insensitive match of
 * the searched field name over the WHOLE script — comment lines and string
 * literals INCLUDED — and every matched line is banded by whether the
 * ENGINE's flow closure covers it. The layer is a comparison aid, not a
 * correctness claim: a red line is a difference to inspect, not a bug.
 *
 * Design of record: `wiki/REQUIREMENTS_TRACEABILITY.md` §"R40.13 —
 * string-match diff layer + browse controls (solution & test plan)";
 * requirement + acceptance criteria: `requirements_v2.md` §"Amendment
 * (2026-08-31)"; CLAUDE.md design decision #45.
 *
 * No sqlglot, no parsing, no network: `sqlText.split("\n")` + one boundary
 * regex. Everything here is total — malformed input yields an empty result,
 * never a throw and never a guess.
 */

// Regex metacharacters escaped so a metacharacter-shaped field name
// (`count(*)`-class) matches LITERALLY instead of throwing or widening.
const escapeRegExp = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * The FROZEN boundary rule (user ruling, 2026-08-31): custom lookarounds over
 * the identifier class `[A-Za-z0-9_$]`, NEVER `\b`.
 *
 * Why not `\b`: `$` is an identifier character in Hive/ODPS but a regex
 * NON-word char (`\w` is `[A-Za-z0-9_]`), so `\b` claims a boundary between
 * `t` and `$` and wrongly matches `p_dt` inside `p_dt$x` / `x$p_dt`. The two
 * rules AGREE on trailing digits (`p_dt2`, `p_dt_backup` reject under both —
 * digits are regex word chars), which is why the ruling names the `$` case and
 * not the digit case. The frozen class covers `$` only: `#` is a boundary
 * character here, so `p_dt#x` matches `p_dt` (measured: 0 `$`/`#`-joined
 * identifiers across the whole `samples/` corpus; changing the class needs a
 * new user ruling — never silently).
 *
 * Flags are "i" ONLY: a "g" flag makes `.test()` stateful (`lastIndex`
 * advances across calls) and silently skips lines.
 */
export const buildBoundaryRegex = (name) =>
  new RegExp(`(?<![A-Za-z0-9_$])${escapeRegExp(name)}(?![A-Za-z0-9_$])`, "i");

/**
 * Every line of `sqlText` containing a case-insensitive boundary match of
 * `fieldName` → `[{ line, text }]`, 1-based ascending, ONE entry per matching
 * LINE (a line with 3 occurrences is one entry — AC3). Comment lines,
 * string-literal lines and DDL all participate: this is the "what would a dumb
 * grep see" baseline, so matching the searched chip's own birth line is
 * correct behaviour, not a defect (AC7).
 *
 * Guards (design point 7): empty/whitespace field name, non-string input or
 * empty `sqlText` → `[]` ⇒ the layer renders nothing.
 */
export function computeStringMatches(sqlText, fieldName) {
  if (typeof sqlText !== 'string' || sqlText.length === 0) return [];
  if (typeof fieldName !== 'string') return [];
  const name = fieldName.trim();
  if (!name) return [];
  const re = buildBoundaryRegex(name);
  const out = [];
  const lines = sqlText.split('\n');
  for (let i = 0; i < lines.length; i++) {
    if (re.test(lines[i])) out.push({ line: i + 1, text: lines[i] });
  }
  return out;
}

/**
 * The ENGINE's claim — the coverage baseline the diff is colored against.
 *
 *   flowLines = { e.data.highlight_line  for e in l2Result.graph.edges
 *                   where e.data.id ∈ l2Result.flow_edge_ids and int ≥ 1 }
 *             ∪ { n.data.line_start     for n in l2Result.graph.nodes
 *                   where n.data.id ∈ l2Result.flow_node_ids and int ≥ 1 }
 *
 * Read from the DETAILED `l2Result.graph` namespace only — `full_graph` /
 * `l2m_*` is the merged projection of the SAME closure and is never read here,
 * which is what makes the coloring identical across the flow-only / full /
 * merged view toggle (AC5). Guards are the standard INV-2 guard (integer ≥ 1,
 * else skip). If the flow sets are absent or empty (the not-in-flow response,
 * `search_matched: false`) the baseline is EMPTY and every naive match
 * classifies as not-in-flow — the truthful reading ("the engine claims nothing
 * on this script"), not a defect.
 */
export function flowLineSet(l2Result) {
  const out = new Set();
  if (!l2Result || typeof l2Result !== 'object') return out;
  const graph = l2Result.graph && typeof l2Result.graph === 'object' ? l2Result.graph : null;
  if (!graph) return out;

  const edgeIds = asIdSet(l2Result.flow_edge_ids);
  const nodeIds = asIdSet(l2Result.flow_node_ids);
  if (edgeIds.size === 0 && nodeIds.size === 0) return out; // not-in-flow ⇒ empty baseline

  if (Array.isArray(graph.edges)) {
    for (const e of graph.edges) {
      const d = (e && e.data) || e || {};
      if (!edgeIds.has(d.id)) continue;
      const ln = d.highlight_line;
      if (Number.isInteger(ln) && ln >= 1) out.add(ln);
    }
  }
  if (Array.isArray(graph.nodes)) {
    for (const n of graph.nodes) {
      const d = (n && n.data) || n || {};
      if (!nodeIds.has(d.id)) continue;
      const ln = d.line_start;
      if (Number.isInteger(ln) && ln >= 1) out.add(ln);
    }
  }
  return ascendingSet(out);
}

/**
 * Split the naive matches against the flow baseline:
 * `covered` = lines the engine's closure also claims, `missed` = lines only
 * the dumb grep sees. The two Sets are DISJOINT by construction and iterate in
 * ascending line order; `flowLines` is any iterable (non-integer / < 1 entries
 * are dropped). An empty baseline classifies EVERYTHING as missed.
 */
export function classifyMatches(matches, flowLines) {
  const flow = new Set();
  if (flowLines && typeof flowLines[Symbol.iterator] === 'function') {
    for (const ln of flowLines) {
      if (Number.isInteger(ln) && ln >= 1) flow.add(ln);
    }
  }
  const covered = new Set();
  const missed = new Set();
  const list = Array.isArray(matches) ? matches : [];
  for (const m of list) {
    const line = m && typeof m === 'object' ? m.line : m;
    if (!Number.isInteger(line) || line < 1) continue;
    if (flow.has(line)) covered.add(line);
    else missed.add(line);
  }
  return { covered: ascendingSet(covered), missed: ascendingSet(missed) };
}

/**
 * The Field Story bar's counter: `N string matches · M in flow · K not in
 * flow` (N = M + K). At N = 0 the M/K suffix is omitted — the counter reads
 * exactly `0 string matches` (design point 7).
 */
export function formatStringMatchSummary(summary) {
  const s = summary && typeof summary === 'object' ? summary : {};
  const total = Number.isInteger(s.total) ? s.total : 0;
  if (total <= 0) return '0 string matches';
  const inFlow = Number.isInteger(s.inFlow) ? s.inFlow : 0;
  const notInFlow = Number.isInteger(s.notInFlow) ? s.notInFlow : 0;
  return `${total} string matches · ${inFlow} in flow · ${notInFlow} not in flow`;
}

// Insertion-ordered Set rebuilt from a sorted copy, so `...set` reads
// ascending everywhere (the props double as an ordered browse list).
function ascendingSet(set) {
  return new Set([...set].sort((a, b) => a - b));
}

// Flow ids arrive as an array (JSON) or a Set (in-memory caller); anything
// else is "no ids" — never a guess.
function asIdSet(value) {
  if (value instanceof Set) return new Set(value);
  if (Array.isArray(value)) return new Set(value);
  return new Set();
}
