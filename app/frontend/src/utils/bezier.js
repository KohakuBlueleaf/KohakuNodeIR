/**
 * Generate SVG path for a data wire (horizontal: left-to-right).
 *
 * Wires flow left→right using a horizontal bezier S-curve.
 * The control-point offset is primarily driven by horizontal distance so the
 * curve stays flat even when source and target are far apart vertically.
 * When the wire goes backward (x2 < x1) it loops around with a downward
 * detour so it doesn't cross through nodes.
 */
export function dataWirePath(x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = Math.abs(y2 - y1);

  if (dx >= 0) {
    // Forward edge — horizontal S-curve.
    // Use a minimum offset so nearly-vertical wires still curve sideways.
    // dy term is kept very small so the curve doesn't tilt vertically.
    const offset = Math.max(60, Math.min(dx * 0.5 + dy * 0.05, 220));
    return `M ${x1} ${y1} C ${x1 + offset} ${y1}, ${x2 - offset} ${y2}, ${x2} ${y2}`;
  }

  // Backward edge — loop around via a downward detour using two cubic segments.
  const absDx = Math.abs(dx);
  const loopOut = Math.max(60, Math.min(absDx * 0.4 + dy * 0.1, 180));
  const loopDown = Math.max(50, dy * 0.5 + absDx * 0.2);
  const midY = y1 + loopDown;
  const midX = (x1 + x2) / 2;
  return (
    `M ${x1} ${y1} ` +
    `C ${x1 + loopOut} ${y1}, ${x1 + loopOut} ${midY}, ${midX} ${midY} ` +
    `C ${x2 - loopOut} ${midY}, ${x2 - loopOut} ${y2}, ${x2} ${y2}`
  );
}

/**
 * Generate SVG path for a control wire (vertical: top-to-bottom).
 *
 * Wires flow top→bottom using a vertical bezier S-curve.
 * Control points are purely vertical (no sideways drift) so the curve does
 * not go sideways before bending down.
 * Backward edges (y2 < y1, loops) arc out to the side proportional to distance.
 */
export function controlWirePath(x1, y1, x2, y2) {
  const dy = y2 - y1;
  const dx = x2 - x1;
  const absDx = Math.abs(dx);

  if (dy >= 0) {
    // Forward edge — vertical S-curve.
    // Control points go straight down from each endpoint so the wire never
    // drifts sideways before curving.
    const offset = Math.max(30, Math.min(dy * 0.5 + absDx * 0.05, 150));
    return `M ${x1} ${y1} C ${x1} ${y1 + offset}, ${x2} ${y2 - offset}, ${x2} ${y2}`;
  }

  // Backward edge — route out to the side then back in.
  // Arc width is proportional to the total distance between ports.
  const dist = Math.sqrt(absDx * absDx + dy * dy);
  const loopOut = Math.max(60, Math.min(dist * 0.4, 220));
  const loopDown = Math.max(40, Math.abs(dy) * 0.25);
  const midY = (y1 + y2) / 2;
  // Route: out to the right from start, sweep down to mid, sweep to arrive at end
  return (
    `M ${x1} ${y1} ` +
    `C ${x1 + loopOut} ${y1}, ${x1 + loopOut} ${y1 + loopDown}, ${x1 + loopOut} ${midY} ` +
    `C ${x1 + loopOut} ${y2 - loopDown}, ${x2 + loopOut} ${y2}, ${x2} ${y2}`
  );
}
