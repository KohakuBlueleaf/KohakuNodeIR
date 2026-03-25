/**
 * Generate SVG path for a data wire (horizontal: left-to-right).
 *
 * Clean horizontal S-curve. For short distances the wire is nearly straight;
 * for longer ones it bends gently. Backward wires loop around smoothly.
 */
export function dataWirePath(x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const absDy = Math.abs(dy);

  if (dx >= 0) {
    // Forward: gentle horizontal S-curve.
    // Scale offset with distance — nearly straight when close.
    const offset = Math.min(dx * 0.4, 150) + Math.min(absDy * 0.1, 30);
    const clampedOffset = Math.max(20, offset);
    return `M ${x1} ${y1} C ${x1 + clampedOffset} ${y1}, ${x2 - clampedOffset} ${y2}, ${x2} ${y2}`;
  }

  // Backward: smooth loop around. Goes below both endpoints.
  const absDx = Math.abs(dx);
  const spread = Math.max(40, absDx * 0.3 + absDy * 0.15);
  const drop = Math.max(30, absDy * 0.4 + absDx * 0.2);
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
 * Clean vertical S-curve. Control points stay directly above/below endpoints
 * so the wire doesn't drift sideways. Backward (loop) wires arc to the right.
 */
export function controlWirePath(x1, y1, x2, y2) {
  const dy = y2 - y1;
  const dx = x2 - x1;
  const absDx = Math.abs(dx);

  if (dy >= 0) {
    // Forward: vertical S-curve, straight when close.
    const offset = Math.min(dy * 0.4, 120) + Math.min(absDx * 0.08, 20);
    const clampedOffset = Math.max(15, offset);
    return `M ${x1} ${y1} C ${x1} ${y1 + clampedOffset}, ${x2} ${y2 - clampedOffset}, ${x2} ${y2}`;
  }

  // Backward (loop): arc out to the right proportional to distance.
  const absDy = Math.abs(dy);
  const dist = Math.sqrt(absDx * absDx + absDy * absDy);
  const arcOut = Math.max(50, Math.min(dist * 0.35, 200));
  // Direction: go right if target is to the right or same column, left if target is far left
  const side = dx >= 0 ? 1 : (absDx > arcOut ? -1 : 1);
  const cx = Math.max(x1, x2) + arcOut * side;
  const midY = (y1 + y2) / 2;
  return (
    `M ${x1} ${y1} ` +
    `C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`
  );
}
