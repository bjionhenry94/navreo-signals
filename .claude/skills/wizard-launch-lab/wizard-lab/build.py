#!/usr/bin/env python3
"""wizard-launch-lab Step 2 builder: lab-run.json -> hydrated base -> l1/l2/l3.html"""
import json, os, re, subprocess, sys

LAB_DIR = os.path.dirname(os.path.abspath(__file__))
STRAT = os.path.expanduser("~/.claude/skills/lilly-strategy")
ENGINE = os.path.join(STRAT, "engine", "engine.py")
RUN_SRC = os.path.join(STRAT, "sessions", "navreo-2026-07-27-run.json")
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()

# 1 -- lab-run.json: this session's 4 ideas ONLY (F1), no carry
run = json.load(open(RUN_SRC))
run["ideas"] = [i for i in run["ideas"] if i["id"] != "cleaning"]
run.pop("carry", None)
run["people"].pop("cleaning", None)
run["footer"] = ("Fresh ideas for Navreo · 27 July 2026 · every number checked against real job "
                 "posts and our own records · example people are illustrative · nothing here "
                 "sends email without you.")
lab_run = os.path.join(LAB_DIR, "lab-run.json")
json.dump(run, open(lab_run, "w"), indent=2, ensure_ascii=False)

# 2 -- hydrate a fresh copy of the maintained template (never edited in place)
base_html = os.path.join(LAB_DIR, "lab-base.html")
subprocess.run(["python3", ENGINE, "hydrate", "--run", lab_run, "--out", base_html], check=True,
               capture_output=True)
src = open(base_html, encoding="utf-8").read()

CAPTURE = """<script>
// capture base renderers before any lab override (assignment-form overrides follow)
const LAB = { base: { renderList, renderWorkspace, renderIntro, renderTargeting } };
</script>"""

FIXTURE = open(os.path.join(LAB_DIR, "launch-fixture.js"), encoding="utf-8").read()

SHARED_CSS = """
.lab-back{position:sticky;top:0;z-index:5;align-self:flex-start;margin:0 0 10px;border:1px solid var(--line-2);
  background:var(--raised);color:var(--ink-2);border-radius:999px;padding:5px 14px 5px 10px;font:inherit;
  font-size:12.5px;cursor:pointer}
.lab-back:hover{background:var(--sunken)}
.shelf-head{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
  margin:18px 2px 6px;padding-top:12px;border-top:1px solid var(--card-line)}
.shelf-mini{border:1px dashed var(--line-2);border-radius:10px;padding:10px 12px;opacity:.75;background:var(--sunken)}
.shelf-mini .im-caption{margin-top:2px}
.lab-chip{display:inline-flex;align-items:center;gap:4px;padding-right:5px}
.lab-x{border:none;background:none;cursor:pointer;color:var(--muted);font-size:13px;line-height:1;padding:0 2px;font-family:inherit}
.lab-x:hover{color:var(--ink)}
.lab-est{font-style:normal;font-size:9px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);
  border:1px solid var(--line-2);border-radius:3px;padding:0 3px;margin-left:2px}
.lab-add-row{display:flex;gap:6px;align-items:center;margin:2px 0 0;flex-wrap:wrap}
.lab-add{border:1px solid var(--line-2);background:var(--raised);border-radius:999px;padding:4px 11px;font:inherit;
  font-size:12px;color:var(--ink-2);width:130px}
.lab-add-btn{border:1px solid var(--line-2);background:var(--raised);border-radius:50%;width:24px;height:24px;
  cursor:pointer;font:inherit;font-size:14px;line-height:1;color:var(--ink-2)}
.lab-add-btn:hover,.lab-gen:hover{background:var(--sunken)}
.lab-gen{border:1px solid var(--line-2);background:var(--raised);border-radius:999px;padding:4px 12px;cursor:pointer;
  font:inherit;font-size:12px;color:var(--ink-2)}
.lab-live-wrap{margin:0 0 2px;display:flex;align-items:baseline;gap:8px}
.lab-live-num{font-size:34px;letter-spacing:-.01em}
.lab-live-unit{font-size:12.5px;color:var(--muted)}
.lab-recount-cap{min-height:16px;margin:0 0 8px}
.lab-gate-line{margin:0 0 10px;font-size:14px}
.l1-facts{margin:14px 0 0;display:flex;flex-direction:column;gap:7px}
.l1-fact{margin:0;font-size:12.5px;color:var(--ink-2);line-height:1.45;display:-webkit-box;-webkit-line-clamp:1;
  -webkit-box-orient:vertical;overflow:hidden;cursor:pointer}
.l1-fact.open{-webkit-line-clamp:unset}
.l1-fact b{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-right:6px}
"""

