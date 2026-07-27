/**
 * Debug node positions - find the elements causing extreme extents
 */
import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8000';
const SAMPLE_ZIP = '/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip';
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  console.log('Page loaded (domcontentloaded)');

  // Upload
  const [fc] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 15000 }),
    page.getByText('Upload .zip').click(),
  ]);
  await fc.setFiles(SAMPLE_ZIP);
  await sleep(5000);

  // Wait for indexed
  try {
    await page.waitForFunction(() => document.body.innerText.includes('Indexed'), { timeout: 30000 });
  } catch {
    console.log('Waiting extra for index...');
    await sleep(5000);
  }
  console.log('Indexed');

  // Search
  await page.getByPlaceholder('Type table name...').fill('analytics_orders');
  await sleep(300);
  await page.getByPlaceholder('Type field name...').fill('amount');
  await sleep(200);
  await page.getByPlaceholder('Type field name...').press('Enter');
  await sleep(3000);

  // Wait for L1 graph
  try {
    await page.waitForFunction(() => window.__cy && window.__cy.nodes().length > 0, { timeout: 10000 });
  } catch {
    console.log('No graph yet, waiting...');
    await sleep(5000);
  }
  console.log('L1 graph loaded');

  // Open L2 for step3
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) {
      const nodes = cy.nodes('[type="script_node"]');
      for (const n of nodes) {
        if ((n.data('label') || '').includes('step3')) {
          n.emit('dbltap');
          return;
        }
      }
      if (nodes.length > 0) nodes[0].emit('dbltap');
    }
  });
  await sleep(3000);

  // Now get ALL node positions
  const allPositions = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;

    // Get bounding box of all elements
    const bb = cy.elements().boundingBox();

    return {
      boundingBox: bb,
      zoom: cy.zoom(),
      pan: cy.pan(),
      minZoom: cy.minZoom(),
      maxZoom: cy.maxZoom(),
      // All nodes positions
      nodes: cy.nodes().map(n => ({
        id: n.id().slice(0, 25),
        label: (n.data('label') || '').slice(0, 20),
        type: n.data('type'),
        x: Math.round(n.position('x')),
        y: Math.round(n.position('y')),
        w: Math.round(n.data('_tableWidth') || n.width() || 0),
        h: Math.round(n.data('_tableHeight') || n.height() || 0),
      })),
      // Check for elements at extreme positions
      extreme: cy.nodes().filter(n => {
        return Math.abs(n.position('x')) > 500 || Math.abs(n.position('y')) > 500;
      }).map(n => ({
        id: n.id().slice(0, 25),
        type: n.data('type'),
        x: n.position('x'),
        y: n.position('y'),
      })),
    };
  });

  console.log(`Zoom: ${allPositions.zoom}, minZoom: ${allPositions.minZoom}, maxZoom: ${allPositions.maxZoom}`);
  console.log(`Bounding box: ${JSON.stringify(allPositions.boundingBox)}`);
  console.log(`Nodes at extreme positions: ${allPositions.extreme.length}`);
  for (const e of allPositions.extreme) {
    console.log(`  EXTREME: ${e.id} type=${e.type} (${e.x}, ${e.y})`);
  }

  console.log('\nAll nodes:');
  for (const n of allPositions.nodes) {
    console.log(`  ${n.id} [${n.type}] "${n.label}" @(${n.x}, ${n.y}) ${n.w}x${n.h}`);
  }

  await browser.close();
}

main().catch(e => {
  console.error('Error:', e);
  process.exit(1);
});
