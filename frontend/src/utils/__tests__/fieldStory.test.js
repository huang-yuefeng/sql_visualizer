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

  it('unrelated edge types (JOIN / SCHEMA) produce no steps', async () => {
    const buildFieldStory = await loadBuildFieldStory();
    const { nodes } = east5Closure();
    const graph = {
      nodes,
      edges: [
        { data: { id: 'j1', source: 'east5.p_dt', target: 'rrcdm',
                  edge_type: 'JOIN', flow_kind: 'field flow', highlight_line: 55 } },
        { data: { id: 's1', source: 'east5', target: 'out41',
                  edge_type: 'SCHEMA', highlight_line: 60 } },
      ],
    };
    const res = buildFieldStory({ graph, fullGraph: graph, table: 'east5_stzfxxb', field: 'p_dt' });

    expect(res.seedNodeId).toBe('east5.p_dt'); // seed still found
    expect(res.steps).toEqual([]);              // but nothing story-worthy
  });
});
