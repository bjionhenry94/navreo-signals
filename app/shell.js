/* Shared shell: rail nav, data loading, small helpers. */

/* Icons8 "Windows 10" set, rendered via CSS mask so they inherit color */
function ic8(name, cls = "") {
  return `<span class="ic8 ${cls}" style="--icon:url('icons/${name}.png')"></span>`;
}

const ICONS = {
  dashboard: ic8("home", "lg"),
  campaigns: ic8("send", "lg"),
  lists: ic8("data", "lg"),
  deliverability: ic8("check", "lg"),
  notifications: ic8("bell", "lg"),
};

const NAV = [
  ["index.html", "dashboard", "Dashboard"],
  ["campaigns.html", "campaigns", "Campaigns"],
  ["lists.html", "lists", "Lists"],
  ["deliverability.html", "deliverability", "Deliverability"],
  ["notifications.html", "notifications", "Notifications"],
];

function renderRail(active) {
  const items = NAV.map(([href, key, label]) =>
    `<a class="nav-i ${key === active ? "on" : ""}" href="${href}" title="${label}">${ICONS[key]}</a>`
  ).join("");
  return `<nav class="rail">
    <a class="logo" href="index.html" title="Navreo">n</a>
    ${items}
    <div class="spacer"></div>
    <div class="avatar">BH</div>
  </nav>`;
}

async function loadData(...names) {
  const out = {};
  await Promise.all(names.map(async (n) => {
    try {
      const r = await fetch(`data/${n}.json`, { cache: "no-store" });
      out[n] = r.ok ? await r.json() : null;
    } catch { out[n] = null; }
  }));
  return out;
}

/* helpers */
const fmt = (n) => (n === null || n === undefined || isNaN(n)) ? "–" : Number(n).toLocaleString("en-GB");
const pct = (num, den, digits = 1) => den > 0 ? (100 * num / den).toFixed(digits) + "%" : "–";
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
/* "when was this last pulled" — a relative phrase the user reads at a glance
   ("3 days ago"), with the exact local timestamp on hover. Replaces the raw
   "07-06 15:38" slice, which was year-less, timezone-ambiguous, and made the
   reader compute staleness themselves. Server writes last_pull/pulled_at in UTC
   with no zone (datetime.now() on Render), so a zone-less string is tagged Z and
   localised for display. Returns an HTML <span>; the phrase is already escaped. */
