import { describe, it, expect } from 'vitest';
import { resumeLayoutKey } from '../layoutPersistence';

/**
 * #291 / E-M9 (#284) — the layout resume key format.
 *
 * The frontend saves L2 positions under `l2:{script}` (script = currentScriptName)
 * and reads them back with the same key. This helper is the single source of
 * truth for BOTH sides so they can never drift — if the read path and the save
 * path disagree, drags would be saved but never restored.
 */
describe('resumeLayoutKey — #291 L2 drag persistence key format', () => {
  it('maps L1 to the literal "l1" key', () => {
    expect(resumeLayoutKey('l1', null)).toBe('l1');
    expect(resumeLayoutKey('l1', 'anything.sql')).toBe('l1');
  });

  it('maps L2 to "l2:{script}" using the exact script value', () => {
    expect(resumeLayoutKey('l2', 'src/job_a.sql')).toBe('l2:src/job_a.sql');
  });

  it('falls back to "l1" for L2 with a missing/empty script (no live L2)', () => {
    expect(resumeLayoutKey('l2', null)).toBe('l1');
    expect(resumeLayoutKey('l2', '')).toBe('l1');
  });
});
