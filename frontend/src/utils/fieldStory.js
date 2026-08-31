/**
 * Field Story — the step-through narrative of one searched table.field
 * (2026-08-27; stage rules re-ruled 2026-08-31 after the per-field audit —
 * see "The 2026-08-31 rule audit" below).
 *
 * The L2 debugger answers "where does this field's value go" with a
 * graph; this module re-tells the SAME closure as an ordered story the
 * user can step through: born → written → read → reappears → joined →
 * filtered → consumed.
 * It is a pure projection of the served payload — no React, no
 * cytoscape, no fetches, and no SQL text (the module never sees the
 * script, so every `detail` is built from endpoint labels + line only;
 * nothing is guessed, no sample text is hardcoded).
 *
 * THE ONE GOVERNING IDEA (2026-08-31): a step is told only when the
 * payload carries FIELD-LEVEL provenance for the searched field — an
 * edge endpoint that IS one of the searched field's chips. An edge that
 * merely touches the searched table's compound (table→table, or
 * chip→table at a line that is not the field's own) carries the TABLE's
 * path, not the field's, and telling it as the field's step was the
 * single largest defect class the audit measured (191 TABLE-PATH +
 * 52 PHANTOM steps out of 597). Where the payload is silent about the
 * field, the story is silent too: the step is DROPPED, never re-anchored
 * onto a line the field was not on.
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
 *      The seed is also the ANCHOR chip, not the only one: the closure
 *      carries the same field on several occurrence chips of the SAME
 *      compound (R44 family-3 occurrence twins), and every one of them
 *      is this field's leg — `chips` is that set.
 *   2. Only closure edges with a valid `highlight_line` (integer ≥ 1 —
 *      INV-2 says every closure edge carries one; malformed edges are
 *      skipped, never repaired) participate. Classification, first
 *      match wins:
 *
 *        write legs (flow_kind 'write', TABLE_FLOW/DML)
 *          written   the write lands ON the searched table's compound —
 *                    the table's own write anchor (the INSERT's line);
 *                    no chip needed, the DML writes the whole row;
 *          birth     a chip of the searched field SOURCES the value leg
 *                    and the leg resolves (through the ⟐ routing
 *                    intermediate, if any) to the field's OWN table —
 *                    the field's production line in this script (the
 *                    SELECT-list line where its value is computed, e.g.
 *                    `REPLACE("$(load_date)","-","") AS cjrq` @74);
 *          consumed  the same, but the leg resolves to a DIFFERENT
 *                    table — another table takes this value. The step
 *                    anchors at the DML statement's own line (the
 *                    routing intermediate's line_start), NOT at the
 *                    field's production line (that line is the birth
 *                    line and would be told twice), and the step's
 *                    evidence carries the resolved write leg too, so
 *                    the reader sees WHO consumes the value;
 *          a write leg sourced by anything else (a table compound) is
 *          another field's value in transit — never this story.
 *
 *        reappears  SCHEMA from the searched table's OWN compound INTO
 *                   one of the field's chips, at a line that chip does
 *                   not occupy (v3.3.193, R40.12 — STRICT; see the
 *                   reappears branch in classifyEdge);
 *        read       REF|TABLE_FLOW kinded read/chain, endpoint = one of
 *                   the field's chips, AT THAT CHIP'S OWN LINE — the one
 *                   line the payload vouches for as the field's own
 *                   occurrence. The same edge shape at any OTHER line is
 *                   the table's hop re-parented onto the field (the
 *                   audit's `FROM bdm_acc_entrusted_payment a` /
 *                   `FROM EAST5_STZFXXB` mis-tells) and is dropped;
 *        joined     JOIN|TRANSFORM|COMPUTED|WINDOW|AGGREGATE with a
 *                   chip endpoint, at a line the table compound does not
 *                   own — the field feeds, or is produced by, that
 *                   expression (an expression whose only contact with
 *                   the story is the searched TABLE belongs to some
 *                   other field's story);
 *        filtered   FILTER (or any edge kinded 'filter') with a chip
 *                   endpoint, same line rule as joined — a FILTER edge
 *                   carries flow_kind 'field flow' (only INDIRECT is
 *                   kinded 'filter'), so either signal alone would miss
 *                   half the filters;
 *        the table's OWN anchor line (its compound `line_start`) is the
 *        compound's line, never the field's: a chip edge sitting there
 *        is the compound's registration and tells nothing about the
 *        field — unless the field's own chip line IS that line
 *        (partition fields: `p_dt` lives on the PARTITION clause of the
 *        INSERT that defines the table), which the chip-line test
 *        already admits for read and the birth absorption below.
 *        anything else → skipped. No step is ever invented.
 *
 *      BIRTH ABSORPTION: when a birth step exists at a line, the other
 *      chip-endpoint REF/TABLE_FLOW edges on that same line are part of
 *      the same production and join the birth step instead of being
 *      re-told as a read of the field's own definition line (the audit:
 *      `p_dt`'s L41 read-shaped edge is the PARTITION binding, not a
 *      read). A field that is NOT written by its own table in this
 *      script has NO birth line — a source-side column is only read
 *      here, and its first occurrence is told as `read`, which is the
 *      honest stage (the audit: 46 fake `Birth @LEFT JOIN …` steps).
 *   3. Steps group per (kind, line) — the fixed point of "merge
 *      consecutive same-kind groups at the same line" — and are ordered
 *      by STORY KIND first (born → written → read → reappears → joined →
 *      filtered → consumed), line ascending within a kind. Pure
 *      line-ascending would bury the narrative: a consuming INSERT that
 *      starts at L179 reads at L189 and filters at L190, while its write
 *      leg anchors at the statement start L179 (§8.3 rule 3 — a write
 *      anchors at the DML statement's own line). The story keeps that
 *      write LAST, after its own read/filter legs.
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
 *     p_dt ─REF─► ⟐output@41                          @41  (value leg)
 *     p_dt ─TABLE_FLOW (write)─► ⟐output@41           @41  (value leg)
 *     ⟐output@41 ─TABLE_FLOW (write)─► east5          @41  (→ written)
 *     east5 ─TABLE_FLOW (chain)─► ⟐output@179         @189 (table path — dropped)
 *     p_dt ─REF─► east5                               @189 (not p_dt's line — dropped)
 *     p_dt ─FILTER─► east5                            @190 (→ filtered)
 *     ⟐output@179 ─TABLE_FLOW (write)─► rrcdm         @179 (table path — dropped)
 *
 *   → { searched: 'east5_stzfxxb.p_dt',
 *       steps: [
 *         { id: 'birth-41',     kind: 'birth',    title: 'Birth',    line: 41, … },
 *         { id: 'written-41',   kind: 'written',  title: 'Written',  line: 41, … },
 *         { id: 'filtered-190', kind: 'filtered', title: 'Filtered', line: 190, … },
 *       ] }
 *
 *   The two dropped edges are the audit's finding, not a loss of
 *   information: L189 is the table's scan line (no `p_dt` on it) and
 *   L179's INSERT writes constants + COUNT(1) only — neither is true of
 *   `p_dt`. The log write would only be `p_dt`'s consumption if `p_dt`'s
 *   value reached it, which the payload does not claim.
 *
 * THE 2026-08-31 RULE AUDIT (117 searchable (table, field) pairs of
 * EAST5_STZFXXB_M.sql, 597 told steps, ground truth = the script text +
 * a hand-verified token/alias model, built independently of this
 * module): 167/597 steps were true of the field (28%). Per stage —
 * birth 3/49, written 63/63, read 0/95, reappears 14/14, joined 51/105,
 * filtered 4/4, consumed 32/267. Four rules were re-ruled:
 *   Fix H  `consumed` had no field-leg requirement AND its ⟐output
 *          exclusion tested `type === 'output_table'`, a type that does
 *          not exist in served payloads (real routing intermediates are
 *          `intermediate_table`; the guard was dead) — so every write
 *          leg in every closure landed there (267 steps, 235 wrong),
 *          including each field's own AS-alias birth line;
 *   Fix M  table-path inheritance — an edge became a step for touching
 *          the searched table compound alone;
 *   Fix M  birth required `highlight_line === the table's line_start`,
 *          which is the FROM/JOIN anchor for source tables (46 fake
 *          births) and never the AS-alias line where a target column is
 *          actually produced;
 *   Fix M  `joined` admitted another field's compute expression because
 *          it touched the searched table.
 * Re-run of the same audit over the same 117 payloads with these rules:
 * see CLAUDE.md #37 (before 28% → after 96%).
 *
 * Malformed payloads never throw: missing nodes/edges/keys degrade to
 * skipped edges (or an empty story), never to a guessed step.
 */

