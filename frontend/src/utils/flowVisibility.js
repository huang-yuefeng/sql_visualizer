/**
 * L2 flow-only visibility (search toggle).
 *
 * View 1 (flow-only, DEFAULT): render only the nodes/edges in the target
 * field's flow closure — the L2 response carries them as
 * `flow_node_ids` / `flow_edge_ids`. View 2 (full): the entire script graph.
 *
 * The cytoscape instance is built ONCE from the FULL payload (see
 * useCytoscapeGraph); these helpers then hide/show client-side — they
 * NEVER run a layout, so node positions stay byte-identical across toggles.
 */

/**
 * Resolve the initial toggle state from an L2 response.
 *  - `flow_node_ids` OR `flow_edge_ids` present (matched search) → flow-only
 *    ON (default). The closure normally carries both lists together, but a
 *    node-only or edge-only closure must still enable View 1 — an edge set
 *    is part of the same flow closure, not a separate signal.
 *  - absent (no search seed / search did not match / filter off) → null
 *    (toggle disabled, always show the full graph).
 */
export function resolveFlowOnly(result) {
  const hasNodes = Array.isArray(result && result.flow_node_ids)
    && result.flow_node_ids.length > 0;
  const hasEdges = Array.isArray(result && result.flow_edge_ids)
    && result.flow_edge_ids.length > 0;
  return (hasNodes || hasEdges) ? true : null;
}

// #376 (v3.3.180): SCHEMA structure/containment edges are permanently
// display-hidden (useCytoscapeGraph adds this class; graphStyles resolves it
// to display:none). An edge carrying it can never connect a chip on screen.
const STRUCTURE_HIDDEN_CLASS = 'structure-hidden';

/**
 * E-M8 (#283): fit the FULL graph (closure + non-closure) and then restore
 * the flow-only visibility.
 *
 * Cytoscape's `fit()` excludes `display:none` elements, so a plain
 * `cy.fit()` while View 1 (flow-only) is active bounds the viewport to the
 * visible closure only — toggling to View 2 then shows non-closure nodes
 * off-screen. This helper shows everything, fits, and re-applies the flow
 * visibility — never a layout, so node positions stay byte-identical.
 */
export function fitAllElements(cy, { flowOnly, flowNodeIds, flowEdgeIds, mergedView, recenter } = {},
  padding = 50) {
  if (!cy || (typeof cy.destroyed === 'function' && cy.destroyed())) return;
  cy.elements().show();
  cy.fit(undefined, padding);
  applyFlowVisibility(cy, { flowOnly, flowNodeIds, flowEdgeIds, mergedView, recenter });
}

/**
 * Apply the flow-only visibility filter to a cytoscape instance.
 *
 * `flowOnly` truthy → show exactly the closure nodes (`flowNodeIds`) and
 * closure edges (`flowEdgeIds`), hiding every other element. An edge is
 * also hidden when either endpoint is hidden (defensive — a closure edge
 * always connects closure nodes, but a hidden-table sibling must never
 * leak an edge). `flowOnly` falsy → show everything.
 *
 * `mergedView` truthy → the displayed payload is a line-merged one
 * ('flow-merged'/'full-merged'); after the show/hide above, field chips with
 * no visible incident edge are hidden as well (#376 — merged edges are all
 * table-level, so an untouched field node would render as a floating orphan;
 * V2-N1: the searched `is_target` seed chips are exempt — they always render).
 * Detailed views never pass it: their field-level edges stay untouched.
 *
 * Pure visibility — calls only cytoscape `.show()` / `.hide()` (+`.batch()`),
 * never a layout, so positions are preserved across toggles.
 */
