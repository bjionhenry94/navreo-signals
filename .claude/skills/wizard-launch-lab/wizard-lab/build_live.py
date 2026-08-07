#!/usr/bin/env python3
"""Generate app/strategy.html for the navreo-signals tool.

Since the L3 winner merge (Bjion pick 2026-07-27), wizard-template.html already
contains the launch-lab layer (chip editor, shelf, Back, sendable emails, L3
runway + minimal preview) - this builder only wraps it as a full document and
adds the LIVE module: fetch the current run from /api/strategy/run, rebuild the
board client-side, poll every 5s so chat-side POSTs appear while you watch.
Regenerate with:
    python3 build_live.py ~/navreo-signals/app/strategy.html
"""
import os, re, sys

TEMPLATE = os.path.expanduser("~/.claude/skills/lilly-strategy/wizard-template.html")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/navreo-signals/app/strategy.html")

src = open(TEMPLATE, encoding="utf-8").read()
if "LAUNCH-LAB WINNER MERGE" not in src:
    sys.exit("template is missing the L3 winner merge - refusing to build a bare page")

# the template's own per-idea state literal, extracted so the live module can
# rebuild cardState for fetched ideas without drifting from the template
m = re.search(r"cardState\[i\.id\] = (\{.*?\n  \});", src, re.S)
if not m:
    sys.exit("cardState literal not found in template - update the extractor")
STATE_LITERAL = m.group(1)

src = re.sub(r"<title>.*?</title>", "<title>Navreo · Strategy board</title>", src, count=1, flags=re.S)

LIVE_CSS = """
#live-boot{position:fixed;inset:0;z-index:2000;background:var(--cream);display:flex;
  align-items:center;justify-content:center;text-align:center;padding:24px}
#live-boot p{max-width:420px;font-size:15px;line-height:1.6;color:var(--ink-2);margin:0}
#live-boot.gone{display:none}
/* chat-mirror: the page follows the conversation */
#mirror-ribbon{position:fixed;top:10px;left:50%;transform:translate(-50%,-160%);z-index:1500;
  display:flex;align-items:center;gap:10px;background:var(--raised);border:1px solid var(--line-2);
  border-radius:999px;padding:7px 16px;font-size:12.5px;color:var(--ink-2);
  box-shadow:0 4px 18px rgba(20,17,14,.08);transition:transform .2s ease-out,opacity .2s ease-out;opacity:0}
#mirror-ribbon.show{transform:translate(-50%,0);opacity:1}
#mirror-ribbon .mr-dot{width:7px;height:7px;border-radius:50%;background:var(--orange);flex:none}
#mirror-ribbon button{border:1px solid var(--line-2);background:var(--sunken);border-radius:999px;
  padding:3px 11px;font:inherit;font-size:11.5px;cursor:pointer;color:var(--ink-2)}
#mirror-ribbon button:hover{background:var(--cream)}
.ws-swap{opacity:0;transition:opacity .18s ease-out}
.ws-in{opacity:1;transition:opacity .22s ease-out}
@keyframes mirrorPulse{0%,100%{box-shadow:0 0 0 0 rgba(255,107,53,0)}50%{box-shadow:0 0 0 3px rgba(255,107,53,.35)}}
.mirror-pulse{animation:mirrorPulse 0.6s ease-in-out 2}
@media (prefers-reduced-motion: reduce){
  #mirror-ribbon,.ws-swap,.ws-in{transition:none}
  .mirror-pulse{animation:none;outline:2px solid var(--orange);outline-offset:2px}
}
/* blend (Bjion pick 2026-07-27): M2 narrated rail replaces the ribbon */
#mirror-ribbon{display:none}
#mirror-rail{position:fixed;right:18px;top:18px;z-index:1500;width:230px;display:flex;
  flex-direction:column;gap:6px;pointer-events:none}
.mrl-entry{background:var(--raised);border:1px solid var(--line-2);border-radius:10px;
  padding:8px 12px;font-size:12px;color:var(--ink-2);box-shadow:0 3px 14px rgba(20,17,14,.07);
  display:flex;align-items:center;gap:8px;opacity:0;transform:translateX(14px);
  transition:opacity .22s ease-out,transform .22s ease-out;pointer-events:auto}
.mrl-entry.in{opacity:1;transform:none}
.mrl-entry:nth-child(n+3){opacity:.5}
.mrl-entry:nth-child(n+5){display:none}
.mrl-time{font-family:ui-monospace,monospace;font-size:10px;color:var(--muted);flex:none}
.mrl-dot{width:6px;height:6px;border-radius:50%;background:var(--orange);flex:none}
.mrl-entry button{border:1px solid var(--orange);background:var(--sunken);border-radius:999px;
  padding:2px 9px;font:inherit;font-size:11px;cursor:pointer;color:var(--ink);margin-left:auto}
/* blend: M3 spotlight sweep + shared number flash */
@keyframes mirrorSweep{0%{background-color:rgba(255,107,53,.16)}100%{background-color:transparent}}
.mirror-spot{animation:mirrorSweep .6s ease-out 1}
@keyframes numFlash{0%{color:var(--orange)}100%{color:inherit}}
.num-flash{animation:numFlash 1.1s ease-out 1}
@media (prefers-reduced-motion: reduce){
  .mrl-entry{transition:none;transform:none;opacity:1}
  .mirror-spot,.num-flash{animation:none}
}
@media (max-width: 700px){#mirror-rail{width:170px}}
"""

