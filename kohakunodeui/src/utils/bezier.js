/**
 * Generate SVG path for a data wire (horizontal: left-to-right).
 */
export function dataWirePath(x1, y1, x2, y2) {
  const dx = Math.abs(x2 - x1);
  const offset = Math.max(50, dx * 0.4);
  return `M ${x1} ${y1} C ${x1 + offset} ${y1}, ${x2 - offset} ${y2}, ${x2} ${y2}`;
}

/**
 * Generate SVG path for a control wire (vertical: top-to-bottom).
 */
export function controlWirePath(x1, y1, x2, y2) {
  const dy = Math.abs(y2 - y1);
  const offset = Math.max(50, dy * 0.4);
  // If going upward (backward edge for loops), use a different curve
  if (y2 < y1) {
    const loopOffset = Math.max(80, Math.abs(x2 - x1) * 0.5);
    return `M ${x1} ${y1} C ${x1 + loopOffset} ${y1 + 60}, ${x2 - loopOffset} ${y2 - 60}, ${x2} ${y2}`;
  }
  return `M ${x1} ${y1} C ${x1} ${y1 + offset}, ${x2} ${y2 - offset}, ${x2} ${y2}`;
}
