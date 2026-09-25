/* Demo layer: top bar, explain-mode callouts, and a cross-page spotlight tour.
   Voice: our team showing how we run every client's campaigns. Example client: Acme. */
(function () {
  var PAGE = location.pathname.split("/").pop() || "index.html";
  var FEATURE = "3859407";
  var isDetail = PAGE === "campaigns.html" && /^#\/c\//.test(location.hash);
  var PK = isDetail ? "campaign" : PAGE.replace(".html", "");

  var STEPS = [
    ["deliverability.html", "#ah-databar", "Every client, every number, one page", "This is the page our team opens first each morning: sends, replies, interested, meetings and bounces across every campaign we run, refreshed hourly from the sending platform and the inbox. Acme is the client selected here."],
    ["deliverability.html", "#ah-filterbar", "One click to scope", "We see every client side by side and flip between 7, 14 and 30 days. Each client gets this same page scoped to their own account."],
    ["deliverability.html", "#lane-improve", "Where can we improve the most?", "For every client we find the single funnel step losing the most people and say what we are doing about it. That becomes the week's optimisation."],
    ["deliverability.html", "#lane-leads", "Lead runway", "How many prospects are queued per campaign, how fast they burn, and the date each runs dry. We top up before that date, never after."],
    ["deliverability.html", "#lane-replies", "Which campaigns and messages win", "Every campaign ranked, dying ones flagged, the winning offer named. This is the table behind every weekly report we send."],
    ["deliverability.html", "#lane-interested", "Who actually replies", "Interested replies cut by job title and company size, so each client's next list pull leans toward the people who say yes."],
    ["deliverability.html", "#lane-meetings", "From interested to booked", "Meetings and the wait between a reply and our first response. Slow follow-up is the leak we watch hardest across all clients."],
    ["campaigns.html", "#campaign-rows", "Every campaign, one scorecard", "One row per campaign across every client, same numbers on each: sends, reply rate, positives, sends per positive, bounce. Colour means the same thing everywhere."],
    ["campaigns.html#/c/" + FEATURE, "#hdr-dial", "One campaign, at a glance", "How far through the list we are and whether it is working, in one sentence. Identical layout for every campaign so we can compare in seconds."],
    ["campaigns.html#/c/" + FEATURE, "#gv-card", "The whole picture", "Sends, replies, positives and progress over the window, reconciled with lifetime totals. Nothing is estimated; a missing number shows as missing."],
    ["campaigns.html#/c/" + FEATURE, "#messaging-root", "Which message is winning", "The actual text prospects received, per variant, with sends and positives. We only rule on a version after a fair test, never on a lucky first hundred."],
    ["campaigns.html#/c/" + FEATURE, "#leads-grid", "Every lead, every step", "Who we emailed, which step they are on, what happened. Suppressed people (the client's customers, past replies, do-not-contact) never enter."],
    ["campaigns.html#/c/" + FEATURE, "#changelog-root", "Change log", "Every change our team or the platform made to this campaign, with the reason. Nothing changes silently on any client account."],
    ["mailboxes-hub.html", "#sec-heat", "The engine underneath", "Every client's sending domains against every check we run, hourly. One red cell is one domain; a red column is a platform problem we catch before any client feels it."],
    ["mailboxes-hub.html", "#sec-mgr", "Inbox and domain manager", "Warm-up, reconnects, bounce, blacklist and signature views across the whole fleet. Mailboxes that dip are rested with a real due-back date and a replacement steps in."],
    ["mailboxes-hub.html", "#sec-tags", "Performance by mailbox group", "Provider and domain groups compared the way we compare message variants. Volume moves toward the groups that land."],
    ["setter.html?share=demo", "#inboxList", "Replies, sorted within minutes", "Every reply on every account is read and categorised. Interested ones get a drafted response in the client's voice. Clients open exactly this view from a private link, no login."],
    ["setter.html?share=demo", "#inboxRight", "The client approves, the setter drafts", "Edit, regenerate or approve. Approve stays locked until a follow-up is chosen, because that is where meetings are won."],
    ["report.html?share=demo", "#rp-verdict", "The weekly report", "Same numbers as the dashboard, pinned to the week, with a plain verdict at the top. Every client gets this on Monday, in Slack and in their portal."],
    ["report.html?share=demo", "#lane-win", "What won this week", "Winning campaigns and the offer behind them, so the client always knows which message is earning the meetings."],
    ["report.html?share=demo", "#lane-who", "Who replied", "The people who answered, quoted, with a link to each. Not a summary, the actual words."],
    ["strategy.html?share=demo#/r/acme-recontact-20260911-r7k2", "#side", "How we share campaign copy", "Every campaign we propose for a client lands on one board: the idea, who it targets, how many people we can reach, and the email itself. Clients open it from a private link, no login."],
    ["strategy.html?share=demo#/r/acme-recontact-20260911-r7k2", "#work", "Edit in place, then sign off", "The client reads the exact email, edits any line directly, and the copy checks update live: sign-off present, no spam words, opt-out line. Nothing sends until they paste the sign-off line back to us."],
    ["index.html#access", "#access", "What every client gets", "Live dashboard, the replies view, weekly reports, campaign copy for sign-off, a portal and a shared Slack channel. One private link each, no logins."]
  ];

  var EXPLAIN = {
    deliverability: {
      "#ah-databar": "<b>The five numbers we judge every client on.</b> Each carries a comparison to the previous window so a dip shows the day it starts, on any account.",
      "#lane-improve": "The step highlighted in orange is losing the most people. It becomes that client's optimisation for the week and appears in their Monday report as <b>what we're doing about it</b>.",
      "#lane-leads": "<b>Runway</b> is how many sending days of leads remain. We schedule top-ups before the run-out date so a good campaign never goes quiet.",
      "#lane-sent": "Sends per day against capacity, with weekday pattern and bounce. Bounce above 3% pauses a campaign automatically, on every account.",
      "#lane-replies": "Campaigns ranked by sends per positive. <b>Under 1,000 is strong, over 2,500 needs a copy or list change.</b> We flag dying campaigns before they waste sends.",
      "#lane-interested": "Interested replies by role and company size. <b>The people who reply decide who we email next.</b>",
      "#lane-meetings": "Meetings booked and the reply-to-response wait. Under 15 minutes in business hours is our target across all clients."
    },
    campaigns: {
      "#campaign-rows": "One row per campaign across every client we run. <b>Sends per positive</b> is the number we manage the whole book on. Click a row to open it."
    },
    campaign: {
      "#hdr-dial": "How much of the list has been worked, and the verdict. We only judge a campaign after a fair test of 1,000+ sends.",
      "#messaging-root": "The real text a prospect received, per variant, never the template. Winners scale automatically inside the rules agreed at onboarding; copy changes wait for the client's yes.",
      "#leads-grid": "Every person we emailed, their step and outcome. <b>Suppressed</b> means people we deliberately never email: the client's customers, past replies, their do-not-contact list.",
      "#changelog-root": "Everything that changed on this campaign and why, whether a person or the platform did it."
    },
    "mailboxes-hub": {
      "#sec-heat": "Every client's sending domains against every check: SPF, DKIM, DMARC, blacklist, bounce, reply. Checked hourly across the whole fleet.",
      "#sec-mgr": "Each provider gets its own daily cap per mailbox: <b>Google 20, Microsoft 2, SMTP 15.</b> Low caps across many mailboxes is how we send at volume without any inbox looking like a bulk sender.",
      "#sec-tags": "Mailbox groups compared the same way we compare message variants. Underperforming groups lose volume after three weeks."
    },
    setter: {
      "#inboxList": "Every reply on every account, categorised within minutes. <b>Needs review</b> means a draft is waiting for the client. Not-now replies are re-contacted on the date they gave, automatically.",
      "#inboxRight": "The draft is written in the client's voice from their training answers. <b>Approve is locked until a follow-up is picked.</b> Every edit teaches the setter."
    },
    strategy: {
      "#side": "One board per client, one row per campaign idea. <b>The number on each row is real people we can reach</b>, netted against everyone the client has already contacted. Pick a row to read its email.",
      "#work": "The exact email a prospect would receive, with the variables we fill per person. <b>Click any line to edit it.</b> The checks below update as you type: sign-off, spam words, opt-out line. Your one-line sign-off at the bottom is what puts a campaign into build.",
      "#lg-phrase": "This line is the client's sign-off. They paste it into Slack or the portal and the campaign goes to build. <b>No campaign sends without it.</b>"
    },
    report: {
      "#rp-verdict": "One sentence first. Same numbers as the dashboard, pinned to the report's exact dates.",
      "#lane-win": "Winning campaigns and the offer behind them for this week only, never lifetime totals dressed up as weekly.",
      "#lane-who": "The actual replies, quoted, with the person's name linked."
    }
  };

  document.body.classList.add("nv-demo");
  var bar = document.createElement("div"); bar.id = "nv-bar";
  bar.innerHTML = '<b>Inside the platform</b><span class="tag">Demo · example client Acme</span><span class="grow"></span>' +
    '<button id="nv-explain" aria-pressed="false">Explain mode</button>' +
    '<button id="nv-tour" class="pri">Show me around</button>' +
    '<a href="index.html">Overview</a>';
  document.body.appendChild(bar);

  function applyExplain() {
    var map = EXPLAIN[PK] || {};
    Object.keys(map).forEach(function (sel) {
      var el = document.querySelector(sel);
      if (!el || (el.__nvEx && el.__nvEx.isConnected)) return;
      var ex = document.createElement("div"); ex.className = "nv-ex"; ex.innerHTML = map[sel];
      // In a flex-row / grid parent a sibling note becomes its own full-height column
      // (and outlives a hidden pane), so put it inside the element instead.
      var ps = el.parentElement && getComputedStyle(el.parentElement);
      var inRow = ps && ((ps.display.indexOf("flex") > -1 && ps.flexDirection.indexOf("row") === 0) || ps.display.indexOf("grid") > -1);
      el.insertAdjacentElement(inRow ? "afterbegin" : "afterend", ex); el.__nvEx = ex;
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
      location.href = target;
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
  try {
    var saved = sessionStorage.getItem("nv-tour");
    if (saved !== null) { var i = parseInt(saved, 10); if (samePage(pageOf(STEPS[i]))) { si = i; setTimeout(function () { showWhenReady(i); }, 600); } }
  } catch (e) {}
  if (new URLSearchParams(location.search).get("tour") === "1") setTimeout(function () { gotoStep(0); }, 800);

  if (PAGE === "deliverability.html") {
    var n = 0; var t = setInterval(function () {
      n++; var chips = document.querySelectorAll("#ah-chips button, #ah-chips .chip, #ah-chips [data-client]");
      var acme = Array.prototype.find.call(chips, function (c) { return /^\s*Acme\s*$/.test(c.textContent); });
      if (acme) { if (!/on|active|sel/.test(acme.className) && acme.getAttribute("aria-pressed") !== "true") acme.click(); clearInterval(t); }
      if (n > 40) clearInterval(t);
    }, 300);
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]"); if (!a) return;
    var h = a.getAttribute("href") || "";
    if (/smartlead|heyreach|notion\.site|slack\.com|calendly|linkedin/.test(h)) { e.preventDefault(); }
  }, true);
})();
