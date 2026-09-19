/* Meetings Scoreboard — live client of /api/scoreboard/data. The hero bar keeps
   the three meeting states we've been building toward:
     Attended (solid) · Booked/pending (dashed) · Meeting-ready (dashed, muted)
   against the target of 4 booked meetings per active client. Everything below
   the bar is per-client: positives, booked, pace, and the two ranked charts. */
(function () {
  "use strict";
  var el = function (id) { return document.getElementById(id); };
  el("rail").outerHTML = renderRail("scoreboard");

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  };
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var num = function (n) { return Number(n || 0).toLocaleString("en-GB"); };
  var clamp = function (n) { return Math.max(0, Math.min(100, n)); };

  function ago(iso) {
    if (!iso) return "";
    var t = Date.parse(String(iso).replace(" ", "T").replace(/Z?$/, "Z"));
    if (isNaN(t)) return "";
    var m = Math.max(0, (Date.now() - t) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return Math.round(m) + "m ago";
    if (m < 1440) return Math.round(m / 60) + "h ago";
    return Math.round(m / 1440) + "d ago";
  }

  function load() {
    fetch("/api/scoreboard/data", {credentials: "same-origin"})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || d.error) { fail(); return; }
        render(d);
      })
      .catch(fail);
  }
  function fail() {
    el("sb-body").innerHTML = '<div class="skel">Couldn’t load the scoreboard. Refresh in a moment.</div>';
  }

  /* ---------- the 3-state hero bar ---------- */
  function heroBar(t) {
    var target = t.target || 0;
    var attPct = target ? clamp(100 * t.counted / target) : 0;
    var bookedPct = target ? Math.max(0, Math.min(100 - attPct, 100 * t.booked / target)) : 0;
    var readyPct = target ? Math.max(0, Math.min(100 - attPct - bookedPct, 100 * t.said_yes_open / target)) : 0;
    var tickPct = target ? clamp(100 * t.should_be_today / target) : 0;
    return '' +
      '<div class="bar">' +
        '<div class="fill" style="width:' + attPct + '%"></div>' +
        (bookedPct > 0 ? '<div class="seg seg-booked" style="left:' + attPct + '%;width:' + bookedPct + '%"></div>' : '') +
        (readyPct > 0 ? '<div class="seg seg-ready" style="left:' + (attPct + bookedPct) + '%;width:' + readyPct + '%"></div>' : '') +
        '<div class="tick" style="left:' + tickPct + '%"></div>' +
      '</div>' +
      '<div class="leg">' +
        '<span><i class="s-att"></i> Attended <b>' + t.counted + '</b></span>' +
        '<span><i class="s-book"></i> Booked · pending <b>' + t.booked + '</b></span>' +
        '<span><i class="s-ready"></i> Meeting-ready <b>' + t.said_yes_open + '</b></span>' +
        '<span><i class="tk"></i> Where we should be today <b>' + t.should_be_today + '</b></span>' +
      '</div>';
  }

  /* ---------- per-client mini bar (booked / 4, with pace + target) ---------- */
  function miniBar(meetings, target, pace) {
    var mf = clamp(100 * meetings / target);
    var mp = clamp(100 * pace / target);
    return '<div class="mini">' +
      '<div class="mf" style="width:' + mf + '%"></div>' +
      '<div class="mp" style="left:' + mp + '%"></div>' +
      '<div class="mt" style="left:100%"></div></div>';
  }

  /* ---------- a ranked horizontal bar chart ---------- */
  function chart(rows, opts) {
    opts = opts || {};
    var maxVal = rows.reduce(function (m, r) { return Math.max(m, r.value); }, 0);
    var axisMax;
    if (opts.target) {
      // keep the 4-target line readable; clip a runaway leader at the edge
      axisMax = Math.max(opts.target + 1, Math.min(opts.target * 2, maxVal));
    } else {
      axisMax = maxVal || 1;
    }
    var tgtPct = opts.target ? clamp(100 * opts.target / axisMax) : 0;
    var body = rows.map(function (r, i) {
      var w = clamp(100 * r.value / axisMax);
      var clipped = r.value > axisMax;
      // the dashed line repeats per row (stacking into one continuous line);
      // the "target N" label rides only the first row so it isn't duplicated.
      var tgtLine = opts.target
        ? '<div class="chtgt" style="left:' + tgtPct + '%">' +
            (i === 0 ? '<span class="lbl">target ' + opts.target + '</span>' : '') + '</div>'
        : '';
      return '<div class="chrow">' +
        '<div class="cl">' + esc(r.name) + '</div>' +
        '<div class="chtrack">' +
          '<div class="chbar ' + (opts.cls || '') + (clipped ? ' clip' : '') + '" style="width:' + w + '%"></div>' +
          tgtLine +
        '</div>' +
        '<div class="chval">' + num(r.value) + '</div>' +
      '</div>';
    }).join("");
    return body || '<div class="skel" style="padding:14px 0">Nothing yet this month.</div>';
  }

  /* ---------- render ---------- */
  function render(d) {
    var t = d.totals, cal = d.cal_days || {}, cards = d.cards || {};
    var today = new Date((d.today || "") + "T00:00:00");
    var dayN = isNaN(today.getDate()) ? "" : today.getDate();
    var monShort = isNaN(today.getMonth()) ? "" : MON[today.getMonth()];

    var behind = t.behind || 0;
    var vClass = behind > 0 ? "behind" : "ok";
    var vTxt = behind > 0 ? "Behind by " + behind : (behind < 0 ? "Ahead by " + (-behind) : "On track");

    // stat cards
    var rr = cards.runrate_diff || 0;
    var rrVal = (rr > 0 ? "+" : (rr < 0 ? "−" : "")) + Math.abs(rr);     // proper minus sign
    var rrLbl = rr < 0 ? "behind the pace to hit " + t.target
              : (rr > 0 ? "ahead of the pace for " + t.target : "on the pace for " + t.target);
    var resp = cards.avg_response_mins;
    var pctS = function (v) { return v == null ? "—" : v + "%"; };
    var cardHtml =
      scard(cards.avg_meetings_per_client + ' <small>of ' + d.per_client_target + '</small>',
            "average meetings per client",
            cards.avg_meetings_per_client < d.pace_mark ? "warn" : "") +
      scard(num(cards.attended), "meetings attended this month", "") +
      scard(pctS(cards.pos_to_booked_pct), "positive reply → booked call", "") +
      scard(pctS(cards.show_up_pct), "show-up rate", "") +
      scard(rrVal, rrLbl, rr < 0 ? "bad" : "") +
      scard(resp == null ? "—" : num(resp), "average response time (mins)", "");

    // client scoreboard table
    var rowsHtml = (d.clients || []).map(function (c) {
      if (!c.scored) {
        return '<div class="trow unscored">' +
          '<div class="cn">' + esc(c.name) + '</div>' +
          '<div class="num mut pos-col">—</div>' +
          '<div class="num mut">—</div>' +
          '<div class="num mut">—</div>' +
          '<div class="num mut">—</div>' +
          '<div class="num mut rate">—</div>' +
          '<div class="num mut rate">—</div>' +
          '<div><span class="badge muted">' + esc(c.status) + '</span></div>' +
        '</div>';
      }
      // per-client conversion rates
      var p2b = c.positives > 0 ? Math.round(100 * c.meetings / c.positives) + "%" : "—";
      var suDen = (c.attended || 0) + (c.no_show || 0);
      var su = suDen > 0 ? Math.round(100 * c.attended / suDen) + "%" : "—";
      return '<div class="trow">' +
        '<div class="cn">' + esc(c.name) + '</div>' +
        '<div class="num pos-col">' + num(c.positives) + '</div>' +
        '<div class="num">' + num(c.said_yes) + '</div>' +       // Meeting-ready (said yes)
        '<div class="num">' + num(c.booked) + '</div>' +          // Booked (upcoming)
        '<div class="num">' + num(c.attended) + '</div>' +        // Attended
        '<div class="num rate">' + p2b + '</div>' +               // positive → booked call
        '<div class="num rate">' + su + '</div>' +                // show-up rate
        '<div><span class="badge ' + esc(c.tone) + '">' + esc(c.status) + '</span></div>' +
      '</div>';
    }).join("");

    var anyClip = (d.booked_chart || []).some(function (r) {
      return r.value > Math.max(d.per_client_target + 1, Math.min(d.per_client_target * 2,
        (d.booked_chart || []).reduce(function (m, x) { return Math.max(m, x.value); }, 0)));
    });

    el("sb-body").innerHTML =
      // header
      '<div class="sb-head">' +
        '<h1>Scoreboard</h1>' +
        '<span class="mo">' + esc(d.month) + ' · 1–' + dayN + ' ' + monShort +
          ' · updated ' + esc(ago(d.generated_at)) + '</span>' +
        '<span class="sp"></span>' +
        '<a class="tt-link" href="team-target.html">Team Target ↗</a>' +
      '</div>' +
      '<p class="sb-sub">Positive replies and booked meetings per client, scored against the target of ' +
        '4 booked meetings per active client each month.</p>' +
      '<div class="sb-scope">Every number on this page is for ' + esc(d.month) + ' only (1–' + dayN + ' ' +
        monShort + ') and resets at the start of each month.</div>' +

      // KPI callout
      '<div class="kpi"><div class="k1">Internal target</div>' +
        '<div class="k2">' + d.per_client_target + ' booked meetings per client per month</div>' +
        '<div class="k3">' + (cal.gone || 0) + ' of ' + (cal.total || 0) + ' days elapsed · pace mark is ' +
          (d.pace_mark != null ? d.pace_mark : "—") + ' meetings</div></div>' +

      // hero
      '<div class="eyebrow">Meetings this month</div>' +
      '<div class="hero">' +
        '<div class="big">' + t.counted + ' <small>of ' + t.target + '</small></div>' +
        '<div class="rt">' +
          '<span class="verdict ' + vClass + '">' + vTxt + '</span>' +
          '<p class="pace">At this pace we finish on ' + t.pace + '. Target ' + t.target + '.</p>' +
          '<p class="subline">' + t.booked + ' booked and still to happen · ' + t.said_yes_open +
            ' more said yes and are waiting to be booked.</p>' +
        '</div>' +
      '</div>' +
      heroBar(t) +

      // cards
      '<div class="cards">' + cardHtml + '</div>' +

      // client scoreboard
      '<div class="sec"><h2>Client scoreboard</h2>' +
        '<p class="desc">Ready = said yes, waiting to book · Booked = scheduled and upcoming · Attended = happened. Pos→Booked = positive replies that became a booked call · Show-up = attended of the calls that were due.</p>' +
        '<div class="tbl-scroll"><div class="tbl">' +
          '<div class="trow head"><div>Client</div><div class="h-pos pos-col">Positives</div>' +
            '<div>Ready</div><div>Booked</div><div>Attended</div>' +
            '<div>Pos→Booked</div><div>Show-up</div><div>Status</div></div>' +
          rowsHtml +
        '</div></div>' +
      '</div>' +

      // charts
      '<div class="sec"><h2>Meetings booked vs target</h2>' +
        '<p class="desc">Dashed line is the ' + d.per_client_target + '-meeting target.' +
          (anyClip ? ' A runaway leader is clipped at the axis edge — the number is exact.' : '') + '</p>' +
        '<div class="chart">' + chart(d.booked_chart || [], {target: d.per_client_target}) + '</div>' +
      '</div>' +

      '<div class="sec"><h2>Positive replies, clean</h2>' +
        '<p class="desc">Unique leads with a positive reply this month (Interested, Meeting Request, Call Booked, Information Request).</p>' +
        '<div class="chart">' + chart(d.positives_chart || [], {cls: "pos"}) + '</div>' +
      '</div>';
  }

  function scard(vHtml, k, tone) {
    return '<div class="scard ' + (tone || '') + '"><div class="v">' + vHtml + '</div>' +
      '<div class="k">' + esc(k) + '</div></div>';
  }

  load();
})();
