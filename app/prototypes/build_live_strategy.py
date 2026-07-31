#!/usr/bin/env python3
"""Generate app/strategy.html AS the prototype (strategy-integrated-a.html) — same design,
but DATA-DRIVEN and live: it fetches the run from /api/strategy/run, renders the prototype's
sidebar + idea view from that data, polls every 5s, and shows the most-recent change in the
top-right corner when chat updates the board. That chat-mirror + the corner toast are the ONLY
live behaviour (Bjion 2026-07-31) — no phase flow, no Start, no build-screen interactivity.

Reuses the prototype's CSS + embedded font from build_integrated.py; the rendering is translated
to runtime JS below. Run:  python3 build_live_strategy.py
Writes: ~/navreo-signals/app/strategy.html
"""
import json, pathlib, sys
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import build_integrated as P   # reuses P.CSS, P.FONT_B64, P.ICEB (import regenerates the static proto — harmless)

CSS = P.CSS.replace("__FONT__", P.FONT_B64)

# JS-driven routing replaces the prototype's radio/:checked approach (real browser runs JS)
EXTRA_CSS = """
.tabin{display:none;}
.idea-view{display:block;} .panel{display:block;}
.im{cursor:pointer;position:relative;}
.im.active{background:var(--orange-100);border-color:var(--orange-100);}
.im.active::before{content:"";position:absolute;left:-14px;top:14px;bottom:14px;width:3px;border-radius:2px;background:var(--orange);}
.tabs label{cursor:pointer;}
.tabs label.active{color:var(--ink);border-color:var(--orange);background:var(--bg);}
.tabs label.active .ring{border-color:var(--orange);background:var(--orange);}
/* boot + top-right most-recent-change toast (the one carried-over live behaviour) */
#boot{position:fixed;inset:0;z-index:50;display:flex;align-items:center;justify-content:center;background:var(--bg);color:var(--ink-3);font-size:15px;}
#boot.gone{display:none;}
#toast{position:fixed;top:16px;right:18px;z-index:60;display:flex;align-items:center;gap:9px;
  background:var(--bg);border:1px solid var(--line-2);border-radius:999px;padding:9px 16px;font-size:12.5px;color:var(--ink-2);
  box-shadow:0 6px 22px -12px rgba(20,17,14,.35);opacity:0;transform:translateY(-8px);pointer-events:none;
  transition:opacity .22s ease,transform .22s ease;max-width:340px;}
#toast.show{opacity:1;transform:none;}
#toast .lt-dot{width:7px;height:7px;border-radius:50%;background:var(--orange);flex:none;}
#toast b{color:var(--ink);font-weight:600;}
.empty-pick{max-width:760px;padding:60px 40px;font-family:var(--font-display);font-size:30px;letter-spacing:-.03em;color:var(--ink-3);}
"""

ICEB = json.dumps(P.ICEB, ensure_ascii=False)

