/**
 * R27 — L2 label decoration: "@L{line}" after node names (2026-08-11).
 *
 * Display-only projection of the payload: append `@L{line_start}` to a
 * node's RENDERED label (the payload label is untouched — canonical node
 * realization matches payload labels; display = pure projection, J12-10).
 *
 * Rules:
 *   - append only when the label does NOT already end with `@<digits>`
 *     (alias display labels like `p1@29` come from the backend — never
 *     double-append, no `@29@29`). Labels already carrying `@L<digits>`
 *     are treated the same (idempotent).
 *   - append only when `line_start` is a valid integer ≥ 1 — nodes
 *     without a valid line (e.g. L1 nodes, fields without a def line)
 *     pass through unchanged; the renderer never guesses.
 *   - compounds show their carried keeper/first-occurrence line_start;
 *     per-occurrence lines stay on the edges (R25, documented
 *     limitation).
 */
export function decorateLabelWithLine(label, lineStart) {
  if (typeof label !== 'string' || label === '') return label;
  if (!Number.isInteger(lineStart) || lineStart < 1) return label;
  // v3.3.188 FIX (review HIGH, corroborated live as `tbl@L41\nT@L41\nT`):
  // idempotence must hold PER LINE, not at the string end — compound
  // labels carry extra lines (role badges like "\nT"), so the old
  // end-of-string guard missed an existing decoration and appended
  // again. Strip any stale `@L<digits>` token anywhere, then append
  // once to the FIRST line. `p1@29`-style ALIAS labels (no "L") are
  // still left untouched — that suffix is the backend's alias-line
  // display convention, not ours to rewrite.
  const first = label.split('\n')[0];
  if (/@\d+$/.test(first)) return label;
  const cleaned = label.replace(/@L\d+/g, '');
  const lines = cleaned.split('\n');
  lines[0] = lines[0].replace(/\s+$/, '') + `@L${lineStart}`;
  return lines.join('\n');
}
