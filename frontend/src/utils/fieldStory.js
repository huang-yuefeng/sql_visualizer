/**
 * Field Story — the step-through narrative of one searched table.field
 * (2026-08-27).
 *
 * The L2 debugger answers "where does this field's value go" with a
 * graph; this module re-tells the SAME closure as an ordered story the
 * user can step through: born → written → read → filtered → consumed.
 * It is a pure projection of the served payload — no React, no
 * cytoscape, no fetches, and no SQL text (the module never sees the
 * script, so every `detail` is built from endpoint labels + line only;
 * nothing is guessed, no sample text is hardcoded).
 *
 * Derivation (data-driven, all from `graph` — the detailed flow closure
 * that `l2Result.graph` carries):
 *
 *   1. Seed = the field node (type 'field') whose label matches `field`
 *      case-insensitively and whose `parent` compound matches `table`
 *      — folding case for PHYSICAL tables exactly like the backend
 *      (#288: the entity key is lowercased, so EAST5_STZFXXB @L189 and
 *      east5_stzfxxb @L41 are ONE compound; alias/CTE/output compounds
 *      keep exact keys). No seed → empty story, never a guess.
 *   2. Only closure edges with a valid `highlight_line` (integer ≥ 1 —
 *      INV-2 says every closure edge carries one; malformed edges are
 *      skipped, never repaired) participate. Each edge is classified
 *      from edge_type + flow_kind + endpoints, FIRST MATCH WINS in the
 *      story-rule order:
 *        birth     REF|TABLE_FLOW touching the SEED at the searched
 *                  table's own anchor (highlight_line === the table
 *                  node's line_start) — the field's binding legs at its
 *                  defining statement (e.g. the INSERT's PARTITION
 *                  clause);
 *        written   write (flow_kind 'write') INTO the searched table;
 *        read      REF|TABLE_FLOW of kind read/chain OUT of the
 *                  searched table;
 *        filtered  FILTER touching the seed or the searched table —
 *                  keyed on edge_type FILTER *or* flow_kind 'filter':
 *                  a FILTER edge carries flow_kind 'field flow' (only
 *                  INDIRECT is kinded 'filter'), so either signal alone
 *                  would miss half the filters;
 *        consumed  write into any OTHER table compound (⟐ output VTs —
 *                  type 'output_table' — are DML routing intermediates,
 *                  never a consumption);
 *        anything else → skipped. No step is ever invented.
 *      birth must outrank read: the seed's binding edge is read-shaped
 *      but is the field's BIRTH, and it sits exactly at the table's
 *      anchor line.
 *   3. Steps group per (kind, line) — the fixed point of "merge
 *      consecutive same-kind groups at the same line" — and are ordered
 *      by STORY KIND first (born → written → read → filtered →
 *      consumed), line ascending within a kind. Pure line-ascending
 *      would bury the narrative: a consuming INSERT that starts at L179
 *      reads at L189 and filters at L190, while its write leg anchors
 *      at the statement start L179 (§8.3 rule 3 — a write anchors at
 *      the DML statement's own line). The story keeps that write LAST,
 *      after its own read/filter legs.
 *   4. Step ids are stable: `${kind}-${line}`. Titles carry no
 *      numbering — the renderer prefixes the circled number.
 *
 * `fullGraph` is accepted for contract symmetry and deliberately unused:
 * R38 makes every search downstream-only, so the story is the closure's
 * story; provenance questions stay answerable in the full view.
 *
 * Worked example — EAST5_STZFXXB_M.sql, search `east5_stzfxxb.p_dt`
 * (hand-built from the served closure shape and checked against
 * samples/sql_sample_v1/EAST5_STZFXXB_M.sql; no container needed):
 *
 *   L41  INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt=…,charge_department)
 *   L179 INSERT INTO TABLE rrcdm_job_log_exec_par( … )
 *   L189 FROM EAST5_STZFXXB                 (same compound as L41 — #288 fold)
 *   L190 WHERE p_dt = '$(load_date)'
 *
 *   closure edges →
 *     p_dt ─REF─► east5_stzfxxb                        @41  (PARTITION binding)
 *     output@41 ─TABLE_FLOW (write)─► east5_stzfxxb    @41
 *     east5_stzfxxb ─TABLE_FLOW (read)─► output@179    @189
 *     p_dt ─FILTER─► output@179                        @190
 *     output@179 ─TABLE_FLOW (write)─► rrcdm_job_log_exec_par  @179
 *
 *   → { searched: 'east5_stzfxxb.p_dt',
 *       steps: [
 *         { id: 'birth-41',     kind: 'birth',    title: 'Birth',    line: 41, … },
 *         { id: 'written-41',   kind: 'written',  title: 'Written',  line: 41, … },
 *         { id: 'read-189',     kind: 'read',     title: 'Read',     line: 189, … },
 *         { id: 'filtered-190', kind: 'filtered', title: 'Filtered', line: 190, … },
 *         { id: 'consumed-179', kind: 'consumed', title: 'Consumed', line: 179, … },
 *       ] }
 *
 * Malformed payloads never throw: missing nodes/edges/keys degrade to
 * skipped edges (or an empty story), never to a guessed step.
 */

