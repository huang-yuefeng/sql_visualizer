/**
 * Layout-persistence key helpers (R31/A-M5, E-M9/#284, #291).
 *
 * The resume layouts map (`resumeLayouts`) uses one key per level/script:
 *   - L1 → `'l1'`
 *   - L2 → `'l2:{script}'` (script = the L2 script name/path)
 *
 * Both the SAVE path (flushLayoutSave — what the drag just produced) and the
 * READ path (DataFlowGraph `savedPositions`) must derive the key from the
 * SAME helper, so the save key and the read key can never drift — a
 * drag → save → L2 re-open always restores the dragged positions.
 */
export function resumeLayoutKey(level, script) {
  return level === 'l2' && script ? `l2:${script}` : 'l1';
}
