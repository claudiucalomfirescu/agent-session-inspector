/* Galaxy 3D: the same hierarchy as the drill-down, as a space you can fly around.

   star    = a user (size: calls, colour: department, red/amber halo: worst firewall level)
   planet  = one of their sessions, orbiting them (size: tokens, colour: worst firewall level)
   moon    = one LLM call of a session, shown when you click the session (colour: its firewall level)

   Drag to rotate, scroll to zoom, right-drag to pan. Click a star to fly to it, a planet to open its
   calls, a moon to read that message. Every panel links back into the 2D drill-down. */
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";

let state = null;

export function unmount() {
  if (!state) return;
  cancelAnimationFrame(state.raf);
  state.ro.disconnect();
  state.renderer.dispose();
  state.renderer.domElement.remove();
  window.removeEventListener("keydown", state.onKey);
  state = null;
}

export function mount(container, data, h) {
  unmount();
  container.innerHTML = "";
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const W = () => container.clientWidth, H = () => container.clientHeight;
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(W(), H());
  container.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#05070c");
  scene.fog = new THREE.FogExp2("#05070c", 0.00045);
  const camera = new THREE.PerspectiveCamera(55, W() / H(), 0.5, 5000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.autoRotate = !reduced;
  controls.autoRotateSpeed = 0.35;
  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const sun = new THREE.PointLight(0xffffff, 1.4, 0, 0);
  scene.add(sun);

  // background stars
  const sg = new THREE.BufferGeometry(), pos = [];
  for (let i = 0; i < 2500; i++) {
    const r = 1400 + Math.random() * 1200, t = Math.random() * Math.PI * 2, p = Math.acos(2 * Math.random() - 1);
    pos.push(r * Math.sin(p) * Math.cos(t), r * Math.cos(p), r * Math.sin(p) * Math.sin(t));
  }
  sg.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  scene.add(new THREE.Points(sg, new THREE.PointsMaterial({ color: 0x8899aa, size: 2, sizeAttenuation: false })));

  // users grouped by department around the centre, departments as arcs
  const users = data.users.filter((u) => u.calls > 0);
  const depts = [...new Set(users.map((u) => u.dept))];
  const pickables = [], userNodes = {}, sessionsBy = {}, glows = [];
  let frozen = false;   // orbits stop while a session is open, so the camera stays on it
  const dimGlows = (on) => glows.forEach((g) => (g.material.opacity = on ? 0.12 : 1));
  // isolate one planet: its siblings step aside so the moons are visible
  const isolate = (keep) => Object.values(userNodes).forEach((n) => n.orbit.children.forEach((p) => (p.visible = !keep || p === keep || p.parent !== keep.parent)));
  data.sessions.forEach((s) => (sessionsBy[s.user] = sessionsBy[s.user] || []).push(s));
  const maxCalls = Math.max(1, ...users.map((u) => u.calls));
  const R = 140 + users.length * 9;
  const HOME = R * 2.3;
  camera.position.set(0, HOME * 0.55, HOME * 0.85);
  let idx = 0;
  const total = users.length;
  const label = (text, color) => {
    const c = document.createElement("canvas"), ctx = c.getContext("2d");
    c.width = 512; c.height = 96;
    ctx.font = "600 40px system-ui, sans-serif";
    ctx.fillStyle = color; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text.length > 22 ? text.slice(0, 21) + "…" : text, 256, 48);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
    sp.scale.set(80, 15, 1);
    return sp;
  };
  depts.forEach((dept) => {
    const du = users.filter((u) => u.dept === dept).sort((a, b) => b.calls - a.calls);
    const a0 = (idx / total) * Math.PI * 2;
    du.forEach((u) => {
      const a = (idx++ / total) * Math.PI * 2 + 0.0001;
      const r = R * (0.85 + 0.3 * ((idx % 3) / 2));
      const y = ((idx % 5) - 2) * 14;
      const size = 4 + 14 * Math.sqrt(u.calls / maxCalls);
      const color = new THREE.Color(h.deptColor(u.dept));
      const star = new THREE.Mesh(new THREE.SphereGeometry(size, 24, 16), new THREE.MeshBasicMaterial({ color }));
      star.position.set(Math.cos(a) * r, y, Math.sin(a) * r);
      star.userData = { kind: "user", u, size };
      const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex(), color: u.max_level === "block" ? 0xf06262 : u.max_level === "warning" ? 0xf0aa2c : color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
      glow.scale.setScalar(size * (u.max_level === "block" || u.max_level === "warning" ? 7 : 4.5));
      star.add(glow);
      glows.push(glow);
      const tag = label(u.user, "#dfe6ee");
      tag.position.set(0, size + 9, 0);
      star.add(tag);
      scene.add(star);
      pickables.push(star);
      // planets: sessions on tilted orbits
      const ss = (sessionsBy[u.user] || []).slice().sort((x, y2) => (x.started < y2.started ? -1 : 1));
      const orbit = new THREE.Group();
      orbit.rotation.x = 0.35 * Math.sin(idx);
      orbit.rotation.z = 0.25 * Math.cos(idx);
      star.add(orbit);
      const maxTok = Math.max(1, ...ss.map((s) => s.tokens || 0));
      ss.forEach((s, i) => {
        const ring = size + 8 + (i % 4) * 5 + Math.floor(i / 24) * 6;
        const ang = (i / Math.max(ss.length, 1)) * Math.PI * 2 * (1 + Math.floor(i / 24));
        const ps = 1 + 3.2 * Math.sqrt((s.tokens || 0) / maxTok);
        const planet = new THREE.Mesh(new THREE.SphereGeometry(ps, 12, 8),
          new THREE.MeshStandardMaterial({ color: h.levelColor(s.max_level), emissive: h.levelColor(s.max_level), emissiveIntensity: s.max_level ? 0.8 : 0.15, roughness: 0.6 }));
        planet.position.set(Math.cos(ang) * ring, 0, Math.sin(ang) * ring);
        planet.userData = { kind: "session", s, u };
        orbit.add(planet);
        pickables.push(planet);
      });
      userNodes[u.user] = { star, orbit, u };
    });
    // department label on the outer rim
    const mid = (a0 + (idx / total) * Math.PI * 2) / 2;
    const dl = label(dept, h.deptColor(dept));
    dl.scale.set(150, 28, 1);
    dl.position.set(Math.cos(mid) * (R * 1.45), 40, Math.sin(mid) * (R * 1.45));
    scene.add(dl);
  });
  const core = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex(), color: 0x6ea1ff, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  core.scale.setScalar(120);
  scene.add(core);
  const coreLabel = label("LLM proxy", "#9fc0ff"); coreLabel.position.set(0, 26, 0); scene.add(coreLabel);

  // overlays
  const legend = document.createElement("div");
  legend.className = "glegend";
  legend.innerHTML = `<b>${users.length} users · ${data.sessions.length} sessions</b>
    <span>★ star = user, colour = department</span><span>● planet = session</span>
    <span><span class="dot" style="background:#8b95a3"></span>clean <span class="dot" style="background:#5aa2f0;margin-left:8px"></span>info
    <span class="dot" style="background:#f0aa2c;margin-left:8px"></span>warning <span class="dot" style="background:#f06262;margin-left:8px"></span>block</span>`;
  const help = document.createElement("div");
  help.className = "ghelp";
  help.textContent = "drag: rotate · scroll: zoom · right-drag: pan · click: select · Esc: overview";
  const panel = document.createElement("div");
  panel.className = "gpanel";
  panel.hidden = true;
  const tools = document.createElement("div");
  tools.className = "gtools";
  tools.innerHTML = `<button data-a="spin">${controls.autoRotate ? "Pause spin" : "Spin"}</button><button data-a="home">Overview</button>`;
  container.append(legend, help, panel, tools);
  const tip = document.getElementById("tip");

  // camera flights
  let flight = null;
  function flyTo(target, dist) {
    const from = { p: camera.position.clone(), t: controls.target.clone() };
    const dir = camera.position.clone().sub(controls.target).normalize();
    const to = { t: target.clone(), p: target.clone().add(dir.multiplyScalar(dist)) };
    flight = { from, to, t0: performance.now(), ms: reduced ? 1 : 900 };
  }
  const home = () => { panel.hidden = true; clearMoons(); frozen = false; dimGlows(false); isolate(null); flyTo(new THREE.Vector3(0, 0, 0), HOME); };
  tools.addEventListener("click", (e) => {
    const a = e.target.dataset.a;
    if (a === "spin") { controls.autoRotate = !controls.autoRotate; e.target.textContent = controls.autoRotate ? "Pause spin" : "Spin"; }
    if (a === "home") home();
  });
  const onKey = (e) => { if (e.key === "Escape") home(); };
  window.addEventListener("keydown", onKey);

  // moons: the calls of the selected session
  let moons = null;
  function clearMoons() { if (moons) { moons.parent.remove(moons); moons.children.forEach((m) => { const i = pickables.indexOf(m); if (i >= 0) pickables.splice(i, 1); }); moons = null; } }
  async function openSession(planet) {
    const { s, u } = planet.userData;
    controls.autoRotate = false;
    frozen = true;
    dimGlows(true);
    isolate(planet);
    tools.querySelector("[data-a=spin]").textContent = "Spin";
    const wp = new THREE.Vector3(); planet.getWorldPosition(wp);
    flyTo(wp, 48);
    panel.hidden = false;
    panel.innerHTML = `<h3>${h.esc(s.title || "Session " + s.session.slice(0, 12))}</h3><div class="muted">${h.esc(u.user)} · ${h.dt(s.started)} · ${s.calls} calls · ${h.fmt(s.tokens)} tokens</div><div class="muted">loading calls…</div>`;
    const d = await h.loadSession(s.session);
    clearMoons();
    moons = new THREE.Group();
    planet.add(moons);
    d.steps.forEach((st, i) => {
      const lv = st.firewall_level || st.signals.reduce((m, x) => (["info", "warning", "block"].indexOf(x.level) > ["info", "warning", "block"].indexOf(m) ? x.level : m), null);
      const a = (i / d.steps.length) * Math.PI * 2, r = 8 + (i % 2) * 2;
      const moon = new THREE.Mesh(new THREE.SphereGeometry(1.1 + (st.output && st.output.tool_calls ? 0.4 : 0), 12, 8),
        new THREE.MeshBasicMaterial({ color: lv ? h.levelColor(lv) : 0xdfe6ee }));
      moon.position.set(Math.cos(a) * r, Math.sin(i * 0.9) * 2, Math.sin(a) * r);
      moon.userData = { kind: "call", st, i, s };
      moons.add(moon);
      pickables.push(moon);
    });
    panel.innerHTML = `<h3>${h.esc(d.labels.title || s.title || "Session")}</h3>
      <div class="muted">${h.esc(u.user)} · ${h.dt(d.started)} · ${d.steps.length} calls · ${h.fmt(d.totals.tokens)} tokens</div>
      <p><a href="#" data-open>Open in drill-down →</a></p>
      ${d.steps.map((st, i) => `<div class="gstep" data-i="${i}"><b>#${i + 1}</b> ${(st.ts || "").slice(11, 16)}
        ${st.signals.map((x) => `<span class="badge ${x.level}">${x.level}</span>`).join(" ")}
        <div class="muted">${h.esc(summary(st))}</div></div>`).join("")}`;
    panel.querySelector("[data-open]").addEventListener("click", (e) => { e.preventDefault(); h.openSession(s.session); });
    panel.querySelectorAll(".gstep").forEach((el) => el.addEventListener("click", () => h.openSession(s.session, d.steps[+el.dataset.i].call_id)));
  }
  const summary = (st) => {
    const out = st.output || {};
    if (out.tool_calls && out.tool_calls.length) return "→ " + out.tool_calls.map((t) => (t.function || {}).name).join(", ");
    const inp = st.input.filter((m) => m.role === "user").map((m) => m.content).join(" ");
    return (out.content || inp || "").slice(0, 110);
  };
  function openUser(star) {
    const { u } = star.userData;
    clearMoons();
    frozen = false;
    dimGlows(false);
    isolate(null);
    const wp = new THREE.Vector3(); star.getWorldPosition(wp);
    flyTo(wp, 90 + star.userData.size * 3);
    panel.hidden = false;
    const ss = (sessionsBy[u.user] || []);
    const flagged = ss.filter((s) => s.max_level === "warning" || s.max_level === "block");
    panel.innerHTML = `<h3>${h.esc(u.user)}</h3><div class="muted">${h.esc(u.dept)} · ${h.fmt(u.calls)} calls · ${u.sessions} sessions · ${h.fmt(u.tokens)} tokens</div>
      <p><a href="#" data-open>Open ${h.esc(u.user)} in drill-down →</a></p>
      ${flagged.length ? `<b>Flagged sessions</b>${flagged.slice(0, 12).map((s) => `<div class="gstep" data-s="${h.esc(s.session)}"><span class="badge ${s.max_level}">${s.max_level}</span> ${h.dt(s.started)}<div class="muted">${h.esc((s.title || "").slice(0, 90))}</div></div>`).join("")}` : '<div class="muted">No warnings or blocks.</div>'}
      <p class="muted">Click a planet to see its calls.</p>`;
    panel.querySelector("[data-open]").addEventListener("click", (e) => { e.preventDefault(); h.openUser(u.user); });
    panel.querySelectorAll("[data-s]").forEach((el) => el.addEventListener("click", () => {
      const p = userNodes[u.user].orbit.children.find((c) => c.userData.s && c.userData.s.session === el.dataset.s);
      if (p) openSession(p);
    }));
  }

  // picking
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  let hovered = null, downAt = null;
  const pick = (ev) => {
    const r = renderer.domElement.getBoundingClientRect();
    mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(pickables, false).find((x) => x.object.visible);
    return hit && hit.object;
  };
  renderer.domElement.addEventListener("pointermove", (ev) => {
    const o = pick(ev);
    hovered = o;
    renderer.domElement.style.cursor = o ? "pointer" : "grab";
    if (!o) { tip.hidden = true; return; }
    const d = o.userData;
    tip.innerHTML = d.kind === "user" ? `<b>${h.esc(d.u.user)}</b>${h.esc(d.u.dept)} · ${h.fmt(d.u.calls)} calls · ${d.u.sessions} sessions`
      : d.kind === "session" ? `<b>${h.esc((d.s.title || d.s.session).slice(0, 70))}</b>${h.esc(d.u.user)} · ${h.dt(d.s.started)} · ${d.s.calls} calls${d.s.max_level ? " · " + d.s.max_level : ""}`
      : `<b>Call #${d.i + 1}</b>${h.esc(summary(d.st))}`;
    tip.hidden = false;
    tip.style.left = ev.clientX + 14 + "px"; tip.style.top = ev.clientY + 14 + "px";
  });
  renderer.domElement.addEventListener("pointerleave", () => (tip.hidden = true));
  renderer.domElement.addEventListener("pointerdown", (ev) => (downAt = [ev.clientX, ev.clientY]));
  renderer.domElement.addEventListener("pointerup", (ev) => {
    if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 5) return;  // that was a drag
    const o = pick(ev);
    if (!o) return;
    const d = o.userData;
    if (d.kind === "user") openUser(o);
    else if (d.kind === "session") openSession(o);
    else if (d.kind === "call") {
      const st = d.st, out = st.output || {};
      panel.hidden = false;
      panel.innerHTML = `<h3>Call #${d.i + 1}</h3><div class="muted">${h.dt(st.ts)} · ${h.fmt(st.total_tokens)} tokens</div>
        ${st.input.map((m) => `<p><b>${h.esc(m.role)}</b><br>${h.esc((m.content || "").slice(0, 600))}</p>`).join("")}
        <p><b>LLM</b><br>${h.esc((out.content || "").slice(0, 600))}${(out.tool_calls || []).map((t) => `<br>🔧 ${h.esc((t.function || {}).name)}`).join("")}</p>
        ${st.signals.map((x) => `<p><span class="badge ${x.level}">${x.level}</span> ${h.esc(x.topic)} <span class="muted">${h.esc(x.rationale || x.matched || "")}</span></p>`).join("")}
        <p><a href="#" data-open>Open this call in drill-down →</a></p>`;
      panel.querySelector("[data-open]").addEventListener("click", (e) => { e.preventDefault(); h.openSession(d.s.session, st.call_id); });
    }
  });

  const ro = new ResizeObserver(() => { renderer.setSize(W(), H()); camera.aspect = W() / H(); camera.updateProjectionMatrix(); });
  ro.observe(container);
  const clock = new THREE.Clock();
  function frame() {
    const dt = clock.getDelta();
    if (!reduced && !frozen) Object.values(userNodes).forEach((n, i) => (n.orbit.rotation.y += dt * (0.08 + (i % 4) * 0.02)));
    if (moons && !reduced) moons.rotation.y += dt * 0.6;
    if (flight) {
      const k = Math.min(1, (performance.now() - flight.t0) / flight.ms), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      camera.position.lerpVectors(flight.from.p, flight.to.p, e);
      controls.target.lerpVectors(flight.from.t, flight.to.t, e);
      if (k >= 1) flight = null;
    }
    controls.update();
    renderer.render(scene, camera);
    state.raf = requestAnimationFrame(frame);
  }
  state = { renderer, ro, onKey, raf: 0 };
  // for tests and the explainer: where a user's star is on screen right now
  window.__galaxy = { screenOf(name) {
    const n = userNodes[name]; if (!n) return null;
    const v = new THREE.Vector3(); n.star.getWorldPosition(v); v.project(camera);
    const r = renderer.domElement.getBoundingClientRect();
    return { x: r.left + (v.x + 1) / 2 * r.width, y: r.top + (1 - v.y) / 2 * r.height };
  }, stopSpin() { controls.autoRotate = false; } };
  frame();
}

let _glow = null;
function glowTex() {
  if (_glow) return _glow;
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d"), grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, "rgba(255,255,255,1)"); grd.addColorStop(0.25, "rgba(255,255,255,.45)"); grd.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  _glow = new THREE.CanvasTexture(c);
  return _glow;
}
