/**
 * Debug script - check container dimensions and actual zoom behavior
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
  page.on('console', msg => {
    if (msg.type() === 'error') console.log(`  [ERR] ${msg.text().slice(0, 150)}`);
  });

  await page.goto(BASE, { waitUntil: 'load', timeout: 60000 });

  // Upload
  const [fc] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 15000 }),
    page.getByText('Upload .zip').click(),
  ]);
  await fc.setFiles(SAMPLE_ZIP);
  await page.waitForFunction(() => document.body.innerText.includes('Indexed'), { timeout: 30000 });
  await sleep(1000);

  // Search
  await page.getByPlaceholder('Type table name...').fill('analytics_orders');
  await sleep(300);
  await page.getByPlaceholder('Type field name...').fill('amount');
  await sleep(200);
  await page.getByPlaceholder('Type field name...').press('Enter');
  await sleep(3000);

  // Wait for L1 graph
  await page.waitForFunction(() => window.__cy && window.__cy.nodes().length > 0, { timeout: 10000 });
  console.log('L1 graph loaded');

  // Check L1 container dimensions
  const l1Dims = await page.evaluate(() => {
    const cy = window.__cy;
    const c = cy.container();
    const r = c?.getBoundingClientRect();
    const p = cy.pan();
    const z = cy.zoom();
    // Check what cy.extent() returns
    const ext = cy.extent();
    return {
      containerRect: r ? { w: r.width, h: r.height, x: r.x, y: r.y } : null,
      zoom: z,
      pan: p,
      extent: ext,
      renderedExtent: cy.extent ? { x1: ext.x1, x2: ext.x2, y1: ext.y1, y2: ext.y2 } : null,
    };
  });
  console.log(`L1 container: ${JSON.stringify(l1Dims)}`);

  // Open L2 for step3
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) {
      const nodes = cy.nodes('[type="script_node"]');
      // Find step3
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

  // Check L2 container dimensions immediately after load
  const l2Dims = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return { error: 'no L2 cy' };

    const c = cy.container();
    const r = c?.getBoundingClientRect();

    // Check which panel is this cy in
    const closestPanel = c?.closest('[class]')?.className || 'unknown';

    // Get all cy instances
    const allCy = [];
    if (window.__cy && !window.__cy.destroyed()) {
      const cc = window.__cy.container();
      const rr = cc?.getBoundingClientRect();
      allCy.push({
        which: '__cy',
        panel: cc?.closest('[class]')?.className?.slice(0, 50) || '?',
        rect: rr ? { w: rr.width, h: rr.height, x: rr.x, y: rr.y } : null,
        zoom: window.__cy.zoom(),
      });
    }
    if (window.__cy1 && !window.__cy1.destroyed()) {
      const cc = window.__cy1.container();
      const rr = cc?.getBoundingClientRect();
      allCy.push({
        which: '__cy1',
        panel: cc?.closest('[class]')?.className?.slice(0, 50) || '?',
        rect: rr ? { w: rr.width, h: rr.height, x: rr.x, y: rr.y } : null,
        zoom: window.__cy1.zoom(),
      });
    }

    const ext = cy.extent();
    return {
      allCy,
      container: r ? { w: r.width, h: r.height, x: r.x, y: r.y, panel: closestPanel } : null,
      zoom: cy.zoom(),
      pan: cy.pan(),
      minZoom: cy.minZoom(),
      extent: { x1: ext.x1, x2: ext.x2, y1: ext.y1, y2: ext.y2 },
      nodeCount: cy.nodes().length,
      // Get first few node positions
      samplePositions: cy.nodes().slice(0, 8).map(n => ({
        id: n.id().slice(0, 20),
        type: n.data('type'),
        x: n.position('x'),
        y: n.position('y'),
      })),
      level: c?.closest('[data-level]')?.dataset?.level || '?',
    };
  });
  console.log(`L2 container: ${JSON.stringify(l2Dims)}`);

  // Now manually call fit and check zoom
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) cy.fit(undefined, 200);
  });
  await sleep(500);

  const afterFit = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    return { zoom: cy.zoom(), pan: cy.pan() };
  });
  console.log(`After manual fit(undefined, 200): zoom=${afterFit.zoom}`);

  // Try fit with all nodes
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) cy.fit(cy.nodes(), 200);
  });
  await sleep(500);

  const afterFitNodes = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return null;
    return { zoom: cy.zoom(), pan: cy.pan() };
  });
  console.log(`After fit(nodes, 200): zoom=${afterFitNodes.zoom}`);

  await browser.close();
}

main().catch(e => {
  console.error('Error:', e);
  process.exit(1);
});
