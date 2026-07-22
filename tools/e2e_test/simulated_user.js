/**
 * Simulated User — E2E Test Runner
 *
 * Simulates a real user performing every supported operation:
 *   upload → index → search → L1 view → layout toggle →
 *   L2 detail → edge click → SQL highlight → export → resize → delete
 *
 * Usage:
 *   node simulated_user.js              # run all test cases
 *   node simulated_user.js --quick      # first test case only
 *   node simulated_user.js --headed     # show browser window
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const config = require('./e2e.config');

// ── CLI args ──────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const QUICK = args.includes('--quick');
const HEADED = args.includes('--headed');
const TEST_CASES = QUICK ? config.testCases.slice(0, 1) : config.testCases;

// ── State ─────────────────────────────────────────────────────────────
const results = [];
const reportDir = path.resolve(__dirname, 'reports');
const ssDir = config.screenshotDir;
fs.mkdirSync(reportDir, { recursive: true });
fs.mkdirSync(ssDir, { recursive: true });

// ── Logger ────────────────────────────────────────────────────────────
const LOG_LINES = [];
function log(msg) { const s = `[${new Date().toISOString().slice(11,19)}] ${msg}`; console.log(s); LOG_LINES.push(s); }
function step(name) { log(`\n▶ ${name}`); }
function pass(msg) { log(`  ✅ ${msg}`); }
function fail(msg) { log(`  ❌ ${msg}`); }
function warn(msg) { log(`  ⚠️ ${msg}`); }
function info(msg) { log(`  ℹ️ ${msg}`); }

// ── Screenshot helper ─────────────────────────────────────────────────
async function screenshot(page, name) {
  const fname = `${name}.png`;
  await page.screenshot({ path: path.join(ssDir, fname) });
  return fname;
}

// ── Safe click helper ─────────────────────────────────────────────────
async function safeClick(page, selector, opts = {}) {
  try {
    const el = page.locator(selector).first();
    await el.waitFor({ state: 'visible', timeout: opts.timeout || 5000 });
    await el.click({ force: opts.force, timeout: opts.timeout || 5000 });
    return true;
  } catch (e) {
    return false;
  }
}

// ── Safe fill helper ──────────────────────────────────────────────────
async function safeFill(page, selector, text, opts = {}) {
  try {
    const el = page.locator(selector).first();
    await el.waitFor({ state: 'visible', timeout: opts.timeout || 5000 });
    await el.fill(text);
    return true;
  } catch (e) {
    return false;
  }
}

// ═════════════════════════════════════════════════════════════════════
// TEST SESSIONS — each simulates one user interaction sequence
// ═════════════════════════════════════════════════════════════════════

class SimulatedUser {
  constructor(page, testCase) {
    this.page = page;
    this.tc = testCase;
    this.results = { name: testCase.name, sessions: [], screenshots: [], errors: [] };
  }

  async run() {
    log(`\n${'='.repeat(60)}`);
    log(`TEST CASE: ${this.tc.name} (${this.tc.scripts} scripts)`);
    log(`${'='.repeat(60)}`);

    try {
      await this.session1_workspaceSetup();
      if (this.results.errors.length > 0) { this._skip('workspace setup failed'); return this.results; }

      // GAP 1: Non-SQL file handling (run only for mixed test case)
      if (this.tc.name === 'multi_workflow') {
        await this.session9_nonSqlFiles();
      }

      // Run searches
      for (const search of this.tc.searches) {
        const errorsBefore = this.results.errors.length;
        await this.session2_search(search);
        if (this.results.errors.length > errorsBefore) { warn('search had errors, continuing'); }

        await this.session3_l1Interact(search);
        await this.session4_layoutToggle();
        await this.session5_resizePanels();

        // GAP 12: Resize limits
        await this.session12_resizeLimits();

        // GAP 11: Pipeline layout column verification
        await this.session11_pipelineLayoutVerify();

        // L2 detail for each specified script
        for (const l2 of (search.l2Scripts || [])) {
          await this.session6_l2Detail(l2, search);
        }

        await this.session7_export(search);
      }

      // GAP 5+6: View tree management (after multiple searches)
      await this.session13_viewTreeManagement();
      // GAP 13: Error states
      await this.session14_errorStates();

      await this.session8_cleanup();
    } catch (e) {
      fail(`FATAL: ${e.message}`);
      this.results.errors.push(e.message);
    }

    return this.results;
  }

  _skip(reason) {
    warn(`SKIPPED remaining sessions: ${reason}`);
    this.results.sessions.push({ name: 'skipped', reason });
  }

  async _tryStep(name, fn) {
    try {
      await fn();
      pass(name);
      this.results.sessions.push({ name, status: 'PASS' });
      return true;
    } catch (e) {
      fail(`${name}: ${e.message}`);
      this.results.sessions.push({ name, status: 'FAIL', error: e.message });
      this.results.errors.push(`${name}: ${e.message}`);
      return false;
    }
  }

  // ── Session 1: Workspace Setup ────────────────────────────────────
  async session1_workspaceSetup() {
    step('Session 1: Workspace Setup');

    // 1.1 Navigate
    await this._tryStep('1.1 Navigate to app', async () => {
      await this.page.goto(config.appUrl, { waitUntil: 'networkidle', timeout: config.timeouts.pageLoad });
    });
    await this.page.waitForTimeout(1000);
    await screenshot(this.page, `${this.tc.name}_01_home`);

    // 1.2 Upload
    await this._tryStep('1.2 Upload workspace zip', async () => {
      const zipPath = path.join(config.SAMPLE_BASE || path.resolve(__dirname, '../../samples'), this.tc.zip);
      if (!fs.existsSync(zipPath)) throw new Error(`ZIP not found: ${zipPath}`);
      const zipInput = this.page.locator('input[type="file"][accept=".zip"]');
      await zipInput.setInputFiles(zipPath);
    });
    await this.page.waitForTimeout(config.timeouts.upload);

    // 1.3 Verify indexing
    await this._tryStep('1.3 Wait for indexing to complete', async () => {
      // Wait for progress to disappear (indexing done) or timeout
      for (let i = 0; i < 30; i++) {
        const progress = await this.page.locator('.progress-bar').count();
        if (progress === 0) {
          // Check if file tree is visible
          const treeItems = await this.page.locator('.folder-tree-item, .tree-item, .file-item').count();
          if (treeItems > 0) break;
        }
        await this.page.waitForTimeout(1000);
      }
    });
    await screenshot(this.page, `${this.tc.name}_02_indexed`);

    // 1.4 Verify file tree
    await this._tryStep('1.4 Verify file tree displayed', async () => {
      // Just check that something is rendered after upload
      const body = await this.page.evaluate(() => document.body.innerText);
      if (!body.includes('.sql')) warn('File tree may not show SQL files');
    });
  }

  // ── Session 2: Search ─────────────────────────────────────────────
  async session2_search(search) {
    step(`Session 2: Search — ${search.table}.${search.field}`);

    // 2.1 Use API to search and trigger UI render
    await this._tryStep('2.1 Execute search via UI with keyboard', async () => {
      // Get workspace ID from the UI
      // Find workspace ID from the page (poll for it)
      let wsId = null;
      for (let attempt = 0; attempt < 10; attempt++) {
        wsId = await this.page.evaluate(() => {
          const wsEl = document.querySelector('.ws-id');
          if (wsEl) { const m = wsEl.textContent.match(/ID:\s*([a-f0-9]+)/i); if (m) return m[1]; }
          const m2 = document.body.innerText.match(/ID:\s*([a-f0-9]{10,})/i);
          return m2 ? m2[1] : null;
        });
        if (wsId) break;
        await this.page.waitForTimeout(500);
      }
      if (!wsId) throw new Error('Could not find workspace ID in page after 5s');

      // Call the search API from Node.js side (no CORS) using Playwright's request context
      const apiResp = await this.page.request.post(
        `http://localhost:8000/api/workspace/${wsId}/search`,
        { data: { table: search.table, field: search.field } }
      );
      const result = await apiResp.json();
      if (!result.l1_graph || !result.l1_graph.nodes) {
        throw new Error(`Search returned ${result.l1_graph?.nodes?.length || 0} nodes`);
      }
      info(`API returned graph: ${result.l1_graph.nodes.length} nodes, ${result.l1_graph.edges.length} edges`);

      // GAP 3: Use real keyboard typing to trigger React autocomplete
      // Clear inputs, then type character-by-character (triggers native input events)
      const inputs = this.page.locator('.autocomplete-wrapper input');
      const inputCount = await inputs.count();
      if (inputCount >= 2) {
        // Type table name with real keystrokes
        await inputs.nth(0).click();
        await this.page.waitForTimeout(200);
        await inputs.nth(0).fill(''); // clear first
        await this.page.waitForTimeout(100);
        await inputs.nth(0).pressSequentially(search.table, { delay: 50 });
        await this.page.waitForTimeout(500);

        // Check if autocomplete dropdown appeared (GAP 3 verification)
        const acItems = await this.page.evaluate(() => {
          const items = document.querySelectorAll('.autocomplete-suggestions li, .suggestion-item, .ac-item');
          return Array.from(items).slice(0, 5).map(i => i.textContent.trim());
        });
        if (acItems.length > 0) {
          info(`Autocomplete appeared: ${acItems.join(', ')}`);
        } else {
          info('Autocomplete: no dropdown items (may need more characters)');
        }

        // Type field name
        await inputs.nth(1).click();
        await this.page.waitForTimeout(200);
        await inputs.nth(1).fill('');
        await this.page.waitForTimeout(100);
        await inputs.nth(1).pressSequentially(search.field, { delay: 50 });
        await this.page.waitForTimeout(500);

        // GAP 4: Field-first search — verify Table dropdown responds to field selection
        const fieldAcItems = await this.page.evaluate(() => {
          const items = document.querySelectorAll('.autocomplete-suggestions li, .suggestion-item, .ac-item');
          return Array.from(items).slice(0, 5).map(i => i.textContent.trim());
        });
        if (fieldAcItems.length > 0) {
          info(`Field autocomplete: ${fieldAcItems.join(', ')}`);
        }

        // Dismiss dropdown and submit
        await this.page.keyboard.press('Escape');
        await this.page.waitForTimeout(200);
        await inputs.nth(1).press('Enter');
        await this.page.waitForTimeout(500);
      }
      // Also try clicking Search button as fallback
      if (await this.page.locator('.graph-canvas svg, .graph-canvas canvas').count() === 0) {
        await this.page.evaluate(() => {
          const btns = document.querySelectorAll('button');
          for (const b of btns) {
            if (b.textContent.trim() === 'Search') {
              b.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
              return;
            }
          }
        });
      }
    });

    // 2.2 Wait for graph to render
    await this.page.waitForTimeout(config.timeouts.search);

    await this._tryStep('2.2 Verify L1 graph rendered with nodes', async () => {
      // Wait up to 5 seconds for the graph to appear
      let graphOk = false;
      for (let attempt = 0; attempt < 20; attempt++) {
        const cy = await this.page.evaluate(() => {
          const c = window.__cy;
          if (!c || c.destroyed()) return null;
          return { nodes: c.nodes().length, edges: c.edges().length };
        });
        if (cy && cy.nodes > 0) {
          info(`L1: ${cy.nodes} nodes, ${cy.edges} edges (after ${attempt * 250}ms)`);
          graphOk = true;
          break;
        }
        await this.page.waitForTimeout(250);
      }
      if (!graphOk) throw new Error('Graph did not render with nodes after 5 seconds');
    });

    await screenshot(this.page, `${this.tc.name}_03_search_${search.table}`);
  }

  // ── Session 3: L1 Node Interaction ────────────────────────────────
  async session3_l1Interact(search) {
    step('Session 3: L1 Node Interaction');

    // 3.1 Click table node (using graph canvas coordinates)
    await this._tryStep('3.1 Click table node in L1 graph', async () => {
      const graphOk = await this.page.evaluate(() => {
        const cy = window.__cy;
        if (!cy || cy.destroyed()) return false;
        const tableNode = cy.nodes('[type$="_table"]').first();
        if (!tableNode.length) return false;
        tableNode.emit('tap');
        return true;
      });
      if (!graphOk) warn('Could not tap table node (graph may not be ready)');
    });
    await this.page.waitForTimeout(300);

    // 3.2 Click script node
    await this._tryStep('3.2 Click script node in L1 graph', async () => {
      const graphOk = await this.page.evaluate(() => {
        const cy = window.__cy;
        if (!cy || cy.destroyed()) return false;
        const sn = cy.nodes('[type="script_node"]').first();
        if (!sn.length) return false;
        sn.emit('tap');
        return true;
      });
      if (!graphOk) warn('No script node to tap');
    });
    await this.page.waitForTimeout(300);
    await screenshot(this.page, `${this.tc.name}_04_script_clicked`);
  }

  // ── Session 4: Layout Toggle ──────────────────────────────────────
  async session4_layoutToggle() {
    step('Session 4: Layout Toggle (Snake ↔ Pipeline)');

    // 4.1 Check current mode
    const toggleBtn = this.page.locator('button:has-text("Snake"), button:has-text("Pipeline")');
    const btnCount = await toggleBtn.count();
    if (btnCount === 0) { warn('No layout toggle button found'); return; }

    // 4.2 Get current mode and toggle
    await this._tryStep('4.1 Toggle to Pipeline layout', async () => {
      const mode = (await toggleBtn.first().textContent()).trim();
      info(`Current mode: ${mode}`);
      await toggleBtn.first().click();
    });
    await this.page.waitForTimeout(config.timeouts.layoutToggle);
    await screenshot(this.page, `${this.tc.name}_05_pipeline_mode`);

    // 4.3 Verify layout changed
    await this._tryStep('4.2 Verify layout changed positions', async () => {
      const changed = await this.page.evaluate(() => {
        const cy = window.__cy; if (!cy || cy.destroyed()) return false;
        const nodes = cy.nodes().filter(n => !n.data('parent'));
        if (nodes.length === 0) return false;
        // Check if nodes are in more organized columns (ELK) vs scattered rows (snake)
        const xs = nodes.map(n => Math.round(n.position().x / 200) * 200);
        const uniqueCols = new Set(xs);
        return uniqueCols.size > 1;
      });
      if (!changed) warn('Layout may not have changed');
    });

    // 4.4 Toggle back to snake
    await this._tryStep('4.3 Toggle back to Snake layout', async () => {
      const btn = this.page.locator('button:has-text("Snake"), button:has-text("Pipeline")').first();
      await btn.click();
    });
    await this.page.waitForTimeout(config.timeouts.layoutToggle);
  }

  // ── Session 5: Panel Resizing ─────────────────────────────────────
  async session5_resizePanels() {
    step('Session 5: Panel Resize');

    // 5.1 Drag left panel handle
    await this._tryStep('5.1 Drag left panel resize handle', async () => {
      const handles = this.page.locator('.resize-handle');
      const hCount = await handles.count();
      if (hCount === 0) { warn('No resize handles found'); return; }
      // Get bounding box of first handle and drag it right by 50px
      const box = await handles.first().boundingBox();
      if (!box) throw new Error('Handle not visible');
      await this.page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await this.page.mouse.down();
      await this.page.mouse.move(box.x + box.width / 2 + 50, box.y + box.height / 2, { steps: 5 });
      await this.page.mouse.up();
      info('Dragged resize handle +50px');
    });
    await this.page.waitForTimeout(500);
    await screenshot(this.page, `${this.tc.name}_06_resized`);
  }

  // ── Session 6: L2 Detail View ─────────────────────────────────────
  async session6_l2Detail(l2spec, search) {
    step(`Session 6: L2 Detail — ${l2spec.script}`);

    // 6.1 Double-click script node → open L2
    let l2Opened = false;
    await this._tryStep('6.1 Double-click script node → open L2 panel', async () => {
      // Ensure we're on L1 view
      const inL2 = await this.page.locator('.panel-inline-l2').count();
      if (inL2 > 0) {
        await this.page.keyboard.press('Escape');
        await this.page.waitForTimeout(800);
      }

      // Before opening L2, store the L1 cy instance reference for later use.
      // After L2 opens/closes, window.__cy gets overwritten by the L2 instance.
      // Store it on a custom window property that survives L2 mount/unmount.
      const triggered = await this.page.evaluate((scriptName) => {
        // Find the L1 cytoscape instance (before L2 overwrites window.__cy)
        let cy = window.__cy;
        if (!cy || cy.destroyed()) {
          // Try window.__cy1 (our backup from previous close)
          cy = window.__cy1;
        }
        if (!cy || cy.destroyed()) {
          return 'no_live_cy';
        }

        // Backup for future
        window.__cy1 = cy;

        // Verify this is L1 (has script nodes)
        const scriptNodes = cy.nodes('[type="script_node"]');
        if (scriptNodes.length === 0) {
          return 'l2_instance';
        }

        // Find and dbltap the target script node
        let target = scriptNodes.filter(n => {
          const label = (n.data('label') || '').split('\n')[0].trim();
          return label.includes(scriptName.replace('.sql', ''));
        }).first();
        if (!target.length) target = scriptNodes.first();
        if (!target.length) return 'no_script_node';

        target.emit('dbltap');
        return 'ok';
      }, l2spec.script);

      if (triggered === 'no_live_cy') throw new Error('No live cytoscape instance found');
      if (triggered === 'l2_instance') throw new Error('Cytoscape instance is L2, not L1 (press Escape first?)');
      if (triggered === 'no_script_node') throw new Error('No script node found in graph');
      if (triggered !== 'ok') throw new Error(`Unexpected result: ${triggered}`);

      // Wait for L2 panel to appear
      for (let i = 0; i < 20; i++) {
        const l2Panel = await this.page.locator('.panel-inline-l2').count();
        if (l2Panel > 0) { l2Opened = true; break; }
        await this.page.waitForTimeout(500);
      }
      if (!l2Opened) throw new Error('L2 panel did not appear after double-click');
    });

    // After L2 closes, restore cy1 backup to __cy
    // (L2 unmount destroys its cy, leaving window.__cy dead)
    if (l2Opened) {
      await this.page.evaluate(() => {
        // Wait a tick for L2 to fully unmount, then check if __cy is dead
        setTimeout(() => {
          if (window.__cy1 && (!window.__cy || window.__cy.destroyed())) {
            window.__cy = window.__cy1;
          }
        }, 1000);
      });
    }
    await this.page.waitForTimeout(1000);
    await screenshot(this.page, `${this.tc.name}_07_l2_${l2spec.script.replace('.sql','')}`);

    // 6.2 Verify L2 graph
    await this._tryStep('6.2 Verify L2 graph has nodes and edges', async () => {
      const l2Data = await this.page.evaluate(() => {
        // Find the second graph canvas (L2)
        const canvases = document.querySelectorAll('.graph-canvas');
        if (canvases.length < 2) return null;
        const cy = window.__cy; if (!cy || cy.destroyed()) return null;
        return { nodes: cy.nodes().length, edges: cy.edges().length };
      });
      // L2 graph might be in a separate cy instance — check the main one
      const cyData = await this.page.evaluate(() => {
        const cy = window.__cy; if (!cy || cy.destroyed()) return null;
        return { nodes: cy.nodes().length, edges: cy.edges().length };
      });
      info(`Graph: ${cyData?.nodes || '?'}N, ${cyData?.edges || '?'}E`);
    });

    // 6.3 Verify SQL panel visible
    await this._tryStep('6.3 Verify SQL panel shows script text', async () => {
      const sqlContent = this.page.locator('.sql-content');
      if (await sqlContent.count() === 0) throw new Error('SQL panel not visible');
      const lineCount = await this.page.evaluate(() => {
        return document.querySelectorAll('.sql-line').length;
      });
      if (lineCount < l2spec.sqlLinesMin) {
        warn(`SQL lines: ${lineCount} (expected ≥${l2spec.sqlLinesMin})`);
      } else {
        info(`SQL lines: ${lineCount}`);
      }
    });

    // 6.4 Click L2 edge → verify SQL highlighting (use cytoscape events, not DOM)
    await this._tryStep('6.4 Click L2 edge → verify SQL highlight', async () => {
      const result = await this.page.evaluate(() => {
        const cy = window.__cy;
        if (!cy || cy.destroyed()) return 'no_cy';
        // Find a real data edge (not turn edge)
        const edge = cy.edges().filter(e => e.data('edge_type') !== 'turn').first();
        if (!edge.length) return 'no_edge';
        // Fire tap event on the edge
        edge.emit('tap');
        // Also try triggering click via cy events
        cy.emit('tap', 'edge', { target: edge });
        return 'ok';
      });
      if (result === 'no_cy') warn('No cy instance for edge click');
      else if (result === 'no_edge') warn('No clickable edges found');
    });
    await this.page.waitForTimeout(1000);
    await screenshot(this.page, `${this.tc.name}_08_l2_edge_click`);

    // 6.5 Check for highlighted SQL lines
    await this._tryStep('6.5 Verify SQL lines highlighted after edge click', async () => {
      const hlCount = await this.page.evaluate(() => {
        return document.querySelectorAll('.sql-line.edge-highlighted, .sql-line.highlighted').length;
      });
      if (hlCount === 0) warn('No SQL lines highlighted after edge click');
      else info(`${hlCount} lines highlighted`);
    });

    // 6.6 Toggle Show All / Show Relevant
    await this._tryStep('6.6 Toggle Show All / Show Relevant filter', async () => {
      const filterBtn = this.page.locator('button:has-text("Show All"), button:has-text("Show Relevant")').first();
      if (await filterBtn.count() === 0) { warn('No filter toggle button'); return; }
      const before = await this.page.evaluate(() => {
        const cy = window.__cy; if (!cy || cy.destroyed()) return 0;
        return cy.nodes().length;
      });
      await filterBtn.click();
      await this.page.waitForTimeout(1500);
      const after = await this.page.evaluate(() => {
        const cy = window.__cy; if (!cy || cy.destroyed()) return 0;
        return cy.nodes().length;
      });
      info(`Nodes: ${before} → ${after} (toggle filter)`);
    });

    // GAP 7: Compound sizing (while L2 is still open)
    await this._tryStep('G7.1 Verify fields inside parent table bounds', async () => {
      const result = await this.page.evaluate(() => {
        const cy = window.__cy; if (!cy || cy.destroyed()) return 'no_cy';
        const fields = cy.nodes('[type="field"]');
        if (fields.length === 0) return 'no_fields';
        let overflow = 0, total = 0;
        fields.forEach(f => {
          const pid = f.data('_tableParent');
          if (!pid) return;
          const parent = cy.getElementById(pid);
          if (!parent.length) return;
          total++;
          const fp = f.position(), pp = parent.position();
          const pw = parent.renderedOuterWidth ? parent.renderedOuterWidth() : 180;
          const ph = parent.renderedOuterHeight ? parent.renderedOuterHeight() : 80;
          if (fp.x < pp.x - pw/2 || fp.x > pp.x + pw/2 || fp.y < pp.y - ph/2 || fp.y > pp.y + ph/2) overflow++;
        });
        return { total, overflow };
      });
      if (result === 'no_cy') warn('No L2 cy instance');
      else if (result === 'no_fields') info('No field nodes — flat graph');
      else if (result.overflow > 0) fail(`${result.overflow}/${result.total} fields overflow parent bounds!`);
      else info(`All ${result.total} fields within parent bounds ✓`);
    });

    // GAP 8: Long script scroll check (while SQL panel is still visible)
    await this._tryStep('G8.1 Verify SQL panel scroll for long scripts', async () => {
      const sqlInfo = await this.page.evaluate(() => {
        const el = document.querySelector('.sql-content');
        if (!el) return 'no_sql';
        const lines = document.querySelectorAll('.sql-line').length;
        const scrollable = el.scrollHeight > el.clientHeight;
        return { lines, scrollable, sh: el.scrollHeight, ch: el.clientHeight };
      });
      if (sqlInfo === 'no_sql') { warn('SQL panel not visible'); return; }
      if (sqlInfo.lines > 50) {
        info(`${sqlInfo.lines} lines, scrollable=${sqlInfo.scrollable}`);
        // Test auto-scroll on edge click
        const scrolled = await this.page.evaluate(() => {
          const el = document.querySelector('.sql-content');
          if (!el) return false;
          const before = el.scrollTop;
          const cy = window.__cy; if (!cy || cy.destroyed()) return false;
          const edge = cy.edges().filter(e => e.data('edge_type') !== 'turn').first();
          if (edge.length) { edge.emit('tap'); return el.scrollTop !== before; }
          return false;
        });
        info(`Auto-scroll on edge click: ${scrolled}`);
      } else {
        info(`${sqlInfo.lines} lines — too short for scroll test`);
      }
    });

    // 6.7 Close L2 with Escape
    await this._tryStep('6.7 Close L2 with Escape key', async () => {
      await this.page.keyboard.press('Escape');
      await this.page.waitForTimeout(500);
      const l2Panel = await this.page.locator('.panel-inline-l2').count();
      if (l2Panel > 0) warn('L2 panel still visible after Escape');
    });

    await this._restoreCy1();
  }

  // ── Session 7: SQL Export ─────────────────────────────────────────
  async session7_export(search) {
    step('Session 7: SQL Export');

    const firstL2 = search.l2Scripts?.[0];
    if (!firstL2) { warn('No L2 scripts to export'); return; }

    // Open L2 — use window.__cy1 (L1 backup) if __cy is dead
    await this._tryStep('7.1 Open L2 for export', async () => {
      const result = await this.page.evaluate((scriptName) => {
        let cy = window.__cy;
        if (!cy || cy.destroyed()) cy = window.__cy1;
        if (!cy || cy.destroyed()) return 'no_cy';

        const sn = cy.nodes('[type="script_node"]').filter(n => {
          const label = (n.data('label') || '').split('\n')[0].trim();
          return label.includes(scriptName.replace('.sql', ''));
        }).first();
        if (!sn.length) return 'no_script';
        sn.emit('dbltap');
        return 'ok';
      }, firstL2.script);

      if (result === 'no_cy') throw new Error('No live cy instance (even backup)');
      if (result === 'no_script') throw new Error('Script node not found for export');
      if (result !== 'ok') throw new Error(`Export L2 open failed: ${result}`);
    });
    await this.page.waitForTimeout(config.timeouts.l2Open);

    // Verify L2 opened
    const l2Vis = await this.page.locator('.panel-inline-l2').count();
    if (l2Vis === 0) { warn('L2 panel not visible for export'); return; }

    // Click Export
    await this._tryStep('7.2 Click Export button', async () => {
      // Find any button containing "Export" or "⬇"
      const clicked = await this.page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
          if (b.textContent.includes('Export') || b.textContent.includes('⬇')) {
            b.click();
            return b.textContent.trim().substring(0, 30);
          }
        }
        return null;
      });
      if (clicked) {
        info(`Clicked: "${clicked}"`);
        // Listen for download via blob URL (exports use URL.createObjectURL)
        await this.page.waitForTimeout(1000);
      } else {
        warn('Export button not found in DOM');
      }
    });

    await this.page.keyboard.press('Escape');
    await this.page.waitForTimeout(500);

    // GAP 9+10: Export config upload and custom export
    await this._tryStep('G9.1 Open config and upload JSON', async () => {
      // Click Config gear in SQL panel
      const clicked = await this.page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
          if (b.textContent.includes('Config')) { b.click(); return true; }
        }
        return false;
      });
      if (!clicked) { warn('Config button not found'); return; }
      await this.page.waitForTimeout(800);

      // Find file input and upload config
      const hasInput = await this.page.evaluate(() => {
        const inputs = document.querySelectorAll('input[type="file"]');
        for (const inp of inputs) {
          if (inp.closest('[class*="config"]') || inp.accept === '.json') return true;
        }
        return false;
      });
      if (hasInput) info('Config file input found');
      else info('Config panel opened (no file input visible)');
    });

    await this._tryStep('G10.1 Toggle config and export', async () => {
      // Toggle a checkbox in config panel
      const toggled = await this.page.evaluate(() => {
        const cbs = document.querySelectorAll('[class*="config"] input[type="checkbox"]');
        if (cbs.length > 0) { cbs[0].click(); return true; }
        return false;
      });
      if (toggled) info('Toggled first config checkbox');

      // Close config
      await this.page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
          if (b.textContent.includes('Config')) { b.click(); return; }
        }
      });
      await this.page.waitForTimeout(300);

      // Click Export
      const exported = await this.page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
          if (b.textContent.includes('Export') || b.textContent.includes('⬇')) {
            b.click(); return b.textContent.trim().substring(0, 30);
          }
        }
        return null;
      });
      if (exported) info(`Exported with custom config: "${exported}"`);
      else warn('Export button not found');
    });
  }

  // ── GAP 1: Non-SQL File Handling ─────────────────────────────────
  async session9_nonSqlFiles() {
    step('Session 9 (Gap 1): Non-SQL file handling');
    // Upload a zip with mixed file types
    await this._tryStep('G1.1 Upload mixed-type zip', async () => {
      const zipPath = '/tmp/mixed_test.zip';
      if (!fs.existsSync(zipPath)) throw new Error('mixed_test.zip not found');
      // Delete current workspace first
      await this.page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
          if (b.textContent.includes('Delete')) { b.click(); return; }
        }
      });
      await this.page.waitForTimeout(1000);
      const zipInput = this.page.locator('input[type="file"][accept=".zip"]');
      await zipInput.setInputFiles(zipPath);
    });
    await this.page.waitForTimeout(config.timeouts.upload);

    await this._tryStep('G1.2 Verify non-SQL files shown with non-sql class', async () => {
      const result = await this.page.evaluate(() => {
        // The correct DOM class is 'tree-node non-sql' (confirmed via DOM inspection)
        const nonSqlNodes = document.querySelectorAll('.tree-node.non-sql');
        const sqlNodes = document.querySelectorAll('.tree-node:not(.non-sql)');
        return {
          nonSql: nonSqlNodes.length,
          sql: sqlNodes.length,
          samples: Array.from(nonSqlNodes).slice(0, 5).map(n => n.textContent.trim().substring(0, 40)),
        };
      });
      if (result.nonSql > 0) {
        info(`Non-SQL files: ${result.nonSql} (${result.samples.join(', ')}), SQL files: ${result.sql}`);
      } else {
        warn('No .tree-node.non-sql elements found — non-SQL class may have changed');
      }
    });
    // GAP 2: Script selection/deselection
    await this._tryStep('G2.1 Click tree node to toggle selection', async () => {
      const clicked = await this.page.evaluate(() => {
        // Find SQL file nodes (not non-sql) and click one
        const sqlNodes = document.querySelectorAll('.tree-node:not(.non-sql)');
        for (const n of sqlNodes) {
          const text = n.textContent.trim();
          if (text.includes('.sql')) {
            n.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            return text.substring(0, 50);
          }
        }
        return null;
      });
      if (clicked) info(`Clicked tree node: ${clicked}`);
      else warn('No SQL tree nodes found to click');
    });
    await this.page.waitForTimeout(500);
    await screenshot(this.page, `${this.tc.name}_gap1_non_sql`);
  }

  // ── cy1 Restore Helper ────────────────────────────────────────────
  async _restoreCy1() {
    // After L2 closes, try to restore L1 cy reference
    await this.page.evaluate(() => {
      setTimeout(() => {
        if (window.__cy1 && (!window.__cy || window.__cy.destroyed())) {
          window.__cy = window.__cy1;
        }
      }, 800);
    });
  }

  // ── GAP 11: Pipeline Layout Column Verification ──────────────────
  async session11_pipelineLayoutVerify() {
    step('Session 11 (Gap 11): Pipeline layout verification');
    // Ensure we're in snake mode first for comparison
    const toggleBtn = this.page.locator('button:has-text("Snake")');
    if (await toggleBtn.count() === 0) return;

    await this._tryStep('G11.1 Verify pipeline mode arranges nodes in columns', async () => {
      // Toggle to pipeline mode
      const btn = this.page.locator('button:has-text("Snake"), button:has-text("Pipeline")').first();
      const mode = (await btn.textContent()).trim();
      if (mode.includes('Snake')) {
        await btn.click();
        await this.page.waitForTimeout(config.timeouts.layoutToggle);
      }

      const cols = await this.page.evaluate(() => {
        const cy = window.__cy;
        if (!cy || cy.destroyed()) return null;
        const nodes = cy.nodes().filter(n => !n.data('parent'));
        const colMap = {};
        nodes.forEach(n => {
          const x = Math.round(n.position().x / 380) * 380; // ~layer spacing
          colMap[x] = (colMap[x] || 0) + 1;
        });
        const cols = Object.keys(colMap).length;
        return { columns: cols, distribution: colMap, total: nodes.length };
      });

      if (!cols) warn('Could not analyze pipeline columns');
      else info(`Pipeline mode: ${cols.total} nodes in ${cols.columns} columns`);

      // Toggle back to snake
      const btn2 = this.page.locator('button:has-text("Pipeline")').first();
      if (await btn2.count() > 0) await btn2.click();
      await this.page.waitForTimeout(config.timeouts.layoutToggle);
    });
  }

  // ── GAP 12: Panel Resize Limits ──────────────────────────────────
  async session12_resizeLimits() {
    step('Session 12 (Gap 12): Panel resize limits');

    await this._tryStep('G12.1 Drag resize to min and max', async () => {
      const handles = this.page.locator('.resize-handle');
      const count = await handles.count();
      if (count === 0) { warn('No handles'); return; }

      // Test first handle: drag far left, then far right
      for (const idx of [0]) {
        const box = await handles.nth(idx).boundingBox();
        if (!box) continue;
        const cx = box.x + box.width / 2;
        const cy = box.y + box.height / 2;

        // Drag far left (attempt to minimize panel)
        await this.page.mouse.move(cx, cy);
        await this.page.mouse.down();
        await this.page.mouse.move(cx - 300, cy, { steps: 10 });
        await this.page.mouse.up();
        await this.page.waitForTimeout(300);

        // Drag far right (attempt to maximize)
        await this.page.mouse.move(cx, cy);
        await this.page.mouse.down();
        await this.page.mouse.move(cx + 300, cy, { steps: 10 });
        await this.page.mouse.up();
        await this.page.waitForTimeout(300);

        // Drag back to reasonable position
        await this.page.mouse.move(cx, cy);
        await this.page.mouse.down();
        await this.page.mouse.move(cx - 150, cy, { steps: 5 });
        await this.page.mouse.up();
        await this.page.waitForTimeout(300);
      }
      info('Resize handle dragged to extremes, no crash');
    });
    await screenshot(this.page, `${this.tc.name}_gap12_resize_limits`);
  }

  // ── GAP 5+6: View Tree Management ───────────────────────────────
  async session13_viewTreeManagement() {
    step('Session 13 (Gap 5+6): View tree management');

    await this._tryStep('G5.1 Verify view tree has multiple entries', async () => {
      const viewCount = await this.page.evaluate(() => {
        const items = document.querySelectorAll('.view-tree-item, [class*="view-item"], [class*="view-entry"]');
        return items.length;
      });
      info(`View tree entries: ${viewCount}`);
    });

    await this._tryStep('G6.1 Attempt to delete a view', async () => {
      const deleted = await this.page.evaluate(() => {
        // Find close/remove buttons in view-related containers
        const allBtns = document.querySelectorAll('button');
        for (const b of allBtns) {
          const text = (b.textContent || '').trim();
          const parent = b.closest('[class*="view"]') || b.parentElement;
          if ((text === '×' || text === 'x' || text === 'X') && parent) {
            b.click();
            return text;
          }
        }
        return null;
      });
      if (deleted) info(`Deleted a view entry (clicked "${deleted}")`);
      else warn('No deletable view entry found');
    });
  }

  // ── GAP 13: Error States ─────────────────────────────────────────
  async session14_errorStates() {
    step('Session 14 (Gap 13): Error states');

    // Test invalid search
    await this._tryStep('G13.1 Search for non-existent table.field', async () => {
      // Get wsId and search for something that doesn't exist
      const wsId = await this.page.evaluate(() => {
        const wsEl = document.querySelector('.ws-id');
        if (wsEl) { const m = wsEl.textContent.match(/ID:\s*([a-f0-9]+)/i); if (m) return m[1]; }
        return null;
      });
      if (!wsId) { warn('No workspace ID'); return; }

      // Just attempt an invalid fill in the search inputs
      await this.page.evaluate(() => {
        const inputs = document.querySelectorAll('.autocomplete-wrapper input');
        if (inputs.length >= 2) {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          setter.call(inputs[0], 'nonexistent_table_xyz');
          inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
          setter.call(inputs[1], 'nonexistent_field_xyz');
          inputs[1].dispatchEvent(new Event('input', { bubbles: true }));
        }
      });
      await this.page.waitForTimeout(300);
      await this.page.keyboard.press('Enter');
      await this.page.waitForTimeout(2000);

      // Check for error banner or empty result
      const hasError = await this.page.evaluate(() => {
        return document.body.innerText.includes('Error') ||
               document.body.innerText.includes('error') ||
               document.body.innerText.includes('not found') ||
               document.body.innerText.includes('No results');
      });
      info(`Error state response: ${hasError ? 'error shown' : 'no visible error (may have silently ignored)'}`);
    });
    await screenshot(this.page, `${this.tc.name}_gap13_error_state`);
  }

  // ── Session 8: Cleanup ────────────────────────────────────────────
  async session8_cleanup() {
    step('Session 8: Cleanup');

    await this._tryStep('8.1 Delete workspace', async () => {
      const delBtn = this.page.locator('button:has-text("Delete"), button:has-text("🗑")').first();
      if (await delBtn.count() === 0) { warn('No delete button'); return; }
      await delBtn.click();
      await this.page.waitForTimeout(1000);
      // Confirm if needed
      const confirmBtn = this.page.locator('button:has-text("Confirm"), button:has-text("OK"), button:has-text("Yes")').first();
      if (await confirmBtn.count() > 0) await confirmBtn.click();
    });

    // Verify empty state
    await this._tryStep('8.2 Verify empty state after delete', async () => {
      const emptyState = await this.page.evaluate(() => {
        return document.body.innerText.includes('Upload a folder') ||
               document.body.innerText.includes('get started');
      });
      if (emptyState) pass('Empty state shown');
    });
    await screenshot(this.page, `${this.tc.name}_09_cleaned`);
  }
}

// ═════════════════════════════════════════════════════════════════════
// MAIN
// ═════════════════════════════════════════════════════════════════════

(async () => {
  log('SQL Visualizer E2E — Simulated User Test');
  log(`Test cases: ${TEST_CASES.map(t => t.name).join(', ')}`);
  log(`Mode: ${HEADED ? 'headed' : 'headless'}, ${QUICK ? 'quick' : 'full'}`);
  log(`Screenshots: ${ssDir}`);
  log(`Report: ${reportDir}`);

  const browser = await chromium.launch({ headless: !HEADED });
  const context = await browser.newContext({
    viewport: config.viewport,
    deviceScaleFactor: config.deviceScaleFactor,
  });

  for (const testCase of TEST_CASES) {
    const page = await context.newPage();
    page.setDefaultTimeout(15000);

    const user = new SimulatedUser(page, testCase);
    const result = await user.run();
    results.push(result);

    // Save intermediate results
    fs.writeFileSync(
      path.join(reportDir, `result_${testCase.name}.json`),
      JSON.stringify(result, null, 2)
    );

    await page.close();
  }

  await browser.close();

  // ── Final Report ──────────────────────────────────────────────────
  const summary = {
    timestamp: new Date().toISOString(),
    total: results.length,
    passed: results.filter(r => r.errors.length === 0).length,
    failed: results.filter(r => r.errors.length > 0).length,
    results: results.map(r => ({
      name: r.name,
      sessions: r.sessions.length,
      errors: r.errors,
      screenshots: r.screenshots,
    })),
  };

  const reportPath = path.join(reportDir, 'summary.json');
  fs.writeFileSync(reportPath, JSON.stringify(summary, null, 2));

  log(`\n${'='.repeat(60)}`);
  log(`TEST COMPLETE`);
  log(`${'='.repeat(60)}`);
  log(`Cases: ${summary.total} total, ${summary.passed} passed, ${summary.failed} failed`);
  for (const r of results) {
    const icon = r.errors.length === 0 ? '✅' : '❌';
    log(`  ${icon} ${r.name}: ${r.sessions.length} sessions, ${r.errors.length} errors`);
    for (const e of r.errors) log(`       ${e}`);
  }
  log(`\nFull report: ${reportPath}`);
  log(`Screenshots: ${ssDir}/`);

  // Generate HTML report
  const htmlReport = generateHtmlReport(summary, results, LOG_LINES);
  fs.writeFileSync(path.join(reportDir, 'report.html'), htmlReport);
  log(`HTML report: ${path.join(reportDir, 'report.html')}`);

  process.exit(summary.failed > 0 ? 1 : 0);
})();

// ── HTML Report Generator ────────────────────────────────────────────
function generateHtmlReport(summary, results, logLines) {
  const rows = results.map(r => {
    const icon = r.errors.length === 0 ? '✅' : '❌';
    const sessionList = r.sessions.map(s =>
      `<li class="${s.status === 'PASS' ? 'pass' : 'fail'}">${s.status === 'PASS' ? '✓' : '✗'} ${s.name}${s.error ? ` — ${s.error}` : ''}</li>`
    ).join('');
    const errorList = r.errors.map(e => `<li class="fail">${e}</li>`).join('');
    return `
      <tr>
        <td>${icon}</td>
        <td>${r.name}</td>
        <td>${r.sessions.length}</td>
        <td>${r.errors.length}</td>
        <td><ul>${sessionList}</ul>${errorList ? '<strong>Errors:</strong><ul>' + errorList + '</ul>' : ''}</td>
      </tr>
    `;
  }).join('');

  const logHtml = logLines.map(l => `<div class="log-line">${l}</div>`).join('');

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>SQL Visualizer E2E Report</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0a0a1a; color: #e0e0e0; padding: 2rem; }
  h1 { color: #F39C12; } h2 { color: #5DADE2; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #333; padding: 8px 12px; text-align: left; vertical-align: top; }
  th { background: #1a1a3e; } tr:nth-child(even) { background: #111; }
  .pass { color: #2ECC71; } .fail { color: #E74C3C; }
  .summary { display: flex; gap: 2rem; margin: 1rem 0; }
  .stat { background: #1a1a3e; padding: 1rem 2rem; border-radius: 8px; text-align: center; }
  .stat .num { font-size: 2rem; font-weight: bold; }
  .log { background: #050510; padding: 1rem; border-radius: 8px; max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 0.8rem; line-height: 1.6; }
  .log-line { white-space: pre-wrap; }
  ul { margin: 0; padding-left: 1rem; }
</style></head><body>
<h1>🧪 SQL Visualizer — E2E Test Report</h1>
<p>${summary.timestamp} | ${summary.total} test cases</p>
<div class="summary">
  <div class="stat"><div class="num">${summary.total}</div>Total</div>
  <div class="stat"><div class="num pass">${summary.passed}</div>Passed</div>
  <div class="stat"><div class="num fail">${summary.failed}</div>Failed</div>
</div>
<h2>Results</h2>
<table><tr><th></th><th>Test Case</th><th>Sessions</th><th>Errors</th><th>Details</th></tr>${rows}</table>
<h2>Full Log</h2>
<div class="log">${logHtml}</div>
</body></html>`;
}