/**
 * #376 (v3.3.180) — hide the field chips that no visible merged edge touches.
 *
 * MERGED view modes only ('flow-merged' / 'full-merged'). The line-merged
 * pass (`build_line_merged_edges`) promotes every field endpoint to its
 * parent table before collapsing same-line duplicates, while the NODE set is
 * passed through untouched (R32). Result: the merged edge set is entirely
 * table-level, so a field chip carried in `flow_node_ids` renders with ZERO
 * visible edges — a floating orphan (the searched seed chip is exactly this
 * case). Hiding such chips repairs the rendering without touching any
 * backend payload: the chip's membership context stays readable through its
 * owning TABLE box, which is always shown and always connected.
 *
 * Tables/CTEs/aliases are never hidden here — only nodes with
 * `data.type === "field"`. A chip with ≥1 visible incident edge stays: in the
 * rare parentless-field case the promotion map skips the endpoint, so that
 * chip keeps its merged edge and must keep rendering. Pure visibility — no
 * positions are read or written.
 *
 * V2-N1 (2026-08-29): the SEARCHED field's own seed chips are exempt. The
 * closure view exists because the user searched a table.field, and F-B1 made
 * field chips clickable (chip tap → its SQL definition line) — hiding the
 * searched chip left the default 'Flow only' view with ZERO chips in 5 of 7
 * measured closures (the merged edge set is table-level, so the seed chip is
 * exactly the edge-less case) and no way to click what the user came for.
 * `is_target` is the builder's seed marker (P1 seed copies land on
 * alias/CTE/target nodes too, all `is_target`), the same flag `centerOnSeed`
 * uses. The chip still sits INSIDE its table box, so it adds no orphan.
 */
function hideEdgelessFieldChips(cy) {
  // Collect the endpoints of every edge actually on screen. Stylesheet-hidden
  // edges (the `.structure-hidden` SCHEMA lines) can never connect anything.
  const linked = new Set();
  const touch = id => { if (id != null) linked.add(id); };
  cy.edges().forEach(e => {
    const structurallyHidden = typeof e.hasClass === 'function'
      && e.hasClass(STRUCTURE_HIDDEN_CLASS);
    if (structurallyHidden || (typeof e.hidden === 'function' && e.hidden())) return;
    touch(typeof e.data === 'function' ? e.data('source') : undefined);
    touch(typeof e.data === 'function' ? e.data('target') : undefined);
  });
  const prune = () => {
    cy.nodes().forEach(n => {
      const d = typeof n.data === 'function' ? n.data() : undefined;
      if (!d || d.type !== 'field') return;
      // V2-N1: a searched seed chip is never an orphan however the merged
      // edge set was promoted — it is the chip the user searched for.
      if (d.is_target === true) return;
      const id = typeof n.id === 'function' ? n.id() : n.id;
      if (!linked.has(id)) n.hide();
    });
  };
  if (typeof cy.batch === 'function') cy.batch(prune); else prune();
}

/**
 * v3.3.183 (updated v3.3.191) — make absorbed FILTER edges BIG and readable
 * in merged views.
 *
 * R32 promotion collapses `p_dt ──FILTER──► east5` into an `east5→east5`
 * self-loop that renders ~5x5 px at the zoom floor, and cytoscape paints
 * edge labels BENEATH node fills — so the single most important edge of a
 * search was effectively invisible (user-verified three times). Fix, purely
 * client-side:
 *   1. Tag every visible merged self-loop with `filter-selfloop` — the
 *      stylesheet (FILTER_LOOP_GEOM_STYLES) then draws it as a big red
 *      bezier loop hugging the table's LEFT border (per-edge
 *      control-point-step-size data + loop-direction -90deg). The edge
 *      itself is the visible, clickable curve: its tap highlights the
 *      absorbed SQL line (R37).
 *   2. Pin a CAPTION NODE at the loop midpoint — nodes paint above
 *      everything, so the caption is deterministically visible. The node is
 *      `synthetic`: non-interactive (`events: 'no'`), excluded from layout
 *      persistence (collectPositions skips type 'caption'), and removed/
 *      re-created on every visibility pass so it can never leak.
 */
// v3.3.191 — target bulge of the self-loop arc PAST the table's left border,
// in model units (≈42 screen px at the 0.28 zoom floor). cytoscape scales a
// self-loop from the node CENTRE (ctrl pts = centre ± 1.4 × step along the
// loop axis; with direction -90deg/sweep -90deg the horizontal reach is
// ≈ 0.99 × step), so a fixed step that clears a small chip disappears inside
// a wide table box — hence the per-edge measurement below.
const SELFLOOP_BULGE = 150;

