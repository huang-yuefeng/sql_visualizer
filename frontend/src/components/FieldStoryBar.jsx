import React, { useEffect } from 'react';
import { SEARCHED_FIELD_COLOR } from '../utils/graphStyles';
import { formatStringMatchSummary } from '../utils/stringMatch';

/**
 * Field Story step-through bar — presentational (Team B).
 *
 * A slim horizontal toolbar of numbered step chips (1..n) rendered ABOVE
 * the L2 graph area. The ACTIVE chip is gold-bordered — the searched-field
 * gold (SEARCHED_FIELD_COLOR, one token one meaning: "this is the field
 * you traced"); ◀ / ▶ step back and forward; ▶/⏸ toggles autoplay (one
 * step every 3 seconds via a cleaned-up interval — reaching the last step
 * turns autoplay off); ✕ dismisses the story focus (the parent nulls the
 * active index, which clears the graph dimming; the bar itself stays).
 *
 * ALL state lives in DataFlowApp (storyActiveIndex / storyAutoplay, and the
 * R40.13 string-match cursor/visibility) — this component only renders it and
 * ticks the interval. Styling reuses the app's existing toolbar/button classes
 * (`.graph-toolbar`, `.btn .btn-sm .btn-outline .btn-active`); inline styles
 * only where no class fits (the active chip's gold border, the step-title
 * ellipsis, the R40.13 divider). English labels only.
 */
const AUTOPLAY_MS = 3000; // one step every 3 seconds

