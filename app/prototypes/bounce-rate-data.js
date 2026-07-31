/* Bounce-rate prototypes — shared sample data.
   Shape is verbatim what the live page already has in memory:
     TRENDS.series  ← /api/deliverability-trends?days=60   (days[], sent[], bounce_pct[])
     SCORE.campaigns ← /api/campaign-scorecard             ({id: {name, sent, bounced, status, workspace}})
   Nothing new is fetched — every prototype slices these client-side (7/14/30),
   matching the hub's client-filter ruling and its 30-day display cap.
   60 days are held so the 30d view still has a previous 30d to compare against;
   only 30 are ever drawn. */

var BR = (function () {
  var DAYS_HELD = 60;

  // Deterministic jitter — stable screenshots, no Math.random.
  var JIT = [0.04, -0.07, 0.11, -0.03, 0.08, -0.10, 0.02, 0.06, -0.05, 0.09,
             -0.02, 0.05, -0.08, 0.03, 0.10, -0.06, 0.01, 0.07, -0.09, 0.04];

  var days = [], sent = [], bounce = [];
  var base = new Date(); base.setHours(0, 0, 0, 0);

  for (var i = 0; i < DAYS_HELD; i++) {
    var d = new Date(base.getTime() - (DAYS_HELD - 1 - i) * 86400000);
    var dow = d.getDay(), weekend = (dow === 0 || dow === 6);
    days.push(d.toISOString().slice(0, 10));

    if (weekend) {                       // we barely send at weekends
      sent.push(dow === 6 ? 40 : 0);
      bounce.push(null);                 // no honest rate off ~40 sends
      continue;
    }
    sent.push(7000 + ((i * 137) % 620));
    // First 30 days steady ~1.1%. Last 30 drift upward, steepening in the
    // final fortnight — the story the widget has to make visible.
    var v = i < 30 ? 1.10 : 1.10 + Math.pow((i - 30) / 29, 1.7) * 1.65;
    bounce.push(Math.round((v + JIT[i % JIT.length]) * 100) / 100);
  }

  var campaigns = {
    "8801": { name: "ValSoft — Ops Directors Q3",         sent: 18420, bounced: 742, status: "ACTIVE" },
    "8802": { name: "Arnic — Plant Managers (recontact)", sent: 12310, bounced: 431, status: "ACTIVE" },
    "8803": { name: "Amplifyy — Founders, hiring signal", sent: 9840,  bounced: 118, status: "ACTIVE" },
    "8804": { name: "Byteplus — CTOs, tech-stack",        sent: 15600, bounced: 156, status: "ACTIVE" },
    "8805": { name: "INSEAD — Alumni programme leads",    sent: 6210,  bounced: 44,  status: "ACTIVE" },
    "8806": { name: "ValSoft — CFO expansion",            sent: 11050, bounced: 508, status: "ACTIVE" },
    "8807": { name: "Arnic — Maintenance heads",          sent: 8730,  bounced: 61,  status: "ACTIVE" },
    "8808": { name: "Byteplus — Eng leaders, EU",         sent: 5480,  bounced: 27,  status: "ACTIVE" },
    "8809": { name: "Amplifyy — Growth leads, funding",   sent: 4120,  bounced: 173, status: "ACTIVE" },
    "8810": { name: "INSEAD — Exec-ed decision makers",   sent: 3960,  bounced: 19,  status: "ACTIVE" },
    "8811": { name: "ValSoft — IT Directors, mid-market", sent: 2140,  bounced: 12,  status: "ACTIVE" },
    "8812": { name: "Arnic — Procurement (test)",         sent: 380,   bounced: 31,  status: "ACTIVE" }
  };

  /* ── derivations every prototype shares ───────────────────────────── */

  var MIN_SENT = 500;   // same floor the hub's campaign ranking already uses
  var LIMIT    = 2.0;   // the number the fleet is judged against

  function slice(n) {   // last n days, client-side
    return { days: days.slice(-n), sent: sent.slice(-n), bounce: bounce.slice(-n) };
  }

  // Sent-weighted bounce % across a window — the honest fleet number.
  // Weekend nulls (near-zero sends) are skipped, not counted as zero.
  function weighted(w) {
    var b = 0, s = 0;
    for (var i = 0; i < w.days.length; i++) {
      if (w.bounce[i] == null || !w.sent[i]) continue;
      s += w.sent[i]; b += w.sent[i] * w.bounce[i] / 100;
    }
    return s ? b / s * 100 : null;
  }

  // This window vs the window immediately before it.
  function delta(n) {
    var cur = weighted(slice(n));
    var prevRaw = { days: days.slice(-2 * n, -n), sent: sent.slice(-2 * n, -n), bounce: bounce.slice(-2 * n, -n) };
    var prev = prevRaw.days.length ? weighted(prevRaw) : null;
    return { cur: cur, prev: prev, diff: (cur != null && prev != null) ? cur - prev : null };
  }

  // A long window's average can sit under the limit while every recent day is
  // over it — a green headline would be a false all-clear. This counts the
  // trailing run of sending days at or above the limit so every prototype can
  // say so out loud.
  function breach() {
    var run = 0, latest = null;
    for (var i = days.length - 1; i >= 0; i--) {
      if (bounce[i] == null) continue;            // skip weekends
      if (latest == null) latest = bounce[i];
      if (bounce[i] >= LIMIT) run++; else break;
    }
    return { run: run, latest: latest };
  }

  // Worst band between the window average and an active breach run, so the
  // headline colour can never be greener than the last few days deserve.
  function headlineBand(cur) {
    var b = band(cur), br = breach();
    if (br.run >= 3) { var lb = band(br.latest); if (RANK[lb] > RANK[b]) return lb; }
    return b;
  }

  // Offending campaigns. NOTE: campaign bounced/sent is LIFETIME cumulative —
  // the scorecard has no per-day campaign series — so this list is labelled
  // "all time" everywhere it appears. Saying "last 7 days" would be a lie.
  // Small lists are INCLUDED and flagged, not hidden. The 500-send floor was
  // silently swallowing a 380-send campaign at 8.2% — the worst rate in the
  // fleet — which is exactly the number someone needs to see.
  function offenders() {
    var out = [];
    Object.keys(campaigns).forEach(function (id) {
      var c = campaigns[id];
      if (!c.sent) return;
      out.push({ id: id, name: c.name, sent: c.sent, bounced: c.bounced,
                 pct: c.bounced / c.sent * 100, small: c.sent < MIN_SENT });
    });
    return out.sort(function (a, b) { return b.pct - a.pct; });
  }

  // Ranked by bounces CAUSED, not by rate — ranking by rate puts a 173-bounce
  // campaign above a 742-bounce one and points the reader at the smallest fire.
  function byVolume() {
    return offenders().sort(function (a, b) { return b.bounced - a.bounced; });
  }

  // Grouped by client (the name prefix before the em dash). One client can own
  // several of the worst campaigns — that is one phone call, not four.
  function byClient() {
    var g = {};
    offenders().forEach(function (o) {
      var c = o.name.split("—")[0].trim();
      g[c] = g[c] || { client: c, sent: 0, bounced: 0, camps: [] };
      g[c].sent += o.sent; g[c].bounced += o.bounced; g[c].camps.push(o);
    });
    return Object.keys(g).map(function (k) {
      var r = g[k];
      r.pct  = r.sent ? r.bounced / r.sent * 100 : 0;   // blended — see r.worst
      var bad = r.camps.filter(function (c) { return c.pct >= LIMIT; })
                       .sort(function (a, b) { return b.pct - a.pct; });
      r.over = bad.length;
      // Blending a client's clean lists into its bad one repaints a 4.2% fire
      // as 2.1% amber. The row must show — and name — the worst list.
      r.worst = bad[0] || null;
      r.badNames = bad.map(function (c) { return c.name.split("—").slice(1).join("—").trim(); });
      return r;
    }).sort(function (a, b) { return b.bounced - a.bounced; });
  }

  function totalBounced() {
    return offenders().reduce(function (a, o) { return a + o.bounced; }, 0);
  }

  // Today's number — the one every reviewer said was missing. The window
  // average answers "how was the month"; this answers "am I in trouble now".
  function today() {
    for (var i = days.length - 1; i >= 0; i--) if (bounce[i] != null) return bounce[i];
    return null;
  }

  // Sparkline markup. The run of days at/over the limit is drawn in the alert
  // colour and everything else stays neutral — colouring the whole line by
  // today's mood retro-paints three healthy weeks as a problem.
  function sparkSVG(w, h) {
    var pts = [];
    for (var i = 0; i < w.days.length; i++) if (w.bounce[i] != null) pts.push(i);
    if (!pts.length) return { svg: "", lo: 0, hi: 0 };
    var vals = pts.map(function (i) { return w.bounce[i]; });
    var lo = Math.min(Math.min.apply(null, vals), LIMIT);
    var hi = Math.max(Math.max.apply(null, vals), LIMIT);
    var pad = Math.max((hi - lo) * 0.20, 0.10);
    lo = Math.max(0, lo - pad); hi = hi + pad;
    var n = w.days.length - 1 || 1;
    var X = function (i) { return i / n * 100; };
    var Y = function (v) { return 100 - (v - lo) / (hi - lo) * 100; };
    var d = function (arr) {
      return arr.map(function (i, k) { return (k ? "L" : "M") + X(i).toFixed(2) + " " + Y(w.bounce[i]).toFixed(2); }).join(" ");
    };
    // trailing run at/over the limit
    var cut = pts.length;
    while (cut > 0 && w.bounce[pts[cut - 1]] >= LIMIT) cut--;
    var over = pts.slice(Math.max(0, cut - 1));   // one back, so the segments join
    var alert = band(w.bounce[pts[pts.length - 1]]);

    var svg =
      '<line x1="0" y1="' + Y(LIMIT).toFixed(2) + '" x2="100" y2="' + Y(LIMIT).toFixed(2) + '" ' +
        'stroke="var(--brown-300)" stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>' +
      '<path d="' + d(pts) + '" fill="none" stroke="var(--brown-400)" stroke-width="1.75" ' +
        'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>' +
      (cut < pts.length
        ? '<path d="' + d(over) + '" fill="none" stroke="' + col(alert) + '" stroke-width="2.25" ' +
          'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        : "");
    return { svg: svg, lo: lo, hi: hi, X: X, Y: Y, lastI: pts[pts.length - 1] };
  }

  var RANK = { g: 0, a: 1, r: 2 };
  // The limit is the limit: at or over 2% is RED. Amber is the approach lane
  // (1.5–2%), green is clear. This deliberately diverges from the hub's older
  // <2 green / <3 amber / 3+ red banding — a card that prints "2% limit" and
  // then paints six days over it amber is telling two different stories.
  function band(p) { return p == null ? "g" : (p >= LIMIT ? "r" : (p >= LIMIT * 0.75 ? "a" : "g")); }
  function col(b)  { return b === "r" ? "var(--red)" : (b === "a" ? "var(--amber)" : "var(--green)"); }
  function pct(p)  { return p == null ? "–" : p.toFixed(2) + "%"; }
  function n(v)    { return v.toLocaleString("en-US"); }
  function shortName(s) { return s.length > 34 ? s.slice(0, 33) + "…" : s; }
  function dayLabel(iso) {
    var d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }

  return { days: days, sent: sent, bounce: bounce, campaigns: campaigns,
           LIMIT: LIMIT, MIN_SENT: MIN_SENT,
           slice: slice, weighted: weighted, delta: delta, breach: breach,
           headlineBand: headlineBand, offenders: offenders,
           today: today, sparkSVG: sparkSVG, byVolume: byVolume,
           byClient: byClient, totalBounced: totalBounced,
           band: band, col: col, pct: pct, n: n,
           shortName: shortName, dayLabel: dayLabel };
})();
