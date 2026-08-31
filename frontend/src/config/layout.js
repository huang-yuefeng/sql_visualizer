/**
 * Layout Configuration — SINGLE SOURCE OF TRUTH
 * All layout constants live here. No other file hardcodes these values.
 */

// ── Cytoscape fit ──────────────────────────────────────────────────
// The margin around a fitted graph is dead space — every pixel of padding
// shrinks the rendered content. History: 200 (huge empty band) → 60 → 24.
// L2 additionally adapts down via Math.max(16, panelW*0.05) in the callers.
export const FIT_PADDING = 24;

// ── FIT-only zoom exception (FTC E2E, user ruling 2026-08-31) ──────
// The runtime minZoom (0.08) bounds MANUAL zooming: below it labels are
// boxes-only anyway (min-zoomed-font-size keeps them at a 6px floor), so
// letting the user shrink further only buys unreadable mush. But a FIT must
// SHOW THE WHOLE GRAPH: a tall L2 closure (tpcds q14 → item.i_brand_id) needs
// ~0.05x in a 420px panel, and clamping at 0.08 left 26–121px of the closure
// overflowing the viewport in 6/9 audited cases.
//
// So a FIT temporarily lifts the floor, fits exactly, then restores it. The
// fitted zoom survives (cytoscape only clamps on zoom operations, not on a
// minZoom write), while the user's own wheel/pinch zoom still bottoms out at
// the runtime floor. EVERY "fit the whole graph" site goes through this —
// never a manual zoom.
export const FIT_ONLY_MIN_ZOOM = 0.01;

export function fitWholeGraph(cy, pad = 50, eles) {
  if (!cy || cy.destroyed()) return undefined;
  const floor = cy.minZoom();
  cy.minZoom(FIT_ONLY_MIN_ZOOM);
  try {
    if (eles && typeof eles.length === 'number' && eles.length > 0) cy.fit(eles, pad);
    else cy.fit(undefined, pad);
  } finally {
    cy.minZoom(floor);
  }
  return cy.zoom();
}

// ── Compound node sizing (tables contain fields) ───────────────────
export const TABLE_HDR_H = 26;
export const FIELD_RENDER_H = 28;
export const FIELD_H = 52;          // center-to-center spacing
export const FIELD_GAP = FIELD_H - FIELD_RENDER_H;  // 24px
export const TABLE_MIN_H = 80;
export const TABLE_DEFAULT_W = 200;
export const TBL_W = TABLE_DEFAULT_W;   // alias
export const TBL_HDR = TABLE_HDR_H;     // alias
export const TBL_MIN_H = TABLE_MIN_H;   // alias

// ── Snake / workflow layout ────────────────────────────────────────
export const SNAKE_ROW_HEIGHT = 300;
export const SNAKE_NODE_SPACING = 500;
export const SNAKE_MAX_PER_ROW = 2;
export const SNAKE_START_X = 80;
export const SNAKE_START_Y = 80;

// ── ELK / pipeline layout ──────────────────────────────────────────
export const ELK_SPACING_NODE = 500;      // Must exceed compound max-width (300) to prevent overlaps
export const ELK_SPACING_LAYER = 400;     // Increased inter-layer spacing
export const ELK_COMPOUND_MAX_W = 300;    // Reduced from 400 to better match rendered table width (200px)
export const ELK_DIRECTION = 'RIGHT';
export const ELK_ALGORITHM = 'layered';


// ── Table padding ──────────────────────────────────────────────────
export const TBL_PAD_TOP = 14;
export const TBL_PAD_BOT = 14;

// ── CSS selectors ──────────────────────────────────────────────────
export const TABLE_SELECTOR = '[type$="_table"], [type="query_output"], [type="cte_table"]';
export const FIELD_SELECTOR = '[type="field"]';

// ── Node default dimensions ────────────────────────────────────────
export const SCRIPT_NODE_W = 190;
export const SCRIPT_NODE_H = 55;
export const SCRIPT_W = SCRIPT_NODE_W;  // alias
export const SCRIPT_H = SCRIPT_NODE_H;  // alias
export const FIELD_NODE_W = 60;
export const FIELD_NODE_H = 34;
