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
 *  - `flow_node_ids` present (matched search) → flow-only ON (default).
 *  - absent (no search seed / search did not match / filter off) → null
 *    (toggle disabled, always show the full graph).
 */
export function resolveFlowOnly(result) {
  return (Array.isArray(result && result.flow_node_ids)
    && result.flow_node_ids.length > 0) ? true : null;
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
  if (!flowOnly || !Array.isArray(flowNodeIds) || flowNodeIds.length === 0) {
    cy.elements().show();
    return;
  }
  const nodeSet = new Set(flowNodeIds);
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
