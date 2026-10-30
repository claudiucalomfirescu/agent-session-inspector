/* Session Console: hash-routed drill-down over the read-only API.

   #/                    all traffic (filters: range, dept, system traffic)
   #/u/<user>            one user: their days/weeks, hours, tools, sessions
   #/s/<session>         one session as a conversation, with firewall findings on the message they concern
   #/fw                  firewall findings and admin actions (only for logs that have them)
   #/galaxy              the same hierarchy in 3D (galaxy.js, loaded on demand)
   #/search?q=…          calls whose request/response contains the text

   Filters live in the hash query (?db=&from=&to=&dept=&bucket=&system=), so every view is a link. */
(function () {
  const { bars, heatmap, hbars, spark, fmt, esc, css, shortDate } = window.Charts;
  const $ = (s, r = document) => r.querySelector(s);
  const view = $("#view");
  const LEVEL = ["info", "warning", "block"];
  const DEPT_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#76b7b2", "#edc948", "#ff9da7", "#9c755f", "#e15759", "#bab0ac"];
  let META = null, DBS = [], deptColor = {};

  // ---- state in the hash ----------------------------------------------------------------------
  function parseHash() {
    const h = location.hash.slice(1) || "/";
    const [path, qs] = h.split("?");
    return { path: path || "/", q: Object.fromEntries(new URLSearchParams(qs || "")) };
  }
  function link(path, extra = {}, drop = []) {
    const q = { ...parseHash().q, ...extra };
    drop.forEach((k) => delete q[k]);
    Object.keys(q).forEach((k) => (q[k] === "" || q[k] == null) && delete q[k]);
    const s = new URLSearchParams(q).toString();
    return "#" + path + (s ? "?" + s : "");
  }
  const go = (path, extra, drop) => (location.hash = link(path, extra, drop));
  function apiQuery(extra = {}) {
    const q = parseHash().q, p = new URLSearchParams();
    ["db", "from", "to", "dept", "system", "bucket"].forEach((k) => q[k] && p.set(k, q[k]));
    Object.entries(extra).forEach(([k, v]) => v != null && v !== "" && p.set(k, v));
    return p.toString();
  }
  let routeToken = 0;
  class Stale extends Error {}
  async function api(path, extra) {
    const token = routeToken;
    const r = await fetch("/api/" + path + "?" + apiQuery(extra));
    const j = await r.json();
    if (token !== routeToken) throw new Stale();   // the user navigated on while this was loading
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }

  // ---- header controls ------------------------------------------------------------------------
  function syncControls() {
    const q = parseHash().q;
    $("#db").value = q.db || (DBS[0] && DBS[0].name) || "";
    $("#system").checked = q.system === "1";
    document.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("on", (q.bucket || "day") === b.dataset.bucket));
    const custom = q.from || q.to;
    $("#range").value = q.range || (custom ? "custom" : "all");
    $("#custom").hidden = $("#range").value !== "custom";
    $("#from").value = q.from || ""; $("#to").value = q.to || "";
    const tab = parseHash().path.startsWith("/fw") ? "fw" : parseHash().path.startsWith("/galaxy") ? "galaxy" : "drill";
    document.querySelectorAll(".tabs a").forEach((a) => {
      a.classList.toggle("on", a.dataset.tab === tab);
      a.href = link(a.dataset.tab === "fw" ? "/fw" : a.dataset.tab === "galaxy" ? "/galaxy" : "/");
    });
  }
  function setRange(v) {
    const { path } = parseHash();
    if (v === "all") return go(path, { range: "" }, ["from", "to"]);
    if (v === "custom") return go(path, { range: "custom", from: $("#from").value || META.first, to: $("#to").value || META.last });
    const end = new Date(META.last + "T00:00:00Z"), start = new Date(end - (Number(v) - 1) * 864e5);
    go(path, { range: v, from: start.toISOString().slice(0, 10), to: META.last });
  }
  $("#range").addEventListener("change", (e) => setRange(e.target.value));
  $("#from").addEventListener("change", () => go(parseHash().path, { range: "custom", from: $("#from").value }));
  $("#to").addEventListener("change", () => go(parseHash().path, { range: "custom", to: $("#to").value }));
  $("#system").addEventListener("change", (e) => go(parseHash().path, { system: e.target.checked ? "1" : "" }));
  $("#db").addEventListener("change", (e) => go("/", { db: e.target.value }, ["from", "to", "range", "dept"]));
  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => go(parseHash().path, { bucket: b.dataset.bucket === "day" ? "" : b.dataset.bucket })));
  $("#searchform").addEventListener("submit", (e) => { e.preventDefault(); go("/search", { q: $("#q").value }); });
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.dataset.theme = cur === "dark" ? "light" : "dark";
    try { localStorage.setItem("console-theme", document.documentElement.dataset.theme); } catch (e) { /* private mode */ }
    route();
  });
  try { const t = localStorage.getItem("console-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* ignore */ }
  $("#modal-close").addEventListener("click", () => $("#modal").close());

  // ---- breadcrumb -------------------------------------------------------------------------------
  function crumbs(parts) {
    const q = parseHash().q, chips = [];
    if (q.from || q.to) {
      const label = q.from === q.to ? dayLabel(q.from) : `${q.from ? shortDate(q.from) : "start"} – ${q.to ? shortDate(q.to) : "end"}`;
      chips.push(`<span class="chip">📅 ${esc(label)}<button data-drop="from,to,range" title="Clear dates">✕</button></span>`);
    }
    if (q.dept) chips.push(`<span class="chip">🏷 ${esc(q.dept)}<button data-drop="dept" title="Clear department">✕</button></span>`);
    const trail = [`<a href="${link("/")}">All traffic</a>`, ...parts].join('<span class="sep">›</span>');
    $("#crumbs").innerHTML = trail + (chips.length ? '<span class="sep">·</span>' + chips.join("") : "")
      + (META ? `<span class="sep">·</span><span class="muted">${esc(META.name)}: users from <b>${esc(META.identity)}</b>${META.has_signals ? "" : ", no firewall tables"}</span>` : "");
    $("#crumbs").querySelectorAll("[data-drop]").forEach((b) => b.addEventListener("click", () => go(parseHash().path, {}, b.dataset.drop.split(","))));
  }
  const dayLabel = (d) => d ? new Date(d + "T00:00:00Z").toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "";
  const time = (ts) => ts ? ts.slice(11, 16) : "";
  const dt = (ts) => ts ? `${shortDate(ts.slice(0, 10))} ${time(ts)}` : "";
  const dur = (a, b) => { const s = (new Date(b) - new Date(a)) / 1000; return s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${(s / 3600).toFixed(1)}h`; };
  const badge = (lv) => lv ? `<span class="badge ${lv}">${lv}</span>` : "";
  const fwBadges = (fw) => LEVEL.slice().reverse().filter((l) => fw && fw[l]).map((l) => `<span class="badge ${l}" title="${fw[l]} ${l} finding(s)">${l[0].toUpperCase()} ${fw[l]}</span>`).join(" ");
  const colorOf = (dept) => deptColor[dept] || "#888";
  const levelColor = (lv) => lv ? css("--" + lv) : css("--none");

  function kpis(t, extra = []) {
    const fw = t.firewall || {};
    const items = [["Calls", t.calls], ["Sessions", t.sessions], ["Users", t.users], ["Tokens", t.tokens],
      ["Active days", t.days], ["Avg latency", t.avg_ms != null ? (t.avg_ms / 1000).toFixed(1) + "s" : "–"],
      ["Cost", t.cost ? "$" + t.cost.toFixed(4) : "$0"], ["Errors", t.errors], ...extra];
    if (META && META.has_signals) items.push(["Info", fw.info || 0, "lv-info"], ["Warnings", fw.warning || 0, "lv-warning"], ["Blocks", fw.block || 0, "lv-block"]);
    return `<div class="kpis">${items.map(([l, v, c]) => `<div class="kpi ${c || ""}"><div class="v">${typeof v === "number" ? fmt(v) : esc(v)}</div><div class="l">${l}</div></div>`).join("")}</div>`;
  }

  function seriesChart(container, series, { onClick, selected, metric }) {
    const m = metric || "calls";
    const accent = css("--accent");
    const keysFor = {
      calls: [{ key: "calls_ok", label: "calls", color: accent }, { key: "blocked", label: "blocked calls", color: css("--block") }],
      sessions: [{ key: "sessions", label: "sessions", color: accent }],
      tokens: [{ key: "prompt_tokens", label: "prompt tokens", color: accent }, { key: "completion_tokens", label: "completion tokens", color: "#8e6bd8" }],
      users: [{ key: "users", label: "active users", color: accent }],
      firewall: LEVEL.map((l) => ({ key: l, label: l, color: css("--" + l) })),
    };
    series.forEach((r) => (r.calls_ok = (r.calls || 0) - (r.blocked || 0)));
    const line = m === "calls" ? { key: "sessions", label: "sessions", color: css("--warning") } : null;
    bars(container, series, { keys: keysFor[m], line, onClick, selected,
      label: (r) => r.bucket.length > 10 ? r.bucket : (parseHash().q.bucket === "week" ? "Week of " : "") + dayLabel(r.bucket),
      tipExtra: (r) => m !== "firewall" && (r.warning || r.block) ? `<div>${fwBadges({ warning: r.warning, block: r.block })}</div>` : "" });
  }
  function metricPicker(id, cur) {
    const opts = ["calls", "sessions", "tokens", "users"].concat(META.has_signals ? ["firewall"] : []);
    return `<div class="seg" id="${id}">${opts.map((o) => `<button data-m="${o}" class="${o === cur ? "on" : ""}">${o}</button>`).join("")}</div>`;
  }
  function bucketClick(r) {
    const week = parseHash().q.bucket === "week";
    if (r.bucket.length > 10) return;
    const to = week ? new Date(new Date(r.bucket + "T00:00:00Z").getTime() + 6 * 864e5).toISOString().slice(0, 10) : r.bucket;
    go(parseHash().path, { from: r.bucket, to, range: "custom", bucket: week ? "" : parseHash().q.bucket });
  }

  // ---- views -----------------------------------------------------------------------------------
  async function viewGlobal() {
    crumbs([]);
    const q = parseHash().q;
    const d = await api("overview");
    const t = d.totals;
    const single = q.from && q.from === q.to;
    view.innerHTML = `
      <h1>${single ? dayLabel(q.from) : "All traffic"} <small>${t.first ? `${dayLabel(t.first)} – ${dayLabel(t.last)}` : "no calls"} · UTC</small></h1>
      ${kpis(t)}
      <div class="grid">
        <section class="card span-12"><div class="row"><h2>${single ? "By hour" : "Over time"}</h2>${metricPicker("metric", q.metric || "calls")}</div>
          <div id="series"></div><div class="muted" style="font-size:12px;margin-top:4px">${single ? "" : "Click a bar to drill into that " + (q.bucket === "week" ? "week" : "day") + "."}</div></section>
        <section class="card span-8"><div class="row"><h2>Users</h2><span class="muted">${d.users.length} · click to drill in</span></div><div class="tbl-wrap" id="users"></div></section>
        <section class="card span-4"><h2>Departments</h2><div id="depts"></div>
          <h2 style="margin-top:16px">Models</h2><div id="models"></div></section>
        <section class="card span-12"><h2>When (weekday × hour, UTC)</h2><div id="heat"></div></section>
      </div>`;
    const series = single ? (await api("overview", { bucket: "hour" })).series : d.series;
    seriesChart($("#series"), series, { onClick: single ? null : bucketClick, metric: q.metric });
    $("#metric").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => go(parseHash().path, { metric: b.dataset.m })));
    usersTable($("#users"), d.users, d.series.map((r) => r.bucket));
    hbars($("#depts"), d.depts.map((x) => ({ key: x.dept, value: x.calls, color: colorOf(x.dept), href: link("/", { dept: x.dept }), extra: ` · ${x.users}u` })));
    hbars($("#models"), d.models.map((x) => ({ key: x.model, value: x.calls })));
    heatmap($("#heat"), d.heatmap);
  }

  function usersTable(container, users, days) {
    const cols = [["user", "User"], ["dept", "Dept"], ["calls", "Calls", 1], ["sessions", "Sessions", 1], ["tokens", "Tokens", 1],
      ["active_days", "Days", 1], ["last_seen", "Last seen"], ["fw_rank", "Firewall"]];
    let sort = { k: "calls", dir: -1 };
    const draw = () => {
      const rows = users.slice().sort((a, b) => {
        const ka = sort.k === "fw_rank" ? rankOf(a) : a[sort.k], kb = sort.k === "fw_rank" ? rankOf(b) : b[sort.k];
        return (ka > kb ? 1 : ka < kb ? -1 : 0) * sort.dir;
      });
      container.innerHTML = `<table><thead><tr>${cols.map(([k, l, n]) => `<th data-k="${k}" class="${n ? "num" : ""}">${l}${sort.k === k ? (sort.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}<th>Activity</th></tr></thead>
        <tbody>${rows.map((u) => `<tr data-u="${esc(u.user)}">
          <td><span class="dot" style="background:${colorOf(u.dept)}"></span><b>${esc(u.user)}</b>${u.is_system ? ' <span class="badge out">system</span>' : ""}</td>
          <td class="muted">${esc(u.dept)}</td><td class="num">${fmt(u.calls)}</td><td class="num">${fmt(u.sessions)}</td>
          <td class="num">${fmt(u.tokens)}</td><td class="num">${u.active_days}</td><td class="muted">${dt(u.last_seen)}</td>
          <td>${fwBadges(u.firewall) || (u.blocked ? badge("block") : "")}</td>
          <td>${spark(days, u.by_day, colorOf(u.dept))}</td></tr>`).join("")}</tbody></table>`;
      container.querySelectorAll("th[data-k]").forEach((th) => th.addEventListener("click", () => {
        sort = { k: th.dataset.k, dir: sort.k === th.dataset.k ? -sort.dir : -1 }; draw();
      }));
      container.querySelectorAll("tr[data-u]").forEach((tr) => tr.addEventListener("click", () => go("/u/" + encodeURIComponent(tr.dataset.u))));
    };
    const rankOf = (u) => (u.firewall.block || 0) * 1e6 + (u.firewall.warning || 0) * 1e3 + (u.firewall.info || 0);
    draw();
  }

  async function viewUser(user) {
    const q = parseHash().q;
    crumbs([`<a href="${link("/u/" + encodeURIComponent(user))}">${esc(user)}</a>`]);
    const d = await api("user/" + encodeURIComponent(user));
    const u = d.user, t = d.totals;
    const single = q.from && q.from === q.to;
    view.innerHTML = `
      <h1><span class="dot" style="background:${colorOf(u.dept)};width:14px;height:14px"></span>${esc(user)}
        <small>${esc(u.dept)} · agent${u.agents && u.agents.includes(",") ? "s" : ""} ${esc(u.agents)} · first seen ${dt(u.first_seen)} · last seen ${dt(u.last_seen)}</small></h1>
      ${kpis(t)}
      <div class="grid">
        <section class="card span-8"><div class="row"><h2>${single ? "By hour" : "Activity over time"}</h2>${metricPicker("metric", q.metric || "calls")}</div><div id="series"></div></section>
        <section class="card span-4"><h2>Tools the LLM called</h2><div id="tools"></div></section>
        <section class="card span-12"><div class="row"><h2>Sessions</h2>
          <div class="seg" id="lvl">${["all", ...LEVEL].map((l) => `<button data-l="${l}" class="${(q.level || "all") === l ? "on" : ""}">${l === "all" ? "all" : "≥ " + l}</button>`).join("")}</div></div>
          <div class="tbl-wrap" id="sessions"></div></section>
        <section class="card span-12"><h2>When (weekday × hour, UTC)</h2><div id="heat"></div></section>
      </div>`;
    const series = single ? (await api("overview", { bucket: "hour", user })).series : d.series;
    seriesChart($("#series"), series, { onClick: single ? null : bucketClick, metric: q.metric });
    $("#metric").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => go(parseHash().path, { metric: b.dataset.m })));
    hbars($("#tools"), d.tools.slice(0, 18).map((x) => ({ key: x.tool, value: x.calls })));
    heatmap($("#heat"), d.heatmap);
    const sessions = d.sessions.filter((s) => !q.level || q.level === "all" || rank(s.max_level) >= rank(q.level));
    sessionsTable($("#sessions"), sessions);
    $("#lvl").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => go(parseHash().path, { level: b.dataset.l === "all" ? "" : b.dataset.l })));
  }
  const rank = (lv) => LEVEL.indexOf(lv) + 1;

  function sessionsTable(container, sessions, showUser) {
    if (!sessions.length) { container.innerHTML = '<div class="empty">No sessions match.</div>'; return; }
    container.innerHTML = `<table><thead><tr><th>Started</th>${showUser ? "<th>User</th>" : ""}<th>Session</th><th>Title / first message</th>
      <th class="num">Calls</th><th class="num">Tokens</th><th class="num">Length</th><th>Firewall</th></tr></thead><tbody>
      ${sessions.map((s) => `<tr data-s="${esc(s.session)}">
        <td class="muted" style="white-space:nowrap">${dt(s.started)}</td>${showUser ? `<td>${esc(s.user)}</td>` : ""}
        <td class="mono">${esc(s.session.slice(0, 14))}</td><td>${esc((s.title || "").slice(0, 90))}</td>
        <td class="num">${s.calls}</td><td class="num">${fmt(s.tokens)}</td><td class="num">${dur(s.started, s.ended)}</td>
        <td>${fwBadges(s.firewall) || badge(s.max_level)}${s.blocked ? ' <span class="badge out">blocked</span>' : ""}</td></tr>`).join("")}
      </tbody></table>`;
    container.querySelectorAll("tr[data-s]").forEach((tr) => tr.addEventListener("click", () => go("/s/" + encodeURIComponent(tr.dataset.s))));
  }

  async function viewSession(id) {
    const d = await api("session/" + encodeURIComponent(id));
    const q = parseHash().q;
    crumbs([`<a href="${link("/u/" + encodeURIComponent(d.user))}">${esc(d.user)}</a>`,
      `<a href="${link("/u/" + encodeURIComponent(d.user), { from: d.started.slice(0, 10), to: d.started.slice(0, 10), range: "custom" })}">${dayLabel(d.started.slice(0, 10))}</a>`,
      `<span>session ${esc(id.slice(0, 14))}</span>`]);
    const sigs = d.steps.flatMap((s) => s.signals).concat(d.loose_signals);
    const fw = {}; sigs.forEach((s) => (fw[s.level] = (fw[s.level] || 0) + 1));
    const labels = Object.entries(d.labels || {}).map(([k, v]) => `<span class="badge out">${esc(k)}: ${esc(v)}</span>`).join(" ");
    view.innerHTML = `
      <h1>${esc(d.labels.title || "Session " + id.slice(0, 14))} <small>${esc(d.user)} · ${esc(d.dept || "")} · ${dt(d.started)} → ${time(d.ended)} (${dur(d.started, d.ended)})</small></h1>
      <div class="kpis">
        <div class="kpi"><div class="v">${d.totals.calls}</div><div class="l">LLM calls</div></div>
        <div class="kpi"><div class="v">${fmt(d.totals.tokens)}</div><div class="l">tokens</div></div>
        <div class="kpi"><div class="v">${d.steps.reduce((n, s) => n + ((s.output && s.output.tool_calls) || []).length, 0)}</div><div class="l">tool calls</div></div>
        ${META.has_signals ? LEVEL.map((l) => `<div class="kpi lv-${l}"><div class="v">${fw[l] || 0}</div><div class="l">${l}</div></div>`).join("") : ""}
      </div>
      <div class="card" style="margin-bottom:12px">
        <div style="margin-bottom:6px">${labels}</div>
        <details><summary>System prompt (${fmt((d.system_prompt || "").length)} chars)</summary><div class="msg system" style="margin-top:6px">${esc(d.system_prompt || "(none)")}</div></details>
        <details><summary>Tools offered to the LLM (${d.tools.length})</summary><div style="margin-top:6px">${d.tools.map((t) => `<span class="tc">${esc(t)}</span>`).join("")}</div></details>
        ${d.loose_signals.length || d.loose_actions.length ? `<details open><summary>Session-level firewall events</summary>${d.loose_signals.map(sigHtml).join("")}${d.loose_actions.map(actHtml).join("")}</details>` : ""}
      </div>
      <div class="steps">${d.steps.map((s, i) => stepHtml(s, i)).join("")}</div>`;
    view.querySelectorAll("[data-raw]").forEach((b) => b.addEventListener("click", () => showRaw(b.dataset.raw)));
    if (q.call) {
      const el = document.getElementById("call-" + q.call);
      if (el) { el.classList.add("hl"); el.scrollIntoView({ block: "center" }); }
    }
  }

  function stepHtml(s, i) {
    const lv = s.firewall_level || s.signals.reduce((m, x) => rank(x.level) > rank(m) ? x.level : m, null);
    const blocked = s.actions.some((a) => a.action === "replace_response") || s.firewall_level === "block";
    const out = s.output || {};
    return `<article class="step ${lv ? "lv-" + lv : ""}" id="call-${s.call_id}">
      <div class="step-head"><b>#${i + 1}</b><span>${time(s.ts)}</span><span class="mono">${esc(s.upstream_model || s.model || "")}</span>
        <span>${fmt(s.prompt_tokens)} in · ${fmt(s.completion_tokens)} out</span><span>${s.duration_ms != null ? (s.duration_ms / 1000).toFixed(1) + "s" : ""}</span>
        <span>${esc(s.finish_reason || "")}</span>${badge(lv)}${s.status >= 400 ? `<span class="badge block">HTTP ${s.status}</span>` : ""}
        <span class="sp"></span><button class="icon" data-raw="${s.call_id}" title="Raw request and response">{ } raw</button></div>
      <div class="msgs">
        ${s.input.map(msgHtml).join("")}
        ${s.error ? `<div class="msg blocked"><span class="who">error</span>${esc(typeof s.error === "string" ? s.error : JSON.stringify(s.error))}</div>` : ""}
        ${out.content || out.tool_calls ? `<div class="msg assistant ${blocked ? "blocked" : ""}"><span class="who">${blocked ? "proxy (answering as the LLM: blocked)" : "LLM"}</span>${esc(out.content || "")}${(out.tool_calls || []).map(tcHtml).join("")}</div>` : ""}
      </div>
      ${s.signals.map(sigHtml).join("")}${s.actions.map(actHtml).join("")}
    </article>`;
  }
  function msgHtml(m) {
    const who = m.role === "tool" ? `tool result${m.name ? " · " + m.name : ""}` : m.role === "user" ? "user / agent" : m.role;
    let content = m.content || "";
    if (m.role === "tool") { try { content = JSON.stringify(JSON.parse(content), null, 1); } catch (e) { /* not JSON */ } }
    return `<div class="msg ${esc(m.role)}"><span class="who">${esc(who)}</span>${esc(content)}${(m.tool_calls || []).map(tcHtml).join("")}</div>`;
  }
  function tcHtml(tc) {
    const f = tc.function || {};
    let args = f.arguments || "";
    try { args = JSON.stringify(JSON.parse(args), null, 1); } catch (e) { /* keep raw */ }
    return `<span class="tc">🔧 <b>${esc(f.name)}</b><details><summary>args</summary>${esc(args)}</details></span>`;
  }
  function sigHtml(s) {
    return `<div class="sig">${badge(s.level)}<div><b>${esc(s.topic)}</b> <span class="muted">· ${esc(s.detector)}${s.rule ? " · " + esc(s.rule) : ""} · ${esc(s.direction || "")}${s.confidence != null ? " · conf " + s.confidence : ""}</span>
      ${s.matched ? `<div>matched: <span class="mono">${esc(s.matched)}</span></div>` : ""}
      ${s.rationale ? `<div class="why">${esc(s.rationale)}</div>` : ""}</div></div>`;
  }
  function actHtml(a) {
    return `<div class="sig"><span class="badge out">${esc(a.action.replace("_", " "))}</span><div><b>${esc(a.actor)}</b> <span class="muted">${dt(a.ts)}${a.topic ? " · " + esc(a.topic) : ""}</span><div class="why">${esc(a.reason || "")}</div></div></div>`;
  }
  async function showRaw(id) {
    const c = await api("call/" + id);
    $("#modal-title").textContent = `Call ${id} · ${c.ts} · ${c.user}`;
    $("#modal-body").innerHTML = `<h2>Request</h2><pre class="json">${esc(JSON.stringify(c.request, null, 2))}</pre>
      <h2>Response</h2><pre class="json">${esc(JSON.stringify(c.response, null, 2))}</pre>
      <h2>Usage and labels</h2><pre class="json">${esc(JSON.stringify({ usage: c.usage, labels: c.labels, route: c.route, attempts: c.attempts, firewall_level: c.firewall_level }, null, 2))}</pre>`;
    $("#modal").showModal();
  }

  async function viewFirewall() {
    crumbs(["<span>Firewall</span>"]);
    const q = parseHash().q;
    if (!META.has_signals) {
      view.innerHTML = `<div class="card empty"><h1 style="justify-content:center">No firewall in this log</h1>
        This log follows K-log-schema@1 (proxy + logging only): it has no <span class="mono">signals</span> or <span class="mono">admin_actions</span> tables.
        Logs written by llm-proxy-firewall (K-log-schema@2) show findings here.</div>`;
      return;
    }
    const [d, ov] = await Promise.all([api("firewall", { level: q.level, topic: q.topic }), api("overview")]);
    const topics = [...new Set(d.topics.map((t) => t.topic))];
    const cell = (tp, lv) => (d.topics.find((t) => t.topic === tp && t.level === lv) || {}).n || 0;
    const fw = ov.totals.firewall;
    view.innerHTML = `
      <h1>Firewall <small>${fmt((fw.info || 0) + (fw.warning || 0) + (fw.block || 0))} findings · ${d.actions.length} admin actions${q.level || q.topic ? " · filtered" : ""}</small></h1>
      <div class="kpis">${LEVEL.map((l) => `<div class="kpi lv-${l}"><div class="v">${fw[l] || 0}</div><div class="l">${l}</div></div>`).join("")}
        <div class="kpi"><div class="v">${ov.totals.blocked_calls}</div><div class="l">calls answered by the proxy</div></div>
        <div class="kpi"><div class="v">${new Set(d.events.map((e) => e.user)).size}</div><div class="l">users flagged</div></div></div>
      <div class="grid">
        <section class="card span-8"><h2>Findings over time</h2><div id="series"></div></section>
        <section class="card span-4"><h2>Topic × level</h2><table class="matrix"><thead><tr><th>Topic</th>${LEVEL.map((l) => `<th class="num">${l}</th>`).join("")}</tr></thead><tbody>
          ${topics.map((tp) => `<tr><td><a href="${link("/fw", { topic: tp }, ["level"])}">${esc(tp)}</a></td>${LEVEL.map((l) => {
            const n = cell(tp, l);
            return `<td class="num cell"><a href="${link("/fw", { topic: tp, level: l })}" style="color:${n ? css("--" + l) : css("--muted")}">${n || "·"}</a></td>`;
          }).join("")}</tr>`).join("")}</tbody></table>
          <h2 style="margin-top:14px">By detector</h2><div id="det"></div></section>
        <section class="card span-12"><div class="row"><h2>Findings</h2><div class="seg" id="lvl">${["all", ...LEVEL].map((l) => `<button data-l="${l}" class="${(q.level || "all") === l ? "on" : ""}">${l}</button>`).join("")}</div></div>
          <div class="tbl-wrap"><table><thead><tr><th>When</th><th>User</th><th>Level</th><th>Topic</th><th>Detector</th><th>What matched / why</th></tr></thead><tbody>
          ${d.events.map((e) => `<tr data-s="${esc(e.session)}" data-c="${e.call_id || ""}"><td class="muted" style="white-space:nowrap">${dt(e.ts)}</td><td>${esc(e.user)}</td>
            <td>${badge(e.level)}</td><td>${esc(e.topic)}</td><td class="muted">${esc(e.detector)}</td>
            <td>${esc((e.matched ? e.matched + " — " : "") + (e.rationale || e.rule || "")).slice(0, 160)}</td></tr>`).join("") || '<tr><td colspan="6" class="empty">No findings match.</td></tr>'}
          </tbody></table></div></section>
        <section class="card span-12"><h2>Admin actions (automatic and manual)</h2><div class="tbl-wrap"><table><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>User</th><th>Topic</th><th>Reason</th></tr></thead><tbody>
          ${d.actions.map((a) => `<tr data-s="${esc(a.session)}" data-c="${a.call_id || ""}"><td class="muted">${dt(a.ts)}</td><td>${esc(a.actor)}</td><td><span class="badge out">${esc(a.action)}</span></td>
            <td>${esc(a.user)}</td><td>${esc(a.topic || "")}</td><td>${esc((a.reason || "").slice(0, 140))}</td></tr>`).join("") || '<tr><td colspan="6" class="empty">None.</td></tr>'}
          </tbody></table></div></section>
      </div>`;
    seriesChart($("#series"), ov.series, { onClick: bucketClick, metric: "firewall" });
    const det = {}; d.detectors.forEach((x) => (det[x.detector] = (det[x.detector] || 0) + x.n));
    hbars($("#det"), Object.entries(det).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ key: k, value: v })));
    view.querySelectorAll("tr[data-s]").forEach((tr) => tr.addEventListener("click", () => go("/s/" + encodeURIComponent(tr.dataset.s), { call: tr.dataset.c })));
    $("#lvl").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => go("/fw", { level: b.dataset.l === "all" ? "" : b.dataset.l })));
  }

  async function viewSearch(text) {
    crumbs([`<span>search “${esc(text)}”</span>`]);
    $("#q").value = text;
    const rows = await api("search", { q: text });
    view.innerHTML = `<h1>Search <small>${rows.length}${rows.length === 100 ? "+" : ""} calls contain “${esc(text)}”</small></h1>
      <div class="card"><table><thead><tr><th>When</th><th>User</th><th>Session</th><th>Snippet</th></tr></thead><tbody>
      ${rows.map((r) => `<tr data-s="${esc(r.session)}" data-c="${r.id}"><td class="muted" style="white-space:nowrap">${dt(r.ts)}</td><td>${esc(r.user)}</td>
        <td class="mono">${esc(r.session.slice(0, 14))}</td><td>${highlight(r.snippet || "", text)}</td></tr>`).join("") || '<tr><td colspan="4" class="empty">No match.</td></tr>'}</tbody></table></div>`;
    view.querySelectorAll("tr[data-s]").forEach((tr) => tr.addEventListener("click", () => go("/s/" + encodeURIComponent(tr.dataset.s), { call: tr.dataset.c })));
  }
  const highlight = (s, t) => esc(s).replace(new RegExp(esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "ig"), (m) => `<mark>${m}</mark>`);

  let galaxyMod = null;
  async function viewGalaxy() {
    crumbs(["<span>Galaxy 3D</span>"]);
    view.innerHTML = `<div class="galaxy-wrap" id="galaxy"><div class="empty" style="color:#9aa3ae">Loading the galaxy…</div></div>`;
    const data = await api("galaxy");
    galaxyMod = galaxyMod || await import("./galaxy.js");
    if (!document.getElementById("galaxy")) return;   // navigated away while loading
    galaxyMod.mount($("#galaxy"), data, {
      deptColor: colorOf, levelColor: (lv) => ({ info: "#5aa2f0", warning: "#f0aa2c", block: "#f06262" }[lv] || "#8b95a3"),
      loadSession: (id) => api("session/" + encodeURIComponent(id)),
      openUser: (u) => go("/u/" + encodeURIComponent(u)),
      openSession: (s, call) => go("/s/" + encodeURIComponent(s), { call }),
      esc, fmt, dt,
    });
  }

  // ---- router ----------------------------------------------------------------------------------
  async function route() {
    if (galaxyMod && galaxyMod.unmount) galaxyMod.unmount();
    routeToken++;
    syncControls();
    const { path, q } = parseHash();
    const db = q.db || (DBS[0] && DBS[0].name);
    if (!META || META.name !== db) {
      try { META = await api("meta"); } catch (e) { if (e instanceof Stale) return; throw e; }
      deptColor = {}; META.depts.forEach((d, i) => (deptColor[d] = DEPT_COLORS[i % DEPT_COLORS.length]));
    }
    try {
      if (path.startsWith("/u/")) await viewUser(decodeURIComponent(path.slice(3)));
      else if (path.startsWith("/s/")) await viewSession(decodeURIComponent(path.slice(3)));
      else if (path.startsWith("/fw")) await viewFirewall();
      else if (path.startsWith("/galaxy")) await viewGalaxy();
      else if (path.startsWith("/search")) await viewSearch(q.q || "");
      else await viewGlobal();
    } catch (e) {
      if (e instanceof Stale) return;
      view.innerHTML = `<div class="card empty">Could not load this view: ${esc(e.message)}</div>`;
      console.error(e);
    }
  }
  let lastPath = null;
  window.addEventListener("hashchange", () => {
    const p = parseHash().path;
    route().then(() => { if (p !== lastPath) window.scrollTo(0, 0); lastPath = p; });
  });
  let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => !parseHash().path.startsWith("/galaxy") && route(), 250); });

  (async function init() {
    DBS = (await (await fetch("/api/dbs")).json()).dbs;
    $("#db").innerHTML = DBS.map((d) => `<option value="${esc(d.name)}">${esc(d.name)} (${fmt(d.calls)} calls)</option>`).join("");
    lastPath = parseHash().path;
    route();
  })();
})();
