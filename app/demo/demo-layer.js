/* Demo layer: top bar, explain-mode callouts, and a cross-page spotlight tour. */
(function () {
  var PAGE = location.pathname.split("/").pop() || "index.html";
  var FEATURE = "3859407";
  var isDetail = PAGE === "campaigns.html" && /^#\/c\//.test(location.hash);
  var PK = isDetail ? "campaign" : PAGE.replace(".html", "");

  // ---------- tour script (page, selector, title, body) ----------
  var STEPS = [
    ["deliverability.html", "#ah-databar", "Every number, one place", "Sent, replies, interested, meetings and bounces for the last 30 days, pulled from the sending platform and the inbox every hour. This is Navreo's own outbound, live, not a mock-up."],
    ["deliverability.html", "#ah-filterbar", "One click to scope", "Client chips and 7, 14 or 30 day windows. Our team sees every client side by side. You get the same page scoped to you."],
    ["deliverability.html", "#lane-improve", "Where can we improve the most?", "The funnel finds the single step losing the most people and says what we are doing about it. That becomes this week's optimisation."],
    ["deliverability.html", "#lane-leads", "Lead runway", "How many prospects are queued, how fast they burn, and the date each campaign runs dry. Top-ups happen before that date, not after."],
    ["deliverability.html", "#lane-replies", "Which campaigns and messages win", "Every campaign ranked, with dying ones flagged and the winning offer named. Same table you get in your weekly report."],
    ["deliverability.html", "#lane-interested", "Who actually replies", "Interested replies cut by job title and company size, so the next list pull leans toward the people who say yes."],
    ["deliverability.html", "#lane-meetings", "From interested to booked", "Meetings, where they came from, and the time between reply and first response. Slow follow-up is the leak we watch hardest."],
    ["campaigns.html", "#campaign-rows", "Every campaign, one scorecard", "One row per campaign with the same numbers: sends, reply rate, positives, sends per positive, bounce. Colour means the same thing on every screen."],
    ["campaigns.html#/c/" + FEATURE, "#hdr-dial", "One campaign, at a glance", "How far through the list we are and whether it is working, in one sentence. Identical layout on every campaign so you can compare in seconds."],
    ["campaigns.html#/c/" + FEATURE, "#gv-card", "The whole picture", "Sends, replies, positives and progress over the window, reconciled with lifetime totals. Nothing is estimated; a missing number shows as missing."],
    ["campaigns.html#/c/" + FEATURE, "#messaging-root", "Which message is winning", "The actual text prospects received, per variant, with sends and positives. A version only gets a ruling after a fair test, never on a lucky first hundred."],
    ["campaigns.html#/c/" + FEATURE, "#leads-grid", "Every lead, every step", "Who we emailed, which step they are on, and what happened. Suppressed people (your clients, past replies, do-not-contact) never enter."],
    ["campaigns.html#/c/" + FEATURE, "#changelog-root", "Change log", "Every change our team or the platform made to this campaign, with the reason. Nothing changes silently."],
    ["mailboxes-hub.html", "#sec-heat", "The engine underneath", "Each sending domain against each check we run, hourly. One red cell is one domain; a red column is a platform problem we catch before it reaches you."],
    ["mailboxes-hub.html", "#sec-mgr", "Inbox and domain manager", "Warm-up, reconnects, bounce, blacklist and signature views. Mailboxes that dip are rested with a real due-back date and a replacement steps in."],
    ["mailboxes-hub.html", "#sec-tags", "Performance by mailbox group", "Provider and domain groups compared like message variants. Volume moves toward the groups that land."],
    ["setter.html?share=demo", "#inboxList", "Replies, sorted within minutes", "Every reply is read and categorised. Interested ones get a drafted response in your voice. This is the exact view you open from a private link, no login."],
    ["setter.html?share=demo", "#inboxRight", "You approve, the setter drafts", "Edit, regenerate or approve. Approve stays locked until you choose what happens if they go quiet, because that is where meetings are won."],
    ["report.html?share=demo", "#rp-verdict", "Your weekly report", "Same numbers as the dashboard, scoped to your dates, with a plain verdict at the top. Sent every Monday to Slack and saved in your portal."],
    ["report.html?share=demo", "#lane-win", "What won this week", "Winning campaigns and the offer behind them, so you always know which message is earning the meetings."],
    ["report.html?share=demo", "#lane-who", "Who replied", "The people who answered, quoted, with a link to each. Not a summary, the actual words."],
    ["index.html#access", "#access", "What you get", "Live dashboard, the replies view, weekly reports, a portal and a shared Slack channel. One private link each, no logins."]
  ];

  // ---------- explain callouts (selector -> text) ----------
  var EXPLAIN = {
    deliverability: {
      "#ah-databar": "<b>The four numbers we are judged on</b>, plus bounces. Each carries a comparison to the previous window so a dip shows the day it starts.",
      "#lane-improve": "The step highlighted in orange is losing the most people. It becomes this week's optimisation and appears in your Monday report as <b>what we're doing about it</b>.",
      "#lane-leads": "<b>Runway</b> is how many sending days of leads remain. Top-ups are scheduled before the run-out date so a good campaign never goes quiet.",
      "#lane-sent": "Sends per day against capacity, with weekday pattern and bounce. Bounce above 3% pauses a campaign automatically.",
      "#lane-replies": "Campaigns ranked by sends per positive. <b>Under 1,000 is strong, over 2,500 needs a copy or list change.</b> Dying campaigns are flagged before they waste sends.",
      "#lane-interested": "Interested replies by role and company size. <b>The people who reply decide who we email next.</b>",
      "#lane-meetings": "Meetings booked and the reply-to-response wait. Under 15 minutes in business hours is the target."
    },
    campaigns: {
      "#campaign-rows": "One row per campaign across every workspace we run. <b>Sends per positive</b> is the number we run the business on. Click a row to open it."
    },
    campaign: {
      "#hdr-dial": "How much of the list has been worked, and the verdict. A campaign is only judged after a fair test of 1,000+ sends.",
      "#messaging-root": "The real text a prospect received, per variant, never the template. Winners scale automatically inside the rules you set at onboarding; copy changes wait for your yes.",
      "#leads-grid": "Every person we emailed, their step and outcome. <b>Suppressed</b> means people we deliberately never email: your clients, past replies, your do-not-contact list.",
      "#changelog-root": "Everything that changed on this campaign and why, whether a person or the platform did it."
    },
    "mailboxes-hub": {
      "#sec-heat": "Every sending domain against every check: SPF, DKIM, DMARC, blacklist, bounce, reply. Checked hourly across all clients.",
      "#sec-mgr": "Each provider gets its own daily cap per mailbox: <b>Google 20, Microsoft 2, SMTP 15.</b> Low caps across many mailboxes is how we send at volume without any inbox looking like a bulk sender.",
      "#sec-tags": "Mailbox groups compared the same way we compare message variants. Underperforming groups lose volume after three weeks."
    },
    setter: {
      "#inboxList": "Every reply, categorised within minutes. <b>Needs review</b> means a draft is waiting for you. Not-now replies are re-contacted on the date they gave, automatically.",
      "#inboxRight": "The draft is written in your voice from your training answers. <b>Approve is locked until you pick a follow-up.</b> Every edit teaches the setter."
    },
    report: {
      "#rp-verdict": "One sentence first. Same numbers as the dashboard, pinned to the report's exact dates.",
      "#lane-win": "Winning campaigns and the offer behind them for this week only, never lifetime totals dressed up as weekly.",
      "#lane-who": "The actual replies, quoted, with the person's name linked."
    }
  };

  // ---------- top bar ----------
  document.body.classList.add("nv-demo");
  var bar = document.createElement("div"); bar.id = "nv-bar";
  bar.innerHTML = '<b>Inside Navreo</b><span class="tag">Demo on fixed data</span><span class="grow"></span>' +
    '<button id="nv-explain" aria-pressed="false">Explain mode</button>' +
    '<button id="nv-tour" class="pri">Show me around</button>' +
    '<a href="' + (PAGE === "index.html" ? "#" : "index.html") + '">Overview</a>';
  document.body.appendChild(bar);

  // ---------- explain ----------
  function applyExplain() {
    var map = EXPLAIN[PK] || {};
    Object.keys(map).forEach(function (sel) {
      var el = document.querySelector(sel);
      if (!el || el.__nvEx) return;
      var ex = document.createElement("div"); ex.className = "nv-ex"; ex.innerHTML = map[sel];
      el.insertAdjacentElement("afterend", ex); el.__nvEx = ex;
    });
  }
  function setExplain(on) {
    document.body.classList.toggle("nv-explain", on);
    document.getElementById("nv-explain").setAttribute("aria-pressed", on);
    try { localStorage.setItem("nv-explain", on ? "1" : "0"); } catch (e) {}
    if (on) applyExplain();
  }
  document.getElementById("nv-explain").onclick = function () { setExplain(!document.body.classList.contains("nv-explain")); };
  try { if (localStorage.getItem("nv-explain") === "1") setExplain(true); } catch (e) {}
  setInterval(function () { if (document.body.classList.contains("nv-explain")) applyExplain(); }, 1500);

  // ---------- tour ----------
  var spot = document.createElement("div"); spot.id = "nv-spot"; document.body.appendChild(spot);
  var card = document.createElement("div"); card.id = "nv-card";
  card.innerHTML = '<div class="st" id="nv-st"></div><h3 id="nv-t"></h3><p id="nv-b"></p><div class="bar"><button class="x" id="nv-exit">Exit tour</button><button class="b" id="nv-prev">Back</button><button class="b p" id="nv-next">Next</button></div>';
  document.body.appendChild(card);
  var hi = null, si = -1;
  function pageOf(step) { return step[0]; }
  function samePage(target) {
    var t = target.split("#")[0].split("?")[0];
    var hash = target.indexOf("#") >= 0 ? "#" + target.split("#")[1] : "";
    if (t !== PAGE) return false;
    if (hash && location.hash !== hash) return false;
    if (!hash && PAGE === "campaigns.html" && /^#\/c\//.test(location.hash)) return false;
    return true;
  }
  function gotoStep(i) {
    if (i < 0 || i >= STEPS.length) { endTour(); return; }
    var s = STEPS[i];
    try { sessionStorage.setItem("nv-tour", String(i)); } catch (e) {}
    if (!samePage(pageOf(s))) {
      var target = pageOf(s);
      if (target.split("#")[0].split("?")[0] === PAGE && target.indexOf("#") >= 0) { location.hash = "#" + target.split("#")[1]; si = i; setTimeout(function () { showWhenReady(i); }, 300); return; }
      location.href = "" + target;
      return;
    }
    si = i; showWhenReady(i);
  }
  function showWhenReady(i, tries) {
    tries = tries || 0;
    var el = document.querySelector(STEPS[i][1]);
    if ((!el || el.offsetHeight < 8) && tries < 60) { setTimeout(function () { showWhenReady(i, tries + 1); }, 250); return; }
    if (!el) { gotoStep(i + 1); return; }
    if (hi) hi.classList.remove("nv-hi"); hi = el; el.classList.add("nv-hi");
    el.scrollIntoView({ block: "center" });
    setTimeout(place, 150);
  }
  function place() {
    if (si < 0) return;
    var el = document.querySelector(STEPS[si][1]); if (!el) return;
    var r = el.getBoundingClientRect();
    spot.style.cssText = "display:block;left:" + (r.left - 8) + "px;top:" + (r.top - 8) + "px;width:" + (r.width + 16) + "px;height:" + (r.height + 16) + "px";
    document.getElementById("nv-st").textContent = "Step " + (si + 1) + " of " + STEPS.length;
    document.getElementById("nv-t").textContent = STEPS[si][2];
    document.getElementById("nv-b").textContent = STEPS[si][3];
    document.getElementById("nv-prev").disabled = si === 0;
    document.getElementById("nv-next").textContent = si === STEPS.length - 1 ? "Finish" : "Next";
    card.style.display = "block";
    var cw = 350, ch = card.offsetHeight, left = r.right + 16, top = Math.max(56, r.top);
    if (left + cw > window.innerWidth - 12) { left = Math.max(12, Math.min(r.left, window.innerWidth - cw - 12)); top = r.bottom + 16; }
    if (top + ch > window.innerHeight - 12) { top = Math.max(56, r.top - ch - 16); if (top + ch > window.innerHeight - 12) top = window.innerHeight - ch - 12; }
    card.style.left = left + "px"; card.style.top = top + "px";
  }
  function endTour() { si = -1; spot.style.display = "none"; card.style.display = "none"; if (hi) hi.classList.remove("nv-hi"); try { sessionStorage.removeItem("nv-tour"); } catch (e) {} }
  document.getElementById("nv-next").onclick = function () { gotoStep(si + 1); };
  document.getElementById("nv-prev").onclick = function () { gotoStep(si - 1); };
  document.getElementById("nv-exit").onclick = endTour;
  document.getElementById("nv-tour").onclick = function () { gotoStep(0); };
  window.addEventListener("resize", place); window.addEventListener("scroll", place, { passive: true });
  document.addEventListener("keydown", function (e) { if (si < 0) return; if (e.key === "Escape") endTour(); if (e.key === "ArrowRight") gotoStep(si + 1); if (e.key === "ArrowLeft") gotoStep(si - 1); });
  window.addEventListener("hashchange", function () { if (si >= 0) setTimeout(place, 200); });
  // resume a tour that crossed a page boundary
  try {
    var saved = sessionStorage.getItem("nv-tour");
    if (saved !== null) { var i = parseInt(saved, 10); if (samePage(pageOf(STEPS[i]))) { si = i; setTimeout(function () { showWhenReady(i); }, 600); } }
  } catch (e) {}
  if (new URLSearchParams(location.search).get("tour") === "1") setTimeout(function () { gotoStep(0); }, 800);

  // ---------- page nudges ----------
  if (PAGE === "deliverability.html") {
    // default the client scope to Navreo so the tab reads as one client's 30 days
    var n = 0; var t = setInterval(function () {
      n++; var chips = document.querySelectorAll("#ah-chips button, #ah-chips .chip, #ah-chips [data-client]");
      var nav = Array.prototype.find.call(chips, function (c) { return /^\s*Navreo\s*$/.test(c.textContent); });
      if (nav) { if (!/on|active|sel/.test(nav.className) && nav.getAttribute("aria-pressed") !== "true") nav.click(); clearInterval(t); }
      if (n > 40) clearInterval(t);
    }, 300);
  }
  // demo-only: make external links harmless
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]"); if (!a) return;
    var h = a.getAttribute("href") || "";
    if (/smartlead|heyreach|notion\.site|slack\.com|calendly|linkedin/.test(h)) { e.preventDefault(); }
  }, true);
})();
