// wizard-launch-lab shared fixture + overrides (Step 1) · 2026-07-27
// Appended to a hydrated copy of wizard-template.html AFTER a capture block
// that saved base renderers into LAB.base. All overrides use assignment form
// (no function declarations) so execution order is explicit. Zero provider
// calls: every number replays sessions/navreo-2026-07-27-run.json.

/* eslint-disable */
LAB.data = {
  "growth-hiring": {
    triggerLabel: "Roles they're hiring for",
    chips: [["Marketing Manager",2830],["Account Executive",1620],["Sales Manager",1190],
      ["Head of Marketing",640],["Head of Growth",460],["Growth Marketing",420],
      ["Performance Marketing Manager",380],["Partnerships Manager",300],["VP Marketing",130],
      ["Growth Manager",90],["Head of Business Development",25]],
    pool: [["Marketing Director",520],["Digital Marketing Manager",680],["Content Marketing Manager",240],
      ["Growth Lead",60],["Field Marketing Manager",70],["Lifecycle Marketing Manager",90]],
    whoWeEmail: ["Founder","CEO","Managing Director","Head of Sales","VP Sales"]
  },
  "jd-outbound": {
    triggerLabel: "Roles they're hiring for",
    chips: [["Account Executive",760],["SDR",590],["BDR",470],["Head of Sales",230],
      ["Sales Manager",200],["Head of Growth",130],["Growth Marketing",110],["Demand Generation",100],
      ["Revenue Operations",84],["VP of Sales",70],["Head of Business Development",50],
      ["Chief Revenue Officer",30],["GTM Engineer",20]],
    pool: [["Sales Executive",240],["Outbound SDR",120],["New Business Manager",90]],
    whoWeEmail: ["Founder","CEO","Managing Director","Head of Sales"]
  },
  "stack": {
    triggerLabel: "Tools they run",
    chips: [["Apollo",260],["Outreach",180],["Salesloft",130],["ZoomInfo",90],["Clay",80],
      ["Instantly",60],["Smartlead",45],["Lemlist",30]],
    pool: [["Salesforce",890],["HubSpot Sales Hub",210],["Amplemarket",25]],
    whoWeEmail: ["Founder","CEO","Head of Sales","VP Sales"]
  },
  "newrole": {
    triggerLabel: "Who counts as new",
    chips: [["Head of Sales",24800],["Sales Director",19400],["VP Sales",12300],
      ["Director of Business Development",8200],["Head of Business Development",5100],
      ["Chief Revenue Officer",2777]],
    pool: [["Commercial Director",3900],["VP Business Development",2100],["Chief Growth Officer",900]],
    whoWeEmail: ["The new leader directly"]
  }
};
LAB.shelf = [{
  name: "Commercial cleaning scale-up", net: 754, status: "Live · in Smartlead #3651763",
  note: "Launched from an earlier session. Sending is handled in Smartlead."
}];
LAB.origNet = {};

// ---- helpers -------------------------------------------------------------
LAB.ensureChips = function(idea, s){
  if (s.labChips) return;
  const d = LAB.data[idea.id] || {};
  LAB.origNet[idea.id] = idea.net;
  // Chip NAMES track the live run.json (idea.targeting.roles) so the lab never
  // drifts from the current board; counts are illustrative weights normalised
  // to sum EXACTLY to idea.net (largest-remainder), so headline == sum(chips)
  // on first paint and after any remove/re-add round trip.
  const roles = (idea.targeting && idea.targeting.roles && idea.targeting.roles.length)
    ? idea.targeting.roles : (d.chips || []).map(c => c[0]);
  const raw = roles.map((n, k) => 1 / (k + 2) + ((n.length % 5) / 50));
  const tot = raw.reduce((a, b) => a + b, 0) || 1;
  const exact = raw.map(w => idea.net * w / tot);
  const counts = exact.map(Math.floor);
  let left = idea.net - counts.reduce((a, b) => a + b, 0);
  exact.map((e, k) => [e - counts[k], k]).sort((a, b) => b[0] - a[0])
    .forEach(([, k]) => { if (left > 0) { counts[k]++; left--; } });
  s.labChips = roles.map((n, k) => ({ name: n, count: counts[k], on: true, est: false }));
  s.labWho = (d.whoWeEmail || ["Founder", "CEO", "Managing Director"]).map(n => ({ name: n }));
  s.labWhoTotal = s.labWho.length;
  s.labPoolIdx = 0;
};
LAB.sum = function(s){
  const trig = s.labChips.filter(c=>c.on!==false).reduce((a,c)=>a+c.count,0);
  const f = s.labWhoTotal ? (s.labWho.length / s.labWhoTotal) : 1;
  return Math.round(trig * f);
};
LAB.estCount = function(name){ return 40 + (name.length * 7) % 260; };
LAB.scaleSplit = function(idea){
  const base = LAB.origNet[idea.id] || idea.net;
  const r = base ? idea.net / base : 1;
  if (idea.freeFromRecords) {
    idea.freeFromRecords = Math.max(0, Math.round((LAB.origSplit[idea.id][0]) * r));
    idea.newPeople = Math.max(0, idea.net - idea.freeFromRecords);
  }
};
LAB.origSplit = {};
LAB.recount = function(idea, s){
  const target = LAB.sum(s);
  // resolve nodes lazily: a rerender inside the 500ms window replaces the
  // workspace DOM, so querying at call time animates an orphaned node
  const capNow = document.querySelector(".lab-recount-cap");
  if (capNow) capNow.textContent = "re-checking…";
  const apply = () => {
    idea.net = target;
    LAB.scaleSplit(idea);
    const numEl = document.querySelector(".lab-live-num");
    const cap = document.querySelector(".lab-recount-cap");
    // direct set, not animateCountUp: rAF is throttled in background/driven
    // panes, which left the headline one edit behind the rail
    if (numEl) numEl.textContent = target.toLocaleString();
    if (cap) cap.textContent = "estimate · re-checked free before launch";
    renderList(); // rail number follows
  };
  setTimeout(apply, 500);
};