// The story order — the rank IS the step order (born first, consumed
// last); the line breaks ties within one kind.
const KIND_RANK = { birth: 0, written: 1, read: 2, filtered: 3, consumed: 4 };

// Bare titles (no numbering — the renderer prefixes the circled number).
const KIND_TITLES = {
  birth: 'Birth',
  written: 'Written',
  read: 'Read',
  filtered: 'Filtered',
  consumed: 'Consumed',
};

// Write legs: the DML rewrite re-types the ⟐output→target leg as
// TABLE_FLOW carrying the write role; raw DML edges with no ⟐ routing
// keep edge_type 'DML'. flow_kind 'write' (§8.7 rule 3) is the canonical
// signal — both carriers are accepted, everything else is not a write.
const WRITE_EDGE_TYPES = new Set(['TABLE_FLOW', 'DML']);

// The ⟐ output compounds are DML routing intermediates — a write into one
// is a leg of the write, never a consumption.
const OUTPUT_TABLE_TYPE = 'output_table';

// #288 mirror: physical compounds fold case-insensitively (the backend
// lowercases the entity key); aliases/CTEs/outputs keep exact keys. JS
// toLowerCase === Python lower() for the ASCII identifiers here.
const PHYSICAL_TABLE_TYPE = 'source_table';

/** "" for anything that is not a usable string (never throws, never
 * coerces objects — a malformed label simply never matches). */
const fold = (s) => (typeof s === 'string' ? s.toLowerCase() : '');

const isField = (d) => !!d && d.type === 'field';

// Table-like = any non-field compound node (source/alias/cte/output/
// intermediate tables all qualify; synthetic caption nodes are
// frontend-only chrome and never appear in a served payload).
const isTableLike = (d) => !!d && d.type !== 'field';

/**
 * Does this compound match the searched table? `table_name` is the raw
 * backend name (display `label` carries alias `@L` suffixes and ⟐
 * sanitization, so table_name is the preferred key; label stays as an
 * older-payload fallback). Physical compounds fold case; the rest keep
 * exact keys, mirroring `_fold_physical`.
 */
function tableNodeMatches(d, table) {
  if (!isTableLike(d)) return false;
  const t = fold(table);
  if (t === '') return false;
  if (d.type === PHYSICAL_TABLE_TYPE) {
    return fold(d.table_name) === t || fold(d.label) === t;
  }
  return d.table_name === table || d.label === table;
}

/**
 * Index the payload nodes by id (insertion order = payload order, which
 * keeps every "first match" below deterministic). Nodes without a usable
 * id are dropped — nothing can reference them anyway.
 */
function buildNodeIndex(graph) {
  const idx = new Map();
  for (const raw of (graph && graph.nodes) || []) {
    const d = raw && raw.data;
    if (d && typeof d.id === 'string' && d.id !== '') idx.set(d.id, d);
  }
  return idx;
}

/**
 * Classify one closure edge into a story kind, or null to skip it.
 * First match wins, in the story-rule order (see the module header for
 * why birth must outrank read).
 */
function classifyEdge(e, { seedId, tableId, tableLine, byId }) {
  const src = byId.get(e.source);
  const tgt = byId.get(e.target);
  // Dangling endpoint (edge pointing outside the payload) — skip rather
  // than guess at the missing node's role.
  if (!src || !tgt) return null;
  const et = e.edge_type;
  const fk = e.flow_kind;
  const line = e.highlight_line;
  const srcId = e.source;
  const tgtId = e.target;
  const touchesSeed = srcId === seedId || tgtId === seedId;
  const touchesTable = srcId === tableId || tgtId === tableId;

  // birth — the seed is bound at the searched table's own anchor line.
  if ((et === 'REF' || et === 'TABLE_FLOW') && touchesSeed
    && Number.isInteger(tableLine) && tableLine >= 1 && line === tableLine) {
    return 'birth';
  }
  const isWrite = fk === 'write' && WRITE_EDGE_TYPES.has(et);
  // written — a write leg lands ON the searched table.
  if (isWrite && tgtId === tableId) return 'written';
  // read — the searched table feeds a read/chain leg outward, OR the
  // seed registers a read onto its OWN table (field→own-parent-table,
  // non-FILTER — red-team ruling A4: endpoint position classifies; the
  // L189 `p_dt → east5` REF is a read registration, and without this
  // clause it fell through every branch and vanished from the story).
  if ((et === 'REF' || et === 'TABLE_FLOW')
    && (fk === 'read' || fk === 'chain')
    && (srcId === tableId || (touchesSeed && tgtId === tableId))) {
    return 'read';
  }
  // filtered — a FILTER edge, or any edge kinded 'filter' (INDIRECT
  // correlated), touching the seed or the searched table.
  if ((et === 'FILTER' || fk === 'filter') && (touchesSeed || touchesTable)) {
    return 'filtered';
  }
  // consumed — a write leg lands on another TABLE compound (⟐ outputs are
  // routing intermediates, not consumers).
  if (isWrite && !touchesTable && isTableLike(tgt)
    && tgt.type !== OUTPUT_TABLE_TYPE) {
    return 'consumed';
  }
  return null;
}

