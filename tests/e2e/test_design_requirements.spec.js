/**
 * E2E Tests for L1L2 Display Redesign Requirements
 * Based on: L1L2_DISPLAY_REDESIGN.md v2.1, L1L2_DISPLAY_REDESIGN_REVIEW.md
 */

const { test, expect } = require('@playwright/test');
const BASE = 'http://localhost:8000';
const SAMPLE = '/home/huangyf/work/sql_visualizer/samples/multi_workflow';

test.describe('R1: Page loads', () => {
  test('title and tabs', async ({ page }) => {
    await page.goto(BASE);
    await expect(page).toHaveTitle(/GPS SQL/);
    await expect(page.getByRole('button', { name: 'Data Flow Debugger' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'SQL Analysis' })).toBeVisible();
  });
});

test.describe('R2: Upload + Index', () => {
  test('folder upload shows file tree', async ({ page }) => {
    await page.goto(BASE);
    const fp = page.waitForEvent('filechooser');
    await page.getByText('Select Folder').click();
    (await fp).setFiles([SAMPLE]);
    await page.waitForSelector('text=Indexed', { timeout: 15000 });
    await expect(page.getByText('step1_load_orders.sql')).toBeVisible();
  });
});

test.describe('R3: Search + Graph', () => {
  test('search renders L1 graph', async ({ page }) => {
    await page.goto(BASE);
    const fp = page.waitForEvent('filechooser');
    await page.getByText('Select Folder').click();
    (await fp).setFiles([SAMPLE]);
    await page.waitForSelector('text=Indexed', { timeout: 15000 });
    await page.getByRole('textbox', { name: 'Type table name...' }).fill('stg_customers');
    await page.getByRole('textbox', { name: 'Type field name...' }).fill('customer_id');
    await page.keyboard.press('Escape');
    await page.keyboard.press('Enter');
    await page.waitForSelector('text=Fit', { timeout: 10000 });
    await expect(page.getByText('Source Table')).toBeVisible();
    await expect(page.locator('.view-bar-tab')).toBeVisible();
  });
});

test.describe('R4: ViewBar', () => {
  test('ViewBar has tabs and close button', async ({ page }) => {
    await page.goto(BASE);
    const fp = page.waitForEvent('filechooser');
    await page.getByText('Select Folder').click();
    (await fp).setFiles([SAMPLE]);
    await page.waitForSelector('text=Indexed', { timeout: 15000 });
    await page.getByRole('textbox', { name: 'Type table name...' }).fill('stg_customers');
    await page.getByRole('textbox', { name: 'Type field name...' }).fill('customer_id');
    await page.keyboard.press('Escape');
    await page.keyboard.press('Enter');
    await page.waitForSelector('text=Fit', { timeout: 10000 });
    await expect(page.locator('.view-bar')).toBeVisible();
    await expect(page.locator('.view-bar-tab-close')).toBeVisible();
  });
});

test.describe('R5: Tab switching', () => {
  test('workspace survives tab switch', async ({ page }) => {
    await page.goto(BASE);
    const fp = page.waitForEvent('filechooser');
    await page.getByText('Select Folder').click();
    (await fp).setFiles([SAMPLE]);
    await page.waitForSelector('text=Indexed', { timeout: 15000 });
    await page.getByRole('button', { name: 'SQL Analysis' }).click();
    await page.waitForTimeout(500);
    await page.getByRole('button', { name: 'Data Flow Debugger' }).click();
    await page.waitForTimeout(500);
    await expect(page.getByText('step1_load_orders.sql')).toBeVisible();
  });
});

test.describe('R6: SQL Analysis legacy', () => {
  test('legend shows all edge types', async ({ page }) => {
    await page.goto(BASE);
    await page.getByRole('button', { name: 'SQL Analysis' }).click();
    await page.waitForTimeout(500);
    await expect(page.getByText('TABLE_FLOW')).toBeVisible();
    await expect(page.getByText('Multi SQL')).toBeVisible();
  });
});

test.describe('R7: No JS errors', () => {
  test('no errors after full flow', async ({ page }) => {
    const errors = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    await page.goto(BASE);
    const fp = page.waitForEvent('filechooser');
    await page.getByText('Select Folder').click();
    (await fp).setFiles([SAMPLE]);
    await page.waitForSelector('text=Indexed', { timeout: 15000 });
    await page.getByRole('textbox', { name: 'Type table name...' }).fill('stg_customers');
    await page.getByRole('textbox', { name: 'Type field name...' }).fill('customer_id');
    await page.keyboard.press('Escape');
    await page.keyboard.press('Enter');
    await page.waitForSelector('text=Fit', { timeout: 10000 });
    expect(errors).toHaveLength(0);
  });
});
