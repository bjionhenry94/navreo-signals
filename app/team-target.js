/* Team Target board — live client of /api/team-target/*. Only ATTENDED
   meetings count toward the 4-per-client target (owner ruling 2026-09-17). */
(function () {
  "use strict";
  var el = function (id) { return document.getElementById(id); };
  el("rail").outerHTML = renderRail("target");

  var MODEL = null, TAB = "month";
  var STATUS_WORDS = {said_yes: "Said yes", booked: "Booked", attended: "Attended",
                      no_show: "No-show", cancelled: "Cancelled", not_fit: "Not a fit"};
  var ORDER = ["said_yes", "booked", "attended", "no_show", "cancelled", "not_fit"];
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g,
    function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); };

  function ago(iso) {
    if (!iso) return "";
    var t = Date.parse(String(iso).replace(" ", "T"));
    if (isNaN(t)) return "";
    var m = Math.max(0, (Date.now() - t) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return Math.round(m) + "m ago";
    if (m < 1440) return Math.round(m / 60) + "h ago";
    return Math.round(m / 1440) + "d ago";
  }
  function waitTxt(d) { return d <= 0 ? "said yes today" : "waiting " + d + (d === 1 ? " day" : " days"); }
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtDate(s) {
    if (!s) return "";
    var m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return String(s);
    return MON[(+m[2]) - 1] + " " + (+m[3]);
  }

  function load(cb) {
    fetch("/api/team-target/data", {credentials: "same-origin"})
      .then(function (r) { return r.json(); })
      .then(function (d) { MODEL = d; if (cb) cb(); render(); })
      .catch(function () { el("tt-body").innerHTML = '<div class="skel">Couldn\'t load the board. Refresh in a moment.</div>'; });
  }

  function post(url, body, done) {
    fetch(url, {method: "POST", credentials: "same-origin",
                headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})
      .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, j: j}; }); })
      .then(function (res) { if (!res.ok) { alert((res.j && res.j.error) || "Couldn't save"); return; } load(done); })
      .catch(function () { alert("Couldn't save — check your connection."); });
  }

  /* ---------- tabs ---------- */
  function renderTabs() {
    var t = MODEL.totals;
    var defs = [["month", "This month", ""],
                ["yes", "Said yes", t.said_yes_open],
                ["meetings", "Meetings", MODEL.meetings.length],
                ["clients", "Clients", MODEL.clients.length]];
    el("tt-tabs").innerHTML = defs.map(function (d) {
      return '<button class="tt-tab ' + (TAB === d[0] ? "on" : "") + '" data-tt="tab" data-tab="' +
        d[0] + '">' + d[1] + (d[2] !== "" ? '<span class="b">' + d[2] + "</span>" : "") + "</button>";
    }).join("");
    Array.prototype.forEach.call(el("tt-tabs").children, function (b) {
      b.onclick = function () { TAB = b.getAttribute("data-tab"); render(); };
    });
  }

  /* ---------- person row with inline status ---------- */
  function personRow(m, showMk) {
    var sub = [m.client, m.company].filter(Boolean).join(" · ");
    var amber = m.waiting_days >= 7 ? " amber" : "";
    var right = "";
    if (m.status === "said_yes") {
      right = '<span class="wait' + amber + '">' + waitTxt(m.waiting_days) + "</span>" +
        (showMk ? ' <button class="mk" data-act="quickbook">Mark booked</button>' : "");
    } else if (m.status === "booked") {
      right = (m.date ? '<span class="date">' + esc(fmtDate(m.date)) + "</span>" : "") +
        ' <button class="mk attend" data-act="confirmattended">Confirmed attended</button>';
    } else {
      right = '<span class="date">' + esc(fmtDate(m.date)) + "</span>";
    }
    var tag = m.source && m.source.indexOf("auto") === 0 && m.status === "said_yes"
      ? '<span class="tag">auto</span>' : "";
    var by = m.by ? '<span class="sub">' + esc(m.by) + " · " + ago(m.at) + "</span>" : "";
    var d = document.createElement("div");
    d.className = "prow";
    d.setAttribute("data-tt", "person");
    d.setAttribute("data-id", m.id);
    d.setAttribute("data-status", m.status);
    d.setAttribute("data-client", m.client);
    d.innerHTML = '<div class="who"><div class="nm">' + esc(m.person || "(no name)") + tag +
      "</div>" + (sub ? '<div class="sub">' + esc(sub) + "</div>" : "") + by +
      '</div><div class="rt-cell">' + right + "</div>";
    var open = function () { openChooser(d, m); };
    d.querySelector(".who").onclick = open;
    var qb = d.querySelector('[data-act="quickbook"]');
    if (qb) qb.onclick = function (e) { e.stopPropagation(); setStatus(m, "booked"); };
    var ca = d.querySelector('[data-act="confirmattended"]');
    if (ca) ca.onclick = function (e) { e.stopPropagation(); setStatus(m, "attended"); };
    return d;
  }

  function openChooser(rowEl, m) {
    var ex = rowEl.nextSibling;
    if (ex && ex.className === "choices") { ex.parentNode.removeChild(ex); return; }
    var box = document.createElement("div");
    box.className = "choices";
    box.innerHTML = ORDER.map(function (s) {
      return '<button class="choice ' + (s === m.status ? "cur" : "") + '" data-tt="set-status" data-status="' +
        s + '">' + STATUS_WORDS[s] + "</button>";
    }).join("");
    Array.prototype.forEach.call(box.children, function (b) {
      b.onclick = function () { setStatus(m, b.getAttribute("data-status")); };
    });
    rowEl.parentNode.insertBefore(box, rowEl.nextSibling);
  }

  function setStatus(m, status) {
    post("/api/team-target/status", {id: m.id, email: m.email, client: m.client,
      person: m.person, company: m.company, status: status,
      said_yes_on: m.said_yes_on || null,
      date: (status === "attended" || status === "no_show") ? (m.date || MODEL.today) : (m.date || null)});
  }

  /* ---------- This month ---------- */
  function renderMonth() {
    var t = MODEL.totals, mt = MODEL.metrics, b = document.createElement("div");
    var pct = t.target ? Math.min(100, 100 * t.counted / t.target) : 0;
    var tickPct = t.target ? Math.min(100, 100 * t.should_be_today / t.target) : 0;
    /* "Pending" = booked, still to happen — shown as a dashed segment continuing
       from the solid attended fill, capped at the target. */
    var pendPct = t.target ? Math.max(0, Math.min(100 - pct, 100 * t.booked / t.target)) : 0;
    var vClass = t.behind > 0 ? "behind" : "ok";
    var vTxt = t.behind > 0 ? "Behind by " + t.behind : (t.behind < 0 ? "Ahead by " + (-t.behind) : "On track");
    b.innerHTML =
      '<div class="hero"><div><div style="font-size:12px;letter-spacing:.06em;color:var(--ink-4);text-transform:uppercase">Attended this month</div>' +
        '<div class="big" data-tt="big-number">' + t.counted + ' <small data-tt="target">of ' + t.target + "</small></div></div>" +
        '<div class="rt"><span class="verdict ' + vClass + '" data-tt="verdict">' + vTxt + "</span>" +
        '<p class="pace" data-tt="pace">At this pace we finish on ' + t.pace + ". Target " + t.target + ".</p>" +
        '<p class="subline">' + t.booked + " booked, still to happen · mark them Attended once they do. Last-month feel: " +
        t.said_yes_open + " said yes and waiting.</p></div></div>" +
      '<div class="bar"><div class="fill" style="width:' + pct + '%"></div>' +
        (pendPct > 0 ? '<div class="pending" style="left:' + pct + '%;width:' + pendPct + '%"></div>' : "") +
        '<div class="tick" style="left:' + tickPct + '%"></div></div>' +
      '<div class="bar-lbl"><b>' + t.should_be_today + "</b> where we should be today" +
        (t.booked > 0 ? ' · <span class="leg-pending">' + t.booked + " pending</span>" : "") + "</div>";

    var cols = document.createElement("div");
    cols.className = "cols";
    var chase = document.createElement("div");
    chase.innerHTML = '<div class="h4">Chase next <span class="hint">longest waits · tap anyone to update them</span></div>';
    var cn = MODEL.chase_next.slice(0, 5);
    if (!cn.length) chase.innerHTML += '<div class="hint" style="padding:12px 0">Nobody waiting — everyone who said yes is booked.</div>';
    cn.forEach(function (w) {
      chase.appendChild(personRow({id: w.id, email: w.email, person: w.person, company: w.company,
        client: w.client, status: "said_yes", waiting_days: w.waiting_days, source: "auto",
        said_yes_on: "", date: ""}, true));
    });

    var help = document.createElement("div");
    var worst = MODEL.clients.filter(function (c) { return c.attended < c.target; }).slice(0, 3);
    help.innerHTML = '<div class="help"><div class="lead">Help first ' +
      '<span class="hint">most people waiting</span></div>' +
      '<div class="z"><b data-tt="zero-clients">' + t.zero_clients + " clients on 0</b> — start here.</div>" +
      worst.map(function (c) {
        var w = c.said_yes;
        return '<div class="crow"><span class="cn" data-tt="client" data-client="' + esc(c.name) + '">' +
          esc(c.name) + '</span><span data-tt="client-count">' + c.attended + " of " + c.target + "</span>" +
          (w ? '<span class="pillw">' + w + " waiting</span>" : "") + "</div>";
      }).join("") + "</div>";

    cols.appendChild(chase); cols.appendChild(help);

    var facts = document.createElement("div");
    facts.className = "facts";
    var sh = mt.show_up_pct == null ? "—" : mt.show_up_pct + "%";
    facts.innerHTML =
      fact(t.avg_per_client, "attended per client", "") +
      fact('<span data-tt="clients-on-target">' + t.clients_on_target + "</span> <small>of " + t.active_clients + "</small>", "clients at 4 or more", "") +
      fact('<span data-tt="longest-wait">' + t.longest_wait + "</span> <small>days</small>", "longest wait", t.longest_wait >= 7 ? "amber" : "") +
      fact('<span data-tt="time-to-book">' + mt.reply_time + "</span>", "avg reply time", "") +
      fact('<span data-tt="yes-to-booked">' + mt.yes_to_booked_pct + "%</span> <small>" + mt.yes_to_booked_num + " of " + mt.yes_to_booked_den + "</small>", "yeses that got booked", "") +
      fact('<span data-tt="show-up">' + sh + "</span> <small>" + mt.show_up_num + " of " + mt.show_up_den + "</small>", "showed up", "") +
      fact(t.said_yes_open, "said yes, waiting", "") +
      fact(t.booked, "booked, to happen", "");
    b.appendChild(cols); b.appendChild(facts);
    return b;
  }
  function fact(v, k, cls) {
    return '<div class="fact"><div class="v ' + (cls || "") + '">' + v + '</div><div class="k">' + k + "</div></div>";
  }

  /* ---------- Said yes ---------- */
  function renderYes() {
    var b = document.createElement("div");
    b.innerHTML = '<div class="h4">Said yes <span class="hint">' + MODEL.totals.said_yes_open +
      " waiting · longest first · tap anyone to update them</span></div>";
    var waiting = MODEL.meetings.filter(function (m) { return m.status === "said_yes"; })
      .sort(function (a, c) { return c.waiting_days - a.waiting_days; });
    if (!waiting.length) b.innerHTML += '<div class="hint" style="padding:14px 0">Nobody is waiting right now.</div>';
    waiting.forEach(function (m) { b.appendChild(personRow(m, true)); });
    return b;
  }

  /* ---------- Meetings ---------- */
  function renderMeetings() {
    var b = document.createElement("div"), t = MODEL.totals;
    var didnt = MODEL.meetings.filter(function (m) { return ["no_show", "cancelled", "not_fit"].indexOf(m.status) >= 0; });
    b.innerHTML = '<div class="mlead">Meetings</div><div class="hint" style="margin-bottom:6px"><b>' +
      t.counted + " count toward the target</b> · " + didnt.length + " didn't happen</div>";
    group(b, "Attended", MODEL.meetings.filter(function (m) { return m.status === "attended"; }));
    group(b, "Booked · still to happen", MODEL.meetings.filter(function (m) { return m.status === "booked"; }));
    group(b, "Didn't happen — re-book?", didnt);
    return b;
  }
  function group(b, title, rows) {
    if (!rows.length) return;
    var h = document.createElement("div"); h.className = "mgroup"; h.textContent = title + " · " + rows.length;
    b.appendChild(h);
    rows.forEach(function (m) { b.appendChild(personRow(m, false)); });
  }

  /* ---------- Clients ---------- */
  function renderClients() {
    var b = document.createElement("div"), t = MODEL.totals;
    b.innerHTML = '<div class="h4">Every client <span class="hint">worst first · ' +
      t.clients_on_target + " of " + t.active_clients + " at 4 or more</span></div>";
    var actionable = MODEL.clients.filter(function (c) { return c.attended > 0 || c.booked > 0 || c.said_yes > 0 || c.didnt > 0; });
    var quiet = MODEL.clients.filter(function (c) { return !(c.attended > 0 || c.booked > 0 || c.said_yes > 0 || c.didnt > 0); });
    actionable.forEach(function (c) { b.appendChild(clientRow(c)); });
    if (quiet.length) {
      var f = document.createElement("div"); f.className = "fold";
      f.textContent = quiet.length + " clients on 0, nobody waiting: " + quiet.map(function (c) { return c.name; }).join(" · ");
      b.appendChild(f);
    }
    return b;
  }
  function clientRow(c) {
    var d = document.createElement("div"); d.className = "crow2";
    d.setAttribute("data-tt", "client"); d.setAttribute("data-client", c.name);
    var full = c.attended >= c.target;
    var dots = "";
    for (var i = 0; i < c.target; i++) dots += '<span class="dot ' + (i < c.attended ? (full ? "g" : "on") : "") + '"></span>';
    var over = c.attended > c.target ? ' <span class="done">+' + (c.attended - c.target) + "</span>" : "";
    var waitNames = c.waiting_names && c.waiting_names.length
      ? c.waiting_names.slice(0, 3).join(", ") + (c.waiting_names.length > 3 ? " +" + (c.waiting_names.length - 3) : "") : "";
    d.innerHTML = '<span class="cx">' + esc(c.name) + '</span><span class="dots">' + dots + "</span>" +
      '<span data-tt="client-count" style="min-width:54px">' + c.attended + " of " + c.target + "</span>" + over +
      '<span class="cwait">' + (waitNames ? esc(waitNames) : (full ? '<span class="done">done</span>' : "")) + "</span>" +
      (c.said_yes ? '<span class="pillw">' + c.said_yes + " waiting</span>" : "");
    return d;
  }

  /* ---------- render + modal ---------- */
  function render() {
    if (!MODEL) return;
    el("tt-mo").textContent = MODEL.month;
    renderTabs();
    var body = el("tt-body"); body.innerHTML = "";
    body.appendChild(TAB === "yes" ? renderYes() : TAB === "meetings" ? renderMeetings() :
      TAB === "clients" ? renderClients() : renderMonth());
  }

  function openAdd() {
    var sel = el("f-client");
    sel.innerHTML = (MODEL.clients_all.length ? MODEL.clients_all : MODEL.clients.map(function (c) { return c.name; }))
      .map(function (c) { return '<option>' + esc(c) + "</option>"; }).join("");
    el("f-person").value = ""; el("f-company").value = ""; el("f-date").value = MODEL.today;
    el("tt-ov").classList.add("on");
  }
  el("tt-addbtn").onclick = openAdd;
  el("f-cancel").onclick = function () { el("tt-ov").classList.remove("on"); };
  el("tt-ov").onclick = function (e) { if (e.target === el("tt-ov")) el("tt-ov").classList.remove("on"); };
  el("f-save").onclick = function () {
    var person = el("f-person").value.trim();
    if (!person) { el("f-person").focus(); return; }
    post("/api/team-target/meeting", {client: el("f-client").value, person: person,
      company: el("f-company").value.trim(), date: el("f-date").value || null},
      function () { el("tt-ov").classList.remove("on"); });
  };

  load();
})();
