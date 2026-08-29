import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import cytoscape from 'cytoscape';
import ELK from 'elkjs/lib/elk.bundled.js';
import { applyElkLayout } from '../elkLayout';
import { computeFieldRelPos, fieldPositionsForTable } from '../layoutCore';
import { ELK_SPACING_LAYER, TABLE_SELECTOR } from '../../config/layout';

/**
 * R42 (2026-08-28): the L2 INITIAL layout is left-to-right — the ELK
 * pipeline (layered, ELK_DIRECTION='RIGHT') so a landscape screen reads
 * sources on the left, DML targets on the right. This probe verifies the
 * GEOMETRY headlessly (no DOM rendering, no backend): a synthetic
 * EAST5-style graph (4 source tables → CTE → query_output → target) is
 * laid out by the REAL applyElkLayout path, and the table x-coordinates
 * must form ≥3 strictly ascending layers.
 *
 * It also pins the "fields keep the previous arrangement" half of the
 * requirement: after the layout, every field must sit at
 * `table.pos + frozen relative offset` (computeFieldRelPos is the single
 * source — the same math drag uses), i.e. the field arrangement is
 * independent of the table layout choice.
 */

// EAST5-style L2 topology: BDM_* sources read into a CTE, which feeds the
// DML query_output (qo_ routing) writing the physical east5 target.
// Field nodes carry _tableParent (post-stripFieldParents shape) — field
// edges are excluded from the ELK input by design, so the layer edges are
// table→table.
function buildEast5StyleGraph() {
  const nodes = [];
  const edges = [];

  const addTable = (id, label, type, fieldNames) => {
    nodes.push({ data: { id, label, type } });
    for (const f of fieldNames) {
      nodes.push({ data: { id: `${id}::${f}`, label: f, type: 'field', _tableParent: id } });
    }
  };

  addTable('src_bdm_acc_entrusted_payment', 'BDM_ACC_ENTRUSTED_PAYMENT', 'source_table',
    ['acct_no', 'entd_paym_amt', 'charge_department']);
  addTable('src_bdm_acc_loan_info', 'BDM_ACC_LOAN_INFO', 'source_table',
    ['contract_no', 'lending_ref', 'loan_amt']);
  addTable('src_bdm_pub_branch', 'BDM_PUB_BRANCH', 'source_table', ['org_no', 'org_no_cbrc']);
  addTable('src_bdm_acc_deposit_acct', 'BDM_ACC_DEPOSIT_ACCT', 'source_table', ['df_dfzh', 'df_dfhm']);
  addTable('cte_counterparty', 't_counterparty', 'cte_table',
    ['stzfdxzh', 'stzfdxhm', 'jrxkzh']);
  addTable('qo_east5_stzfxxb', 'INSERT east5_stzfxxb', 'query_output', []);
  addTable('tgt_east5_stzfxxb', 'east5_stzfxxb', 'output_table',
    ['stzfje', 'stzfrq', 'stzfdxzh']);

  // sources → CTE (copy/transform), CTE → qo (compute), qo → target (write)
  const srcIds = ['src_bdm_acc_entrusted_payment', 'src_bdm_acc_loan_info',
    'src_bdm_pub_branch', 'src_bdm_acc_deposit_acct'];
  srcIds.forEach((s, i) => {
    edges.push({ data: { id: `e_src_${i}`, source: s, target: 'cte_counterparty', type: 'REF' } });
  });
  edges.push({ data: { id: 'e_cte_qo', source: 'cte_counterparty', target: 'qo_east5_stzfxxb', type: 'TRANSFORM' } });
  edges.push({ data: { id: 'e_qo_tgt', source: 'qo_east5_stzfxxb', target: 'tgt_east5_stzfxxb', type: 'DML' } });

  return { nodes, edges };
}

/** Cluster table x-positions into ELK layers (ascending x, gap > half the
 * layer spacing starts a new layer). */
function layersByX(tablePositions) {
  const sorted = [...tablePositions].sort((a, b) => a.x - b.x);
  const tolerance = ELK_SPACING_LAYER / 2;
  const layers = [];
  for (const p of sorted) {
    const last = layers[layers.length - 1];
    if (last && p.x - last.maxX <= tolerance) {
      last.members.push(p);
      last.maxX = Math.max(last.maxX, p.x);
    } else {
      layers.push({ members: [p], maxX: p.x });
    }
  }
  return layers.map(l => ({
    ids: l.members.map(p => p.id),
    minX: Math.min(...l.members.map(p => p.x)),
    maxX: l.maxX,
    meanX: l.members.reduce((s, p) => s + p.x, 0) / l.members.length,
  }));
}