// ---- chip editor (pattern: the tool's "Who should they be hiring?" modal) --
LAB.editorHtml = function(idea, s){
  const d = LAB.data[idea.id]; if (!d) return "";
  LAB.ensureChips(idea, s);
  const chip = (c, i) => `<span class="trg-chip lab-chip${c.on===false?" trg-off":""}" data-i="${i}">
      ${esc(c.name)}${c.est?'<i class="lab-est">est</i>':""}
      <button class="lab-x" data-x="${i}" aria-label="${c.on===false?"Put back":"Remove"} ${esc(c.name)}" type="button">${c.on===false?"+":"&times;"}</button></span>`;
  const who = (c, i) => `<span class="trg-chip lab-chip" data-w="${i}">${esc(c.name)}
      ${s.labWho.length>1?`<button class="lab-x" data-wx="${i}" aria-label="Remove ${esc(c.name)}" type="button">&times;</button>`:""}</span>`;
  return `
  <div class="targeting-box lab-editor">
    <p class="targeting-head">${esc(d.triggerLabel)}</p>
    <div class="targeting-chips">${s.labChips.map(chip).join("")}</div>
    <div class="lab-add-row">
      <input class="lab-add" data-g="t" type="text" placeholder="add a role…" aria-label="Add a role">
      <button class="lab-add-btn" data-add="t" type="button" aria-label="Add">+</button>
      <button class="lab-gen" type="button">&#9998; Generate more</button>
    </div>
    <p class="targeting-head" style="margin-top:12px">Who we email</p>
    <div class="targeting-chips">${s.labWho.map(who).join("")}</div>
    ${LAB.data[idea.id].whoWeEmail.length>1?`<div class="lab-add-row">
      <input class="lab-add" data-g="w" type="text" placeholder="add a role…" aria-label="Add who we email">
      <button class="lab-add-btn" data-add="w" type="button" aria-label="Add">+</button></div>`:""}
  </div>`;
};
LAB.wireEditor = function(el, idea, s, rerender){
  el.querySelectorAll(".lab-x[data-x]").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation();
    const on = s.labChips.filter(c=>c.on!==false);
    const c = s.labChips[+b.dataset.x];
    if (on.length <= 1 && c.on!==false) return; // last chip stays
    c.on = c.on === false ? true : false;
    rerender(); LAB.recount(idea, s);
  }));
  el.querySelectorAll(".lab-x[data-wx]").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation();
    if (s.labWho.length <= 1) return;
    s.labWho.splice(+b.dataset.wx, 1); rerender(); LAB.recount(idea, s);
  }));
  el.querySelectorAll(".lab-add-btn").forEach(b => b.addEventListener("click", () => {
    const inp = el.querySelector(`.lab-add[data-g="${b.dataset.add==="t"?"t":"w"}"]`);
    const v = (inp.value || "").trim(); if (!v) return;
    if (b.dataset.add === "t") { s.labChips.push({name:v, count:LAB.estCount(v), on:true, est:true}); LAB.recount(idea, s); }
    else { s.labWho.push({name:v}); LAB.recount(idea, s); }
    inp.value = ""; rerender();
  }));
  el.querySelectorAll(".lab-add").forEach(inp => inp.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); el.querySelector(`.lab-add-btn[data-add="${inp.dataset.g}"]`).click(); }
  }));
  const gen = el.querySelector(".lab-gen");
  if (gen) gen.addEventListener("click", () => {
    const pool = LAB.data[idea.id].pool || [];
    let added = 0;
    while (added < 3 && s.labPoolIdx < pool.length) {
      const p = pool[s.labPoolIdx++];
      if (!s.labChips.some(c => c.name === p[0])) { s.labChips.push({name:p[0], count:p[1], on:true, est:true}); added++; }
    }
    if (added) { rerender(); LAB.recount(idea, s); }
    else { gen.textContent = "No more suggestions"; gen.disabled = true; }
  });
};

