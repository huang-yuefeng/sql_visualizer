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
 * Fit the VISIBLE closure (user ruling 2026-09-02, amending E-M8/#283 —
 * the Full view is cut from the requirement). Applies the flow visibility
 * pass first, then `cy.fit` over `:visible` elements only, so the viewport
 * frames exactly what the user sees — never a layout, so node positions
 * stay byte-identical. (The old order — show everything, fit the FULL
 * model, re-hide — zoomed out over the hidden elements' space, which no
 * user can reach any more; with COMPACT's box compaction the visible
 * bounds are the whole story.)
 */
export function fitVisibleElements(cy, { flowOnly, flowNodeIds, flowEdgeIds, mergedView, recenter } = {},
  padding = 50) {
  if (!cy || (typeof cy.destroyed === 'function' && cy.destroyed())) return;
  // FLOW-ONLY-ONLY (user ruling 2026-09-02, amending E-M8/#283): the Full
  // view is cut from the requirement, so Fit frames the VISIBLE closure —
  // apply the visibility pass FIRST, then fit only what is shown. The old
  // order (fit the FULL model, then hide) zoomed out over the hidden
  // elements' space, which no user can reach any more. With COMPACT's box
  // compaction the visible bounds are the whole story.
  applyFlowVisibility(cy, { flowOnly, flowNodeIds, flowEdgeIds, mergedView, recenter });
  cy.fit(cy.elements(':visible'), padding);
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
 * v3.3.183 (updated v3.3.191, captions retired v3.3.194) — make absorbed
 * FILTER edges BIG and readable in merged views.
 *
 * R32 promotion collapses `p_dt ──FILTER──► east5` into an `east5→east5`
 * self-loop that renders ~5x5 px at the zoom floor, and cytoscape paints
 * edge labels BENEATH node fills — so the single most important edge of a
 * search was effectively invisible (user-verified three times). Fix, purely
 * client-side:
 *   1. Tag every visible merged self-loop with `filter-selfloop` — the
 *      stylesheet (FILTER_LOOP_GEOM_STYLES) then draws it as an enlarged
 *      bezier loop hugging the table's LEFT border in the uniform edge
 *      style (no special color — user ruling 2026-09-02; per-edge
 *      control-point-step-size data + loop-direction data). The edge
 *      itself is the visible, clickable curve: its tap highlights the
 *      absorbed SQL line (R37), and the Field Story "Filtered" step names
 *      the same line.
 *   2. (RETIRED v3.3.194 — user ruling 2026-08-31.) This pass used to ALSO
 *      pin a `⟂ field (filtered @L<line>)` caption NODE at the loop
 *      midpoint. That text was already painted a second time by the
 *      FILTER_SELFLOOP_STYLES edge-label rule, and because the enlarged
 *      loop's midpoint sits OUTSIDE the table box, neither copy was hidden
 *      by a node fill — the user saw the SAME caption twice on one loop
 *      (`east5_stzfxxb.p_dt`: one merged self-loop `l2m_…` @190, two
 *      identical `⟂ p_dt (filtered @L190)` texts). The loop line is now the
 *      loop's only on-canvas form; the line number travels through the
 *      click channel (R37) and the Field Story, not through a caption.
 */
// v3.3.191 — target bulge of the self-loop arc PAST the table's left border,
// in model units. cytoscape scales a self-loop from the node CENTRE (ctrl
// pts = centre ± 1.4 × step along the loop axis; with direction -90deg/sweep
// -90deg the horizontal control-point reach is ≈ 0.99 × step), so a fixed
// step that clears a small chip disappears inside a wide table box — hence
// the per-edge measurement below.
//
// Measured with the real renderer (cytoscape 3.34, headless canvas pass over
// `edge.controlPoints()`, node w=200 → halfW=100 → step=250): the control
// points sit 147.5 model units left of the border and the drawn curve
// reaches 110.6 units past it — i.e. visible bulge ≈ 0.7425 × step −
// 0.75 × halfW ≈ 0.7425 × SELFLOOP_BULGE, independent of box size (the
// halfW terms cancel: that is the point of the per-edge step). Screen size
// over the merged view's working zoom range: 31 px @0.28, 17 px @0.15,
// 8.9 px @0.08 — readable and hittable at the fit floor, so the constant
// stays 150; growing it would buy nothing at the floor and would start
// swallowing the neighbour box to the left at working zooms.
const SELFLOOP_BULGE = 150;

// v3.3.194 — parallel self-loops on ONE table (the full-merged view can put
// 2-3 absorbed filters on the same box, e.g. @52/@84/@99) used to draw the
// same left-border arc. They never coincide exactly — cytoscape's
// findLoopPoints nests loops that share a direction+sweep key by (j/3 + 1) on
// the STEP, so consecutive loops draw 62 model units farther out (measured
// bulges 110.6 / 172.5 / 234.4 for three loops at step 250) — but that 62-unit
// gap is ~17 px at the 0.28 fit floor and ~5 px at the 0.08 overview floor,
// where the arcs read as one thick line. Smallest robust fix: alternate the
// loop AXIS (left / right border) inside each node group, so the first two
// loops are mirror images with zero interaction — each is the only loop in its
// own direction+sweep group, hence no nesting compounding and no dependence on
// cytoscape's internal render order. A 3rd loop returns to the first side and
// nests 62 units outside it. (A per-index `loopstep` increment was rejected:
// it multiplies with that same (j/3 + 1) factor, so if the two orders ever
// disagree the "bigger" loop renders inside the smaller one.)
const SELFLOOP_LEFT = '-90deg';
const SELFLOOP_RIGHT = '90deg';
const SELFLOOP_DIRECTIONS = [SELFLOOP_LEFT, SELFLOOP_RIGHT];

// WHICH border is free is measured, not assumed: cytoscape paints edges below
// nodes, so the axis is the only lever against occlusion. H2 pixel-counted
// this exact case (east5_stzfxxb, Full/merged): a loop pushed to the RIGHT
// border by blind alternation rendered BEHIND the neighbouring alias box —
// 377 visible reddish px against 2730 for its left sibling (~7x suppressed,
// reads as a muted mauve arc). So the pass scores both borders — per table
// box, the band being a property of the border rather than of the loop — and
// then assigns loops to borders by TOTAL visibility (v3.3.195, below); the
// LABELLED loop (`data.filterLabel` — the absorbed-filter loop) anchors the
// freer border in every candidate assignment:
//   1. neighbour boxes overlapping the arc band (x within SELFLOOP_BULGE of
//      the border, y within the arc's vertical span ≈ ±0.99 × step) — nodes
//      paint ABOVE edges, so these are the real occluders;
//   2. then ordinary (non-self-loop) incident edges attaching there — a
//      neighbour whose centre sits on that side attaches at that border, and
//      its 2px line crosses the band.
//
// v3.3.195 — the per-border score feeds a per-GROUP ASSIGNMENT OPTIMUM, not
// blind alternation. The v3.3.194 rule ("labelled loop takes the freer border,
// siblings alternate away") fixed the nesting complaint but manufactured a new
// one, measured on this very table: the labelled @190 loop won LEFT (88.6% of
// its stroke visible) while its unlabelled @86 sibling was FORCED to the RIGHT
// border — where the band holds bdm_acc_entrusted_payment — for 14.3%. Both
// loops on the freer border would have kept both arcs alive; the TOTAL is what
// matters, so for a two-loop table the candidate assignments are compared and
// the cheaper wins (three or more loops keep the alternation fallback):
//   alternate     — each loop on its own border (no nesting; but the second
//                   loop may be thrown into an OCCUPIED border)
//   all-preferred — every loop on the freer border (cytoscape nests same-side
//                   loops +62 model units per extra loop: crowded, yet every
//                   arc stays in the free band)
// Costs are normalized to one loop's value (1.0 = a fully visible stroke):
//   BAND_BOX_COST      0.70 per occluding box in the band — measured: the
//                      occluded loop keeps ~14% of its stroke against ~89%
//                      for a free-border sibling, i.e. ~0.7 of the arc is lost;
//   BAND_EDGE_COST     0.05 per crossing edge, capped at BAND_EDGE_CAP (0.20)
//                      so a busy border can never outrank an occluding box —
//                      the old lexicographic boxes-before-edges order, kept as
//                      weights;
//   SHARED_BORDER_COST 0.30 per EXTRA loop on a border — the nesting cost
//                      (both arcs survive, 62 model units apart, but at the
//                      fit floor they read as one thick line).
// 0.30 < 0.70 is the whole optimizer: a SHARED free border beats a private
// occupied one, while two free borders still separate (a strict tie keeps
// alternation — v3.3.194's no-share rule survives wherever it is free). The
// labelled loop (`data.filterLabel`) anchors the freer border either way, and
// placement order stays the deterministic line-then-id sort below.
const BAND_BOX_COST = 0.7;
const BAND_EDGE_COST = 0.05;
const BAND_EDGE_CAP = 4;
const SHARED_BORDER_COST = 0.3;

/** Cost of drawing ONE loop on `side`, in fractions of a visible loop. */
function bandCost(score, side) {
  const nodes = side === 'left' ? score.leftNodes : score.rightNodes;
  const edges = side === 'left' ? score.leftEdges : score.rightEdges;
  return BAND_BOX_COST * nodes + BAND_EDGE_COST * Math.min(BAND_EDGE_CAP, edges);
}

function borderScore(cy, nodeId, halfW, step) {
  const score = { leftNodes: 0, rightNodes: 0, leftEdges: 0, rightEdges: 0 };
  try {
    const coll = typeof cy.getElementById === 'function'
      ? cy.getElementById(nodeId) : null;
    const node = coll && coll.length ? coll[0] : null;
    if (!node || typeof node.position !== 'function') return score;
    const c = node.position();
    const halfArc = 0.99 * step; // arc vertical half-span (ctrl pts at ±0.99·step)
    const bands = [
      { side: 'left', x1: c.x - halfW - SELFLOOP_BULGE, x2: c.x - halfW },
      { side: 'right', x1: c.x + halfW, x2: c.x + halfW + SELFLOOP_BULGE },
    ];
    const y1 = c.y - halfArc, y2 = c.y + halfArc;
    // 1. boxes painting above the band (strict inequalities exclude the table
    //    itself, whose border IS a band edge).
    if (typeof cy.nodes === 'function') {
      cy.nodes().forEach(n => {
        try {
          if (typeof n.hidden === 'function' && n.hidden()) return;
          if (typeof n.boundingBox !== 'function') return;
          const b = n.boundingBox({ includeLabels: false, includeNodes: true,
            includeEdges: false, includeOverlays: false });
          if (!b) return;
          for (const band of bands) {
            if (b.x1 < band.x2 && b.x2 > band.x1 && b.y1 < y2 && b.y2 > y1)
              score[`${band.side}Nodes`] += 1;
          }
        } catch (_) { /* skip an unsized/fake node */ }
      });
    }
    // 2. ordinary edges whose other endpoint faces that border.
    if (typeof node.connectedEdges === 'function') {
      node.connectedEdges().forEach(e => {
        try {
          const d = (typeof e.data === 'function' ? e.data() : e.data) || {};
          if (d.source == null || d.source === d.target) return;
          if (typeof e.hidden === 'function' && e.hidden()) return;
          const otherId = d.source === nodeId ? d.target : d.source;
          const oc = typeof cy.getElementById === 'function'
            ? cy.getElementById(otherId) : null;
          const other = oc && oc.length ? oc[0] : null;
          if (!other || typeof other.position !== 'function') return;
          const dx = other.position().x - c.x;
          // A vertically aligned neighbour attaches at the top/bottom border
          // (snake columns) and never crosses a side arc — occupies neither.
          if (dx < -1) score.leftEdges += 1;
          else if (dx > 1) score.rightEdges += 1;
        } catch (_) { /* best-effort */ }
      });
    }
  } catch (_) { /* fake cy in unit tests — both borders score 0 → LEFT */ }
  return score;
}

/**
 * v3.3.195 — the (loop → border) assignment for ONE table's self-loops.
 *
 * `score` is the border score of the table box (every loop on that box shares
 * it — the band is a property of the border, not of the loop), `anchor` the
 * index of the labelled loop (the loop that must get the freer border), and
 * the costs are bandCost() per side. Returns one loop-direction per loop.
 *
 * Two assignments are compared by summed cost over the whole group — exact for
 * two loops; three or more keep the plain alternation (the greedy fallback the
 * spec keeps beyond the first pair, because a deeper same-side nest reaches
 * outside the band the score measures):
 *   alternate: the anchor loop takes the freer border, every other loop
 *              alternates away from it → Σ preferred/other cost by parity;
 *   share:     every loop takes the freer border → n × preferredCost plus one
 *              SHARED_BORDER_COST per extra loop (the cytoscape nesting).
 * A strict tie answers `alternate`: two free borders must still separate, and
 * an uncluttered table (0/0 both sides) always does.
 */
function assignLoopSides(score, anchor, loopCount) {
  const leftCost = bandCost(score, 'left');
  const rightCost = bandCost(score, 'right');
  // Strict tie → LEFT: the side the tool has used since v3.3.191 and the
  // Flow-only case's side.
  const preferred = leftCost <= rightCost ? SELFLOOP_LEFT : SELFLOOP_RIGHT;
  const other = preferred === SELFLOOP_LEFT ? SELFLOOP_RIGHT : SELFLOOP_LEFT;
  const preferredCost = Math.min(leftCost, rightCost);
  const otherCost = Math.max(leftCost, rightCost);

  let alternateCost = 0;
  for (let i = 0; i < loopCount; i++)
    alternateCost += (i - anchor) % 2 === 0 ? preferredCost : otherCost;
  const shareCost = loopCount * preferredCost
    + SHARED_BORDER_COST * (loopCount - 1);
  // Sharing is decided only where the comparison is EXACT: two loops. Three
  // or more keep the v3.3.194 alternation (the greedy fallback) — a third
  // same-side loop nests another 62 model units out, a reach the two-band
  // score cannot see, so a deeper nest is never bought by this rule.
  const share = loopCount === 2 && shareCost < alternateCost;

  return Array.from({ length: loopCount }, (_v, i) =>
    (share || (i - anchor) % 2 === 0) ? preferred : other);
}

function enlargeFilterSelfLoops(cy) {
  // v3.3.191: tag the edge and let the stylesheet draw the big curve. The
  // v3.3.185 `data.segp` + `segment-points` hack never worked — cytoscape
  // 3.34 has no `segment-points` property (the parsed stylesheet drops it
  // silently), and a self-edge's geometry comes from findLoopPoints
  // (control-point-step-size / loop-direction / loop-sweep) whatever
  // curve-style says, so the loop rendered at the 40-unit default: 8×8 px
  // at the 0.28 zoom floor. FILTER_LOOP_GEOM_STYLES maps this class to the
  // loop properties with a per-edge `loopstep` sized from the endpoint box.
  // v3.3.194: the pass also assigns the per-loop axis (`loopdir`). v3.3.195:
  // the axis comes from the group's assignment optimum (assignLoopSides) —
  // the LABELLED loop anchors the freer border and the group shares that
  // border only when the opposite one is occupied (see borderScore).
  const groups = new Map(); // endpoint id → visible self-loops on that table
  cy.edges().forEach(e => {
    try {
      const d = (typeof e.data === 'function' ? e.data() : e.data) || {};
      const isSelf = d.source != null && d.source === d.target;
      if (!isSelf || (typeof e.hidden === 'function' && e.hidden())) return;
      let g = groups.get(d.source);
      if (!g) groups.set(d.source, (g = []));
      g.push(e);
    } catch (_) { /* fake cy in unit tests — best-effort */ }
  });
  groups.forEach((loops, nodeId) => {
    try {
      // Deterministic placement: line order, then id (never payload order).
      loops.sort((a, b) => {
        const la = Number(a.data('highlight_line')) || 0;
        const lb = Number(b.data('highlight_line')) || 0;
        if (la !== lb) return la - lb;
        const ia = String(a.id() ?? ''), ib = String(b.id() ?? '');
        return ia < ib ? -1 : ia > ib ? 1 : 0;
      });
      let halfW = 60; // sane floor for bare/fake nodes in unit tests
      try {
        const coll = typeof cy.getElementById === 'function'
          ? cy.getElementById(nodeId) : null;
        const node = coll && coll.length ? coll[0] : null;
        const nb = node && typeof node.boundingBox === 'function'
          ? node.boundingBox({ includeLabels: false, includeNodes: true,
            includeEdges: false, includeOverlays: false })
          : null;
        if (nb && Number.isFinite(nb.w)) halfW = Math.max(20, nb.w / 2);
      } catch (_) { /* keep the floor */ }
      const step = Math.round(halfW + SELFLOOP_BULGE);
      // The labelled loop anchors the freer border; the assignment then puts
      // the group where the total visibility is highest (see assignLoopSides).
      let anchor = loops.findIndex(e => {
        try { const d = e.data(); return !!(d && d.filterLabel); }
        catch (_) { return false; }
      });
      if (anchor < 0) anchor = 0;
      const sides = assignLoopSides(
        borderScore(cy, nodeId, halfW, step), anchor, loops.length);
      loops.forEach((e, i) => {
        try {
          // data FIRST, then the class — the mapping resolves on the style
          // recalc that follows this batch, so no missing-field warning fires.
          if (typeof e.data === 'function') {
            e.data({ loopstep: step, loopdir: sides[i] });
          }
          if (typeof e.addClass === 'function') e.addClass('filter-selfloop');
        } catch (_) { /* fake edge in unit tests — best-effort */ }
      });
    } catch (_) { /* best-effort chrome — never break the visibility pass */ }
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
    // The searched seed chip (it sits inside its table box, next to the
    // loop). Until v3.3.194 this preferred the retired caption node — that
    // preference is gone with the caption.
    const seeds = cy.nodes().filter(n => {
      const d = typeof n.data === 'function' ? n.data() : {};
      return d && d.is_target === true;
    });
    const first = seeds && typeof seeds.eq === 'function'
      ? seeds.eq(0)
      : (Array.isArray(seeds) ? seeds[0] : null);
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
  if (!flowOnly) {
    cy.elements().show();
    if (mergedView) {
      hideEdgelessFieldChips(cy);
      enlargeFilterSelfLoops(cy);
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
  }
  // R41: recenter=false (user clicked Fit) skips the seed re-center —
  // the fit's whole-graph viewport must survive the visibility pass.
  if (recenter) centerOnSeed(cy);
}