export default function FieldStoryBar({
  steps,          // [{ id, kind, title, line, edgeIds, nodeIds, detail }]
  activeIndex,    // number | null (null = inactive — nothing lit)
  onStep,         // (i) — chip click
  onPrev,         // () — ◀
  onNext,         // () — ▶ (also the autoplay tick)
  autoplay,       // bool
  onToggleAutoplay, // ()
  onDismiss,      // optional () — ✕
  // ── R40.13: the naive string-match diff layer's browse controls ──────
  stringMatchSummary, // { total, inFlow, notInFlow } | null (null = no
                      // active search → the whole cluster stays unrendered,
                      // INCLUDING a `total: 0` search's absence)
  stringMatchCursor,  // number | null — 0-based, the SEPARATE browse channel
  stringMatchVisible, // bool — the layer's show/hide toggle state
  onToggleStringMatch, // () — show/hide the bands
  onPrevStringMatch,   // (nextIndex) — ◀ (index computed HERE, see below)
  onNextStringMatch,   // (nextIndex) — ▶
}) {
  const list = Array.isArray(steps) ? steps : [];
  const activeStep = activeIndex != null ? list[activeIndex] : undefined;
  const atLast = activeIndex != null && activeIndex >= list.length - 1;

  // ── R40.13 browse arithmetic (the one place the ring rule lives) ──────
  // The match list is a RING, deliberately unlike the story steps above,
  // which clamp and never wrap: ◀ from inactive lands on the LAST match,
  // ▶ from inactive on the FIRST, otherwise ±1 modulo N. The wrapped index
  // is handed to the parent so the callback always carries the index that
  // will become the cursor (DataFlowApp only bounds-checks and stores it).
  const total = stringMatchSummary ? stringMatchSummary.total : 0;
  const hasMatches = Number.isInteger(total) && total > 0;
  const rawCursor = stringMatchCursor;
  const cursor = rawCursor != null && hasMatches
    ? Math.min(Math.max(0, rawCursor), total - 1) // clamp, never guess
    : null;
  const stepTo = (dir) => {
    if (!hasMatches) return null;
    if (cursor == null) return dir > 0 ? 0 : total - 1;
    return ((cursor + dir) % total + total) % total;
  };
  const matchBrowseDisabled = !stringMatchVisible || !hasMatches;
  const counterText = formatStringMatchSummary(stringMatchSummary);

  // Autoplay tick — advance every 3s while playing. The interval is
  // recreated on every activeIndex change, so each step gets its FULL
  // 3 seconds (a manual jump restarts the clock); cleanup clears it on
  // pause, dismiss, and unmount. Reaching the last step turns autoplay
  // off instead of wrapping — a story is walked once, not looped.
  useEffect(() => {
    if (!autoplay || list.length === 0) return;
    const t = setInterval(() => {
      if (activeIndex == null || activeIndex < list.length - 1) onNext?.();
      else onToggleAutoplay?.();
    }, AUTOPLAY_MS);
    return () => clearInterval(t);
  }, [autoplay, activeIndex, list, onNext, onToggleAutoplay]);

  return (
    <div className="graph-toolbar" style={{ flexShrink: 0, flexWrap: 'wrap', rowGap: 4 }}>
      <span className="graph-level-badge">Field story</span>
      {/* Step chips — horizontal scroll when the story is long, never a
          wrap that would grow the bar. */}
      <div style={{ display: 'flex', gap: 4, minWidth: 0, overflowX: 'auto' }}>
        {list.map((s, i) => {
          const isActive = i === activeIndex;
          return (
            <button
              key={s && s.id !== undefined ? s.id : i}
              type="button"
              className={`btn btn-sm ${isActive ? '' : 'btn-outline'}`}
              aria-current={isActive ? 'step' : undefined}
              style={isActive
                ? {
                    borderColor: SEARCHED_FIELD_COLOR,
                    borderWidth: 2,
                    background: 'rgba(255, 215, 0, 0.15)',
                    color: SEARCHED_FIELD_COLOR,
                    minWidth: 26,
                  }
                : { minWidth: 26 }}
              onClick={() => onStep?.(i)}
              title={s && s.title ? `Step ${i + 1}: ${s.title}` : `Step ${i + 1}`}
            >
              {i + 1}
            </button>
          );
        })}
      </div>
      {/* Active step title (or the idle hint) fills the middle; the SQL
          line rides along so the title and the SQL panel agree. */}
      {activeStep ? (
        <span
          title={activeStep.title || ''}
          style={{
            flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap', fontSize: '0.72rem', color: 'var(--ink-600)',
          }}
        >
          {activeStep.title || `Step ${activeIndex + 1}`}
          {Number.isInteger(activeStep.line) && activeStep.line >= 1
            ? ` (L${activeStep.line})` : ''}
        </span>
      ) : (
        <span
          style={{
            flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap', fontSize: '0.72rem', color: 'var(--ink-400)',
          }}
        >
          {list.length} steps - click a number to walk this field's story
        </span>
      )}
      <button type="button" className="btn btn-sm btn-outline"
        onClick={() => onPrev?.()}
        disabled={activeIndex == null || activeIndex === 0}
        title="Previous step" aria-label="Previous step"
      >◀</button>
      <button type="button" className="btn btn-sm btn-outline"
        onClick={() => onNext?.()}
        disabled={atLast}
        title="Next step" aria-label="Next step"
      >▶</button>
      <button type="button" className={`btn btn-sm ${autoplay ? 'btn-active' : 'btn-outline'}`}
        onClick={() => onToggleAutoplay?.()}
        title={autoplay ? 'Pause autoplay' : 'Autoplay (3 seconds per step)'}
        aria-label="Toggle autoplay"
      >{autoplay ? '⏸' : '▶'}</button>
      {onDismiss && (
        <button type="button" className="btn btn-sm btn-outline"
          onClick={onDismiss}
          title="Dismiss story focus" aria-label="Dismiss story focus"
        >✕</button>
      )}
      {/* ── R40.13: the naive string-match diff layer's cluster ─────────
          Renders whenever an L2 search is active (stringMatchSummary
          non-null, including total: 0) even when the script has no story
          steps — the render GATE in DataFlowApp widens for exactly that.
          The counter is the diff summary the feature exists to show, so it
          STAYS visible while the bands are hidden; only ◀/▶ are disabled
          then. Hidden also removes the bands and the active outline (the
          parent passes none while hidden) — the bar only reports the click;
          what the cursor does on activation is the parent's rule (it lands
          the layer back on its FIRST match and re-centers the panel). */}
      {stringMatchSummary != null && (
        <>
          <span aria-hidden="true" className="sm-divider" />
          <button type="button"
            className={`btn btn-sm ${stringMatchVisible ? 'btn-active' : 'btn-outline'}`}
            onClick={() => onToggleStringMatch?.()}
            title={stringMatchVisible ? 'Hide the string-match bands' : 'Show the string-match bands'}
            aria-label="Toggle string-match layer"
            aria-pressed={stringMatchVisible ? 'true' : 'false'}
          >{stringMatchVisible ? '◌' : '○'}</button>
          <span className="sm-counter" title={counterText}>{counterText}</span>
          <button type="button" className="btn btn-sm btn-outline"
            onClick={() => { const i = stepTo(-1); if (i != null) onPrevStringMatch?.(i); }}
            disabled={matchBrowseDisabled}
            title="Previous string match" aria-label="Previous string match"
          >◀</button>
          <span className="sm-readout" aria-label="String match position">
            {cursor == null ? '–' : cursor + 1}/{total}
          </span>
          <button type="button" className="btn btn-sm btn-outline"
            onClick={() => { const i = stepTo(1); if (i != null) onNextStringMatch?.(i); }}
            disabled={matchBrowseDisabled}
            title="Next string match" aria-label="Next string match"
          >▶</button>
        </>
      )}
    </div>
  );
}