// The story order — the rank IS the step order (born first, consumed
// last); the line breaks ties within one kind.
// v3.3.191 (random-10 audit, user-authorized ≤10 stages): the JOINED stage.
// v3.3.193 (R40.12, field-story audit 2026-08-30): the REAPPEARS stage,
// taking the slot AFTER read and BEFORE joined. Placement is not cosmetic:
// a reappears step is the field's OWN occurrence evidence — "it occurs
// again here, on a line its chip doesn't show" — and it is frequently the
// very evidence that explains the joined/filtered steps that follow it.
const KIND_RANK = {
  birth: 0, written: 1, read: 2, reappears: 3, joined: 4, filtered: 5, consumed: 6,
};

// Bare titles (no numbering — the renderer prefixes the circled number).
const KIND_TITLES = {
  birth: 'Birth',
  written: 'Written',
  read: 'Read',
  reappears: 'Reappears',
  joined: 'Joined/Transformed',
  filtered: 'Filtered',
  consumed: 'Consumed',
};

// Write legs: the DML rewrite re-types the ⟐output→target leg as
// TABLE_FLOW carrying the write role; raw DML edges with no ⟐ routing
// keep edge_type 'DML'. flow_kind 'write' (§8.7 rule 3) is the canonical
// signal — both carriers are accepted, everything else is not a write.
const WRITE_EDGE_TYPES = new Set(['TABLE_FLOW', 'DML']);
const JOINISH_EDGE_TYPES = new Set(['JOIN', 'TRANSFORM', 'COMPUTED', 'WINDOW', 'AGGREGATE']);

