"""Build the animated replay of an off-site run: one self-contained HTML file (inline CSS/JS/SVG, no network).

    python3 -m offsite.replay offsite/runs/2026-10-31            # writes <run>/replay.html

The page plays the room's events back in order: the chat on the left, the table on the right with the
current speaker lit up, the agenda as a progress rail, and the game boards (icebreaker, idea votes) filling
in as the meeting reaches them. Play / pause / step / speed controls; reduced motion shows everything at once.
"""
import base64
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from offsite import agenda  # noqa: E402
from offsite.run import MODERATOR  # noqa: E402
from people.load import read_part  # noqa: E402

MOD_AVATAR = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><circle cx="100" cy="100" r="100" '
              'fill="#e7defa"/><circle cx="100" cy="82" r="38" fill="#c98f6b"/><path d="M58 76 Q60 30 100 32 Q142 30 '
              '144 80 Q130 52 100 54 Q72 52 58 76Z" fill="#6b3b22"/><path d="M34 200 Q38 140 100 132 Q162 140 166 200Z" '
              'fill="#7a5bd6"/><text x="100" y="186" font-size="26" text-anchor="middle" fill="#fff" '
              'font-family="sans-serif">HB</text></svg>')


def avatar_uri(agent_id):
    path = os.path.join(ROOT, "company", "avatars", agent_id + ".svg")
    svg = open(path, encoding="utf-8").read() if os.path.isfile(path) else MOD_AVATAR
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def unwrap(md):
    """Join hard-wrapped Markdown lines so the replay's tiny renderer sees one line per paragraph or item."""
    out = []
    for line in md.splitlines():
        cont = line.strip() and out and out[-1].strip() and not re.match(r"\s*([-#|]|\d+\.)", line) \
            and not out[-1].lstrip().startswith("#")
        if cont:
            out[-1] += " " + line.strip()
        else:
            out.append(line)
    return "\n".join(out)