// ---- F3: sendable emails only (peerProofLine never enters a body) ---------
variantsFor = function(i){
  const optout = "If this isn't for you, just say so and I won't follow up.";
  const offerLine = "If it fits, we run it on a pay-per-lead basis, so you only pay for the leads we deliver.";
  const proof = "We've booked calls for 50+ firms doing exactly this, and it's driven $15M+ in pipeline along the way.";
  return [
    { label:"Version A", angle:"The video", subject:`Is this relevant ${i.firstName}?`,
      body:`Hi ${i.firstName},\n\n{{Personal opening line}}\n\n${i.pain}\n\n${proof}\n\nI recorded a short video for ${i.company} showing what we'd build to fix that.\n\n${offerLine}\n\nShould I send it over?\n\n${optout}\n\nP.S - We'll run a pilot at no cost, and if it works we can talk about doing more.` },
    { label:"Version B", angle:"The mapped plan", subject:"Quick thought",
      body:`Hi ${i.firstName},\n\n{{Personal opening line}}\n\n${i.pain}\n\n${proof}\n\nSo we've already mapped out how we'd help ${i.company}: who we'd reach out to, what we'd say, and when.\n\n${offerLine}\n\nCan I share it?\n\n${optout}\n\nP.S - Happy to send the exact playbook first, at no cost, before you commit to anything.` },
    { label:"Version C", angle:"The question", subject:`Worth a look, ${i.firstName}?`,
      body:`Hi ${i.firstName},\n\n{{Personal opening line}}\n\n${i.moment}\n\nMost firms in that spot are so busy delivering that new conversations quietly dry up.\n\nIf we could keep ${i.company}'s calendar filled with the right meetings, would you be open to seeing exactly how, in a two-minute video?\n\n${offerLine}\n\n${optout}` },
    { label:"Version D", angle:"The moment", subject:"While your competitors wait",
      body:`Hi ${i.firstName},\n\n{{Personal opening line}}\n\n${i.moment}\n\nThe firms that start those conversations first win the work.\n\nWe'd run that outreach for ${i.company}, done for you. ${offerLine}\n\nCould I send a one-pager on how we'd run it?\n\n${optout}\n\nP.S - You only pay once a qualified lead shows up, so there's nothing to lose trying it.` }
  ];
};

// ---- F4: revisits never re-run finished builds ----------------------------
runBuild = function(idea, s, phaseKey){
  const stages = stagesFor(idea);
  const phaseIndices = stages.map((st, idx) => ({ st, idx })).filter(x => x.st.phase === phaseKey);
  const remaining = phaseIndices.filter(x => x.idx >= s.stagesDone);
  const finish = () => {
    s.phase = phaseKey === "A" ? 4 : 6;
    if (activeId === idea.id) renderAll(); else renderList();
  };
  if (!remaining.length) { finish(); return; }
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const step = (pos) => {
    if (pos >= remaining.length) { finish(); return; }
    const { st, idx } = remaining[pos];
    const ms = delayFor(st.ms);
    if (activeId === idea.id) {
      const hero = document.getElementById("build-hero-" + idea.id);
      if (hero) {
        const fill = hero.querySelector(".stage-bar-fill");
        if (fill) { if (reduceMotion) fill.style.width = "100%";
          else requestAnimationFrame(() => { fill.style.transitionDuration = ms + "ms"; fill.style.width = "100%"; }); }
        const numEl = hero.querySelector(".build-hero-num");
        const target = BUILD_STAGE_NUM[idx] ? BUILD_STAGE_NUM[idx](idea) : null;
        if (numEl && target != null) animateCountUp(numEl, target, ms, reduceMotion);
      }
    }
    setTimeout(() => { s.stagesDone = Math.max(s.stagesDone, idx + 1);
      if (activeId === idea.id) renderAll(); else renderList(); step(pos + 1); }, ms);
  };
  step(0);
};

