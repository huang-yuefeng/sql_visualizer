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
  L2_UNIFORM_EDGE_STYLES, L2_EDGE_CLASSES, HOVER_EMPHASIS_STYLES,
  FILTER_CAPTION_STYLES,
  FILTER_SELFLOOP_STYLES } from '../utils/graphStyles';
import { stripFieldParents, computeFieldRelPos, positionTableFields } from '../utils/layoutCore';
import { TABLE_SELECTOR, FIT_PADDING } from '../config/layout';
import { runSnakeLayout } from '../utils/snakeLayout';
import { decorateLabelWithLine } from '../utils/labelDecoration';
import { applyFlowVisibility, fitAllElements } from '../utils/flowVisibility';

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

// ── R31 layout persistence (A-M5) ──────────────────────────────────
/**
 * Collect absolute node positions {nodeId: [x, y]} for every NON-field node
 * (fields are re-derived from their table at table + frozen offset, so they
 * are never saved — applyLayout and the drag handler position them).
 */
function collectPositions(cy) {
  if (!cy || cy.destroyed()) return {};
  const out = {};
  cy.nodes().forEach(n => {
    if (n.data('type') === 'field') return;
    if (n.data('synthetic')) return; // v3.3.183 caption nodes are view chrome
    const p = n.position();
    if (p) out[n.id()] = [Math.round(p.x), Math.round(p.y)];
  });
  return out;
}

/**
 * Re-apply saved positions {nodeId: [x,y]} on a fresh graph (resume). Node
 * ids that no longer exist are skipped — never an error (design §5.3). After
 * tables move, fields are re-derived; then re-fit with the level-aware
 * adaptive padding so the viewport spans the applied layout. Runs BEFORE
 * flow-visibility hiding, so the fit sees every node — the same D-H2
 * contract as the initial layout (the fit excludes display:none elements).
 */
function applySavedPositions(cy, savedPositions, fieldRel) {
  if (!cy || cy.destroyed() || !savedPositions || typeof savedPositions !== 'object') return;
  let moved = false;
  cy.batch(() => {
    cy.nodes().forEach(n => {
      const p = savedPositions[n.id()];
      if (Array.isArray(p) && p.length === 2 && Number.isFinite(p[0]) && Number.isFinite(p[1])) {
        n.position({ x: p[0], y: p[1] });
        moved = true;
      }
    });
  });
  if (!moved) return;
  // Fields follow their tables (shared helper — same math as the drag path).
  if (fieldRel) {
    const parents = new Set();
    for (const rel of Object.values(fieldRel)) parents.add(rel.parentId);
    for (const pid of parents) positionTableFields(cy, pid, fieldRel);
  }
  // Level-aware fit — mirrors layoutCore.applyLayout's adaptive padding
  // (that file is the single source; kept in sync deliberately).
  if (!cy.destroyed()) {
    const level = (cy.container()?.closest?.('[data-level]')?.dataset?.level) || 'L1';
    const panelW = cy.container()?.offsetWidth || 800;
    const pad = level === 'L2' ? Math.max(16, Math.floor(panelW * 0.05)) : FIT_PADDING;
    cy.fit(undefined, pad);
  }
}

// ── Pipeline layout (lazy-import ELK) ──────────────────────────────
async function pipelineLayout(cy, opts = {}, onFit) {
  if (!cy || cy.destroyed() || cy.nodes().length === 0) return;
  try {
    const { applyElkLayout } = await import('../utils/elkLayout');
    await applyElkLayout(cy, opts, onFit);
  } catch (e) {
    console.warn('ELK layout failed, falling back to snake', e);
    runSnakeLayout(cy, onFit);
  }
}

// ── Dynamic hover-enlarge (display-only) ───────────────────────────
/**
 * Elements whose label enlarges while `target` is under the pointer.
 *   - edge  → its two endpoint nodes PLUS every field chip of each endpoint
 *     table box (the chips, not just the title, are what the reader traces).
 *   - node  → the node itself PLUS every field chip of its table box.
 *     Fields are separate TOP-LEVEL nodes: their `parent` was moved into
 *     `_tableParent` by stripFieldParents BEFORE Cytoscape ever saw them,
 *     so `target.children()` is always empty — membership comes only from
 *     matching `_tableParent` against the hovered box's id. data() itself
 *     is guarded (an element always has one, but a defensive read keeps
 *     this quiet if the payload shape drifts).
 * Returns a collection (empty when handed anything unexpected), so the
 * callers below can add/remove the class unconditionally.
 */