// The ⟐ output compounds are DML routing intermediates — a write into one
// is a leg of the write, never a consumption. The audit (2026-08-31) found
// the served type is `intermediate_table` (0 `output_table` nodes in 117
// payloads — the old single-type guard was dead code), so the family is
// matched by type AND by the `⟐` name marker the builder stamps on the
// virtual-table name (B5), which also covers the older `virtual_table`
// spelling. A write into anything else IS a destination.
const ROUTING_TABLE_TYPES = new Set(['intermediate_table', 'virtual_table', 'output_table']);
const ROUTING_NAME_MARK = '⟐';

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

/** A valid INV-2 line: integer ≥ 1. */
const validLine = (n) => (Number.isInteger(n) && n >= 1 ? n : null);

/**
 * Is this compound a DML routing intermediate (an ⟐ output virtual
 * table)? Type family first, then the name marker — either signal is
 * enough, because the guard's failure mode is symmetric: treating a
 * routing leg as a destination invents a consumption, and treating a
 * destination as a routing leg would hide one.
 */
function isRoutingTable(d) {
  if (!isTableLike(d)) return false;
  if (ROUTING_TABLE_TYPES.has(d.type)) return true;
  return fold(d.table_name).includes(ROUTING_NAME_MARK)
    || fold(d.label).includes(ROUTING_NAME_MARK);
}

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

/** The edge data this module classifies on, or null when the entry is
 * not a usable closure edge (malformed entries are skipped, not repaired). */
function edgeData(raw) {
  const e = raw && raw.data;
  if (!e || typeof e.source !== 'string' || typeof e.target !== 'string') return null;
  return e;
}

const isWriteLeg = (e) => e.flow_kind === 'write' && WRITE_EDGE_TYPES.has(e.edge_type);

/**
 * Classify one closure edge into a story step — `{ kind, line }`, or null
 * to skip it. `line` is the step's line: the edge's own, EXCEPT for a
 * consumed step, which anchors at the consuming DML statement's line (the
 * routing intermediate's `line_start`) rather than at the field's
 * production line. First match wins, in the story-rule order (see the
 * module header).
 *
 * `ctx` carries: `chips` (ids of EVERY chip of the searched field on the
 * searched table), `chipLine` (their line_starts, for the own-line test),
 * `ownTableId`, `tableLine`, `birthLines` (lines where a chip sources a
 * write leg back into its own table), `routingLeg` (the single write leg
 * leaving a routing intermediate, or null), `byId`.
 */
