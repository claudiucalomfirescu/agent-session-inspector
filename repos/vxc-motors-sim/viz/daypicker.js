// Day picker for the baked pages (console, mission control, workday timeline).
// The exporter inlines this after `window.DAYS = {key: {title, data}}`. It sets window.SNAPSHOT to
// the chosen day before the page's own script runs, and adds a small "Day" menu; changing it reloads
// the page on the other day. The choice is kept in window.name, which survives a reload in the same
// tab (and inside an iframe) without needing storage.
(function () {
  "use strict";
  var keys = Object.keys(window.DAYS || {});
  if (!keys.length) return;
  var m = /(?:^|;)vxc-day=([\w-]+)/.exec(window.name || "");
  var key = m && window.DAYS[m[1]] ? m[1] : keys[0];
  window.DAY = key;
  window.SNAPSHOT = window.DAYS[key].data;
  if (keys.length < 2) return;
  function add() {
    var css = document.createElement("style");
    css.textContent = ".daypick{position:fixed;right:12px;bottom:12px;z-index:50;display:flex;gap:6px;align-items:center;" +
      "font:12px/1.2 system-ui,sans-serif;background:var(--panel,var(--bg,#fff));color:inherit;border:1px solid rgba(128,128,128,.4);" +
      "border-radius:8px;padding:6px 8px;box-shadow:0 2px 8px rgba(0,0,0,.15)}.daypick select{font:inherit;color:inherit;" +
      "background:transparent;border:1px solid rgba(128,128,128,.4);border-radius:6px;padding:3px 4px;max-width:58vw}";
    document.head.appendChild(css);
    var box = document.createElement("label");
    box.className = "daypick";
    box.appendChild(document.createTextNode("Day"));
    var sel = document.createElement("select");
    keys.forEach(function (k) {
      var o = document.createElement("option");
      o.value = k; o.textContent = window.DAYS[k].title || k; o.selected = k === key;
      sel.appendChild(o);
    });
    sel.onchange = function () {
      window.name = (window.name || "").replace(/(?:^|;)vxc-day=[\w-]+/, "") + ";vxc-day=" + sel.value;
      location.reload();
    };
    box.appendChild(sel);
    document.body.appendChild(box);
  }
  if (document.body) add(); else document.addEventListener("DOMContentLoaded", add);
})();
