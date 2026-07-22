# Bug List — V3.2.6

## B1 ✅ Tables overlap in top-left corner — FIXED
- **Root cause**: ELK.js not positioning nodes; backend returned (0,0) for all
- **Fix**: Backend now assigns default pipeline-layer positions (x=layer*280, y=index*100) 
  so nodes never overlap even without layout engine
- **Verified**: 0 overlapping nodes with multi_workflow test

## B2 ✅ analytics_orders + daily_summary have 0 fields — FIXED
- **Root cause**: Extractor assigns columns to source tables via aliases; 
  output/intermediate tables get no field variables
- **Fix**: After direct field enrichment, propagate fields: 
  for table B with 0 fields, find producer scripts, inherit fields from their input tables.
  Cascading propagation (analytics_orders → daily_summary) now works
- **Verified**: analytics_orders=8 fields, daily_summary=8 fields

## B3 ✅ Missing script→table output edges — FIXED
- **Root cause**: Only table→script "table_script" edges existed (undirected)
- **Fix**: Split into `reads_from` (table→script) and `writes_to` (script→table) edges
- **Verified**: reads_from=6, writes_to=4 in multi_workflow

## B4 ✅ L1↔L2 panel border cannot be dragged — FIXED
- **Root cause**: Resize handle too narrow (6px) and invisible
- **Fix**: 8px wide, visible background (#2a2a4a), 16px hit area via ::after pseudo-element.
  SQL panel uses inline `style={{ height }}` instead of CSS variable
- **Verified**: Resize CSS/JS present in built bundle

## B5 ✅ L2↔SQL border moves inverse direction — FIXED
- **Root cause**: `startValueRef` was stale (set once at mount, not tracking current value)
- **Fix**: Added `valueRef` that tracks current `defaultValue`, used in mousedown handler
- **Verified**: Resize hook code present in built JS bundle
