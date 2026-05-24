/* Dashboard sparkline SVG rendering. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.renderSpark = function renderSpark(svg) {
    if (svg.getAttribute("data-spark-rendered") === "1") return;
    const raw = svg.getAttribute("data-points");
    if (!raw) return;
    let points;
    try { points = JSON.parse(raw); } catch (_) { return; }
    if (!points || !points.length) return;
    svg.setAttribute("data-spark-rendered", "1");
    const W = 280, H = 56;
    const vs = points.map(function (d) { return d.amount_yuan || 0; });
    const max = Math.max.apply(null, vs) || 1;
    const stepX = W / Math.max(points.length - 1, 1);
    const pts = points.map(function (d, i) {
      return [i * stepX, H - 6 - ((d.amount_yuan || 0) / max) * (H - 12)];
    });
    const path = pts.map(function (p, i) {
      return (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1);
    }).join(" ");
    const area = path + " L " + W + "," + H + " L 0," + H + " Z";
    const ns = "http://www.w3.org/2000/svg";
    const areaEl = document.createElementNS(ns, "path");
    areaEl.setAttribute("d", area);
    areaEl.setAttribute("fill", "url(#sparkArea)");
    svg.appendChild(areaEl);
    const lineEl = document.createElementNS(ns, "path");
    lineEl.setAttribute("d", path);
    lineEl.setAttribute("fill", "none");
    lineEl.setAttribute("stroke", "currentColor");
    lineEl.setAttribute("stroke-width", "1.25");
    svg.appendChild(lineEl);
    if (pts.length) {
      const last = pts[pts.length - 1];
      const dot = document.createElementNS(ns, "circle");
      dot.setAttribute("cx", last[0]);
      dot.setAttribute("cy", last[1]);
      dot.setAttribute("r", "2.5");
      dot.setAttribute("fill", "var(--brand-primary)");
      svg.appendChild(dot);
    }
  };

  app.initSparks = function initSparks(root) {
    (root || document).querySelectorAll(".spark[data-points]").forEach(app.renderSpark);
  };
})(window, document);
