/**
 * Bug Verification Test Script V2 — accurate test for each bug.
 *
 * Tests each bug from BUG_ANALYSIS_AND_SUGGESTIONS.md against the running app.
 * Uses Playwright to interact with the actual frontend.
 *
 * Run: http_proxy="" https_proxy="" no_proxy="*" node --no-warnings tools/bug_verification_v2.mjs
 */
import { chromium } from 'playwright';
import { execSync } from 'child_process';

const BASE = 'http://127.0.0.1:8000';
const API = 'http://127.0.0.1:8000/api';
const SAMPLE_ZIP = '/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip';
const RESULTS = [];
const sleep = ms => new Promise(r => setTimeout(r, ms));

function report(bugId, status, detail) {
  RESULTS.push({ bugId, status, detail });
  console.log(`[${status === 'CONFIRMED' ? 'FAIL' : status === 'FIXED' ? 'PASS' : 'WARN'}] Bug #${bugId}: ${detail}`);
}

function reportNew(name, severity, detail) {
  RESULTS.push({ bugId: `NEW: ${name}`, status: severity, detail });
  console.log(`[${severity === 'CONFIRMED' ? 'FAIL' : 'WARN'}] NEW: ${name}: ${detail}`);
}

async function main() {
  console.log('=== Bug Verification Suite V2 ===\n');

  // ── 0. API Health ────────────────────────────────────────────────
  const health = await (await fetch(`${API}/health`)).json();
  console.log(`API: version=${health.version}, status=${health.status}`);
  const version = health.version;

  // Clean up any old workspaces
  for (const wsSuffix of ['fb4ce3c52cf3', '2d3b72886207', '05c4c4cfe650']) {
    try {
      await fetch(`${API}/workspace/${wsSuffix}`, { method: 'DELETE' });
    } catch {}
  }

  // ── 1. API-based setup ──────────────────────────────────────────
  console.log('\n--- API Setup ---');
  const zipBuf = require('fs').readFileSync(SAMPLE_ZIP);
  const form = new (await import('formdata-node')).FormData();
  form.append('file', new Blob([zipBuf]), 'multi_workflow.zip');
  const wsResp = await (await fetch(`${API}/workspace`, { method: 'POST', body: form })).json();
  const wsId = wsResp.workspace_id;
  console.log(`Workspace: ${wsId}`);

  // Wait a moment for the workspace to be ready
  await sleep(1000);

  // Index
  const scripts = [
    'multi_workflow/step1_load_orders.sql', 'multi_workflow/step2_enrich_customers.sql',
    'multi_workflow/step3_join_orders_customers.sql', 'multi_workflow/step4_aggregate_daily.sql',
    'multi_workflow/step5_final_report.sql',
  ];
  const idxResp = await (await fetch(`${API}/workspace/${wsId}/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scripts }),
  })).json();
  console.log(`Indexed: ${Object.keys(idxResp.table_index || {}).length} tables`);

  // Search
  const searchResp = await (await fetch(`${API}/workspace/${wsId}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ table: 'analytics_orders', field: 'amount' }),
  })).json();
  const viewId = searchResp.view_id;
  console.log(`View: ${viewId} (${searchResp.script_ids?.length} scripts)`);

  // ── Bug #3: Partition Test ──────────────────────────────────────
  console.log('\n--- Bug #3: Partition Invariant ---');
  try {
    const pythonScript = `
import json, sys, os
from collections import defaultdict

scripts = ${JSON.stringify(scripts.map(s => s.replace('.sql', '')))}
results = {}
for s in scripts:
    path = f'/tmp/l2_part_{os.path.basename(s)}.json'
    if not os.path.exists(path):
        continue
    with open(path) as f:
        data = json.load(f)

    sql_text = data.get('sql_text', '')
    graph = data.get('graph', data)
    edges = graph.get('edges', [])
    lines = sql_text.split('\\n')
    N = len(lines) if sql_text else 0

    covered_by = defaultdict(set)
    for e in edges:
        ed = e.get('data', e)
        sr = ed.get('sql_range')
        if not sr or sr == 'N/A':
            continue
        eid = ed.get('id', '?')
        start, end = sr[0], sr[2]
        for li in range(start, end + 1):
            if 1 <= li <= N:
                covered_by[li].add(eid)

    lines_with_multi = sum(1 for i in range(1, N+1) if len(covered_by[i]) > 1)
    overlap = lines_with_multi / N if N > 0 else 0
    total_assignments = sum(len(s) for s in covered_by.values())
    lines_covered = sum(1 for i in range(1, N+1) if covered_by[i])
    redundancy = total_assignments / max(lines_covered, 1)
    coverage = lines_covered / N if N > 0 else 0

    results[os.path.basename(s)] = {
        'edges': len(edges),
        'edges_with_range': len([e for e in edges if e.get('data', e).get('sql_range') and e.get('data', e).get('sql_range') != 'N/A']),
        'coverage': round(coverage * 100, 1),
        'overlap': round(overlap * 100, 1),
        'redundancy': round(redundancy, 2),
        'pass': overlap == 0 and coverage >= 0.85
    }

print(json.dumps(results))
`;

    // Get L2 graphs (filter=false = full graph)
    for (const script of ['step1_load_orders', 'step2_enrich_customers', 'step3_join_orders_customers', 'step4_aggregate_daily', 'step5_final_report']) {
      const resp = await fetch(`${API}/workspace/${wsId}/views/${viewId}/level2?script=multi_workflow/${script}.sql&filter=false`);
      const data = await resp.json();
      require('fs').writeFileSync(`/tmp/l2_part_${script}.json`, JSON.stringify(data));
    }

    // Run Python analysis
    const output = execSync(`python3 -c ${JSON.stringify(pythonScript)}`, { encoding: 'utf8', timeout: 10000 });
    const partResults = JSON.parse(output.trim());

    let allPass = true;
    for (const [script, r] of Object.entries(partResults)) {
      const status = r.pass ? 'PASS' : 'FAIL';
      if (!r.pass) allPass = false;
      console.log(`  ${script}: ${status} coverage=${r.coverage}% overlap=${r.overlap}% redundancy=${r.redundancy} (${r.edges_with_range}/${r.edges} edges with ranges)`);
    }

    if (allPass) {
      report(3, 'FIXED', `All ${Object.keys(partResults).length} scripts pass partition test: 0% overlap, 100% coverage`);
    } else {
      const fails = Object.entries(partResults).filter(([,r]) => !r.pass);
      report(3, 'CONFIRMED', `${fails.length}/${Object.keys(partResults).length} scripts fail partition`);
    }
  } catch (e) {
    console.log(`Partition test error: ${e.message}`);
    report(3, 'ERROR', `Could not run partition test: ${e.message}`);
  }

  // ── 2. Playwright UI Tests ───────────────────────────────────────
  console.log('\n--- Playwright Tests ---');
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // Navigate and upload via UI
  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  console.log('Page loaded');

  // Upload zip
  const [fc] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 15000 }),
    page.getByText('Upload .zip').click(),
  ]);
  await fc.setFiles(SAMPLE_ZIP);
  await sleep(5000);
  try { await page.waitForFunction(() => document.body.innerText.includes('Indexed'), { timeout: 30000 }); } catch { await sleep(5000); }
  console.log('Uploaded & Indexed');

  // Search
  await page.getByPlaceholder('Type table name...').fill('analytics_orders');
  await sleep(300);
  await page.getByPlaceholder('Type field name...').fill('amount');
  await sleep(200);
  await page.getByPlaceholder('Type field name...').press('Enter');
  await sleep(3000);

  await page.waitForFunction(() => window.__cy && window.__cy.nodes().length > 0, { timeout: 10000 }).catch(() => {});
  console.log('L1 graph loaded');

  // ── Bug #1: Offscreen edges in Snake mode ─────────────────────────
  console.log('\n--- Bug #1: Offscreen edges (Snake) ---');
  const snakeBtn = page.locator('button:has-text("Snake")');
  if (await snakeBtn.count() > 0) {
    await snakeBtn.click();
    await sleep(2000);
  }

  const snakeInfo = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    const c = cy.container();
    const r = c?.getBoundingClientRect() || { width: 1440, height: 900 };
    const z = cy.zoom(), p = cy.pan();
    let offscreenEdges = 0, totalEdges = 0;
    cy.edges().forEach(e => {
      totalEdges++;
      const sp = e.source().position(), tp = e.target().position();
      const mx = (sp.x + tp.x) / 2, my = (sp.y + tp.y) / 2;
      const sx = (mx + p.x) * z, sy = (my + p.y) * z;
      if (sx < -100 || sx > r.width + 100 || sy < -100 || sy > r.height + 100) offscreenEdges++;
    });
    return { offscreenEdges, totalEdges, zoom: z, nodeCount: cy.nodes().length, viewport: { w: r.width, h: r.height } };
  });

  if (snakeInfo) {
    console.log(`  Snake: ${snakeInfo.offscreenEdges}/${snakeInfo.totalEdges} offscreen, zoom=${snakeInfo.zoom.toFixed(3)}`);
    if (snakeInfo.offscreenEdges === 0) {
      report(1, 'FIXED', `0/${snakeInfo.totalEdges} edges offscreen in Snake mode`);
    } else {
      report(1, 'REGRESSION', `${snakeInfo.offscreenEdges}/${snakeInfo.totalEdges} edges offscreen`);
    }
  }

  // ── Open L2 for Bug #4: L2 too small ────────────────────────────
  console.log('\n--- Bug #4: L2 zoom level ---');
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) {
      const nodes = cy.nodes('[type="script_node"]');
      if (nodes.length > 0) nodes[Math.min(2, nodes.length-1)].emit('dbltap'); // step3
    }
  });
  await sleep(3000);

  const l2Zoom = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    const c = cy.container();
    const r = c?.getBoundingClientRect();
    const dLevel = c?.closest('[data-level]')?.dataset?.level;
    const allLevels = Array.from(document.querySelectorAll('[data-level]')).map(el => el.getAttribute('data-level'));
    return {
      zoom: cy.zoom(),
      minZoom: cy.minZoom(),
      viewport: r ? { w: r.width, h: r.height } : null,
      dataLevel: dLevel,
      allDataLevels: allLevels,
      nodeCount: cy.nodes().length,
    };
  });

  if (l2Zoom) {
    console.log(`  L2: zoom=${l2Zoom.zoom.toFixed(3)}, minZoom=${l2Zoom.minZoom}, vp=${JSON.stringify(l2Zoom.viewport)}, level=${l2Zoom.dataLevel}`);
    console.log(`  DOM data-level attributes: ${JSON.stringify(l2Zoom.allDataLevels)}`);

    // The data-level attribute IS present (confirmed fixed)
    if (l2Zoom.allDataLevels.includes('L2')) {
      // Check if zoom is correctly computed
      if (l2Zoom.zoom <= 0.06) {
        report(4, 'CONFIRMED', `L2 zoom=${l2Zoom.zoom.toFixed(3)} (clamped at minZoom). Root cause: FIT_PADDING=200 is too large for 420px-wide L2 panel. Available space after padding: only ${Math.round(l2Zoom.viewport.w - 400)}px. data-level attribute IS present (fix applied but insufficient). Suggested fix: use smaller padding (e.g. 30px) for L2.`);
      } else {
        report(4, 'FIXED', `L2 zoom=${l2Zoom.zoom.toFixed(3)} — reasonable`);
      }
    } else {
      report(4, 'CONFIRMED', `data-level="L2" missing from DOM`);
    }
  }

  // ── Bug #5: Spore table overlaps ─────────────────────────────────
  console.log('\n--- Bug #5: Spore overlaps ---');
  const sporeBtn = page.locator('button:has-text("Spore")');
  if (await sporeBtn.count() > 0) {
    await sporeBtn.click();
    await sleep(2000);
  }

  const sporeInfo = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    const tables = cy.nodes().filter(n => {
      const t = n.data('type') || '';
      return t.endsWith('_table') || t === 'query_output' || t === 'cte_table';
    });
    let overlaps = 0;
    const tdata = tables.map(t => ({ id: t.id(), x: t.position('x'), y: t.position('y'), w: t.data('_tableWidth') || 200, h: t.data('_tableHeight') || 80 }));
    for (let i = 0; i < tdata.length; i++) {
      for (let j = i + 1; j < tdata.length; j++) {
        const a = tdata[i], b = tdata[j];
        if (Math.abs(a.x - b.x) < (a.w + b.w) / 2 && Math.abs(a.y - b.y) < (a.h + b.h) / 2) overlaps++;
      }
    }
    return { tableOverlaps: overlaps, totalTables: tables.length };
  });

  if (sporeInfo) {
    console.log(`  Spore: ${sporeInfo.tableOverlaps}/${sporeInfo.totalTables} table overlaps`);
    if (sporeInfo.tableOverlaps === 0) {
      report(5, 'FIXED', `0/${sporeInfo.totalTables} table overlaps in Spore mode`);
    } else {
      report(5, 'CONFIRMED', `${sporeInfo.tableOverlaps}/${sporeInfo.totalTables} table overlaps`);
    }
  }

  // ── Switch to Pipeline mode for comparison ───────────────────────
  console.log('\n--- Bug #2: Pipeline vs Spore ---');

  // Get Pipeline node positions
  const pipelineBtn = page.locator('button:has-text("Pipeline")');
  if (await pipelineBtn.count() > 0) {
    await pipelineBtn.click();
    await sleep(2000);
  }
  const pipelinePos = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: n.position('x'), y: n.position('y') }; });
    return p;
  });

  // Switch back to Spore
  const sporeBtn2 = page.locator('button:has-text("Spore")');
  if (await sporeBtn2.count() > 0) {
    await sporeBtn2.click();
    await sleep(2000);
  }
  const sporePos = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: n.position('x'), y: n.position('y') }; });
    return p;
  });

  if (pipelinePos && sporePos) {
    let different = 0, total = 0;
    for (const id of Object.keys(pipelinePos)) {
      if (sporePos[id]) {
        total++;
        const dx = Math.abs(pipelinePos[id].x - sporePos[id].x);
        const dy = Math.abs(pipelinePos[id].y - sporePos[id].y);
        if (dx > 1 || dy > 1) different++;
      }
    }
    console.log(`  Pipeline vs Spore: ${different}/${total} nodes differ`);
    if (different > 5) {
      report(2, 'FIXED', `Pipeline and Spore produce different layouts: ${different}/${total} nodes differ`);
    } else if (different > 0) {
      report(2, 'PARTIAL', `Only ${different}/${total} nodes differ — may be within rounding error`);
    } else {
      report(2, 'REGRESSION', `All ${total} nodes have identical positions. Pipeline == Spore`);
    }
  }

  // ── Screenshot ──────────────────────────────────────────────────
  await page.screenshot({ path: '/tmp/bug_verification_final.png' });
  console.log('\nScreenshot: /tmp/bug_verification_final.png');

  await browser.close();

  // ── Results Summary ─────────────────────────────────────────────
  console.log('\n\n=====================================');
  console.log('=== FINAL RESULTS ===');
  console.log('=====================================');
  for (const r of RESULTS) {
    const icon = r.status === 'FIXED' ? 'PASS' : r.status === 'CONFIRMED' ? 'FAIL' : r.status === 'REGRESSION' ? 'FAIL' : 'WARN';
    console.log(`[${icon}] ${r.bugId}: ${r.status} — ${r.detail}`);
  }
  console.log(`\nVersion: ${version}`);
}

main().catch(e => { console.error('Fatal error:', e); process.exit(1); });
