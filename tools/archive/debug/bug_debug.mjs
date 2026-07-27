/**
 * Quick debug script to extract node positions from L2 graph
 */
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = 'http://127.0.0.1:8000';
const SAMPLE_ZIP = '/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip';

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  await page.goto(BASE, { waitUntil: 'load', timeout: 60000 });

  // Upload zip
  const [fileChooser] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 15000 }),
    page.getByText('Upload .zip').click(),
  ]);
  await fileChooser.setFiles(SAMPLE_ZIP);
  await page.waitForFunction(() => document.body.innerText.includes('Indexed'), { timeout: 30000 });
  await sleep(1000);

  // Search
  await page.getByPlaceholder('Type table name...').fill('analytics_orders');
  await sleep(500);
  await page.getByPlaceholder('Type field name...').fill('amount');
  await sleep(300);
  await page.getByPlaceholder('Type field name...').press('Enter');
  await sleep(3000);

  // Open L2 for the LAST script node (should be step5 with more... actually they all similar)
  // Let's open step3 which has more nodes
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) {
      const scriptNodes = cy.nodes('[type="script_node"]');
      // Try to find step3
      for (let i = 0; i < scriptNodes.length; i++) {
        const label = scriptNodes[i].data('label') || '';
        if (label.includes('step3') || label.includes('join')) {
          scriptNodes[i].emit('dbltap');
          return;
        }
      }
      // Fall back to first
      if (scriptNodes.length > 0) scriptNodes[0].emit('dbltap');
    }
  });
  await sleep(3000);

  // Now test each mode and capture node positions
  const modes = ['snake', 'pipeline', 'spore'];
  const results = {};

  for (const mode of modes) {
    // Click mode button
    const btn = page.locator(`button:has-text("${mode === 'snake' ? 'Snake' : mode === 'pipeline' ? 'Pipeline' : 'Spore'}")`);
    if (await btn.count() > 0) {
      await btn.click();
      await sleep(2000);
    }

    const info = await page.evaluate((m) => {
      const cy = window.__cy;
      if (!cy || cy.destroyed()) return null;

      const tableNodes = cy.nodes().filter(n => {
        const t = n.data('type') || '';
        return t.endsWith('_table') || t === 'query_output' || t === 'cte_table';
      });

      const tables = tableNodes.map(t => ({
        id: t.id(),
        type: t.data('type'),
        label: t.data('label'),
        x: t.position('x'), y: t.position('y'),
        w: t.data('_tableWidth') || t.width(),
        h: t.data('_tableHeight') || t.height(),
      }));

      // All node positions (truncated)
      const allPositions = {};
      cy.nodes().forEach(n => {
        allPositions[n.id()] = { x: n.position('x'), y: n.position('y') };
      });

      return { mode: m, zoom: cy.zoom(), tables, nodeCount: cy.nodes().length, allPositions };
    }, mode);

    results[mode] = info;
    console.log(`\n=== ${mode.toUpperCase()} MODE ===`);
    console.log(`zoom=${info.zoom} nodes=${info.nodeCount}`);
    console.log('Tables:');
    info.tables.forEach(t => console.log(`  ${t.label} (${t.type}): (${Math.round(t.x)}, ${Math.round(t.y)}) w=${Math.round(t.w)} h=${Math.round(t.h)}`));
    console.log('All nodes:');
    for (const [id, pos] of Object.entries(info.allPositions)) {
      console.log(`  ${id}: (${Math.round(pos.x)}, ${Math.round(pos.y)})`);
    }
  }

  // Compare Pipeline vs Spore
  const pipelinePos = JSON.stringify(results.pipeline.allPositions);
  const sporePos = JSON.stringify(results.spore.allPositions);
  console.log(`\n=== COMPARISON ===`);
  console.log(`Pipeline == Spore: ${pipelinePos === sporePos}`);

  if (pipelinePos !== sporePos) {
    for (const id of Object.keys(results.pipeline.allPositions)) {
      const p = results.pipeline.allPositions[id];
      const s = results.spore.allPositions[id];
      if (p && s) {
        const dx = Math.abs(p.x - s.x);
        const dy = Math.abs(p.y - s.y);
        if (dx > 0.1 || dy > 0.1) {
          console.log(`  ${id}: Pipeline(${Math.round(p.x)},${Math.round(p.y)}) vs Spore(${Math.round(s.x)},${Math.round(s.y)}) diff=(${dx.toFixed(1)},${dy.toFixed(1)})`);
        }
      }
    }
  }

  await browser.close();
}

main().catch(e => {
  console.error('Error:', e);
  process.exit(1);
});
