#!/usr/bin/env python3
"""chat-mirror-lab Step 3 builder: live strategy page -> m1/m2/m3 replay artifacts.

Each prototype = the real live page (winner-merged template + LIVE/MIRROR modules)
with the server poll swapped for the scripted replay driver, plus a per-style
motion layer. Zero provider calls: REPLAY_RUN is the launch lab's frozen fixture.
Usage: python3 build_mirror.py <out_dir>
"""
import json, os, re, subprocess, sys, tempfile

LAB = os.path.dirname(os.path.abspath(__file__))
WIZLAB = os.path.expanduser("~/.claude/skills/wizard-launch-lab/wizard-lab")
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()

# 1 -- fresh live page into a temp file (never touch the repo copy)
tmp = os.path.join(tempfile.gettempdir(), "mirror-base.html")
subprocess.run(["python3", os.path.join(WIZLAB, "build_live.py"), tmp], check=True)
src = open(tmp, encoding="utf-8").read()

# 2 -- swap the server poll for the replay driver
poll_block = re.search(r"LIVE\.tick = async function\(\)\{.*?setInterval\(LIVE\.tick, 5000\);\nLIVE\.tick\(\);", src, re.S)
if not poll_block:
    sys.exit("poll block not found in live page - update the matcher")
src = src.replace(poll_block.group(0), "// replay build: server poll removed; the timeline below feeds LIVE/MIRROR")

# 3 -- frozen fixture (engine fields stripped, like the server does)
run = json.load(open(os.path.join(WIZLAB, "lab-run.json")))
for i in run["ideas"]:
    for f in ("vector", "probe", "netting", "pull_spec"):
        i.pop(f, None)
run.pop("carry", None)
FIXTURE = "const REPLAY_RUN = " + json.dumps(run) + ";\n"
TIMELINE = open(os.path.join(LAB, "replay-timeline.js"), encoding="utf-8").read()

SHARED_FIX = """
<style id="mirror-shared-fix">
@keyframes numFlash{0%{color:var(--orange)}100%{color:inherit}}
.num-flash{animation:numFlash 1.1s ease-out 1}
@media (prefers-reduced-motion: reduce){.num-flash{animation:none}}
</style>
<script id="mirror-shared-fix-js">
// round-2 fix: a chat-side change that moves a number flags it (headline + rail).
// Nets are tracked in a separate snapshot because the replay driver mutates the
// same objects that already sit in IDEAS (aliasing would hide every change).
LIVE.lastNets = {};
const _applyRun2 = LIVE.applyRun;
LIVE.applyRun = function(run){
  const prev = LIVE.lastNets;
  _applyRun2(run);
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
</script>
"""

REPLAY_UI = """
<style id="replay-ui-style">
#replay-btn{position:fixed;right:18px;bottom:18px;z-index:1600;border:none;border-radius:999px;
  background:var(--invert-bg,#14110E);color:var(--invert-text,#FFF);padding:12px 20px;font:inherit;
  font-size:13.5px;cursor:pointer;box-shadow:0 6px 22px rgba(20,17,14,.25)}
#replay-btn:hover{background:var(--invert-hover,#2A251F)}
</style>
<script id="replay-ui">
(function(){
  const b = document.createElement("button");
  b.id = "replay-btn"; b.type = "button"; b.textContent = "Replay the session";
  b.addEventListener("click", () => { b.textContent = "Restart the session"; MIRROR.lastTouch = 0; replayStart(); });
  document.body.appendChild(b);
  // board visible immediately; the story starts on tap
  LIVE.updated = "replay-boot"; LIVE.applyRun(JSON.parse(JSON.stringify(REPLAY_RUN)));
  renderAll(); LIVE.ready();
})();
</script>
"""

M1_JS = """<script>
// round-2 fix: the quiet follower's one line stays present; the next note replaces it
const _rib1 = MIRROR.ribbon;
MIRROR.ribbon = function(note, pendingFocus){ _rib1(note, pendingFocus); clearTimeout(MIRROR.ribbonTimer); };
</script>"""
M1 = ("Mirror M1 — Quiet follow", "", M1_JS)

