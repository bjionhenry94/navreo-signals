/* Subsequence Effectiveness — shared mock fixture + renderers for p1..p3.
   Zero API calls. One shared dataset, two states (off-benchmark + healthy) so the
   colour system is visible. Benchmarks: reply >= 12%, book-call >= 5%. */
(function (global) {
  "use strict";

  var T_REPLY = 12.5, T_BOOK = 5;               // benchmarks: positive-reply >=12.5%, book-call >=5%
  var DATA = {
    off: { n: 1240, reply: 10, replyN: 124, book: 3, bookN: 37 },   // copy-problem client
    ok:  { n: 1240, reply: 15, replyN: 186, book: 6, bookN: 74 }    // healthy client
  };

  function tone(v, t) { return v >= t ? "green" : v >= t * 0.75 ? "amber" : "red"; }
  function word(t) { return t === "green" ? "good" : t === "red" ? "bad" : "warn"; }
  function chip(tn) {                            // plain-language severity — no math, no "pts", no colour-guessing
    var t = tn === "green" ? "On target" : tn === "amber" ? "Just under" : "Well under";
    return '<span class="m5-chip c-' + tn + '">' + t + '</span>';
  }

  /* ── the two live siblings — identical in every prototype ── */
  function whoCard() {
    return '<div class="card-kick">Who\'s replying <span class="soft">· 14 interested with a known title · whole book</span></div>' +
      '<div class="brows num">' +
        '<div class="brow"><span class="lbl strong">Founders and CEOs</span><div class="fill orange" style="width:100%"></div><span class="val">8</span></div>' +
        '<div class="brow"><span class="lbl">Marketing and Gro…</span><div class="fill" style="width:50%"></div><span class="val">4</span></div>' +
        '<div class="brow"><span class="lbl">Sales leaders</span><div class="fill" style="width:25%"></div><span class="val">2</span></div>' +
      '</div>' +
      '<div class="subline" style="margin-top:8px"><b>Company size</b> (9 known): 11–50 6 · 51–200 3</div>' +
      '<div class="take"><span class="arr">→</span><span>Aim new lists at founders and ceos — most of Navreo\'s real yeses.</span></div>';
  }
  function fastCard() {
    return '<div class="card-kick">How fast we answer <span class="soft">· Navreo · benchmark 15 min</span></div>' +
      '<div class="bignum warn num">7 h 51 m</div>' +
      '<div class="subline">median answer time · 0 in 100 answered under 15 min · 51 answered</div>' +
      '<div class="take"><span class="arr">→</span><span>Over the 15-minute benchmark — answer faster to book more.</span></div>';
  }

  /* ── P1 · twin benchmark meters ── */
  function renderP1(d) {
    var rt = tone(d.reply, T_REPLY), bt = tone(d.book, T_BOOK);
    function meter(lab, val, target, tn, axis) {
      var w = Math.min(100, val / axis * 100), tl = Math.min(100, target / axis * 100);
      var gap = val < target ? '<div class="m5-gap" style="left:' + w + '%;width:' + (tl - w) + '%"></div>' : "";
      return '<div class="m5-meter">' +
        '<div class="m5-mtop"><span class="m5-mlab">' + lab + '</span>' +
          '<span class="m5-right"><span class="m5-mval tone-' + tn + '">' + val + '%</span>' + chip(tn) + '</span></div>' +
        '<div class="m5-track"><div class="m5-fill bg-' + tn + '" style="width:' + w + '%"></div>' + gap +
          '<div class="m5-tick" style="left:' + tl + '%"></div></div>' +
        '<div class="m5-axis"><span class="m5-ticklab" style="left:' + tl + '%">target ' + target + '%</span></div></div>';
    }
    var ok = rt === "green" && bt === "green";
    var take = ok ? "Follow-ups are pulling their weight."
      : (rt !== "green" && bt !== "green" ? "Both under target — booked calls leak most. Rewrite the follow-up that asks for the call."
        : (bt !== "green" ? "Booked calls are under — rewrite the follow-up that asks for the call."
          : "Positive replies are under — the follow-up needs a sharper opener."));
    return '<div class="card-kick">How effective are our follow-ups <span class="soft">· ' + d.n.toLocaleString() + ' in follow-ups</span></div>' +
      '<div style="margin-top:8px">' + meter("Positive replies", d.reply, T_REPLY, rt, 20) + meter("Booked calls", d.book, T_BOOK, bt, 10) + '</div>' +
      '<div class="take"><span class="arr">→</span><span>' + take + '</span></div>';
  }

  /* ── P2 · one verdict + one proof ── */
  function renderP2(d) {
    var bt = tone(d.book, T_BOOK), rt = tone(d.reply, T_REPLY);
    var ok = bt === "green" && rt === "green";
    var take = ok ? "Follow-ups are doing their job." : "Rewrite the follow-up that asks for the call.";
    return '<div class="card-kick">How effective are our follow-ups <span class="soft">· ' + d.n.toLocaleString() + ' in follow-ups</span></div>' +
      '<div class="m5-herorow"><span class="m5-herolab">Booked a call</span>' + chip(bt) + '</div>' +
      '<div class="bignum ' + word(bt) + ' num">' + d.book + '%</div>' +
      '<div class="m5-sub2">target ' + T_BOOK + '% · ' + d.bookN + ' booked</div>' +
      '<div class="m5-proof">' + chip(rt) + '<span>Positive replies <b>' + d.reply + '%</b> · target ' + T_REPLY + '%</span></div>' +
      '<div class="take"><span class="arr">→</span><span>' + take + '</span></div>';
  }

  /* ── P3 · gap-to-target scorecard ── */
  function renderP3(d) {
    function row(name, val, target) {
      var tn = tone(val, target);
      return '<div class="m5-scrow">' +
        '<div class="m5-scline"><span class="m5-scname">' + name + '</span>' + chip(tn) + '</div>' +
        '<div class="m5-scnums"><span class="m5-scbig tone-' + tn + '">' + val + '%</span><span class="m5-sctarget">target ' + target + '%</span></div></div>';
    }
    var bt = tone(d.book, T_BOOK), rt = tone(d.reply, T_REPLY);
    var ok = bt === "green" && rt === "green";
    // weak link = worse relative to its own target (ratio), so all 3 cards agree
    var take = ok ? "Follow-ups are ahead of target."
      : ((d.book / T_BOOK) <= (d.reply / T_REPLY) ? "Booked calls are the weak link — rewrite the follow-up that asks for the call."
        : "Positive replies are the weak link — sharpen the follow-up's opener.");
    return '<div class="card-kick">How effective are our follow-ups <span class="soft">· ' + d.n.toLocaleString() + ' in follow-ups</span></div>' +
      '<div style="margin-top:2px">' + row("Positive replies", d.reply, T_REPLY) + row("Booked calls", d.book, T_BOOK) + '</div>' +
      '<div class="take"><span class="arr">→</span><span>' + take + '</span></div>';
  }

  var RENDER = { p1: renderP1, p2: renderP2, p3: renderP3 };
  var NAMES = { p1: "Benchmark meters", p2: "One verdict, one proof", p3: "Gap-to-target scorecard" };

  /* Build the full lane-5 row with the chosen variant as the third card + a state toggle.
     Initial state from ?s=off|ok (default off), so each state can be screenshotted. */
  function mountLane(which) {
    var initial = /[?&]s=ok\b/.test(global.location.search) ? "ok" : "off";
    var app = document.getElementById("app");
    app.innerHTML =
      '<div class="previewbar"><span class="lab">Preview this client as</span>' +
        '<div class="seg" id="seg"><button data-s="off">⚠&nbsp; Off-benchmark</button><button data-s="ok">✓&nbsp; Healthy</button></div>' +
        '<span class="lab" style="letter-spacing:0;text-transform:none;font-weight:500;color:var(--ink-3)">— only the third card changes.</span></div>' +
      '<div class="ah"><section class="lane"><span class="node num">5</span>' +
        '<div class="lane-head"><h2 class="lane-q">Who actually replies?</h2><span class="lane-tag num">Pipeline · Interested · 162</span></div>' +
        '<div class="cards c233"><div class="acard" id="who"></div><div class="acard" id="fast"></div><div class="acard" id="third"></div></div>' +
      '</section></div>';
    function paint(state) {
      document.getElementById("who").innerHTML = whoCard();
      document.getElementById("fast").innerHTML = fastCard();
      document.getElementById("third").innerHTML = RENDER[which](DATA[state]);
      var seg = document.getElementById("seg");
      seg.querySelectorAll("button").forEach(function (x) { x.classList.toggle("on", x.dataset.s === state); });
    }
    document.getElementById("seg").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (b) paint(b.dataset.s);
    });
    paint(initial);
  }

  global.SUBSEQ = { mountLane: mountLane, RENDER: RENDER, NAMES: NAMES, DATA: DATA };
})(window);
