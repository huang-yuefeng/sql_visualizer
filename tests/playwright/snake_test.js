const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  const log = (msg) => console.log(msg);

  // Use API to set up workspace (faster, avoids autocomplete issues)
  const apiBase = 'http://localhost:8000/api';

  // Step 1: Upload via API
  const zipData = fs.readFileSync('/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip');
  const uploadResp = await page.request.post(`${apiBase}/workspace`, {
    multipart: { file: { name: 'multi_workflow.zip', mimeType: 'application/zip', buffer: zipData } }
  });
  const { workspace_id } = await uploadResp.json();
  log(`Workspace: ${workspace_id}`);

  // Step 2: Index
  const scripts = ['step1_load_orders.sql','step2_enrich_customers.sql','step3_join_orders_customers.sql','step4_aggregate_daily.sql','step5_final_report.sql'];
  await page.request.post(`${apiBase}/workspace/${workspace_id}/index`, { data: { script_paths: scripts } });
  log('Indexed');

  // Step 3: Search
  const searchResp = await page.request.post(`${apiBase}/workspace/${workspace_id}/search`, {
    data: { table: 'analytics_orders', field: 'amount' }
  });
  const { view_id } = await searchResp.json();
  log(`View: ${view_id}`);

  // Step 4: Navigate to app and inject graph data
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  // Upload the workspace in the UI
  const zipInput = page.locator('input[type="file"][accept=".zip"]');
  await zipInput.setInputFiles('/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip');
  log('UI: uploaded');
  await page.waitForTimeout(5000);

  // Search in UI — use Escape to dismiss autocomplete first
  const autoInputs = page.locator('.autocomplete-wrapper input');
  const acCount = await autoInputs.count();
  log(`UI: ${acCount} autocomplete inputs`);

  if (acCount >= 2) {
    await autoInputs.nth(0).fill('analytics_orders');
    await page.waitForTimeout(500);
    // Press Escape to close dropdown
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    await autoInputs.nth(1).fill('amount');
    await page.waitForTimeout(500);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    // Click search button with force to bypass overlay
    const searchBtn = page.locator('button.btn-primary:has-text("Search")');
    await searchBtn.click({ force: true, timeout: 5000 }).catch(() => {
      log('Force click Search failed, trying keyboard');
    });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(4000);
  }

  await page.screenshot({ path: '/tmp/snake_02_l1_snake.png' });
  log('Screenshot: 02_l1_snake');

  // ---- Analysis ----
  const graphData = await page.evaluate(() => {
    const cy = window.__cy;
    if (!cy || cy.destroyed()) return { error: 'No cy instance' };

    const getNodes = () => {
      const nodes = cy.nodes().filter(n => !n.data('parent'));
      return nodes.map(n => {
        const p = n.position();
        return {
          id: n.id().substring(0, 28),
          type: n.data('type') || '?',
          label: (n.data('label')||'').replace(/\n.*/g,' ').substring(0,36),
          x: Math.round(p.x), y: Math.round(p.y),
          w: n.renderedOuterWidth ? Math.round(n.renderedOuterWidth()) : '?',
          h: n.renderedOuterHeight ? Math.round(n.renderedOuterHeight()) : '?',
        };
      });
    };
    const getEdges = () => cy.edges().map(e => ({
      id: e.id().substring(0, 28),
      type: e.data('edge_type') || '?',
      curve: e.style('curve-style'),
      srcL: (e.data('label')||'').substring(0, 30),
      sx: Math.round(e.source().position().x),
      sy: Math.round(e.source().position().y),
      tx: Math.round(e.target().position().x),
      ty: Math.round(e.target().position().y),
    }));

    return { nodes: getNodes(), edges: getEdges(), zoom: cy.zoom() };
  });

  if (graphData.nodes) {
    log(`\n=== NODES (${graphData.nodes.length}) ===`);
    // Group by Y-position rows
    const rows = {};
    graphData.nodes.forEach(n => {
      const r = Math.round(n.y / 280);
      if (!rows[r]) rows[r] = [];
      rows[r].push(n);
    });
    Object.entries(rows).sort((a,b)=>a[0]-b[0]).forEach(([r,ns]) => {
      // Sort by x within row
      ns.sort((a,b) => a.x - b.x);
      log(`Row ${r} (y≈${ns[0].y}):`);
      ns.forEach(n => {
        log(`  x=${n.x} ${n.type.padEnd(20)} ${n.w}x${n.h}  ${n.label}`);
      });
    });

    log(`\n=== EDGES (${graphData.edges.length}) ===`);
    const byType = {};
    graphData.edges.forEach(e => {
      byType[e.type] = (byType[e.type]||0) + 1;
      log(`  ${e.type.padEnd(22)} [${e.curve}]  (${e.sx},${e.sy})→(${e.tx},${e.ty})  ${e.srcL}`);
    });
    log(`\nEdge type counts: ${JSON.stringify(byType)}`);

    // DEFECT ANALYSIS
    log(`\n=== DEFECT ANALYSIS ===`);

    // D1: Snake reversal
    let snakeReversals = 0;
    Object.entries(rows).forEach(([r, ns]) => {
      ns.sort((a,b) => a.x - b.x);
      if (ns.length >= 2) {
        // Check if this row's x-order is reversed from previous row
        const prevRow = rows[parseInt(r)-1];
        if (prevRow) {
          prevRow.sort((a,b) => a.x - b.x);
          const prevLeft = prevRow[0].x;
          const prevRight = prevRow[prevRow.length-1].x;
          const curLeft = ns[0].x;
          const curRight = ns[ns.length-1].x;
          // If previous row's leftmost node is to the left of current row's leftmost,
          // that's normal (left-to-right). Reverse = alternating direction.
          if (Math.abs(curLeft - prevRight) < Math.abs(curLeft - prevLeft)) {
            snakeReversals++;
          }
        }
      }
    });
    log(`Snake reversal rows detected: ${snakeReversals}`);

    // D2: Table/script separation
    const tableRows = new Set();
    const scriptRows = new Set();
    Object.entries(rows).forEach(([r, ns]) => {
      const hasTable = ns.some(n => n.type.endsWith('_table'));
      const hasScript = ns.some(n => n.type === 'script_node');
      if (hasTable && !hasScript) tableRows.add(parseInt(r));
      if (hasScript && !hasTable) scriptRows.add(parseInt(r));
    });
    log(`Pure table rows: ${[...tableRows].join(',')}  Pure script rows: ${[...scriptRows].join(',')}`);

    // D3: Turn edges
    const turnEdges = graphData.edges.filter(e => e.type === 'turn');
    log(`Artificial turn edges: ${turnEdges.length}`);

    // D4: Edge overlap potential
    const overlapping = [];
    for (let i = 0; i < graphData.edges.length; i++) {
      for (let j = i+1; j < graphData.edges.length; j++) {
        const a = graphData.edges[i], b = graphData.edges[j];
        if (a.sx === b.sx && a.sy === b.sy && a.tx === b.tx && a.ty === b.ty) {
          overlapping.push(`${a.id} & ${b.id}`);
        }
      }
    }
    log(`Duplicate source→target edges: ${overlapping.length}`);
  }

  // Check layout toggle
  const toggleBtn = page.locator('button:has-text("Snake"), button:has-text("Pipeline")');
  if (await toggleBtn.count() > 0) {
    const mode = await toggleBtn.first().textContent();
    log(`\nLayout mode: "${mode.trim()}"`);

    // Toggle to pipeline
    await toggleBtn.first().click();
    await page.waitForTimeout(3000);
    await page.screenshot({ path: '/tmp/snake_03_l1_pipeline.png' });
    log('Screenshot: 03_l1_pipeline');

    const pipeData = await page.evaluate(() => {
      const cy = window.__cy;
      if (!cy || cy.destroyed()) return [];
      return cy.nodes().filter(n => !n.data('parent')).map(n => ({
        x: Math.round(n.position().x), y: Math.round(n.position().y),
        type: n.data('type')||'?', label: (n.data('label')||'').replace(/\n.*/g,' ').substring(0,30),
      })).sort((a,b)=>a.x-b.x || a.y-b.y);
    });
    log('Pipeline positions (by column):');
    // Group by layer/x column
    const cols = {};
    pipeData.forEach(n => {
      const c = Math.round(n.x / 380);
      if (!cols[c]) cols[c] = [];
      cols[c].push(n);
    });
    Object.entries(cols).sort((a,b)=>a[0]-b[0]).forEach(([c,ns]) => {
      log(`  Col ${c} (x≈${ns[0].x}): ${ns.map(n=>n.type+':'+n.label).join(' | ')}`);
    });
  }

  fs.writeFileSync('/tmp/snake_analysis.json', JSON.stringify(graphData, null, 2));
  await browser.close();
  log('\nDone');
})();
