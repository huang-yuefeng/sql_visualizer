import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// ── Landing gate ────────────────────────────────────────────────────────────
// Team A ships src/utils/fieldStory.js alongside this suite; it may not exist
// when this file first runs. A STATIC named import of a missing module is a
// link error that kills the whole file, so the source is read from disk, every
// suite is gated on the export actually having landed, and the module is
// imported dynamically only inside the gated suites (same posture as
// selfLoopFilterLabel.test.js).
// v3.3.188: vite rewrites new URL(…, import.meta.url) into a dev-server
// http URL under vitest — existsSync then fails. cwd-based path instead
// (vitest runs with frontend/ as root).
// v3.3.188: cwd-based read — vite rewrites new URL(…, import.meta.url)
// into a dev-server http URL under vitest (existsSync then fails).
const MODULE_URL = resolve(process.cwd(), 'src/utils/fieldStory.js')
const moduleSrc = existsSync(MODULE_URL) ? readFileSync(MODULE_URL, 'utf8') : '';
const storyLanded =
  /export\s+(?:async\s+)?(?:function|const)\s+buildFieldStory/.test(moduleSrc)
  || /export\s*\{[^}]*\bbuildFieldStory\b/.test(moduleSrc);
const storySuite = storyLanded ? describe : describe.skip;

// The specifier MUST stay non-statically-analyzable (@vite-ignore + variable):
// a literal `import('../fieldStory.js')` makes vite:import-analysis fail the
// whole file's TRANSFORM while the module is absent (hard suite error), which
// would defeat the landing gate. Resolved lazily, only inside gated suites.
const MODULE_SPECIFIER = '../fieldStory.js';
async function loadBuildFieldStory() {
  let mod;
  try {
    mod = await import(/* @vite-ignore */ MODULE_SPECIFIER);
  } catch (_e) {
    throw new Error('fieldStory.js passed the landing gate but cannot be imported');
  }
  if (typeof mod.buildFieldStory !== 'function')
    throw new Error('fieldStory.js landed without exporting buildFieldStory');
  return mod.buildFieldStory;
}

// ── EAST5 p_dt closure fixture ──────────────────────────────────────────────
// Constructed literally from the known served L2 payload (nodes carry
// { id, type, parent?, label, line_start }; edges carry
// { id, source, target, edge_type, highlight_line }):
//
//   L41   INSERT INTO east5_stzfxxb ... p_dt
//           p_dt ──REF──▶ ⟐ output@41          (seed edge, birth)
//           p_dt ──TABLE_FLOW──▶ ⟐ output@41   (seed edge, birth)
//           ⟐ output@41 ──TABLE_FLOW(write)──▶ east5
//   L189  east5 ──TABLE_FLOW(chain)──▶ ⟐ output@179
//         p_dt ──REF──▶ east5                 (read back out of east5)
//   L190  p_dt ──FILTER──▶ east5              (WHERE predicate)
//   L179  ⟐ output@179 ──TABLE_FLOW(write)──▶ rrcdm
//
// Story: 5 steps — birth@41 (BOTH seed edges merged), written@41,
// read@189, filtered@190, consumed@179. Note the lines are NOT globally
// ascending: the consumed step reports the rrcdm write anchor (179) while
// the reads feeding it sit at 189/190 — the order is the story order
// [birth, written, read, filtered, consumed].
function east5Closure() {
  const nodes = [
    { data: { id: 'east5', type: 'source_table', label: 'east5_stzfxxb', line_start: 41 } },
    { data: { id: 'east5.p_dt', type: 'field', parent: 'east5', label: 'p_dt', line_start: 41 } },
    { data: { id: 'out41', type: 'virtual_table', label: '⟐ output@41', line_start: 41 } },
    { data: { id: 'rrcdm', type: 'target_table', label: 'rrcdm.dm_table', line_start: 179 } },
    { data: { id: 'out179', type: 'virtual_table', label: '⟐ output@179', line_start: 179 } },
  ];
  const edges = [
    { data: { id: 'e-ref-41', source: 'east5.p_dt', target: 'out41',
              edge_type: 'REF', flow_kind: 'read', highlight_line: 41 } },
    { data: { id: 'e-tf-41', source: 'east5.p_dt', target: 'out41',
              edge_type: 'TABLE_FLOW', highlight_line: 41 } },
    { data: { id: 'e-write-41', source: 'out41', target: 'east5',
              edge_type: 'TABLE_FLOW', flow_kind: 'write', highlight_line: 41 } },
    { data: { id: 'e-chain-189', source: 'east5', target: 'out179',
              edge_type: 'TABLE_FLOW', flow_kind: 'chain', highlight_line: 189 } },
    { data: { id: 'e-write-179', source: 'out179', target: 'rrcdm',
              edge_type: 'TABLE_FLOW', flow_kind: 'write', highlight_line: 179 } },
    { data: { id: 'e-ref-189', source: 'east5.p_dt', target: 'east5',
              edge_type: 'REF', flow_kind: 'read', highlight_line: 189 } },
    { data: { id: 'e-filter-190', source: 'east5.p_dt', target: 'east5',
              edge_type: 'FILTER', flow_kind: 'field flow', highlight_line: 190 } },
  ];
  return { nodes, edges };
}

const CLOSURE_EDGE_IDS = [
  'e-ref-41', 'e-tf-41', 'e-write-41',
  'e-chain-189', 'e-write-179', 'e-ref-189', 'e-filter-190',
];
const sorted = a => [...a].sort();
// Set equality, never a size check: every closure edge must land in exactly
// one step (partition) and no non-closure id may leak in.
const edgeUnion = steps => steps.flatMap(s => s.edgeIds || []);

