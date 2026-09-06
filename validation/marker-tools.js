/* Marker coordinates are normalized; removal distance is measured on screen. */
const MarkerTools = (() => {
  function edit(points, position, tool, width, height) {
    if (tool === 'add') return [...points, [...position]];
    let nearest = -1, distance = 7;
    points.forEach(([x, y], index) => {
      const d = Math.hypot((x - position[0]) * width, (y - position[1]) * height);
      if (d < distance) { nearest = index; distance = d; }
    });
    return nearest < 0 ? points : points.filter((_, index) => index !== nearest);
  }
  return { edit };
})();
if (typeof module !== 'undefined') module.exports = MarkerTools;
