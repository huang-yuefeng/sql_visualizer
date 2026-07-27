/**
 * Debug ELK - check if it actually loads and produces different results
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
    if (msg.text().includes('ELK') || msg.text().includes('elk') || msg.text().includes('spore') || msg.type() === 'error')
      console.log(`[${msg.type()}] ${msg.text().slice(0, 150)}`);
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

  // Open L2 for step3
  await page.evaluate(() => {
    const cy = window.__cy;
    if (cy && !cy.destroyed()) {
      const sn = cy.nodes('[type="script_node"]');
      for (const n of sn) { if ((n.data('label')||'').includes('step3')) { n.emit('dbltap'); return; } }
      if (sn.length > 0) sn[0].emit('dbltap');
    }
  });
  await sleep(3000);

  // Check ELK availability
  const elkCheck = await page.evaluate(() => ({
    hasELK: typeof window.ELK !== 'undefined',
    elkVersions: window.ELK ? Object.keys(window.ELK) : [],
  }));
  console.log(`ELK available: ${elkCheck.hasELK}`);

  // Test Snake (baseline)
  await page.locator('button:has-text("Snake")').click();
  await sleep(1500);
  const snakePos = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: Math.round(n.position('x')), y: Math.round(n.position('y')) }; });
    return p;
  });
  console.log('Snake positions:', Object.values(snakePos).slice(0,4));

  // Test Pipeline
  // First, check if ELK layout started by listening for warnings
  await page.locator('button:has-text("Pipeline")').click();
  await sleep(2000);

  const pipelinePos = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: Math.round(n.position('x')), y: Math.round(n.position('y')) }; });
    return p;
  });
  console.log('Pipeline positions:', Object.values(pipelinePos).slice(0, 4));

  // Test Spore
  await page.locator('button:has-text("Spore")').click();
  await sleep(2000);

  const sporePos = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy) return null;
    const p = {};
    cy.nodes().forEach(n => { p[n.id()] = { x: Math.round(n.position('x')), y: Math.round(n.position('y')) }; });
    return p;
  });
  console.log('Spore positions:', Object.values(sporePos).slice(0, 4));

  // Compare
  const pipeStr = JSON.stringify(pipelinePos);
  const sporeStr = JSON.stringify(sporePos);
  console.log(`\nPipeline == Spore: ${pipeStr === sporeStr}`);

  if (pipeStr !== sporeStr) {
    for (const id of Object.keys(pipelinePos)) {
      if (sporePos[id] && (pipelinePos[id].x !== sporePos[id].x || pipelinePos[id].y !== sporePos[id].y)) {
        console.log(`  DIFF ${id}: Pipeline(${pipelinePos[id].x},${pipelinePos[id].y}) vs Spore(${sporePos[id].x},${sporePos[id].y})`);
      }
    }
  }

  await browser.close();
}

main().catch(e => { console.error('Error:', e); process.exit(1); });