/** A node's label, falling back to its raw id when the label is missing
 * (factual either way — never a placeholder guess). */
function labelOf(d, fallbackId) {
  if (d && typeof d.label === 'string' && d.label !== '') return d.label;
  return typeof fallbackId === 'string' && fallbackId !== '' ? fallbackId : '?';
}

/**
 * Assemble one story step from a (kind, line) edge group:
 *   - nodeIds: the group's edge endpoints, each field endpoint's parent
 *     compound included (payload field nodes carry `parent`) so the
 *     renderer can highlight the owning box, not just the chip;
 *   - edgeIds: the group's edge ids (edges without a usable id cannot be
 *     looked up client-side and are left out);
 *   - detail: distinct `src → tgt @L<line>` endpoint-label pairs — the
 *     line's SQL context is unknown to this module, so the detail stays
 *     endpoint labels + line, capped at 3 pairs with a `(+n more)` tail.
 */
function buildStep(group, byId) {
  const nodeIds = [];
  const seenNode = new Set();
  const addNode = (id) => {
    if (typeof id === 'string' && id !== '' && !seenNode.has(id)) {
      seenNode.add(id);
      nodeIds.push(id);
    }
  };
  const pairs = [];
  const seenPair = new Set();
  for (const e of group.edges) {
    addNode(e.source);
    addNode(e.target);
    for (const endpoint of [byId.get(e.source), byId.get(e.target)]) {
      if (isField(endpoint) && typeof endpoint.parent === 'string') {
        addNode(endpoint.parent);
      }
    }
    const pair = `${labelOf(byId.get(e.source), e.source)} → `
      + `${labelOf(byId.get(e.target), e.target)}`;
    if (!seenPair.has(pair)) {
      seenPair.add(pair);
      pairs.push(pair);
    }
  }
  const shown = pairs.slice(0, 3);
  let detail = `${shown.join(', ')} @L${group.line}`;
  if (pairs.length > shown.length) {
    detail += ` (+${pairs.length - shown.length} more)`;
  }
  return {
    id: group.id,
    kind: group.kind,
    title: KIND_TITLES[group.kind],
    line: group.line,
    edgeIds: group.edges
      .map(e => e.id)
      .filter(id => typeof id === 'string' && id !== ''),
    nodeIds,
    detail,
  };
}

/**
 * Build the field story for one L2 search result.
 *
 * @param {Object} args
 * @param {Object} args.graph - the detailed flow closure (cytoscape
 *   elements format: nodes[].data {id,label,type,parent,line_start,
 *   is_target,table_name}, edges[].data {id,source,target,edge_type,
 *   highlight_line,flow_kind}). Passing the whole l2Result is tolerated
 *   (its `.graph` is unwrapped) — a normalization, never a behavior
 *   branch.
 * @param {Object} [args.fullGraph] - accepted for contract symmetry,
 *   deliberately unused (R38: every search is downstream-only; the story
 *   is the closure's story).
 * @param {string} args.table - the searched table (physical labels fold
 *   case-insensitively).
 * @param {string} args.field - the searched field (case-insensitive).
 * @returns {{searched: string, seedNodeId: string|null, steps:
 *   Array<{id: string, kind: string, title: string, line: number,
 *   edgeIds: string[], nodeIds: string[], detail: string}>}}
 *   `steps` is ordered born → written → read → filtered → consumed
 *   (line ascending within a kind); `{steps: [], seedNodeId: null}` when
 *   no seed matches. Never throws on malformed payloads.
 */
