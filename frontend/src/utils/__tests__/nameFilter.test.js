import { describe, it, expect } from 'vitest';
import { filterNames, levenshteinLe1 } from '../nameFilter';

describe('levenshteinLe1', () => {
  it('is true for equal strings', () => {
    expect(levenshteinLe1('east5_stzfxxb', 'east5_stzfxxb')).toBe(true);
  });

  it('is true for one insertion (case1: extra S)', () => {
    expect(levenshteinLe1('east5_stzfxxb', 'east5_sstzfxxb')).toBe(true);
  });

  it('is true for one deletion and one substitution', () => {
    expect(levenshteinLe1('stzfje', 'stzfja')).toBe(true);
    expect(levenshteinLe1('abc', 'ab')).toBe(true);
  });

  it('is false for distance 2', () => {
    expect(levenshteinLe1('stzfje', 'stzjfe')).toBe(false);
    expect(levenshteinLe1('east5_stzfxxb', 'east5_sstzfxxc')).toBe(false);
  });
});

describe('filterNames', () => {
  const names = [
    'east5_stzfxxb',
    'east5_stzfxxb_old',
    'stzfje',
    'STZFJE_A',
    'LENDING_REF',
    'stzfxxb_bak',
  ];

  it('returns first 20 (alphabetical) for empty query', () => {
    expect(filterNames(names, '')).toEqual(names.slice(0, 20));
  });

  it('substring primary: two hits → no typo fallback', () => {
    const out = filterNames(names, 'stzfje');
    expect(out).toContain('stzfje');
    expect(out).toContain('STZFJE_A');
    expect(out).not.toContain('east5_stzfxxb'); // distance-2, not a substring
  });

  it('typo fallback surfaces the one-char-off name (case1 shape)', () => {
    // query has an extra S vs the real table name — substring gives 0 hits
    const out = filterNames(names, 'east5_sstzfxxb');
    expect(out).toContain('east5_stzfxxb');
  });

  it('single substring hit keeps the typo neighbour after it', () => {
    // query is one char off the real name AND a substring of a padded twin:
    // substring returns 1 hit, the distance-1 fallback adds the real name
    const out = filterNames(['EAST5_SSTZFXXB_PAD', 'east5_stzfxxb'], 'EAST5_SSTZFXXB');
    expect(out[0]).toBe('EAST5_SSTZFXXB_PAD'); // substring hit first
    expect(out).toContain('east5_stzfxxb');    // distance-1 neighbour appended
  });

  it('caps at 20', () => {
    const many = Array.from({ length: 50 }, (_, i) => `field_${i}`);
    expect(filterNames(many, 'field').length).toBe(20);
    expect(filterNames(many, '').length).toBe(20);
  });
});
