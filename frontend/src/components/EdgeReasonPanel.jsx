import React from 'react';

/**
 * EdgeReasonPanel — R25/§8.8, rendered BELOW the SQL panel in L2.
 *
 * Shows the clicked edge's (a) flow kind, (b) anchor line, and (c) the
 * extraction-time reason string — `<kind> — <flow string>` — with the
 * current edge's own ‖…‖-wrapped segment emphasized (bold + edge color)
 * so the user sees exactly where the clicked edge sits in the flow.
 *
 * The reason string is built at L2 build time from the closure walk and
 * rendered as-is — never reconstructed at render.
 *
 * R11-3 (code evidence): when the edge carries the backend `mech` payload,
 * the panel additionally shows the flow sentence and a clickable
 * "code evidence" block — one row per SQL line (reference site / join-key
 * and value uses / source def), each row jumping the SQL panel to that
 * line via onJumpToLine. Line numbers come from the payload verbatim;
 * sqlText only supplies the display text (never re-derived). Without
 * `mech` the output is exactly the R25 rendering (backward compatible).
 */
export default function EdgeReasonPanel({ edge, sqlText, onJumpToLine }) {
  if (!edge) {
    return (
      <div className="edge-reason-panel edge-reason-empty" data-testid="edge-reason-panel"
        role="status" aria-live="polite">
        <span className="edge-reason-title">Flow Reason</span>
        <span className="edge-reason-hint">Click an edge to see its flow reason</span>
      </div>
    );
  }

  const kind = edge.flow_kind || '';
  const color = edge.color || '#5DADE2';
  const anchor = edge.highlight_line;
  const reason = edge.reason || '';
  const mech = edge.mech;

  // Split on ‖…‖-wrapped segments (the clicked edge's own flow segment).
  const segments = reason.split(/(‖[^‖]*‖)/g).filter(Boolean);

  // ── R11-3 code evidence ──
  // Rows are built from the payload lines (ref_line / use_lines /
  // highlight_line); sqlText is the display-only text source.
  const sqlLines = typeof sqlText === 'string' ? sqlText.split('\n') : null;

  let evidenceRows = [];
  if (mech) {
    const rows = [];
    if (Number.isInteger(mech.ref_line) && mech.ref_line >= 1) {
      rows.push({ line: mech.ref_line, label: `reference site · ${mech.clause || ''}` });
    }
    (Array.isArray(mech.use_lines) ? mech.use_lines : []).forEach(l => {
      if (Number.isInteger(l) && l >= 1) rows.push({ line: l, label: 'join key / value use' });
    });
    if (Number.isInteger(anchor) && anchor >= 1) {
      rows.push({ line: anchor, label: 'def of source' });
    }
    // One row per line — dedupe (a line can serve several roles) + sort.
    const seen = new Set();
    const deduped = [];
    for (const r of rows) {
      if (seen.has(r.line)) continue;
      seen.add(r.line);
      deduped.push(r);
    }
    evidenceRows = deduped.sort((a, b) => a.line - b.line);
  }

  const lineText = (line) =>
    (sqlLines && line >= 1 && line <= sqlLines.length) ? sqlLines[line - 1] : null;

  return (
    <div className={`edge-reason-panel${mech ? ' edge-reason-with-evidence' : ''}`} data-testid="edge-reason-panel"
      role="status" aria-live="polite">
      <span className="edge-reason-title">Flow Reason</span>
      {kind && (
        <span className="edge-reason-kind" style={{ color, borderColor: color }}>
          {kind}
        </span>
      )}
      {Number.isInteger(anchor) && anchor >= 1 && (
        <span className="edge-reason-anchor">Anchor: L{anchor}</span>
      )}
      <div className="edge-reason-text">
        {segments.length > 0 ? segments.map((seg, i) =>
          /^‖.*‖$/.test(seg) ? (
            <strong key={i} className="edge-reason-segment" style={{ color }}>
              {seg.slice(1, -1)}
            </strong>
          ) : (
            <span key={i}>{seg}</span>
          )
        ) : (reason || '—')}
      </div>
      {mech && (
        <div className="edge-reason-mech">
          {mech.sentence && (
            <div className="edge-reason-sentence">{mech.sentence}</div>
          )}
          {evidenceRows.length > 0 && (
            <div className="edge-reason-evidence">
              <span className="edge-reason-evidence-title">Code evidence</span>
              {evidenceRows.map(({ line, label }) => {
                const text = lineText(line);
                return (
                  <button key={line} type="button" data-line={line}
                    className="edge-reason-evidence-row"
                    onClick={() => onJumpToLine?.(line)}>
                    <span className="edge-reason-evidence-label">{label}</span>
                    <span className="edge-reason-evidence-code">
                      L{line}: {text !== null ? text : '(line not available)'}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
