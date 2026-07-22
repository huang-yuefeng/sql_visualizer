import { useRef, useCallback, useMemo } from 'react';

/**
 * Resizable panel hook — attaches mousedown via callback ref (works with
 * conditionally rendered elements). Attaches document mousemove/mouseup
 * imperatively on mousedown for immediate response.
 */
export function useResizable({ direction, defaultValue, value, min, max, onResize, invert }) {
  const valueRef = useRef(defaultValue);
  const startPosRef = useRef(0);
  const startValueRef = useRef(defaultValue);
  const onResizeRef = useRef(onResize);
  // Track the current element for cleanup
  const elRef = useRef(null);

  // Track CURRENT value (not just default) so drags don't jump
  valueRef.current = value !== undefined ? value : defaultValue;
  onResizeRef.current = onResize;

  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();

    startPosRef.current = direction === 'horizontal' ? e.clientX : e.clientY;
    startValueRef.current = valueRef.current;

    const onMouseMove = (ev) => {
      const currentPos = direction === 'horizontal' ? ev.clientX : ev.clientY;
      const delta = currentPos - startPosRef.current;
      let newValue = invert ? (startValueRef.current - delta) : (startValueRef.current + delta);
      if (min !== undefined) newValue = Math.max(min, newValue);
      if (max !== undefined) newValue = Math.min(max, newValue);
      if (onResizeRef.current) onResizeRef.current(newValue);
    };

    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    document.body.style.userSelect = 'none';
    document.body.style.cursor = direction === 'horizontal' ? 'col-resize' : 'row-resize';
  }, [direction, min, max]);

  // Callback ref: React calls this with the element every time it mounts/updates.
  // We attach the native listener directly.
  const handleRef = useCallback((el) => {
    // Cleanup previous element
    if (elRef.current) {
      elRef.current.removeEventListener('mousedown', handleMouseDown);
    }
    elRef.current = el;
    if (el) {
      el.addEventListener('mousedown', handleMouseDown);
    }
  }, [handleMouseDown]);

  const handleProps = useMemo(() => ({
    ref: handleRef,
    className: `resize-handle${direction === 'horizontal' ? '' : '-h'}`,
  }), [handleRef, direction]);

  return { handleProps };
}