def build(run_dir):
    events = [json.loads(l) for l in open(os.path.join(run_dir, "transcript.jsonl"), encoding="utf-8")]
    results = json.load(open(os.path.join(run_dir, "results.json"), encoding="utf-8"))
    meta = json.load(open(os.path.join(run_dir, "meta.json"), encoding="utf-8"))
    people = {}
    for ev in events:
        if ev["kind"] == "message" and ev["speaker"] not in people:
            people[ev["speaker"]] = {"name": ev["name"], "role": ev["role"], "avatar": avatar_uri(ev["speaker"])}
    for p in meta["attendees"] + [MODERATOR]:
        people.setdefault(p, {"name": p, "role": "", "avatar": avatar_uri(p)})
    for ev in events:  # model/latency metadata stays in transcript.jsonl; the replay does not need it
        ev.pop("call", None)
    for p in meta["attendees"]:  # identity cards: click a seat to read who they are
        try:
            people[p]["card"] = {part: unwrap(read_part(p, part)[1]) for part in ("job", "persona", "soul")}
        except OSError:
            pass
    data = {"events": events, "people": people, "seats": meta["attendees"], "moderator": MODERATOR,
            "segments": [{"id": s["id"], "title": s["title"]} for s in agenda.SEGMENTS],
            "results": {"two_truths": results.get("two_truths", {}), "vote": results.get("vote", {})},
            "meta": {k: meta[k] for k in ("started_utc", "finished_utc", "messages", "calls", "fake")}}
    html = TEMPLATE.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out = os.path.join(run_dir, "replay.html")
    open(out, "w", encoding="utf-8").write(html)
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VXC Motors Off-site</title>
<style>
:root{--bg:#f6f5f2;--panel:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e1dc;--accent:#1c69d4;--accent-soft:#e3eefc;
--scene:#fff7e0;--scene-ink:#7a5a00;--gold:#e0a400;--bar:#1c69d4;--you:#f0f4ff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111214;--panel:#1b1c1f;--ink:#ececef;--muted:#9a9aa2;
--line:#2c2d31;--accent:#5b9bff;--accent-soft:#1d2a40;--scene:#2a2414;--scene-ink:#f2c94c;--gold:#f2c94c;--bar:#5b9bff;--you:#1d2433}}
:root[data-theme="dark"]{--bg:#111214;--panel:#1b1c1f;--ink:#ececef;--muted:#9a9aa2;--line:#2c2d31;--accent:#5b9bff;--accent-soft:#1d2a40;
--scene:#2a2414;--scene-ink:#f2c94c;--gold:#f2c94c;--bar:#5b9bff;--you:#1d2433}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:18px 16px 8px;max-width:1240px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}header p{margin:0;color:var(--muted)}
.rail{display:flex;gap:4px;margin:14px 0 6px;flex-wrap:wrap}
.rail button{flex:1 1 110px;border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:8px;padding:6px 8px;
font-size:12px;cursor:pointer;text-align:left;position:relative;overflow:hidden}
.rail button .fill{position:absolute;left:0;bottom:0;height:3px;background:var(--accent);width:0;transition:width .3s}
.rail button.on{color:var(--ink);border-color:var(--accent)}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0}
.controls button,.controls select{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;padding:6px 12px;font-size:14px;cursor:pointer}
.controls .primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.controls .count{color:var(--muted);font-size:13px;margin-left:auto}
main{max-width:1240px;margin:0 auto;padding:0 16px 40px;display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:16px}
@media (max-width:860px){main{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px}
#chat{height:72vh;overflow-y:auto;padding:12px}
.msg{display:flex;gap:10px;padding:8px 6px;border-radius:10px;animation:in .35s ease}
.msg img{width:38px;height:38px;border-radius:50%;flex:none}
.msg .who{font-weight:600;font-size:14px}.msg .who span{font-weight:400;color:var(--muted);font-size:12px;margin-left:6px}
.msg .txt{white-space:pre-wrap;word-wrap:break-word}
.msg.mod{background:var(--accent-soft)}
.scene{margin:10px 0;padding:8px 12px;border-radius:10px;background:var(--scene);color:var(--scene-ink);font-size:13px;animation:in .35s ease}
.scene.seg{font-weight:700;text-transform:uppercase;letter-spacing:.04em;font-size:12px}
.typing{color:var(--muted);font-size:13px;padding:4px 8px;height:24px}
@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
aside{display:flex;flex-direction:column;gap:16px;min-width:0}
#table{padding:8px}#table svg{width:100%;height:auto;display:block}
.seat-name{font-size:11px;fill:var(--muted)}
.seat.on .ring{stroke:var(--gold);stroke-width:5}
.seat .ring{stroke:var(--line);stroke-width:2;fill:none;transition:stroke .2s}
.bubble{font-size:12px;fill:var(--ink)}
.board{padding:12px 14px}.board h2{font-size:14px;margin:0 0 8px}
.board .empty{color:var(--muted);font-size:13px}
.vrow{display:grid;grid-template-columns:1fr 90px 22px;gap:8px;align-items:center;font-size:13px;margin:4px 0}
.vbar{height:8px;border-radius:4px;background:var(--line);overflow:hidden}.vbar i{display:block;height:100%;background:var(--bar);width:0;transition:width .6s}
.badge{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;background:var(--accent-soft);margin:2px 4px 2px 0}
dialog{max-width:640px;width:calc(100% - 32px);border:1px solid var(--line);border-radius:14px;background:var(--panel);color:var(--ink);padding:0}
dialog::backdrop{background:#0006}dialog .hd{display:flex;gap:12px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line)}
dialog .hd img{width:56px;height:56px;border-radius:50%}dialog .bd{padding:4px 16px 16px;max-height:65vh;overflow:auto;font-size:14px}
dialog .tabs{display:flex;gap:6px;padding:10px 16px 0}dialog .tabs button{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:99px;padding:4px 12px;cursor:pointer}
dialog .tabs button.on{background:var(--accent);color:#fff;border-color:var(--accent)}dialog h3{font-size:14px;margin:14px 0 4px}dialog ul{margin:4px 0;padding-left:18px}
.seat{cursor:pointer}
footer{max-width:1240px;margin:0 auto;padding:0 16px 30px;color:var(--muted);font-size:12px}
@media (prefers-reduced-motion:reduce){.msg,.scene{animation:none}.vbar i,.rail .fill{transition:none}}
</style></head><body>
<header>
<h1>VXC Motors all-staff off-site</h1>
<p>Saturday 31 October 2026, The Old Mill. Twelve employee agents and a facilitator agent in one group chat;
every message is a real LLM call made as that person through the logging proxy. Click anyone at the table to read their persona, soul and job.</p>
<div class="rail" id="rail"></div>
<div class="controls">
<button class="primary" id="play">▶ Play</button><button id="step">Step</button><button id="all">Show all</button><button id="restart">Restart</button>
<select id="speed" aria-label="Speed"><option value="2600">0.5×</option><option value="1300" selected>1×</option><option value="550">2×</option><option value="180">5×</option></select>
<button id="theme" aria-label="Toggle light or dark theme">Theme</button>
<span class="count" id="count"></span></div>
</header>
<main>
<section class="card" aria-label="Chat"><div id="chat" role="log" aria-live="polite"></div><div class="typing" id="typing"></div></section>
<aside>
<div class="card" id="table"></div>
<div class="card board"><h2>Icebreaker · two truths and a lie</h2><div id="tt" class="empty">Revealed after the round.</div></div>
<div class="card board"><h2>Brainstorm vote</h2><div id="votes" class="empty">Ideas appear after the brainstorm.</div></div>
</aside>
</main>
<footer id="foot"></footer>
<dialog id="card"><div class="hd"><img id="cimg" alt=""><div><b id="cname"></b><div id="crole" style="color:var(--muted);font-size:13px"></div></div>
<button id="cclose" style="margin-left:auto;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:8px;padding:4px 10px;cursor:pointer">Close</button></div>
<div class="tabs" id="ctabs"></div><div class="bd" id="cbody"></div></dialog>
<script>
const D=/*DATA*/null;
const $=s=>document.querySelector(s), ev=D.events, P=D.people;
let i=0, timer=null;
const first=id=>(P[id]?.name||id).split(' ')[0];
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
// rail
D.segments.forEach(s=>{const b=document.createElement('button');b.dataset.seg=s.id;b.innerHTML=esc(s.title)+'<span class="fill"></span>';
 b.onclick=()=>{const k=ev.findIndex(e=>e.segment===s.id);if(k>=0){reset();while(i<=k)show(ev[i++]);sync();}};$('#rail').append(b)});
const segCount={};ev.forEach(e=>segCount[e.segment]=(segCount[e.segment]||0)+1);
// table: seats around an ellipse, moderator at the head
const seats=[D.moderator,...D.seats], W=540,H=420,cx=W/2,cy=H/2;
let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Meeting table"><ellipse cx="${cx}" cy="${cy}" rx="150" ry="78" fill="var(--accent-soft)" stroke="var(--line)"/>
<text x="${cx}" y="${cy-4}" text-anchor="middle" font-size="13" fill="var(--muted)">The Old Mill</text><text id="segtxt" x="${cx}" y="${cy+16}" text-anchor="middle" font-size="12" fill="var(--muted)"></text>`;
seats.forEach((id,k)=>{const a=-Math.PI/2+k*2*Math.PI/seats.length, x=cx+215*Math.cos(a), y=cy+150*Math.sin(a);
 svg+=`<g class="seat" id="seat-${id}" transform="translate(${x},${y})"><image href="${P[id].avatar}" x="-22" y="-22" width="44" height="44"/>
 <circle class="ring" r="24"/><text class="seat-name" y="38" text-anchor="middle">${esc(first(id))}</text></g>`});
svg+='<g id="bub"></g></svg>';$('#table').innerHTML=svg;
function bubble(id,text){const g=$('#bub');g.innerHTML='';if(!id)return;const s=$('#seat-'+id);if(!s)return;
 const t=s.getAttribute('transform').match(/[-\d.]+/g).map(Number);const w=170,x=Math.max(4,Math.min(W-w-4,t[0]-w/2)),y=t[1]<cy?t[1]+34:t[1]-82;
 const short=text.replace(/\s+/g,' ').slice(0,64)+(text.length>64?'…':'');
 g.innerHTML=`<rect x="${x}" y="${y}" width="${w}" height="40" rx="10" fill="var(--panel)" stroke="var(--gold)"/><foreignObject x="${x+6}" y="${y+3}" width="${w-12}" height="36"><div xmlns="http://www.w3.org/1999/xhtml" style="font-size:11px;line-height:1.25;color:var(--ink);overflow:hidden;height:34px">${esc(short)}</div></foreignObject>`}
function show(e){const c=$('#chat');
 if(e.kind==='scene'){const d=document.createElement('div');const seg=e.text.startsWith('Agenda:');d.className='scene'+(seg?' seg':'');
  d.textContent=(seg?'':e.time+' · ')+e.text;c.append(d);if(/Icebreaker results/.test(e.text))drawTT();if(/Idea board/.test(e.text))drawIdeas(false);if(/Vote result/.test(e.text))drawIdeas(true);}
 else{const d=document.createElement('div');d.className='msg'+(e.speaker===D.moderator?' mod':'');
  d.innerHTML=`<img alt="" src="${P[e.speaker].avatar}"><div><div class="who">${esc(e.name)}<span>${esc(e.role)} · ${e.time}</span></div><div class="txt">${esc(e.text)}</div></div>`;c.append(d);}
 c.scrollTop=c.scrollHeight;}
function sync(){const e=ev[i-1];document.querySelectorAll('.seat').forEach(s=>s.classList.remove('on'));
 if(e&&e.kind==='message'){$('#seat-'+e.speaker)?.classList.add('on');bubble(e.speaker,e.text)}else bubble(null);
 const seg=e?e.segment:null;$('#segtxt').textContent=seg?D.segments.find(s=>s.id===seg).title:'';
 document.querySelectorAll('#rail button').forEach(b=>{const done=ev.slice(0,i).filter(x=>x.segment===b.dataset.seg).length;
  b.querySelector('.fill').style.width=(100*done/segCount[b.dataset.seg]||0)+'%';b.classList.toggle('on',b.dataset.seg===seg)});
 $('#count').textContent=`${i} / ${ev.length} events`;
 const nx=ev[i];$('#typing').textContent=timer&&nx&&nx.kind==='message'?`${first(nx.speaker)} is typing…`:'';}
function drawTT(){const g=D.results.two_truths;if(!g.turns)return;
 const lies=g.turns.filter(t=>t.lie&&t.statements[t.lie-1]).map(t=>`<div style="font-size:13px;margin:3px 0"><b>${esc(first(t.who))}</b>: “${esc(t.statements[t.lie-1])}”</div>`).join('');
 $('#tt').className='';$('#tt').innerHTML=`<div>${(g.detectives||[]).map(p=>`<span class="badge">🔎 ${esc(first(p))}</span>`).join('')||'<span class="badge">No correct guesses</span>'}
 ${(g.fooled_everyone||[]).map(p=>`<span class="badge">🎭 ${esc(first(p))}</span>`).join('')}</div><div style="margin-top:6px;color:var(--muted);font-size:12px">🔎 guessed right · 🎭 lie got through</div>${lies}`}
function drawIdeas(withVotes){const v=D.results.vote;if(!v.ranking)return;const max=Math.max(1,...v.ranking.map(r=>r.votes));
 const rows=(withVotes?v.ranking:[...v.ranking].sort((a,b)=>a.n-b.n)).map(r=>`<div class="vrow"><div>${r.n}. ${esc(r.title)} <span style="color:var(--muted)">· ${esc(first(r.who))}</span></div><div class="vbar"><i data-w="${withVotes?100*r.votes/max:0}"></i></div><div>${withVotes?r.votes:''}</div></div>`).join('');
 $('#votes').className='';$('#votes').innerHTML=rows;requestAnimationFrame(()=>document.querySelectorAll('#votes .vbar i').forEach(x=>x.style.width=x.dataset.w+'%'))}
function tick(){if(i>=ev.length){pause();return}show(ev[i++]);sync();timer=setTimeout(tick,+$('#speed').value*(ev[i-1].kind==='scene'?0.6:1))}
function play(){if(timer)return;$('#play').textContent='❚❚ Pause';timer=setTimeout(tick,50)}
function pause(){clearTimeout(timer);timer=null;$('#play').textContent='▶ Play';sync()}
function reset(){pause();i=0;$('#chat').innerHTML='';$('#tt').className='empty';$('#tt').textContent='Revealed after the round.';$('#votes').className='empty';$('#votes').textContent='Ideas appear after the brainstorm.';sync()}
$('#play').onclick=()=>timer?pause():play();$('#step').onclick=()=>{pause();if(i<ev.length){show(ev[i++]);sync()}};
$('#all').onclick=()=>{pause();while(i<ev.length)show(ev[i++]);sync()};$('#restart').onclick=reset;
$('#theme').onclick=()=>{const r=document.documentElement,dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;r.dataset.theme=dark?'light':'dark'};
function md(t){return t.split('\n').map(l=>{l=esc(l).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>');
 if(/^#\s/.test(l))return '';if(/^##\s/.test(l))return '<h3>'+l.slice(3)+'</h3>';if(/^- /.test(l))return '<li>'+l.slice(2)+'</li>';return l?'<p style="margin:4px 0">'+l+'</p>':''}).join('').replace(/(<li>.*?<\/li>)+/g,x=>'<ul>'+x+'</ul>')}
function openCard(id){const p=P[id];if(!p||!p.card)return;$('#cimg').src=p.avatar;$('#cname').textContent=p.name;$('#crole').textContent=p.role;
 const parts=[['persona','Persona (public)'],['soul','Soul (private)'],['job','Job']];$('#ctabs').innerHTML='';
 const showPart=k=>{$('#cbody').innerHTML=md(p.card[k]);[...$('#ctabs').children].forEach(b=>b.classList.toggle('on',b.dataset.k===k))};
 parts.forEach(([k,l])=>{const b=document.createElement('button');b.dataset.k=k;b.textContent=l;b.onclick=()=>showPart(k);$('#ctabs').append(b)});showPart('persona');$('#card').showModal()}
$('#cclose').onclick=()=>$('#card').close();
document.querySelectorAll('.seat').forEach(s=>s.addEventListener('click',()=>openCard(s.id.slice(5))));
const m=D.meta;$('#foot').textContent=`${m.messages} room events · ${m.calls.ok} LLM calls (${Object.entries(m.calls.models).map(([k,v])=>k+': '+v).join(', ')||'offline fake'}) · run ${m.started_utc} → ${m.finished_utc}. Scene lines are written by the meeting software; games and votes are scored by it, not by an LLM.`;
if(matchMedia('(prefers-reduced-motion: reduce)').matches){$('#all').click()}else{sync()}
</script></body></html>
"""

if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "runs", "2026-10-31")))
