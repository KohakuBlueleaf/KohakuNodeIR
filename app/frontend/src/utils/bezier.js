/**
 * Generate SVG path for a data wire (horizontal: left-to-right).
 *
 * When the wire goes backward (x2 < x1) it loops around with a vertical
 * detour so it doesn't cross through nodes.
 */
export function dataWirePath(x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = Math.abs(y2 - y1);

  if (dx >= 0) {
    // Forward edge — simple S-curve
    const offset = Math.max(40, Math.min(dx * 0.45 + dy * 0.1, 200));
    return `M ${x1} ${y1} C ${x1 + offset} ${y1}, ${x2 - offset} ${y2}, ${x2} ${y2}`;
  }

  // Backward edge — loop around via a vertical detour
  const loopOut = Math.max(50, Math.min(Math.abs(dx) * 0.35 + dy * 0.15, 160));
  const loopDown = Math.max(40, dy * 0.5 + Math.abs(dx) * 0.15);
  const midY = y1 + loopDown;
  return (
    `M ${x1} ${y1} ` +
    `C ${x1 + loopOut} ${y1}, ${x1 + loopOut} ${midY}, ${(x1 + x2) / 2} ${midY} ` +
    `S ${x2 - loopOut} ${midY}, ${x2 - loopOut} ${midY} ` +
    `C ${x2 - loopOut} ${midY}, ${x2 - loopOut} ${y2}, ${x2} ${y2}`
  );
}

/**
 * Generate SVG path for a control wire (vertical: top-to-bottom).
 *
 * Forward edges use a gentle S-curve that scales with both dx and dy.
 * Backward edges (loops) arc out to the side proportional to distance.
 */
export function controlWirePath(x1, y1, x2, y2) {
  const dy = y2 - y1;
  const dx = Math.abs(x2 - x1);

  if (dy >= 0) {
    // Forward edge — scale offset by both dy and dx for gentler curves
    const offset = Math.max(30, Math.min(dy * 0.5 + dx * 0.1, 150));
    return `M ${x1} ${y1} C ${x1} ${y1 + offset}, ${x2} ${y2 - offset}, ${x2} ${y2}`;
  }

  // Backward edge — route around the side; arc width scales with distance
  const dist = Math.sqrt(dx * dx + dy * dy);
  const loopOut = Math.max(60, Math.min(dist * 0.4, 220));
  const loopDown = Math.max(40, Math.abs(dy) * 0.25);
  return (
    `M ${x1} ${y1} ` +
    `C ${x1 + loopOut} ${y1}, ${x1 + loopOut} ${y1 + loopDown}, ${x1 + loopOut} ${(y1 + y2) / 2} ` +
    `S ${x2 + loopOut} ${y2 - loopDown}, ${x2 + loopOut} ${y2}, ${x2} ${y2}`
  );
}