storySuite('buildFieldStory — EAST5 p_dt canonical closure', () => {
  it('builds exactly the five story steps in story order', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    const res = buildFieldStory({
      graph: { nodes, edges },
      fullGraph: { nodes, edges },
      table: 'east5_stzfxxb',
      field: 'p_dt',
    });

    expect(res).toBeTruthy();
    expect(res.searched).toBeTruthy();
    expect(res.seedNodeId).toBe('east5.p_dt');
    expect(res.steps).toHaveLength(5);
    expect(res.steps.map(s => s.kind))
      .toEqual(['birth', 'written', 'read', 'filtered', 'consumed']);
    expect(res.steps.map(s => s.line)).toEqual([41, 41, 189, 190, 179]);
  });

  it('merges BOTH L41 seed edges into the single birth step', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    const res = buildFieldStory({
      graph: { nodes, edges }, fullGraph: { nodes, edges },
      table: 'east5_stzfxxb', field: 'p_dt',
    });

    expect(sorted(res.steps[0].edgeIds)).toEqual(sorted(['e-ref-41', 'e-tf-41']));
    // The remaining steps own exactly their own line's edges.
    expect(sorted(res.steps[1].edgeIds)).toEqual(['e-write-41']);
    expect(sorted(res.steps[2].edgeIds)).toEqual(sorted(['e-chain-189', 'e-ref-189']));
    expect(sorted(res.steps[3].edgeIds)).toEqual(['e-filter-190']);
    expect(sorted(res.steps[4].edgeIds)).toEqual(['e-write-179']);
  });

  it('partitions the closure edges exactly — nothing dropped, nothing invented', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    const res = buildFieldStory({
      graph: { nodes, edges }, fullGraph: { nodes, edges },
      table: 'east5_stzfxxb', field: 'p_dt',
    });

    const union = edgeUnion(res.steps);
    expect(union).toHaveLength(CLOSURE_EDGE_IDS.length);        // no duplicates
    expect(sorted([...new Set(union)])).toEqual(sorted(CLOSURE_EDGE_IDS)); // set equality
  });

  it('steps come from the CLOSURE graph only — fullGraph noise is ignored', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    const fullGraph = {
      nodes: [...nodes, { data: { id: 'other', type: 'source_table', label: 'unrelated_tbl', line_start: 10 } }],
      edges: [...edges, { data: { id: 'noise-join', source: 'east5', target: 'other',
                                 edge_type: 'JOIN', flow_kind: 'field flow', highlight_line: 55 } }],
    };
    const res = buildFieldStory({
      graph: { nodes, edges }, fullGraph,
      table: 'east5_stzfxxb', field: 'p_dt',
    });

    expect(res.steps).toHaveLength(5);
    expect(edgeUnion(res.steps)).not.toContain('noise-join');
  });

  it('every step carries the full step contract (id/title/line/kind/edges/nodes/detail)', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    const res = buildFieldStory({
      graph: { nodes, edges }, fullGraph: { nodes, edges },
      table: 'east5_stzfxxb', field: 'p_dt',
    });

    res.steps.forEach(st => {
      expect(typeof st.id).toBe('string');
      expect(typeof st.title).toBe('string');
      expect(st.title.length).toBeGreaterThan(0);
      expect(typeof st.line).toBe('number');
      expect(typeof st.kind).toBe('string');
      expect(Array.isArray(st.edgeIds)).toBe(true);
      expect(st.edgeIds.length).toBeGreaterThan(0);
      expect(Array.isArray(st.nodeIds)).toBe(true);
      expect(typeof st.detail).toBe('string');
    });
    expect(new Set(res.steps.map(s => s.id)).size).toBe(5); // ids unique
  });
});

storySuite('buildFieldStory — seed matching', () => {
  it('matches table and field case-insensitively', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    const graph = { nodes, edges };
    const res = buildFieldStory({
      graph, fullGraph: graph,
      table: 'EAST5_STZFXXB',
      field: 'P_DT',
    });

    expect(res.seedNodeId).toBe('east5.p_dt');
    expect(res.steps).toHaveLength(5);
    expect(res.steps.map(s => s.kind))
      .toEqual(['birth', 'written', 'read', 'filtered', 'consumed']);
    expect(res.steps.map(s => s.line)).toEqual([41, 41, 189, 190, 179]);
  });

  it('no seed → empty steps, no throw (field absent, or parented elsewhere)', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();

    // Field does not exist at all.
    const missing = buildFieldStory({
      graph: { nodes: nodes.filter(n => n.data.id !== 'east5.p_dt'), edges: [] },
      fullGraph: { nodes, edges }, table: 'east5_stzfxxb', field: 'p_dt',
    });
    expect(missing.steps).toEqual([]);
    expect(missing.seedNodeId).toBeFalsy();

    // A same-named field parented to a DIFFERENT table is not the seed.
    const elsewhere = buildFieldStory({
      graph: {
        nodes: [
          ...nodes.filter(n => n.data.id !== 'east5.p_dt'),
          { data: { id: 'rrcdm.p_dt', type: 'field', parent: 'rrcdm', label: 'p_dt', line_start: 179 } },
        ],
        edges: [],
      },
      fullGraph: { nodes, edges }, table: 'east5_stzfxxb', field: 'p_dt',
    });
    expect(elsewhere.steps).toEqual([]);
  });
});

storySuite('buildFieldStory — robustness (never throws)', () => {
  it('survives malformed arguments with empty steps', async () => {
    const buildFieldStory = await loadBuildFieldStory();

    expect(() => buildFieldStory()).not.toThrow();
    expect(() => buildFieldStory({})).not.toThrow();
    expect(() => buildFieldStory({ graph: null, fullGraph: null, table: 't', field: 'f' })).not.toThrow();
    expect(() => buildFieldStory({ graph: { nodes: null, edges: null }, table: 't', field: 'f' })).not.toThrow();

    expect(buildFieldStory({}).steps).toEqual([]);
    expect(buildFieldStory({ graph: { nodes: [], edges: [] }, table: 't', field: 'f' }).steps)
      .toEqual([]);
  });

  it('classifies JOIN/TRANSFORM legs as the Joined stage, ordered between read and filtered (audit Q2)', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    const graph = {
      nodes,
      edges: [...edges,
        { data: { id: 'e-join-144', source: 'east5', target: 'out41',
                  edge_type: 'JOIN', flow_kind: 'field flow', highlight_line: 144 } },
        { data: { id: 'e-tr-150', source: 'east5', target: 'out41',
                  edge_type: 'TRANSFORM', flow_kind: 'field flow', highlight_line: 150 } }],
    };
    const r = buildFieldStory({ graph, table: 'east5_stzfxxb', field: 'p_dt' });
    // story order: birth, written, read, JOINED (×2, per (kind,line)),
    // filtered, consumed
    expect(r.steps.map(x => x.kind)).toEqual(
      ['birth', 'written', 'read', 'joined', 'joined', 'filtered', 'consumed']);
    const joined = r.steps.filter(x => x.kind === 'joined');
    expect(sorted(joined.flatMap(x => x.edgeIds))).toEqual(['e-join-144', 'e-tr-150']);
  });

  it('skips malformed closure edges (no highlight_line / no endpoints) without throwing', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    const graph = {
      nodes,
      edges: [
        ...edges,
        { data: { id: 'bad-noline', source: 'east5.p_dt', target: 'out41',
                  edge_type: 'REF' } },                                // no highlight_line
        { data: { id: 'bad-noendpoints', edge_type: 'TABLE_FLOW',
                  highlight_line: 50 } },                               // no source/target
        { data: { source: 'east5', target: 'rrcdm', edge_type: 'REF',
                  highlight_line: 60 } },                               // no id
        null,                                                           // junk entry
        { data: null },                                                 // junk entry
      ],
    };

    let res;
    expect(() => { res = buildFieldStory({ graph, fullGraph: graph, table: 'east5_stzfxxb', field: 'p_dt' }); })
      .not.toThrow();
    expect(res.steps).toHaveLength(5);
    expect(res.steps.map(s => s.line)).toEqual([41, 41, 189, 190, 179]);
    const union = edgeUnion(res.steps);
    expect(sorted([...new Set(union)])).toEqual(sorted(CLOSURE_EDGE_IDS)); // only real edges
  });

  it('non-narrative edge types (SCHEMA / ALIAS / SUBSET) produce no steps', async () => {
    // R40.12 amendment (title/comment only — the assertion is untouched and
    // still passes as written): these three edges all land on out41, NOT on
    // the seed chip, so none of them is the one SCHEMA shape that became
    // narrative in v3.3.193 (own-table → seed chip, see the Reappears suite
    // below). ALIAS/SUBSET stay non-narrative on every endpoint.
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes } = east5Closure();
    const graph = {
      nodes,
      edges: [
        { data: { id: 's1', source: 'east5', target: 'out41',
                  edge_type: 'SCHEMA', highlight_line: 60 } },
        { data: { id: 'a1', source: 'east5', target: 'out41',
                  edge_type: 'ALIAS', highlight_line: 61 } },
        { data: { id: 'ss1', source: 'east5', target: 'out41',
                  edge_type: 'SUBSET', highlight_line: 62 } },
      ],
    };
    const res = buildFieldStory({ graph, fullGraph: graph, table: 'east5_stzfxxb', field: 'p_dt' });

    expect(res.seedNodeId).toBe('east5.p_dt'); // seed still found
    expect(res.steps).toEqual([]);              // but nothing story-worthy
  });
});