function hoverEmphTargets(target) {
  const cy = target && typeof target.cy === 'function' ? target.cy() : null;
  if (!cy || typeof target.isEdge !== 'function' || cy.destroyed()) {
    return cy ? cy.collection() : null;
  }
  const members = [target];
  // v3.3.176 FIX (user-verified defect): the edge branch returned the EDGE
  // itself, but edges carry no visible label — so hovering an edge changed
  // nothing on screen. Enlarge the two ENDPOINT nodes (edge included
  // harmlessly, for future edge styling).
  // v3.3.177: endpoint TABLES must bring their FIELD CHIPS along — a title
  // alone is not the caption the reader traces; the chips are the payload
  // (same `_tableParent` flat scan the node branch uses, applied to every
  // connected node, so CTE/alias endpoints without chips are unaffected).
  if (target.isEdge()) {
    const ends = target.connectedNodes();
    ends.forEach(n => members.push(n));
    const ids = new Set(ends.map(n => n.id()));
    cy.nodes().forEach(n => {
      const nd = n.data();
      if (nd && nd._tableParent && ids.has(nd._tableParent)) members.push(n);
    });
    return cy.collection(members);
  }
  {
    const d = target.data();
    if (d && d.id !== undefined) {
      // Field chips link UP to their box via `_tableParent` (never down via
      // children() — see docstring), so membership is a flat id scan.
      cy.nodes().forEach(n => {
        const nd = n.data();
        if (nd && nd._tableParent === d.id) members.push(n);
      });
    }
  }
  return cy.collection(members);
}

