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

/* read-only note for inert actions */
function protoNote(msg = "Read-only prototype") {
  let el = document.querySelector(".proto-note");
  if (!el) {
    el = document.createElement("div");
    el.className = "proto-note";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  requestAnimationFrame(() => el.classList.add("on"));
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("on"), 2600);
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
  el.innerHTML = svg;
}
