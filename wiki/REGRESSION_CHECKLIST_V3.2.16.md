# Regression Checklist — V3.2.16

> Last updated: 2026-07-20
> Based on bug history from V3.2.6 and V3.2.15

## How to use
Each item must pass in both **L1 graph** and **L2 graph** modes with `multi_workflow` test data.

---

## B1: Table node overlap
- [ ] L1: No two table nodes overlap each other
- [ ] L2: No two table nodes overlap each other

## B2: Fields in tables
- [ ] L1: Every table on data flow path has >=1 field visible
- [ ] L2: Every table on data flow path has >=1 field visible

## B3: Script→table output edges
- [ ] L1: Every script node has at least one `writes_to` edge (green arrow) to an output table

## B4: L1↔L2 panel resize
- [ ] Drag handle left → L2 panel gets wider
- [ ] Drag handle right → L2 panel gets narrower

## B5: L2↔SQL panel resize
- [ ] Drag handle down → SQL panel gets taller
- [ ] Drag handle up → SQL panel gets shorter

## B6: Edge colors visible
- [ ] L1: All edges visible with clear colors (blue=reads_from, green=writes_to)
- [ ] L2: All edges visible with category colors
- [ ] Console: 0 "missing color" warnings

## B7: Field overlap within tables
- [ ] L1: Field labels do not overlap within the same table
- [ ] L2: Field labels do not overlap within the same table

## B8: Field nodes within table bounds
- [ ] L1: All field nodes are contained within their parent table boundary
- [ ] L2: All field nodes are contained within their parent table boundary

## B9: Edge click → SQL highlight
- [ ] L2: Clicking any edge shows corresponding SQL segment in SQL panel
- [ ] L2: SQL panel highlights the relevant lines

## B10: Drag table → fields move together
- [ ] L1: Dragging a table node moves all its child fields
- [ ] L2: Dragging a table node moves all its child fields

## B11: L2 on right of L1 (not below)
- [ ] At 1440px+ viewport: L2 panel appears to the RIGHT of L1 (not below)

## B12: Version
- [ ] API health endpoint returns "3.2.16"
- [ ] Browser meta tag shows "3.2.16"

## B13: SQL export config
- [ ] Click ⚙ Config → 10 toggleable options visible
- [ ] Upload JSON config → config values update
- [ ] Export SQL → downloads .sql file with correct config

## B14: File tree
- [ ] Upload .zip → hierarchical tree shows SQL files clickable
- [ ] Non-SQL files grayed out
- [ ] Checkboxes work for selection/deselection

## B15: Autocomplete
- [ ] Table autocomplete shows color-coded suggestions
- [ ] Field autocomplete filters by selected table

## Summary
| Date | Tester | Pass/Fail | Notes |
|------|--------|-----------|-------|
| 2026-07-20 | Auto | Pending | V3.2.16 initial |
