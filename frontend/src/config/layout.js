/**
 * Layout Configuration — SINGLE SOURCE OF TRUTH
 * All layout constants live here. No other file hardcodes these values.
 */

// ── Cytoscape fit ──────────────────────────────────────────────────
// 200 left a huge empty band around the fitted graph (the poster shrank to
// make room for a margin nobody asked for). 60 keeps breathing room while
// spending the window on content. L2 additionally adapts down via
// Math.max(30, panelW*0.07) in the callers — unchanged.
export const FIT_PADDING = 60;

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
