/**
 * Debug - check if cy.fit() works at all
 */
import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8000';
const SAMPLE_ZIP = '/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip';
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });

  // Upload
  const [fc] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 15000 }),
    page.getByText('Upload .zip').click(),
  ]);
  await fc.setFiles(SAMPLE_ZIP);
  await sleep(5000);
  try { await page.waitForFunction(() => document.body.innerText.includes('Indexed'), { timeout: 30000 }); } catch { await sleep(5000); }

  // Search
  await page.getByPlaceholder('Type table name...').fill('analytics_orders');
  await sleep(300);
  await page.getByPlaceholder('Type field name...').fill('amount');
  await sleep(200);
  await page.getByPlaceholder('Type field name...').press('Enter');
  await sleep(3000);

  try { await page.waitForFunction(() => window.__cy && window.__cy.nodes().length > 0, { timeout: 10000 }); } catch { await sleep(5000); }

  // Open L2 for step3
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) {
      const nodes = cy.nodes('[type="script_node"]');
      for (const n of nodes) {
        if ((n.data('label') || '').includes('step3')) { n.emit('dbltap'); return; }
      }
      if (nodes.length > 0) nodes[0].emit('dbltap');
    }
  });
  await sleep(3000);

  // Now test fit with various arguments
  const fitTests = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;

    const results = [];

    // Get current state
    results.push({ test: 'initial', zoom: cy.zoom(), pan: { ...cy.pan() } });

    // Test 1: cy.fit() with no args
    cy.fit();
    results.push({ test: 'fit()', zoom: cy.zoom(), pan: { ...cy.pan() } });

    // Test 2: fit with nodes
    cy.fit(cy.nodes(), 50);
    results.push({ test: 'fit(nodes, 50)', zoom: cy.zoom(), pan: { ...cy.pan() } });

    // Test 3: fit with specific bounding box
    const bb = cy.elements().boundingBox();
    results.push({ test: 'bbox', bb });

    // Test 4: manual zoom to 1
    cy.zoom(1).pan({ x: 0, y: 0 });
    results.push({ test: 'zoom(1)', zoom: cy.zoom(), pan: { ...cy.pan() } });

    // Test 5: fit again after zoom 1
    cy.fit(cy.nodes(), 200);
    results.push({ test: 'fit(nodes, 200) after zoom(1)', zoom: cy.zoom(), pan: { ...cy.pan() } });

    // Test 6: fit(cy.elements(), 200)
    cy.fit(cy.elements(), 200);
    results.push({ test: 'fit(elements, 200)', zoom: cy.zoom(), pan: { ...cy.pan() } });

    // Test 7: check if container dimensions are correct
    const container = cy.container();
    const rect = container?.getBoundingClientRect();

    return {
      results,
      containerRect: rect ? { w: rect.width, h: rect.height, x: rect.x, y: rect.y } : null,
      dataLevel: container?.closest('[data-level]')?.dataset?.level || 'unknown',
    };
  });

  if (!fitTests) {
    console.log('No cy instance found');
    await browser.close();
    return;
  }

  for (const r of fitTests.results) {
    console.log(`${r.test}: zoom=${r.zoom?.toFixed(4) || r.zoom}, pan=(${r.pan?.x?.toFixed(1) || '-'}, ${r.pan?.y?.toFixed(1) || '-'})`);
    if (r.bb) console.log(`  boundingBox: x1=${r.bb.x1.toFixed(1)} y1=${r.bb.y1.toFixed(1)} x2=${r.bb.x2.toFixed(1)} y2=${r.bb.y2.toFixed(1)} w=${r.bb.w.toFixed(1)} h=${r.bb.h.toFixed(1)}`);
  }
  console.log(`Container: ${JSON.stringify(fitTests.containerRect)}`);
  console.log(`data-level: ${fitTests.dataLevel}`);

  await browser.close();
}

main().catch(e => { console.error('Error:', e); process.exit(1); });