// ── Main hook ──────────────────────────────────────────────────────
export default function useCytoscapeGraph(containerRef, graphData, options = {}) {
  const cyRef = useRef(null);
  const optsRef = useRef(options);
  optsRef.current = options;
  const fieldRelRef = useRef(null);
  // L2 flow toggle: the layout must run ONCE on the FULL graph (all nodes
  // visible) and only THEN hide non-flow elements. This ref gates the
  // standalone flow effect so it never hides before the initial
  // cy.ready→layout+fit has finished (see cy.ready + the effect below).
  const layoutDoneRef = useRef(false);

  const { level, layoutMode, flowOnly, flowNodeIds, flowEdgeIds, mergedView } = options;

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
      // HOVER_EMPHASIS_STYLES composes LAST by convention (later rules win
      // specificity ties in cytoscape): the `.label-emph` font-size must
      // beat every per-type node rule (field chips, table compounds, script
      // cards) that would otherwise share the tie. Pure display — a label
      // size change never feeds any layout, so nothing re-layouts.
      style: [...NODE_STYLES, ...COMPOUND_STYLES, ...edgeStyles,
        ...HOVER_EMPHASIS_STYLES,
        ...FILTER_CAPTION_STYLES,
        // R32 self-loop FILTER captions — spread LAST so the rule beats
        // L2_UNIFORM_EDGE_STYLES' explicit `'label': ''` on the same
        // specificity tie (later rule wins; same convention as the hover
        // block above). Only edges carrying `data.filterLabel` match —
        // everything else renders exactly as before.
        ...FILTER_SELFLOOP_STYLES],
      elements: { nodes, edges },
      layout: { name: 'preset' },
      wheelSensitivity: 0.3,
      // v3.3.175: 0.05 let fit shrink EAST5's full L2 to ~1px glyphs where
      // even 2x hover emphasis gained <1 screen px (the "#377 invisible
      // hover" trial). 0.28 keeps labels legible; pan covers the rest.
      minZoom: 0.28,
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
    // R31/A-M5: report node positions after any drag ends (tables + scripts;
    // fields follow their table via frozen offsets) — DataFlowApp autosaves
    // them ≤1/s + on close (design §4 Q4). Fires for every draggable node.
    cy.on('dragfree', () => {
      const o = optsRef.current;
      if (o.onPositionsChange) o.onPositionsChange(collectPositions(cy));
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
    // R37: L2 node tap → SQL definition line. DataFlowGraph gates this to
    // level === 'L2' and guards the line in its handler; the hook stays a
    // plain pass-through like onEdgeTap.
    if (o.onNodeTap) cy.on('tap', 'node', e => o.onNodeTap(e));
    if (o.onDblTap) cy.on('dbltap', 'node', e => o.onDblTap(e));
    if (o.onHoverEnter) cy.on('mouseover', 'node', e => o.onHoverEnter(e));
    if (o.onEdgeTap) cy.on('tap', 'edge', e => o.onEdgeTap(e));
    // R25/§8.8: background taps only — element taps bubble to the core,
    // so guard on e.target === cy (tap on canvas/empty space clears the
    // edge selection; a node/edge tap must never trigger the clear).
    if (o.onBgTap) cy.on('tap', e => { if (e.target === cy) o.onBgTap(e); });

    // ── Dynamic hover-enlarge (display-only) ────────────────────
    // Hovering a node enlarges ITS label plus the labels of every field
    // chip in that table box; hovering an edge enlarges its two endpoints.
    // Fields are separate top-level nodes whose `parent` was stripped into
    // `_tableParent` before Cytoscape saw them, so `children()` is always
    // empty — hoverEmphTargets matches on `_tableParent` instead. Classes
    // only re-render styles: a label size never feeds a layout, so no
    // re-layout can fire from this path.
    cy.on('mouseover', 'node, edge', e => {
      const t = hoverEmphTargets(e.target);
      if (!t || t.length === 0) return;
      cy.batch(() => t.addClass('label-emph'));
    });
    // The main effect's cleanup destroys the instance without waiting for
    // the pointer to leave — removing classes off a destroyed core throws,
    // so mouseout bails instead (mirrors every other cy.destroyed() guard
    // in this file).
    cy.on('mouseout', 'node, edge', e => {
      if (cy.destroyed()) return;
      const t = hoverEmphTargets(e.target);
      if (!t || t.length === 0) return;
      cy.batch(() => t.removeClass('label-emph'));
    });

    cyRef.current = cy;
    // Fresh graph: layout+fit must run on the FULL graph before the flow
    // filter hides anything (see layoutDoneRef docstring above).
    layoutDoneRef.current = false;
    // Devtools-only debug handles (nothing in the app reads them). Gated
    // on DEV so the globals never exist in production; both are cleared
    // on unmount so they can't outlive the cytoscape instance.
    if (import.meta.env.DEV) {
      window.__cy = cy;
      if (containerRef.current?.closest('.panel-center')) window.__cy1 = cy;
    }

    // ── Initial layout ──────────────────────────────────────────
    // Layout runs ONCE on the FULL graph (every node visible). Only after
    // it completes does the flow filter hide the non-closure elements — the
    // viewport fit (applyLayout's deferred cy.fit) therefore always sees
    // the full graph, so both View 1 and View 2 fit inside it.
    cy.ready(() => {
      fieldRelRef.current = computeFieldRelPos(cy);
      // D-H2: fit the FULL graph BEFORE hiding. applyLayout defers cy.fit
      // via setTimeout(100); cy.fit excludes display:none elements, so hiding
      // non-flow elements first would clip the viewport to the flow closure
      // and push View 2's non-closure nodes off-screen. onFit runs after the
      // deferred fit has seen every node — only then apply visibility (and
      // mark the initial layout done).
      const onFit = () => {
        const o = optsRef.current;
        // R31/A-M5: re-apply saved positions on a fresh graph (resume)
        // instead of recomputing — node ids that no longer exist are skipped.
        // Runs AFTER the layout's deferred fit (layoutCore.applyLayout) so the
        // viewport refits to the applied positions, and BEFORE the flow filter
        // hides anything (the re-fit must see the FULL graph, D-H2).
        if (o.savedPositions) {
          applySavedPositions(cy, o.savedPositions, fieldRelRef.current);
        }
        applyFlowVisibility(cy, o);
        layoutDoneRef.current = true;
      };
      if (layoutMode === 'pipeline') {
        pipelineLayout(cy, {}, onFit);
      } else {
        runSnakeLayout(cy, onFit);
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

  // ── L2 flow toggle (View 1 flow-only / View 2 full) ──────────────
  // Applies .hide()/.show() — NEVER a layout, so positions stay identical
  // across toggles. Gated on layoutDoneRef: on a fresh graph the initial
  // cy.ready→layout+fit runs first (the fit must see the FULL graph), and
  // cy.ready applies the initial visibility itself.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || cy.destroyed()) return;
    if (!layoutDoneRef.current) return; // initial layout not done yet
    applyFlowVisibility(cy, { flowOnly, flowNodeIds, flowEdgeIds, mergedView });
    // mergedView rides along (#376): only the line-merged members prune their
    // edgeless field chips — switching detailed ↔ merged re-runs this effect.
  }, [flowOnly, flowNodeIds, flowEdgeIds, mergedView]);

  const fit = useCallback((p = undefined) => {
    const cy = cyRef.current;
    if (!cy || cy.destroyed()) return;
    // E-M8 (#283): while a flow-only (View 1) filter is active, a plain fit
    // bounds only the visible closure — View 2's non-closure nodes would sit
    // off-screen after every resize. Fit the FULL graph, then restore the
    // flow visibility (never a layout — positions are preserved).
    const o = optsRef.current;
    if (o.flowOnly || o.flowNodeIds || o.flowEdgeIds) {
      fitAllElements(cy, {
        flowOnly: o.flowOnly,
        flowNodeIds: o.flowNodeIds,
        flowEdgeIds: o.flowEdgeIds,
        mergedView: o.mergedView,
      }, p !== undefined ? p : 50);
    } else {
      cy.fit(undefined, p !== undefined ? p : 50);
    }
  }, []);

  const relayout = useCallback((mode) => {
    const cy = cyRef.current;
    if (!cy || cy.destroyed()) return;
    // D-H2: gate mount-time relayout on the initial layout having finished
    // (cy.ready → layout → deferred fit). On a fresh graph DataFlowGraph's
    // mount-time mode-switch effect fires relayout BEFORE the initial fit —
    // running it would hide flow elements before cy.fit sees the full graph.
    if (!layoutDoneRef.current) return;
    // #310: show every element before re-running the layout. applyLayout's
    // deferred cy.fit excludes display:none elements, so if a flow-only
    // (View 1) filter is active the fit would bound only the visible closure
    // and push View 2's non-closure nodes off-screen after the mode switch.
    // The flow-only ↔ full toggle itself stays pure visibility (no re-layout).
    cy.elements().show();
    fieldRelRef.current = computeFieldRelPos(cy);
    const onFit = () => applyFlowVisibility(cy, optsRef.current);
    if (mode === "pipeline") {
      pipelineLayout(cy, {}, onFit);
    } else {
      runSnakeLayout(cy, onFit);
    }
  }, []);

  return { cyRef, fit, relayout };
}
