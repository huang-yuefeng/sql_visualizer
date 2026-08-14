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
  OPERATION_NODE_STYLES, L2_DETAIL_STYLES, L2_NODE_ROLE_STYLES,
  L2_UNIFORM_EDGE_STYLES, L2_EDGE_CLASSES } from '../utils/graphStyles';
import { stripFieldParents, computeFieldRelPos, positionTableFields } from '../utils/layoutCore';
import { TABLE_SELECTOR } from '../config/layout';
import { runSnakeLayout } from '../utils/snakeLayout';
import { decorateLabelWithLine } from '../utils/labelDecoration';

const TABLE_SEL = TABLE_SELECTOR;

// R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow — always
// hidden (the display toggle was removed as seldom-used). The selector
// matches edge_type (canonical) and tolerates the legacy relationship key.
const SCHEMA_EDGE_SELECTOR = '[edge_type="SCHEMA"], [relationship="SCHEMA"]';

/**
 * Net-flow role badge for an L2 table node (R19.6a, defensive).
 * Data-driven only: `flow_role` ("source"|"target"|"waypoint") wins;
 * otherwise `flow_source`/`flow_target` booleans (both → "S/T").
 * Returns null when the payload carries no role fields — no badge.
 */
function flowRoleBadge(d) {
  if (d.flow_role === 'source') return 'S';
  if (d.flow_role === 'target') return 'T';
  if (d.flow_role === 'waypoint') return 'W';
  const parts = [];
  if (d.flow_source === true) parts.push('S');
  if (d.flow_target === true) parts.push('T');
  return parts.length > 0 ? parts.join('/') : null;
}

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

    // J12-19 (render-only): field→own-table edges would render INSIDE the
    // table box (fields sit at table.pos + frozen offset; the box paints an
    // opaque background, and Cytoscape draws edges below nodes) — invisible
    // and un-clickable. Tag them with a class so the stylesheet can raise
    // their z-index above the box. The payload is untouched (new element
    // objects only); the SQL highlight on edge click was already correct.
    const fieldParent = {};
    for (const n of nodes) {
      const d = n.data;
      if (d && d.type === 'field' && d._tableParent) fieldParent[d.id] = d._tableParent;
    }
    if (Object.keys(fieldParent).length) {
      edges = edges.map(e => {
        const d = e.data;
        if (!d || !d.source || !d.target) return e;
        if (fieldParent[d.source] === d.target || fieldParent[d.target] === d.source) {
          return { ...e, classes: `${e.classes || ''} field-to-own-parent`.trim() };
        }
        return e;
      });
    }

    const isL2 = level === 'L2';
    const baseEdgeStyles = isL2
      ? [...TURN_EDGE_STYLES, ...BUNDLED_EDGE_STYLES,
         ...CATEGORY_EDGE_STYLES, ...OPERATION_NODE_STYLES, ...L2_DETAIL_STYLES,
         // R28: source/target/waypoint role styles LAST — they must win
         // the specificity tie against the compound-type styles below.
         ...L2_NODE_ROLE_STYLES,
         // R30/#224-#225: L2 uniform edge style + mid-point arrow + flow
         // cone. MUST be last — wins the specificity tie against the
         // per-type `edge[color]` / `edge[category=...]` / `edge[flow_kind]`
         // rules so every L2 edge renders identically (the cone classes
         // then override the uniform base on focus).
         ...L2_UNIFORM_EDGE_STYLES]
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

    // ── R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow ──
    // Always hidden via a style class — client-side visibility only: the
    // edges STAY in the graph model (the payload is untouched and nothing
    // re-fetches); edge taps on hidden edges never fire, so the SQL
    // highlight-on-edge-click keeps working for visible edges.
    cy.edges(SCHEMA_EDGE_SELECTOR).addClass('structure-hidden');

    // ── R30/#224: L2 uniform edge style — tag every L2 edge ───────────
    // The `.l2-uniform` rule is appended LAST in the stylesheet above, so
    // for these edges it wins the specificity tie against the per-type
    // `edge[color]` / `edge[category=...]` / `edge[flow_kind]` rules —
    // every L2 edge renders ONE uniform line (single color/width/style,
    // no text label, mid-point arrow). L1 edges never carry the class, so
    // L1 rendering is unchanged.
    if (isL2) cy.edges().addClass(L2_EDGE_CLASSES.uniform);

    // ── R27: "@L{line}" after L2 node names (display-only projection) ──
    // Append `@L{line_start}` to the RENDERED label of every L2 node
    // carrying a valid line_start (table compounds incl. the ⟐ output
    // VTs — `output@L160`/`output@L211` — exactly the reason-string
    // convention). The payload labels are untouched (same pattern as
    // the badge block below, which appends to n.data('label')). Labels
    // that already end with @<digits> (aliases like `p1@29`) keep it
    // as-is — never double-append. Nodes without a valid line_start
    // pass through unchanged — the renderer never guesses.
    if (isL2) {
      cy.nodes().forEach(n => {
        const d = n.data();
        if (!d) return;
        n.data('label', decorateLabelWithLine(d.label, d.line_start));
      });
    }

    // ── Net-flow role badges on L2 table nodes (defensive) ──────────
    // If the payload carries flow_role ("source"|"target"|"waypoint")
    // and/or flow_source/flow_target booleans, append a small S/T/W
    // badge line to the table label. Field absent → no badge — the
    // renderer never guesses (the backend attaches the fields only
    // where it has the information, e.g. the FULL no-search view).
    if (isL2) {
      cy.nodes().forEach(n => {
        const d = n.data();
        if (!d) return;
        const badge = flowRoleBadge(d);
        if (!badge) return;
        const label = d.label || '';
        if (!label.endsWith('\n' + badge)) n.data('label', label + '\n' + badge);
      });
    }

    // ── Event wiring ────────────────────────────────────────────
    const o = optsRef.current;
    if (o.onTap) cy.on('tap', 'node', e => o.onTap(e));
    if (o.onDblTap) cy.on('dbltap', 'node', e => o.onDblTap(e));
    if (o.onHoverEnter) cy.on('mouseover', 'node', e => o.onHoverEnter(e));
    if (o.onEdgeTap) cy.on('tap', 'edge', e => o.onEdgeTap(e));
    // R25/§8.8: background taps only — element taps bubble to the core,
    // so guard on e.target === cy (tap on canvas/empty space clears the
    // edge selection; a node/edge tap must never trigger the clear).
    if (o.onBgTap) cy.on('tap', e => { if (e.target === cy) o.onBgTap(e); });

    cyRef.current = cy;
    // Devtools-only debug handles (nothing in the app reads them). Gated
    // on DEV so the globals never exist in production; both are cleared
    // on unmount so they can't outlive the cytoscape instance.
    if (import.meta.env.DEV) {
      window.__cy = cy;
      if (containerRef.current?.closest('.panel-center')) window.__cy1 = cy;
    }

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
      if (import.meta.env.DEV) {
        if (window.__cy === cy) {
          window.__cy = (window.__cy1 && !window.__cy1.destroyed?.()) ? window.__cy1 : null;
        }
        // __cy1 was never cleared before — a destroyed instance could
        // linger after unmount (and even be promoted into __cy above).
        if (window.__cy1 === cy) window.__cy1 = null;
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
