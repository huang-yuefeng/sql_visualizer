/**
 * Workflow (Snake) Layout — V4.1
 * Simple, reliable snake-wrap: collect all top-level nodes, sort by label/layer, wrap.
 */
import {
  FIT_PADDING, SNAKE_ROW_HEIGHT, SNAKE_NODE_SPACING, SNAKE_MAX_PER_ROW,
  SNAKE_START_X, SNAKE_START_Y,
} from '../config/layout';
import { finalizeLayout } from './compoundLayout';

export function applyWorkflowLayout(cy, options = {}) {
  if (!cy || cy.destroyed() || cy.nodes().length === 0) return false;

  const rowHeight = options.rowHeight || SNAKE_ROW_HEIGHT;
  const nodeSpacing = options.nodeSpacing || SNAKE_NODE_SPACING;
  const maxPerRow = options.maxNodesPerRow || SNAKE_MAX_PER_ROW;

  // Collect all non-field, non-child nodes
  const topLevel = [];
  cy.nodes().forEach(n => {
    const type = n.data('type') || '';
    const parent = n.data('parent');
    if (parent || type === 'field') return;
    topLevel.push({ id: n.id(), label: (n.data('label') || ''), layer: n.data('layer') });
  });

  if (topLevel.length === 0) return false;

  // Sort: scripts first by label (step1, step2...), then tables by label
  topLevel.sort((a, b) => {
    const aIsScript = a.id.length < 20; // script IDs are short hashes
    const bIsScript = b.id.length < 20;
    if (aIsScript !== bIsScript) return aIsScript ? -1 : 1;
    // Extract number from label
    const aNum = parseInt((a.label.match(/(\d+)/) || ['0'])[1]);
    const bNum = parseInt((b.label.match(/(\d+)/) || ['0'])[1]);
    if (aNum !== bNum) return aNum - bNum;
    return a.label.localeCompare(b.label);
  });

  // Snake-wrap
  cy.batch(() => {
    topLevel.forEach((item, idx) => {
      const col = idx % maxPerRow;
      const row = Math.floor(idx / maxPerRow);
      const x = SNAKE_START_X + col * nodeSpacing;
      const y = SNAKE_START_Y + row * rowHeight;
      const node = cy.getElementById(item.id);
      if (node && node.length) {
        node.position({ x, y });
        node.data('x', x);
        node.data('y', y);
      }
    });
  });

  finalizeLayout(cy, FIT_PADDING);
  return true;
}
