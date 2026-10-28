/* dc-lite: a small runtime for the board pages in this folder.

The boards were drawn as Design Component pages: markup inside <x-dc> with {{holes}},
<sc-for list as>, <sc-if value>, onClick="{{handler}}", page basics in <helmet>, and a
`class Component extends DCLogic` script whose renderVals() feeds the holes. This file
implements just that subset, so the board files stay close to their canvas originals.

Props declared in data-props take their defaults; ?name=value in the URL overrides one.
*/
(function () {
  // Hide the raw template until it is rendered.
  document.write('<style>x-dc,helmet{display:none!important}</style>');

  const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', middot: '·', mdash: '—', ndash: '–', hellip: '…', rarr: '→', larr: '←', times: '×' };

  function decode(s) {
    return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
      if (e[0] === '#') return String.fromCodePoint(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
      return ENTITIES[e.toLowerCase()] ?? m;
    });
  }

  // Template source -> tree of {tag, attrs, children} and strings. The boards quote every
  // attribute and close every non-void element, so a small tokenizer is enough.
  function parse(src) {
    const root = { tag: '#root', attrs: [], children: [] };
    const stack = [root];
    const re = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>|[^<]+|</g;
    let m;
    while ((m = re.exec(src))) {
      const top = stack[stack.length - 1];
      if (m[0].startsWith('<!--')) continue;
      if (m[1]) {
        const tag = m[1].toLowerCase();
        for (let i = stack.length - 1; i > 0; i--) if (stack[i].tag === tag) { stack.length = i; break; }
      } else if (m[2]) {
        const node = { tag: m[2].toLowerCase(), attrs: [], children: [] };
        const ar = /([^\s=>\/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
        let a;
        while ((a = ar.exec(m[3] || ''))) node.attrs.push([a[1], decode(a[2] ?? a[3] ?? a[4] ?? '')]);
        top.children.push(node);
        if (!m[4] && !VOID.has(node.tag)) stack.push(node);
      } else {
        // Like JSX: whitespace that spans a line break is layout, not content.
        const text = m[0].replace(/^\s*\n\s*/, '').replace(/\s*\n\s*$/, '');
        if (text) top.children.push(decode(text));
      }
    }
    return root;
  }

  function lookup(path, scopes) {
    path = path.trim();
    if (path === 'true') return true;
    if (path === 'false') return false;
    const parts = path.split('.');
    for (let i = scopes.length - 1; i >= 0; i--) {
      if (scopes[i] != null && Object.prototype.hasOwnProperty.call(Object(scopes[i]), parts[0])) {
        let v = scopes[i][parts[0]];
        for (let j = 1; j < parts.length && v != null; j++) v = v[parts[j]];
        return v;
      }
    }
    return undefined;
  }

  const HOLE = /\{\{([^}]*)\}\}/g;
  const whole = s => { const m = /^\s*\{\{([^}]*)\}\}\s*$/.exec(s); return m ? m[1] : null; };
  const fill = (s, scopes) => s.replace(HOLE, (_, p) => { const v = lookup(p, scopes); return v == null ? '' : String(v); });

  // Tree + values -> fresh DOM nodes.
  function build(node, scopes, out, svg) {
    if (typeof node === 'string') { out.push(document.createTextNode(fill(node, scopes))); return; }
    const attr = n => (node.attrs.find(a => a[0] === n) || [])[1];
    if (node.tag === 'sc-for') {
      const list = lookup(whole(attr('list')) || '', scopes) || [];
      const as = attr('as') || 'item';
      Array.from(list).forEach((item, index) => node.children.forEach(c => build(c, scopes.concat([{ [as]: item, index }]), out, svg)));
      return;
    }
    if (node.tag === 'sc-if') {
      if (lookup(whole(attr('value')) || '', scopes)) node.children.forEach(c => build(c, scopes, out, svg));
      return;
    }
    const inSvg = svg || node.tag === 'svg';
    const el = inSvg ? document.createElementNS(SVG_NS, node.tag) : document.createElement(node.tag);
    node.attrs.forEach(([k, v]) => {
      if (k.startsWith('hint-')) return;
      if (/^on[A-Z]/.test(k)) {
        const fn = lookup(whole(v) || '', scopes);
        if (typeof fn === 'function') el['__dc_' + k.slice(2).toLowerCase()] = fn;
        return;
      }
      el.setAttribute(k, fill(v, scopes));
    });
    node.children.forEach(c => build(c, scopes, el.__kids || (el.__kids = []), inSvg));
    (el.__kids || []).forEach(k => el.appendChild(k));
    delete el.__kids;
    out.push(el);
  }

  // Patch the live DOM to match freshly built nodes, so scroll positions and focus survive.
  function morph(parent, fresh) {
    const old = Array.from(parent.childNodes);
    fresh.forEach((f, i) => {
      const o = old[i];
      if (!o || o.nodeType !== f.nodeType || o.nodeName !== f.nodeName) {
        o ? parent.replaceChild(f, o) : parent.appendChild(f);
        return;
      }
      if (o.nodeType === 3) { if (o.data !== f.data) o.data = f.data; return; }
      for (const a of Array.from(o.attributes)) if (!f.hasAttribute(a.name)) o.removeAttribute(a.name);
      for (const a of Array.from(f.attributes)) if (o.getAttribute(a.name) !== a.value) o.setAttribute(a.name, a.value);
      for (const k of Object.keys(o)) if (k.startsWith('__dc_') && !(k in f)) delete o[k];
      for (const k of Object.keys(f)) if (k.startsWith('__dc_')) o[k] = f[k];
      morph(o, Array.from(f.childNodes));
    });
    for (let i = old.length - 1; i >= fresh.length; i--) parent.removeChild(old[i]);
  }

  class DCLogic {
    constructor(props) { this.props = props || {}; this.state = {}; }
    setState(patch) {
      this.state = Object.assign({}, this.state, typeof patch === 'function' ? patch(this.state) : patch);
      this.__schedule && this.__schedule();
    }
    renderVals() { return {}; }
  }
  window.DCLogic = DCLogic;

  function readProps(script) {
    const props = {};
    let decl = {};
    try { decl = JSON.parse(script.getAttribute('data-props') || '{}'); } catch (e) { /* no props */ }
    Object.entries(decl).forEach(([k, d]) => { if (k[0] !== '$') props[k] = d && d.default; });
    new URLSearchParams(location.search).forEach((v, k) => {
      if (!(k in decl)) return;
      try { props[k] = JSON.parse(v); } catch (e) { props[k] = v; }
    });
    return props;
  }

  async function boot() {
    // Read the page's own source: the browser's parse would move <sc-for> out of tables.
    const src = await fetch(location.pathname, { cache: 'no-store' }).then(r => r.text());
    const tpl = /<x-dc>([\s\S]*)<\/x-dc>/.exec(src);
    if (!tpl) return;
    let body = tpl[1];
    const helmet = /<helmet>([\s\S]*?)<\/helmet>/.exec(body);
    if (helmet) {
      body = body.replace(helmet[0], '');
      const box = document.createElement('div');
      box.innerHTML = helmet[1];
      Array.from(box.childNodes).forEach(n => document.head.appendChild(n));
    }
    const script = document.querySelector('script[data-dc-script]');
    const Component = new Function('DCLogic', script.textContent + '\nreturn Component;')(DCLogic);
    const comp = new Component(readProps(script));
    const tree = parse(body);
    const mount = document.createElement('div');
    mount.className = 'dc-root';
    document.body.insertBefore(mount, document.body.firstChild);

    let queued = false;
    const render = () => {
      queued = false;
      const out = [];
      tree.children.forEach(c => build(c, [comp.renderVals()], out, false));
      morph(mount, out.filter(n => n.nodeType !== 3 || n.data.trim()));
    };
    comp.__schedule = () => { if (!queued) { queued = true; queueMicrotask(render); } };
    mount.addEventListener('click', e => {
      for (let el = e.target; el && el !== mount; el = el.parentNode) {
        if (el.__dc_click) { el.__dc_click(e); return; }
      }
    });
    render();
    if (comp.componentDidMount) comp.componentDidMount();
    window.addEventListener('pagehide', () => comp.componentWillUnmount && comp.componentWillUnmount());
  }

  document.addEventListener('DOMContentLoaded', () => boot().catch(err => {
    document.body.insertAdjacentHTML('afterbegin', '<pre style="color:#A3221B;padding:16px">dc-lite: ' + String(err && err.stack || err).replace(/</g, '&lt;') + '</pre>');
  }));
})();