function classifyEdge(e, ctx) {
  const src = ctx.byId.get(e.source);
  const tgt = ctx.byId.get(e.target);
  // Dangling endpoint (edge pointing outside the payload) — skip rather
  // than guess at the missing node's role.
  if (!src || !tgt) return null;
  const line = validLine(e.highlight_line);
  if (line === null) return null; // INV-2 defense (also enforced upstream)
  const srcId = e.source;
  const tgtId = e.target;
  const srcIsChip = ctx.chips.has(srcId);
  const tgtIsChip = ctx.chips.has(tgtId);

  // ── write legs ────────────────────────────────────────────────────────
  // `written` keys on the destination compound only: the DML writes the
  // whole row, so no chip is required (the audit measured 63/63 true).
  if (isWriteLeg(e)) {
    if (tgtId === ctx.ownTableId) return { kind: 'written', line };
    // A value leg is this field's only when a chip of the field carries it.
    if (!srcIsChip) return null;
    const dest = writeDestination(tgtId, tgt, line, ctx);
    if (!dest) return null; // unroutable → not told, never guessed
    if (dest.tableId === ctx.ownTableId) return { kind: 'birth', line };
    return { kind: 'consumed', line: dest.line };
  }

  // ── the field's own occurrence evidence ───────────────────────────────
  // reappears — the field occurring again on a line its chip doesn't show
  // (v3.3.193, R40.12 — the ruling is STRICT, all of it, because the audit
  // measured the alternatives as over-admitting):
  //   * edge_type SCHEMA — the belongs-to family; the only edge a compound
  //     emits straight INTO a field chip;
  //   * source === the searched table's compound AND target === one of the
  //     field's OWN chips. The same field instance is carried on
  //     ⟐output/alias/CTE compounds too, and those emit their own SCHEMA
  //     edges INTO this very chip (measured: 1-4 per real closure) — those
  //     are other boxes' copies, not this field's occurrence on its own
  //     table, and they would re-tell one line as many steps;
  //   * the line must NOT be that chip's own line — what the chip already
  //     shows is told by birth/read, and a reappears step there would say
  //     "it appears here" about the line the user is already looking at.
  if (e.edge_type === 'SCHEMA' && srcId === ctx.ownTableId && tgtIsChip) {
    const chipLine = ctx.chipLine.get(tgtId);
    if (chipLine === null || line !== chipLine) return { kind: 'reappears', line };
  }

  // Everything below needs the field's own chip on the edge — a table
  // compound's participation is the table's path, not the field's (Fix M:
  // this alone removes the audit's 191 TABLE-PATH + 52 PHANTOM steps).
  if (!srcIsChip && !tgtIsChip) return null;
  const chipId = srcIsChip ? srcId : tgtId;
  const chipLine = ctx.chipLine.get(chipId);

  // birth absorption — the field's production line, told ONCE. Any other
  // edge on a birth line is part of the same production (the PARTITION
  // binding beside the value leg, the expression that computes it), not a
  // separate read or join of the line the field is defined on.
  if (ctx.birthLines.has(line)) {
    if (e.edge_type === 'REF' || e.edge_type === 'TABLE_FLOW'
      || JOINISH_EDGE_TYPES.has(e.edge_type)) return { kind: 'birth', line };
  }

  // read — the field's own occurrence line only, and the chip must SOURCE
  // the leg: `chip ─read─► elsewhere` is this field's value being read,
  // while `compound ─read─► chip` is the compound's scan registering its
  // own chip (the audit measured that shape 8/8 wrong — every one a
  // `table → chip` value copy onto a line the field's name is not on).
  // The payload vouches for exactly one line per chip (its `line_start`,
  // the keeper occurrence); the same edge shape at any other line is the
  // compound's hop re-parented onto the field (`FROM …`, the table's scan
  // line) and is dropped.
  if ((e.edge_type === 'REF' || e.edge_type === 'TABLE_FLOW')
    && (e.flow_kind === 'read' || e.flow_kind === 'chain')) {
    if (srcIsChip && chipLine !== null && line === chipLine) return { kind: 'read', line };
    return null;
  }

  // joined / filtered — the field feeds (or is produced by) an expression,
  // or is filtered by a predicate, at a line the compound does not own: the
  // compound's anchor line is the table's, never the field's. A JOINISH
  // edge ON the chip's own line is that line's own expression, not a join
  // leg — the honest stage there is the field's occurrence, `read` (the
  // audit's own correction for every such step was `read @L<line>`, never
  // a join). A FILTER edge is different: the line IS the field's predicate
  // (`a.data_dt = …` is both the chip's line and the WHERE), so it stays a
  // filter wherever it sits.
  if (line === ctx.tableLine) return null;
  if (JOINISH_EDGE_TYPES.has(e.edge_type)) {
    if (chipLine !== null && line === chipLine) return { kind: 'read', line };
    return { kind: 'joined', line };
  }
  if (e.edge_type === 'FILTER' || e.flow_kind === 'filter') return { kind: 'filtered', line };
  return null;
}