JS = r"""
const TABS=[['tgt','Targeting'],['copy','Copy'],['first','Icebreaker'],['build','Build'],['live','Live']];
const ICEB=__ICEB__;
const CHECKS=[
  ["Spelling &amp; grammar","every line read and fixed"],
  ["Merge fields fill in","no blank [First name] or [Company] slips through"],
  ["Links work","every link opened and checked"],
  ["Unsubscribe line present","an easy opt-out on every email"],
  ["No spam-trigger words","wording that stays out of the junk folder"],
  ["Sending addresses are healthy","warmed-up domains, good reputation"],
  ["Daily send caps set","we ramp up slowly, never blast"],
  ["Nobody emailed twice","checked against everyone we've contacted before"]
];
let IDEAS=[], active=0, tab='tgt', lastFP=null, client='';
const side=document.getElementById('side'), work=document.getElementById('work'),
      boot=document.getElementById('boot'), toast=document.getElementById('toast');

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function num(n){return (n==null||n==='')?'':Number(n).toLocaleString();}
function cap120(t,limit){limit=limit||120;t=String(t||'').split(/\s+/).join(' ').trim();if(t.length<=limit)return t;
  let cut=t.slice(0,limit);cut=cut.slice(0,cut.lastIndexOf(' '));
  const stops=new Set(["and","or","the","a","an","to","of","their","that","who","with","without","in","on","for","is","are","but","its","whose","by","at","as","new"]);
  let w=cut.replace(/[,;:—\- ]+$/,'').split(' ');
  while(w.length&&stops.has(w[w.length-1].toLowerCase().replace(/[,;:]/g,'')))w.pop();
  let o=w.join(' ').replace(/[,;:—\- ]+$/,'');return o+(/[.!?]$/.test(o)?'':'.');}

function anchorChips(x){return (x.anchors||[]).map(a=>`<span class="chip">${esc(a)}</span>`).join('');}
function caseChip(c){const i=String(c).indexOf(' — ');if(i<0)return `<span class="chip">${esc(c)}</span>`;
  return `<span class="chip">${esc(c.slice(0,i))}<span class="chip-sub"> — ${esc(c.slice(i+3))}</span></span>`;}
function caseChips(x){return (x.cases||[]).map(caseChip).join('');}
function rolesChips(x){const r=(x.targeting&&x.targeting.roles)||[],n=8;
  let h=r.slice(0,n).map(v=>`<span class="chip">${esc(v)}</span>`).join('');
  if(r.length>n)h+=`<span class="chip chip-more">+${r.length-n} more</span>`;return h;}
function numBig(x){const p=x.reachablePool||x.net;return `<div class="numbig"><div class="n">${num(p)}</div><div class="rl">reachable — we email all</div></div>`;}
function targetingSections(x){return `<div class="sect"><p class="eyb">Companies like these</p><div class="chips">${anchorChips(x)}</div></div>`
  +`<div class="sect"><p class="eyb">Case studies we pull</p><div class="chips">${caseChips(x)}</div></div>`
  +`<div class="sect"><p class="eyb">Decision-makers we email</p><div class="chips">${rolesChips(x)}</div></div>`;}
function versionFrame(x){return `<div class="mail"><div class="mh">Subject: ${esc(x.caption||'')}</div><div class="mb">${esc(x.email||'').replace(/\n/g,'<br>')}</div></div>`;}
function openerRows(){return ICEB.map((o,i)=>{const name=o[0],rec=o[1],plain=o[2],ex=o[3];
  const recH=rec?' <span class="ib-rec">Recommended</span>':'';const up=i===0?' disabled':'';const dn=i===ICEB.length-1?' disabled':'';
  return `<div class="opener-row"><div class="opener-order"><span class="opos">${i+1}</span><button class="oarrow"${up}>▲</button><button class="oarrow"${dn}>▼</button></div>`
    +`<div class="opener-body"><p class="ib-name">${esc(name)}${recH}</p><p class="ib-plain">${esc(plain)}</p><p class="ib-example">"${esc(ex)}"</p></div><span class="otog">On</span></div>`;}).join('');}

function panelHTML(x){
  if(tab==='tgt') return `<div class="desc">${esc(cap120(x.who||''))}</div><div class="tgt-hero">${numBig(x)}</div>${targetingSections(x)}`;
  if(tab==='copy') return `<p class="copy-heading">Your emails</p>`
    +`<div class="pager"><button class="pager-arrow" disabled>‹</button><div class="pager-mid"><div class="pager-dots">`
    +`<button class="pager-dot active"></button><button class="pager-dot"></button><button class="pager-dot"></button><button class="pager-dot"></button>`
    +`<span class="pager-divider"></span><button class="pager-dot"></button><span class="pager-fu">Follow-up</span></div>`
    +`<span class="pager-label">Version A</span></div><button class="pager-arrow">›</button></div>`
    +versionFrame(x)+`<div class="actions-center"><button class="btn-ink">Next: choose the opener</button></div>`;
  if(tab==='first') return `<p class="copy-heading">The opener</p><div class="opener-list">${openerRows()}</div>`
    +`<p class="hooknote" style="margin-top:16px">We try these in order for each person, and always have the safe opener as backup.</p>`;
  if(tab==='build') return `<p class="eyb">Build</p><p class="chkhead">This is the one step that pulls real data. When you build, we pull the real list (or arm the trigger for an ongoing signal) and run every check below. Nothing sends until it's Live.</p>`
    +`<div class="checks">`+CHECKS.map(c=>`<div class="chk"><span class="ck"></span><div><div class="cl">${c[0]}</div><div class="cn">${esc(c[1])}</div></div></div>`).join('')+`</div>`
    +`<button class="build-btn">Build the campaign</button>`;
  const p=x.reachablePool||x.net;
  return `<p class="eyb">Live</p><div class="livebanner">Not live yet — the campaign turns on when you approve it. Nothing sends until then.</div>`
    +`<div class="tiles"><div class="tile"><div class="tn">${num(p)}</div><div class="tl">in the pool</div></div>`
    +`<div class="tile"><div class="tn">—</div><div class="tl">emailed</div></div>`
    +`<div class="tile"><div class="tn">—</div><div class="tl">replies</div></div>`
    +`<div class="tile"><div class="tn">—</div><div class="tl">meetings booked</div></div></div>`
    +`<p class="planline">Once it's on, we email all ${num(p)} at a steady, safe pace and track every reply, positive reply and meeting right here.</p>`;
}

function renderSidebar(){
  const cards=IDEAS.map((x,i)=>{const service=(x.service||'').replace('->','→');
    return `<div class="im ${i===active?'active':''}" data-i="${i}"><p class="im-name">${esc(x.name)}</p>`
      +`<p class="im-caption">${esc(x.caption||'')}</p>`
      +`<p class="im-count"><span class="im-number">${num(x.net||x.reachablePool)}</span> reachable</p>`
      +(service?`<p class="im-type">${esc(service)}</p>`:'')
      +`<div class="im-track"><i></i><i></i><i></i><i></i><i></i></div></div>`;}).join('');
  side.innerHTML=`<div class="brand"><b>Navreo</b><span class="ey">Strategy</span></div>`
    +(client?`<div class="client"><div class="lbl">Building for</div><div class="name">${esc(client)}</div></div>`:'')
    +`<div class="sechead">${IDEAS.length} campaign idea${IDEAS.length===1?'':'s'}</div>${cards}`;
  side.querySelectorAll('.im').forEach(c=>c.onclick=()=>{active=+c.dataset.i;tab='tgt';render();});
}
function renderWorkspace(){
  const x=IDEAS[active];
  if(!x){work.innerHTML='<div class="empty-pick">Pick an idea on the left.</div>';return;}
  const pills=`<div class="tabs">`+TABS.map(t=>`<label class="${t[0]===tab?'active':''}" data-tab="${t[0]}"><span class="ring"></span>${esc(t[1])}</label>`).join('')+`</div>`;
  work.innerHTML=`<div class="wrap">${pills}<h1 class="h1">${esc(x.name)}</h1><div class="panels"><section class="panel">${panelHTML(x)}</section></div></div>`;
  work.querySelectorAll('.tabs label').forEach(l=>l.onclick=()=>{tab=l.dataset.tab;renderWorkspace();});
}
function render(){renderSidebar();renderWorkspace();}

function fmtTime(u){try{const d=u?new Date(u):new Date();return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});}catch(e){return '';}}
function showToast(updated,note){
  toast.innerHTML=`<span class="lt-dot"></span><span>Just updated${note?': <b>'+esc(note)+'</b>':' from chat'} · ${fmtTime(updated)}</span>`;
  toast.classList.add('show');clearTimeout(toast._h);toast._h=setTimeout(()=>toast.classList.remove('show'),6500);
}
async function fetchRun(){
  try{
    const r=await fetch('/api/strategy/run',{credentials:'include',cache:'no-store'});
    if(!r.ok)return;
    const j=await r.json();const run=j.run||j;const ideas=(run&&run.ideas)||[];
    const fp=JSON.stringify(ideas)+'|'+(j.updated||run.updated||'');
    if(fp===lastFP)return;
    const first=lastFP===null;
    IDEAS=ideas;client=run.client||run.clientLabel||client;
    if(active>=IDEAS.length)active=0;
    render();boot.classList.add('gone');
    if(!first){const note=(j.focus&&j.focus.note)||(run.focus&&run.focus.note)||'';showToast(j.updated||run.updated,note);}
    lastFP=fp;
  }catch(e){/* keep last good board */}
}
fetchRun();setInterval(fetchRun,5000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)fetchRun();});
"""
JS = JS.replace("__ICEB__", ICEB)

HTML = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Navreo · Strategy</title><style>" + CSS + EXTRA_CSS + "</style></head><body>"
        "<div id=\"boot\">Loading your board…</div>"
        "<div id=\"toast\"></div>"
        "<div class=\"app\"><aside class=\"side\" id=\"side\"></aside><main class=\"work\" id=\"work\"></main></div>"
        "<script>" + JS + "</script></body></html>")

out = pathlib.Path.home() / "navreo-signals" / "app" / "strategy.html"
out.write_text(HTML, encoding="utf-8")
print(f"wrote {out}  ({len(HTML)//1024} KB)")