LIVE_JS = """<script>
// ---- LIVE module: the board is server-fed and chat-driven ------------------
// Chat POSTs a run to /api/strategy/run; this page polls the GET every 5s and
// repaints. Journey state (phases, approvals, builds) survives repaints; when
// chat changes an idea's targeting, that idea's chips rebuild from the new
// roles because chat is the source of truth.
const LIVE = { updated: null, footerBase: "" };
LIVE.defaultState = function(i){ return __STATE__; };
LIVE.applyRun = function(run){
  const keep = new Set((run.ideas || []).map(i => i.id));
  Object.keys(cardState).forEach(k => { if (!keep.has(k)) delete cardState[k]; });
  IDEAS.length = 0;
  (run.ideas || []).forEach(i => IDEAS.push(i));
  IDEAS.forEach(i => {
    const sig = JSON.stringify((i.targeting && i.targeting.roles) || []);
    if (!cardState[i.id]) cardState[i.id] = LIVE.defaultState(i);
    else {
      const s = cardState[i.id];
      if (s._trgSig !== sig) { s.labChips = null; s.labWho = null; delete LAB.origNet[i.id]; }
      if (s.phase === 1) s.whoText = i.who;
    }
    cardState[i.id]._trgSig = sig;
    LAB.origSplit[i.id] = [i.freeFromRecords || 0, i.newPeople || 0];
  });
  Object.keys(PEOPLE).forEach(k => delete PEOPLE[k]);
  Object.assign(PEOPLE, run.people || {});
  try {
    if (run.colleagues) { Object.keys(COLLEAGUES).forEach(k => delete COLLEAGUES[k]); Object.assign(COLLEAGUES, run.colleagues); }
    if (run.validation_card) Object.assign(VALIDATION_CARD, run.validation_card);
  } catch (e) {}
  LAB.shelf = run.shelf || [];
  LIVE.footerBase = run.footer || "";
  const foot = document.getElementById("board-footer");
  if (foot && LIVE.footerBase) foot.textContent = LIVE.footerBase;
};
LIVE.ready = function(){ const b = document.getElementById("live-boot"); if (b) b.classList.add("gone"); };
LIVE.empty = function(){
  const t = document.getElementById("live-boot-text");
  if (t) t.textContent = "No board yet. In the chat, say: run Navreo strategy.";
};
LIVE.stamp = function(){
  const foot = document.getElementById("board-footer");
  if (!foot) return;
  const hm = new Date().toTimeString().slice(0, 5);
  foot.textContent = (LIVE.footerBase || "") + " · updated from chat " + hm;
};
// ---- MIRROR: chat leads, the page follows (chat-mirror-lab) ----------------
const MIRROR = { focusTs: null, pending: null, lastTouch: 0, holdMs: 10000, ribbonTimer: null };
["pointerdown", "keydown", "wheel"].forEach(ev =>
  addEventListener(ev, () => { MIRROR.lastTouch = Date.now(); }, { capture: true, passive: true }));
MIRROR.holdingFocus = function(){ return Date.now() - MIRROR.lastTouch < MIRROR.holdMs; };
MIRROR.aCount = function(idea){ return stagesFor(idea).filter(st => st.phase === "A").length; };
MIRROR.ribbon = function(note, pendingFocus){
  let r = document.getElementById("mirror-ribbon");
  if (!r) {
    r = document.createElement("div");
    r.id = "mirror-ribbon";
    r.innerHTML = '<span class="mr-dot"></span><span class="mr-note"></span>';
    document.body.appendChild(r);
  }
  r.querySelector(".mr-note").textContent = note || "";
  const old = r.querySelector("button"); if (old) old.remove();
  if (pendingFocus) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = "Catch up";
    b.addEventListener("click", () => { MIRROR.pending = null; MIRROR.navigate(pendingFocus); });
    r.appendChild(b);
  }
  r.classList.add("show");
  clearTimeout(MIRROR.ribbonTimer);
  MIRROR.ribbonTimer = setTimeout(() => r.classList.remove("show"), 20000);
};
MIRROR.pulseRail = function(ideaId){
  const ix = IDEAS.findIndex(i => i.id === ideaId);
  if (ix < 0) return;
  const cards = Array.from(document.querySelectorAll("#idea-list .idea-mini"))
    .filter(c => !c.classList.contains("validation-mini"));
  const card = cards[ix]; if (!card) return;
  card.classList.remove("mirror-pulse"); void card.offsetWidth;
  card.classList.add("mirror-pulse");
};
MIRROR.navigate = function(f){
  const swap = () => {
    if (!f.ideaId || f.view === "board") { activeId = null; renderAll(); return; }
    const idea = IDEAS.find(i => i.id === f.ideaId); if (!idea) { renderAll(); return; }
    activeId = f.ideaId;
    const s = cardState[f.ideaId]; if (!s) { renderAll(); return; }
    const a = MIRROR.aCount(idea);
    if (f.view === "targeting") s.phase = 2;
    else if (f.view === "building") s.phase = s.stagesDone >= a ? 5 : 3;
    else if (f.view === "emails" || f.view === "opener") {
      s.stagesDone = Math.max(s.stagesDone, a);
      s.phase = 4; s.copyPackPage = f.view === "opener" ? 2 : 1;
    } else if (f.view === "checks" || f.view === "signoff") {
      s.stagesDone = 5;
      try { ensureVersions(idea, s);
        if (!s.chosenVersion) { const v = (s.versions || []).find(x => x.active); if (v) s.chosenVersion = v.id; }
      } catch (e) {}
      s.phase = 6;
    }
    renderAll();
  };
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) { swap(); }
  else {
    wsEl.classList.remove("ws-in"); wsEl.classList.add("ws-swap");
    setTimeout(() => { swap(); wsEl.classList.remove("ws-swap"); wsEl.classList.add("ws-in"); }, 180);
  }
  if (f.ideaId) MIRROR.pulseRail(f.ideaId);
  MIRROR.ribbon(f.note);
};
MIRROR.applyFocus = function(f){
  if (!f || !f.ts || f.ts === MIRROR.focusTs) return;
  MIRROR.focusTs = f.ts;
  if (MIRROR.holdingFocus()) {
    MIRROR.pending = f;
    if (f.ideaId) MIRROR.pulseRail(f.ideaId);
    MIRROR.ribbon(f.note || "Chat moved on", f);
    return;
  }
  MIRROR.navigate(f);
};

// ---- blend layer (Bjion pick 2026-07-27): M2 narrated rail + M3 spotlight ----
MIRROR.ribbon = function(note, pendingFocus){
  let rail = document.getElementById("mirror-rail");
  if (!rail) { rail = document.createElement("div"); rail.id = "mirror-rail"; document.body.appendChild(rail); }
  const e = document.createElement("div");
  e.className = "mrl-entry";
  const hm = new Date().toTimeString().slice(0, 5);
  e.innerHTML = '<span class="mrl-dot"></span><span class="mrl-time">' + hm + '</span><span>' + esc(note || "") + "</span>";
  if (pendingFocus) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = "Catch up";
    b.addEventListener("click", () => { MIRROR.pending = null; MIRROR.navigate(pendingFocus); });
    e.appendChild(b);
  }
  rail.prepend(e);
  setTimeout(() => e.classList.add("in"), 20);
  while (rail.children.length > 5) rail.lastChild.remove();
};
MIRROR.spotTargets = { targeting: ".lab-editor", emails: ".mail-frame", opener: ".copy-pack-page, .mail-frame",
                       checks: ".step-label", signoff: ".step-label", building: ".build-hero-word" };
MIRROR.lastRunStamp = null;
const _navBlend = MIRROR.navigate;
MIRROR.navigate = function(f){
  _navBlend(f);
  const sel = MIRROR.spotTargets[f.view];
  if (!sel) return;
  setTimeout(() => {
    const el = document.querySelector(sel);
    if (!el) return;
    el.classList.remove("mirror-spot"); void el.offsetWidth; el.classList.add("mirror-spot");
    // only pull the page around when data actually changed; view moves sweep in place
    const dataChanged = LIVE.updated !== MIRROR.lastRunStamp;
    MIRROR.lastRunStamp = LIVE.updated;
    if (dataChanged) {
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      try { el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" }); } catch (e) {}
    }
  }, 260);
};
// a chat-side change that moves a number flags it (nets tracked in a snapshot -
// run objects can alias what IDEAS already holds, hiding a naive prev-vs-new)
LIVE.lastNets = {};
const _applyBlend = LIVE.applyRun;
LIVE.applyRun = function(run){
  const prev = LIVE.lastNets;
  _applyBlend(run);
  const changed = IDEAS.filter(i => prev[i.id] !== undefined && prev[i.id] !== i.net).map(i => i.id);
  LIVE.lastNets = {}; IDEAS.forEach(i => LIVE.lastNets[i.id] = i.net);
  if (!changed.length) return;
  setTimeout(() => {
    changed.forEach(id => {
      const ix = IDEAS.findIndex(i => i.id === id);
      const card = document.querySelectorAll("#idea-list .idea-mini:not(.validation-mini)")[ix];
      const rail = card && card.querySelector(".im-number");
      [rail, id === activeId ? document.querySelector(".lab-live-num, .preview-num") : null].forEach(el => {
        if (!el) return; el.classList.remove("num-flash"); void el.offsetWidth; el.classList.add("num-flash");
      });
    });
  }, 60);
};

LIVE.tick = async function(){
  let d;
  try {
    const r = await fetch("/api/strategy/run", { cache: "no-store" });
    if (r.status === 401) { location.href = "/app/login.html?next=/app/strategy.html"; return; }
    d = await r.json();
  } catch (e) { return; }
  if (!d || !d.run) { LIVE.empty(); return; }
  if (d.updated !== LIVE.updated) {
    const first = !LIVE.updated;
    LIVE.updated = d.updated;
    LIVE.applyRun(d.run);
    if (!MIRROR.pending) renderAll();
    LIVE.ready();
    if (!first) LIVE.stamp();
  }
  LIVE.ready();
  if (d.focus) MIRROR.applyFocus(d.focus);
};
setInterval(LIVE.tick, 5000);
LIVE.tick();
</script>""".replace("__STATE__", STATE_LITERAL)

BOOT = '<div id="live-boot"><p id="live-boot-text">Loading your board…</p></div>\n'

page = ("<!doctype html>\n<html lang=\"en\">\n<body>\n" + BOOT + src +
        f'\n<style id="live-style">{LIVE_CSS}</style>\n{LIVE_JS}\n</body>\n</html>\n')
open(OUT, "w", encoding="utf-8").write(page)
print(f"wrote {OUT} ({len(page)} bytes)")
