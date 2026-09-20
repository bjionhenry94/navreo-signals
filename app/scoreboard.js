/* Team Target — the team's meetings hub. Two tabs under one header:
     Scoreboard — live per-client numbers (/api/scoreboard/data)
     Board — add / move / remove the three meeting states (/api/team-target/*)
   One "Add a meeting"; any write refreshes both views. */
(function () {
  "use strict";
  var el = function (id) { return document.getElementById(id); };
  el("rail").outerHTML = renderRail("target");

  var TAB = "scoreboard", SB = null, TT = null, DRAG = null, BOARD_CLIENT = "", EDITING = null;

  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); };
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var num = function (n) { return Number(n || 0).toLocaleString("en-GB"); };
  var clamp = function (n) { return Math.max(0, Math.min(100, n)); };
  function fmtReply(mins) {
    if (mins == null) return "—";
    return mins < 90 ? Math.round(mins) + " min" : (mins / 60).toFixed(1) + " h";
  }
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
  function waitTxt(d) { return d <= 0 ? "said yes today" : "waiting " + d + (d === 1 ? " day" : " days"); }
  function fmtDate(s) {
    if (!s) return "";
    var m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return String(s);
    return MON[(+m[2]) - 1] + " " + (+m[3]);
  }
  var STATUS_WORDS = {said_yes: "Meeting-ready", booked: "Booked", attended: "Attended",
                      no_show: "No-show", cancelled: "Cancelled", not_fit: "Not a fit"};
  var ORDER = ["said_yes", "booked", "attended", "no_show", "cancelled", "not_fit"];

  /* ---------- data ---------- */
  function loadAll(cb) {
    var pending = 2;
    function step() { if (--pending === 0) { render(); if (cb) cb(); } }
    fetch("/api/scoreboard/data", {credentials: "same-origin"})
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d && !d.error) SB = d; step(); }, function () { step(); });
    fetch("/api/team-target/data", {credentials: "same-origin"})
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d && !d.error) TT = d; step(); }, function () { step(); });
  }
  function post(url, body, done) {
    fetch(url, {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})
      .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, j: j}; }); })
      .then(function (res) { if (!res.ok) { alert((res.j && res.j.error) || "Couldn't save"); return; } loadAll(done); })
      .catch(function () { alert("Couldn't save — check your connection."); });
  }

  /* ---------- shell (header tabs + body) ---------- */
  function render() {
    el("sb-mo").textContent = (SB && SB.month) || (TT && TT.month) || "";
    var bn = TT ? TT.meetings.length : "";
    el("sb-tabs").innerHTML =
      '<button class="tt-tab ' + (TAB === "scoreboard" ? "on" : "") + '" data-tab="scoreboard">Scoreboard</button>' +
      '<button class="tt-tab ' + (TAB === "board" ? "on" : "") + '" data-tab="board">Leads' +
        (bn !== "" ? ' <span class="b">' + bn + "</span>" : "") + "</button>";
    Array.prototype.forEach.call(el("sb-tabs").children, function (b) {
      b.onclick = function () { TAB = b.getAttribute("data-tab"); render(); };
    });
    var body = el("sb-body");
    if (TAB === "board") {
      if (!TT) { body.innerHTML = '<div class="skel">Loading the board…</div>'; return; }
      body.innerHTML = ""; body.appendChild(renderBoard());
    } else {
      if (!SB) { body.innerHTML = '<div class="skel">Loading the scoreboard…</div>'; return; }
      body.innerHTML = ""; body.appendChild(renderScoreboard(SB));
    }
  }

  /* ---------- Scoreboard (dashboard) ---------- */
  function heroBar(t) {
    var target = t.target || 0;
    var attPct = target ? clamp(100 * t.counted / target) : 0;
    var bookedPct = target ? Math.max(0, Math.min(100 - attPct, 100 * t.booked / target)) : 0;
    var readyPct = target ? Math.max(0, Math.min(100 - attPct - bookedPct, 100 * t.said_yes_open / target)) : 0;
    var tickPct = target ? clamp(100 * t.should_be_today / target) : 0;
    return '<div class="bar"><div class="fill" style="width:' + attPct + '%"></div>' +
        (bookedPct > 0 ? '<div class="seg seg-booked" style="left:' + attPct + '%;width:' + bookedPct + '%"></div>' : "") +
        (readyPct > 0 ? '<div class="seg seg-ready" style="left:' + (attPct + bookedPct) + '%;width:' + readyPct + '%"></div>' : "") +
        '<div class="tick" style="left:' + tickPct + '%"></div></div>' +
      '<div class="leg">' +
        '<span><i class="s-att"></i> Attended <b>' + t.counted + "</b></span>" +
        '<span><i class="s-book"></i> Booked · pending <b>' + t.booked + "</b></span>" +
        '<span><i class="s-ready"></i> Meeting-ready <b>' + t.said_yes_open + "</b></span>" +
        '<span><i class="tk"></i> Where we should be today <b>' + t.should_be_today + "</b></span></div>";
  }
  function miniBar(meetings, target, pace) {
    return '<div class="mini"><div class="mf" style="width:' + clamp(100 * meetings / target) + '%"></div>' +
      '<div class="mp" style="left:' + clamp(100 * pace / target) + '%"></div><div class="mt" style="left:100%"></div></div>';
  }
  /* per-client pipeline bar — attended (solid) then booked + meeting-ready
     (dashed segments), stacked toward the target: the hero bar, per client.
     Shows EVERY client, most attended first, so a client with no attended but
     live pipeline still reads as progress instead of an empty row. */
  function pipelineChart(clients, target) {
    var rows = (clients || []).slice().sort(function (a, z) {
      return (z.attended - a.attended) ||
        ((z.booked + z.said_yes) - (a.booked + a.said_yes)) ||
        (String(a.name).toLowerCase() < String(z.name).toLowerCase() ? -1 : 1);
    });
    var maxAtt = rows.reduce(function (m, r) { return Math.max(m, r.attended || 0); }, 0);
    var axisMax = Math.max(target + 1, Math.min(target * 2, maxAtt));
    var tgtPct = clamp(100 * target / axisMax);
    var body = rows.map(function (r, i) {
      var att = r.attended || 0, bk = r.booked || 0, rd = r.said_yes || 0;
      var attPct = clamp(100 * att / axisMax);
      var bkPct = Math.max(0, Math.min(100 - attPct, 100 * bk / axisMax));
      var rdPct = Math.max(0, Math.min(100 - attPct - bkPct, 100 * rd / axisMax));
      var segs =
        (attPct > 0 ? '<div class="chbar' + (att > axisMax ? " clip" : "") + '" style="width:' + attPct + '%"></div>' : "") +
        (bkPct > 0 ? '<div class="chseg book" style="left:' + attPct + '%;width:' + bkPct + '%"></div>' : "") +
        (rdPct > 0 ? '<div class="chseg ready" style="left:' + (attPct + bkPct) + '%;width:' + rdPct + '%"></div>' : "");
      var tgtLine = '<div class="chtgt" style="left:' + tgtPct + '%">' +
        (i === 0 ? '<span class="lbl">target ' + target + "</span>" : "") + "</div>";
      return '<div class="chrow"><div class="cl">' + esc(r.name) + '</div><div class="chtrack">' +
        segs + tgtLine + '</div><div class="chval">' + num(att) + "</div></div>";
    }).join("");
    return body || '<div class="skel" style="padding:14px 0">Nothing yet this month.</div>';
  }
  function scard(vHtml, k, tone) {
    return '<div class="scard ' + (tone || "") + '"><div class="v">' + vHtml + '</div><div class="k">' + esc(k) + "</div></div>";
  }
  /* red / amber / green thresholds (owner 2026-09-19) */
  var RAG = {
    meetings: function (v) { return v == null ? "" : (v >= 4 ? "good" : (v < 3 ? "bad" : "warn")); },
    p2b: function (v) { return v == null ? "" : (v >= 40 ? "good" : (v <= 15 ? "bad" : "warn")); },
    show: function (v) { return v == null ? "" : (v >= 70 ? "good" : (v <= 50 ? "bad" : "warn")); },
    resp: function (v) { return v == null ? "" : (v <= 30 ? "good" : "bad"); }
  };
  function dot(tone, big) { return tone ? '<span class="rag' + (big ? " big" : "") + " rag-" + tone + '"></span>' : ""; }
  function renderScoreboard(d) {
    var t = d.totals, cards = d.cards || {};
    var behind = t.behind || 0;
    var pot = (t.counted || 0) + (t.booked || 0) + (t.said_yes_open || 0);
    var vClass = behind > 0 ? "behind" : "ok";
    var vTxt = behind > 0 ? "Behind by " + behind : (behind < 0 ? "Ahead by " + (-behind) : "On track");
    var resp = cards.avg_response_mins;
    var pctS = function (v) { return v == null ? "—" : v + "%"; };
    var cardHtml =
      scard(cards.avg_meetings_per_client + ' <small>of ' + d.per_client_target + "</small>" +
            dot(RAG.meetings(cards.avg_meetings_per_client), true), "average meetings attended per client", "") +
      scard(pctS(cards.pos_to_booked_pct) + dot(RAG.p2b(cards.pos_to_booked_pct), true),
            "positive reply → booked call", "") +
      scard(pctS(cards.show_up_pct) + dot(RAG.show(cards.show_up_pct), true), "show-up rate", "") +
      scard((resp == null ? "—" : num(resp)) + dot(RAG.resp(resp), true),
            "average response time (mins) · excluding out-of-hours", "");
    var rowsHtml = (d.clients || []).map(function (c) {
      if (!c.scored) {
        return '<div class="trow unscored"><div class="cn">' + esc(c.name) + "</div>" +
          '<div class="num mut pos-col">—</div><div class="num mut">—</div><div class="num mut">—</div>' +
          '<div class="num mut">—</div><div class="num mut rate">—</div><div class="num mut rate">—</div>' +
          '<div class="num mut rate">—</div>' +
          '<div><span class="badge muted">' + esc(c.status) + "</span></div></div>";
      }
      var p2bN = c.positives > 0 ? Math.round(100 * c.meetings / c.positives) : null;
      var suDen = (c.attended || 0) + (c.no_show || 0);
      var suN = suDen > 0 ? Math.round(100 * c.attended / suDen) : null;
      return '<div class="trow"><div class="cn">' + esc(c.name) + "</div>" +
        '<div class="num pos-col">' + num(c.positives) + "</div>" +
        '<div class="num">' + num(c.said_yes) + "</div>" +
        '<div class="num">' + num(c.booked) + "</div>" +
        '<div class="num">' + num(c.attended) + "</div>" +
        '<div class="num rate">' + (p2bN == null ? "—" : p2bN + "%" + dot(RAG.p2b(p2bN))) + "</div>" +
        '<div class="num rate">' + (suN == null ? "—" : suN + "%" + dot(RAG.show(suN))) + "</div>" +
        '<div class="num rate">' + (c.reply_mins == null ? "—" : fmtReply(c.reply_mins) + dot(RAG.resp(c.reply_mins))) + "</div>" +
        '<div><span class="badge ' + esc(c.tone) + '">' + esc(c.status) + "</span></div></div>";
    }).join("");
    var b = document.createElement("div");
    b.innerHTML =
      '<div class="eyebrow">Meetings this month</div>' +
      '<div class="hero"><div class="big">' + t.counted + ' <small>of ' + t.target + "</small></div>" +
        '<div class="rt"><span class="verdict ' + vClass + '">' + vTxt + "</span>" +
          '<p class="pace">At this pace we finish on ' + t.pace + ". Target " + t.target + ".</p>" +
          '<p class="potential"><b>' + pot + '</b> total potential meetings <span class="pnote">meeting-ready + booked + attended</span></p></div></div>' +
      heroBar(t) +
      '<div class="cards">' + cardHtml + "</div>" +
      '<div class="sec"><h2>Client scoreboard</h2>' +
        '<div class="tbl-scroll"><div class="tbl">' +
          '<div class="trow head"><div>Client</div><div class="h-pos pos-col">Positives</div>' +
            '<div>Ready</div><div>Booked</div><div>Attended</div><div>Pos→Booked</div><div>Show-up</div>' +
            '<div title="Business hours only — excludes out-of-hours">Avg reply</div><div>Status</div></div>' +
          rowsHtml + "</div></div></div>" +
      '<div class="sec"><h2>Meetings attended vs target</h2>' +
        '<div class="chleg"><span><i class="a"></i>Attended</span>' +
          '<span><i class="b"></i>Booked</span><span><i class="r"></i>Meeting-ready</span></div>' +
        '<div class="chart">' + pipelineChart(d.clients || [], d.per_client_target) + "</div></div>";
    return b;
  }

  /* ---------- Board ---------- */
  var BOARD_COLS = [
    {key: "said_yes", title: "Meeting-ready", sub: "said yes, waiting to book"},
    {key: "booked", title: "Booked", sub: "scheduled, still to happen"},
    {key: "attended", title: "Attended", sub: "happened this month"},
    {key: "no_show", title: "No-show", sub: "booked but didn't attend"},
    {key: "cancelled", title: "Cancelled/Closed-Lost", sub: "called off or closed-lost"}];
  var PILL_COLORS = [
    {bg: "#E7EFFB", fg: "#1E40AF"}, {bg: "#E4F4EA", fg: "#166534"},
    {bg: "#F3E8FD", fg: "#6B21A8"}, {bg: "#FCE7EF", fg: "#9D174D"},
    {bg: "#FBEAD7", fg: "#9A3412"}, {bg: "#D8F3F0", fg: "#115E59"},
    {bg: "#FBEACB", fg: "#854D0E"}, {bg: "#E6E6F5", fg: "#3730A3"}];
  function clientColor(name) {
    var h = 0, s = String(name || "");
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return PILL_COLORS[h % PILL_COLORS.length];
  }
  function clientPill(client) {
    if (!client) return "";
    var c = clientColor(client);
    return '<span class="mtag" style="background:' + c.bg + ";color:" + c.fg + '">' + esc(client) + "</span>";
  }
  var ICON_DOC = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>' +
    '<path d="M14 3v5h5" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>';
  var ICON_PHONE = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6.6 10.8a15 15 0 006.6 6.6l2.2-2.2a1 1 0 011-.24 11 11 0 003.5.56 1 1 0 011 1V20a1 1 0 01-1 1A17 17 0 013 4a1 1 0 011-1h3.5a1 1 0 011 1 11 11 0 00.56 3.5 1 1 0 01-.24 1l-2.2 2.3z" fill="currentColor"/></svg>';
  var ICON_MAIL = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M4 7l8 6 8-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  var ICON_WEB = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.7"/><path d="M3 12h18M12 3c2.5 2.5 3.5 6 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-6-3.5-9s1-6.5 3.5-9z" stroke="currentColor" stroke-width="1.7"/></svg>';
  var ICON_EXT = '<svg class="ext" width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 17L17 7M9 7h8v8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var ICON_CAL = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M3 10h18M8 3v4M16 3v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  var ICON_WARN = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3l9 16H3z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 10v4M12 17v.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  function webFromEmail(email) {
    var at = String(email || "").split("@")[1];
    if (!at) return "";
    at = at.toLowerCase().trim();
    if (/^(gmail|googlemail|outlook|hotmail|yahoo|ymail|icloud|aol|protonmail|proton|gmx|mail|live|msn|me|comcast|verizon)\./.test(at + ".")) return "";
    return at;
  }
  function setterLink(email) { return email ? "setter.html#/r/" + encodeURIComponent(email) : ""; }

  function boardCard(m) {
    var d = document.createElement("div");
    d.className = "mcard" + (m.overdue ? " overdue" : "");
    d.setAttribute("data-id", m.id);
    d.setAttribute("data-status", m.status);

    // when — label + value, coloured by state
    var whenLbl = "", whenVal = "", whenCls = "";
    if (m.status === "booked") {
      if (m.overdue) { whenLbl = "Overdue"; whenVal = "was " + fmtDate(m.date); whenCls = "od"; }
      else if (m.date) { whenLbl = "Meeting"; whenVal = fmtDate(m.date); }
    } else if (m.status === "attended") { whenLbl = "Attended"; whenVal = m.date ? fmtDate(m.date) : "this month"; whenCls = "gd"; }
    else if (m.status === "no_show") { whenLbl = "No-show"; whenVal = m.date ? fmtDate(m.date) : "—"; whenCls = "od"; }
    else if (m.status === "cancelled") { whenLbl = "Cancelled"; whenVal = m.date ? fmtDate(m.date) : "—"; }
    else if (m.status === "said_yes") { whenLbl = "Said yes"; whenVal = m.said_yes_on ? fmtDate(m.said_yes_on) : "—"; }

    var domain = webFromEmail(m.email);
    var url = setterLink(m.email);

    // identity — company name hyperlinked to the website (saves a line vs showing both)
    var idline = "";
    if (m.company) idline = '<div class="mcard-idline">' + (domain
        ? '<a href="https://' + esc(domain) + '" target="_blank" rel="noopener">' + esc(m.company) + "</a>"
        : esc(m.company)) + "</div>";
    else if (domain) idline = '<div class="mcard-idline"><a href="https://' + esc(domain) + '" target="_blank" rel="noopener">' + esc(domain) + "</a></div>";
    // the hero: a meeting band, tinted by state (od = red alert, gd = green done)
    var band = whenVal ? ('<div class="mcard-band ' + whenCls + '">' + (whenCls === "od" ? ICON_WARN : ICON_CAL) +
      '<span class="bl">' + whenLbl + '</span><span class="bv">' + esc(whenVal) + "</span></div>") : "";

    // status dropdown — switch the lead's stage right from the card
    var statusSel = '<select class="mcard-status" data-act="status">' +
      BOARD_COLS.map(function (c) {
        return '<option value="' + c.key + '"' + (c.key === m.status ? " selected" : "") + ">" + esc(c.title) + "</option>";
      }).join("") + "</select>";
    // hide the added-by line for Bjion / the admin (self-added, just noise)
    var by = (m.by && !/bjion|admin@navreo|zapier/i.test(m.by)) ? '<span class="mcard-by">' + esc(m.by) + "</span>" : "";

    d.innerHTML =
      '<div class="mcard-head">' +
        '<div class="mcard-t"><span>' + esc(m.person || "(no name)") + "</span></div>" +
        (m.client ? '<span class="mcard-pill">' + clientPill(m.client) + "</span>" : "") +
        '<button class="mcard-del" data-act="dismiss" title="Remove from board">×</button>' +
      "</div>" +
      idline +
      band +
      (url ? '<div class="mcard-crows">' +
          '<a class="crow" href="' + url + '" target="_blank" rel="noopener" title="Open in the setter — dial from the multi-number picker">' + ICON_PHONE + "<span>Call</span>" + ICON_EXT + "</a>" +
          '<a class="crow" href="' + url + '" target="_blank" rel="noopener" title="Open the lead in the setter to reply">' + ICON_MAIL + '<span class="cval">' + esc(m.email) + "</span>" + ICON_EXT + "</a></div>" : "") +
      '<div class="mcard-foot">' + statusSel + by + "</div>";

    // click anywhere on the card (except the dropdown / links / ×) opens the edit dialog
    d.onclick = function () { openEdit(m); };
    var ss = d.querySelector('[data-act="status"]');
    ss.onchange = function () { setStatus(m, ss.value); };
    ss.addEventListener("click", function (e) { e.stopPropagation(); });
    ss.addEventListener("mousedown", function (e) { e.stopPropagation(); });
    d.querySelector('[data-act="dismiss"]').onclick = function (e) { e.stopPropagation(); dismiss(m); };
    // contact/website links open in a new tab; never start a drag or open the chooser
    Array.prototype.forEach.call(d.querySelectorAll("a"), function (a) {
      a.draggable = false;
      a.addEventListener("click", function (e) { e.stopPropagation(); });
      a.addEventListener("mousedown", function (e) { e.stopPropagation(); });
    });
    return d;
  }
  function openChooser(rowEl, m) {
    var ex = rowEl.nextSibling;
    if (ex && ex.className === "choices") { ex.parentNode.removeChild(ex); return; }
    var box = document.createElement("div");
    box.className = "choices";
    box.innerHTML = ORDER.map(function (s) {
      return '<button class="choice ' + (s === m.status ? "cur" : "") + '" data-status="' + s + '">' + STATUS_WORDS[s] + "</button>";
    }).join("");
    Array.prototype.forEach.call(box.children, function (b) {
      b.onclick = function () { setStatus(m, b.getAttribute("data-status")); };
    });
    rowEl.parentNode.insertBefore(box, rowEl.nextSibling);
  }
  function setStatus(m, status) {
    post("/api/team-target/status", {id: m.id, email: m.email, client: m.client,
      person: m.person, company: m.company, status: status, said_yes_on: m.said_yes_on || null,
      date: (status === "attended" || status === "no_show") ? (m.date || TT.today) : (m.date || null)});
  }
  function dismiss(m) {
    if (String(m.id).indexOf("man:") === 0 &&
        !window.confirm("Delete " + (m.person || "this meeting") + "? A hand-added meeting can't be restored.")) return;
    post("/api/team-target/dismiss", {id: m.id, email: m.email, client: m.client,
      person: m.person, company: m.company, said_yes_on: m.said_yes_on || null});
  }
  function renderBoard() {
    var b = document.createElement("div");
    var seen = {};
    TT.meetings.forEach(function (m) { if (m.client) seen[m.client] = 1; });
    (TT.removed || []).forEach(function (m) { if (m.client) seen[m.client] = 1; });
    var clientList = Object.keys(seen).sort(function (a, z) { return a.toLowerCase() < z.toLowerCase() ? -1 : 1; });
    if (BOARD_CLIENT && clientList.indexOf(BOARD_CLIENT) < 0) BOARD_CLIENT = "";
    var match = function (m) { return !BOARD_CLIENT || m.client === BOARD_CLIENT; };
    var head = document.createElement("div"); head.className = "board-head";
    head.innerHTML = '<div class="h4">Leads <span class="hint">' +
      "drag a card between columns, or tap a name · + Add to create, × to remove</span></div>" +
      '<label class="bfilter">Client <select id="b-client"><option value="">All clients</option>' +
      clientList.map(function (c) {
        return '<option value="' + esc(c) + '"' + (c === BOARD_CLIENT ? " selected" : "") + ">" + esc(c) + "</option>";
      }).join("") + "</select></label>";
    b.appendChild(head);
    head.querySelector("#b-client").onchange = function () { BOARD_CLIENT = this.value; render(); };
    var overdue = TT.meetings.filter(function (m) { return m.overdue && match(m); });
    if (overdue.length) {
      var al = document.createElement("div"); al.className = "board-alert";
      al.innerHTML = "⚠ <b>" + overdue.length + " " +
        (overdue.length === 1 ? "meeting has" : "meetings have") +
        " passed without confirmation</b> — confirm attended, or move them to no-show.";
      b.appendChild(al);
    }
    var wrap = document.createElement("div"); wrap.className = "board";
    BOARD_COLS.forEach(function (c) {
      var rows = TT.meetings.filter(function (m) { return m.status === c.key && match(m); });
      if (c.key === "said_yes") rows.sort(function (a, z) { return z.waiting_days - a.waiting_days; });
      var od = c.key === "booked" ? rows.filter(function (m) { return m.overdue; }).length : 0;
      var col = document.createElement("div"); col.className = "bcol";
      col.innerHTML = '<div class="bcol-h"><div><b>' + c.title + '</b> <span class="bn">' + rows.length + "</span>" +
        (od ? ' <span class="odpill">' + od + " overdue</span>" : "") +
        '<div class="bcol-sub">' + c.sub + "</div></div>" +
        '<button class="badd" data-stage="' + c.key + '">+ Add</button></div>';
      col.querySelector(".badd").onclick = function () { openAdd(c.key); };
      var list = document.createElement("div"); list.className = "bcol-list";
      if (!rows.length) list.innerHTML = '<div class="bempty">Nobody here yet.</div>';
      rows.forEach(function (m) {
        var card = boardCard(m);
        card.draggable = true;
        card.addEventListener("dragstart", function (e) {
          DRAG = m; card.classList.add("dragging"); e.dataTransfer.effectAllowed = "move";
          try { e.dataTransfer.setData("text/plain", String(m.id)); } catch (_) { /* IE */ }
        });
        card.addEventListener("dragend", function () {
          DRAG = null; card.classList.remove("dragging");
          Array.prototype.forEach.call(document.querySelectorAll(".bcol.over"),
            function (x) { x.classList.remove("over"); });
        });
        list.appendChild(card);
      });
      col.appendChild(list);
      col.addEventListener("dragover", function (e) {
        if (DRAG && DRAG.status !== c.key) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; col.classList.add("over"); }
      });
      col.addEventListener("dragleave", function (e) { if (!col.contains(e.relatedTarget)) col.classList.remove("over"); });
      col.addEventListener("drop", function (e) {
        e.preventDefault(); col.classList.remove("over");
        if (DRAG && DRAG.status !== c.key) setStatus(DRAG, c.key);
        DRAG = null;
      });
      wrap.appendChild(col);
    });
    b.appendChild(wrap);
    var rm = (TT.removed || []).filter(match);
    if (rm.length) {
      var sec = document.createElement("div"); sec.className = "removed-sec";
      sec.innerHTML = '<div class="rm-h">Removed this month · ' + rm.length +
        ' <span class="hint">— auto-pulled leads; restore any time</span></div>';
      rm.forEach(function (m) {
        var r = document.createElement("div"); r.className = "prow rm-row";
        var sub = [m.client, m.company].filter(Boolean).join(" · ");
        r.innerHTML = '<div class="who"><div class="nm">' + esc(m.person || "(no name)") + "</div>" +
          (sub ? '<div class="sub">' + esc(sub) + "</div>" : "") +
          '</div><div class="rt-cell"><button class="mk" data-act="restore">Restore</button></div>';
        r.querySelector('[data-act="restore"]').onclick = function () {
          post("/api/team-target/restore", {id: m.id, email: m.email});
        };
        sec.appendChild(r);
      });
      b.appendChild(sec);
    }
    return b;
  }

  /* ---------- add / edit modal ---------- */
  function fillClients(sel) {
    var cs = (TT.clients_all && TT.clients_all.length ? TT.clients_all
      : (TT.clients || []).map(function (c) { return c.name; })).slice();
    if (sel && cs.indexOf(sel) < 0) cs.unshift(sel);
    el("f-client").innerHTML = cs.map(function (c) {
      return '<option' + (c === sel ? " selected" : "") + ">" + esc(c) + "</option>";
    }).join("");
  }
  function openAdd(stage) {
    if (!TT) return;
    EDITING = null;
    fillClients("");
    el("f-person").value = ""; el("f-company").value = ""; el("f-date").value = TT.today;
    if (el("f-stage")) el("f-stage").value = typeof stage === "string" ? stage : "booked";
    el("tt-ov-title").textContent = "Add to the board";
    el("f-save").textContent = "Add";
    el("tt-ov").classList.add("on");
  }
  function openEdit(m) {
    if (!TT) return;
    EDITING = m;
    fillClients(m.client || "");
    el("f-person").value = m.person || "";
    el("f-company").value = m.company || "";
    el("f-date").value = String((m.status === "said_yes" ? m.said_yes_on : m.date) || "").slice(0, 10);
    if (el("f-stage")) el("f-stage").value = m.status;
    el("tt-ov-title").textContent = "Edit meeting";
    el("f-save").textContent = "Save";
    el("tt-ov").classList.add("on");
  }
  el("sb-addbtn").onclick = function () { openAdd(); };
  el("f-cancel").onclick = function () { el("tt-ov").classList.remove("on"); EDITING = null; };
  el("tt-ov").onclick = function (e) { if (e.target === el("tt-ov")) { el("tt-ov").classList.remove("on"); EDITING = null; } };
  el("f-save").onclick = function () {
    var person = el("f-person").value.trim();
    if (!person) { el("f-person").focus(); return; }
    var status = el("f-stage").value, date = el("f-date").value || null;
    var client = el("f-client").value, company = el("f-company").value.trim();
    if (EDITING) {
      var m = EDITING;
      post("/api/team-target/status", {id: m.id, email: m.email, client: client, person: person,
        company: company, status: status,
        date: status === "said_yes" ? null : date,
        said_yes_on: status === "said_yes" ? date : (m.said_yes_on || null)},
        function () { el("tt-ov").classList.remove("on"); EDITING = null; });
    } else {
      post("/api/team-target/meeting", {client: client, person: person,
        company: company, date: date, status: status},
        function () { el("tt-ov").classList.remove("on"); });
    }
  };

  loadAll();
})();
