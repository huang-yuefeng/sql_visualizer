/**
 * Debug ELK - check how it's loaded
 */
import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:8000';
const SAMPLE_ZIP = '/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip';
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', msg => {
    if (msg.text().includes('ELK') || msg.text().includes('elk') || msg.text().includes('warn') || msg.type() === 'error')
      console.log(`[${msg.type()}] ${msg.text().slice(0, 200)}`);
  });

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });

  const [fc] = await Promise.all([
    page.waitForEvent('filechooser', { timeout: 15000 }),
    page.getByText('Upload .zip').click(),
  ]);
  await fc.setFiles(SAMPLE_ZIP);
  await page.waitForFunction(() => document.body.innerText.includes('Indexed'), { timeout: 60000 }).catch(() => sleep(10000));
  await sleep(1000);

  await page.getByPlaceholder('Type table name...').fill('analytics_orders');
  await sleep(300);
  await page.getByPlaceholder('Type field name...').fill('amount');
  await sleep(200);
  await page.getByPlaceholder('Type field name...').press('Enter');
  await sleep(3000);

  // Open L2
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) {
      const sn = cy.nodes('[type="script_node"]');
      if (sn.length > 0) sn[Math.min(2, sn.length-1)].emit('dbltap');
    }
  });
  await sleep(3000);

  // Check ELK details
  const elkInfo = await page.evaluate(() => {
    const info = {
      typeofELK: typeof window.ELK,
      elkValue: String(window.ELK),
      elkKeys: window.ELK ? Object.getOwnPropertyNames(window.ELK) : [],
      elkConstructor: window.ELK?.constructor?.name,
      elkPrototypeKeys: window.ELK?.prototype ? Object.getOwnPropertyNames(window.ELK.prototype) : [],
      elkBundled: document.querySelector('script[src*="elk"]')?.src || 'not found',
    };
    return info;
  });
  console.log('ELK info:', JSON.stringify(elkInfo));

  // Now test Pipeline vs Snake
  await page.locator('button:has-text("Snake")').click();
  await sleep(1500);
  const snakeP = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: Math.round(n.position('x')), y: Math.round(n.position('y')) }; });
    return p;
  });

  // Delete old workspace and create new via API to test L1 with Pipeline
  // Actually, let me just check on L2

  // Pipeline
  await page.locator('button:has-text("Pipeline")').click();
  await sleep(2000);
  const pipelineP = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: Math.round(n.position('x')), y: Math.round(n.position('y')) }; });
    return p;
  });

  // Check ELK after Pipeline ran
  const elkAfter = await page.evaluate(() => {
    return {
      typeofELK: typeof window.ELK,
      elkIsFunction: typeof window.ELK === 'function',
      elkIsObject: typeof window.ELK === 'object',
      elkString: String(window.ELK).slice(0, 100),
      elkLayoutInstances: Object.keys(window).filter(k => k.includes('elk') || k.includes('ELK')),
      elkConstructor: window.ELK?.constructor?.name,
    };
  });
  console.log('ELK after Pipeline:', JSON.stringify(elkAfter));

  await browser.close();
}

main().catch(e => { console.error('Error:', e); process.exit(1); });