describe('R42 — L2 initial layout is left-to-right (ELK pipeline, direction RIGHT)', () => {
  let cy;

  beforeAll(() => {
    // elkLayout.getElk() prefers window.ELK — inject the real bundled ELK
    // (its worker shim runs under the Node runtime, verified headless).
    window.ELK = ELK;
    // Headless cytoscape (no canvas renderer): the layout code paths all
    // treat a missing container as a viewport fallback (offsetWidth→1440),
    // so geometry math runs identically without a rendered canvas. A headless
    // instance carries NO stylesheet (cytoscape skips style init when
    // headless) while applyLayout() calls cy.style().update() after
    // positioning — in the browser every cy always has a stylesheet, so this
    // stub is a TEST-ONLY seam, never a production path.
    cy = cytoscape({ elements: buildEast5StyleGraph(), headless: true });
    cy.style = () => ({ update: () => {} });
  });

  afterAll(() => {
    if (cy && !cy.destroyed()) cy.destroy();
  });

  it('applyElkLayout runs the real ELK path (no snake fallback)', async () => {
    const ok = await applyElkLayout(cy);
    expect(ok).toBe(true);
  });

  it('tables form ≥3 strictly ascending layers: sources left, DML target right', async () => {
    await applyElkLayout(cy);
    const tablePositions = cy.nodes(TABLE_SELECTOR).map(n => ({
      id: n.id(), x: n.position().x, y: n.position().y,
    }));
    expect(tablePositions.length).toBe(7); // 4 sources + CTE + qo_ + target

    const layers = layersByX(tablePositions);
    expect(layers.length).toBeGreaterThanOrEqual(3);
    for (let i = 1; i < layers.length; i++) {
      expect(layers[i].minX).toBeGreaterThan(layers[i - 1].maxX);
    }

    // Directional reading (landscape): every SOURCE table strictly left of
    // the query_output, which is strictly left of the physical TARGET.
    const xOf = id => tablePositions.find(p => p.id === id).x;
    const srcXs = ['src_bdm_acc_entrusted_payment', 'src_bdm_acc_loan_info',
      'src_bdm_pub_branch', 'src_bdm_acc_deposit_acct'].map(xOf);
    expect(Math.max(...srcXs)).toBeLessThan(xOf('qo_east5_stzfxxb'));
    expect(xOf('qo_east5_stzfxxb')).toBeLessThan(xOf('tgt_east5_stzfxxb'));

    // The write target sits in the RIGHTMOST layer (nothing to its right).
    const lastLayer = layers[layers.length - 1];
    expect(lastLayer.ids).toContain('tgt_east5_stzfxxb');
  });

  it('R42.2 — fields keep the previous arrangement (table.pos + frozen offsets)', async () => {
    await applyElkLayout(cy);
    const fieldRel = computeFieldRelPos(cy);
    expect(Object.keys(fieldRel).length).toBeGreaterThan(0);
    // Every field must sit exactly at its table's center + frozen offset —
    // the identical math the drag handler uses, so the pipeline layout did
    // not reshuffle field chips.
    cy.nodes('[type="field"]').forEach(f => {
      const rel = fieldRel[f.id()];
      expect(rel, `field ${f.id()} has a frozen offset`).toBeTruthy();
      const table = cy.getElementById(rel.parentId);
      expect(f.position().x).toBeCloseTo(table.position().x + rel.rx, 6);
      expect(f.position().y).toBeCloseTo(table.position().y + rel.ry, 6);
    });
    // And the shared helper reproduces the same absolute positions.
    const expected = fieldPositionsForTable(
      cy.getElementById('src_bdm_acc_loan_info').position(),
      fieldRel,
      'src_bdm_acc_loan_info',
    );
    for (const [fid, pos] of Object.entries(expected)) {
      expect(cy.getElementById(fid).position().x).toBeCloseTo(pos.x, 6);
      expect(cy.getElementById(fid).position().y).toBeCloseTo(pos.y, 6);
    }
  });
});