// ── Reappears — the 7th stage (R40.12, v3.3.193) ────────────────────────────
// The audit's ruling, STRICT on all four conditions at once: edge_type
// SCHEMA, source = the searched table's compound, target = the seed chip,
// and a highlight_line that is neither invalid nor the chip's own line.
// The label is "Reappears" and names NO clause — 4 of the audit's 9
// admitted lines are not GROUP BY.
storySuite('buildFieldStory — Reappears stage (R40.12)', () => {
  // An SCHEMA edge from the OWN table compound INTO the seed chip, on a line
  // the chip does not occupy — the audit's foreign-line twin.
  const schemaEdge = (id, line, source = 'east5') => ({
    data: { id, source, target: 'east5.p_dt', edge_type: 'SCHEMA',
            flow_kind: 'structure', highlight_line: line },
  });

  it('a foreign-line SCHEMA twin from the own table adds a Reappears step', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    const graph = { nodes, edges: [...edges, schemaEdge('e-schema-250', 250)] };
    const res = buildFieldStory({ graph, table: 'east5_stzfxxb', field: 'p_dt' });

    expect(res.steps.map(s => s.id)).toContain('reappears-250');
    const rep = res.steps.find(s => s.kind === 'reappears');
    expect(rep.title).toBe('Reappears');           // never a clause name
    expect(rep.line).toBe(250);
    expect(rep.edgeIds).toEqual(['e-schema-250']); // the twin, and only it
    expect(rep.nodeIds).toEqual(['east5', 'east5.p_dt']);
    expect(rep.detail).toBe('east5_stzfxxb → p_dt @L250');
    // Nothing else moved: the step count grew by exactly one and the rest of
    // the closure still partitions exactly.
    expect(res.steps).toHaveLength(6);
    expect(sorted(edgeUnion(res.steps)))
      .toEqual(sorted([...CLOSURE_EDGE_IDS, 'e-schema-250']));
  });

  it("the chip's own line never becomes a Reappears step", async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    // 41 IS the chip's line_start — what the chip already shows is told by
    // birth/read, so the twin there is not an occurrence the user is missing.
    const graph = { nodes, edges: [...edges, schemaEdge('e-schema-41', 41)] };
    const res = buildFieldStory({ graph, table: 'east5_stzfxxb', field: 'p_dt' });

    expect(res.steps.map(s => s.kind)).not.toContain('reappears');
    expect(res.steps).toHaveLength(5);
    expect(edgeUnion(res.steps)).not.toContain('e-schema-41');
  });

  it('a SCHEMA twin from an ⟐output or alias compound is not a Reappears step', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    // The nodes ride along on purpose: a dangling endpoint would be dropped
    // by the dangling-endpoint guard, which is not the rule under test.
    const graph = {
      nodes: [...nodes,
        { data: { id: 'east5_alias', type: 'alias_table', label: 'p1@189',
                  table_name: 'p1', line_start: 189 } }],
      edges: [
        ...edges,
        schemaEdge('e-schema-from-vt', 250, 'out41'),      // ⟐ output compound
        schemaEdge('e-schema-from-alias', 250, 'east5_alias'), // alias compound
      ],
    };
    const res = buildFieldStory({ graph, table: 'east5_stzfxxb', field: 'p_dt' });

    expect(res.steps.filter(s => s.kind === 'reappears')).toEqual([]);
    expect(res.steps).toHaveLength(5);
    const union = edgeUnion(res.steps);
    expect(union).not.toContain('e-schema-from-vt');
    expect(union).not.toContain('e-schema-from-alias');
  });

  it('Reappears takes the KIND_RANK slot AFTER read and BEFORE joined', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes, edges } = east5Closure();
    const graph = {
      nodes,
      edges: [...edges,
        schemaEdge('e-schema-250', 250),
        { data: { id: 'e-join-260', source: 'east5', target: 'out41',
                  edge_type: 'JOIN', flow_kind: 'field flow', highlight_line: 260 } }],
    };
    const res = buildFieldStory({ graph, table: 'east5_stzfxxb', field: 'p_dt' });

    expect(res.steps.map(s => s.kind)).toEqual(
      ['birth', 'written', 'read', 'reappears', 'joined', 'filtered', 'consumed']);
    // The occurrence evidence precedes the join/filter it explains — even the
    // filter at the EARLIER line 190 stays after both (rank beats line).
    expect(res.steps.map(s => s.line)).toEqual([41, 41, 189, 250, 260, 190, 179]);
  });
});