function enlargeFilterSelfLoops(cy) {
  // v3.3.191: tag the edge and let the stylesheet draw the big curve. The
  // v3.3.185 `data.segp` + `segment-points` hack never worked — cytoscape
  // 3.34 has no `segment-points` property (the parsed stylesheet drops it
  // silently), and a self-edge's geometry comes from findLoopPoints
  // (control-point-step-size / loop-direction / loop-sweep) whatever
  // curve-style says, so the loop rendered at the 40-unit default: 8×8 px
  // at the 0.28 zoom floor. FILTER_LOOP_GEOM_STYLES maps this class to the
  // loop properties with a per-edge `loopstep` sized from the endpoint box.
  cy.edges().forEach(e => {
    try {
      const d = (typeof e.data === 'function' ? e.data() : e.data) || {};
      const isSelf = d.source != null && d.source === d.target;
      if (!isSelf || (typeof e.hidden === 'function' && e.hidden())) return;
      let halfW = 60; // sane floor for bare/fake nodes in unit tests
      try {
        const nb = e.source().boundingBox({ includeLabels: false,
          includeNodes: true, includeEdges: false, includeOverlays: false });
        if (nb && Number.isFinite(nb.w)) halfW = Math.max(20, nb.w / 2);
      } catch (_) { /* keep the floor */ }
      // data FIRST, then the class — the mapping resolves on the style
      // recalc that follows this batch, so no missing-field warning fires.
      if (typeof e.data === 'function') {
        e.data('loopstep', Math.round(halfW + SELFLOOP_BULGE));
      }
      if (typeof e.addClass === 'function') e.addClass('filter-selfloop');
    } catch (_) { /* fake cy in unit tests — best-effort */ }
  });
}

function removeCaptionNodes(cy) {
  try {
    const deadEdges = cy.edges().filter(e => {
      const d = typeof e.data === 'function' ? e.data() : {};
      return d && d.type === 'caption';
    });
    if (deadEdges.length) cy.remove(deadEdges);
  } catch (_) {}
  const dead = cy.nodes().filter(n => {
    const d = typeof n.data === 'function' ? n.data() : {};
    return d.type === 'caption';
  });
  if (dead.length) cy.remove(dead);
}

function upsertFilterCaptions(cy) {
  cy.edges().forEach(e => {
    try {
      const d = (typeof e.data === 'function' ? e.data() : e.data) || {};
      const label = d.filterLabel;
      if (!label || (typeof e.hidden === 'function' && e.hidden())) return;
      const z2 = (typeof cy.zoom === 'function') ? (cy.zoom() || 1) : 1;
      if (typeof e.midpoint !== 'function') return; // fake edge — skip
      const id = 'cap_' + (typeof e.id === 'function' ? e.id() : e.id);
      // Caption text is model-space too — compensate for zoom so it stays
      // ~14 screen px (readable) at the 0.28 floor and modest when zoomed in.
      // v3.3.190 (ruling B2): font-size is MODEL-space — 14px at the 0.28
      // zoom floor renders ~4px. Carry a zoom-compensated size in data
      // (runtime e.style() is a no-op; the stylesheet maps it) so the
      // caption never renders below ~11 screen px.
      const capFont = Math.max(14, Math.round(11 / z2));
      if (!cy.getElementById(id).length) {
        cy.add({
          data: { id, label, type: 'caption', synthetic: true, caption_font: capFont },
          position: e.midpoint(),
          classes: 'filter-caption',
        });
      } else {
        cy.getElementById(id).position(e.midpoint()).data('caption_font', capFont);
      }
      // v3.3.186/187 capA/capB/capL bracket — RETIRED in v3.3.191. The
      // bracket was a straight node-node line minted beside the table
      // BECAUSE the real self-loop could not be enlarged (inert
      // segment-points hack). Two user-reported defects came of it: the
      // straight line read as "edge from and to the same table is a
      // straight line", and clicking it did nothing (the bracket carried
      // `events: 'no'`, and the tiny 8×8 px real loop beneath was
      // un-hittable). The real edge now IS the big left-border curve
      // (FILTER_LOOP_GEOM_STYLES) and takes the taps itself; only the
      // caption NODE above the loop remains. removeCaptionNodes still
      // sweeps any stale anchors on resumed graphs.
    } catch (_) { /* fake cy — captions are best-effort chrome */ }
  });
}

