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
export function fitAllElements(cy, { flowOnly, flowNodeIds, flowEdgeIds, mergedView } = {},
  padding = 50) {
  if (!cy || (typeof cy.destroyed === 'function' && cy.destroyed())) return;
  cy.elements().show();
  cy.fit(undefined, padding);
  applyFlowVisibility(cy, { flowOnly, flowNodeIds, flowEdgeIds, mergedView });
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
 * table-level, so an untouched field node would render as a floating orphan).
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
      const id = typeof n.id === 'function' ? n.id() : n.id;
      if (!linked.has(id)) n.hide();
    });
  };
  if (typeof cy.batch === 'function') cy.batch(prune); else prune();
}

/**
 * v3.3.183 — make absorbed FILTER edges BIG and readable in merged views.
 *
 * R32 promotion collapses `p_dt ──FILTER──► east5` into an `east5→east5`
 * self-loop that renders ~5x5 px at the zoom floor, and cytoscape paints
 * edge labels BENEATH node fills — so the single most important edge of a
 * search was effectively invisible (user-verified three times). Fix, purely
 * client-side:
 *   1. Enlarge every visible merged self-loop (control-point-distances),
 *      thicken it, and give its label an above-box text treatment.
 *   2. Pin a CAPTION NODE at the loop midpoint — nodes paint above
 *      everything, so the caption is deterministically visible. The node is
 *      `synthetic`: non-interactive (`events: 'no'`), excluded from layout
 *      persistence (collectPositions skips type 'caption'), and removed/
 *      re-created on every visibility pass so it can never leak.
 */
function enlargeFilterSelfLoops(cy) {
  // v3.3.185: runtime e.style() is a silent no-op — tag the edge and let the
  // stylesheet (FILTER_SELFLOOP_STYLES, data-driven segment-points) draw a
  // big polygonal loop OUTSIDE the box.
  cy.edges().forEach(e => {
    try {
      const d = (typeof e.data === 'function' ? e.data() : e.data) || {};
      const isSelf = d.source != null && d.source === d.target;
      if (!isSelf || (typeof e.hidden === 'function' && e.hidden())) return;
      const pts = [[-460, -330], [-580, 0], [-460, 330]];
      if (typeof e.data === 'function') e.data('segp', pts);
      if (typeof e.addClass === 'function') e.addClass('filter-selfloop');
    } catch (_) { /* fake cy in unit tests — best-effort */ }
  });
}

function removeCaptionNodes(cy) {
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
      if (typeof e.midpoint !== 'function') return; // fake edge — skip
      const id = 'cap_' + (typeof e.id === 'function' ? e.id() : e.id);
      // Caption text is model-space too — compensate for zoom so it stays
      // ~14 screen px (readable) at the 0.28 floor and modest when zoomed in.
      const fs = 12; // v3.3.185: same tier as table titles ("as big as others")
      if (!cy.getElementById(id).length) {
        cy.add({
          data: { id, label, type: 'caption', synthetic: true },
          position: e.midpoint(),
          classes: 'filter-caption',
        });
      } else {
        cy.getElementById(id).position(e.midpoint());
      }
      const cap = cy.getElementById(id);
      if (typeof cap.style === 'function') {
        try { cap.style({ 'font-size': fs }); } catch (_) {}
      }
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

export function applyFlowVisibility(cy, { flowNodeIds, flowEdgeIds, flowOnly, mergedView } = {}) {
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
  centerOnSeed(cy);
}
