// @ts-check
const path = require('path');
const { test, expect } = require('@playwright/test');

const BASE = 'http://localhost:8000';
// Resolve the fixture relative to this file (tests/playwright/) instead of
// hardcoding one developer's absolute checkout path.
const TEST_ZIP = path.resolve(__dirname, '../../samples/multi_workflow.zip');

// R31: the login gate is ON in production (start.py sets REQUIRE_LOGIN=1) —
// gated /api/* calls 401 without a session, and the login FORM renders in the
// Data Flow Debugger's left panel (#293; there is no full-page gate).
// Accounts are provisioned from CONFIG (PROVISIONED_USERS) at startup only —
// the gate-exempt POST /api/admin/users bootstrap is REMOVED (R31 #269). The
// login below uses the config default admin account (admin@hsbc.com / 123456).
const ADMIN_USER = 'admin@hsbc.com';
const ADMIN_PW = '123456';

// R29 made upstream (writing flow) the default search direction. crm_customers
// is a SOURCE table — it has no writing flow, so querying it yields an empty
// no_flow view. Every test searches an OUTPUT field (stg_customers.region),
// whose upstream flow runs crm_customers.region → step2 → stg_customers.region
// and produces a real L1 with script nodes.
const SEARCH_TBL = 'stg_customers';
const SEARCH_FIELD = 'region';

// E2E coverage note: this spec exercises only the debugger happy-path. The
// login gate, workspace quota (MAX_WORKSPACES_PER_USER), creator-only 403s,
// and the heavy-op gate have UNIT coverage only (backend/tests/test_r31_gate.py,
// backend/tests/test_r31_auth.py) — no browser E2E for them. The in-app
// notification subsystem is REMOVED (#322), so it needs no coverage here.

// ── Cytoscape instance access ──────────────────────────────────────
// window.__cy / __cy1 are DEV-only (v3.3.149) and never exist in a production
// build, so there is no app-provided global to read. Cytoscape registers the
// live instance on its own container element as `el._cyreg.cy` in every build.
// `_cyreg` is an internal Cytoscape handle, not a stable public API, but it is
// the only DOM→instance path available without an app change (and re-exposing a
// production global is exactly what v3.3.149 removed). That coupling is kept in
// ONE place (cyEval below) so a future stable accessor only needs to change
// here. Each DataFlowGraph renders `.dataflow-graph-container[data-level="L1"|"L2"]`
// with the `.graph-canvas` inside it, so the right instance is selected by level.
//
// cyEval builds a self-contained page expression: `level` and `tail` are
// interpolated into the source at build time, so nothing (level, tail, or a
// function) is passed across the evaluate boundary — this Playwright build
// cannot serialize plain function arguments.
function cyEval(page, level, tail) {
  const expr = `
    (() => {
      const el = document.querySelector('.dataflow-graph-container[data-level="${level}"] .graph-canvas');
      const cy = el && el._cyreg && el._cyreg.cy;
      if (!cy) return null;
      ${tail}
    })()
  `;
  return page.evaluate(expr);
}

async function search(page) {
  await page.getByRole('textbox', { name: 'Type table name...' }).fill(SEARCH_TBL);
  await page.getByRole('textbox', { name: 'Type field name...' }).fill(SEARCH_FIELD);
  await page.getByRole('textbox', { name: 'Type field name...' }).press('Enter');
  await page.waitForSelector('.dataflow-graph-container[data-level="L1"]');
  await page.waitForTimeout(2000);
}

async function openL2(page) {
  await cyEval(page, 'L1', `
    const firstScript = cy.nodes('[type="script_node"]').eq(0);
    if (firstScript.length) firstScript.emit('dbltap');
  `);
  await page.waitForSelector('.dataflow-graph-container[data-level="L2"]');
  await page.waitForTimeout(2000);
}

async function tapFirstL2Edge(page) {
  await cyEval(page, 'L2', `
    if (cy.edges().length > 0) cy.edges()[0].emit('tap');
  `);
  await page.waitForTimeout(500);
}

// R31: log in through the login form (the Data Flow Debugger's left panel
// post-#293). The username input has the "you@hsbc.com" placeholder; the
// password is the only input[type=password].
async function login(page) {
  await page.waitForSelector('form'); // the login form
  await page.getByPlaceholder('you@hsbc.com').fill(ADMIN_USER);
  await page.locator('input[type="password"]').fill(ADMIN_PW);
  await page.getByRole('button', { name: 'Sign in' }).click();
  // Post-login landing page = the "My workspaces" dashboard
  await page.getByText('My workspaces').waitFor();
}

// Repeatable E2E: every run uploads a NEW workspace, and without a clean slate
// the quota (MAX_WORKSPACES_PER_USER = 10) fills up after two full runs. These
// workspaces are E2E-created only, so physically deleting them (creator role,
// A-M2) is safe. page.request shares the page's session cookie.
async function cleanWorkspaces(page) {
  const res = await page.request.get(`${BASE}/api/workspaces`);
  if (!res.ok()) return;
  const body = await res.json();
  for (const w of body.workspaces || []) {
    await page.request.delete(`${BASE}/api/me/workspaces/${w.ws_id}`);
  }
}

test.describe('SQL Data Flow Debugger', () => {
  // R6: console errors are collected across the WHOLE flow. The listener is
  // attached in beforeEach BEFORE page.goto so no action (login, upload,
  // index, search, L2, edge tap) is ever observed without it.
  let consoleErrors;

  test.beforeEach(async ({ page }) => {
    consoleErrors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    await page.goto(BASE);
    await login(page);
    // Remove workspaces left by previous runs so uploads never hit the quota.
    await cleanWorkspaces(page);
    // Upload from the dashboard ("+ Upload a folder (zip)")
    await page.setInputFiles('input[type="file"][accept=".zip"]', TEST_ZIP);
    // Wait for the debugger to open the new workspace + index
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
    // R29 (upstream = writing flow): the directional L1 for stg_customers.region
    // carries exactly the producing script (step2) — step1/3/4/5 do not produce
    // this field. The script-node label is the full zip-relative path.
    const scriptLabels = await cyEval(page, 'L1', `
      return cy.nodes('[type="script_node"]').map(n => n.data('label'));
    `);
    expect(scriptLabels).toEqual(['multi_workflow/step2_enrich_customers.sql']);
  });

  test('R3: Double-click script opens L2 with edges', async ({ page }) => {
    await search(page);
    await openL2(page);

    // L2 panel should appear
    await expect(page.getByText('Level 2 Detail')).toBeVisible();
    await expect(page.getByText('Per-Script Detail')).toBeVisible();

    // Should have edges
    const edgeCount = await cyEval(page, 'L2', `return cy.edges().length;`);
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

    const exceeds = await cyEval(page, 'L2', `
      let count = 0;
      cy.nodes('[type="field"]').forEach(f => {
        const fp = f.position();
        const pid = f.data('_tableParent');
        if (!pid) return;
        const p = cy.getElementById(pid);
        if (!p.length) return;
        const ph = p.data('_tableHeight') || 80;
        const top = p.position().y;
        if (fp.y > top + ph) count++; // bottom overflow (field below table)
        if (fp.y < top) count++;      // top overflow (field above table top)
      });
      return count;
    `);
    expect(exceeds).toBe(0);
  });

  test('R6: Console has zero errors', async () => {
    // consoleErrors is populated from beforeEach (listener attached before
    // page.goto). Filter out expected cytoscape warnings.
    const realErrors = consoleErrors.filter(
      e => !e.includes('Deprecation') && !e.includes('Warning')
    );
    expect(realErrors.length).toBe(0);
  });
});
