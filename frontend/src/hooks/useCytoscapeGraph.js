/**
 * Cytoscape Graph Hook — thin orchestrator.
 *
 * Responsibilities:
 *   - Create/destroy Cytoscape instance
 *   - Apply styles from graphStyles.js
 *   - Strip field parents before Cytoscape sees them (via layoutCore)
 *   - Delegate layout to snakeLayout.js or elkLayout.js
 *   - Expose fit() and relayout() callbacks
 *
 * Layout logic lives in:
 *   - layoutCore.js    — shared: field rel pos, table info, applyLayout
 *   - snakeLayout.js   — snake algorithm: computeSnakePositions + runSnakeLayout
 *   - elkLayout.js     — ELK algorithm: applyElkLayout
 */
import { useEffect, useRef, useCallback } from 'react';
import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';
cytoscape.use(fcose);
import { NODE_STYLES, COMPOUND_STYLES, L1_PIPELINE_EDGE_STYLES, TURN_EDGE_STYLES,
  BUNDLED_EDGE_STYLES, CATEGORY_EDGE_STYLES, SCRIPT_CARD_STYLES,
  OPERATION_NODE_STYLES, L2_DETAIL_STYLES } from '../utils/graphStyles';
import { stripFieldParents, computeFieldRelPos, positionTableFields } from '../utils/layoutCore';
import { TABLE_SELECTOR } from '../config/layout';
import { runSnakeLayout } from '../utils/snakeLayout';

const TABLE_SEL = TABLE_SELECTOR;

// ── Pipeline layout (lazy-import ELK) ──────────────────────────────
async function pipelineLayout(cy, opts = {}) {
  if (!cy || cy.destroyed() || cy.nodes().length === 0) return;
  try {
    const { applyElkLayout } = await import('../utils/elkLayout');
    await applyElkLayout(cy, opts);
  } catch (e) {
    console.warn('ELK layout failed, falling back to snake', e);
    runSnakeLayout(cy);
  }
}

// ── Main hook ──────────────────────────────────────────────────────
export default function useCytoscapeGraph(containerRef, graphData, options = {}) {
  const cyRef = useRef(null);
  const optsRef = useRef(options);
  optsRef.current = options;
  const fieldRelRef = useRef(null);

  const { level, layoutMode } = options;

  useEffect(() => {
    if (!containerRef.current || !graphData) return;
    let { nodes, edges } = graphData;
    if (!nodes || nodes.length === 0) return;

    // Strip field "parent" → "_tableParent" before Cytoscape sees them
    nodes = stripFieldParents(nodes);

    const isL2 = level === 'L2';
    const baseEdgeStyles = isL2
      ? [...TURN_EDGE_STYLES, ...BUNDLED_EDGE_STYLES,
         ...CATEGORY_EDGE_STYLES, ...OPERATION_NODE_STYLES, ...L2_DETAIL_STYLES]
      : [...SCRIPT_CARD_STYLES];
    const edgeStyles = [...L1_PIPELINE_EDGE_STYLES, ...baseEdgeStyles];

    const cy = cytoscape({
      container: containerRef.current,
      style: [...NODE_STYLES, ...COMPOUND_STYLES, ...edgeStyles],
      elements: { nodes, edges },
      layout: { name: 'preset' },
      wheelSensitivity: 0.3,
      minZoom: 0.05,
      maxZoom: 5,
    });

    // ── Drag: keep fields glued to their table (frozen offsets) ──
    // Fields hold ABSOLUTE positions. Re-derive them from the table's
    // current position + frozen relative offsets on every drag event
    // (shared helper in layoutCore — same math applyLayout uses). The
    // old per-event delta accumulation preserved any pre-existing
    // discrepancy (a directly-dragged field, a coalesced drag frame, a
    // stale position left by a programmatic move) instead of correcting
    // it — that was the drift root cause.
    cy.on('drag', TABLE_SEL, evt => {
      if (fieldRelRef.current) positionTableFields(cy, evt.target.id(), fieldRelRef.current);
    });
    // Final snap after release — guarantees exact offsets even if the
    // last drag frame's event was dropped.
    cy.on('dragfree', TABLE_SEL, evt => {
      if (fieldRelRef.current) positionTableFields(cy, evt.target.id(), fieldRelRef.current);
    });

    // ── Role badges on script nodes ─────────────────────────────
    cy.nodes('[type="script_node"]').forEach(n => {
      const roles = n.data('roles') || [];
      if (!roles.length) return;
      const s = { REF: 'R', JOIN: 'J', FILTER: 'F', AGGREGATE: 'A', WINDOW: 'W', TRANSFORM: 'T',
        COMPUTED: 'C', SCHEMA: 'S', TABLE_FLOW: 'TF', 'DML TARGET': 'DT', CORRELATED: 'CR' };
      const ab = roles.slice(0, 4).map(r => s[r] || r.slice(0, 2));
      if (!/\n(R|J|F|A|W|T|C|S|TF|DT|CR)/.test(n.data('label') || ''))
        n.data('label', (n.data('label') || '') + '\n' + ab.join(' '));
    });

    // ── Event wiring ────────────────────────────────────────────
    const o = optsRef.current;
    if (o.onTap) cy.on('tap', 'node', e => o.onTap(e));
    if (o.onDblTap) cy.on('dbltap', 'node', e => o.onDblTap(e));
    if (o.onHoverEnter) cy.on('mouseover', 'node', e => o.onHoverEnter(e));
    if (o.onHoverLeave) cy.on('mouseout', 'node', e => o.onHoverLeave(e));
    if (o.onEdgeTap) cy.on('tap', 'edge', e => o.onEdgeTap(e));
    if (o.onEdgeHover) cy.on('mouseover', 'edge', e => o.onEdgeHover(e));
    // R25/§8.8: background taps only — element taps bubble to the core,
    // so guard on e.target === cy (tap on canvas/empty space clears the
    // edge selection; a node/edge tap must never trigger the clear).
    if (o.onBgTap) cy.on('tap', e => { if (e.target === cy) o.onBgTap(e); });

    cyRef.current = cy;
    window.__cy = cy;
    if (containerRef.current?.closest('.panel-center')) window.__cy1 = cy;

    // ── Initial layout ──────────────────────────────────────────
    cy.ready(() => {
      fieldRelRef.current = computeFieldRelPos(cy);
      if (layoutMode === 'pipeline') {
        pipelineLayout(cy);
      } else {
        runSnakeLayout(cy);
      }
    });

    return () => {
      if (cy && !cy.destroyed()) cy.destroy();
      cyRef.current = null;
      if (window.__cy === cy) {
        window.__cy = (window.__cy1 && !window.__cy1.destroyed?.()) ? window.__cy1 : null;
      }
    };
  }, [graphData, containerRef]);

  const fit = useCallback((p = undefined) => {
    if (cyRef.current && !cyRef.current.destroyed()) {
      cyRef.current.fit(undefined, p !== undefined ? p : 50);
    }
  }, []);

  const relayout = useCallback((mode) => {
    const cy = cyRef.current;
    if (!cy || cy.destroyed()) return;
    fieldRelRef.current = computeFieldRelPos(cy);
    if (mode === "pipeline") {
      pipelineLayout(cy);
    } else {
      runSnakeLayout(cy);
    }
  }, []);

  return { cyRef, fit, relayout };
}