function pulledAgo(iso) {
  if (!iso) return "";
  let s = String(iso).trim().replace(" ", "T");
  if (!/(?:[zZ]|[+-]\d\d:?\d\d)$/.test(s)) s += "Z";  // tag zone-less UTC
  const then = new Date(s);
  if (isNaN(then.getTime())) return esc(String(iso));  // unparseable -> show raw, never crash
  const secs = Math.max(0, (Date.now() - then.getTime()) / 1000);
  const plur = (n, w) => `${n} ${w}${n === 1 ? "" : "s"} ago`;
  let rel;
  if (secs < 45) rel = "just now";
  else if (secs < 3600) rel = plur(Math.round(secs / 60) || 1, "min");
  else if (secs < 86400) rel = plur(Math.floor(secs / 3600), "hour");
  else if (secs < 86400 * 7) rel = plur(Math.floor(secs / 86400), "day");
  else {
    const sameYear = then.getFullYear() === new Date().getFullYear();
    rel = "on " + then.toLocaleDateString("en-GB",
      sameYear ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" });
  }
  const full = then.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  return `<span title="${esc(full)} (your local time)">${esc(rel)}</span>`;
}
/* the proof behind a prospect — job post for hiring, post URL for engagement */
const sigHref = (p) => p.signal_url || p.job_url || "";
const sigTitle = (p) => p.hiring_for ? `Hiring: ${p.hiring_for}` : "The signal that surfaced this person";

function statusPill(status) {
  const map = { ACTIVE: "g", PAUSED: "a", COMPLETED: "n", STOPPED: "n", DRAFTED: "n" };
  const cls = map[status] || "n";
  return `<span class="pill ${cls}"><span class="dot"></span>${esc(status || "?")}</span>`;
}

function freshnessBlock(meta) {
  if (!meta) return "";
  const dt = new Date(meta.fetched_at);
  return `<div class="freshness">Snapshot <b>${dt.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</b> · read-only</div>`;
}

/* toast note. Pass {sticky:true} for an in-flight message that stays up until the
   next protoNote replaces it (a plain result toast auto-hides after ~2.6s) — this
   keeps a "Finding people…" message visible for the whole of a long server call. */
function protoNote(msg = "Read-only prototype", opts = {}) {
  let el = document.querySelector(".proto-note");
  if (!el) {
    el = document.createElement("div");
    el.className = "proto-note";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  requestAnimationFrame(() => el.classList.add("on"));
  clearTimeout(el._t);
  if (!opts.sticky) el._t = setTimeout(() => el.classList.remove("on"), opts.ms || 2600);
}

/* Put a button into a working state: inline spinner + label, disabled so it can't
   be double-clicked while the action runs. Returns a restore() that puts the button
   back exactly how it was (safe to call even after a re-render has replaced it).
   Returns null if the button is ALREADY busy — callers use that to bail out of a
   duplicate submit, which is the whole point: no more "did my click work?" re-clicks. */
function busyBtn(btn, label = "Working…") {
  if (!btn) return () => {};                 // caller had no element (e.g. auto-triggered) — no-op
  if (btn.dataset.busy === "1") return null; // second click while the first is in flight — ignore it
  const html = btn.innerHTML, wasDisabled = btn.disabled;
  btn.dataset.busy = "1";
  btn.classList.add("busy");
  btn.setAttribute("aria-busy", "true");
  btn.disabled = true;
  btn.innerHTML = `<span class="btnspin"></span>${esc(label)}`;
  return () => {
    delete btn.dataset.busy;
    btn.classList.remove("busy");
    btn.removeAttribute("aria-busy");
    btn.disabled = wasDisabled;
    btn.innerHTML = html;
  };
}

/* force-hide the toast now — call on step changes / modal open+close so a stale
   validation message never lingers across the flow or after a dialog is dismissed */
function hideNote() {
  const el = document.querySelector(".proto-note");
  if (el) { clearTimeout(el._t); el.classList.remove("on"); }
}

/* tiny dependency-free line chart */
function lineChart(el, series, opts = {}) {
  const w = opts.width || el.clientWidth || 800, h = opts.height || 180;
  const pad = { l: 34, r: 10, t: 12, b: 22 };
  const all = series.flatMap((s) => s.points.map((p) => p.y));
  const maxY = Math.max(1, ...all);
  const n = Math.max(2, series[0]?.points.length || 2);
  const x = (i) => pad.l + (i / (n - 1)) * (w - pad.l - pad.r);
  const y = (v) => pad.t + (1 - v / maxY) * (h - pad.t - pad.b);
  let svg = `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:${h}px;display:block">`;
  for (let g = 0; g <= 3; g++) {
    const gy = pad.t + (g / 3) * (h - pad.t - pad.b);
    svg += `<line x1="${pad.l}" y1="${gy}" x2="${w - pad.r}" y2="${gy}" stroke="#ECE5DC" stroke-width="1"/>`;
    svg += `<text x="${pad.l - 6}" y="${gy + 3.5}" text-anchor="end" font-size="10" fill="#A89684">${Math.round(maxY * (1 - g / 3))}</text>`;
  }
  series.forEach((s) => {
    const d = s.points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join("");
    svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"/>`;
  });
  const labels = series[0]?.points || [];
  const step = Math.ceil(labels.length / 6);
  labels.forEach((p, i) => {
    if (i % step === 0) svg += `<text x="${x(i)}" y="${h - 6}" text-anchor="middle" font-size="10" fill="#A89684">${esc(p.label || "")}</text>`;
  });
  svg += "</svg>";
  el.innerHTML = chartWrap(svg, {
    W: w, H: h, padT: pad.t, padB: pad.b, maxV: maxY,
    xs: labels.map((_, i) => +x(i).toFixed(1)),
    labels: labels.map((p) => p.label || ""),
    // `vals` position the hover dot on the drawn line (may be scaled); `disp` is the
    // true number shown in the tooltip (pass p.raw when the plotted y is scaled).
    series: series.map((s) => ({
      name: s.name || "", color: s.color,
      vals: s.points.map((p) => p.y),
      disp: s.points.map((p) => (p.raw != null ? p.raw : p.y)),
    })),
    suffix: opts.suffix || "",
  });
  hydrateCharts(el);
}

/* Wrap a built <svg> string in a positioned container that carries the chart's
   data payload, so hydrateCharts() can wire an interactive tooltip after insertion.
   The JSON is HTML-escaped for the attribute; getAttribute() decodes it back. */
function chartWrap(svg, cfg) {
  return `<div class="chartwrap" data-chart="${esc(JSON.stringify(cfg))}">${svg}</div>`;
}

/* Find every chart container under `root` (inclusive) and attach hover tooltips. */
function hydrateCharts(root) {
  if (!root) return;
  const wraps = [];
  if (root.matches && root.matches(".chartwrap[data-chart]")) wraps.push(root);
  if (root.querySelectorAll) root.querySelectorAll(".chartwrap[data-chart]").forEach((w) => wraps.push(w));
  wraps.forEach(setupChartTooltip);
}

/* Attach a crosshair + floating tooltip to one .chartwrap. Uses the SVG's own
   coordinate transform (getScreenCTM) so hit-testing and positioning stay correct
   under viewBox scaling and preserveAspectRatio letterboxing at any pixel width. */
function setupChartTooltip(wrap) {
  if (wrap._ttReady) return;
  let cfg; try { cfg = JSON.parse(wrap.getAttribute("data-chart")); } catch { return; }
  const svg = wrap.querySelector("svg");
  if (!svg || !cfg || !Array.isArray(cfg.xs) || !cfg.xs.length) return;
  wrap._ttReady = true;

  const { W, H, padT, padB, maxV, xs, labels, series, suffix } = cfg;
  const NS = "http://www.w3.org/2000/svg";
  const yOf = (v) => padT + (1 - v / maxV) * (H - padT - padB);

  const guide = document.createElementNS(NS, "line");
  guide.setAttribute("y1", padT); guide.setAttribute("y2", H - padB);
  guide.setAttribute("stroke", "var(--ink-3, #6B6055)");
  guide.setAttribute("stroke-width", "1"); guide.setAttribute("stroke-dasharray", "3 3");
  guide.setAttribute("pointer-events", "none"); guide.style.opacity = "0";
  svg.appendChild(guide);

  const dots = series.map((s) => {
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("r", "3.5"); c.setAttribute("fill", "var(--bg, #fff)");
    c.setAttribute("stroke", s.color); c.setAttribute("stroke-width", "2");
    c.setAttribute("pointer-events", "none"); c.style.opacity = "0";
    svg.appendChild(c); return c;
  });

  const tip = document.createElement("div");
  tip.className = "charttip"; tip.style.opacity = "0";
  wrap.appendChild(tip);

  const pt = svg.createSVGPoint();
  const toLocal = (clientX, clientY) => {
    const ctm = svg.getScreenCTM(); if (!ctm) return null;
    pt.x = clientX; pt.y = clientY;
    return pt.matrixTransform(ctm.inverse());
  };
  const nearestIdx = (localX) => {
    let best = 0, bd = Infinity;
    for (let i = 0; i < xs.length; i++) { const d = Math.abs(xs[i] - localX); if (d < bd) { bd = d; best = i; } }
    return best;
  };

  function show(i) {
    const gx = xs[i];
    guide.setAttribute("x1", gx); guide.setAttribute("x2", gx);
    guide.style.opacity = xs.length > 1 ? "1" : "0";
    series.forEach((s, si) => {
      const v = s.vals[i];
      if (v == null || isNaN(v)) { dots[si].style.opacity = "0"; return; }
      dots[si].setAttribute("cx", gx); dots[si].setAttribute("cy", +yOf(v).toFixed(1));
      dots[si].style.opacity = "1";
    });
    tip.innerHTML = `<div class="charttip-h">${esc(labels[i] || "")}</div>` +
      series.map((s, si) => `<div class="charttip-r"><span class="charttip-sw" style="background:${s.color}"></span>` +
        `${s.name ? `<span class="charttip-nm">${esc(s.name)}</span>` : ""}` +
        `<b>${fmt((s.disp || s.vals)[i])}${suffix || ""}</b></div>`).join("");

    const ctm = svg.getScreenCTM(); const wr = wrap.getBoundingClientRect();
    pt.x = gx; pt.y = padT; const sc = pt.matrixTransform(ctm);
    tip.style.opacity = "1";
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let left = sc.x - wr.left - tw / 2;
    left = Math.min(Math.max(left, 4), wrap.clientWidth - tw - 4);
    let top = sc.y - wr.top - th - 10;
    if (top < 4) top = sc.y - wr.top + 14;
    tip.style.left = left + "px"; tip.style.top = top + "px";
  }
  function hide() { guide.style.opacity = "0"; dots.forEach((d) => (d.style.opacity = "0")); tip.style.opacity = "0"; }

  const move = (e) => { const l = toLocal(e.clientX, e.clientY); if (l) show(nearestIdx(l.x)); };
  wrap.style.touchAction = "pan-y";
  wrap.addEventListener("pointermove", move);
  wrap.addEventListener("pointerdown", move);
  wrap.addEventListener("pointerleave", hide);
}

/* ── Tasks in progress sidebar ─────────────────────────────
   Self-contained widget: its own DOM, its own <style>, plain fetch only.
   Deliberately does NOT call any other helper in this file (esc, fmt, pulledAgo,
   etc.) so it works even on pages that only load a stub of shell.js — this is
   the one bit of shell.js allowed to be "unshipped" without breaking the page. */
(function () {
  const POLL_FAST_MS = 4000;
  const POLL_SLOW_MS = 45000;
  const LS_OPEN_KEY = "nav_jobs_panel_open";

  let jobs = [];
  let havePolledOnce = false;
  let knownIds = new Set();
  let userClosedThisView = false;
  let pollTimer = null;
  let warnedOnce = false;
  let backendOk = false;

  let elRoot, elTab, elBadge, elPanel, elList;

  function jEsc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function jRelTime(iso) {
    if (!iso) return "";
    let s = String(iso).trim().replace(" ", "T");
    if (!/(?:[zZ]|[+-]\d\d:?\d\d)$/.test(s)) s += "Z";
    const then = new Date(s);
    if (isNaN(then.getTime())) return "";
    const secs = Math.max(0, (Date.now() - then.getTime()) / 1000);
    if (secs < 45) return "just now";
    if (secs < 3600) { const m = Math.max(1, Math.round(secs / 60)); return `${m}m ago`; }
    if (secs < 86400) { const h = Math.floor(secs / 3600); return `${h}h ago`; }
    const d = Math.floor(secs / 86400);
    return `${d}d ago`;
  }

  function isOpenSaved() {
    try { return localStorage.getItem(LS_OPEN_KEY) === "1"; } catch { return false; }
  }
  function saveOpen(v) {
    try { localStorage.setItem(LS_OPEN_KEY, v ? "1" : "0"); } catch { /* ignore */ }
  }

  function statusLabel(status) {
    return { queued: "Queued", running: "Running", done: "Done", failed: "Failed", cancelled: "Cancelled", interrupted: "Interrupted" }[status] || jEsc(status || "?");
  }
  function statusClass(status) {
    return { queued: "jq-n", running: "jq-b", done: "jq-g", failed: "jq-r", cancelled: "jq-c", interrupted: "jq-r" }[status] || "jq-n";
  }

  function countsLine(job) {
    const c = job.counts;
    if (job.status === "interrupted") return jEsc(job.error || "Server restarted mid-run — re-run to resume (already-checked emails are cached).");
    if (job.error && job.status === "failed") return jEsc(job.error);
    if (job.status === "cancelled") {
      const kind = String(job.kind || "").toLowerCase();
      if (c && typeof c === "object" && (c.deleted != null || c.removed != null) && kind.includes("remove")) {
        return `${jEsc(c.deleted ?? c.removed)} removed before cancel`;
      }
      const done = job.progress && job.progress.done;
      if (done != null && done > 0) return `${jEsc(done)} checked before cancel`;
      return "stopped before finishing";
    }
    if (!c || typeof c !== "object") return "";
    const kind = String(job.kind || "").toLowerCase();
    if (kind.includes("verify")) {
      const checked = c.checked ?? c.total ?? "–";
      const good = c.good ?? "–", ca = c.catch_all ?? c.catchAll ?? "–", unk = c.unknown ?? "–", bad = c.bad ?? "–";
      return `${jEsc(checked)} checked · ${jEsc(good)} good / ${jEsc(ca)} catch-all / ${jEsc(unk)} unknown / ${jEsc(bad)} bad`;
    }
    if (kind.includes("remove")) {
      const removed = c.removed ?? "–";
      const kept = c.kept ?? c.kept_replied ?? "–";
      return `${jEsc(removed)} removed · ${jEsc(kept)} kept (replied)`;
    }
    const parts = Object.keys(c).slice(0, 6).map((k) => `${jEsc(k)}: ${jEsc(c[k])}`);
    return parts.join(" · ");
  }

  function injectStyle() {
    if (document.getElementById("nav-jobs-style")) return;
    const style = document.createElement("style");
    style.id = "nav-jobs-style";
    style.textContent = `
#nav-jobs-tab {
  position: fixed; top: 50%; right: 0; transform: translateY(-50%);
  z-index: 200; display: none;
  background: var(--card, #fff); color: var(--ink-2, #3A332C);
  border: 1px solid var(--line, #ECECEA); border-right: none;
  border-radius: 10px 0 0 10px;
  padding: 12px 8px; cursor: pointer;
  font: 500 12px var(--font-sans, sans-serif); letter-spacing: -0.01em;
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  box-shadow: -2px 2px 10px rgba(20, 17, 14, 0.08);
}
#nav-jobs-tab.nj-show { display: flex; }
#nav-jobs-tab .nj-label {
  writing-mode: vertical-rl; text-orientation: mixed; transform: rotate(180deg);
}
#nav-jobs-tab .nj-badge {
  min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px;
  background: var(--orange, #FF4D00); color: #fff;
  font-size: 10.5px; font-weight: 600; line-height: 18px; text-align: center;
  display: none;
}
#nav-jobs-tab .nj-badge.nj-on { display: inline-block; }
#nav-jobs-tab .nj-badge.nj-pulse { animation: nj-pulse 1.2s ease-in-out infinite; }
#nav-jobs-tab.nj-flash { animation: nj-flash 1.1s ease-in-out; }
@keyframes nj-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255, 77, 0, 0.5); }
  50% { box-shadow: 0 0 0 5px rgba(255, 77, 0, 0); }
}
@keyframes nj-flash {
  0%, 100% { box-shadow: -2px 2px 10px rgba(20, 17, 14, 0.08); }
  30% { box-shadow: 0 0 0 4px rgba(255, 77, 0, 0.35); }
}
#nav-jobs-panel {
  position: fixed; top: 0; right: 0; height: 100vh; width: 320px; max-width: 90vw;
  background: var(--bg, #fff); border-left: 1px solid var(--line, #ECECEA);
  box-shadow: -8px 0 24px rgba(20, 17, 14, 0.12);
  z-index: 201; display: none; flex-direction: column;
  transform: translateX(100%); transition: transform 0.22s ease;
}
#nav-jobs-panel.nj-open { display: flex; transform: translateX(0); }
#nav-jobs-tab.nj-shifted { right: min(320px, 90vw); z-index: 202; }
#nav-jobs-panel .nj-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 16px 12px; border-bottom: 1px solid var(--line, #ECECEA); flex: none;
}
#nav-jobs-panel .nj-title {
  font-family: var(--font-display, sans-serif); font-size: 15px; color: var(--ink, #14110E);
}
#nav-jobs-panel .nj-close {
  border: none; background: none; cursor: pointer; font-size: 18px; line-height: 1;
  color: var(--ink-3, #6B6055); padding: 4px 6px; border-radius: 6px;
}
#nav-jobs-panel .nj-close:hover { background: var(--bg-sunken, #F7F7F6); }
#nav-jobs-panel .nj-head-actions { display: flex; align-items: center; gap: 6px; }
#nav-jobs-panel .nj-clear-btn {
  border: 1px solid var(--line, #ECECEA); background: var(--card, #fff);
  color: var(--ink-3, #6B6055); font-size: 11px; font-weight: 500;
  padding: 3px 9px; border-radius: 999px; cursor: pointer; line-height: 1.4;
}
#nav-jobs-panel .nj-clear-btn:hover { background: var(--bg-sunken, #F7F7F6); color: var(--ink, #14110E); }
#nav-jobs-panel .nj-clear-btn:disabled { opacity: 0.5; cursor: default; }
.nj-dismiss-btn {
  border: none; background: none; cursor: pointer; font-size: 16px; line-height: 1;
  color: var(--brown-400, #A89684); padding: 0 2px 0 6px; flex: none; align-self: flex-start;
}
.nj-dismiss-btn:hover { color: var(--ink, #14110E); }
.nj-dismiss-btn:disabled { opacity: 0.4; cursor: default; }
#nav-jobs-panel .nj-list { flex: 1; overflow-y: auto; padding: 10px 14px 16px; }
#nav-jobs-panel .nj-empty {
  text-align: center; color: var(--brown-400, #A89684); font-size: 13px; padding: 40px 0;
}
.nj-card {
  border: 1px solid var(--line, #ECECEA); border-radius: var(--radius, 12px);
  padding: 12px 13px; margin-bottom: 10px; background: var(--card, #fff);
}
.nj-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.nj-card-label { font-size: 13px; font-weight: 500; color: var(--ink, #14110E); word-break: break-word; }
.nj-pill {
  font-size: 10.5px; font-weight: 500; padding: 2px 8px; border-radius: 999px;
  display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; flex: none;
}
.nj-pill .nj-dot { width: 6px; height: 6px; border-radius: 999px; background: currentColor; flex: none; }
.nj-pill.jq-n { background: #F2F2F0; color: var(--ink-2, #3A332C); }
.nj-pill.jq-b { background: var(--orange-100, #FFE4D6); color: var(--orange-700, #A83100); }
.nj-pill.jq-g { background: var(--green-bg, #E2F1E9); color: #195C3F; }
.nj-pill.jq-r { background: var(--red-bg, #F7DCD5); color: #861E10; }
.nj-pill.jq-c { background: #F2F2F0; color: var(--ink-3, #6B6055); }
.nj-card-progress { font-size: 11.5px; color: var(--ink-3, #6B6055); margin-bottom: 3px; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.nj-card-time { font-size: 11px; color: var(--brown-400, #A89684); margin-bottom: 4px; }
.nj-card-counts { font-size: 11.5px; color: var(--ink-2, #3A332C); line-height: 1.4; }
.nj-card.jf-failed .nj-card-counts { color: var(--red, #C2371F); }
.nj-cancel-btn {
  border: 1px solid var(--line, #ECECEA); background: var(--card, #fff);
  color: var(--ink-3, #6B6055); font-size: 10.5px; font-weight: 500;
  padding: 2px 8px; border-radius: 999px; cursor: pointer; flex: none;
  line-height: 1.4;
}
.nj-cancel-btn:hover { background: var(--bg-sunken, #F7F7F6); color: var(--ink, #14110E); }
.nj-cancel-btn:disabled { opacity: 0.5; cursor: default; }
.nj-card-actions { margin-top: 8px; }
.nj-resume-btn {
  border: 1px solid var(--orange, #FF4D00); background: var(--orange, #FF4D00);
  color: #fff; font-size: 11px; font-weight: 600;
  padding: 4px 12px; border-radius: 999px; cursor: pointer; flex: none; line-height: 1.4;
}
.nj-resume-btn:hover { background: var(--orange-700, #C63B00); border-color: var(--orange-700, #C63B00); }
.nj-resume-btn:disabled { opacity: 0.6; cursor: default; }
    `;
    document.head.appendChild(style);
  }

  function buildDom() {
    elRoot = document.createElement("div");

    elTab = document.createElement("button");
    elTab.id = "nav-jobs-tab";
    elTab.type = "button";
    elTab.innerHTML = `<span class="nj-badge" id="nav-jobs-badge">0</span><span class="nj-label">Tasks</span>`;
    elTab.addEventListener("click", () => setOpen(!isOpen(), isOpen()));

    elPanel = document.createElement("div");
    elPanel.id = "nav-jobs-panel";
    elPanel.innerHTML = `
      <div class="nj-head">
        <div class="nj-title">Tasks in progress</div>
        <div class="nj-head-actions">
          <button type="button" class="nj-clear-btn" title="Remove all finished tasks">Clear finished</button>
          <button type="button" class="nj-close" aria-label="Close">&times;</button>
        </div>
      </div>
      <div class="nj-list" id="nav-jobs-list"></div>
    `;
    elPanel.querySelector(".nj-close").addEventListener("click", () => setOpen(false, true));
    elPanel.querySelector(".nj-clear-btn").addEventListener("click", (e) => {
      const b = e.currentTarget; b.disabled = true; b.textContent = "Clearing…";
      // Optimistic: drop finished from the list now.
      jobs = jobs.filter((j) => j.status === "queued" || j.status === "running");
      render();
      fetch("/api/jobs/dismiss-finished", { method: "POST" })
        .then(() => fetchJobs())
        .catch(() => { /* next poll reconciles */ })
        .finally(() => { b.disabled = false; b.textContent = "Clear finished"; });
    });

    elBadge = elTab.querySelector("#nav-jobs-badge");
    elList = elPanel.querySelector("#nav-jobs-list");
    elList.addEventListener("click", onListClick);

    elRoot.appendChild(elTab);
    elRoot.appendChild(elPanel);
    document.body.appendChild(elRoot);
  }

  // Set of job ids with an in-flight cancel POST — guards double-clicks
  // (the next poll removes the id once the job leaves queued/running).
  const cancelling = new Set();
  const resuming = new Set();  // same guard for in-flight Resume POSTs
  const dismissing = new Set();  // same guard for in-flight Dismiss POSTs

  function onListClick(e) {
    const dismiss = e.target.closest(".nj-dismiss-btn");
    if (dismiss) {
      const jid = dismiss.getAttribute("data-jid");
      if (!jid || dismissing.has(jid)) return;
      dismissing.add(jid);
      dismiss.disabled = true;
      // Optimistic: drop it from the local list immediately so it feels instant.
      jobs = jobs.filter((j) => j.id !== jid);
      render();
      fetch(`/api/jobs/${encodeURIComponent(jid)}/dismiss`, { method: "POST" })
        .then(() => fetchJobs())
        .catch(() => { /* next poll reconciles */ })
        .finally(() => dismissing.delete(jid));
      return;
    }
    const resume = e.target.closest(".nj-resume-btn");
    if (resume) {
      const jid = resume.getAttribute("data-jid");
      if (!jid || resuming.has(jid)) return;
      resuming.add(jid);
      resume.disabled = true;
      resume.textContent = "Resuming…";
      fetch(`/api/jobs/${encodeURIComponent(jid)}/resume`, { method: "POST" })
        .then((r) => r.json().catch(() => ({})))
        .then((j) => {
          if (j && j.job_id) { ping(); }          // new continuation job — refresh fast
          else if (resume.isConnected) { resume.disabled = false; resume.textContent = "Resume"; }
        })
        .catch(() => { if (resume.isConnected) { resume.disabled = false; resume.textContent = "Resume"; } })
        .finally(() => resuming.delete(jid));
      return;
    }
    const btn = e.target.closest(".nj-cancel-btn");
    if (!btn) return;
    const jid = btn.getAttribute("data-jid");
    if (!jid || cancelling.has(jid)) return;
    cancelling.add(jid);
    btn.disabled = true;
    btn.textContent = "Cancelling…";
    fetch(`/api/jobs/${encodeURIComponent(jid)}/cancel`, { method: "POST" })
      .then(() => fetchJobs())
      .catch(() => { /* next poll will reconcile state either way */ })
      .finally(() => cancelling.delete(jid));
  }

  function setOpen(open, userInitiated) {
    if (open) {
      elPanel.classList.add("nj-open");
      elTab.classList.add("nj-shifted"); // tab rides the panel edge so it stays a toggle
    } else {
      elPanel.classList.remove("nj-open");
      elTab.classList.remove("nj-shifted");
      if (userInitiated) userClosedThisView = true;
    }
    saveOpen(open);
  }

  function isOpen() {
    return !!(elPanel && elPanel.classList.contains("nj-open"));
  }

  function flashTab() {
    if (!elTab) return;
    elTab.classList.remove("nj-flash");
    // force reflow so re-adding the class restarts the animation
    void elTab.offsetWidth;
    elTab.classList.add("nj-flash");
    setTimeout(() => elTab && elTab.classList.remove("nj-flash"), 1300);
  }

  function renderCard(job, queuePos, campaignBusy) {
    const status = job.status || "queued";
    const label = jEsc(job.label || job.kind || "Job");
    const pill = `<span class="nj-pill ${statusClass(status)}"><span class="nj-dot"></span>${statusLabel(status)}</span>`;
    const cancellable = status === "queued" || status === "running";
    const cancelBtn = cancellable
      ? `<button type="button" class="nj-cancel-btn" data-jid="${jEsc(job.id)}">Cancel</button>` : "";
    // Resume: an interrupted verification can be continued on demand instead of
    // waiting for the next server restart's auto-resume. Hidden when that
    // campaign is already being verified again (no duplicate runs).
    const resumable = status === "interrupted" && (job.kind === "verify" || job.kind === "remove_bad") && !job.dry_run && !campaignBusy;
    const resumeBtn = resumable
      ? `<button type="button" class="nj-resume-btn" data-jid="${jEsc(job.id)}">Resume</button>` : "";
    let progress = "";
    if (status === "running" && job.progress && typeof job.progress === "object") {
      const done = job.progress.done, total = job.progress.total;
      if (done != null && total != null) {
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        progress = `<div class="nj-card-progress"><span>${jEsc(done)} of ${jEsc(total)} · ${pct}%</span>${cancelBtn}</div>`;
      }
    }
    if (status === "queued") {
      const waitTxt = queuePos == null ? "Waiting…"
        : queuePos <= 0 ? "Next up — starts when the current task finishes"
        : queuePos === 1 ? "Waiting · 1 task ahead"
        : `Waiting · ${queuePos} tasks ahead`;
      progress = `<div class="nj-card-progress"><span class="nj-queue-wait">${waitTxt}</span>${cancelBtn}</div>`;
    }
    if (!progress && cancellable) {
      progress = `<div class="nj-card-progress"><span></span>${cancelBtn}</div>`;
    }
    const startedIso = job.started_at || job.finished_at;
    const timeStr = jRelTime(startedIso);
    const timeLine = timeStr ? `<div class="nj-card-time">${timeStr}</div>` : "";
    let countsHtml = "";
    if (status === "done" || status === "failed" || status === "cancelled" || status === "interrupted") {
      const line = countsLine(job);
      if (line) countsHtml = `<div class="nj-card-counts">${line}</div>`;
    }
    const cardCls = (status === "failed" || status === "interrupted") ? "nj-card jf-failed" : "nj-card";
    // Dismiss: remove a FINISHED task from the panel. Not shown while live.
    const finished = status === "done" || status === "failed" || status === "cancelled" || status === "interrupted";
    const dismissBtn = finished
      ? `<button type="button" class="nj-dismiss-btn" data-jid="${jEsc(job.id)}" title="Remove this task from the list" aria-label="Dismiss">&times;</button>` : "";
    const resumeRow = (resumeBtn) ? `<div class="nj-card-actions">${resumeBtn}</div>` : "";
    return `<div class="${cardCls}">
      <div class="nj-card-top"><span class="nj-card-label">${label}</span>${pill}${dismissBtn}</div>
      ${progress}${timeLine}${countsHtml}${resumeRow}
    </div>`;
  }

  function render() {
    if (!jobs.length) {
      elList.innerHTML = `<div class="nj-empty">No tasks in progress yet.</div>`;
    } else {
      // Queue position: a queued job waits behind every running job plus every
      // queued job enqueued before it (lower queue_seq). Lets each card show
      // "next up" / "2nd in line" so a stack of added tasks reads clearly.
      const running = jobs.filter((j) => j.status === "running").length;
      const queuedSeqs = jobs.filter((j) => j.status === "queued")
        .map((j) => j.queue_seq).filter((s) => s != null).sort((a, b) => a - b);
      const posFor = (job) => {
        if (job.status !== "queued") return null;
        const ahead = running + (job.queue_seq != null
          ? queuedSeqs.filter((s) => s < job.queue_seq).length
          : 0);
        return ahead;
      };
      // Campaigns with a live job — used to hide Resume on an interrupted card
      // whose campaign is already being verified again (avoids duplicate runs).
      const busyCampaigns = new Set(jobs
        .filter((j) => (j.status === "queued" || j.status === "running") && j.campaign_id != null)
        .map((j) => String(j.campaign_id)));
      elList.innerHTML = jobs.map((j) =>
        renderCard(j, posFor(j), j.campaign_id != null && busyCampaigns.has(String(j.campaign_id)))
      ).join("");
    }
    const activeCount = jobs.filter((j) => j.status === "queued" || j.status === "running").length;
    elBadge.textContent = String(activeCount);
    elBadge.classList.toggle("nj-on", activeCount > 0);
    elBadge.classList.toggle("nj-pulse", activeCount > 0);
  }

  function currentInterval() {
    const anyActive = jobs.some((j) => j.status === "queued" || j.status === "running");
    return anyActive ? POLL_FAST_MS : POLL_SLOW_MS;
  }

  function scheduleNext() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(() => fetchJobs(), currentInterval());
  }

  function fetchJobs() {
    fetch("/api/jobs", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error("bad status " + r.status);
        return r.json();
      })
      .then((data) => {
        backendOk = true;
        const list = (data && Array.isArray(data.jobs)) ? data.jobs : [];
        processJobs(list);
        elTab.classList.add("nj-show");
        scheduleNext();
      })
      .catch((err) => {
        if (!warnedOnce) {
          warnedOnce = true;
          console.warn("[nav-jobs] tasks in progress unavailable:", err && err.message ? err.message : err);
        }
        backendOk = false;
        if (elTab) elTab.classList.remove("nj-show");
        if (elPanel) elPanel.classList.remove("nj-open");
        scheduleNext();
      });
  }

  function processJobs(list) {
    const prevStatusById = {};
    jobs.forEach((j) => { prevStatusById[j.id] = j.status; });

    const newIds = [];
    let anyJustFinished = false;
    list.forEach((j) => {
      if (!knownIds.has(j.id)) newIds.push(j.id);
      const prevStatus = prevStatusById[j.id];
      if (prevStatus === "running" && (j.status === "done" || j.status === "failed" || j.status === "cancelled" || j.status === "interrupted")) anyJustFinished = true;
    });

    jobs = list;

    if (!havePolledOnce) {
      havePolledOnce = true;
      knownIds = new Set(list.map((j) => j.id));
      render();
      return;
    }

    knownIds = new Set(list.map((j) => j.id));
    render();

    if (newIds.length && document.visibilityState === "visible" && !userClosedThisView) {
      setOpen(true);
    } else if ((newIds.length || anyJustFinished) && !isOpen()) {
      flashTab();
    }
  }

  function ping() {
    fetchJobs();
  }

  function init() {
    injectStyle();
    buildDom();
    if (isOpenSaved()) setOpen(true);
    render();
    fetchJobs();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.NavreoJobs = { ping };
})();
