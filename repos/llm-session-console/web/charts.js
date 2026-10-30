/* Small SVG charts with no dependencies: stacked bars over time, heatmap, horizontal bars, sparkline.
   Every chart takes plain arrays and an onClick so a bar is also a drill-down link. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = (n) => n == null ? "–" : Math.abs(n) >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M"
    : Math.abs(n) >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k" : String(Math.round(n * 100) / 100);
  const el = (tag, attrs, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  };
  const tip = {
    show(ev, html) { const t = document.getElementById("tip"); t.innerHTML = html; t.hidden = false; tip.move(ev); },
    move(ev) {
      const t = document.getElementById("tip"); if (t.hidden) return;
      const w = t.offsetWidth, h = t.offsetHeight;
      t.style.left = Math.min(ev.clientX + 14, innerWidth - w - 8) + "px";
      t.style.top = Math.min(ev.clientY + 14, innerHeight - h - 8) + "px";
    },
    hide() { document.getElementById("tip").hidden = true; },
  };
  const niceMax = (v) => {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v))), m = v / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
  };

  /* Stacked bars. rows: [{bucket, ...}], keys: [{key, label, color}], line: optional {key, label, color}
     (drawn against its own right-hand scale). selected: bucket to highlight. */
  function bars(container, rows, { keys, line, height = 220, onClick, selected, label = (r) => r.bucket, tipExtra } = {}) {
    container.innerHTML = "";
    if (!rows.length) { container.innerHTML = '<div class="empty">No traffic in this range.</div>'; return; }
    const W = Math.max(container.clientWidth || 600, 300), H = height, m = { l: 44, r: line ? 48 : 8, t: 8, b: 26 };
    const svg = el("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img" }, container);
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const tot = rows.map((r) => keys.reduce((s, k) => s + (r[k.key] || 0), 0));
    const ymax = niceMax(Math.max(...tot));
    const g = el("g", { class: "grid" }, svg);
    for (let i = 0; i <= 4; i++) {
      const y = m.t + ih - (ih * i) / 4;
      el("line", { x1: m.l, x2: W - m.r, y1: y, y2: y }, g);
      el("text", { x: m.l - 6, y: y + 4, "text-anchor": "end" }, svg).textContent = fmt((ymax * i) / 4);
    }
    const bw = iw / rows.length, gap = Math.min(4, bw * 0.2);
    const every = Math.ceil(rows.length / Math.max(1, Math.floor(iw / 64)));
    rows.forEach((r, i) => {
      const x = m.l + i * bw;
      if (selected && r.bucket === selected) el("rect", { class: "sel", x, y: m.t, width: bw, height: ih }, svg);
      let y = m.t + ih;
      const grp = el("g", { class: "bar" }, svg);
      keys.forEach((k) => {
        const v = r[k.key] || 0; if (!v) return;
        const h = (v / ymax) * ih;
        y -= h;
        el("rect", { x: x + gap / 2, y, width: Math.max(1, bw - gap), height: Math.max(h, 0.5), fill: k.color, rx: Math.min(2, bw / 4) }, grp);
      });
      el("rect", { x, y: m.t, width: bw, height: ih, fill: "transparent" }, grp);
      grp.addEventListener("mousemove", (ev) => tip.show(ev, `<b>${label(r)}</b>` + keys.map((k) =>
        `<div><span class="dot" style="background:${k.color}"></span>${k.label}: ${fmt(r[k.key] || 0)}</div>`).join("")
        + (line ? `<div>${line.label}: ${fmt(r[line.key] || 0)}</div>` : "") + (tipExtra ? tipExtra(r) : "")
        + (onClick ? '<div class="muted">click to drill in</div>' : "")));
      grp.addEventListener("mouseleave", tip.hide);
      if (onClick) grp.addEventListener("click", () => { tip.hide(); onClick(r); });
      if (i % every === 0) el("text", { x: x + bw / 2, y: H - 8, "text-anchor": "middle" }, svg).textContent = shortDate(r.bucket);
    });
    if (line) {
      const lmax = niceMax(Math.max(...rows.map((r) => r[line.key] || 0)));
      const pts = rows.map((r, i) => `${m.l + i * bw + bw / 2},${m.t + ih - ((r[line.key] || 0) / lmax) * ih}`).join(" ");
      el("polyline", { points: pts, fill: "none", stroke: line.color, "stroke-width": 2, "stroke-linejoin": "round", "pointer-events": "none" }, svg);
      for (let i = 0; i <= 4; i++) el("text", { x: W - m.r + 6, y: m.t + ih - (ih * i) / 4 + 4 }, svg).textContent = fmt((lmax * i) / 4);
    }
  }

  function shortDate(b) {
    if (!b) return "";
    if (b.length > 10) return b.slice(11, 16);
    const d = new Date(b + "T00:00:00Z");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  }

  /* Weekday x hour heatmap. cells: [{dow, hour, calls}] */
  function heatmap(container, cells, { onClick } = {}) {
    container.innerHTML = "";
    const W = Math.max(container.clientWidth || 600, 300), m = { l: 34, t: 4, b: 18 }, cw = (W - m.l) / 24, ch = 18, H = m.t + 7 * ch + m.b;
    const svg = el("svg", { class: "chart", viewBox: `0 0 ${W} ${H}` }, container);
    const max = Math.max(1, ...cells.map((c) => c.calls));
    const by = {}; cells.forEach((c) => (by[c.dow + ":" + c.hour] = c.calls));
    const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], accent = css("--accent");
    days.forEach((d, i) => {
      el("text", { x: m.l - 6, y: m.t + i * ch + 13, "text-anchor": "end" }, svg).textContent = d;
      for (let h = 0; h < 24; h++) {
        const v = by[i + ":" + h] || 0;
        const r = el("rect", { x: m.l + h * cw + 1, y: m.t + i * ch + 1, width: cw - 2, height: ch - 2, rx: 2,
          fill: v ? accent : css("--panel2"), "fill-opacity": v ? 0.15 + 0.85 * Math.sqrt(v / max) : 1 }, svg);
        r.addEventListener("mousemove", (ev) => tip.show(ev, `<b>${d} ${String(h).padStart(2, "0")}:00–${String(h + 1).padStart(2, "0")}:00 UTC</b>${v} calls`));
        r.addEventListener("mouseleave", tip.hide);
        if (onClick && v) { r.style.cursor = "pointer"; r.addEventListener("click", () => onClick(i, h)); }
      }
    });
    for (let h = 0; h < 24; h += 3) el("text", { x: m.l + h * cw + cw / 2, y: H - 4, "text-anchor": "middle" }, svg).textContent = String(h).padStart(2, "0");
  }

  /* Horizontal bars as an HTML grid: items [{key, value, href?, color?, extra?}] */
  function hbars(container, items, { fmtv = fmt } = {}) {
    if (!items.length) { container.innerHTML = '<div class="empty">Nothing here.</div>'; return; }
    const max = Math.max(...items.map((i) => i.value), 1);
    container.innerHTML = `<div class="hbar">${items.map((i) => `
      ${i.href ? `<a href="${i.href}" title="${esc(i.key)}">${esc(i.key)}</a>` : `<span class="k" title="${esc(i.key)}">${esc(i.key)}</span>`}
      <div><div class="b" style="width:${(100 * i.value) / max}%;${i.color ? "background:" + i.color : ""}"></div></div>
      <span class="n">${fmtv(i.value)}${i.extra || ""}</span>`).join("")}</div>`;
  }

  /* Tiny inline sparkline (SVG string) over a fixed list of days. */
  function spark(days, byDay, color) {
    if (!days.length) return "";
    const w = 90, h = 20, max = Math.max(1, ...days.map((d) => byDay[d] || 0)), bw = w / days.length;
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">${days.map((d, i) => {
      const v = byDay[d] || 0, bh = v ? Math.max(1.5, (v / max) * h) : 0;
      return bh ? `<rect x="${i * bw + 0.3}" y="${h - bh}" width="${Math.max(1, bw - 0.6)}" height="${bh}" fill="${color}"/>` : "";
    }).join("")}</svg>`;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  window.Charts = { bars, heatmap, hbars, spark, fmt, esc, tip, css, shortDate };
})();
