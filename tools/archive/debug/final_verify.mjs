/**
 * Final Bug Verification — focuses on what only Playwright can test.
 * Partition test is done via curl + Python.
 *
 * Run: http_proxy="" https_proxy="" no_proxy="*" node --no-warnings tools/final_verify.mjs
 */
import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8000';
const SAMPLE_ZIP = '/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip';
const RESULTS = [];
const sleep = ms => new Promise(r => setTimeout(r, ms));

function report(id, status, detail) {
  RESULTS.push({ id, status, detail });
  const icon = { FIXED: 'PASS', CONFIRMED: 'FAIL', REGRESSION: 'FAIL', PARTIAL: 'WARN', FIXED_PARTIAL: 'PASS' }[status] || 'WARN';
  console.log(`[${icon}] Bug #${id}: ${status} — ${detail}`);
}

function reportNew(name, severity, detail) {
  RESULTS.push({ id: `NEW: ${name}`, status: severity, detail });
  console.log(`[${severity === 'CONFIRMED' ? 'FAIL' : 'WARN'}] NEW: ${name}: ${detail}`);
}

async function main() {
  console.log('=== Final Bug Verification ===\n');

  const health = await (await fetch(`${BASE}/api/health`)).json();
  console.log(`Version: ${health.version}`);

  // ── Launch Playwright ────────────────────────────────────────────
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // Catch console errors
  const consoleErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 200));
  });

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  console.log('Page loaded');

  // ── Upload ──────────────────────────────────────────────────────
  console.log('\n--- Upload ---');
  const [fc] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 15000 }),
    page.getByText('Upload .zip').click(),
  ]);
  await fc.setFiles(SAMPLE_ZIP);
  console.log('Uploading...');

  // Wait for indexing
  await page.waitForFunction(
    () => document.body.innerText.includes('Indexed'),
    { timeout: 60000 }
  ).catch(() => {});
  await sleep(1000);
  console.log('Indexed');

  // ── Search ──────────────────────────────────────────────────────
  console.log('\n--- Search analytics_orders.amount ---');
  try {
    await page.getByPlaceholder('Type table name...').waitFor({ state: 'visible', timeout: 10000 });
    await page.getByPlaceholder('Type table name...').fill('analytics_orders');
    await sleep(400);
    await page.getByPlaceholder('Type field name...').fill('amount');
    await sleep(300);
    await page.getByPlaceholder('Type field name...').press('Enter');
    await sleep(3000);
  } catch {
    console.log('Search interaction issue');
    await page.screenshot({ path: '/tmp/fv_search.png' });
  }

  // Wait for graph
  await sleep(3000);
  const hasGraph = await page.evaluate(() => !!(window.__cy && window.__cy.nodes().length > 0)).catch(() => false);
  console.log(`L1 graph loaded: ${hasGraph}`);

  if (!hasGraph) {
    console.log('Cannot proceed without graph. Taking screenshot.');
    await page.screenshot({ path: '/tmp/fv_no_graph.png' });
    await browser.close();
    return;
  }

  // ── Bug #1: Snake offscreen edges (Document says FIXED) ──────────
  console.log('\n--- Bug #1: Snake offscreen edges ---');

  // Ensure Snake mode
  const snakeBtn = page.locator('button:has-text("Snake")');
  if (await snakeBtn.count() > 0) {
    await snakeBtn.click();
    await sleep(1500);
  }

  const snakeInfo = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    const c = cy.container();
    const r = c?.getBoundingClientRect() || { width: 1172, height: 780 };
    const z = cy.zoom(), p = cy.pan();
    let offscreen = 0, total = 0;
    cy.edges().forEach(e => {
      total++;
      const sp = e.source().position(), tp = e.target().position();
      const mx = (sp.x + tp.x) / 2, my = (sp.y + tp.y) / 2;
      const sx = (mx + p.x) * z, sy = (my + p.y) * z;
      if (sx < -100 || sx > r.width + 100 || sy < -100 || sy > r.height + 100) offscreen++;
    });
    return { offscreen, total, zoom: z };
  });

  if (snakeInfo) {
    console.log(`  ${snakeInfo.offscreen}/${snakeInfo.total} edges offscreen`);
    report(1, snakeInfo.offscreen === 0 ? 'FIXED' : 'REGRESSION',
      `${snakeInfo.offscreen}/${snakeInfo.total} edges offscreen`);
  }

  // ── Open L2 for Bug #4 ──────────────────────────────────────────
  console.log('\n--- Bug #4: L2 zoom level ---');

  // Open L2: double-click a script node
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) {
      const nodes = cy.nodes('[type="script_node"]');
      if (nodes.length > 0) nodes[Math.min(2, nodes.length - 1)].emit('dbltap');
    }
  });
  await sleep(3000);

  const l2Data = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    const c = cy.container();
    const r = c?.getBoundingClientRect();
    const allLevels = Array.from(document.querySelectorAll('[data-level]')).map(el => ({
      level: el.getAttribute('data-level'),
      class: el.className?.slice(0, 40),
    }));
    const bb = cy.elements().boundingBox();
    return {
      zoom: cy.zoom(),
      minZoom: cy.minZoom(),
      viewport: r ? { w: r.width, h: r.height } : null,
      allDataLevels: allLevels,
      boundingBox: bb,
      nodeCount: cy.nodes().length,
    };
  });

  if (l2Data) {
    console.log(`  zoom=${l2Data.zoom.toFixed(3)}, minZoom=${l2Data.minZoom}, vp=${JSON.stringify(l2Data.viewport)}`);
    console.log(`  data-level: ${JSON.stringify(l2Data.allDataLevels)}`);
    console.log(`  boundingBox: w=${l2Data.boundingBox.w.toFixed(0)} h=${l2Data.boundingBox.h.toFixed(0)}`);

    const hasL2Level = l2Data.allDataLevels.some(d => d.level === 'L2');
    if (hasL2Level) {
      if (l2Data.zoom <= 0.06) {
        // Zoom clamped at minZoom. The fit uses FIT_PADDING=200 but L2 panel is only ~420px wide.
        // Available space = 420 - 2*200 = 20px which forces extreme zoom-out.
        report(4, 'CONFIRMED',
          `zoom=${l2Data.zoom.toFixed(3)} at minZoom. data-level="L2" IS present (fix applied). ` +
          `Root cause: FIT_PADDING=200 is too large for ${l2Data.viewport.w}px-wide L2 panel. ` +
          `Available space after padding: ${l2Data.viewport.w - 400}px. ` +
          `bb_w=${l2Data.boundingBox.w.toFixed(0)}. Suggested: use smaller padding for L2 (e.g. 30px).`);
      } else {
        report(4, 'FIXED', `zoom=${l2Data.zoom.toFixed(3)} — reasonable`);
      }
    } else {
      report(4, 'CONFIRMED', 'data-level="L2" missing from DOM — first root cause not fixed');
    }
  }

  // ── Bug #5 & Bug #2: Pipeline + Spore ────────────────────────────
  console.log('\n--- Bug #5: Spore overlaps & Bug #2: Pipeline vs Spore ---');

  // Get Pipeline positions first
  const pipelineBtn = page.locator('button:has-text("Pipeline")');
  if (await pipelineBtn.count() > 0) {
    await pipelineBtn.click();
    await sleep(2000);
  }

  const pipelinePos = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: n.position('x'), y: n.position('y') }; });
    return p;
  });

  // Get Pipeline overlap info
  const pipelineOverlap = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    const tables = cy.nodes().filter(n => (n.data('type') || '').endsWith('_table') || n.data('type') === 'query_output' || n.data('type') === 'cte_table');
    let overlaps = 0;
    const t = tables.map(n => ({ x: n.position('x'), y: n.position('y'), w: n.data('_tableWidth') || 200, h: n.data('_tableHeight') || 80 }));
    for (let i = 0; i < t.length; i++)
      for (let j = i + 1; j < t.length; j++)
        if (Math.abs(t[i].x - t[j].x) < (t[i].w + t[j].w) / 2 && Math.abs(t[i].y - t[j].y) < (t[i].h + t[j].h) / 2) overlaps++;
    return { overlaps, totalTables: tables.length };
  });
  console.log(`  Pipeline: ${JSON.stringify(pipelineOverlap)}`);

  // Switch to Spore
  const sporeBtn = page.locator('button:has-text("Spore")');
  if (await sporeBtn.count() > 0) {
    await sporeBtn.click();
    await sleep(2000);
  }

  const sporePos = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: n.position('x'), y: n.position('y') }; });
    return p;
  });

  const sporeOverlap = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    const tables = cy.nodes().filter(n => (n.data('type') || '').endsWith('_table'));
    let overlaps = 0;
    const t = tables.map(n => ({ x: n.position('x'), y: n.position('y'), w: n.data('_tableWidth') || 200, h: n.data('_tableHeight') || 80 }));
    for (let i = 0; i < t.length; i++)
      for (let j = i + 1; j < t.length; j++)
        if (Math.abs(t[i].x - t[j].x) < (t[i].w + t[j].w) / 2 && Math.abs(t[i].y - t[j].y) < (t[i].h + t[j].h) / 2) overlaps++;
    return { overlaps, totalTables: tables.length };
  });
  console.log(`  Spore: ${JSON.stringify(sporeOverlap)}`);

  // Bug #5: Spore overlaps
  if (sporeOverlap) {
    report(5, sporeOverlap.overlaps === 0 ? 'FIXED' : 'CONFIRMED',
      `${sporeOverlap.overlaps}/${sporeOverlap.totalTables} table overlaps in Spore mode`);
  }

  // Bug #2: Pipeline vs Spore comparison
  if (pipelinePos && sporePos) {
    let different = 0, total = 0;
    for (const id of Object.keys(pipelinePos)) {
      if (sporePos[id]) {
        total++;
        if (Math.abs(pipelinePos[id].x - sporePos[id].x) > 1 || Math.abs(pipelinePos[id].y - sporePos[id].y) > 1) different++;
      }
    }
    console.log(`  Comparison: ${different}/${total} nodes differ`);
    report(2, different > 0 ? 'FIXED' : 'REGRESSION',
      `${different}/${total} node positions differ between Pipeline and Spore`);
  }

  // ── Check for field overflow ─────────────────────────────────────
  console.log('\n--- Field overflow check ---');
  const fieldInfo = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    let overflow = 0, total = 0;
    cy.nodes().forEach(n => {
      if (n.data('type') === 'field') {
        total++;
        const pid = n.data('_tableParent');
        if (pid) {
          const p = cy.getElementById(pid);
          if (p.length) {
            const pp = p.position(), fp = n.position();
            const ph = p.data('_tableHeight') || 80, pw = p.data('_tableWidth') || 200;
            if (fp.y < pp.y - ph / 2 || fp.y > pp.y + ph / 2 || fp.x < pp.x - pw / 2 || fp.x > pp.x + pw / 2) overflow++;
          }
        }
      }
    });
    return { overflow, total };
  });

  if (fieldInfo && fieldInfo.overflow > 0) {
    reportNew('Field overflow', 'BUG', `${fieldInfo.overflow}/${fieldInfo.total} field nodes exceed parent table bounds`);
  } else if (fieldInfo) {
    console.log(`  All ${fieldInfo.total} field nodes within table bounds`);
  }

  // ── Console errors ──────────────────────────────────────────────
  const realErrors = consoleErrors.filter(e =>
    !e.includes('Deprecation') && !e.includes('favicon') && !e.includes('ERR_BLOCKED') &&
    !e.includes('Warning') && !e.includes('ResizeObserver')
  );
  if (realErrors.length > 0) {
    reportNew('Console errors', 'INFO', `${realErrors.length} console errors (${realErrors.slice(0, 3).join('; ')})`);
  }

  // ── Screenshot ──────────────────────────────────────────────────
  await page.screenshot({ path: '/tmp/final_verify.png' });

  await browser.close();

  // ── Summary ─────────────────────────────────────────────────────
  console.log('\n\n' + '='.repeat(60));
  console.log('FINAL SUMMARY');
  console.log('='.repeat(60));
  for (const r of RESULTS) {
    let icon = '?';
    switch (r.status) {
      case 'FIXED': icon = 'PASS'; break;
      case 'FIXED_PARTIAL': icon = 'PASS'; break;
      case 'CONFIRMED': case 'REGRESSION': icon = 'FAIL'; break;
      default: icon = 'WARN';
    }
    console.log(`[${icon}] ${r.id}: ${r.status}`);
    console.log(`       ${r.detail}`);
  }
  console.log('='.repeat(60));
}

main().catch(e => {
  console.error('Fatal:', e.message);
  process.exit(1);
});
