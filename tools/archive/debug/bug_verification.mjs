/**
 * Bug Verification Test Script — Playwright-based
 *
 * Tests each bug from BUG_ANALYSIS_AND_SUGGESTIONS.md against the running app.
 * Uses the frontend UI via Playwright for layout testing.
 * Partition test is run separately via Python.
 *
 * Setup: Frontend at http://127.0.0.1:8000, API at http://127.0.0.1:8000/api
 * Run: node --no-warnings tools/bug_verification.mjs
 */
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = 'http://127.0.0.1:8000';
const SAMPLE_ZIP = '/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip';
const RESULTS = [];

function report(bugId, status, detail) {
  RESULTS.push({ bugId, status, detail });
  console.log(`[${status}] Bug #${bugId}: ${detail}`);
}

function reportNew(name, severity, detail) {
  RESULTS.push({ bugId: `NEW: ${name}`, status: severity, detail });
  console.log(`[${severity}] NEW: ${name}: ${detail}`);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function getCyInfo(page, cySelector = 'window.__cy') {
  return page.evaluate((sel) => {
    const cy = eval(sel);
    if (!cy || cy.destroyed?.()) return null;

    const container = cy.container();
    const rect = container?.getBoundingClientRect() || { width: 1440, height: 900 };
    const zoom = cy.zoom();
    const pan = cy.pan();
    const vp = { w: rect.width, h: rect.height };
    const level = container?.closest?.('[data-level]')?.dataset?.level || 'unknown';

    // Table positions
    const tableNodes = cy.nodes().filter(n => {
      const t = n.data('type') || '';
      return t.endsWith('_table') || t === 'query_output' || t === 'cte_table' || t === 'table';
    });
    const tables = tableNodes.map(t => ({
      id: t.id(),
      type: t.data('type'),
      x: t.position('x'), y: t.position('y'),
      w: t.data('_tableWidth') || t.width() || 200,
      h: t.data('_tableHeight') || t.height() || 80,
    }));

    // Table overlaps
    let tableOverlaps = 0;
    for (let i = 0; i < tables.length; i++) {
      for (let j = i + 1; j < tables.length; j++) {
        const a = tables[i], b = tables[j];
        const ox = Math.abs(a.x - b.x) < (a.w + b.w) / 2;
        const oy = Math.abs(a.y - b.y) < (a.h + b.h) / 2;
        if (ox && oy) tableOverlaps++;
      }
    }

    // Offscreen edges (midpoint check)
    let offscreenEdges = 0;
    cy.edges().forEach(e => {
      const sp = e.source().position(), tp = e.target().position();
      const mx = (sp.x + tp.x) / 2, my = (sp.y + tp.y) / 2;
      const sx = (mx + pan.x) * zoom, sy = (my + pan.y) * zoom;
      if (sx < -100 || sx > vp.w + 100 || sy < -100 || sy > vp.h + 100) offscreenEdges++;
    });

    // Offscreen nodes
    let offscreenNodes = 0;
    cy.nodes().forEach(n => {
      const p = n.position();
      const sx = (p.x + pan.x) * zoom, sy = (p.y + pan.y) * zoom;
      if (sx < -200 || sx > vp.w + 200 || sy < -200 || sy > vp.h + 200) offscreenNodes++;
    });

    // Field overflow
    let fieldOverflows = 0, totalFields = 0;
    cy.nodes().forEach(n => {
      if (n.data('type') === 'field') {
        totalFields++;
        const pid = n.data('_tableParent');
        if (pid) {
          const p = cy.getElementById(pid);
          if (p.length) {
            const pp = p.position(), fp = n.position();
            const ph = p.data('_tableHeight') || 80, pw = p.data('_tableWidth') || 200;
            if (fp.y < pp.y - ph/2 || fp.y > pp.y + ph/2 ||
                fp.x < pp.x - pw/2 || fp.x > pp.x + pw/2) fieldOverflows++;
          }
        }
      }
    });

    return {
      zoom, pan, level,
      nodeCount: cy.nodes().length, edgeCount: cy.edges().length,
      tables: tables.length, tableOverlaps,
      offscreenEdges, totalEdges: cy.edges().length,
      offscreenNodes, totalNodes: cy.nodes().length,
      fieldOverflows, totalFields,
      viewport: vp,
    };
  }, cySelector);
}

async function main() {
  console.log('=== Bug Verification Suite ===\n');

  // ── 0. API version check ─────────────────────────────────────────
  const healthResp = await fetch(`${BASE}/api/health`);
  const health = await healthResp.json();
  console.log(`API: version=${health.version}, status=${health.status}`);

  // ── 1. Launch browser ────────────────────────────────────────────
  console.log('\n--- Launching Playwright ---');
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  page.on('console', msg => {
    if (msg.type() === 'error') console.log(`  [console.error] ${msg.text().slice(0, 120)}`);
  });

  await page.goto(BASE, { waitUntil: 'load', timeout: 60000 });
  console.log('Page loaded');

  // ── 2. Upload zip ─────────────────────────────────────────────────
  console.log('\n--- Uploading multi_workflow.zip ---');
  const [fileChooser] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 15000 }),
    page.getByText('Upload .zip').click(),
  ]);
  await fileChooser.setFiles(SAMPLE_ZIP);
  console.log('File uploaded');

  // Wait for indexing to complete (look for "Indexed" text)
  try {
    await page.waitForFunction(
      () => document.body.innerText.includes('Indexed'),
      { timeout: 30000 }
    );
    console.log('Indexing complete');
  } catch {
    console.log('Waiting extra for indexing...');
    await sleep(5000);
  }
  await sleep(1000);

  // ── 3. Search for analytics_orders.amount ─────────────────────────
  console.log('\n--- Searching for analytics_orders.amount ---');

  try {
    await page.getByPlaceholder('Type table name...').waitFor({ state: 'visible', timeout: 15000 });

    // Fill table
    const tableInput = page.getByPlaceholder('Type table name...');
    await tableInput.click();
    await tableInput.fill('analytics_orders');
    await sleep(500);

    // Try to pick from dropdown
    const dropdown = page.locator('.autocomplete-dropdown');
    if (await dropdown.isVisible({ timeout: 1000 }).catch(() => false)) {
      const item = dropdown.locator('text=analytics_orders').first();
      if (await item.count() > 0) {
        await item.click();
        await sleep(200);
      }
    }

    // Fill field
    const fieldInput = page.getByPlaceholder('Type field name...');
    await fieldInput.click();
    await fieldInput.fill('amount');
    await sleep(500);

    // Press Enter to search
    await fieldInput.press('Enter');
    console.log('Search triggered');
    await sleep(2000);
  } catch (e) {
    console.log(`Search interaction issue: ${e.message}`);
    await page.screenshot({ path: '/tmp/bug_test_search.png' });
  }

  // Wait for L1 graph
  await sleep(2000);
  let cyInfo = await getCyInfo(page);
  console.log(`L1 initial: ${JSON.stringify(cyInfo)}`);

  // ── 4. Bug #1: Offscreen edges (Snake) ───────────────────────────
  console.log('\n--- Bug #1: Offscreen edges in Snake mode ---');

  // Ensure Snake mode
  const snakeBtn = page.locator('button:has-text("Snake")');
  if (await snakeBtn.count() > 0) {
    await snakeBtn.click();
    await sleep(2000);
  }

  cyInfo = await getCyInfo(page);
  console.log(`Snake mode: ${JSON.stringify(cyInfo)}`);

  if (cyInfo) {
    if (cyInfo.offscreenEdges === 0) {
      report(1, 'FIXED', `0/${cyInfo.totalEdges} edges offscreen in Snake mode`);
    } else {
      reportNew('Bug 1 (Snake offscreen)', 'REGRESSION', `${cyInfo.offscreenEdges}/${cyInfo.totalEdges} edges offscreen`);
    }
  }

  // ── 5. Open L2 (Bug #4) ──────────────────────────────────────────
  console.log('\n--- Bug #4: L2 zoom level ---');

  // Open L2 by double-clicking the first script node
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) {
      const scriptNodes = cy.nodes('[type="script_node"]');
      if (scriptNodes.length > 0) scriptNodes[0].emit('dbltap');
    }
  });
  await sleep(3000);

  // Check data-level attributes
  const allLevels = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('[data-level]')).map(el => ({
      level: el.getAttribute('data-level'),
      class: el.className?.slice(0, 60),
    }));
  });
  console.log(`data-level elements: ${JSON.stringify(allLevels)}`);

  // Check L2 zoom
  cyInfo = await getCyInfo(page);
  console.log(`L2 info: ${JSON.stringify(cyInfo)}`);

  if (cyInfo) {
    if (cyInfo.zoom <= 0.06) {
      report(4, 'CONFIRMED', `L2 zoom=${cyInfo.zoom.toFixed(3)} (at or near minZoom 0.05). L2 view too small. data-level values: ${JSON.stringify(allLevels.map(l => l.level))}`);
    } else if (cyInfo.zoom >= 0.3) {
      report(4, 'FIXED', `L2 zoom=${cyInfo.zoom.toFixed(3)} — reasonable level`);
    } else {
      report(4, 'PARTIAL', `L2 zoom=${cyInfo.zoom.toFixed(3)} — borderline`);
    }

    if (cyInfo.fieldOverflows > 0) {
      reportNew('Field overflow in L2', 'BUG', `${cyInfo.fieldOverflows}/${cyInfo.totalFields} fields overflow parent table`);
    }
  }

  const hasL2DataLevel = allLevels.some(l => l.level === 'L2');
  if (!hasL2DataLevel) {
    reportNew('Missing data-level=L2', 'CONFIRMED', 'No element with data-level="L2" found in DOM');
  }

  // ── 6. Pipeline mode ─────────────────────────────────────────────
  console.log('\n--- Pipeline mode ---');

  // First get Snake positions for comparison
  const snakePositions = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: n.position('x'), y: n.position('y') }; });
    return p;
  });
  console.log(`Snake positions: ${Object.keys(snakePositions || {}).length} nodes`);

  // Switch to Pipeline
  const pipelineBtn = page.locator('button:has-text("Pipeline")');
  if (await pipelineBtn.count() > 0) {
    await pipelineBtn.click();
    await sleep(2000);
  }

  cyInfo = await getCyInfo(page);
  console.log(`Pipeline mode: ${JSON.stringify(cyInfo)}`);

  const pipelinePositions = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: n.position('x'), y: n.position('y') }; });
    return p;
  });

  // ── 7. Spore mode (Bug #5) ───────────────────────────────────────
  console.log('\n--- Bug #5: Spore overlaps ---');

  const sporeBtn = page.locator('button:has-text("Spore")');
  if (await sporeBtn.count() > 0) {
    await sporeBtn.click();
    await sleep(2000);
  }

  cyInfo = await getCyInfo(page);
  console.log(`Spore mode: ${JSON.stringify(cyInfo)}`);

  if (cyInfo) {
    if (cyInfo.tableOverlaps === 0 && cyInfo.offscreenNodes === 0) {
      report(5, 'FIXED', `0/${cyInfo.tables} table overlaps, 0/${cyInfo.totalNodes} offscreen nodes`);
    } else {
      reportNew('Bug 5 (Spore overlaps)', 'REGRESSION',
        `${cyInfo.tableOverlaps}/${cyInfo.tables} table overlaps, ${cyInfo.offscreenNodes}/${cyInfo.totalNodes} offscreen`);
    }
  }

  const sporePositions = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: n.position('x'), y: n.position('y') }; });
    return p;
  });

  // ── Bug #2: Pipeline vs Spore identical ──────────────────────────
  console.log('\n--- Bug #2: Pipeline vs Spore comparison ---');

  if (pipelinePositions && sporePositions) {
    let different = 0, total = 0;
    for (const id of Object.keys(pipelinePositions)) {
      if (sporePositions[id]) {
        total++;
        const dx = Math.abs(pipelinePositions[id].x - sporePositions[id].x);
        const dy = Math.abs(pipelinePositions[id].y - sporePositions[id].y);
        if (dx > 1 || dy > 1) different++;
      }
    }

    if (different > 0) {
      report(2, 'FIXED', `Pipeline and Spore produce different layouts: ${different}/${total} nodes differ`);
    } else {
      reportNew('Bug 2 (Pipeline vs Spore)', 'REGRESSION', `${total} nodes all identical positions`);
    }
  }

  // ── Take final screenshot ────────────────────────────────────────
  await page.screenshot({ path: '/tmp/bug_test_final.png', fullPage: false });
  console.log('\nScreenshot saved to /tmp/bug_test_final.png');

  // ── Summary ──────────────────────────────────────────────────────
  console.log('\n\n===========================');
  console.log('=== RESULTS SUMMARY ===');
  console.log('===========================');
  for (const r of RESULTS) {
    const icon = r.status === 'FIXED' ? 'PASS' : r.status === 'CONFIRMED' ? 'FAIL' : 'WARN';
    console.log(`[${icon}] ${r.bugId}: ${r.detail}`);
  }

  await browser.close();
  console.log('\nDone.');
}

main().catch(e => {
  console.error('Fatal error:', e);
  process.exit(1);
});
