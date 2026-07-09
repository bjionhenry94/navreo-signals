/* Shared shell: rail nav, data loading, small helpers. */

/* Icons8 "Windows 10" set, rendered via CSS mask so they inherit color */
function ic8(name, cls = "") {
  return `<span class="ic8 ${cls}" style="--icon:url('icons/${name}.png')"></span>`;
}

const ICONS = {
  dashboard: ic8("home", "lg"),
  campaigns: ic8("send", "lg"),
  mailboxes: ic8("mail", "lg"),
  notifications: ic8("bell", "lg"),
};

const NAV = [
  ["index.html", "dashboard", "Dashboard"],
  ["campaigns.html", "campaigns", "Campaigns"],
  ["mailboxes.html", "mailboxes", "Mailboxes"],
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