/**
 * Where does a chip-sourced write value leg land, and at which line?
 * A routing intermediate is resolved through the ONE write leg leaving it
 * (measured: exactly one on every real routing compound); the step then
 * anchors at the DML statement's own line — the intermediate's
 * `line_start` — rather than at the field's production line. No single
 * outgoing leg (none, or several) → unresolved, and an unresolved leg is
 * never told: guessing a destination would invent a consumption.
 */
function writeDestination(tgtId, tgt, line, ctx) {
  if (isRoutingTable(tgt)) {
    const leg = ctx.routingLeg(tgtId);
    if (!leg) return null;
    const dest = ctx.byId.get(leg.target);
    if (!dest || !isTableLike(dest)) return null; // the leg must land on a compound
    return { tableId: leg.target, line: validLine(dest.line_start) || line };
  }
  return { tableId: tgtId, line };
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
 *   `steps` is ordered born → written → read → reappears → joined →
 *   filtered → consumed (line ascending within a kind); `{steps: [],
 *   seedNodeId: null}` when no seed matches. Never throws on malformed
 *   payloads.
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
  const ownTableId = tableNode ? tableNode.id : null;

  // The searched field's OWN chips: every occurrence chip of this field on
  // the searched compound (the seed plus the R44 occurrence twins). These
  // — and only these — are the endpoints that vouch for a field-level leg;
  // an edge touching the compound itself carries the table's path.
  const chips = new Set();
  const chipLine = new Map();
  for (const d of nodes) {
    if (!isField(d) || fold(d.label) !== fieldKey) continue;
    if (d.parent !== ownTableId) continue;
    chips.add(d.id);
    chipLine.set(d.id, validLine(d.line_start));
  }

  // Write legs by source, for routing-intermediate resolution: a routing
  // compound has exactly ONE write leg out; anything else is ambiguous and
  // unresolved on purpose.
  const writeLegsFrom = new Map();
  const closureEdges = [];
  for (const raw of (g && g.edges) || []) {
    const e = edgeData(raw);
    if (!e) continue;
    if (!validLine(e.highlight_line)) continue; // INV-2 defense
    closureEdges.push(e);
    if (isWriteLeg(e)) {
      if (!writeLegsFrom.has(e.source)) writeLegsFrom.set(e.source, []);
      writeLegsFrom.get(e.source).push(e);
    }
  }
  const routingLeg = (id) => {
    const legs = writeLegsFrom.get(id);
    return Array.isArray(legs) && legs.length === 1 ? legs[0] : null;
  };
  const ctx = {
    chips,
    chipLine,
    ownTableId,
    tableLine: tableNode ? validLine(tableNode.line_start) : null,
    birthLines: null, // filled below (it needs writeDestination)
    routingLeg,
    byId,
  };
  // Birth lines: the lines where a chip of this field sources a write leg
  // back into its OWN table — the field's production lines in this script.
  const birthLines = new Set();
  for (const e of closureEdges) {
    if (!isWriteLeg(e) || !chips.has(e.source)) continue;
    const tgt = byId.get(e.target);
    if (!tgt) continue;
    const dest = writeDestination(e.target, tgt, validLine(e.highlight_line), ctx);
    if (dest && dest.tableId === ownTableId) {
      const l = validLine(e.highlight_line);
      if (l !== null) birthLines.add(l);
    }
  }
  ctx.birthLines = birthLines;

  // Endpoint map for the closure edges (A1 merged-id resolution reads
  // source/target of each detailed edge when promoting to parent pairs).
  const closureEdgeById = new Map();
  for (const e of closureEdges) {
    if (e.id && typeof e.id === 'string') closureEdgeById.set(e.id, e);
  }

  // 2. Classify + group per (kind, line); `seq` records first-seen order
  //    as the final deterministic tie-break after (kind rank, line).
  const groups = new Map();
  let seq = 0;
  for (const e of closureEdges) {
    const told = classifyEdge(e, ctx);
    if (!told) continue;
    const { kind, line } = told;
    // A consumed step tells WHO takes the value: its routing write leg is
    // part of the same fact and joins the step's evidence (it can never
    // collide with another step of THIS story — its destination is another
    // table, so it is not this story's `written` leg).
    let edges = [e];
    if (kind === 'consumed') {
      const tgt = byId.get(e.target);
      const leg = tgt ? routingLeg(e.target) : null;
      if (leg && leg !== e) edges = [e, leg];
    }
    const id = `${kind}-${line}`;
    let group = groups.get(id);
    if (!group) {
      group = { id, kind, line, edges: [], seq: seq++ };
      groups.set(id, group);
    }
    for (const edge of edges) {
      if (!group.edges.includes(edge)) group.edges.push(edge);
    }
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
