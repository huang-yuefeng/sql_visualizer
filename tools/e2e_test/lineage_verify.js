/**
 * Lineage mode verification — captures L1 and L2 screenshots
 * for stg_customers.customer_id in multi_workflow.
 *
 * Usage: node lineage_verify.js
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const SCREENSHOT_DIR = path.resolve(__dirname, 'screenshots');
const BASE_URL = 'http://192.168.0.66:8000';
const TEST_ZIP = path.resolve(__dirname, '../../samples/multi_workflow.zip');
const TABLE = 'stg_customers';
const FIELD = 'customer_id';

fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();

  try {
    // ── 1. Open app and upload workspace ──
    console.log('1. Opening app...');
    await page.goto(BASE_URL, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);

    // Click "Data Flow Debugger" tab
    const dfBtn = page.getByRole('button', { name: 'Data Flow Debugger' });
    if (await dfBtn.count() > 0) {
      await dfBtn.click();
      await page.waitForTimeout(1000);
    }

    // Upload zip
    console.log('2. Uploading workspace...');
    const fileInput = page.locator('input[type="file"][accept=".zip"]');
    if (await fileInput.count() > 0) {
      await fileInput.setInputFiles(TEST_ZIP);
      await page.waitForTimeout(8000);
    }

    // ── 2. Search for stg_customers.customer_id ──
    console.log('3. Searching...');
    const inputs = page.locator('.autocomplete-wrapper input');
    if (await inputs.count() >= 2) {
      await inputs.nth(0).fill(TABLE);
      await page.waitForTimeout(500);
      await inputs.nth(1).fill(FIELD);
      await page.waitForTimeout(500);
      await page.keyboard.press('Enter');
    } else {
      // Fallback: use the old search inputs
      await page.getByRole('textbox', { name: /table/i }).fill(TABLE);
      await page.getByRole('textbox', { name: /field/i }).fill(FIELD);
      await page.keyboard.press('Enter');
    }
    await page.waitForTimeout(4000);

    // ── 3. L1 screenshot ──
    console.log('4. Capturing L1...');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'l1_lineage_stg_customers_customer_id.png'),
      fullPage: false,
    });

    // Get L1 info
    const l1Info = await page.evaluate(() => {
      const cy = window.__cy1 || window.__cy;
      if (!cy || cy.destroyed()) return null;
      const fields = cy.nodes('[type="field"]');
      const tables = cy.nodes('[type$="_table"]');
      const scripts = cy.nodes('[type="script_node"]');
      return {
        fieldCount: fields.length,
        tableCount: tables.length,
        scriptCount: scripts.length,
        fieldLabels: fields.map(n => {
          const d = n.data();
          return `${d.table_name || ''}.${d.field_name || ''} (${d.field_group || '?'}${d.is_target ? ', TARGET' : ''})`;
        }),
        scriptLabels: scripts.map(n => n.data('label') || ''),
      };
    });
    console.log('   L1:', JSON.stringify(l1Info, null, 2));

    // ── 4. L2 screenshots for each script ──
    const scriptsToOpen = (l1Info?.scriptLabels || []);
    for (let i = 0; i < scriptsToOpen.length; i++) {
      const sname = scriptsToOpen[i];
      const shortName = sname.split('/').pop();
      console.log(`5. Opening L2 for ${shortName}...`);

      // Double-click the script node to open L2
      await page.evaluate((idx) => {
        const cy = window.__cy1 || window.__cy;
        if (!cy || cy.destroyed()) return;
        const nodes = cy.nodes('[type="script_node"]');
        if (idx < nodes.length) {
          nodes[idx].emit('dbltap');
        }
      }, i);

      await page.waitForTimeout(3000);

      // Get L2 info
      const l2Info = await page.evaluate(() => {
        const cy = window.__cy;
        if (!cy || cy.destroyed()) return null;
        const fields = cy.nodes('[type="field"]');
        const tables = cy.nodes('[type$="_table"]');
        return {
          fieldCount: fields.length,
          tableCount: tables.length,
          edgeCount: cy.edges().length,
          fieldLabels: fields.map(n => {
            const d = n.data();
            return `${d.label} parent=${d.parent || 'none'} fg=${d.field_group || '?'} target=${d.is_target || false}`;
          }),
        };
      });
      console.log('   L2:', JSON.stringify(l2Info, null, 2));

      // Screenshot L2
      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, `l2_lineage_${shortName.replace('.sql', '')}.png`),
        fullPage: false,
      });

      // Close L2
      await page.keyboard.press('Escape');
      await page.waitForTimeout(1000);
    }

    console.log('Done! Screenshots in:', SCREENSHOT_DIR);
  } catch (err) {
    console.error('Error:', err.message);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'error_state.png'),
      fullPage: true,
    });
  } finally {
    await browser.close();
  }
})();