M2_CSS = """
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
.mrl-entry button{border-color:var(--orange);color:var(--ink)}
.mrl-dot{width:6px;height:6px;border-radius:50%;background:var(--orange);flex:none}
.mrl-entry button{border:1px solid var(--line-2);background:var(--sunken);border-radius:999px;
  padding:2px 9px;font:inherit;font-size:11px;cursor:pointer;color:var(--ink-2);margin-left:auto}
@media (prefers-reduced-motion: reduce){.mrl-entry{transition:none;transform:none;opacity:1}}
@media (max-width: 700px){#mirror-rail{width:170px}}
"""
M2_JS = """<script>
// M2 Narrated cockpit: the ribbon becomes a ticking activity rail
MIRROR.holdMs = 8000;
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
  requestAnimationFrame ? setTimeout(() => e.classList.add("in"), 20) : e.classList.add("in");
  while (rail.children.length > 5) rail.lastChild.remove();
};
</script>"""

M3_CSS = """
@keyframes mirrorSweep{0%{background-color:rgba(255,107,53,.16)}100%{background-color:transparent}}
.mirror-spot{animation:mirrorSweep .6s ease-out 1}
.chip-out{opacity:0;transform:scale(.85);transition:opacity .24s ease-out,transform .24s ease-out}
@media (prefers-reduced-motion: reduce){.mirror-spot{animation:none}.chip-out{transition:none}}
"""
M3_JS = """<script>
// M3 Guided spotlight: the exact element being changed announces itself
MIRROR.holdMs = 12000;
MIRROR.spotTargets = { targeting: ".lab-editor", emails: ".mail-frame", opener: ".copy-pack-page, .mail-frame",
                       checks: ".step-label", signoff: ".step-label", building: ".build-hero-word" };
MIRROR.lastRunStamp = null;
const _nav3 = MIRROR.navigate;
MIRROR.navigate = function(f){
  _nav3(f);
  const sel = MIRROR.spotTargets[f.view];
  if (!sel) return;
  setTimeout(() => {
    const el = document.querySelector(sel);
    if (!el) return;
    el.classList.remove("mirror-spot"); void el.offsetWidth; el.classList.add("mirror-spot");
    // round-2 fix: only pull the page around when something concrete changed;
    // pure view moves sweep in place (the cross-fade already reorients)
    const dataChanged = LIVE.updated !== MIRROR.lastRunStamp;
    MIRROR.lastRunStamp = LIVE.updated;
    if (dataChanged) {
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      try { el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" }); } catch (e) {}
    }
  }, 260);
};
MIRROR.beforePatch = function(patch){
  if (!patch || !patch.dropRole) return 0;
  const chip = [...document.querySelectorAll(".lab-chip, .trg-chip")]
    .find(c => c.textContent.trim().startsWith(patch.dropRole));
  if (!chip) return 0;
  chip.classList.add("chip-out");
  return 260;
};
</script>"""

BUILDS = { "m1": M1, "m2": ("Mirror M2 — Narrated cockpit", M2_CSS, M2_JS),
           "m3": ("Mirror M3 — Guided spotlight", M3_CSS, M3_JS) }

for key, (title, css, js) in BUILDS.items():
    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", src, count=1, flags=re.S)
    block = (f'<script id="replay-fixture">\n{FIXTURE}{TIMELINE}\n</script>\n'
             + (f'<style id="mirror-style">{css}</style>\n' if css else "")
             + (js + "\n" if js else "") + SHARED_FIX + REPLAY_UI)
    html = html.replace("</body>", block + "</body>", 1)
    out = os.path.join(OUT_DIR, f"{key}.html")
    open(out, "w", encoding="utf-8").write(html)
    print(f"built {out} ({len(html)} bytes)")
print("ok")
