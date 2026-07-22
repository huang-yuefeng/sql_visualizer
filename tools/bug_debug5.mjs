/**
 * Debug - test cy.fit() with different padding values
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

  const [fc] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 15000 }),
    page.getByText('Upload .zip').click(),
  ]);
  await fc.setFiles(SAMPLE_ZIP);
  await sleep(5000);
  try { await page.waitForFunction(() => document.body.innerText.includes('Indexed'), { timeout: 30000 }); } catch { await sleep(5000); }

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

  const fitTests = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;

    const results = [];
    const testPaddings = [0, 10, 20, 50, 100, 150, 180, 200, 250, 300, 500];

    for (const p of testPaddings) {
      cy.zoom(1).pan({ x: 0, y: 0 });  // reset first
      cy.fit(cy.nodes(), p);
      results.push({ padding: p, zoom: cy.zoom(), pan: { ...cy.pan() } });
    }

    // Also test with all elements
    results.push({ padding: 'elements-0', zoom: null, pan: null });
    for (const p of [0, 50, 100, 200]) {
      cy.zoom(1).pan({ x: 0, y: 0 });
      cy.fit(cy.elements(), p);
      results.push({ padding: `elements-${p}`, zoom: cy.zoom(), pan: { ...cy.pan() } });
    }

    // Also check rendered node dimensions
    const nodeDims = cy.nodes().map(n => ({
      id: n.id().slice(0, 25),
      type: n.data('type'),
      renderedW: n.renderedOuterWidth(),
      renderedH: n.renderedOuterHeight(),
      bb: n.boundingBox(),
    }));

    // Check container size
    const rect = cy.container()?.getBoundingClientRect();

    return { results, nodeDims, container: rect ? { w: rect.width, h: rect.height } : null };
  });

  if (!fitTests) { console.log('No cy'); await browser.close(); return; }

  console.log(`Container: ${JSON.stringify(fitTests.container)}`);
  console.log('\nFit tests (nodes):');
  for (const r of fitTests.results) {
    if (r.zoom !== null) {
      console.log(`  padding=${r.padding}: zoom=${r.zoom.toFixed(4)} pan=(${r.pan.x.toFixed(1)}, ${r.pan.y.toFixed(1)})`);
    }
  }

  console.log('\nRendered node dimensions:');
  for (const n of fitTests.nodeDims) {
    console.log(`  ${n.id} [${n.type}] renderedW=${n.renderedW?.toFixed(1)} renderedH=${n.renderedH?.toFixed(1)} bb=(${n.bb.x1.toFixed(1)},${n.bb.y1.toFixed(1)},${n.bb.x2.toFixed(1)},${n.bb.y2.toFixed(1)})`);
  }

  await browser.close();
}

main().catch(e => { console.error('Error:', e); process.exit(1); });
