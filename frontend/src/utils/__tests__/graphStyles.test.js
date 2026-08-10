import { describe, it, expect } from 'vitest';
import { NODE_STYLES, CATEGORY_EDGE_STYLES } from '../graphStyles';

describe('graphStyles — R25/§8.8 flow-kind edge labels', () => {
  it('every L2 edge with flow_kind renders the kind at the midpoint, in the edge color', () => {
    const rule = CATEGORY_EDGE_STYLES.find(r => r.selector === 'edge[flow_kind]');
    expect(rule).toBeDefined();
    expect(rule.style['label']).toBe('data(flow_kind)');
    expect(rule.style['color']).toBe('data(color)');
    expect(rule.style['font-size']).toBeDefined();
    expect(Number(rule.style['font-size'])).toBeLessThanOrEqual(10);
  });

  it('the label carries the flow kind ONLY — never edge type, never SQL text', () => {
    const rule = CATEGORY_EDGE_STYLES.find(r => r.selector === 'edge[flow_kind]');
    expect(rule.style['label']).not.toBe('data(edge_type)');
    expect(rule.style['label']).not.toBe('data(label)');
    expect(rule.style['label']).not.toMatch(/sql/i);
  });

  it('the base edge rule still defaults the label to data(label) (L1 edges unaffected)', () => {
    const base = NODE_STYLES.find(r => r.selector === 'edge');
    expect(base.style['label']).toBe('data(label)');
  });
});