L1_CSS = """
.l1-grid{display:grid;grid-template-columns:minmax(200px,240px) 1fr;gap:22px;align-items:start;max-width:860px}
@media(max-width:900px){.l1-grid{grid-template-columns:1fr}}
.l1-cta{margin-top:16px}
"""
L1_JS = """<script>
renderIntro = function(idea, s){
  LAB.ensureChips(idea, s);
  const el = document.createElement("div");
  const facts = [["Why", idea.why.replace(/^Why: /,"")]]
    .filter(f=>f[1]).map(f=>`<p class="l1-fact" tabindex="0"><b>${esc(f[0])} &#9662;</b>${esc(f[1])}</p>`).join("");
  el.innerHTML = `
    <div class="l1-grid">
      <div>
        <p class="lab-live-wrap" style="flex-direction:column;align-items:flex-start;gap:2px">
          <span class="lab-live-num num mono">${idea.net.toLocaleString()}</span>
          <span class="lab-live-unit">${esc(idea.netUnit||"people we can reach")}</span></p>
        <p class="lab-recount-cap edit-caption"></p>
        <div class="l1-facts">${facts}</div>
      </div>
      <div>${LAB.editorHtml(idea, s)}
        <div class="actions l1-cta"><button class="btn btn-primary" type="button" data-act="go">Looks right, write my emails</button></div>
      </div>
    </div>`;
  el.querySelectorAll(".l1-fact").forEach(p=>p.addEventListener("click",()=>p.classList.toggle("open")));
  const rerender = () => { const fresh = renderIntro(idea, s); el.replaceWith(fresh); };
  LAB.wireEditor(el, idea, s, rerender);
  el.querySelector('[data-act="go"]').addEventListener("click", () => {
    s.phase = 3; renderAll(); runBuild(idea, s, "A");
  });
  return el;
};
renderAll();
</script>"""

L2_CSS = """
.l2-dots{display:flex;gap:18px;align-items:center;margin:0 0 18px;flex-wrap:wrap}
.l2-dot{display:flex;align-items:center;gap:6px;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.l2-dot i{width:9px;height:9px;border-radius:50%;border:1.5px solid var(--line-2);background:transparent;font-style:normal}
.l2-dot.done i{background:var(--ink);border-color:var(--ink)}
.l2-dot.now{color:var(--ink)}
.l2-dot.now i{border-color:var(--orange);background:var(--orange)}
.l2-chips{display:flex;flex-wrap:wrap;gap:5px;margin:12px 0}
"""
L2_JS = """<script>
LAB.sharedWS = renderWorkspace;
LAB.l2Steps = function(s){
  const done = { who: s.phase>=3, words: s.phase>=5 || (s.phase===4 && s.copyPackPage===2), opener: s.phase>=5, go: s.phase===7 };
  const now = s.phase<=1?null : s.phase===2?"who" : (s.phase===4 && s.copyPackPage!==2)?"words" : (s.phase===4)?"opener" : s.phase===6?"go" : null;
  return [["who","Who"],["words","Words"],["opener","Opener"],["go","Go"]]
    .map(x=>`<span class="l2-dot${done[x[0]]?" done":""}${now===x[0]?" now":""}"><i></i>${x[1]}</span>`).join("");
};
renderWorkspace = function(){
  LAB.sharedWS();
  if (!activeId) return;
  const s = cardState[activeId];
  if (!s || s.phase <= 1) return;
  const bar = document.createElement("div");
  bar.className = "l2-dots";
  bar.innerHTML = LAB.l2Steps(s);
  const back = wsEl.querySelector(".lab-back");
  wsEl.insertBefore(bar, back ? back.nextSibling : wsEl.firstChild);
};
renderIntro = LAB.minimalIntro;
renderAll();
</script>"""