// ── Reappears over the audit's REAL payloads (R40.12, audit 2026-08-30) ─────
// The 9 audited examples + the dm_flag2 negative, as PROJECTIONS of the real
// served L2 payloads (built in-process through gps-sql-backend's service
// layer — `dataflow_service.get_level2_graph` — over the four sample
// scripts; nothing here is hand-invented):
//   * nodes/edges keep the served content-derived ids and every key the
//     builder reads (id/type/parent/label/table_name/line_start/is_target,
//     id/source/target/edge_type/flow_kind/highlight_line);
//   * `edges` = EVERY SCHEMA edge of that closure that targets the seed chip
//     — the own-table one AND the foreign-sourced ones (⟐output / alias /
//     CTE compounds carry the same field instance). The foreign sources'
//     nodes ride along on purpose: a dangling endpoint would be dropped by
//     the dangling-endpoint guard, which is not the strict rule under test.
//   * `mergedNodes` / `mergedEdges` = the served merged payload SLICED to the
//     reappears line(s) — the only slice `mergedEdgeIds` reads (step.line +
//     parent-promoted endpoint pair), including the closure endpoints with
//     the parents the merged payload records for them.
// `expectReappears` is the audit's own measured line (dm_flag2: none), and
// `expectMergedIds` the l2m_* self-loop the merged view really carries there.
const REAL_CLOSURES = [
  {
    // 1 product PL — real served closure of bdm_fin_lrr_key_base_info.product (BDM_ACC_LOAN_INFO_PL.sql), chip line 232.
    table: 'bdm_fin_lrr_key_base_info', field: 'product',
    seedNodeId: 'fld_17f3571622',
    nodes: [{"id": "l2_tbl_e5cda89884", "type": "intermediate_table", "label": "output(p2/subq/km1)", "table_name": "⟐ p2/subq/km1", "line_start": 228}, {"id": "fld_17f3571622", "type": "field", "parent": "l2_tbl_b119f058eb", "label": "product", "line_start": 232, "is_target": true}, {"id": "l2_tbl_b119f058eb", "type": "source_table", "label": "bdm_fin_lrr_key_base_info", "table_name": "bdm_fin_lrr_key_base_info", "line_start": 234}],
    edges: [{"id": "l2e_4b9e3ca45475", "source": "l2_tbl_e5cda89884", "target": "fld_17f3571622", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 232}, {"id": "l2e_6c9a20a326b4", "source": "l2_tbl_b119f058eb", "target": "fld_17f3571622", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 246}],
    mergedNodes: [{"id": "fld_17f3571622", "type": "field", "parent": "l2_tbl_b119f058eb", "label": "product", "line_start": 232, "is_target": true}, {"id": "l2_tbl_b119f058eb", "type": "source_table", "label": "bdm_fin_lrr_key_base_info", "table_name": "bdm_fin_lrr_key_base_info", "line_start": 234}, {"id": "l2_tbl_e5cda89884", "type": "intermediate_table", "label": "output(p2/subq/km1)", "table_name": "⟐ p2/subq/km1", "line_start": 228}],
    mergedEdges: [{"id": "l2m_c06160e84e2a", "source": "l2_tbl_b119f058eb", "target": "l2_tbl_b119f058eb", "edge_type": "FLOW", "highlight_line": 246}],
    expectReappears: [246],
    expectMergedIds: ["l2m_c06160e84e2a"],
  },
  {
    // 2 lending_ref SUP_M — real served closure of bdm_acc_loan_info.lending_ref (BDM_ACC_LOAN_INFO_SUP_M.sql), chip line 13.
    table: 'bdm_acc_loan_info', field: 'lending_ref',
    seedNodeId: 'fld_11e63e716c',
    nodes: [{"id": "l2_tbl_2f3c099a10", "type": "cte_table", "label": "rollover_loan_info", "table_name": "rollover_loan_info", "line_start": 9}, {"id": "l2_tbl_03425ce768", "type": "alias_table", "label": "p1@84", "table_name": "p1", "line_start": 84}, {"id": "l2_tbl_ace84be2f9", "type": "alias_table", "label": "p1@29", "table_name": "p1", "line_start": 29}, {"id": "l2_tbl_d5ff4bbf35", "type": "source_table", "label": "bdm_acc_loan_info", "table_name": "bdm_acc_loan_info", "line_start": 16}, {"id": "l2_tbl_a0a152838b", "type": "intermediate_table", "label": "output(subq)", "table_name": "⟐ subq", "line_start": 26}, {"id": "fld_11e63e716c", "type": "field", "parent": "l2_tbl_d5ff4bbf35", "label": "lending_ref", "line_start": 13, "is_target": true}],
    edges: [{"id": "l2e_12fb3d27eb0f", "source": "l2_tbl_ace84be2f9", "target": "fld_11e63e716c", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 41}, {"id": "l2e_d09a9af06f01", "source": "l2_tbl_03425ce768", "target": "fld_11e63e716c", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 41}, {"id": "l2e_1c812d147b5c", "source": "l2_tbl_d5ff4bbf35", "target": "fld_11e63e716c", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 59}, {"id": "l2e_fe3f0392da15", "source": "l2_tbl_2f3c099a10", "target": "fld_11e63e716c", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 13}, {"id": "l2e_3dfd0ff7406e", "source": "l2_tbl_a0a152838b", "target": "fld_11e63e716c", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 26}],
    mergedNodes: [{"id": "fld_11e63e716c", "type": "field", "parent": "l2_tbl_d5ff4bbf35", "label": "lending_ref", "line_start": 13, "is_target": true}, {"id": "l2_tbl_d5ff4bbf35", "type": "source_table", "label": "bdm_acc_loan_info", "table_name": "bdm_acc_loan_info", "line_start": 16}, {"id": "l2_tbl_03425ce768", "type": "alias_table", "label": "p1@84", "table_name": "p1", "line_start": 84}, {"id": "l2_tbl_2f3c099a10", "type": "cte_table", "label": "rollover_loan_info", "table_name": "rollover_loan_info", "line_start": 9}, {"id": "l2_tbl_a0a152838b", "type": "intermediate_table", "label": "output(subq)", "table_name": "⟐ subq", "line_start": 26}, {"id": "l2_tbl_ace84be2f9", "type": "alias_table", "label": "p1@29", "table_name": "p1", "line_start": 29}],
    mergedEdges: [{"id": "l2m_6cc57b037902", "source": "l2_tbl_d5ff4bbf35", "target": "l2_tbl_d5ff4bbf35", "edge_type": "FLOW", "highlight_line": 59}],
    expectReappears: [59],
    expectMergedIds: ["l2m_6cc57b037902"],
  },
  {
    // 3 busi_no RFN — real served closure of bdm_acc_writeoff.busi_no (BDM_ACC_LOAN_INFO_RFN.sql), chip line 275.
    table: 'bdm_acc_writeoff', field: 'busi_no',
    seedNodeId: 'fld_c51db90b11',
    nodes: [{"id": "l2_tbl_629d02ff72", "type": "source_table", "label": "BDM_ACC_WRITEOFF", "table_name": "BDM_ACC_WRITEOFF", "line_start": 275}, {"id": "l2_tbl_a8cd4a49be", "type": "alias_table", "label": "A@275", "table_name": "A", "line_start": 275}, {"id": "l2_tbl_23fdbcb8da", "type": "cte_table", "label": "TEMP_ZCHX", "table_name": "TEMP_ZCHX", "line_start": 274}, {"id": "fld_c51db90b11", "type": "field", "parent": "l2_tbl_629d02ff72", "label": "BUSI_NO", "line_start": 275, "is_target": true}],
    edges: [{"id": "l2e_4ea1626c0a93", "source": "l2_tbl_a8cd4a49be", "target": "fld_c51db90b11", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 275}, {"id": "l2e_cccc4204ca07", "source": "l2_tbl_23fdbcb8da", "target": "fld_c51db90b11", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 275}, {"id": "l2e_b607aa52c92d", "source": "l2_tbl_629d02ff72", "target": "fld_c51db90b11", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 277}],
    mergedNodes: [{"id": "fld_c51db90b11", "type": "field", "parent": "l2_tbl_629d02ff72", "label": "BUSI_NO", "line_start": 275, "is_target": true}, {"id": "l2_tbl_629d02ff72", "type": "source_table", "label": "BDM_ACC_WRITEOFF", "table_name": "BDM_ACC_WRITEOFF", "line_start": 275}, {"id": "l2_tbl_23fdbcb8da", "type": "cte_table", "label": "TEMP_ZCHX", "table_name": "TEMP_ZCHX", "line_start": 274}, {"id": "l2_tbl_a8cd4a49be", "type": "alias_table", "label": "A@275", "table_name": "A", "line_start": 275}],
    mergedEdges: [{"id": "l2m_bebd245bc967", "source": "l2_tbl_629d02ff72", "target": "l2_tbl_629d02ff72", "edge_type": "FLOW", "highlight_line": 277}],
    expectReappears: [277],
    expectMergedIds: ["l2m_bebd245bc967"],
  },
  {
    // 4 repay_acct_no RFN — real served closure of bdm_acc_loan_info.repay_acct_no (BDM_ACC_LOAN_INFO_RFN.sql), chip line 1236.
    table: 'bdm_acc_loan_info', field: 'repay_acct_no',
    seedNodeId: 'fld_0cc390dfc0',
    nodes: [{"id": "fld_0cc390dfc0", "type": "field", "parent": "l2_tbl_2a2a3ba1c1", "label": "repay_acct_no", "line_start": 1236, "is_target": true}, {"id": "l2_tbl_be20ae0caf", "type": "alias_table", "label": "A@1382", "table_name": "A", "line_start": 1382}, {"id": "l2_tbl_2a2a3ba1c1", "type": "source_table", "label": "bdm_acc_loan_info", "table_name": "bdm_acc_loan_info", "line_start": 768}, {"id": "l2_tbl_23924e32b3", "type": "alias_table", "label": "A@1121", "table_name": "A", "line_start": 1121}],
    edges: [{"id": "l2e_4b31be1ef389", "source": "l2_tbl_23924e32b3", "target": "fld_0cc390dfc0", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 1236}, {"id": "l2e_6080db3896b6", "source": "l2_tbl_be20ae0caf", "target": "fld_0cc390dfc0", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 1236}, {"id": "l2e_201ac28e8f4f", "source": "l2_tbl_2a2a3ba1c1", "target": "fld_0cc390dfc0", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 1413}],
    mergedNodes: [{"id": "fld_0cc390dfc0", "type": "field", "parent": "l2_tbl_2a2a3ba1c1", "label": "repay_acct_no", "line_start": 1236, "is_target": true}, {"id": "l2_tbl_2a2a3ba1c1", "type": "source_table", "label": "bdm_acc_loan_info", "table_name": "bdm_acc_loan_info", "line_start": 768}, {"id": "l2_tbl_23924e32b3", "type": "alias_table", "label": "A@1121", "table_name": "A", "line_start": 1121}, {"id": "l2_tbl_822cff8e55", "type": "intermediate_table", "label": "branch3", "table_name": "branch3", "line_start": 1157}, {"id": "l2_tbl_be20ae0caf", "type": "alias_table", "label": "A@1382", "table_name": "A", "line_start": 1382}, {"id": "l2_tbl_fd251e9cfa", "type": "intermediate_table", "label": "output", "table_name": "⟐ output", "line_start": 1429}],
    mergedEdges: [{"id": "l2m_ab85b0c30e40", "source": "l2_tbl_822cff8e55", "target": "l2_tbl_fd251e9cfa", "edge_type": "FLOW", "highlight_line": 1413}],
    expectReappears: [1413],
    expectMergedIds: [],
  },
  {
    // 5 X5GMAB RFN — real served closure of ods_hub_ssinrtp.x5gmab (BDM_ACC_LOAN_INFO_RFN.sql), chip line 475.
    table: 'ods_hub_ssinrtp', field: 'x5gmab',
    seedNodeId: 'fld_ba75627013',
    nodes: [{"id": "l2_tbl_a0e076c4b6", "type": "intermediate_table", "label": "output(p8)", "table_name": "⟐ p8", "line_start": 474}, {"id": "fld_ba75627013", "type": "field", "parent": "l2_tbl_4a5e34ca00", "label": "X5GMAB", "line_start": 475, "is_target": true}, {"id": "l2_tbl_4a5e34ca00", "type": "source_table", "label": "ODS_HUB_SSINRTP", "table_name": "ODS_HUB_SSINRTP", "line_start": 485}, {"id": "l2_tbl_b66a5c69b4", "type": "cte_table", "label": "TEMP_BDM_ACC_LOAN_INFO_01", "table_name": "TEMP_BDM_ACC_LOAN_INFO_01", "line_start": 290}],
    edges: [{"id": "l2e_eafecfca8f17", "source": "l2_tbl_4a5e34ca00", "target": "fld_ba75627013", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 489}, {"id": "l2e_489bcf5d862a", "source": "l2_tbl_b66a5c69b4", "target": "fld_ba75627013", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 475}, {"id": "l2e_b1fc4a619982", "source": "l2_tbl_a0e076c4b6", "target": "fld_ba75627013", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 475}],
    mergedNodes: [{"id": "fld_ba75627013", "type": "field", "parent": "l2_tbl_4a5e34ca00", "label": "X5GMAB", "line_start": 475, "is_target": true}, {"id": "l2_tbl_4a5e34ca00", "type": "source_table", "label": "ODS_HUB_SSINRTP", "table_name": "ODS_HUB_SSINRTP", "line_start": 485}, {"id": "l2_tbl_a0e076c4b6", "type": "intermediate_table", "label": "output(p8)", "table_name": "⟐ p8", "line_start": 474}, {"id": "l2_tbl_b66a5c69b4", "type": "cte_table", "label": "TEMP_BDM_ACC_LOAN_INFO_01", "table_name": "TEMP_BDM_ACC_LOAN_INFO_01", "line_start": 290}, {"id": "l2_tbl_dd107222cb", "type": "intermediate_table", "label": "p8", "table_name": "p8", "line_start": 487}],
    mergedEdges: [{"id": "l2m_411424d209e2", "source": "l2_tbl_4a5e34ca00", "target": "l2_tbl_b66a5c69b4", "edge_type": "FLOW", "highlight_line": 489}, {"id": "l2m_7a88bc0bf05e", "source": "l2_tbl_dd107222cb", "target": "l2_tbl_4a5e34ca00", "edge_type": "FLOW", "highlight_line": 489}, {"id": "l2m_52304e353dfa", "source": "l2_tbl_dd107222cb", "target": "l2_tbl_b66a5c69b4", "edge_type": "FLOW", "highlight_line": 489}],
    expectReappears: [489],
    expectMergedIds: [],
  },
  {
    // 6 acnw DL — real served closure of ods_cupd_cld_acctmaster_new.acnw (BDM_ACC_LOAN_INFO_Digitallending.sql), chip line 62.
    table: 'ods_cupd_cld_acctmaster_new', field: 'acnw',
    seedNodeId: 'fld_7a9814b6e4',
    nodes: [{"id": "l2_tbl_a62aa53d35", "type": "alias_table", "label": "p2@491", "table_name": "p2", "line_start": 491}, {"id": "l2_tbl_4b6a3cb3f9", "type": "alias_table", "label": "p1@85", "table_name": "p1", "line_start": 85}, {"id": "l2_tbl_ba247966a6", "type": "alias_table", "label": "p1@65", "table_name": "p1", "line_start": 65}, {"id": "fld_7a9814b6e4", "type": "field", "parent": "l2_tbl_46209df8e6", "label": "acnw", "line_start": 62, "is_target": true}, {"id": "l2_tbl_b216fae5b7", "type": "alias_table", "label": "p1@487", "table_name": "p1", "line_start": 487}, {"id": "l2_tbl_46209df8e6", "type": "source_table", "label": "ODS_CUPD_CLD_ACCTMASTER_NEW", "table_name": "ODS_CUPD_CLD_ACCTMASTER_NEW", "line_start": 65}],
    edges: [{"id": "l2e_ae9e42eaa41c", "source": "l2_tbl_ba247966a6", "target": "fld_7a9814b6e4", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 62}, {"id": "l2e_31b15cbfd104", "source": "l2_tbl_4b6a3cb3f9", "target": "fld_7a9814b6e4", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 62}, {"id": "l2e_efa71ae8a5a1", "source": "l2_tbl_b216fae5b7", "target": "fld_7a9814b6e4", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 62}, {"id": "l2e_a822396f3f8f", "source": "l2_tbl_a62aa53d35", "target": "fld_7a9814b6e4", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 491}, {"id": "l2e_28ea048fedd5", "source": "l2_tbl_46209df8e6", "target": "fld_7a9814b6e4", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 64}],
    mergedNodes: [{"id": "fld_7a9814b6e4", "type": "field", "parent": "l2_tbl_46209df8e6", "label": "acnw", "line_start": 62, "is_target": true}, {"id": "l2_tbl_46209df8e6", "type": "source_table", "label": "ODS_CUPD_CLD_ACCTMASTER_NEW", "table_name": "ODS_CUPD_CLD_ACCTMASTER_NEW", "line_start": 65}, {"id": "l2_tbl_08c84b0f77", "type": "alias_table", "label": "SSALSFP@66", "table_name": "SSALSFP", "line_start": 66}, {"id": "l2_tbl_0b4f7119d3", "type": "cte_table", "label": "temp_kmbh_gl", "table_name": "temp_kmbh_gl", "line_start": 58}, {"id": "l2_tbl_0dc034be71", "type": "source_table", "label": "ODS_HUB_SSALSFP", "table_name": "ODS_HUB_SSALSFP", "line_start": 66}, {"id": "l2_tbl_4b6a3cb3f9", "type": "alias_table", "label": "p1@85", "table_name": "p1", "line_start": 85}, {"id": "l2_tbl_a62aa53d35", "type": "alias_table", "label": "p2@491", "table_name": "p2", "line_start": 491}, {"id": "l2_tbl_b216fae5b7", "type": "alias_table", "label": "p1@487", "table_name": "p1", "line_start": 487}, {"id": "l2_tbl_ba247966a6", "type": "alias_table", "label": "p1@65", "table_name": "p1", "line_start": 65}, {"id": "l2_tbl_c020b6fd9b", "type": "intermediate_table", "label": "output(t)", "table_name": "⟐ t", "line_start": 62}, {"id": "l2_tbl_c0e88dbc60", "type": "alias_table", "label": "SSALSFP@86", "table_name": "SSALSFP", "line_start": 86}],
    mergedEdges: [{"id": "l2m_7b448632d620", "source": "l2_tbl_08c84b0f77", "target": "l2_tbl_0dc034be71", "edge_type": "FLOW", "highlight_line": 64}, {"id": "l2m_708cc7666e62", "source": "l2_tbl_0b4f7119d3", "target": "l2_tbl_c020b6fd9b", "edge_type": "FLOW", "highlight_line": 64}, {"id": "l2m_ee650f4a3753", "source": "l2_tbl_0dc034be71", "target": "l2_tbl_c020b6fd9b", "edge_type": "FLOW", "highlight_line": 64}, {"id": "l2m_4383d2b061b3", "source": "l2_tbl_c0e88dbc60", "target": "l2_tbl_0dc034be71", "edge_type": "FLOW", "highlight_line": 64}, {"id": "l2m_f589763d708f", "source": "l2_tbl_46209df8e6", "target": "l2_tbl_c020b6fd9b", "edge_type": "FLOW", "highlight_line": 64}],
    expectReappears: [64],
    expectMergedIds: [],
  },
  {
    // 7 lrr_key PL — real served closure of bdm_fin_lrr_key_base_info.lrr_key (BDM_ACC_LOAN_INFO_PL.sql), chip line 230.
    table: 'bdm_fin_lrr_key_base_info', field: 'lrr_key',
    seedNodeId: 'fld_522c62971c',
    nodes: [{"id": "l2_tbl_e5cda89884", "type": "intermediate_table", "label": "output(p2/subq/km1)", "table_name": "⟐ p2/subq/km1", "line_start": 228}, {"id": "fld_522c62971c", "type": "field", "parent": "l2_tbl_b119f058eb", "label": "lrr_key", "line_start": 230, "is_target": true}, {"id": "l2_tbl_b119f058eb", "type": "source_table", "label": "bdm_fin_lrr_key_base_info", "table_name": "bdm_fin_lrr_key_base_info", "line_start": 234}],
    edges: [{"id": "l2e_f3d0df43e786", "source": "l2_tbl_e5cda89884", "target": "fld_522c62971c", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 230}, {"id": "l2e_bd57e694094f", "source": "l2_tbl_b119f058eb", "target": "fld_522c62971c", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 247}],
    mergedNodes: [{"id": "fld_522c62971c", "type": "field", "parent": "l2_tbl_b119f058eb", "label": "lrr_key", "line_start": 230, "is_target": true}, {"id": "l2_tbl_b119f058eb", "type": "source_table", "label": "bdm_fin_lrr_key_base_info", "table_name": "bdm_fin_lrr_key_base_info", "line_start": 234}, {"id": "l2_tbl_488bc1017a", "type": "intermediate_table", "label": "km1", "table_name": "km1", "line_start": 247}, {"id": "l2_tbl_e5cda89884", "type": "intermediate_table", "label": "output(p2/subq/km1)", "table_name": "⟐ p2/subq/km1", "line_start": 228}],
    mergedEdges: [{"id": "l2m_7539113b76b1", "source": "l2_tbl_488bc1017a", "target": "l2_tbl_e5cda89884", "edge_type": "FLOW", "highlight_line": 247}],
    expectReappears: [247],
    expectMergedIds: [],
  },
  {
    // 8 product DL — real served closure of bdm_fin_lrr_key_base_info.product (BDM_ACC_LOAN_INFO_Digitallending.sql), chip line 513.
    table: 'bdm_fin_lrr_key_base_info', field: 'product',
    seedNodeId: 'fld_e6439121ca',
    nodes: [{"id": "l2_tbl_3641116c9f", "type": "intermediate_table", "label": "output(p3/subq/km)", "table_name": "⟐ p3/subq/km", "line_start": 509}, {"id": "l2_tbl_15d08daf51", "type": "source_table", "label": "bdm_fin_lrr_key_base_info", "table_name": "bdm_fin_lrr_key_base_info", "line_start": 516}, {"id": "fld_e6439121ca", "type": "field", "parent": "l2_tbl_15d08daf51", "label": "product", "line_start": 513, "is_target": true}],
    edges: [{"id": "l2e_20b20e59efef", "source": "l2_tbl_3641116c9f", "target": "fld_e6439121ca", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 513}, {"id": "l2e_c639a8d9ffbf", "source": "l2_tbl_15d08daf51", "target": "fld_e6439121ca", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 529}],
    mergedNodes: [{"id": "fld_e6439121ca", "type": "field", "parent": "l2_tbl_15d08daf51", "label": "product", "line_start": 513, "is_target": true}, {"id": "l2_tbl_15d08daf51", "type": "source_table", "label": "bdm_fin_lrr_key_base_info", "table_name": "bdm_fin_lrr_key_base_info", "line_start": 516}, {"id": "l2_tbl_3641116c9f", "type": "intermediate_table", "label": "output(p3/subq/km)", "table_name": "⟐ p3/subq/km", "line_start": 509}],
    mergedEdges: [{"id": "l2m_95f839718c7e", "source": "l2_tbl_15d08daf51", "target": "l2_tbl_15d08daf51", "edge_type": "FLOW", "highlight_line": 529}],
    expectReappears: [529],
    expectMergedIds: ["l2m_95f839718c7e"],
  },
  {
    // 9 acnw PL — real served closure of ods_cupd_ploan_acctm_new5.acnw (BDM_ACC_LOAN_INFO_PL.sql), chip line 220.
    table: 'ods_cupd_ploan_acctm_new5', field: 'acnw',
    seedNodeId: 'fld_951d9563cc',
    nodes: [{"id": "l2_tbl_9a0232f98a", "type": "source_table", "label": "ODS_CUPD_PLOAN_ACCTM_NEW5", "table_name": "ODS_CUPD_PLOAN_ACCTM_NEW5", "line_start": 220}, {"id": "fld_951d9563cc", "type": "field", "parent": "l2_tbl_9a0232f98a", "label": "acnw", "line_start": 220, "is_target": true}],
    edges: [{"id": "l2e_4ff0cdde7dff", "source": "l2_tbl_9a0232f98a", "target": "fld_951d9563cc", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 21}],
    mergedNodes: [{"id": "fld_951d9563cc", "type": "field", "parent": "l2_tbl_9a0232f98a", "label": "acnw", "line_start": 220, "is_target": true}, {"id": "l2_tbl_9a0232f98a", "type": "source_table", "label": "ODS_CUPD_PLOAN_ACCTM_NEW5", "table_name": "ODS_CUPD_PLOAN_ACCTM_NEW5", "line_start": 220}, {"id": "l2_tbl_2669804682", "type": "intermediate_table", "label": "a", "table_name": "a", "line_start": 220}, {"id": "l2_tbl_321fb68abc", "type": "intermediate_table", "label": "output", "table_name": "⟐ output", "line_start": 19}, {"id": "l2_tbl_f257959ab7", "type": "source_table", "label": "bdm_acc_loan_info", "table_name": "bdm_acc_loan_info", "line_start": 19}],
    mergedEdges: [{"id": "l2m_84da6a3fd492", "source": "l2_tbl_2669804682", "target": "l2_tbl_321fb68abc", "edge_type": "FLOW", "highlight_line": 21}, {"id": "l2m_047cbff1374b", "source": "l2_tbl_9a0232f98a", "target": "l2_tbl_321fb68abc", "edge_type": "FLOW", "highlight_line": 21}, {"id": "l2m_1ca9f2eae97e", "source": "l2_tbl_321fb68abc", "target": "l2_tbl_f257959ab7", "edge_type": "FLOW", "highlight_line": 21}],
    expectReappears: [21],
    expectMergedIds: [],
  },
  {
    // N dm_flag2 RFN — real served closure of bdm_acc_loan_info.dm_flag2 (BDM_ACC_LOAN_INFO_RFN.sql), chip line 1380.
    table: 'bdm_acc_loan_info', field: 'dm_flag2',
    seedNodeId: 'fld_fb092a5c53',
    nodes: [{"id": "fld_fb092a5c53", "type": "field", "parent": "l2_tbl_2a2a3ba1c1", "label": "DM_FLAG2", "line_start": 1380, "is_target": true}, {"id": "l2_tbl_be20ae0caf", "type": "alias_table", "label": "A@1382", "table_name": "A", "line_start": 1382}, {"id": "l2_tbl_fd251e9cfa", "type": "intermediate_table", "label": "output", "table_name": "⟐ output", "line_start": 1429}, {"id": "l2_tbl_2a2a3ba1c1", "type": "source_table", "label": "bdm_acc_loan_info", "table_name": "bdm_acc_loan_info", "line_start": 768}, {"id": "l2_tbl_00356d3a9a", "type": "intermediate_table", "label": "output", "table_name": "⟐ output", "line_start": 867}],
    edges: [{"id": "l2e_bfdaef0c976f", "source": "l2_tbl_be20ae0caf", "target": "fld_fb092a5c53", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 1380}, {"id": "l2e_245d29eafa36", "source": "l2_tbl_00356d3a9a", "target": "fld_fb092a5c53", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 1119}, {"id": "l2e_db09c979141f", "source": "l2_tbl_fd251e9cfa", "target": "fld_fb092a5c53", "edge_type": "SCHEMA", "flow_kind": "structure", "highlight_line": 1380}],
    mergedNodes: [{"id": "fld_fb092a5c53", "type": "field", "parent": "l2_tbl_2a2a3ba1c1", "label": "DM_FLAG2", "line_start": 1380, "is_target": true}, {"id": "l2_tbl_2a2a3ba1c1", "type": "source_table", "label": "bdm_acc_loan_info", "table_name": "bdm_acc_loan_info", "line_start": 768}, {"id": "l2_tbl_00356d3a9a", "type": "intermediate_table", "label": "output", "table_name": "⟐ output", "line_start": 867}, {"id": "l2_tbl_23924e32b3", "type": "alias_table", "label": "A@1121", "table_name": "A", "line_start": 1121}, {"id": "l2_tbl_3a90d8b31d", "type": "alias_table", "label": "A@241", "table_name": "A", "line_start": 241}, {"id": "l2_tbl_6a58ef678c", "type": "alias_table", "label": "A@269", "table_name": "A", "line_start": 269}, {"id": "l2_tbl_80cf9ee23d", "type": "alias_table", "label": "A@211", "table_name": "A", "line_start": 211}, {"id": "l2_tbl_8611ebd518", "type": "alias_table", "label": "A@259", "table_name": "A", "line_start": 259}, {"id": "l2_tbl_a8cd4a49be", "type": "alias_table", "label": "A@275", "table_name": "A", "line_start": 275}, {"id": "l2_tbl_be20ae0caf", "type": "alias_table", "label": "A@1382", "table_name": "A", "line_start": 1382}, {"id": "l2_tbl_fd251e9cfa", "type": "intermediate_table", "label": "output", "table_name": "⟐ output", "line_start": 1429}],
    mergedEdges: [{"id": "l2m_6fed1f50c0ef", "source": "l2_tbl_23924e32b3", "target": "l2_tbl_2a2a3ba1c1", "edge_type": "FLOW", "highlight_line": 1380}, {"id": "l2m_ca195a7c1b74", "source": "l2_tbl_3a90d8b31d", "target": "l2_tbl_2a2a3ba1c1", "edge_type": "FLOW", "highlight_line": 1380}, {"id": "l2m_836332421288", "source": "l2_tbl_6a58ef678c", "target": "l2_tbl_2a2a3ba1c1", "edge_type": "FLOW", "highlight_line": 1380}, {"id": "l2m_90e449bd37f8", "source": "l2_tbl_80cf9ee23d", "target": "l2_tbl_2a2a3ba1c1", "edge_type": "FLOW", "highlight_line": 1380}, {"id": "l2m_68ad737e1834", "source": "l2_tbl_8611ebd518", "target": "l2_tbl_2a2a3ba1c1", "edge_type": "FLOW", "highlight_line": 1380}, {"id": "l2m_fa35d6166f8d", "source": "l2_tbl_a8cd4a49be", "target": "l2_tbl_2a2a3ba1c1", "edge_type": "FLOW", "highlight_line": 1380}, {"id": "l2m_15e7ebe7d5d9", "source": "l2_tbl_be20ae0caf", "target": "l2_tbl_2a2a3ba1c1", "edge_type": "FLOW", "highlight_line": 1380}, {"id": "l2m_540968b4b29c", "source": "l2_tbl_fd251e9cfa", "target": "l2_tbl_2a2a3ba1c1", "edge_type": "FLOW", "highlight_line": 1380}],
    expectReappears: [],
    expectMergedIds: [],
  },
];

