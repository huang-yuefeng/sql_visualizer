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
export function fitAllElements(cy, { flowOnly, flowNodeIds, flowEdgeIds } = {}, padding = 50) {
  if (!cy || (typeof cy.destroyed === 'function' && cy.destroyed())) return;
  cy.elements().show();
  cy.fit(undefined, padding);
  applyFlowVisibility(cy, { flowOnly, flowNodeIds, flowEdgeIds });
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
 * Pure visibility — calls only cytoscape `.show()` / `.hide()`, never a
 * layout, so positions are preserved across toggles.
 */
export function applyFlowVisibility(cy, { flowNodeIds, flowEdgeIds, flowOnly } = {}) {
  if (!cy || (typeof cy.destroyed === 'function' && cy.destroyed())) return;
  if (!flowOnly) {
    cy.elements().show();
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
}
