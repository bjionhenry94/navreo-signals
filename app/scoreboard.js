/* Team Target — the team's meetings hub. Two tabs under one header:
     Scoreboard — live per-client numbers (/api/scoreboard/data)
     Board — add / move / remove the three meeting states (/api/team-target/*)
   One "Add a meeting"; any write refreshes both views. */
(function () {
  "use strict";
  var el = function (id) { return document.getElementById(id); };
  el("rail").outerHTML = renderRail("target");

  var TAB = "scoreboard", SB = null, TT = null, DRAG = null, BOARD_CLIENT = "";

  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); };
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
      '<button class="tt-tab ' + (TAB === "board" ? "on" : "") + '" data-tab="board">Board' +
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
  function chart(rows, opts) {
    opts = opts || {};
    var maxVal = rows.reduce(function (m, r) { return Math.max(m, r.value); }, 0);
    var axisMax = opts.target ? Math.max(opts.target + 1, Math.min(opts.target * 2, maxVal)) : (maxVal || 1);
    var tgtPct = opts.target ? clamp(100 * opts.target / axisMax) : 0;
    var body = rows.map(function (r, i) {
      var w = clamp(100 * r.value / axisMax), clipped = r.value > axisMax;
      var tgtLine = opts.target ? '<div class="chtgt" style="left:' + tgtPct + '%">' +
        (i === 0 ? '<span class="lbl">target ' + opts.target + "</span>" : "") + "</div>" : "";
      return '<div class="chrow"><div class="cl">' + esc(r.name) + '</div><div class="chtrack">' +
        '<div class="chbar ' + (opts.cls || "") + (clipped ? " clip" : "") + '" style="width:' + w + '%"></div>' +
        tgtLine + '</div><div class="chval">' + num(r.value) + "</div></div>";
    }).join("");
    return body || '<div class="skel" style="padding:14px 0">Nothing yet this month.</div>';
  }
  function scard(vHtml, k, tone) {
    return '<div class="scard ' + (tone || "") + '"><div class="v">' + vHtml + '</div><div class="k">' + esc(k) + "</div></div>";
  }
  function renderScoreboard(d) {
    var t = d.totals, cards = d.cards || {};
    var behind = t.behind || 0;
    var vClass = behind > 0 ? "behind" : "ok";
    var vTxt = behind > 0 ? "Behind by " + behind : (behind < 0 ? "Ahead by " + (-behind) : "On track");
    var resp = cards.avg_response_mins;
    var pctS = function (v) { return v == null ? "—" : v + "%"; };
    var cardHtml =
      scard(cards.avg_meetings_per_client + ' <small>of ' + d.per_client_target + "</small>",
            "average meetings per client", cards.avg_meetings_per_client < d.pace_mark ? "warn" : "") +
      scard(pctS(cards.pos_to_booked_pct), "positive reply → booked call", "") +
      scard(pctS(cards.show_up_pct), "show-up rate", "") +
      scard(resp == null ? "—" : num(resp), "average response time (mins) · excluding out-of-hours", "");
    var rowsHtml = (d.clients || []).map(function (c) {
      if (!c.scored) {
        return '<div class="trow unscored"><div class="cn">' + esc(c.name) + "</div>" +
          '<div class="num mut pos-col">—</div><div class="num mut">—</div><div class="num mut">—</div>' +
          '<div class="num mut">—</div><div class="num mut rate">—</div><div class="num mut rate">—</div>' +
          '<div><span class="badge muted">' + esc(c.status) + "</span></div></div>";
      }
      var p2b = c.positives > 0 ? Math.round(100 * c.meetings / c.positives) + "%" : "—";
      var suDen = (c.attended || 0) + (c.no_show || 0);
      var su = suDen > 0 ? Math.round(100 * c.attended / suDen) + "%" : "—";
      return '<div class="trow"><div class="cn">' + esc(c.name) + "</div>" +
        '<div class="num pos-col">' + num(c.positives) + "</div>" +
        '<div class="num">' + num(c.said_yes) + "</div>" +
        '<div class="num">' + num(c.booked) + "</div>" +
        '<div class="num">' + num(c.attended) + "</div>" +
        '<div class="num rate">' + p2b + '</div><div class="num rate">' + su + "</div>" +
        '<div><span class="badge ' + esc(c.tone) + '">' + esc(c.status) + "</span></div></div>";
    }).join("");
    var mx = (d.booked_chart || []).reduce(function (m, x) { return Math.max(m, x.value); }, 0);
    var anyClip = (d.booked_chart || []).some(function (r) {
      return r.value > Math.max(d.per_client_target + 1, Math.min(d.per_client_target * 2, mx)); });
    var b = document.createElement("div");
    b.innerHTML =
      '<div class="eyebrow">Meetings this month</div>' +
      '<div class="hero"><div class="big">' + t.counted + ' <small>of ' + t.target + "</small></div>" +
        '<div class="rt"><span class="verdict ' + vClass + '">' + vTxt + "</span>" +
          '<p class="pace">At this pace we finish on ' + t.pace + ". Target " + t.target + ".</p>" +
          '<p class="subline">' + t.booked + " booked and still to happen · " + t.said_yes_open +
            " more said yes and are waiting to be booked.</p></div></div>" +
      heroBar(t) +
      '<div class="cards">' + cardHtml + "</div>" +
      '<div class="sec"><h2>Client scoreboard</h2>' +
        '<p class="desc">Ready = said yes, waiting to book · Booked = scheduled and upcoming · Attended = happened. ' +
        "Pos→Booked = positive replies that became a booked call · Show-up = attended of the calls that were due.</p>" +
        '<div class="tbl-scroll"><div class="tbl">' +
          '<div class="trow head"><div>Client</div><div class="h-pos pos-col">Positives</div>' +
            "<div>Ready</div><div>Booked</div><div>Attended</div><div>Pos→Booked</div><div>Show-up</div><div>Status</div></div>" +
          rowsHtml + "</div></div></div>" +
      '<div class="sec"><h2>Meetings booked vs target</h2>' +
        '<p class="desc">Dashed line is the ' + d.per_client_target + "-meeting target." +
          (anyClip ? " A runaway leader is clipped at the axis edge — the number is exact." : "") + "</p>" +
        '<div class="chart">' + chart(d.booked_chart || [], {target: d.per_client_target}) + "</div></div>" +
      '<div class="sec"><h2>Positive replies, clean</h2>' +
        '<p class="desc">Unique leads with a positive reply this month (Interested, Meeting Request, Call Booked, Information Request).</p>' +
        '<div class="chart">' + chart(d.positives_chart || [], {cls: "pos"}) + "</div></div>";
    return b;
  }

  /* ---------- Board ---------- */
  var BOARD_COLS = [
    {key: "said_yes", title: "Meeting-ready", sub: "said yes, waiting to book"},
    {key: "booked", title: "Booked", sub: "scheduled, still to happen"},
    {key: "attended", title: "Attended", sub: "happened this month"}];
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

  function boardCard(m) {
    var d = document.createElement("div");
    d.className = "mcard" + (m.overdue ? " overdue" : "");
    d.setAttribute("data-id", m.id);
    d.setAttribute("data-status", m.status);
    var pills = clientPill(m.client);
    if (m.source && m.source.indexOf("auto") === 0) pills += '<span class="mtag auto">Auto</span>';
    if (m.status === "said_yes") {
      var late = m.waiting_days >= 7;
      pills += '<span class="mtag ' + (late ? "amber" : "grey") + '">' +
        (m.waiting_days <= 0 ? "said yes today" : "waiting " + m.waiting_days + "d") + "</span>";
    } else if (m.status === "booked") {
      if (m.overdue) pills += '<span class="mtag red">⚠ overdue' + (m.date ? " · " + esc(fmtDate(m.date)) : "") + "</span>";
      else if (m.date) pills += '<span class="mtag grey">' + esc(fmtDate(m.date)) + "</span>";
    } else if (m.status === "attended") {
      pills += '<span class="mtag green">attended' + (m.date ? " · " + esc(fmtDate(m.date)) : "") + "</span>";
    }
    var action = m.status === "said_yes" ? '<button class="mk" data-act="quickbook">Mark booked</button>'
      : m.status === "booked" ? '<button class="mk attend" data-act="confirmattended">Confirmed attended</button>' : "";
    var by = m.by ? '<span class="mcard-by">' + esc(m.by) + " · " + ago(m.at) + "</span>" : "";
    d.innerHTML =
      '<button class="mcard-del" data-act="dismiss" title="Remove from board">×</button>' +
      '<div class="mcard-t"><span class="mcard-ic">' + ICON_DOC + "</span><span>" + esc(m.person || "(no name)") + "</span></div>" +
      (m.company ? '<div class="mcard-co">' + esc(m.company) + "</div>" : "") +
      '<div class="mcard-tags">' + pills + "</div>" +
      (action || by ? '<div class="mcard-foot">' + (action || "<span></span>") + by + "</div>" : "");
    d.querySelector(".mcard-t").onclick = function () { openChooser(d, m); };
    var qb = d.querySelector('[data-act="quickbook"]');
    if (qb) qb.onclick = function (e) { e.stopPropagation(); setStatus(m, "booked"); };
    var ca = d.querySelector('[data-act="confirmattended"]');
    if (ca) ca.onclick = function (e) { e.stopPropagation(); setStatus(m, "attended"); };
    d.querySelector('[data-act="dismiss"]').onclick = function (e) { e.stopPropagation(); dismiss(m); };
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
    head.innerHTML = '<div class="h4">Board <span class="hint">' +
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

  /* ---------- add modal ---------- */
  function openAdd(stage) {
    if (!TT) return;
    var clients = TT.clients_all && TT.clients_all.length ? TT.clients_all
      : (TT.clients || []).map(function (c) { return c.name; });
    el("f-client").innerHTML = clients.map(function (c) { return "<option>" + esc(c) + "</option>"; }).join("");
    el("f-person").value = ""; el("f-company").value = ""; el("f-date").value = TT.today;
    if (el("f-stage")) el("f-stage").value = typeof stage === "string" ? stage : "booked";
    el("tt-ov").classList.add("on");
  }
  el("sb-addbtn").onclick = function () { openAdd(); };
  el("f-cancel").onclick = function () { el("tt-ov").classList.remove("on"); };
  el("tt-ov").onclick = function (e) { if (e.target === el("tt-ov")) el("tt-ov").classList.remove("on"); };
  el("f-save").onclick = function () {
    var person = el("f-person").value.trim();
    if (!person) { el("f-person").focus(); return; }
    post("/api/team-target/meeting", {client: el("f-client").value, person: person,
      company: el("f-company").value.trim(), date: el("f-date").value || null, status: el("f-stage").value},
      function () { el("tt-ov").classList.remove("on"); });
  };

  loadAll();
})();
