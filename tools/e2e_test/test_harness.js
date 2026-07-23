/**
 * Standardized E2E Test Harness — reusable setup for all Playwright tests.
 *
 * Usage:
 *   const { page, scriptIds, cleanup } = await setupTest(browser, {
 *     zipPath: "/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip",
 *     table: "analytics_orders", field: "amount"
 *   });
 *   // ... run your test ...
 *   await cleanup();
 */

/**
 * Convert model coordinates to screen/viewport coordinates.
 * Fixes the coordinate system mismatch that caused false positives.
 */
function screenPos(cy, modelX, modelY) {
  const zoom = cy.zoom();
  const pan = cy.pan();
  const vpW = cy.container()?.offsetWidth || 1440;
  const vpH = cy.container()?.offsetHeight || 900;
  return {
    x: (modelX - pan.x) * zoom + vpW / 2,
    y: (modelY - pan.y) * zoom + vpH / 2,
  };
}

/**
 * Check if an element is visible in the viewport (screen coordinates).
 */
function isInViewport(cy, modelX, modelY, margin = 0) {
  const s = screenPos(cy, modelX, modelY);
  const vpW = cy.container()?.offsetWidth || 1440;
  const vpH = cy.container()?.offsetHeight || 900;
  return s.x > margin && s.x < vpW - margin && s.y > margin && s.y < vpH - margin;
}

/**
 * Get a position hash for comparing layouts.
 */
function layoutHash(cy) {
  if (!cy || cy.destroyed()) return 0;
  let h = 0;
  cy.nodes().filter(n => n.data('type') !== 'field').forEach(n => {
    const p = n.position();
    h += Math.round(p.x) + Math.round(p.y) * 1000;
  });
  return h;
}

/**
 * Count overlapping table bounding boxes.
 */
function countTableOverlaps(cy) {
  if (!cy || cy.destroyed()) return 0;
  const tables = cy.nodes('[type$="_table"]');
  let overlap = 0;
  tables.forEach(a => { tables.forEach(b => {
    if (a.id() >= b.id()) return;
    const ba = a.renderedBoundingBox(), bb = b.renderedBoundingBox();
    if (!ba || !bb) return;
    if (Math.max(0, Math.min(ba.x2, bb.x2) - Math.max(ba.x1, bb.x1)) > 5 &&
        Math.max(0, Math.min(ba.y2, bb.y2) - Math.max(ba.y1, bb.y1)) > 5) overlap++;
  });});
  return overlap;
}

/**
 * Main setup function. Returns everything needed for testing.
 */
async function setupTest(browser, opts = {}) {
  const {
    zipPath = "/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip",
    table = "analytics_orders",
    field = "amount",
    baseUrl = "http://127.0.0.1:8000",
  } = opts;

  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForTimeout(2000);

  // Upload workspace
  const zipInput = page.locator('input[type="file"][accept=".zip"]');
  await zipInput.setInputFiles(zipPath);
  await page.waitForTimeout(8000);

  // Search
  const inputs = page.locator(".autocomplete-wrapper input");
  await inputs.nth(0).pressSequentially(table, { delay: 30 });
  await page.waitForTimeout(500);
  await inputs.nth(1).pressSequentially(field, { delay: 30 });
  await page.waitForTimeout(500);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  await page.evaluate(() => {
    const btns = document.querySelectorAll("button");
    for (const b of btns) if (b.textContent.trim() === "Search") { b.click(); return; }
  });
  await page.waitForTimeout(4000);

  // Get L1 graph info
  const graphInfo = await page.evaluate(() => {
    const cy = window.__cy1 || window.__cy;
    if (!cy || cy.destroyed()) return null;
    return {
      scriptIds: cy.nodes('[type="script_node"]').map(n => n.id()),
      scriptLabels: cy.nodes('[type="script_node"]').map(n =>
        (n.data('label') || '').substring(0, 40)),
      edgeCount: cy.edges().length,
      nodeCount: cy.nodes().filter(n => !n.data('parent')).length,
    };
  });

  // Open L2 for a script
  const openL2 = async (scriptIndex = 0) => {
    const ids = await page.evaluate(() => {
      const cy = window.__cy1 || window.__cy;
      if (!cy || cy.destroyed()) return [];
      return cy.nodes('[type="script_node"]').map(n => n.id());
    });
    if (scriptIndex >= ids.length) return false;
    await page.evaluate((nid) => {
      const cy = window.__cy1 || window.__cy;
      if (!cy || cy.destroyed()) return;
      const n = cy.getElementById(nid);
      if (n.length) n.emit('dbltap');
    }, ids[scriptIndex]);
    await page.waitForTimeout(2500);
    return true;
  };

  const closeL2 = async () => {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(1000);
  };

  // Click an edge in L2 by index
  const clickEdge = async (index = 0) => {
    await page.evaluate((idx) => {
      const cy = window.__cy;
      if (!cy || cy.destroyed()) return;
      const edges = cy.edges();
      if (idx < edges.length) edges[idx].emit('tap');
    }, index);
    await page.waitForTimeout(300);
  };

  // Get highlighted SQL lines
  const getHighlightedLines = async () => {
    return page.evaluate(() => {
      const lines = [];
      document.querySelectorAll('.sql-line.edge-highlighted').forEach(l =>
        lines.push(parseInt(l.getAttribute('data-line')))
      );
      return lines;
    });
  };

  // Get all L2 edge ranges
  const getL2EdgeRanges = async () => {
    return page.evaluate(() => {
      const cy = window.__cy;
      if (!cy || cy.destroyed()) return [];
      return cy.edges().map(e => {
        const sr = e.data().sql_range;
        return {
          type: e.data().edge_type || '?',
          range: sr ? `${sr[0]}-${sr[2]}` : 'NONE',
        };
      });
    });
  };

  // Switch layout mode
  const switchLayout = async (mode) => {
    const btn = page.locator(`button:has-text("${mode}")`);
    if (await btn.count() > 0) {
      await btn.first().click();
      await page.waitForTimeout(2500);
    }
  };

  const cleanup = async () => {
    await page.close();
  };

  return {
    page,
    graphInfo,
    openL2, closeL2, clickEdge,
    getHighlightedLines, getL2EdgeRanges,
    switchLayout,
    cleanup,
    // Utility functions exposed for page.evaluate use
    utils: { screenPos, isInViewport, layoutHash, countTableOverlaps },
  };
}

module.exports = { setupTest, screenPos, isInViewport, layoutHash, countTableOverlaps };
