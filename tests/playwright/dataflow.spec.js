// @ts-check
const { test, expect } = require('@playwright/test');

const BASE = 'http://localhost:8000';
const TEST_ZIP = '/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip';

// R29 made upstream (writing flow) the default search direction. crm_customers
// is a SOURCE table — it has no writing flow, so querying it yields an empty
// no_flow view. Every test searches an OUTPUT field (stg_customers.region),
// whose upstream flow runs crm_customers.region → step2 → stg_customers.region
// and produces a real L1 with script nodes.
const SEARCH_TBL = 'stg_customers';
const SEARCH_FIELD = 'region';

// Production builds (localhost:8000 = the gps-sql release container) gate the
// window.__cy / __cy1 debug globals behind import.meta.env.DEV (v3.3.149), so
// those handles never exist in the deployed app. Cytoscape itself registers the
// live instance on its container element (container._cyreg.cy) in every build;
// the tests read that instead — no app code change required. Each DataFlowGraph
// renders `.dataflow-graph-container[data-level="L1"|"L2"]` with the
// `.graph-canvas` inside it, so the right instance is selected by level.

async function search(page) {
  await page.getByRole('textbox', { name: 'Type table name...' }).fill(SEARCH_TBL);
  await page.getByRole('textbox', { name: 'Type field name...' }).fill(SEARCH_FIELD);
  await page.getByRole('textbox', { name: 'Type field name...' }).press('Enter');
  await page.waitForSelector('.dataflow-graph-container[data-level="L1"]');
  await page.waitForTimeout(2000);
}

async function openL2(page) {
  await page.evaluate(() => {
    const el = document.querySelector('.dataflow-graph-container[data-level="L1"] .graph-canvas');
    const cy = el && el._cyreg && el._cyreg.cy;
    if (cy) cy.nodes('[type="script_node"]').eq(0).emit('dbltap');
  });
  await page.waitForSelector('.dataflow-graph-container[data-level="L2"]');
  await page.waitForTimeout(2000);
}

async function tapFirstL2Edge(page) {
  await page.evaluate(() => {
    const el = document.querySelector('.dataflow-graph-container[data-level="L2"] .graph-canvas');
    const cy = el && el._cyreg && el._cyreg.cy;
    if (cy && cy.edges().length > 0) cy.edges()[0].emit('tap');
  });
  await page.waitForTimeout(500);
}

test.describe('SQL Data Flow Debugger', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto(BASE);
    // Click Data Flow Debugger tab
    await page.getByRole('button', { name: 'Data Flow Debugger' }).click();
    // Upload test data
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.getByText('Upload .zip').click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(TEST_ZIP);
    // Wait for indexing
    await page.waitForTimeout(5000);
  });

  test('R1: Upload folder and see file tree', async ({ page }) => {
    // Verify file tree is visible with 5 SQL scripts
    await expect(page.getByText('step1_load_orders.sql')).toBeVisible();
    await expect(page.getByText('step5_final_report.sql')).toBeVisible();
    await expect(page.getByText('Indexed 5 scripts')).toBeVisible();
  });

  test('R2: Search table.field shows L1 graph', async ({ page }) => {
    await search(page);

    // L1 graph should appear with the L1 header badge
    await expect(page.getByText('Cross-Script Pipeline')).toBeVisible();
    // The directional L1 must contain at least one script node
    const scriptNodes = await page.evaluate(() => {
      const el = document.querySelector('.dataflow-graph-container[data-level="L1"] .graph-canvas');
      const cy = el && el._cyreg && el._cyreg.cy;
      return cy ? cy.nodes('[type="script_node"]').length : 0;
    });
    expect(scriptNodes).toBeGreaterThan(0);
  });

  test('R3: Double-click script opens L2 with edges', async ({ page }) => {
    await search(page);
    await openL2(page);

    // L2 panel should appear
    await expect(page.getByText('Level 2 Detail')).toBeVisible();
    await expect(page.getByText('Per-Script Detail')).toBeVisible();

    // Should have edges
    const edgeCount = await page.evaluate(() => {
      const el = document.querySelector('.dataflow-graph-container[data-level="L2"] .graph-canvas');
      const cy = el && el._cyreg && el._cyreg.cy;
      return cy ? cy.edges().length : 0;
    });
    expect(edgeCount).toBeGreaterThan(0);
  });

  test('R4: Edge click highlights SQL', async ({ page }) => {
    await search(page);
    await openL2(page);
    await tapFirstL2Edge(page);

    // Verify SQL highlight appears
    const highlighted = await page.evaluate(() =>
      document.querySelectorAll('.sql-line.edge-highlighted').length
    );
    expect(highlighted).toBeGreaterThan(0);
  });

  test('R5: No field nodes exceed table bounds', async ({ page }) => {
    await search(page);
    await openL2(page);

    const exceeds = await page.evaluate(() => {
      const el = document.querySelector('.dataflow-graph-container[data-level="L2"] .graph-canvas');
      const cy = el && el._cyreg && el._cyreg.cy;
      if (!cy) return -1;
      let count = 0;
      cy.nodes('[type="field"]').forEach(f => {
        const fp = f.position();
        const pid = f.data('_tableParent');
        if (!pid) return;
        const p = cy.getElementById(pid);
        if (!p.length) return;
        const ph = p.data('_tableHeight') || 80;
        if (fp.y > p.position().y + ph) count++;
      });
      return count;
    });
    expect(exceeds).toBe(0);
  });

  test('R6: Console has zero errors', async ({ page }) => {
    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await search(page);
    await openL2(page);
    await tapFirstL2Edge(page);

    // Filter out expected cytoscape warnings
    const realErrors = errors.filter(e => !e.includes('Deprecation') && !e.includes('Warning'));
    expect(realErrors.length).toBe(0);
  });
});