L3_CSS = """
.idea-mini .im-bar-track{display:none}
.runway{display:flex;gap:4px;margin:8px 0 2px;align-items:center}
.rw-stop{flex:1;display:flex;flex-direction:column;gap:3px;align-items:center;border:none;background:none;
  cursor:pointer;padding:2px 0;font:inherit}
.rw-stop[disabled]{cursor:default;opacity:.35}
.rw-seg{width:100%;height:4px;border-radius:2px;background:var(--sunken);border:1px solid var(--card-line)}
.rw-stop.done .rw-seg{background:var(--ink);border-color:var(--ink)}
.rw-stop.now .rw-seg{background:var(--orange);border-color:var(--orange)}
.rw-lbl{font-size:8.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.rw-stop.done .rw-lbl,.rw-stop.now .rw-lbl{color:var(--ink-2)}
"""
L3_JS = """<script>
LAB.sharedList = renderList;
LAB.aCount = function(idea){ return stagesFor(idea).filter(st=>st.phase==="A").length; };
renderIntro = LAB.minimalIntro;
renderList = function(){
  LAB.sharedList();
  const cards = Array.from(listEl.querySelectorAll(".idea-mini")).filter(c=>!c.classList.contains("validation-mini"));
  cards.forEach((card, ix) => {
    const idea = IDEAS[ix]; if (!idea) return;
    const s = cardState[idea.id];
    const done = { who: s.phase>=3, words: s.phase>=5 || (s.phase===4 && s.copyPackPage===2), opener: s.phase>=5, go: s.phase===7 };
    const now = s.phase===2?"who" : (s.phase===4&&s.copyPackPage!==2)?"words" : s.phase===4?"opener" : s.phase===6?"go" : null;
    const can = { who: true, words: s.stagesDone>=LAB.aCount(idea), opener: s.stagesDone>=LAB.aCount(idea), go: s.phase>=6 };
    const strip = document.createElement("div");
    strip.className = "runway";
    strip.innerHTML = [["who","Who"],["words","Words"],["opener","Opener"],["go","Go"]].map(x=>
      `<button type="button" class="rw-stop${done[x[0]]?" done":""}${now===x[0]?" now":""}" data-stop="${x[0]}"
        ${can[x[0]]?"":"disabled"} aria-label="${x[1]}"><span class="rw-seg"></span><span class="rw-lbl">${x[1]}</span></button>`).join("");
    strip.querySelectorAll(".rw-stop:not([disabled])").forEach(b=>b.addEventListener("click",(e)=>{
      e.stopPropagation();
      activeId = idea.id;
      const st = b.dataset.stop;
      if (st==="who") s.phase = 2;
      else if (st==="words"){ s.phase = 4; s.copyPackPage = 1; }
      else if (st==="opener"){ s.phase = 4; s.copyPackPage = 2; }
      else if (st==="go") s.phase = s.phase===7 ? 7 : 6;
      renderAll();
    }));
    card.appendChild(strip);
  });
};
renderAll();
</script>"""

TREATMENTS = {
  "l1": ("Launch walkthrough L1 — Chips do the work", L1_CSS, L1_JS),
  "l2": ("Launch walkthrough L2 — One decision per screen", L2_CSS, L2_JS),
  "l3": ("Launch walkthrough L3 — Launch runway", L3_CSS, L3_JS),
}

for key, (title, css, js) in TREATMENTS.items():
    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", src, count=1, flags=re.S)
    block = (f'<style id="lab-style">{SHARED_CSS}{css}</style>\n{CAPTURE}\n'
             f'<script id="lab-fixture">\n{FIXTURE}\n</script>\n{js}\n')
    if "</body>" in html:
        html = html.replace("</body>", block + "</body>", 1)
    else:
        html += block
    out = os.path.join(OUT_DIR, f"{key}.html")
    open(out, "w", encoding="utf-8").write(html)
    print(f"built {out} ({len(html)} bytes)")
print("ok")
