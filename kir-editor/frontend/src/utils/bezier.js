/**
 * Generate SVG path for a data wire (horizontal: left-to-right).
 *
 * Nearly straight when close, gentle S-curve at distance.
 * Backward wires loop smoothly below both endpoints.
 */
export function dataWirePath(x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const absDy = Math.abs(dy);

  if (dx >= 0) {
    // Forward: horizontal S-curve, proportional to distance.
    const offset = Math.max(20, Math.min(dx * 0.4 + absDy * 0.08, 150));
    return `M ${x1} ${y1} C ${x1 + offset} ${y1}, ${x2 - offset} ${y2}, ${x2} ${y2}`;
  }

  // Backward: loop below. Keep arc tight — proportional to actual distance, not oversized.
  const absDx = Math.abs(dx);
  const spread = Math.max(30, Math.min(absDx * 0.25 + absDy * 0.1, 120));
  const drop = Math.max(25, Math.min(absDy * 0.3 + absDx * 0.15, 100));
  const midX = (x1 + x2) / 2;
  const loopY = Math.max(y1, y2) + drop;
  return (
    `M ${x1} ${y1} ` +
    `C ${x1 + spread} ${y1}, ${x1 + spread} ${loopY}, ${midX} ${loopY} ` +
    `C ${x2 - spread} ${loopY}, ${x2 - spread} ${y2}, ${x2} ${y2}`
  );
}

/**
 * Generate SVG path for a control wire (vertical: top-to-bottom).
 *
 * Nearly straight when close, gentle S-curve at distance.
 * Backward (loop) wires arc to the side — tightly, not oversized.
 */
export function controlWirePath(x1, y1, x2, y2) {
  const dy = y2 - y1;
  const dx = x2 - x1;
  const absDx = Math.abs(dx);

  if (dy >= 0) {
    // Forward: vertical S-curve. Control points stay above/below endpoints.
    // When there's horizontal offset, blend a small horizontal component
    // so the curve transitions smoothly instead of going straight down then snapping sideways.
    const vOffset = Math.max(15, Math.min(dy * 0.4, 120));
    const hBlend = absDx > 0 ? Math.min(absDx * 0.15, 30) : 0;
    return `M ${x1} ${y1} C ${x1 + hBlend} ${y1 + vOffset}, ${x2 - hBlend} ${y2 - vOffset}, ${x2} ${y2}`;
  }

  // Backward (loop): arc to the side. Keep arc proportional to distance, not oversized.
  const absDy = Math.abs(dy);
  const arcOut = Math.max(
    40,
    Math.min(Math.sqrt(absDx * absDx + absDy * absDy) * 0.3, 150),
  );
  // Arc direction: go to the right of the rightmost endpoint
  const rightX = Math.max(x1, x2);
  return (
    `M ${x1} ${y1} ` +
    `C ${rightX + arcOut} ${y1}, ${rightX + arcOut} ${y2}, ${x2} ${y2}`
  );
}
