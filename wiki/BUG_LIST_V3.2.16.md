# Bug List — V3.2.16

## Fixed in V3.2.16

### B6 ✅ Edge colors missing (console warnings) — FIXED
- **Root cause**: Base `edge` selector used `data(color)` mapping, but L1 edges (`reads_from`, `writes_to`) had no `color` data field
- **Fix**: 
  - Base edge now uses default `#5DADE2` color
  - Added `edge[color]` selector for data-driven colors
  - Added `L1_PIPELINE_EDGE_STYLES`: reads_from=blue (#5DADE2), writes_to=green (#27AE60)
- **Verified**: Console warnings reduced from 9 → 1 (only wheel sensitivity info left)

### B7 ✅ Field label overlap — FIXED
- **Root cause**: FIELD_H=40px too small for field labels
- **Fix**: FIELD_H increased to 50px
- Field font-size increased from 8 to 10, color from #f0f0f0 to #ffffff
- Text outline width increased from 2 to 3

### B8 ✅ L2↔SQL resize inverse direction — FIXED
- **Root cause**: `sqlResize` had `invert: true` in DataFlowApp.jsx
- **Fix**: Removed `invert: true` — now drag down = taller SQL panel

### B9 ✅ Structure edges too weak — FIXED
- **Root cause**: Structure edge color #CFD8DC too close to background
- **Fix**: Changed to #AED6F1 with width 2.5

### B10 ✅ L2 edges missing sql_range — FIXED
- **Root cause**: `_estimate_sql_range()` returned None when all strategies failed
- **Fix**: Added ultimate fallback: return full script range [1,1,end,end]

### B11 ✅ Version not updating in browser — FIXED
- **Root cause**: index.html had hardcoded version "3.2.15"
- **Fix**: Updated to "3.2.16"

## Previously Fixed (V3.2.6)

### B1 ✅ Tables overlap — FIXED
### B2 ✅ Empty table fields — FIXED
### B3 ✅ Missing output edges — FIXED
### B4 ✅ L1↔L2 resize handle — FIXED
### B5 ✅ L2↔SQL resize inverse — FIXED (re-fixed in V3.2.16)