/**
 * v3.3.183 — after the flow show/hide, re-center the viewport on the SEED
 * (the searched field and its owning box). Fit bottoms out at the zoom
 * floor for tall scripts, and the seed zone sat at negative Y — above the
 * canvas (the "I still cannot see L190" clipping). Centering on the seed
 * puts what the user searched for on-screen first; panning reveals the rest.
 */
function centerOnSeed(cy) {
  try {
    // Prefer the filter caption (it sits at the loop, inside the seed zone);
    // fall back to the seed chip itself.
    const cap = cy.nodes().filter(n => {
      const d = typeof n.data === 'function' ? n.data() : {};
      return d && d.type === 'caption';
    });
    let first = null;
    if (cap.length) first = typeof cap.eq === 'function' ? cap.eq(0) : cap[0];
    if (!first) {
      const seeds = cy.nodes().filter(n => {
        const d = typeof n.data === 'function' ? n.data() : {};
        return d && d.is_target === true;
      });
      first = seeds && typeof seeds.eq === 'function'
        ? seeds.eq(0)
        : (Array.isArray(seeds) ? seeds[0] : null);
    }
    if (!first) return;
    if (typeof cy.stop === 'function') cy.stop(true);
    if (typeof cy.center === 'function') cy.center(first);
  } catch (_) {
    // best-effort: a fake cy (unit tests) or a torn-down instance must never
    // break the visibility pass — centering is a viewport nicety.
  }
}

export function applyFlowVisibility(
  cy, { flowNodeIds, flowEdgeIds, flowOnly, mergedView, recenter = true } = {}) {
  if (!cy || (typeof cy.destroyed === 'function' && cy.destroyed())) return;
  removeCaptionNodes(cy);
  if (!flowOnly) {
    cy.elements().show();
    if (mergedView) {
      hideEdgelessFieldChips(cy);
      enlargeFilterSelfLoops(cy);
      upsertFilterCaptions(cy);
    }
    return;
  }
  let nodeIds = Array.isArray(flowNodeIds) ? flowNodeIds : [];
  // Edge-only closure: `flowOnly` is truthy but the node set is empty while
  // the edge set is non-empty. The closure nodes are then derived from the
  // closure edges' source/target endpoints (the edge set is part of the same
  // flow closure — `resolveFlowOnly` already returns true for it, so this
  // branch must never fall through to "show the full graph").
  if (nodeIds.length === 0 && Array.isArray(flowEdgeIds) && flowEdgeIds.length > 0) {
    const edgeIdSet = new Set(flowEdgeIds);
    const derived = [];
    cy.edges().forEach(e => {
      const id = typeof e.id === 'function' ? e.id() : e.id;
      if (!edgeIdSet.has(id)) return;
      const srcId = typeof e.data === 'function' ? e.data('source') : undefined;
      const tgtId = typeof e.data === 'function' ? e.data('target') : undefined;
      if (srcId != null) derived.push(srcId);
      if (tgtId != null) derived.push(tgtId);
    });
    nodeIds = derived;
  }
  const nodeSet = new Set(nodeIds);
  const edgeSet = new Set(flowEdgeIds || []);
  cy.nodes().forEach(n => {
    const id = typeof n.id === 'function' ? n.id() : n.id;
    if (nodeSet.has(id)) n.show(); else n.hide();
  });
  cy.edges().forEach(e => {
    const id = typeof e.id === 'function' ? e.id() : e.id;
    const srcId = typeof e.data === 'function' ? e.data('source') : undefined;
    const tgtId = typeof e.data === 'function' ? e.data('target') : undefined;
    const srcVisible = srcId != null
      && cy.getElementById(srcId).length
      && !cy.getElementById(srcId).hidden();
    const tgtVisible = tgtId != null
      && cy.getElementById(tgtId).length
      && !cy.getElementById(tgtId).hidden();
    if (edgeSet.has(id) && srcVisible && tgtVisible) e.show(); else e.hide();
  });
  // #376: merged views additionally drop the field chips the promoted edge
  // set can no longer connect (see hideEdgelessFieldChips).
  if (mergedView) {
    hideEdgelessFieldChips(cy);
    enlargeFilterSelfLoops(cy);
    upsertFilterCaptions(cy);
  }
  // R41: recenter=false (user clicked Fit) skips the seed re-center —
  // the fit's whole-graph viewport must survive the visibility pass.
  if (recenter) centerOnSeed(cy);
}
