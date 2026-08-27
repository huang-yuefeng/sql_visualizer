import React, { useEffect } from 'react';
import { SEARCHED_FIELD_COLOR } from '../utils/graphStyles';

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
 * ALL state lives in DataFlowApp (storyActiveIndex / storyAutoplay) —
 * this component only renders it and ticks the interval. Styling reuses
 * the app's existing toolbar/button classes (`.graph-toolbar`,
 * `.btn .btn-sm .btn-outline .btn-active`); inline styles only where no
 * class fits (the active chip's gold border, the step-title ellipsis).
 * English labels only.
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
}) {
  const list = Array.isArray(steps) ? steps : [];
  const activeStep = activeIndex != null ? list[activeIndex] : undefined;
  const atLast = activeIndex != null && activeIndex >= list.length - 1;

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
    <div className="graph-toolbar" style={{ flexShrink: 0 }}>
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
    </div>
  );
}
