// @ts-check
const { test, expect } = require('@playwright/test');

const BASE = 'http://localhost:8000';
const TEST_ZIP = '/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip';

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
    // Search for crm_customers.customer_id
    await page.getByRole('textbox', { name: 'Type table name...' }).fill('crm_customers');
    await page.getByRole('textbox', { name: 'Type field name...' }).fill('customer_id');
    await page.getByRole('textbox', { name: 'Type field name...' }).press('Enter');
    await page.waitForTimeout(2000);
    
    // L1 graph should appear with Cross-Script Pipeline badge
    await expect(page.getByText('Cross-Script Pipeline')).toBeVisible();
    // Should find 5 script nodes
    const scriptNodes = await page.evaluate(() => {
      const cy = window.__cy;
      return cy ? cy.nodes('[type="script_node"]').length : 0;
    });
    expect(scriptNodes).toBe(5);
  });

  test('R3: Double-click script opens L2 with edges', async ({ page }) => {
    // First search
    await page.getByRole('textbox', { name: 'Type table name...' }).fill('crm_customers');
    await page.getByRole('textbox', { name: 'Type field name...' }).fill('customer_id');
    await page.getByRole('textbox', { name: 'Type field name...' }).press('Enter');
    await page.waitForTimeout(2000);
    
    // Double-click 3rd script node (step3 has joins)
    await page.evaluate(() => {
      const cy = window.__cy;
      if (cy) cy.nodes('[type="script_node"]').eq(2).emit('dbltap');
    });
    await page.waitForTimeout(2000);
    
    // L2 panel should appear
    await expect(page.getByText('Level 2 Detail')).toBeVisible();
    
    // Should have edges
    const edgeCount = await page.evaluate(() => {
      const cy = window.__cy;
      return cy ? cy.edges().length : 0;
    });
    expect(edgeCount).toBeGreaterThan(0);
  });

  test('R4: Edge click highlights SQL', async ({ page }) => {
    // Search and open L2 as above
    await page.getByRole('textbox', { name: 'Type table name...' }).fill('crm_customers');
    await page.getByRole('textbox', { name: 'Type field name...' }).fill('customer_id');
    await page.getByRole('textbox', { name: 'Type field name...' }).press('Enter');
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
      const cy = window.__cy;
      if (cy) cy.nodes('[type="script_node"]').eq(2).emit('dbltap');
    });
    await page.waitForTimeout(2000);
    
    // Click first edge
    await page.evaluate(() => {
      const cy = window.__cy;
      if (cy && cy.edges().length > 0) cy.edges()[0].emit('tap');
    });
    await page.waitForTimeout(500);
    
    // Verify SQL highlight appears
    const highlighted = await page.evaluate(() =>
      document.querySelectorAll('.sql-line.edge-highlighted').length
    );
    expect(highlighted).toBeGreaterThan(0);
  });

  test('R5: No field nodes exceed table bounds', async ({ page }) => {
    await page.getByRole('textbox', { name: 'Type table name...' }).fill('crm_customers');
    await page.getByRole('textbox', { name: 'Type field name...' }).fill('customer_id');
    await page.getByRole('textbox', { name: 'Type field name...' }).press('Enter');
    await page.waitForTimeout(2000);
    
    const exceeds = await page.evaluate(() => {
      const cy = window.__cy;
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
    
    await page.getByRole('textbox', { name: 'Type table name...' }).fill('crm_customers');
    await page.getByRole('textbox', { name: 'Type field name...' }).fill('customer_id');
    await page.getByRole('textbox', { name: 'Type field name...' }).press('Enter');
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
      const cy = window.__cy;
      if (cy) cy.nodes('[type="script_node"]').eq(2).emit('dbltap');
    });
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
      const cy = window.__cy;
      if (cy && cy.edges().length > 0) cy.edges()[0].emit('tap');
    });
    await page.waitForTimeout(500);
    
    // Filter out expected cytoscape warnings
    const realErrors = errors.filter(e => !e.includes('Deprecation') && !e.includes('Warning'));
    expect(realErrors.length).toBe(0);
  });
});