// ---- shared renderTargeting: the chip editor IS the who-gate --------------
renderTargeting = function(idea, s){
  // ideas with no targeting data (other clients' runs, older boards) keep the
  // base free-text who-gate instead of an empty chip editor
  if (!(idea.targeting && idea.targeting.roles && idea.targeting.roles.length) && !LAB.data[idea.id]) {
    return LAB.base.renderTargeting(idea, s);
  }
  const el = document.createElement("div");
  LAB.ensureChips(idea, s);
  el.innerHTML = `
    <p class="lab-gate-line">Who this reaches. Edit it, then confirm.</p>
    <p class="lab-live-wrap"><span class="lab-live-num num mono">${idea.net.toLocaleString()}</span>
      <span class="lab-live-unit">${esc(idea.netUnit || "people we can reach")}</span></p>
    <p class="lab-recount-cap edit-caption"></p>
    ${LAB.editorHtml(idea, s)}
    <div class="actions"><button class="btn btn-primary" type="button" data-act="confirm">Looks right</button></div>`;
  const rerender = () => { const fresh = renderTargeting(idea, s); el.replaceWith(fresh); };
  LAB.wireEditor(el, idea, s, rerender);
  el.querySelector('[data-act="confirm"]').addEventListener("click", () => {
    s.phase = 3; renderAll(); runBuild(idea, s, "A");
  });
  return el;
};

// ---- F1: "Already running" shelf below the fresh menu ---------------------
renderList = function(){
  LAB.base.renderList();
  const old = document.getElementById("lab-shelf"); if (old) old.remove();
  if (!LAB.shelf.length) return; // no running campaigns -> no shelf header
  const shelf = document.createElement("div");
  shelf.id = "lab-shelf";
  shelf.innerHTML = `<p class="shelf-head">Already running</p>` + LAB.shelf.map(x => `
    <div class="shelf-mini" title="${esc(x.note)}">
      <div class="im-rest-row"><p class="im-name">${esc(x.name)}</p>
        <p class="im-number mono">${x.net.toLocaleString()}</p>
        <span class="state-dot dot-ready"></span></div>
      <p class="im-caption">${esc(x.status)}</p>
    </div>`).join("");
  listEl.appendChild(shelf);
};

// ---- F4: a Back control on every screen -----------------------------------
LAB.backTarget = function(s){
  if (!s) return null;
  if (s.phase <= 1) return { deselect: true };
  if (s.phase === 2) return { phase: 1 };
  if (s.phase === 3) return { deselect: true };            // build continues in background
  if (s.phase === 4) return s.copyPackPage === 2 ? { page: 1 } : { phase: 2 };
  if (s.phase === 5) return { phase: 4 };
  if (s.phase === 6) return { phase: 4, page: 2 };
  if (s.phase === 7) return { phase: 6 };
  return { deselect: true };
};
renderWorkspace = function(){
  LAB.base.renderWorkspace();
  if (!activeId) return;
  const s = cardState[activeId]; // undefined for the validation card
  const t = s ? LAB.backTarget(s) : { deselect: true };
  const back = document.createElement("button");
  back.type = "button"; back.className = "lab-back";
  back.setAttribute("aria-label", "Back");
  back.innerHTML = "&#8249; Back";
  back.addEventListener("click", () => {
    if (t.deselect) { activeId = null; renderAll(); return; }
    if (t.page) { s.copyPackPage = t.page; s.phase = 4; renderAll(); return; }
    s.phase = t.phase; if (t.phase === 4) s.copyPackPage = s.copyPackPage || 1; renderAll();
  });
  wsEl.insertBefore(back, wsEl.firstChild);
};

// ---- shared minimal preview (used by L2 and L3): number, chips, Start ------
LAB.minimalIntro = function(idea, s){
  LAB.ensureChips(idea, s);
  const el = document.createElement("div");
  const chips = s.labChips.slice(0,6).map(c=>`<span class="trg-chip">${esc(c.name)}</span>`).join("")
    + (s.labChips.length>6?`<span class="trg-chip">+${s.labChips.length-6} more</span>`:"");
  el.innerHTML = `
    <p class="lab-live-wrap"><span class="lab-live-num num mono">${idea.net.toLocaleString()}</span>
      <span class="lab-live-unit">${esc(idea.netUnit||"people we can reach")}</span></p>
    <div class="l2-chips targeting-chips" style="margin:12px 0">${chips}</div>
    <p class="l1-fact" tabindex="0"><b>Offer &#9662;</b>${esc(idea.offer)}</p>
    <div class="actions"><button class="btn btn-primary" type="button" data-act="start">Start</button></div>`;
  el.querySelector('.l1-fact').addEventListener("click",(e)=>e.currentTarget.classList.toggle("open"));
  el.querySelector('[data-act="start"]').addEventListener("click", () => { s.phase = 2; renderAll(); });
  return el;
};

// ---- init: record original splits for proportional re-scaling -------------
IDEAS.forEach(i => { LAB.origSplit[i.id] = [i.freeFromRecords || 0, i.newPeople || 0]; });
renderAll();