export function buildFieldStory({ graph, fullGraph, mergedGraph, table, field } = {}) {
  // fullGraph stays untouched on purpose — see the JSDoc above.
  void fullGraph;
  const searched = `${String(table == null ? '' : table)}`
    + `.${String(field == null ? '' : field)}`;

  // Contract: `graph` is the closure itself; tolerate the whole l2Result.
  const g = (graph && (Array.isArray(graph.nodes) || Array.isArray(graph.edges)))
    ? graph
    : (graph && graph.graph) || null;
  const byId = buildNodeIndex(g);
  const nodes = Array.from(byId.values());

  // 1. Seed: the field node on a table compound matching the search.
  //    The searched table IS the seed's parent — the two are found
  //    together so the anchor line always belongs to the compound the
  //    seed actually sits on. is_target (the backend marks the seed)
  //    breaks duplicates; payload order keeps it deterministic.
  const fieldKey = fold(field);
  let seed = null;
  if (fieldKey !== '') {
    for (const d of nodes) {
      if (!isField(d) || fold(d.label) !== fieldKey) continue;
      if (!tableNodeMatches(byId.get(d.parent), table)) continue;
      if (seed === null || (d.is_target === true && seed.is_target !== true)) {
        seed = d;
      }
    }
  }
  if (!seed) return { searched, seedNodeId: null, steps: [] };
  // A1 (red-team ruling 1): the DEFAULT L2 view is merged, whose edge
  // ids are content-derived l2m_* — a DISJOINT namespace from the
  // detailed closure's l2e_*. Each step therefore also carries
  // mergedEdgeIds resolved against `mergedGraph` (l2Result.full_merged;
  // ids coincide with flow_only_merged) by (highlight_line, unordered
  // parent-promoted endpoint pair), falling back to line-match. Without
  // this, story emphasis silently no-ops in the default view.
  const resolveMergedIds = (() => {
    const mg = (mergedGraph && Array.isArray(mergedGraph.edges)) ? mergedGraph : null;
    if (!mg) return () => [];
    const parentOf = new Map();
    for (const n of (mg.nodes || [])) {
      const d = n && n.data ? n.data : n;
      if (d && d.id) parentOf.set(d.id, d.parent || d.id);
    }
    const idx = [];
    for (const e of mg.edges) {
      const d = e && e.data ? e.data : e;
      if (!d || !d.source || !d.target) continue;
      const line = Number(d.highlight_line);
      if (!Number.isInteger(line) || line < 1) continue;
      const a = parentOf.get(d.source) || d.source;
      const b = parentOf.get(d.target) || d.target;
      const key = a <= b ? `${a}|${b}` : `${b}|${a}`;
      idx.push({ line, key, id: d.id });
    }
    return (step) => {
      const pairs = new Set();
      for (const eid of (step.edgeIds || [])) {
        // closure edge endpoints promoted to their parents the same way
        const ce = closureEdgeById.get(eid);
        if (!ce) continue;
        const a = parentOf.get(ce.source) || ce.source;
        const b = parentOf.get(ce.target) || ce.target;
        pairs.add(a <= b ? `${a}|${b}` : `${b}|${a}`);
      }
      const out = new Set();
      for (const it of idx) {
        if (it.line === step.line && (pairs.size === 0 || pairs.has(it.key))) out.add(it.id);
      }
      return Array.from(out);
    };
  })();
  const tableNode = byId.get(seed.parent);
  const ctx = {
    seedId: seed.id,
    tableId: tableNode ? tableNode.id : null,
    tableLine: tableNode ? tableNode.line_start : null,
    byId,
  };
  // Endpoint map for the closure edges (A1 merged-id resolution reads
  // source/target of each detailed edge when promoting to parent pairs).
  const closureEdgeById = new Map();
  for (const e of ((g && g.edges) || [])) {
    const d = e && e.data ? e.data : e;
    if (d && d.id && d.source && d.target) closureEdgeById.set(d.id, d);
  }

  // 2. Classify + group per (kind, line); `seq` records first-seen order
  //    as the final deterministic tie-break after (kind rank, line).
  const groups = new Map();
  let seq = 0;
  for (const raw of (g && g.edges) || []) {
    const e = raw && raw.data;
    if (!e || typeof e.source !== 'string' || typeof e.target !== 'string') {
      continue;
    }
    const line = e.highlight_line;
    if (!Number.isInteger(line) || line < 1) continue; // INV-2 defense
    const kind = classifyEdge(e, ctx);
    if (!kind) continue;
    const id = `${kind}-${line}`;
    let group = groups.get(id);
    if (!group) {
      group = { id, kind, line, edges: [], seq: seq++ };
      groups.set(id, group);
    }
    group.edges.push(e);
  }

  // 3. Story order: kind rank first, line ascending within a kind.
  const steps = Array.from(groups.values())
    .sort((a, b) => (KIND_RANK[a.kind] - KIND_RANK[b.kind])
      || (a.line - b.line)
      || (a.seq - b.seq))
    .map(group => buildStep(group, byId));

    // A1: attach merged-view ids per step (disjoint l2m_* namespace).
  for (const step of steps) step.mergedEdgeIds = resolveMergedIds(step);
  return { searched, seedNodeId: seed.id, steps };
}