storySuite('buildFieldStory — Reappears over the audit\'s real payloads (R40.12)', () => {
  // The fixture stores bare data records; the builder eats cytoscape
  // elements, so wrap once here.
  const el = list => list.map(data => ({ data }));
  const ownEdgeIds = fx => {
    const chip = fx.nodes.find(n => n.id === fx.seedNodeId);
    return fx.edges.filter(e => e.source === chip.parent).map(e => e.id).sort();
  };

  it('each of the 9 audited examples gains exactly the audited Reappears step', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const positives = REAL_CLOSURES.filter(fx => fx.expectReappears.length > 0);
    expect(positives).toHaveLength(9);

    for (const fx of positives) {
      const res = buildFieldStory({
        graph: { nodes: el(fx.nodes), edges: el(fx.edges) },
        table: fx.table, field: fx.field,
      });
      expect(res.seedNodeId).toBe(fx.seedNodeId);
      const rep = res.steps.filter(s => s.kind === 'reappears');
      // exactly one, at the audit's line, titled without any clause name
      expect(rep.map(s => s.id)).toEqual(fx.expectReappears.map(l => `reappears-${l}`));
      expect(rep.map(s => s.line)).toEqual(fx.expectReappears);
      rep.forEach(s => {
        expect(s.title).toBe('Reappears');
        expect(s.detail).toContain(`@L${s.line}`);
      });
      // STRICT: the foreign-sourced SCHEMA twins in the same closure land in
      // NO step — the steps own exactly the own-table edges, nothing else.
      expect(sorted(res.steps.flatMap(s => s.edgeIds))).toEqual(ownEdgeIds(fx));
    }
  });

  it('dm_flag2 (RFN) keeps exactly its four steps — the L1119 mask line stays out', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const fx = REAL_CLOSURES.find(f => f.expectReappears.length === 0);
    expect(fx.field).toBe('dm_flag2');
    // Three SCHEMA edges target this chip — from an alias compound and two
    // ⟐output compounds, one of them AT the mask line 1119 — and none of
    // them comes from the searched table, so none is a Reappears step.
    expect(fx.edges.length).toBe(3);
    expect(fx.edges.map(e => e.highlight_line)).toEqual([1380, 1119, 1380]);

    const res = buildFieldStory({
      graph: { nodes: el(fx.nodes), edges: el(fx.edges) },
      table: fx.table, field: fx.field,
    });
    expect(res.seedNodeId).toBe(fx.seedNodeId);
    expect(res.steps).toEqual([]);           // no reappears, and nothing else
    expect(res.steps.filter(s => s.kind === 'reappears')).toEqual([]);
  });

  it('dm_flag2 keeps exactly its audit steps on its real closure (written×2, consumed×2)', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const fx = REAL_CLOSURES.find(f => f.field === 'dm_flag2');
    // The write/consume legs around the mask line, spliced in verbatim from
    // the same served closure — the story must stay exactly as it was.
    const legs = [
      { id: 'l2e_8d3bf142ceaa_dml_out', source: 'l2_tbl_fd251e9cfa',
        target: 'l2_tbl_2a2a3ba1c1', edge_type: 'TABLE_FLOW',
        flow_kind: 'write', highlight_line: 768 },
      { id: 'l2e_4f9168173bc5_dml_out', source: 'l2_tbl_00356d3a9a',
        target: 'l2_tbl_2a2a3ba1c1', edge_type: 'TABLE_FLOW',
        flow_kind: 'write', highlight_line: 1168 },
      { id: 'l2e_905b94c215c4_dml_out', source: 'l2_tbl_00356d3a9a',
        target: 'l2_tbl_be20ae0caf', edge_type: 'TABLE_FLOW',
        flow_kind: 'write', highlight_line: 1382 },
      { id: 'l2e_289a1047cbdc_dml_out', source: 'l2_tbl_00356d3a9a',
        target: 'l2_tbl_79eb0908d0', edge_type: 'TABLE_FLOW',
        flow_kind: 'write', highlight_line: 1422 },
    ];
    const nodes = [...fx.nodes,
      { id: 'l2_tbl_fd251e9cfa', type: 'intermediate_table', label: 'output',
        table_name: '⟐ output', line_start: 1429 },
      { id: 'l2_tbl_00356d3a9a', type: 'intermediate_table', label: 'output',
        table_name: '⟐ output', line_start: 867 },
      { id: 'l2_tbl_be20ae0caf', type: 'alias_table', label: 'A@1382',
        table_name: 'A', line_start: 1382 },
      { id: 'l2_tbl_79eb0908d0', type: 'alias_table', label: 'B@1422',
        table_name: 'B', line_start: 1422 },
    ];
    const res = buildFieldStory({
      graph: { nodes: el(nodes), edges: el([...fx.edges, ...legs]) },
      table: fx.table, field: fx.field,
    });
    expect(res.steps.map(s => s.id))
      .toEqual(['written-768', 'written-1168', 'consumed-1382', 'consumed-1422']);
  });

  it('mergedEdgeIds needs no change: the merged self-loop rides along, a foreign pair never does', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    for (const fx of REAL_CLOSURES) {
      const res = buildFieldStory({
        graph: { nodes: el(fx.nodes), edges: el(fx.edges) },
        mergedGraph: { nodes: el(fx.mergedNodes), edges: el(fx.mergedEdges) },
        table: fx.table, field: fx.field,
      });
      const rep = res.steps.find(s => s.kind === 'reappears');
      if (!fx.expectReappears.length) {
        expect(rep).toBeUndefined();
        continue;
      }
      // Both namespaces ride the step, resolved by the SAME generic rule the
      // other kinds use — l2e_* on the step, l2m_* via mergedEdgeIds.
      expect(Array.isArray(rep.mergedEdgeIds)).toBe(true);
      expect(sorted(rep.mergedEdgeIds)).toEqual(sorted(fx.expectMergedIds));
    }
    // and the 4 merged self-loops the merged view really carries are real ids
    const withMerged = REAL_CLOSURES.filter(f => f.expectMergedIds.length > 0);
    expect(withMerged.map(f => f.expectMergedIds[0])).toEqual([
      'l2m_c06160e84e2a', 'l2m_6cc57b037902', 'l2m_bebd245bc967', 'l2m_95f839718c7e',
    ]);
  });
});
