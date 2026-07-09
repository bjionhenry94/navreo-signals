/* Deliverability tab — mock-data recreation of the standalone Navreo audit dashboard,
   restyled to native navreo-signals tokens. Everything lives in this one file, wrapped
   in an IIFE. The ONLY global this file adds is window.renderDeliverability.
   Zero fetch/XHR/sendBeacon — all state lives in memory + sessionStorage. */
(function () {
  "use strict";

  /* ============================================================
     0. Small utilities
     ============================================================ */
  const esc = window.esc || ((s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));
  const fmtN = window.fmt || ((n) => (n === null || n === undefined || isNaN(n)) ? "–" : Number(n).toLocaleString("en-GB"));
  const $id = (id) => document.getElementById(id);
  const todayISO = () => new Date().toISOString().slice(0, 10);
  function addDays(iso, n) { const d = new Date(iso + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
  function daysUntil(iso) { const a = new Date(todayISO() + "T00:00:00Z"), b = new Date(iso + "T00:00:00Z"); return Math.round((b - a) / 864e5); }
  function deepClone(o) { return JSON.parse(JSON.stringify(o)); }
  function uid(prefix) { return prefix + "_" + Math.random().toString(36).slice(2, 10); }
  function groupCount(arr, keyFn) { const m = {}; (arr || []).forEach((x) => { const k = keyFn(x); if (k == null) return; m[k] = (m[k] || 0) + 1; }); return m; }

  /* Plain-English glossary — one short muted line surfaced under jargon-heavy
     to-do actions and stat tiles (fix: testers couldn't parse the abbreviations). */
  const JARGON_DICT = [
    // Specific phrases first — these disambiguate the two SPF/DKIM/DMARC tiles,
    // which used to both fall through to the same generic line (fix: duplicated
    // tile subtitle — testers couldn't tell "missing" apart from "enforcing").
    { re: /missing\s*spf\s*\/?\s*dkim\s*\/?\s*dmarc/i, txt: "Authentication records missing — mail may land in spam." },
    { re: /dmarc\s*enforcing/i, txt: "Domains whose DMARC policy actively rejects/quarantines fakes." },
    // Fix #3a (holdout VA): extended past the bare definition — "SURBL" vs
    // "Spamhaus" read as two mystery names with no relationship, so both
    // glossary entries (this one feeds SURBL AND Spamhaus via plainLineFor)
    // now spell out that they're independent lists with the same remediation.
    { re: /surbl|spamhaus/i, txt: "Industry spam blocklists that mailbox providers check. SURBL and Spamhaus are two independent blocklists; being on either hurts delivery. The fix is the same for both: pause, clean the cause, then request removal from each list separately." },
    { re: /mxtoolbox/i, txt: "A free external checker for domain/blacklist status." },
    { re: /replace\s*\(young domain\)|young domain/i, txt: "Domain too new to be worth delisting — cheaper to replace." },
    { re: /\bdelisting\b/i, txt: "Asking a blocklist to remove your domain after you've fixed the cause." },
    { re: /spf\s*\/?\s*dkim\s*\/?\s*dmarc|\bspf\b|\bdkim\b|\bdmarc\b/i, txt: "Email authentication records that stop you landing in spam." },
    { re: /nameserver/i, txt: "Your domain's DNS is pointing somewhere unexpected." },
    { re: /catch-all/i, txt: "Domain accepts any address — risky to email." },
    { re: /reply-guard/i, txt: "Anyone who replied is automatically kept, never deleted." },
    { re: /oauth/i, txt: "Connected via Google/Microsoft sign-in." },
    { re: /listmint|millionverifier|\bmv\b/i, txt: "Email verification services (e.g. MillionVerifier) — check which leads are safe to email." },
    // Word-bounded + excludes "warmup noise" (fix #6): the previous /resting|warm.../
    // pattern matched the bare substring "warmup"/"resting" ANYWHERE in a tile's
    // label+note, so it fired on tiles that only mention warmup in passing (e.g.
    // "Blocked (real)"'s "+N soft (warmup noise, no action)" note) instead of tiles
    // actually describing the domain-resting/warmup-pause mechanic — testers saw the
    // same "Sending paused while reputation recovers" line under ~5 unrelated tiles.
    { re: /\bresting\b|\bwarm(?:ed|ing)?[\s-]*up\b(?!\s*noise)/i, txt: "Sending paused while reputation recovers." },
    { re: /baseline/i, txt: "Expected daily send volume for this pool." },
  ];
  function plainLineFor(text) {
    const s = String(text || "");
    for (const j of JARGON_DICT) if (j.re.test(s)) return j.txt;
    return null;
  }

  /* Click-popover glossary — a "?" marker inserted right after specific jargon
     WORDS (not whole phrases) wherever they appear in to-do cards, the blacklist
     fold and the delisting modal (fix: the muted plainLineFor() line above only
     ever explains a whole tile/action, so a VA reading a to-do sentence had no way
     to look up just "SURBL" or "delisting" inline). Definitions are pulled
     straight off JARGON_DICT via plainLineFor() with a representative sample —
     single-sourced so the two mechanisms never say something different — but the
     match regex here is deliberately tighter/word-scoped than JARGON_DICT's
     phrase-level regexes (e.g. JARGON_DICT's /resting|warm(?:ed|ing)?[\s-]*up/
     is fine for a whole-line hint but would wrongly tag the word "warming" too). */
  const GLOSS_TERMS = [
    // Listed before the generic SPF/DKIM/DMARC entry below so its more specific,
    // longer match wins at the same start index (fix #5b: technical-details fold
    // coverage) — otherwise "DMARC enforcing" would pop up the generic auth
    // definition instead of the quarantine/reject one.
    // Item 5e: extended with the three policy states so the DMARC-enforcing
    // tile's "?" explains what quarantine/reject/none actually MEAN, not just
    // that enforcement exists.
    { re: /DMARC\s*enforcing/i, txt: "Domains whose DMARC policy actively acts on fakes — none = watch only, quarantine = suspicious mail goes to spam, reject = fakes bounced outright." },
    { re: /SPF\s*\/?\s*DKIM\s*\/?\s*DMARC|DMARC|SPF|DKIM/i, txt: plainLineFor("spf") },
    { re: /SURBL/i, txt: plainLineFor("surbl") },
    { re: /Spamhaus(?:\s*DBL)?/i, txt: plainLineFor("spamhaus") },
    { re: /delisting/i, txt: plainLineFor("delisting") },
    { re: /nameservers?/i, txt: plainLineFor("nameserver") },
    { re: /MXToolbox/i, txt: plainLineFor("mxtoolbox") },
    { re: /catch-all/i, txt: plainLineFor("catch-all") },
    // Covers both the delisting modal's "young (replace-instead) domains" checkbox
    // label and the blacklist advice badge's "REPLACE (young domain)" text (fix #5b).
    { re: /young\s*\(replace-instead\)\s*domains?|replace\s*\(young domain\)/i, txt: plainLineFor("young domain") },
    { re: /resting/i, txt: "Sending paused while reputation recovers." },
    // Defect G: these three tool names show up in to-do action text and the
    // per-campaign verify buttons but had no click-popover definition at all.
    { re: /ListMint/i, txt: "Email verification service — checks which leads are safe to email." },
    { re: /MillionVerifier/i, txt: "Same family as ListMint — a second verification layer." },
    { re: /Hypertide/i, txt: "The mailbox hosting provider — they fix hosting-side blocks." },
    // Defect 6a: three terms testers flagged with no click-popover definition —
    // SMTP/IMAP (technical-details tile), OAuth (shows up in reconnect reason
    // text, e.g. "OAuth token revoked"), and batch baseline (reuses the exact
    // wording already in JARGON_DICT so the muted line and the "?" popover
    // never disagree).
    { re: /SMTP\s*\/?\s*IMAP|\bSMTP\b|\bIMAP\b/i, txt: "The connections used to send and read mail — a fail means the inbox can't send or sync." },
    { re: /OAuth/i, txt: plainLineFor("oauth") },
    { re: /\bbaseline\b/i, txt: plainLineFor("baseline") },
  ];
  const GLOSS_RE = new RegExp(GLOSS_TERMS.map((g) => "(" + g.re.source + ")").join("|"), "gi");
  // Escapes `text` (like esc()) then, in one single pass over the ALREADY-escaped
  // string, wraps every matched glossary word with a clickable "?" superscript.
  // Single-pass (one combined regex) so a later term's match can never land
  // inside markup a previous term already inserted.
  function glossify(text) {
    const escaped = esc(text);
    return escaped.replace(GLOSS_RE, function () {
      const args = Array.prototype.slice.call(arguments, 1, 1 + GLOSS_TERMS.length);
      const idx = args.findIndex((g) => g !== undefined);
      const match = arguments[0];
      const def = idx >= 0 ? GLOSS_TERMS[idx].txt : "";
      if (!def) return match;
      return match + '<sup class="dlv-gloss" data-act="gloss-open" data-def="' + esc(def) + '" title="Click for a plain-English definition">?</sup>';
    });
  }
  // Same clickable "?" marker as glossify() inserts inline, but for spots
  // where the LABEL text itself doesn't literally contain the jargon word
  // (defect 6a: the Warmup tile's label is just "Warmup", and the "Fleet
  // lifecycle" group header doesn't mention warmup at all) — attaches the
  // definition directly rather than relying on a regex match against the
  // visible text.
  function glossMark(def) {
    return ' <sup class="dlv-gloss" data-act="gloss-open" data-def="' + esc(def) + '" title="Click for a plain-English definition">?</sup>';
  }
  const WARMUP_DEF = "Background reputation-building: mailboxes exchange friendly mail so providers trust them.";
  // Item 5c: "batch" is provisioning jargon — surfaced with a "?" in the batch
  // fold header and the best/worst chips, where the word does the most work.
  const BATCH_DEF = "A pool of sender mailboxes provisioned together — usually one client or provider order.";
  // Item 5e: plain-English hover tooltips for the blocked-breakdown category
  // tiles (their labels are raw bounce-category strings from the mock rows).
  const BLOCK_REASON_TIPS = {
    "hosting block": "Provider-side block — the receiving host refuses this sender outright.",
    "spam complaint": "Recipient complaints — people marked these emails as spam.",
    "mailbox full": "Bounce back — the recipient's mailbox is over quota.",
    soft: "Temporary failures (greylisting, DNS blips) — they retry on their own, no action.",
  };

  /* ============================================================
     1. MOCK data — shaped like the real audit blob captured in
        scratchpad/audit-dashboard/*.json, trimmed to demo scale.
     ============================================================ */
  const BATCHES = ["June 2026", "Hypertide (Odd - 2026)", "Amplifyy v1", "Arnic - Temporary", "sender:Bjion Henry", "Navreo Maildoso", "Thunderbird-July", "Client Trial (A)"];

  const DOMAIN_POOL = [
    "weamplifyy.info", "arnicbiz.biz", "navreoops.info", "surgeamplifyy.info", "navreoscale.info",
    "navreogotomarket.biz", "navreostrategy.org", "salesnavreo.info", "navreostrategy.xyz", "gtmnavreo.org",
    "theamplifyylab.info", "navreopipelineengine.info", "gtmnavreo.info", "reachalign.net", "geteasysales.com",
    "navreo.biz", "saleswithnavreo.info", "navreoleads.info", "navreopipeline.info", "navreoconversion.digital",
    "navreogotomarket.info", "getnavreo.biz", "gtmwithnavreo.xyz", "gtmnavreo.com",
  ];

  function buildDomainHealthRows() {
    // 24 domains: 9 flagged for warmup (reply < cutoff), 3 watch, 2 Maildoso, 10 keep-active.
    const spec = [
      ["weamplifyy.info", 624, 472, 2, 0.42, 0, 32, 6.78, false, ["Amplifyy - Hypertide", "Amplifyy v1"]],
      ["arnicbiz.biz", 900, 717, 4, 0.56, 0, 13, 1.81, false, ["Arnic - Temporary"]],
      ["navreoops.info", 624, 495, 3, 0.61, 0, 5, 1.01, false, ["June 2026"]],
      ["surgeamplifyy.info", 624, 473, 3, 0.63, 0, 30, 6.13, false, ["Amplifyy v1"]],
      ["navreoscale.info", 624, 464, 3, 0.65, 0, 6, 1.29, false, ["June 2026", "Hypertide (Odd - 2026)"]],
      ["navreogotomarket.biz", 700, 512, 3, 0.68, 0, 8, 1.42, false, ["Client Trial (A)"]],
      ["navreostrategy.org", 610, 470, 3, 0.72, 0, 4, 0.85, false, ["June 2026"]],
      ["salesnavreo.info", 590, 455, 3, 0.75, 0, 5, 1.02, false, ["sender:Bjion Henry"]],
      ["navreostrategy.xyz", 540, 401, 3, 0.78, 0, 3, 0.62, false, ["Hypertide (Odd - 2026)"]],
      ["gtmnavreo.org", 560, 430, 5, 0.9, 0, 4, 0.71, false, ["June 2026"]],
      ["theamplifyylab.info", 610, 460, 6, 0.95, 1, 5, 0.9, false, ["Amplifyy v1"]],
      ["navreopipelineengine.info", 520, 402, 5, 0.98, 0, 3, 0.6, false, ["Arnic - Temporary"]],
      ["gtmnavreo.info", 890, 660, 12, 1.35, 2, 4, 0.5, true, ["Navreo Maildoso"]],
      ["reachalign.net", 780, 590, 13, 1.67, 3, 3, 0.4, true, ["Navreo Maildoso"]],
      ["geteasysales.com", 1020, 780, 18, 1.76, 4, 6, 0.6, false, ["Client Trial (A)"]],
      ["navreo.biz", 1500, 1120, 27, 1.8, 5, 9, 0.6, false, ["June 2026", "sender:Bjion Henry"]],
      ["saleswithnavreo.info", 640, 480, 12, 1.88, 2, 5, 0.8, false, ["Hypertide (Odd - 2026)"]],
      ["navreoleads.info", 300, 220, 6, 2.0, 1, 2, 0.7, false, ["Thunderbird-July"]],
      ["navreopipeline.info", 260, 190, 5, 1.92, 1, 2, 0.8, false, ["Thunderbird-July"]],
      ["navreoconversion.digital", 980, 740, 21, 2.14, 4, 7, 0.7, false, ["Client Trial (A)"]],
      ["navreogotomarket.info", 210, 150, 4, 1.9, 0, 1, 0.5, false, ["June 2026"]],
      ["getnavreo.biz", 640, 490, 14, 2.19, 3, 3, 0.5, false, ["Arnic - Temporary"]],
      ["gtmwithnavreo.xyz", 1100, 830, 24, 2.18, 4, 6, 0.5, false, ["sender:Bjion Henry"]],
      ["gtmnavreo.com", 720, 540, 16, 2.22, 3, 3, 0.4, false, ["Hypertide (Odd - 2026)"]],
    ];
    return spec.map(([domain, sent, lead, replied, reply_rate, positive, bounced, bounce_rate, maildoso, batches]) => ({
      domain, sent, lead, replied, reply_rate, positive,
      positive_rate: Math.round((positive / Math.max(1, lead)) * 10000) / 100,
      bounced, bounce_rate, maildoso, batches,
    }));
  }

  function dhFlag(d, minSent, cutoff) {
    if (d.maildoso) return "maildoso";
    if (d.sent < minSent) return "ok";
    return d.reply_rate < cutoff ? "warmup" : (d.reply_rate < 1 ? "watch" : "ok");
  }

  function buildInboxRows() {
    const rows = [];
    let id = 90000001;
    const mk = (email, domain, batch, extra) => rows.push(Object.assign({
      id: id++, email, domain, provider: "OAuth/Outlook", maildoso: false, tags: [batch],
      cap: 20, warmup_status: "ACTIVE", kind: "ok", reason_category: "", reason: "",
      rested: false, restedAt: null,
    }, extra));

    // 5 reconnect (connection failed)
    mk("j.henry@sending.ac", "sending.ac", "sender:Bjion Henry", { kind: "reconnect", warmup_status: "none", reason_category: "auth failed", reason: "IMAP login failed — password changed at provider", cap: 0 });
    mk("b.dormer@thunderbirdadvisory.info", "thunderbirdadvisory.info", "Thunderbird-July", { kind: "reconnect", warmup_status: "none", reason_category: "smtp timeout", reason: "SMTP connection timed out repeatedly", cap: 0 });
    mk("k.dormer@navreo.biz", "navreo.biz", "June 2026", { kind: "reconnect", warmup_status: "none", reason_category: "auth failed", reason: "OAuth token revoked", cap: 0 });
    mk("r.arnic@arnicbiz.biz", "arnicbiz.biz", "Arnic - Temporary", { kind: "reconnect", warmup_status: "none", reason_category: "smtp timeout", reason: "SMTP connection refused", cap: 0 });
    mk("s.hypertide@saleswithnavreo.info", "saleswithnavreo.info", "Hypertide (Odd - 2026)", { kind: "reconnect", warmup_status: "none", reason_category: "auth failed", reason: "IMAP login failed", cap: 0 });

    // 14 warmup-off (drives warmupConfig.notWarming too — same rows referenced there)
    const woSpec = [
      ["hb-henry-h@navreoops.info", "navreoops.info", "June 2026"],
      ["hb-henry@navreoops.info", "navreoops.info", "June 2026"],
      ["bb-henry-h@navreoops.info", "navreoops.info", "June 2026"],
      ["a.dormer@surgeamplifyy.info", "surgeamplifyy.info", "Amplifyy v1"],
      ["b.dormer@surgeamplifyy.info", "surgeamplifyy.info", "Amplifyy v1"],
      ["c.dormer@theamplifyylab.info", "theamplifyylab.info", "Amplifyy v1"],
      ["jacki_a@arnicbiz.biz", "arnicbiz.biz", "Arnic - Temporary"],
      ["jacki_b@arnicbiz.biz", "arnicbiz.biz", "Arnic - Temporary"],
      ["m.h@getnavreo.biz", "getnavreo.biz", "Arnic - Temporary"],
      ["p.k@navreoleads.info", "navreoleads.info", "Thunderbird-July"],
      ["q.k@navreopipeline.info", "navreopipeline.info", "Thunderbird-July"],
      ["z.b@gtmnavreo.org", "gtmnavreo.org", "June 2026"],
      ["y.b@gtmnavreo.com", "gtmnavreo.com", "Hypertide (Odd - 2026)"],
      ["x.dep@geteasysales.com", "geteasysales.com", "Client Trial (A)"],
    ];
    const woRows = woSpec.map(([email, domain, batch], i) => ({
      id: id++, email, domain, provider: "OAuth/Outlook", maildoso: false, tags: [batch],
      cap: 15, warmup_status: "INACTIVE", kind: "warmupoff", reason_category: "", reason: "Warmup toggled off — no activity in 7d",
      rested: false, restedAt: null, created: addDays(todayISO(), -(20 + i * 2)), status: "off", batch,
    }));
    woRows.forEach((r) => rows.push(r));

    // 10 blocked (real hosting/complaint blocks + soft warmup noise) — also feeds "reasons" breakdown
    const blSpec = [
      ["r.krs@heygroutsonline.info", "heygroutsonline.info", "June 2026", "soft", "Address not found — recipient mailbox doesn't exist"],
      ["r.krs@getgroutsonline.info", "getgroutsonline.info", "June 2026", "soft", "Message not delivered — greylisted, will retry"],
      ["jacki_a@arnicoutreach.info", "arnicoutreach.info", "Arnic - Temporary", "soft", "Message not delivered — temporary DNS failure"],
      ["m.p@navreostrategy.xyz", "navreostrategy.xyz", "Hypertide (Odd - 2026)", "soft", "Deferred — 4.7.0 temporary throttling"],
      ["a.w@theamplifyylab.info", "theamplifyylab.info", "Amplifyy v1", "hosting block", "550 5.7.1 blocked by recipient policy (Proofpoint)"],
      ["b.w@getnavreo.biz", "getnavreo.biz", "Arnic - Temporary", "hosting block", "550 5.7.606 Access denied, banned sending IP (Outlook)"],
      ["c.d@navreoconversion.digital", "navreoconversion.digital", "Client Trial (A)", "mailbox full", "552 5.2.2 mailbox full"],
      ["d.e@gtmwithnavreo.xyz", "gtmwithnavreo.xyz", "sender:Bjion Henry", "mailbox full", "452 4.2.2 mailbox over quota"],
      ["e.f@saleswithnavreo.info", "saleswithnavreo.info", "Hypertide (Odd - 2026)", "spam complaint", "550 5.7.1 message flagged as spam (SNDS)"],
      ["f.g@navreopipelineengine.info", "navreopipelineengine.info", "Arnic - Temporary", "spam complaint", "550 5.7.1 too many complaints, sender blocked"],
    ];
    blSpec.forEach(([email, domain, batch, cat, reason]) => rows.push({
      id: id++, email, domain, provider: "OAuth/Outlook", maildoso: false, tags: [batch],
      cap: 0, warmup_status: "none", kind: "blocked", reason_category: cat, reason, rested: false, restedAt: null,
    }));

    // 31 general rows: sending / in-warmup / rested, spread across the domain pool + batches
    let di = 0, bi = 0;
    for (let i = 0; i < 20; i++) { // sending
      const domain = DOMAIN_POOL[di % DOMAIN_POOL.length]; di++;
      const batch = BATCHES[bi % BATCHES.length]; bi++;
      mk(`s${i}@${domain}`, domain, batch, { cap: [15, 20, 25, 35][i % 4], warmup_status: "ACTIVE" });
    }
    for (let i = 0; i < 6; i++) { // in warmup (cap 0, not yet promoted — not dashboard-rested)
      const domain = DOMAIN_POOL[di % DOMAIN_POOL.length]; di++;
      const batch = BATCHES[bi % BATCHES.length]; bi++;
      mk(`w${i}@${domain}`, domain, batch, { cap: 0, warmup_status: "ACTIVE" });
    }
    for (let i = 0; i < 5; i++) { // rested by the dashboard
      const domain = DOMAIN_POOL[di % DOMAIN_POOL.length]; di++;
      const batch = BATCHES[bi % BATCHES.length]; bi++;
      const due = Date.now() + (i < 2 ? -1 : 1) * (2 + i) * 864e5; // first two already due, rest upcoming
      mk(`r${i}@${domain}`, domain, batch, { cap: 0, warmup_status: "ACTIVE", rested: true, restedAt: due - 7 * 864e5 });
    }
    return { rows, woRows };
  }

  function buildMock() {
    // Built fresh on every call (never shared/reused) so "Run Live Audit" and any other
    // reset genuinely starts over instead of replaying a previous run's mutations.
    const _built = buildInboxRows();
    const domainHealthRows = buildDomainHealthRows();
    const resting = {};
    const restingDue = {};
    // 6 of the 24 domains are already resting (dashboard-paused); 2 due now, 4 upcoming.
    const restingDomains = ["weamplifyy.info", "arnicbiz.biz", "navreoops.info", "surgeamplifyy.info", "navreoscale.info", "navreogotomarket.biz"];
    restingDomains.forEach((d, i) => {
      const mailboxesOnDomain = _built.rows.filter((r) => r.domain === d).length || 3;
      resting[d] = Math.max(1, mailboxesOnDomain);
      restingDue[d] = Date.now() + (i < 2 ? -1 : 1) * (1 + i) * 864e5;
    });

    return {
      date: "2026-07-08",
      inboxes: 8674,
      domains: 158,
      active: 62,
      sent: 8197,
      reply_pct: 1.24,
      bounce_pct: 1.8,
      replyTrend: { wkRate: 1.24, prevRate: 1.62, drop: true },
      campLow: 4,
      highb: 2,
      spfMiss: 0, dkimMiss: 0, dmarcMiss: 1,
      noNS: 0,
      quarantine: 94, reject: 42, none: 22,
      warmupResting: Object.keys(resting).length,
      warmupDue: Object.entries(restingDue).filter(([, ts]) => ts <= Date.now()).length,
      smtp: 3, imap: 1,
      inactiveNote: "incl. external Maildoso (~600 by design)",
      inactiveRows: [
        { email: "hb-henry-h@meetingsnavreo.info", domain: "meetingsnavreo.info", smtp_host: "(Azure/Outlook)", smtp_ok: true, reputation: "99%", error: "DSN: mailbox disabled by admin (Maildoso, by design)" },
        { email: "hb-henry@meetingsnavreo.info", domain: "meetingsnavreo.info", smtp_host: "(Azure/Outlook)", smtp_ok: true, reputation: "100%", error: "DSN: mailbox disabled by admin (Maildoso, by design)" },
        { email: "bb-henry-h@meetingsnavreo.info", domain: "meetingsnavreo.info", smtp_host: "(Azure/Outlook)", smtp_ok: true, reputation: "99%", error: "DSN: mailbox disabled by admin (Maildoso, by design)" },
        { email: "hq@bookednavreo.info", domain: "bookednavreo.info", smtp_host: "(Azure/Outlook)", smtp_ok: true, reputation: "98%", error: "DSN: mailbox disabled by admin (Maildoso, by design)" },
        { email: "sales@navreohub.info", domain: "navreohub.info", smtp_host: "(Azure/Outlook)", smtp_ok: true, reputation: "97%", error: "DSN: mailbox disabled by admin (Maildoso, by design)" },
        { email: "hello@launchwithnavreo.digital", domain: "launchwithnavreo.digital", smtp_host: "(Azure/Outlook)", smtp_ok: true, reputation: "96%", error: "DSN: mailbox disabled by admin (Maildoso, by design)" },
        { email: "team@getnavreogrowth.org", domain: "getnavreogrowth.org", smtp_host: "(Azure/Outlook)", smtp_ok: false, reputation: "61%", error: "Repeated auth failures — reputation dropping, real issue" },
        { email: "ops@navreoconnect.info", domain: "navreoconnect.info", smtp_host: "(Azure/Outlook)", smtp_ok: false, reputation: "58%", error: "SMTP disabled after abuse report — real issue" },
      ],
      lifecycle: {
        newUnprocessed: [
          { email: "a.new@navreohub.info", domain: "navreohub.info", tagged: false, inCampaign: false, created: addDays(todayISO(), -1) },
          { email: "b.new@bookednavreo.info", domain: "bookednavreo.info", tagged: false, inCampaign: false, created: addDays(todayISO(), -1) },
          { email: "c.new@launchwithnavreo.digital", domain: "launchwithnavreo.digital", tagged: true, inCampaign: false, created: addDays(todayISO(), -2) },
          { email: "d.new@getnavreogrowth.org", domain: "getnavreogrowth.org", tagged: false, inCampaign: true, created: addDays(todayISO(), -2) },
          { email: "e.new@navreoconnect.info", domain: "navreoconnect.info", tagged: false, inCampaign: false, created: addDays(todayISO(), -3) },
          { email: "f.new@thenavreoagency.info", domain: "thenavreoagency.info", tagged: false, inCampaign: false, created: addDays(todayISO(), -3) },
          { email: "g.new@navreocampaign.info", domain: "navreocampaign.info", tagged: true, inCampaign: false, created: addDays(todayISO(), -4) },
          { email: "h.new@theamplifyyteam.info", domain: "theamplifyyteam.info", tagged: false, inCampaign: false, created: addDays(todayISO(), -4) },
          { email: "i.new@runamplifyy.info", domain: "runamplifyy.info", tagged: false, inCampaign: true, created: addDays(todayISO(), -5) },
        ],
        untagged: [],
        retired: [{ domain: "oldnavreotest.info", mailboxes: 3 }],
      },
      warmupConfig: {
        notWarming: _built.woRows,
        wrongSettings: [
          { email: "p.w@navreostrategy.org", domain: "navreostrategy.org", issue: "reply-rate threshold too low (12%)" },
          { email: "q.w@salesnavreo.info", domain: "salesnavreo.info", issue: "per-day cap set to 60 (fleet standard is 35)" },
          { email: "r.w@gtmnavreo.org", domain: "gtmnavreo.org", issue: "ramp-up disabled" },
          { email: "s.w@navreopipelineengine.info", domain: "navreopipelineengine.info", issue: "per-day cap set to 60 (fleet standard is 35)" },
          { email: "t.w@theamplifyylab.info", domain: "theamplifyylab.info", issue: "reply-rate threshold too low (10%)" },
          { email: "u.w@geteasysales.com", domain: "geteasysales.com", issue: "ramp-up disabled" },
          { email: "v.w@navreo.biz", domain: "navreo.biz", issue: "per-day cap set to 55 (fleet standard is 35)" },
          { email: "w.w@gtmwithnavreo.xyz", domain: "gtmwithnavreo.xyz", issue: "reply-rate threshold too low (15%)" },
        ],
        standard: "38/35",
      },
      signature: {
        missing: [
          { email: "hb-henry-h@navreoops.info", domain: "navreoops.info", batch: "June 2026", from_name: "Bjion Henry", created: addDays(todayISO(), -6) },
          { email: "a.dormer@surgeamplifyy.info", domain: "surgeamplifyy.info", batch: "Amplifyy v1", from_name: "Kevin Dormer", created: addDays(todayISO(), -6) },
          { email: "jacki_a@arnicbiz.biz", domain: "arnicbiz.biz", batch: "Arnic - Temporary", from_name: "Jacki Arnic", created: addDays(todayISO(), -7) },
          { email: "m.h@getnavreo.biz", domain: "getnavreo.biz", batch: "Arnic - Temporary", from_name: "Jacki Arnic", created: addDays(todayISO(), -7) },
          { email: "p.k@navreoleads.info", domain: "navreoleads.info", batch: "Thunderbird-July", from_name: "Priya Kapoor", created: addDays(todayISO(), -8) },
          { email: "z.b@gtmnavreo.org", domain: "gtmnavreo.org", batch: "June 2026", from_name: "Bjion Henry", created: addDays(todayISO(), -9) },
          { email: "y.b@gtmnavreo.com", domain: "gtmnavreo.com", batch: "Hypertide (Odd - 2026)", from_name: "Bjion Henry", created: addDays(todayISO(), -9) },
          { email: "x.dep@geteasysales.com", domain: "geteasysales.com", batch: "Client Trial (A)", from_name: "Kevin Dormer", created: addDays(todayISO(), -10) },
          { email: "b.dormer@thunderbirdadvisory.info", domain: "thunderbirdadvisory.info", batch: "Thunderbird-July", from_name: "Kevin Dormer", created: addDays(todayISO(), -10) },
        ],
        mismatch: [
          { email: "hb-henry@navreoops.info", domain: "navreoops.info", batch: "June 2026", from_name: "Bjion Henry", issue: "signature says 'Bjion H.' — mismatched from_name", created: addDays(todayISO(), -11) },
          { email: "bb-henry-h@navreoops.info", domain: "navreoops.info", batch: "June 2026", from_name: "Bjion Henry", issue: "signature says 'Team Navreo'", created: addDays(todayISO(), -11) },
          { email: "b.dormer@surgeamplifyy.info", domain: "surgeamplifyy.info", batch: "Amplifyy v1", from_name: "Kevin Dormer", issue: "signature says 'K. Dormer'", created: addDays(todayISO(), -12) },
          { email: "jacki_b@arnicbiz.biz", domain: "arnicbiz.biz", batch: "Arnic - Temporary", from_name: "Jacki Arnic", issue: "signature says 'J. Arnic — Arnic Growth'", created: addDays(todayISO(), -12) },
          { email: "c.dormer@theamplifyylab.info", domain: "theamplifyylab.info", batch: "Amplifyy v1", from_name: "Kevin Dormer", issue: "signature blank first line", created: addDays(todayISO(), -13) },
        ],
      },
      sendingDeviation: {
        over: [
          { email: "s0@navreo.biz", domain: "navreo.biz", batch: "June 2026", cap: 60, baseline: 25, direction: "over" },
          { email: "s4@navreoscale.info", domain: "navreoscale.info", batch: "June 2026", cap: 55, baseline: 20, direction: "over" },
          { email: "s8@gtmnavreo.org", domain: "gtmnavreo.org", batch: "Hypertide (Odd - 2026)", cap: 50, baseline: 20, direction: "over" },
          { email: "s12@navreo.biz", domain: "navreo.biz", batch: "sender:Bjion Henry", cap: 45, baseline: 20, direction: "over" },
        ],
        under: [
          { email: "s2@navreoops.info", domain: "navreoops.info", batch: "Amplifyy v1", cap: 5, baseline: 20, direction: "under" },
          { email: "s6@salesnavreo.info", domain: "salesnavreo.info", batch: "Arnic - Temporary", cap: 3, baseline: 20, direction: "under" },
          { email: "s10@getnavreo.biz", domain: "getnavreo.biz", batch: "Navreo Maildoso", cap: 2, baseline: 20, direction: "under" },
        ],
      },
      batchStats: BATCHES.map((b, i) => ({
        batch: b,
        mailboxes: [1050, 3844, 1493, 1417, 300, 304, 18, 519][i],
        domains: [22, 46, 19, 17, 5, 6, 2, 8][i],
        sending: [720, 2610, 980, 940, 210, 180, 12, 360][i],
        warmup: [280, 1050, 420, 400, 80, 110, 5, 140][i],
        dead: [3, 8, 2, 4, 0, 1, 0, 1][i],
        blocked: [1, 4, 3, 1, 0, 0, 0, 0][i],
        blacklisted: [1, 1, 1, 1, 0, 0, 0, 0][i],
        sent: [61200, 224500, 88900, 79800, 15100, 16400, 900, 33200][i],
        reply_rate: [0.94, 1.42, 0.61, 0.88, 1.71, 1.05, 2.4, 1.18][i],
        bounce_rate: [1.6, 1.3, 2.9, 1.9, 0.9, 1.1, 0.5, 1.4][i],
        positive_rate: [0.21, 0.34, 0.12, 0.19, 0.4, 0.25, 0.6, 0.28][i],
      })),
      reminders: [
        { id: "r1", domains: ["launchwithnavreo.digital"], note: "", restoredDate: "2026-07-01", dueDate: "2026-07-15", done: false, ts: 1782911944439 },
        { id: "r2", domains: ["bookednavreo.info", "navreohub.info"], note: "batch restore", restoredDate: "2026-06-28", dueDate: "2026-07-12", done: false, ts: 1782500000000 },
        { id: "r3", domains: ["arnicbiz.biz"], note: "", restoredDate: "2026-06-20", dueDate: "2026-07-04", done: false, ts: 1781800000000 },
      ],
      remHealth: {
        r1: { total: 2, warming: 2, failed: 0, dead: 0, reasons: {} },
        r2: { total: 5, warming: 3, failed: 2, dead: 0, reasons: { off: 2 } },
        r3: { total: 3, warming: 1, failed: 2, dead: 0, reasons: { off: 1, blocked: 1 } },
      },
      history: [
        { date: "2026-07-07", action: "reenable", count: 18, failed: 1, scope: "Amplifyy v1" },
        { date: "2026-07-07", action: "notion_sync", count: 12, scope: "changed" },
        { date: "2026-07-06", action: "warmup_pause", mailboxes: 22, domains: 3, scope: "reply-rate rotation" },
        { date: "2026-07-05", action: "reconnect", count: 4 },
        { date: "2026-07-05", action: "signatures", count: 31, failed: 0, scope: "Arnic - Temporary" },
        { date: "2026-07-04", action: "warmup_resume", mailboxes: 9 },
        { date: "2026-07-03", action: "process_new", count: 6, scope: "tagged + added to campaign" },
        { date: "2026-07-02", name: "Amplifyy - Not on Amazon (Hard)", campaign: 3409745, removed: 214, guarded: 6, before: 4210, after: 3996, total: 4210 },
        { date: "2026-07-01", action: "notion_sync", count: 9, scope: "changed" },
        { date: "2026-06-30", action: "reenable", count: 27, failed: 0, scope: "June 2026" },
      ],
      acks: [],
      delisting: [],
      blacklistCleared: 1,
      blacklistRows: [
        { domain: "heygroutsonline.info", url: "https://mxtoolbox.com/domain/heygroutsonline.info/blacklist", lists: "Spamhaus DBL", advice: "PAUSE + FIX", batch: "June 2026", tags: ["dash-rest-2"], mailboxes: 9, rested: 9, restedDue: Date.now() + 4 * 864e5, cleared: false },
        { domain: "getgroutsonline.info", url: "https://mxtoolbox.com/domain/getgroutsonline.info/blacklist", lists: "SURBL", advice: "PAUSE + FIX", batch: "June 2026", tags: [], mailboxes: 6, rested: 0, restedDue: null, cleared: false },
        { domain: "arnicoutreach.info", url: "https://mxtoolbox.com/domain/arnicoutreach.info/blacklist", lists: "Spamhaus DBL, SURBL", advice: "REPLACE (young domain)", batch: "Arnic - Temporary", tags: [], mailboxes: 12, rested: 12, restedDue: Date.now() - 1 * 864e5, cleared: false },
        { domain: "navreocampaign.info", url: "https://mxtoolbox.com/domain/navreocampaign.info/blacklist", lists: "SURBL", advice: "PAUSE + FIX", batch: "June 2026", tags: ["dash-rest-15"], mailboxes: 5, rested: 0, restedDue: null, cleared: false },
        { domain: "weamplifyy.info", url: "https://mxtoolbox.com/domain/weamplifyy.info/blacklist", lists: "Spamhaus DBL", advice: "CLEARED — reactivate", batch: "Amplifyy - Hypertide", tags: [], mailboxes: 8, rested: 8, restedDue: Date.now() + 2 * 864e5, cleared: true },
        { domain: "thunderbirdadvisory.info", url: "https://mxtoolbox.com/domain/thunderbirdadvisory.info/blacklist", lists: "SURBL", advice: "PAUSE + FIX", batch: "Thunderbird-July", tags: [], mailboxes: 3, rested: 0, restedDue: null, cleared: false },
      ],
      campaignsFlagged: [
        { id: 3409745, name: "Amplifyy - Hiring Signal - Not on Amazon (Hard)", url: "https://app.smartlead.ai/app/campaign/3409745/analytics", bounce_pct: 4.2, sent: 2140 },
        { id: 3488224, name: "Navreo - Commercial Roofing", url: "https://app.smartlead.ai/app/campaign/3488224/analytics", bounce_pct: 3.1, sent: 1870 },
        { id: 3506763, name: "Arnic - Sales Leaders", url: "https://app.smartlead.ai/app/campaign/3506763/analytics", bounce_pct: 5.6, sent: 990 },
        { id: 3550274, name: "Navreo - YC Startups", url: "https://app.smartlead.ai/app/campaign/3550274/analytics", bounce_pct: 2.9, sent: 1420 },
      ],
      domainHealth: {
        start: "2026-07-01", end: "2026-07-08", minSent: 500, cutoff: 0.8,
        rows: domainHealthRows, resting, restingDue,
      },
      inboxRows: _built.rows,
      sigTemplates: { navreo: "Best,\n{{name}}\nNavreo Growth Team", arnic: "Cheers,\n{{name}}\nArnic", amplifyy: "Thanks,\n{{name}}\nAmplifyy Team", _all: "Best,\n{{name}}" },
    };
  }

  const CAMPAIGNS = [
    { id: 3409745, name: "Amplifyy - Hiring Signal - Not on Amazon (Hard)" },
    { id: 3409812, name: "Amplifyy - Hiring Signal - Not on Amazon (Soft)" },
    { id: 3488224, name: "Navreo - Commercial Roofing" },
    { id: 3487932, name: "Navreo - CRE" },
    { id: 3488466, name: "Navreo - MSP" },
    { id: 3506763, name: "Arnic - Sales Leaders" },
    { id: 3506833, name: "Arnic - CEO Outreach" },
    { id: 3477409, name: "Navreo - SaaS Overlap" },
    { id: 3550274, name: "Navreo - YC Startups" },
    { id: 3550324, name: "Arnic - YC Startups" },
  ];

  /* ============================================================
     2. State — mutable S, mirrored to sessionStorage
     ============================================================ */
  let S = null;
  // `ui`: small persisted UI preferences that need to survive a repaint (unlike
  // the ephemeral UI object below) — currently just the technical-details fold's
  // manual open/close override, so a user's explicit toggle sticks across every
  // paintPage() re-render instead of snapping back to its computed default.
  function freshState() { const a = buildMock(); return { A: a, campaigns: deepClone(CAMPAIGNS), ui: {} }; }
  function saveState() { try { sessionStorage.setItem("dlv_state", JSON.stringify(S)); } catch (e) {} }
  // Root-cause fix (reliable history log, item 1): every state-changing handler
  // used to build its own `{ date: todayISO(), ... }` row and unshift it onto
  // S.A.history directly — 28 call sites, each free to drift in shape. Two
  // problems fell out of that: (a) nothing stamped a real instant on a row, so
  // "seed data" (loaded once in buildMock(), dated but never re-run) and
  // "ran this session" rows were indistinguishable beyond eyeballing the date
  // string — exactly what the "static demo placeholder" report was seeing; and
  // (b) a couple of real mutations (CSV export, clipboard copy, verify-clean)
  // never wrote a row at all, so those actions left literally zero trace.
  // logAction() is now the ONE place anything appends to the log: it stamps a
  // `ts` (a session-local action always has one; nothing in buildMock()'s seed
  // history ever does, so `h.ts != null` is a reliable, single-sourced "ran
  // this session" test — reused by renderHistoryRow() below for the "earlier"
  // vs "today — this session" badge instead of a second parallel flag that
  // could drift out of sync with the first). Capped so an extremely long
  // session can't grow this unboundedly inside sessionStorage.
  function logAction(entry) {
    if (!S || !S.A) return null;
    if (!Array.isArray(S.A.history)) S.A.history = [];
    const row = Object.assign({ date: todayISO() }, entry, { ts: Date.now() });
    S.A.history.unshift(row);
    if (S.A.history.length > 500) S.A.history.length = 500;
    saveState();
    // Update an open Recent-actions fold IMMEDIATELY — even for actions whose
    // handlers never repaint the page (CSV download, copy, verify run).
    try { repaintHistoryFold(); } catch (e) {}
    return row;
  }
  // Root-cause hardening (defect A): every history/acks-mutating action assumes
  // its own writes are clean, but nothing ever validated a LOADED blob — one
  // stray malformed entry (a non-object, or one missing the `.date`/`.key`
  // fields every reader assumes exist) sitting in sessionStorage from a stale
  // schema or an interrupted write is enough to throw inside actionRanToday()/
  // isAcked() the moment any code iterates `S.A.history`/`S.A.acks` — and
  // because it lives in sessionStorage, that exception reproduces on every
  // subsequent action AND survives a reload. Called right after every load
  // (fresh or restored) so a corrupt blob can never brick the tab permanently;
  // at worst it silently drops the one bad row instead of crashing forever.
  function normalizeState(s) {
    if (!s || typeof s !== "object") return freshState();
    if (!s.A || typeof s.A !== "object") { const fresh = freshState(); s.A = fresh.A; }
    if (!s.ui || typeof s.ui !== "object") s.ui = {};
    if (!Array.isArray(s.campaigns)) s.campaigns = deepClone(CAMPAIGNS);
    const isPlainObj = (x) => x != null && typeof x === "object" && !Array.isArray(x);
    // acks: must be a plain object with a string `key` and a finite `count` —
    // everything else (isAcked/markDone/unmarkDone) only ever reads those two.
    s.A.acks = (Array.isArray(s.A.acks) ? s.A.acks : []).filter((a) =>
      isPlainObj(a) && typeof a.key === "string" && a.key && Number.isFinite(Number(a.count)));
    // history: must be a plain object with a string `date` — every
    // TODO_ACTION_MATCH test and actionRanToday()'s `.some()` dereferences
    // `.date` (and often `.action`/`.scope`/`.campaign`) unconditionally, so a
    // non-object or dateless row is exactly the "unexpected shape" that turns
    // a routine `.some()` scan into a permanent TypeError.
    s.A.history = (Array.isArray(s.A.history) ? s.A.history : []).filter((h) =>
      isPlainObj(h) && typeof h.date === "string" && h.date);
    return s;
  }
  function loadState() {
    try {
      const raw = sessionStorage.getItem("dlv_state");
      if (raw) { S = normalizeState(JSON.parse(raw)); saveState(); return; }
    } catch (e) {}
    S = freshState();
    saveState();
  }
  function resetState() { S = freshState(); S.A.date = todayISO(); saveState(); }

  /* ============================================================
     3a. LIVE DATA LAYER (Stage A) — same-origin proxy fetch, live/
         sample mode, /run-blob → S mapping, per-panel live fetch.
         READ path only: NO mutating action talks to the backend here
         (that is Stage B) — every action still mutates the local S,
         which stays no-op-safe in live mode (its finders guard on the
         mock ids). The proxy at /api/deliverability/<path> adds the
         backend Basic-Auth server-side, so nothing is sent client-side.
     ============================================================ */
  const DLV_API = "/api/deliverability/";
  // Data-source mode: null = not probed yet, "live" = backend reachable,
  // "sample" = backend unconfigured/unreachable → mock data + a banner.
  const DATA = {
    mode: null,
    probed: false,          // the config probe (GET campaigns) resolved once
    booting: false,         // a bootData() pass is in flight
    runLoading: false,      // a POST /run is in flight
    runError: null,         // last /run failure kind (banner)
    sampleDismissed: false, // user closed the "sample data" banner
    // Manager (mailbox views) live cache — keyed by view+batch.
    mgr: { key: null, pendingKey: null, loading: false, error: false, rows: null, counts: null, batches: null, total: null, truncated: false },
    // Domain-health live cache — keyed by window+minSent+cutoff.
    dh: { key: null, pendingKey: null, loading: false, error: false, done: false },
  };
  function isLive() { return DATA.mode === "live"; }

  // Typed fetch error so callers can distinguish 503 (backend unconfigured)
  // from 502 (upstream error) from a raw network/timeout failure.
  // kind ∈ "unconfigured" | "upstream" | "network" | "http".
  function ApiError(kind, status, message) {
    this.name = "ApiError"; this.kind = kind; this.status = status || 0;
    this.message = message || kind;
  }
  ApiError.prototype = Object.create(Error.prototype);

  async function apiFetch(path, opts) {
    opts = opts || {};
    const ctrl = ("AbortController" in window) ? new AbortController() : null;
    const timer = ctrl ? setTimeout(() => { try { ctrl.abort(); } catch (e) {} }, opts.timeout || 30000) : null;
    let resp;
    try {
      resp = await fetch(DLV_API + path, {
        method: opts.method || "GET",
        headers: opts.body != null ? { "Content-Type": "application/json" } : undefined,
        body: opts.body != null ? JSON.stringify(opts.body) : undefined,
        signal: ctrl ? ctrl.signal : undefined,
        // NO credentials — the same-origin proxy owns the backend auth.
      });
    } catch (e) {
      if (timer) clearTimeout(timer);
      throw new ApiError("network", 0, String((e && e.message) || e));
    }
    if (timer) clearTimeout(timer);
    if (resp.status === 503) throw new ApiError("unconfigured", 503, "deliverability backend not configured");
    if (resp.status === 502) throw new ApiError("upstream", 502, "deliverability upstream error");
    if (!resp.ok) throw new ApiError("http", resp.status, "HTTP " + resp.status);
    const ct = resp.headers.get("Content-Type") || "";
    if (ct.indexOf("application/json") === -1) return resp.text(); // CSV etc.
    return resp.json();
  }
  function apiGet(path, opts) { return apiFetch(path, Object.assign({ method: "GET" }, opts)); }
  function apiPost(path, body, opts) { return apiFetch(path, Object.assign({ method: "POST", body: body || {} }, opts)); }

  // Map the live /run blob onto a complete S.A. Base = a fresh mock A so any
  // field the blob does NOT carry (inboxRows for the manager fallback,
  // inactiveRows/remHealth for the Stage-C-owned View modals) stays populated
  // and valid; then overlay every field the backend provides, adapting the
  // handful of names that differ (blacklist→blacklistRows, highbCamps→
  // campaignsFlagged). Sets A._live so derive()/warmupTile() prefer the live
  // pre-computed aggregates over recomputing from the (mock) inboxRows.
  function mapRunBlob(blob) {
    const A = buildMock();
    // Fields whose live shape already matches what the renderers read off S.A.
    const keep = [
      "date", "inboxes", "domains", "active", "sent", "reply_pct", "bounce_pct",
      "replyTrend", "campLow", "highb", "blacklistCleared", "spfMiss", "dkimMiss",
      "dmarcMiss", "noNS", "quarantine", "reject", "none", "smtp", "imap", "inactive",
      "warmupResting", "warmupDue", "lifecycle", "warmupConfig", "signature",
      "sendingDeviation", "batchStats", "history", "acks", "delisting", "reminders",
      "domainHealth", "sigTemplates",
      // live-only aggregates that derive() prefers when A._live is set:
      "blocked", "blockedReal", "blockedSoft", "reasons",
    ];
    keep.forEach((k) => { if (blob[k] != null) A[k] = blob[k]; });
    // blacklist[] → blacklistRows[]: the live rows omit url/advice/cleared that
    // renderBlacklistRow expects, so synthesize them (Object.assign target-first
    // so any real backend field of the same name wins).
    if (Array.isArray(blob.blacklist)) {
      A.blacklistRows = blob.blacklist.map((b) => Object.assign({
        url: "https://mxtoolbox.com/domain/" + b.domain + "/blacklist",
        advice: (b.ageDays != null && b.ageDays < 30) ? "REPLACE (young domain)" : "PAUSE + FIX",
        cleared: false,
      }, b));
    }
    // highbCamps[] → campaignsFlagged[] (drives the verify to-do + tile count).
    if (Array.isArray(blob.highbCamps)) {
      A.campaignsFlagged = blob.highbCamps.map((c) => ({
        id: c.id, name: c.name,
        url: c.url || ("https://app.smartlead.ai/app/campaign/" + c.id + "/analytics"),
        bounce_pct: c.bounce_pct, sent: c.sent,
      }));
    }
    // Per-reminder health isn't in the /run blob — an empty map keeps
    // renderReminderRow's `S.A.remHealth[r.id]` lookups returning undefined
    // (health line simply omitted) instead of throwing on a missing object.
    A.remHealth = {};
    A._live = true;
    return A;
  }

  // Probe the backend once and set DATA.mode; in live mode, overlay the cheap
  // /reminders immediately and kick a background /run to fill the aggregate S.A
  // (unless the in-memory / sessionStorage S is already a live snapshot).
  async function bootData() {
    if (DATA.booting) return;
    if (DATA.probed) {
      if (isLive() && !(S.A && S.A._live) && !DATA.runLoading) runLiveAuditBg(false);
      return;
    }
    DATA.booting = true;
    try {
      await apiGet("campaigns", { timeout: 20000 }); // config probe (light)
      DATA.mode = "live";
    } catch (e) {
      DATA.mode = "sample"; // 503 unconfigured OR network/upstream → sample
    }
    DATA.probed = true;
    DATA.booting = false;
    try { sessionStorage.setItem("dlv_data_mode", DATA.mode); } catch (e) {}
    if (isLive()) {
      // Cheap live wins first: reminders paint before the ~2-min /run resolves.
      apiGet("reminders", { timeout: 20000 }).then((rem) => {
        if (Array.isArray(rem)) { S.A.reminders = rem; saveState(); paintPage(); }
      }).catch(() => {});
      if (!(S.A && S.A._live)) runLiveAuditBg(false);
      else paintPage();
    } else {
      paintPage(); // surface the sample-data banner
    }
  }

  // POST /run in the background (~1-2 min): non-blocking banner while it runs,
  // then S.A ← mapped blob + repaint. `force` is cosmetic (the button path);
  // it always runs regardless of the current snapshot.
  async function runLiveAuditBg(force) {
    if (DATA.runLoading) return;
    DATA.runLoading = true; DATA.runError = null;
    paintPage(); // show the "Running live audit…" banner
    try {
      const blob = await apiPost("run", {}, { timeout: 200000 });
      S.A = mapRunBlob(blob);
      DATA.mode = "live";
      if (S.ui) delete S.ui.redSnapshot; // re-baseline partial-progress math to live
      saveState();
      // Invalidate the per-panel live caches so they re-fetch against the new run.
      DATA.mgr.key = null; DATA.mgr.rows = null; DATA.mgr.counts = null; DATA.mgr.batches = null;
      DATA.dh.key = null; DATA.dh.done = false;
    } catch (e) {
      DATA.runError = (e && e.kind) ? e.kind : "error";
    } finally {
      DATA.runLoading = false;
      paintPage();
    }
  }

  // ── Manager live fetch: mailbox views via GET /inboxes?view=&batch= ──
  function mgrLiveKey() { return "mbx|" + UI.mgr.view + "|" + (UI.mgr.batch || ""); }
  // Returns true when DATA.mgr holds rows for the current view/batch; otherwise
  // kicks a fetch (idempotent per key) and returns false so the caller paints a
  // loading/error state. Search stays a client-side filter on the cached rows.
  function ensureMgrLive() {
    const key = mgrLiveKey();
    if (DATA.mgr.key === key && DATA.mgr.rows) return true;
    if (DATA.mgr.loading && DATA.mgr.pendingKey === key) return false;
    DATA.mgr.loading = true; DATA.mgr.error = false; DATA.mgr.pendingKey = key;
    const q = "inboxes?view=" + encodeURIComponent(UI.mgr.view) + "&batch=" + encodeURIComponent(UI.mgr.batch || "");
    apiGet(q, { timeout: 90000 }).then((r) => {
      DATA.mgr.key = key; DATA.mgr.pendingKey = null; DATA.mgr.loading = false; DATA.mgr.error = false;
      DATA.mgr.rows = (r && Array.isArray(r.rows)) ? r.rows : [];
      DATA.mgr.counts = (r && r.counts) || null;
      DATA.mgr.batches = (r && Array.isArray(r.batches)) ? r.batches : null;
      DATA.mgr.total = r ? r.total : null;
      DATA.mgr.truncated = !!(r && r.truncated);
      if (dlvSubtab === "manager") paintPage(); // refresh selector counts + rows
    }).catch(() => {
      DATA.mgr.pendingKey = null; DATA.mgr.loading = false; DATA.mgr.error = true;
      if (dlvSubtab === "manager") paintManagerRows();
    });
    return false;
  }

  // ── Domain view live fetch: GET /domain-health?start&end&minSent&cutoff ──
  // The /run blob already ships a live domainHealth, so the domain table has
  // live rows on first open with NO gate; this refetch keeps it in sync when the
  // owner changes the window/min-sent/cutoff controls (server-affecting params).
  function dhLiveKey() {
    const c = dhCutoffMin();
    return "dh|" + (S.A.domainHealth.start || "") + "|" + (S.A.domainHealth.end || "") + "|" + c.minSent + "|" + c.cutoff;
  }
  function ensureDhLive() {
    const key = dhLiveKey();
    if (DATA.dh.key === key && DATA.dh.done) return;
    if (DATA.dh.loading && DATA.dh.pendingKey === key) return;
    DATA.dh.loading = true; DATA.dh.error = false; DATA.dh.pendingKey = key;
    const c = dhCutoffMin();
    const q = "domain-health?start=" + encodeURIComponent(S.A.domainHealth.start || "") +
      "&end=" + encodeURIComponent(S.A.domainHealth.end || "") +
      "&minSent=" + encodeURIComponent(c.minSent) + "&cutoff=" + encodeURIComponent(c.cutoff);
    apiGet(q, { timeout: 120000 }).then((r) => {
      if (r && Array.isArray(r.rows)) {
        S.A.domainHealth = Object.assign({}, S.A.domainHealth, {
          rows: r.rows, resting: r.resting || {}, restingDue: r.restingDue || {},
          start: r.start || S.A.domainHealth.start, end: r.end || S.A.domainHealth.end,
          minSent: r.minSent != null ? r.minSent : S.A.domainHealth.minSent,
          cutoff: r.cutoff != null ? r.cutoff : S.A.domainHealth.cutoff,
          counts: r.counts || S.A.domainHealth.counts,
        });
        saveState();
      }
      DATA.dh.key = key; DATA.dh.pendingKey = null; DATA.dh.done = true; DATA.dh.loading = false;
      if (dlvSubtab === "manager" && UI.mgr.view === "domain") paintPage();
    }).catch(() => {
      DATA.dh.pendingKey = null; DATA.dh.loading = false; DATA.dh.error = true; DATA.dh.done = true; DATA.dh.key = key;
    });
  }

  /* ============================================================
     3. Derived counts — computed fresh from S every paint so every
        tile / banner / to-do / view-selector count stays in sync.
     ============================================================ */
  function dhCutoffMin() { return { minSent: Number((UI.dh.minSent != null ? UI.dh.minSent : S.A.domainHealth.minSent)) || 500, cutoff: Number((UI.dh.cutoff != null ? UI.dh.cutoff : S.A.domainHealth.cutoff)) }; }

  function derive() {
    const A = S.A;
    const today = todayISO();
    const { minSent, cutoff } = dhCutoffMin();
    const dhRows = A.domainHealth.rows.map((d) => Object.assign({}, d, { flag: dhFlag(d, minSent, cutoff) }));
    const resting = A.domainHealth.resting || {};
    const flaggedTotal = dhRows.filter((d) => d.flag === "warmup").length;
    const flaggedActionable = dhRows.filter((d) => d.flag === "warmup" && !(resting[d.domain] > 0)).length;
    const restingCount = Object.keys(resting).length;
    const recovered = dhRows.filter((d) => (resting[d.domain] || 0) > 0 && d.sent >= minSent && d.reply_rate >= cutoff).map((d) => d.domain);
    const sized = dhRows.filter((d) => d.sent >= minSent).length;
    const maildosoN = dhRows.filter((d) => d.maildoso).length;
    const domainHealthCounts = { total: dhRows.length, sized, flagged: flaggedTotal, keep: Math.max(0, sized - flaggedTotal - maildosoN), maildoso: maildosoN, resting: restingCount };

    const blockedRows = A.inboxRows.filter((r) => r.kind === "blocked");
    // Live mode: the /run blob carries pre-computed blocked aggregates over the
    // full 8k-mailbox fleet — prefer them over recomputing from the mock
    // inboxRows base (which mapRunBlob() keeps only as a manager fallback).
    let reasonCounts = groupCount(blockedRows, (r) => r.reason_category || "other");
    let blockedReal = Object.entries(reasonCounts).reduce((s, [k, v]) => s + (k === "soft" ? 0 : v), 0);
    let blockedSoft = reasonCounts.soft || 0;
    let blockedTotal = blockedRows.length;
    if (A._live) {
      if (A.reasons && typeof A.reasons === "object") reasonCounts = A.reasons;
      if (A.blockedReal != null) blockedReal = Number(A.blockedReal);
      if (A.blockedSoft != null) blockedSoft = Number(A.blockedSoft);
      if (A.blocked != null) blockedTotal = Number(A.blocked);
    }

    // Inbox counts feed the manager view-selector labels. In live mode prefer
    // the counts returned alongside GET /inboxes (full-fleet); until that
    // resolves fall back to the mock-derived counts so the panel never blanks.
    let inboxCounts = {
      total: A.inboxRows.length,
      blocked: A.inboxRows.filter((r) => r.kind === "blocked").length,
      reconnect: A.inboxRows.filter((r) => r.kind === "reconnect").length,
      warmupoff: A.inboxRows.filter((r) => r.kind === "warmupoff").length,
      inwarmup: A.inboxRows.filter((r) => r.kind === "ok" && r.cap === 0 && !r.rested).length,
      rested: A.inboxRows.filter((r) => r.kind === "ok" && r.rested).length,
      sending: A.inboxRows.filter((r) => r.kind === "ok" && r.cap > 0).length,
    };
    if (A._live && DATA.mgr && DATA.mgr.counts) inboxCounts = Object.assign({}, inboxCounts, DATA.mgr.counts);
    let inboxBatches = Object.entries(groupCount(A.inboxRows, (r) => (r.tags || [])[0] || "(no batch)")).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
    if (A._live && DATA.mgr && Array.isArray(DATA.mgr.batches)) inboxBatches = DATA.mgr.batches.slice();
    const dhBatches = Object.entries(groupCount(dhRows.flatMap((d) => (d.batches || []).map((b) => ({ b }))), (x) => x.b)).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);

    const signatureCount = A.signature.missing.length + A.signature.mismatch.length;
    const warmupConfigCount = A.warmupConfig.notWarming.length + A.warmupConfig.wrongSettings.length;
    const deviationCount = A.sendingDeviation.over.length + A.sendingDeviation.under.length;
    const newCount = A.lifecycle.newUnprocessed.length || A.lifecycle.untagged.length;
    const retiredCount = A.lifecycle.retired.length;
    const reminderDueCount = A.reminders.filter((r) => !r.done && r.dueDate <= today).length;

    const blMailboxes = A.blacklistRows.reduce((s, r) => s + r.mailboxes, 0);
    const blResting = A.blacklistRows.reduce((s, r) => s + (r.rested || 0), 0);
    const blSending = blMailboxes - blResting;
    const blClearedCount = A.blacklistRows.filter((r) => r.cleared).length;

    const cleanedCampaignIds = new Set((A.history || []).filter((h) => h.campaign != null).map((h) => String(h.campaign)));
    const uncleanedVerifyCamps = A.campaignsFlagged.filter((c) => !cleanedCampaignIds.has(String(c.id)));

    return {
      today, dhRows, resting, restingDue: A.domainHealth.restingDue || {}, flaggedTotal, flaggedActionable, restingCount, recovered,
      domainHealthCounts, reasonCounts, blockedReal, blockedSoft, blockedTotal,
      inboxCounts, inboxBatches, dhBatches, signatureCount, warmupConfigCount, deviationCount, newCount, retiredCount,
      reminderDueCount, blMailboxes, blResting, blSending, blClearedCount, uncleanedVerifyCamps,
    };
  }

  function fullDerive() {
    const D = derive();
    const { activeTodo, doneTodo, resolvedTodo, raw } = recomputeTodos(D);
    D.activeTodo = activeTodo; D.doneTodo = doneTodo; D.resolvedTodo = resolvedTodo; D.rawTodo = raw;
    ensureRedSnapshot(raw);
    D.goodChips = buildGoodChips(D);
    D.status = computeStatus(D);
    return D;
  }
  // Item 4 (hero banner partial-progress cue): captured ONCE per session (or
  // once per fresh "Run Live Audit", since resetState() wipes S.ui back to
  // {}) — the count each red to-do item carried the FIRST time it was ever
  // derived this session. Everything downstream compares a red item's live
  // count against this frozen baseline to notice "the owner paused 1 of 3
  // blacklisted domains" even though the item is still active (so the red
  // category count alone never drops) — without this, partial progress on
  // one red item is invisible: the banner's "N urgent" only ever counts
  // whole CATEGORIES resolved, never partial movement within one.
  function ensureRedSnapshot(raw) {
    if (!S.ui) S.ui = {};
    if (S.ui.redSnapshot) return;
    const snap = {};
    raw.forEach((it) => { if (it.level === "red" && !it.resolved && it.key) snap[it.key] = Number(it.count); });
    S.ui.redSnapshot = snap;
    saveState();
  }

  /* ============================================================
     4. Ephemeral UI state (not persisted — resets on reload)
     ============================================================ */
  const UI = {
    mgr: { view: "domain", batch: "", search: "", sel: new Set(), domFilter: "resting" },
    dh: { minSent: null, cutoff: null, start: null, end: null },
    sig: { batch: "", search: "" },
    pn: { search: "" },
    wu: { search: "" },
    delist: { includeYoung: false },
    coachOpen: false, // Part B1: transient "re-opened the coach via Show tips" flag
  };

  /* Sub-tab shell — pulls the three heavy sections (Blacklisted domains,
     Inbox & domain manager, Performance by batch) out of the Overview scroll
     into their own tab panels. Persisted (unlike the ephemeral UI above) so a
     mid-session reload lands back on whichever sub-tab the owner was using. */
  const DLV_SUBTABS = [
    ["overview", "Overview"],
    ["blacklist", "Blacklisted domains"],
    ["manager", "Inbox & domain manager"],
    ["batch", "Performance by batch"],
    ["reminders", "Restore reminders"],
  ];
  let dlvSubtab = "overview";
  function loadSubtab() {
    try {
      const v = sessionStorage.getItem("dlv_subtab");
      if (v && DLV_SUBTABS.some(([id]) => id === v)) dlvSubtab = v;
    } catch (e) {}
  }
  function setSubtab(id) {
    dlvSubtab = id;
    try { sessionStorage.setItem("dlv_subtab", id); } catch (e) {}
  }

  /* ============================================================
     5. CSS injection — one <style id="dlv-styles">, every new
        selector prefixed .dlv-. Existing navreo.css component
        classes (.card/.pill/.btn/.small/.muted/.eyebrow/.tabs/.tab)
        are reused unprefixed straight from navreo.css.
     ============================================================ */
  function injectStyles() {
    if ($id("dlv-styles")) return;
    const css = `
.dlv{font-family:var(--font-sans);color:var(--ink)}
.dlv-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
/* Fix #2 (holdout VA): "Run Live Audit" is destructive but sat first in the row,
   shoulder-to-shoulder with harmless Copy/Slack buttons. It now lives at the far
   right behind a visible divider, with a caution (red-outline) treatment that is
   deliberately NOT the solid .btn.danger used at final confirm points. */
.dlv-hdr-sep{width:1px;align-self:stretch;min-height:22px;background:var(--line-2);margin:0 8px;flex-shrink:0}
/* Part C(d): the caution treatment was too subtle — the owner still read Run
   Live Audit as a normal button. Strengthen it with a solid 2px red border, a
   heavier weight, and a small ⚠ so it visibly stands apart from the harmless
   Copy/Slack/Notion buttons to its left (still NOT the solid .btn.danger used
   at final confirm points). */
.dlv-btn-caution{background:var(--red-bg);border:2px solid var(--red);color:#861E10;font-weight:700;box-shadow:0 0 0 3px rgba(200,40,20,.08)}
.dlv-btn-caution:hover{background:var(--red);border-color:var(--red);color:#fff}
.dlv-banner{display:flex;align-items:center;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;margin:16px 0 22px}
.dlv-dot{width:12px;height:12px;border-radius:50%;flex-shrink:0}
.dlv-dot.g{background:var(--green)} .dlv-dot.a{background:var(--amber)} .dlv-dot.r{background:var(--red)}
.dlv-banner h2{font-size:16px;font-weight:600}
.dlv-banner .sub{font-size:12.5px;color:var(--ink-3);margin-top:3px}
.dlv-section-title{font-size:11px;color:var(--ink-3);text-transform:uppercase;letter-spacing:.08em;font-weight:600;margin:26px 0 12px}
.dlv-fleet-group{margin-bottom:18px}
.dlv-fleet-glabel{font-size:11px;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600;margin-bottom:8px}
/* Design-fix (Fleet-by-the-numbers restyle): tiles now reuse navreo.css's own
   .stat/.lab/.num-hero/.hint straight from the shared stylesheet (already loaded
   on this page) so they match the Dashboard's stat tiles font-for-font instead of
   defining their own (smaller, taller-bodied) look. .dlv-stat only ADDS the
   severity left-border + number tint on top of that shared component — it no
   longer redefines background/border/radius/padding/font-size. The grid wraps
   at a wider min column and drops the old cramped gap; align-items:start (grid
   items stretch to the tallest row-mate by default) stops one long tile from
   forcing every tile in its row to inflate to match it. */
.dlv-stat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;align-items:start}
.dlv-stat{border-left:3px solid var(--line-2)}
.dlv-stat .num-hero{color:var(--green)}
.dlv-stat-csv{margin-top:8px;display:flex;flex-direction:column;gap:4px;align-items:flex-start}
.dlv-stat.warn{border-left-color:var(--amber)} .dlv-stat.warn .num-hero{color:var(--amber)}
.dlv-stat.bad{border-left-color:var(--red)} .dlv-stat.bad .num-hero{color:var(--red)}
.dlv-dl{font-size:11.5px;font-weight:600;color:var(--orange-700);text-decoration:none;cursor:pointer}
.dlv-dl:hover{text-decoration:underline}
.dlv-todo-head{display:flex;align-items:center;gap:10px;font-size:17px;font-weight:600;margin:6px 0 12px}
.dlv-todo-count{display:inline-flex;align-items:center;justify-content:center;min-width:24px;height:24px;padding:0 7px;border-radius:12px;background:var(--orange);color:#fff;font-size:12.5px;font-weight:700}
.dlv-actions-list{display:flex;flex-direction:column;gap:11px}
.dlv-ai{display:flex;flex-wrap:wrap;gap:13px;align-items:flex-start;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line-2);border-radius:12px;padding:16px 18px}
.dlv-ai.red{border-left-color:var(--red)} .dlv-ai.yellow{border-left-color:var(--amber)} .dlv-ai.note{border-left-color:var(--ink-3)} .dlv-ai.done{opacity:.65}
.dlv-ai-n{flex-shrink:0;width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12.5px;font-weight:700;color:#fff}
.dlv-ai-n.red{background:var(--red)} .dlv-ai-n.yellow{background:var(--amber)} .dlv-ai-n.note{background:var(--ink-3)}
.dlv-ai-body{flex:1;min-width:0}
.dlv-ai-text{font-weight:600;font-size:14px}
.dlv-ai-action{font-size:12.5px;color:var(--ink-3);margin-top:5px}
.dlv-ai-action .arrow{color:var(--orange-700);font-weight:700;margin-right:4px}
.dlv-ai-btns{display:flex;gap:7px;flex-wrap:wrap;flex-shrink:0;align-self:center}
.dlv-all-clear{background:var(--green-bg);border:1px solid var(--green-line);border-radius:12px;padding:24px;text-align:center}
.dlv-all-clear .big{font-size:19px;font-weight:600;color:#195C3F}
.dlv-all-clear .sub{font-size:12.5px;color:var(--ink-3);margin-top:6px}
.dlv-good-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.dlv-good-chip{font-size:12px;color:#195C3F;background:var(--green-bg);border:1px solid var(--green-line);border-radius:8px;padding:6px 11px}
details.dlv-fold{border:1px solid var(--line);border-radius:12px;background:var(--card);margin-top:12px;overflow:hidden}
details.dlv-fold>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:9px;padding:14px 16px;font-size:14px;font-weight:600;user-select:none}
details.dlv-fold>summary::-webkit-details-marker{display:none}
details.dlv-fold>summary .hint{font-weight:500;font-size:12px;color:var(--ink-3)}
details.dlv-fold>summary::after{content:'▸ open';margin-left:auto;font-size:11.5px;font-weight:600;color:var(--ink-3)}
details.dlv-fold[open]>summary::after{content:'▾ close'}
details.dlv-fold[open]>summary{border-bottom:1px solid var(--line)}
/* Defect D fix: don't rely solely on the UA stylesheet's native collapse of a
   closed <details> (some rendering contexts don't apply it), so a closed fold
   still shows its tiles. Force it explicitly — every direct non-summary child
   is hidden unless the details carries [open]. */
details.dlv-fold:not([open])>*:not(summary){display:none}
.dlv-fold-body{padding:16px}
/* Sub-tab shell -- the 4 tabs reuse the app's own .tabs/.tab classes for visual
   consistency (see campaigns.html's detail-view tabs); .dlv-subtabs only adds
   wrapping so a narrow viewport never clips a tab label off-screen. Moved
   sections (Blacklisted domains / Inbox and domain manager / Performance by
   batch) render as an always-expanded .dlv-subtab-panel -- same card look as
   a details.dlv-fold fold, minus the collapse/toggle behaviour, since these
   are now permanent tab panels rather than folds. */
.dlv-subtabs{flex-wrap:wrap;margin:14px 0 18px}
.dlv-subtab-panel{border:1px solid var(--line);border-radius:12px;background:var(--card);overflow:hidden}
.dlv-subtab-head{display:flex;align-items:center;gap:9px;padding:14px 16px;font-size:14px;font-weight:600;border-bottom:1px solid var(--line)}
.dlv-subtab-head .hint{font-weight:500;font-size:12px;color:var(--ink-3)}
.dlv-subtab-panel.dlv-flash{animation:dlvFlash 1.5s ease-out}
.dlv-vcamps{display:flex;flex-direction:column;gap:9px;margin-top:8px}
.dlv-vcamp{background:var(--bg-sunken);border:1px solid var(--line);border-radius:9px;padding:10px 12px;display:flex;flex-wrap:wrap;align-items:center;gap:9px}
.dlv-vcamp a{font-weight:600;color:var(--ink);text-decoration:none} .dlv-vcamp a:hover{color:var(--orange-700)}
.dlv-vmeta{font-size:11.5px;color:var(--ink-3)}
.dlv-vbtns{margin-left:auto;display:flex;gap:7px;flex-wrap:wrap}
.dlv-vresult{flex-basis:100%}
.dlv-vbox{margin-top:4px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:11px;font-size:12.5px;display:flex;flex-direction:column;gap:6px}
.dlv-vrow b{color:var(--ink)} .dlv-vkeep b{color:var(--green)} .dlv-vremove b{color:var(--red)}
.dlv-vrun{font-size:12px;color:var(--ink-3)}
.dlv-badge-cleaned{font-size:11px;font-weight:700;color:#195C3F;background:var(--green-bg);border-radius:999px;padding:3px 9px}
.dlv-bl-summary{font-size:13px;font-weight:500;margin-bottom:10px}
.dlv-bl-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.dlv-bl-scroll{max-height:340px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:8px;background:var(--bg-sunken)}
.dlv-view-scroll{max-height:56vh;overflow:auto;border:1px solid var(--line);border-radius:8px}
.dlv-view-scroll table.tbl{margin:0}
.dlv-view-scroll table.tbl thead th{position:sticky;top:0;background:var(--card);z-index:1}
.dlv-tag{display:inline-block;font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:999px;white-space:nowrap}
.dlv-tag.blocked{background:var(--red-bg);color:#861E10} .dlv-tag.inactive{background:var(--amber-bg);color:#6B4A00}
.dlv-tag.md{background:#F2F2F0;color:var(--ink-2)} .dlv-tag.ok{background:var(--green-bg);color:#195C3F}
.dlv-mb-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
.dlv-mb-bar select,.dlv-mb-bar input[type=text],.dlv-mb-bar input[type=date],.dlv-mb-bar input[type=number]{font-family:var(--font-sans);font-size:12.5px;border:1px solid var(--line-2);border-radius:8px;padding:7px 10px;background:var(--card);color:var(--ink)}
.dlv-mb-bar input[type=text]{flex:1;min-width:160px}
.dlv-mb-count{font-size:11.5px;color:var(--ink-3)}
.dlv-mb-wrap{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.dlv-mb-scroll{max-height:420px;overflow:auto}
table.dlv-mb{width:100%;border-collapse:collapse;font-size:12.5px}
table.dlv-mb th{position:sticky;top:0;background:var(--bg-sunken);text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-3);font-weight:600;padding:9px 11px;z-index:1}
table.dlv-mb td{padding:8px 11px;border-top:1px solid var(--line);vertical-align:middle}
table.dlv-mb tr:hover td{background:var(--bg-sunken)}
.dlv-mb-email{font-weight:600} .dlv-mb-dom{font-size:11px;color:var(--ink-3)}
.dlv-mb-reason{font-size:11px;color:var(--ink-3);max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
table.dlv-mb th.ck,table.dlv-mb td.ck{width:32px;text-align:center;padding-right:0}
table.dlv-mb input[type=checkbox]{width:15px;height:15px;cursor:pointer;accent-color:var(--orange)}
.dlv-bt-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table.dlv-bt{width:100%;border-collapse:collapse;font-size:12.5px}
table.dlv-bt th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-3);font-weight:600;padding:9px 12px;border-bottom:1px solid var(--line);background:var(--bg-sunken);white-space:nowrap}
table.dlv-bt td{padding:9px 12px;border-bottom:1px solid var(--line)}
table.dlv-bt tbody tr:last-child td{border-bottom:none}
table.dlv-bt th:not(:first-child),table.dlv-bt td:not(:first-child){text-align:right;white-space:nowrap}
.dlv-bt-name{font-weight:600}
.dlv-bt-g{color:var(--green);font-weight:700} .dlv-bt-y{color:var(--amber);font-weight:700} .dlv-bt-r{color:var(--red);font-weight:700} .dlv-bt-mut{color:var(--ink-3)}
.dlv-bt-summary{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px}
.dlv-bt-sum{font-size:12.5px;padding:9px 13px;border-radius:9px;border:1px solid var(--line);flex:1;min-width:240px}
.dlv-bt-sum.best{background:var(--green-bg);border-color:var(--green-line);color:#195C3F}
.dlv-bt-sum.worst{background:var(--red-bg);border-color:var(--red-line);color:#861E10}
.dlv-rem-add{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.dlv-rem-add input[type=text]{flex:1;min-width:220px}
.dlv-rem-add input[type=text],.dlv-rem-add input[type=date]{font-family:var(--font-sans);font-size:13px;padding:9px 11px;border:1px solid var(--line-2);border-radius:8px;background:var(--card);color:var(--ink)}
.dlv-rem-row{display:flex;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid var(--line)}
.dlv-rem-row:last-child{border-bottom:none}
.dlv-rem-row.done{opacity:.6}
.dlv-rem-main{flex:1;min-width:0}
.dlv-rem-doms{font-weight:600;font-size:13px;word-break:break-word}
.dlv-rem-meta{font-size:11.5px;color:var(--ink-3);margin-top:2px}
.dlv-rem-health{font-size:12px;color:var(--ink-3);margin-top:6px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dlv-rem-health b{color:var(--ink)}
.dlv-rem-acts{display:flex;gap:7px;align-items:center;flex-shrink:0}
.dlv-rem-tag{font-size:10.5px;font-weight:700;padding:3px 8px;border-radius:6px;white-space:nowrap}
.dlv-rem-tag.due{color:#861E10;background:var(--red-bg)} .dlv-rem-tag.wait{color:var(--ink-3);background:#F2F2F0} .dlv-rem-tag.done{color:#195C3F;background:var(--green-bg)}
.dlv-dl-row{display:flex;gap:12px;align-items:center;padding:11px 0;border-bottom:1px solid var(--line)}
.dlv-dl-row:last-child{border-bottom:none}
.dlv-dl-row.done{opacity:.55}
.dlv-dl-main{flex:1;min-width:0}
.dlv-dl-dom{font-weight:600;font-size:13.5px}
.dlv-dl-tag{font-size:10.5px;color:var(--green);font-weight:700;margin-left:6px}
.dlv-dl-meta{font-size:11.5px;color:var(--ink-3);margin-top:2px}
.dlv-dl-links{margin-top:5px;display:flex;gap:12px}
.dlv-dl-acts{display:flex;gap:7px;flex-shrink:0}
.dlv-sig-trow{display:flex;justify-content:space-between;gap:10px;padding:6px 11px;font-size:12px;border-bottom:1px solid var(--line)}
.dlv-sig-trow:last-child{border-bottom:none}
.dlv-sig-email{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dlv-sig-when{color:var(--ink-3);white-space:nowrap;flex-shrink:0}
.dlv-modal-overlay{position:fixed;inset:0;background:rgba(20,17,14,.45);display:none;align-items:center;justify-content:center;padding:24px;z-index:200}
.dlv-modal-overlay.show{display:flex}
/* Part B4: an opening confirm/modal must draw the eye — a brief backdrop fade
   plus a scale/opacity pop on the dialog itself, so a click that opens a
   confirm is unmistakable (testers previously read an opened confirm as
   "nothing happened"). */
@keyframes dlvOverlayFade{from{background:rgba(20,17,14,0)}to{background:rgba(20,17,14,.45)}}
@keyframes dlvModalPop{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:scale(1)}}
.dlv-modal-overlay.show{animation:dlvOverlayFade .18s ease-out}
.dlv-modal-overlay.show .dlv-modal{animation:dlvModalPop .2s cubic-bezier(.2,.9,.3,1.2)}
/* The confirm dialog gets an extra-strong (darker) backdrop dim + fade so the
   commitment point in particular is impossible to miss. */
@keyframes dlvConfirmFade{from{background:rgba(20,17,14,0)}to{background:rgba(20,17,14,.66)}}
#dlv-confirm-overlay{background:rgba(20,17,14,.66)}
#dlv-confirm-overlay.show{animation:dlvConfirmFade .18s ease-out}
.dlv-modal{background:var(--card);border:1px solid var(--line);border-radius:16px;max-width:720px;width:100%;max-height:86vh;display:flex;flex-direction:column;box-shadow:0 30px 80px rgba(20,17,14,.35)}
.dlv-modal.narrow{max-width:460px}
.dlv-modal.wide{max-width:860px}
.dlv-modal-head{display:flex;align-items:center;justify-content:space-between;padding:18px 22px;border-bottom:1px solid var(--line);flex-shrink:0}
.dlv-modal-head h3{font-size:15px;font-weight:600}
.dlv-modal-head .x{background:transparent;border:none;font-size:20px;color:var(--ink-3);cursor:pointer;padding:0 6px}
.dlv-modal-body{padding:20px 22px;overflow:auto;flex:1 1 auto;min-height:0}
.dlv-modal-foot{padding:14px 22px;border-top:1px solid var(--line);display:flex;justify-content:flex-end;gap:9px;flex-wrap:wrap;flex-shrink:0}
.dlv-modal pre{margin:0;white-space:pre-wrap;font-family:var(--font-mono);font-size:12.5px;line-height:1.5}
.dlv-field-label{font-size:12px;font-weight:600;margin-bottom:6px;display:block}
.dlv-field-hint{font-weight:400;color:var(--ink-3);font-size:11.5px}
.dlv-input,.dlv-select,.dlv-textarea{width:100%;font-family:var(--font-sans);font-size:13.5px;padding:10px 11px;border:1px solid var(--line-2);border-radius:9px;background:var(--card);color:var(--ink)}
.dlv-textarea{font-family:var(--font-mono);resize:vertical}
.dlv-preview{margin-top:8px;padding:11px;background:var(--bg-sunken);border:1px solid var(--line);border-radius:9px;white-space:pre-wrap;font-size:12.5px;font-family:var(--font-mono)}
/* Stacked toast container (defect B fix — replaces the old single-node queue):
   each toast() call appends its own independent node; several can be visible
   at once, newest at the bottom of the column.
   Defect 2: explicitly the highest z-index of any .dlv- overlay (modal 200,
   confirm 260, glossary popover 290) with real headroom above all three, so
   a receipt toast fired while a modal is still open/closing is never
   rendered underneath it — verified live via getBoundingClientRect() +
   isConnected at fire time for signature-apply / Notion sync / Slack send /
   copy. */
.dlv-toast-stack{position:fixed;bottom:26px;left:50%;transform:translateX(-50%);display:flex;flex-direction:column;gap:10px;align-items:center;z-index:500;pointer-events:none}
.dlv-toast{position:relative;overflow:hidden;background:var(--ink);color:#fff;border-radius:10px;padding:12px 20px;font-size:13.5px;opacity:0;transform:translateY(16px);transition:opacity .25s,transform .25s;pointer-events:none;box-shadow:0 12px 40px rgba(20,17,14,.3);max-width:min(420px,80vw)}
.dlv-toast.show{opacity:1;transform:translateY(0);pointer-events:auto}
.dlv-toast.ok{background:var(--green)} .dlv-toast.err{background:var(--red)}
.dlv-spinner{width:14px;height:14px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:dlvspin .7s linear infinite;display:inline-block;vertical-align:middle}
.dlv-spinner.ink{border-color:rgba(20,17,14,.2);border-top-color:var(--orange-700)}
@keyframes dlvspin{to{transform:rotate(360deg)}}
.dlv-empty{color:var(--ink-3);text-align:center;padding:60px 0;font-size:14px}
/* Stage-A data-source banner (sample-data notice / running-audit strip). */
.dlv-data-banner{display:flex;align-items:center;gap:10px;padding:9px 13px;border-radius:9px;margin-bottom:14px;font-size:13px;line-height:1.45;border:1px solid transparent}
.dlv-data-banner .dlv-data-banner-txt{flex:1}
.dlv-data-banner.sample{background:var(--amber-50,#fdf6e3);border-color:var(--amber-200,#e7d5a3);color:var(--ink-2)}
.dlv-data-banner.running{background:var(--surface-2,#f4efe8);border-color:var(--border,#e2d8cb);color:var(--ink-2)}
.dlv-data-banner.err{background:var(--red-50,#fdeceb);border-color:var(--red-200,#f0bcb7);color:var(--ink-2)}
.dlv-data-banner-x{background:transparent;border:0;color:var(--ink-3);font-size:20px;line-height:1;cursor:pointer;padding:0 4px}
.dlv-data-banner-x:hover{color:var(--ink)}
.dlv-footer{margin-top:30px;color:var(--ink-3);font-size:11.5px;text-align:center}
.dlv-confirm-body{font-size:13.5px;color:var(--ink-2);white-space:pre-wrap;line-height:1.55}
#dlv-confirm-overlay{z-index:260}
.dlv-plain{font-size:11.5px;color:var(--ink-3);margin-top:4px;line-height:1.4}
/* Hint-sized (matches .hint's 11.5px/brown-400) so the state-derived
   breakdown lines (Warmup's "3 to warm up + 2 due back", Signature issues'
   "N missing · N mismatch", etc.) stay compact instead of reading as body copy. */
.dlv-stat-plain{font-size:11.5px;color:var(--brown-400);margin-top:4px;line-height:1.3}
.dlv-mb-cap{font-size:10.5px;color:var(--ink-3);font-weight:600;text-transform:uppercase;letter-spacing:.04em;align-self:center}
.dlv-todo-resolved-label{font-size:11px;color:var(--ink-3);font-weight:600;margin-top:14px;margin-bottom:-2px}
.dlv-resolved-chip{opacity:.9}
.dlv-signpost-row{display:flex;flex-wrap:wrap;gap:16px;margin-top:10px}
.dlv-toast-row{display:flex;align-items:center;gap:10px}
.dlv-toast-hint{font-size:11.5px;opacity:.85;margin-top:5px}
.dlv-toast-hint a{color:#fff;cursor:pointer;text-decoration:underline}
.dlv-toast-undo{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.4);color:#fff;border-radius:6px;padding:3px 9px;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap}
.dlv-toast-undo:hover{background:rgba(255,255,255,.28)}
@keyframes dlvFlash{0%{box-shadow:0 0 0 3px var(--orange-700)}70%{box-shadow:0 0 0 3px var(--orange-700)}100%{box-shadow:0 0 0 0 rgba(0,0,0,0)}}
details.dlv-fold.dlv-flash{animation:dlvFlash 1.5s ease-out}
.dlv-todo-anchor.dlv-flash{animation:dlvFlash 1.5s ease-out;border-radius:12px}
.dlv-health-strip{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 22px}
.dlv-health-chip{flex:1 1 220px;min-width:220px;border:1px solid var(--line);border-left:4px solid var(--line-2);border-radius:10px;padding:12px 16px;font-size:13.5px;font-weight:600;line-height:1.4;background:var(--card)}
.dlv-health-chip.g{border-left-color:var(--green);color:#195C3F;background:var(--green-bg)}
.dlv-health-chip.a{border-left-color:var(--amber);color:#6B4A00;background:var(--amber-bg)}
.dlv-health-chip.r{border-left-color:var(--red);color:#861E10;background:var(--red-bg)}
.dlv-health-chip[data-act]{cursor:pointer}
.dlv-health-chip[data-act]:hover{filter:brightness(.96)}
/* Part C(c): one-glance verdict line — the single leading sentence above the
   chip row that reads out the overall state in plain English for the owner
   persona (who otherwise had to assemble a verdict from 4 separate chips). */
.dlv-verdict{display:flex;align-items:flex-start;gap:10px;border:1px solid var(--line);border-left:5px solid var(--line-2);border-radius:12px;padding:13px 17px;margin:0 0 12px;font-size:14.5px;font-weight:700;line-height:1.4;background:var(--card)}
.dlv-verdict.g{border-left-color:var(--green);color:#195C3F;background:var(--green-bg)}
.dlv-verdict.a{border-left-color:var(--amber);color:#6B4A00;background:var(--amber-bg)}
.dlv-verdict.r{border-left-color:var(--red);color:#861E10;background:var(--red-bg)}
.dlv-verdict .vdot{font-size:16px;line-height:1.25}
/* Part B1: first-run onboarding coach — a dismissible, non-blocking callout at
   the very top of the tab. On-brand card treatment, amber accent so it reads
   as guidance not an alert. */
.dlv-coach{position:relative;border:1px solid var(--orange-700);border-left:5px solid var(--orange-700);border-radius:14px;padding:16px 44px 16px 18px;margin:0 0 18px;background:var(--amber-bg,rgba(200,140,20,.12))}
.dlv-coach h3{font-size:14.5px;font-weight:700;color:#6B4A00;margin:0 0 8px}
.dlv-coach ul{margin:0 0 12px;padding-left:2px;list-style:none}
.dlv-coach li{font-size:12.8px;color:var(--ink-2);line-height:1.5;margin:4px 0;padding-left:20px;position:relative}
.dlv-coach li::before{content:"▸";position:absolute;left:2px;color:var(--orange-700);font-weight:700}
.dlv-coach .dlv-coach-x{position:absolute;top:10px;right:12px;background:transparent;border:none;font-size:20px;color:var(--ink-3);cursor:pointer;line-height:1;padding:0 4px}
.dlv-coach .dlv-coach-x:hover{color:var(--ink)}
.dlv-coach .dlv-coach-got{background:var(--orange-700);color:#fff;border:none;border-radius:8px;padding:8px 16px;font-size:12.5px;font-weight:700;cursor:pointer}
.dlv-coach .dlv-coach-got:hover{filter:brightness(1.08)}
.dlv-tips-btn{background:transparent;border:1px solid var(--line-2);border-radius:8px;color:var(--ink-3);font-size:12.5px;font-weight:600;cursor:pointer;padding:8px 12px}
.dlv-tips-btn:hover{border-color:var(--orange-700);color:var(--orange-700)}
/* Part B2: first-load pulse on the first "?" glossary marker so a new user
   notices the affordance is interactive. Fires once per browser, then never
   again (dlv_gloss_hint_seen in localStorage). */
@keyframes dlvGlossPulse{0%{box-shadow:0 0 0 0 var(--orange-700)}70%{box-shadow:0 0 0 7px rgba(200,140,20,0)}100%{box-shadow:0 0 0 0 rgba(200,140,20,0)}}
.dlv-gloss.dlv-gloss-pulse{animation:dlvGlossPulse 1.1s ease-out 3}
/* Part B3: signature modal — disabled Apply + helper text until a brand chosen. */
.dlv-sig-helper{font-size:12px;color:var(--orange-700);font-weight:600;margin:0 0 6px;display:none}
.dlv-sig-helper.show{display:block}
.btn.primary:disabled,.btn:disabled{opacity:.45;cursor:not-allowed;filter:grayscale(.2)}
.dlv-gloss{cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:13px;height:13px;min-width:13px;border-radius:50%;background:var(--amber-bg,rgba(200,140,20,.14));color:var(--orange-700);font-weight:700;font-size:9.5px;line-height:1;vertical-align:super;margin-left:3px;border:1px solid var(--orange-700);user-select:none;opacity:.62;transition:background .15s,color .15s,opacity .15s}
.dlv-gloss:hover,.dlv-gloss:focus-visible{background:var(--orange-700);color:#fff;opacity:1}
.dlv-gloss-pop{position:fixed;z-index:290;max-width:260px;background:var(--ink);color:#fff;border-radius:9px;padding:11px 30px 11px 13px;font-size:12.5px;line-height:1.45;box-shadow:0 16px 40px rgba(20,17,14,.35);display:none;pointer-events:none}
.dlv-gloss-pop.show{display:block}
/* Root cause (defect #3, glossary reopen): with several "?" markers packed
   close together (stacked stat tiles, adjacent jargon in one sentence), the
   popover's own box — positioned just below/above whichever trigger opened
   it — regularly lands directly on top of a NEIGHBOURING "?" the user
   clicks next. That click was landing on the (inert, except for its ×) pop
   body instead of the trigger underneath: not an outside click (so the
   existing dismiss-on-outside-click logic never fired) and not the ×, so it
   was silently swallowed — indistinguishable from "the ? does nothing".
   pointer-events:none on the box (with the × explicitly opted back in
   below) makes every other click pass straight through to whatever is
   actually underneath it — the next "?" (which then opens normally) or the
   real page background (which now correctly counts as an outside click and
   closes this popover via dispatchDlvClick's existing check). */
.dlv-gloss-pop .x{position:absolute;top:5px;right:9px;cursor:pointer;color:rgba(255,255,255,.7);font-size:14px;line-height:1;pointer-events:auto}
.dlv-gloss-pop .x:hover{color:#fff}
/* Item 2: floating manual-copy fallback — shown only when BOTH the async
   Clipboard API and execCommand("copy") fail, for the copy actions whose
   source text isn't rendered anywhere on screen (delisting request / all
   domains). Pre-selected on open so a Ctrl/Cmd+C works with zero hunting. */
.dlv-copy-fallback{position:fixed;z-index:295;width:300px;max-width:calc(100vw - 32px);background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:10px;box-shadow:0 16px 40px rgba(20,17,14,.35);padding:11px;display:none}
.dlv-copy-fallback.show{display:block}
.dlv-copy-fallback-head{font-size:11px;color:var(--ink-3);margin-bottom:7px;display:flex;justify-content:space-between;align-items:center;gap:8px}
.dlv-copy-fallback-head .x{cursor:pointer;color:var(--ink-3);font-size:15px;line-height:1}
.dlv-copy-fallback-head .x:hover{color:var(--ink)}
#dlv-copy-fallback-ta{width:100%;min-height:74px;font-family:var(--font-mono);font-size:12px;border:1px solid var(--line-2);border-radius:8px;padding:8px;resize:vertical;background:var(--bg-sunken);color:var(--ink)}
.dlv-toast-bar{position:absolute;left:0;bottom:0;height:3px;width:100%;background:rgba(255,255,255,.5);transform-origin:left center}
/* Item 2: temporary success state flashed onto the clicked control itself —
   a durable near-click receipt that survives a missed toast. */
.dlv-btn-flash{background:var(--green)!important;color:#fff!important;border-color:var(--green)!important;text-decoration:none!important;transition:background .15s,color .15s}
/* Item 5d: thin divider between the two per-campaign verify buttons so
   "✓ ListMint" and "✓ MillionVerifier → ListMint" never read as one control. */
.dlv-vsep{width:1px;align-self:stretch;background:var(--line-2);margin:0 4px;flex-shrink:0}
/* Item 1: group labels inside the Recent-actions fold — seed rows ("earlier")
   vs rows written by this session ("today — this session"). */
.dlv-hist-glabel{font-size:10.5px;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em;font-weight:700;margin:4px 0 2px}
.dlv-ai.dlv-hist-sess{border-left-color:var(--orange)!important}
/* Fix #1 (holdout VA): temporary in-place stub left where a just-marked-done
   to-do card was — a toast-independent trace with its own Undo + a link to the
   ✅ Actioned fold. .dlv-stub-out animates the ~12s auto-collapse. */
.dlv-done-stub{display:flex;align-items:center;gap:6px;flex-wrap:wrap;background:var(--green-bg);border:1px solid var(--green-line);border-left:4px solid var(--green);border-radius:12px;padding:10px 18px;font-size:12.5px;font-weight:600;color:#195C3F;overflow:hidden;max-height:90px;transition:max-height .4s ease,opacity .4s ease,padding .4s ease,margin .4s ease,border-width .4s ease}
.dlv-done-stub a{color:#195C3F;text-decoration:underline;cursor:pointer;font-weight:700}
.dlv-done-stub a:hover{color:#0E3D29}
.dlv-stub-what{color:var(--ink-3);font-weight:500;margin-left:6px;font-size:11.5px}
.dlv-done-stub.dlv-stub-out{max-height:0;opacity:0;padding-top:0;padding-bottom:0;margin-top:-11px;border-top-width:0;border-bottom-width:0}
/* Item 5a: inline red hint under the reminder-add form (no toast needed). */
.dlv-rem-err{display:none;color:var(--red);font-size:12px;font-weight:600;margin:-6px 0 10px}
.dlv-rem-err.show{display:block}
.dlv-input.dlv-input-err{border-color:var(--red)}
`;
    const st = document.createElement("style");
    st.id = "dlv-styles";
    st.textContent = css;
    document.head.appendChild(st);
  }

  /* ============================================================
     6. Toast + confirm dialog (namespaced, never native confirm())
     ============================================================ */
  // Defect B fix — root cause of the "queued toast replays on an unrelated
  // click" / "undo toast cut short" reports: the previous design used ONE
  // shared DOM node for every toast, so a second toast arriving while an undo
  // toast was alive either clobbered it outright or (the last round's "fix")
  // got queued and silently replayed later on whatever the user happened to
  // click next — which is exactly the "Marked done ↩ Undo toast replayed on
  // an unrelated Pause click" bug. Simplest correct design: every toast is its
  // own independent DOM node appended to a stack container (#dlv-toast-stack,
  // a persistent node outside #dlv-root/#main so it survives every repaint,
  // same as before) — multiple toasts can be visible at once, newest at the
  // bottom, each with its own timer. No queue, nothing to replay.
  function dismissToastEl(el) {
    if (!el || el._dismissed) return;
    el._dismissed = true;
    clearTimeout(el._t);
    clearInterval(el._bar);
    el.onmouseenter = null; el.onmouseleave = null;
    el.classList.remove("show");
    setTimeout(() => el.remove(), 260); // let the fade-out transition finish first
  }
  // Defect B root-cause hardening: `$id("dlv-toast-stack")` finding a node by
  // id says nothing about whether that node is still ATTACHED to the document
  // — a node can keep its id and still be `isConnected === false` if it was
  // ever detached (e.g. an ancestor got replaced by an innerHTML reset that
  // didn't go through this file's own paintPage() guard, or a stale reference
  // survived a full-page navigation/restore). Appending a toast to a detached
  // node "succeeds" with no error and no visible toast — indistinguishable
  // from a real silent failure. ensureModals() already knows how to
  // (re)create every persistent node correctly, so re-run it and re-resolve
  // the stack whenever the one we found isn't actually on-page.
  function toastStack() {
    let stack = $id("dlv-toast-stack");
    if (!stack || !stack.isConnected) {
      ensureModals();
      stack = $id("dlv-toast-stack");
    }
    return stack;
  }
  function toast(msg, kind, opts) {
    const stack = toastStack();
    if (!stack) return;
    opts = opts || {};
    const el = document.createElement("div");
    el.className = "dlv-toast " + (kind || "");
    if (opts.undoKey) {
      // Undo toasts get a 10s window, a visible countdown bar, a hover-pause
      // so reading the message or moving the mouse toward Undo doesn't race
      // the dismiss timer, and a second line pointing at the durable fallback
      // (defect H) — if the toast is missed entirely, the same undo is always
      // still reachable afterwards.
      // Defect 3: this hint used to say "Recent actions ↓" and scroll to the
      // history fold — but the per-item ↩ Undo button this toast is offering
      // a fallback for actually lives in the "✅ Actioned" fold, a completely
      // different section. Name + scroll to the fold that actually holds it
      // (renderHistoryFold() below also now mirrors the same Undo into Recent
      // actions, so either path works regardless of which one this points to).
      el.innerHTML = `<div class="dlv-toast-row"><span>${esc(msg)}</span><button type="button" class="dlv-toast-undo" data-act="toast-undo" data-key="${esc(opts.undoKey)}">↩ Undo</button></div>` +
        `<div class="dlv-toast-hint">or undo later from <a data-act="scroll-actioned">✅ Actioned ↓</a></div>` +
        `<div class="dlv-toast-bar"></div>`;
      const dur = 10000;
      const bar = el.querySelector(".dlv-toast-bar");
      let remaining = dur, last = Date.now();
      const tick = () => {
        const now = Date.now();
        remaining -= (now - last);
        last = now;
        if (bar) bar.style.transform = "scaleX(" + Math.max(0, remaining / dur) + ")";
        if (remaining <= 0) dismissToastEl(el);
      };
      if (bar) bar.style.transform = "scaleX(1)";
      el._bar = setInterval(tick, 100);
      el.onmouseenter = () => { clearInterval(el._bar); };
      el.onmouseleave = () => { last = Date.now(); el._bar = setInterval(tick, 100); };
    } else {
      el.textContent = msg;
      el._t = setTimeout(() => dismissToastEl(el), 3200);
    }
    stack.appendChild(el);
    // A macrotask, not requestAnimationFrame — rAF callbacks are suspended
    // entirely while the document is hidden/backgrounded (spec behavior), which
    // would leave a toast permanently stuck at opacity:0 (never gets its "show"
    // class) if it's ever triggered while the tab isn't the foreground one.
    // setTimeout still fires (if throttled) in that case, and deferring one
    // macrotask past appendChild is enough for the fade-in transition to run.
    setTimeout(() => el.classList.add("show"), 0);
    return el;
  }

  let _confirmResolve = null;
  // Single source of truth for which .dlv- modal(s) are currently shown. paintPage()
  // never touches modals (they're persistent nodes outside #dlv-root), but relying on
  // classList alone let a modal that was "closed" stay stale if something later opened
  // on top of it (e.g. a dlvConfirm) without going through closeModal first — it would
  // then resurface, unprompted, once the thing on top of it closed. Routing every open
  // through openModal() below (confirm included) guarantees only one modal is ever
  // tracked/visible at a time, so closing is durable regardless of what opens next.
  const _openModalIds = new Set();
  function dlvConfirm(message, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      // Defect C root cause: if the modal markup isn't there (torn down,
      // not yet injected, or a stray partial DOM state) the old code threw
      // synchronously setting `.textContent` on null — the caller's `await
      // dlvConfirm(...)` then rejected, which reads as a normal error IF
      // toasts are visible, but as a total "dead click" whenever they're
      // not (defect B). Worse, if only SOME elements were missing, a
      // half-configured dialog could still call openModal() and appear with
      // stale/wrong content. Resolve false immediately instead of ever
      // leaving a confirm that can't be answered right now to somehow
      // answer itself later — dropped, never queued.
      const title = $id("dlv-confirm-title"), body = $id("dlv-confirm-body"), yes = $id("dlv-confirm-yes");
      if (!title || !body || !yes) { resolve(false); return; }
      // Defect 1 root cause: dlvConfirm() shares ONE overlay/title/body/yes
      // set of nodes across every caller. If a confirm is already pending
      // (the user triggered a second "Mark done" — or any other confirm —
      // before answering the first) this used to silently overwrite
      // `_confirmResolve` with the new promise, orphaning the old one
      // forever: openModal()'s own exclusivity loop skips closing the
      // overlay it's about to re-open (`if (openId !== id)`), so the
      // force-close-resolves-false safety net in closeModal() never fires
      // for a same-id restack. The FIRST caller's `await dlvConfirm(...)`
      // then hangs indefinitely — reads exactly as "the dialog sat there,
      // no resolution" for whichever item asked first. Decline the pending
      // one before starting the new one so nothing can ever be orphaned.
      if (_confirmResolve) { const prev = _confirmResolve; _confirmResolve = null; prev(false); }
      _confirmResolve = resolve;
      title.textContent = opts.title || "Please confirm";
      body.textContent = message;
      yes.textContent = opts.yesLabel || "Proceed";
      yes.className = "btn " + (opts.danger ? "danger" : "primary");
      openModal("dlv-confirm-overlay");
    });
  }
  function closeConfirm(result) {
    const r = _confirmResolve; _confirmResolve = null;
    closeModal("dlv-confirm-overlay");
    if (r) r(result);
  }

  function openModal(id) {
    // Force-close any other modal still tracked open before showing this one — this is
    // what makes a dlvConfirm opening ON TOP of an already-closed (or not-yet-closed)
    // modal safe: whatever else was open gets durably closed right here, so it can't
    // reappear later when this one closes.
    _openModalIds.forEach((openId) => { if (openId !== id) closeModal(openId); });
    // Defect 1 (suspect: "opener references a modal id ensureModals no longer
    // creates") — belt-and-braces, same pattern as toastStack(): if the node
    // this opener asked for isn't on the page for any reason, rebuild the
    // whole persistent modal set before giving up, instead of silently
    // no-op'ing (which reads as "the button does nothing").
    let el = $id(id);
    if (!el) { ensureModals(); el = $id(id); }
    if (!el) return;
    _openModalIds.add(id);
    el.classList.add("show");
  }
  function closeModal(id) {
    _openModalIds.delete(id);
    const el = $id(id);
    if (el) el.classList.remove("show");
    // Defect C ("stray delayed confirm"): force-closing the confirm overlay to
    // make room for a DIFFERENT modal (the openModal() loop above, or any
    // direct closeModal("dlv-confirm-overlay") call) used to just hide it —
    // the awaiting `dlvConfirm()` caller's promise was left pending forever.
    // Reproduced live as: open confirm A, open unrelated modal B before
    // answering A (A silently vanishes), close B — A's promise is still
    // pending, so the NEXT dlvConfirm() call anywhere later reuses the same
    // shared overlay/title/body nodes, and if the user answers slower than
    // the code expects, whichever click lands while the shared nodes still
    // carry a stale title/body can look exactly like "a confirm from a
    // totally different, earlier action reappeared". A confirm that can't be
    // answered right now is always treated as declined the instant it's
    // force-closed, never left to resolve itself on a later, unrelated click.
    if (id === "dlv-confirm-overlay" && _confirmResolve) {
      const r = _confirmResolve; _confirmResolve = null;
      r(false);
    }
  }

  /* ============================================================
     19b. Clipboard copy — with a real fallback (defect E)
     ============================================================ */
  // navigator.clipboard.writeText() reliably REJECTS in several real
  // environments this tab runs in — an unfocused document/iframe, a browser
  // without the Clipboard-write permission granted, a non-HTTPS embed, or a
  // sandboxed preview — and every copy button used to just show a bare "Copy
  // failed" with no way to actually get the text. Falls back to the old
  // hidden-textarea + document.execCommand("copy") trick, which works from a
  // synchronous user gesture even where the async Clipboard API is blocked.
  // Always resolves (never throws) and always leaves exactly one toast: a
  // real success either way, or an explicit "select manually" only when BOTH
  // paths genuinely failed.
  // `logLabel` (item 1): every successful copy now writes a typed history row —
  // copies used to leave zero durable trace beyond the 3s toast.
  // `opts.btn` (item 2 — copy must always visibly resolve): in some browsers
  // (unfocused iframe, no clipboard permission granted, a sandboxed preview)
  // BOTH the async Clipboard API and the execCommand fallback below can fail,
  // and the only sign used to be a toast that a tester could easily miss —
  // "I clicked Copy and nothing happened" with no recovery path. Every call
  // now ends in one of exactly two visible states at the clicked control
  // itself: success flashes "✓ Copied" (in addition to the toast), failure
  // flashes "✗ Select & copy manually" AND leaves the source text actually
  // selected (`opts.sourceEl`, when the text is visible on-screen in a
  // textarea/pre) or surfaces it in a small floating, pre-selected textarea
  // near the button (`showCopyFallback`, for copy actions — the delisting
  // request/all-domains buttons — whose text was never rendered anywhere on
  // screen to select in the first place) so a manual Ctrl/Cmd+C always works
  // immediately, no hunting for the text required.
  async function copyText(text, okMsg, logLabel, opts) {
    opts = opts || {};
    text = String(text == null ? "" : text);
    const logCopy = () => logAction({ action: "copy", scope: logLabel || (okMsg ? String(okMsg).replace(/^Copied\s*✓\s*(—\s*)?/i, "") : "") || "text" });
    const succeed = () => {
      logCopy();
      toast(okMsg || "Copied ✓", "ok");
      if (opts.btn) flashBtn(opts.btn, "✓ Copied");
      return true;
    };
    try {
      // navigator.clipboard.writeText() doesn't just reject in some
      // environments (unfocused document, no permission granted yet, no
      // secure context) — in a permission-"prompt" state it can also sit
      // PENDING indefinitely behind a native browser permission dialog that
      // nothing here can dismiss, so a bare `await` would hang forever and
      // never reach the execCommand fallback below (or the final toast).
      // Race it against a short timeout so a stuck/slow clipboard call always
      // still falls through instead of leaving the button looking dead. The
      // real call keeps a no-op `.catch` so a LATE rejection (after the race
      // has already moved on) never surfaces as an unhandled-rejection
      // console error.
      const clip = navigator.clipboard.writeText(text);
      clip.catch(() => {});
      await Promise.race([
        clip,
        new Promise((_, reject) => setTimeout(() => reject(new Error("clipboard timeout")), 800)),
      ]);
      return succeed();
    } catch (e) { /* fall through to the execCommand fallback below */ }
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      // Off-screen but still focusable/selectable — execCommand("copy") only
      // acts on the current selection, so the node has to be real and in the
      // document (not display:none, which excludes it from selection).
      ta.style.position = "fixed";
      ta.style.top = "0";
      ta.style.left = "-9999px";
      ta.setAttribute("readonly", "");
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, text.length);
      const ok = document.execCommand("copy");
      ta.remove();
      if (ok) return succeed();
    } catch (e2) { /* both paths failed */ }
    // Both the Clipboard API and execCommand("copy") failed — leave the text
    // genuinely selected somewhere on screen so a manual Ctrl/Cmd+C works
    // right now, and make the button state impossible to miss.
    if (opts.btn) flashBtn(opts.btn, "✗ Select & copy manually");
    selectForManualCopy(text, opts.sourceEl, opts.btn);
    toast("Clipboard blocked — text selected, press Ctrl/Cmd+C to copy", "err");
    return false;
  }
  // Selects `text` somewhere visible so the user's own Ctrl/Cmd+C can finish
  // the job. If the caller points at the real on-screen node the text came
  // from (a <textarea> or a <pre> inside a modal, e.g. the Claude-context /
  // Hypertide previews) select THAT — no extra UI, the existing element just
  // highlights. Otherwise (the delisting request/all-domains buttons have no
  // visible source node — the text is built on the fly) fall back to a small
  // floating textarea anchored near the button, pre-selected.
  function selectForManualCopy(text, sourceEl, anchorEl) {
    if (sourceEl && typeof sourceEl.select === "function") {
      try { sourceEl.focus(); sourceEl.select(); return; } catch (e) {}
    }
    if (sourceEl && sourceEl.nodeType === 1) {
      try {
        const range = document.createRange();
        range.selectNodeContents(sourceEl);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        sourceEl.scrollIntoView({ block: "center", behavior: "smooth" });
        return;
      } catch (e) { /* fall through to the floating box below */ }
    }
    showCopyFallback(text, anchorEl);
  }
  // Floating, pre-selected readonly textarea — the fallback for copy actions
  // with no visible source node on screen. Persistent node (ensureModals()),
  // positioned like the glossary popover: anchored just below the button that
  // triggered it, clamped to stay fully on screen.
  function showCopyFallback(text, anchorEl) {
    const box = $id("dlv-copy-fallback");
    const ta = $id("dlv-copy-fallback-ta");
    if (!box || !ta) return;
    ta.value = text;
    box.classList.add("show");
    box.style.transform = "";
    if (anchorEl && anchorEl.getBoundingClientRect) {
      const r = anchorEl.getBoundingClientRect();
      const margin = 8;
      const bw = box.offsetWidth || 320, bh = box.offsetHeight || 130;
      let top = r.bottom + margin;
      if (top + bh > window.innerHeight - margin) {
        const above = r.top - margin - bh;
        top = above >= margin ? above : Math.max(margin, window.innerHeight - margin - bh);
      }
      top = Math.max(margin, top);
      let left = Math.min(r.left, window.innerWidth - margin - bw);
      left = Math.max(margin, left);
      box.style.top = top + "px";
      box.style.left = left + "px";
    } else {
      box.style.top = "50%";
      box.style.left = "50%";
      box.style.transform = "translate(-50%,-50%)";
    }
    ta.focus();
    ta.select();
  }
  function closeCopyFallback() {
    const box = $id("dlv-copy-fallback");
    if (box) box.classList.remove("show");
  }

  /* Glossary click-popover (fix #4) — a lightweight floating box, deliberately
     NOT part of the full-screen _openModalIds system above (it's a small
     inline definition, not a task the user is committing to), so it can be
     open at the same time as a real modal without fighting modal exclusivity.
     Dismissed by its own × button, by clicking anywhere else (see onDlvClick),
     or implicitly whenever paintPage() repaints. */
  function openGlossaryPopover(trigger) {
    const pop = $id("dlv-gloss-pop");
    if (!pop) return;
    $id("dlv-gloss-pop-text").textContent = trigger.dataset.def || "";
    pop.classList.add("show");
    // Defect 6d: the old math assumed a fixed ~90px-tall/260px-wide box and
    // only ever clamped away from the RIGHT edge and the BOTTOM (partially —
    // never checked whether flipping above would fit either), so a "?" near
    // the top, near the bottom with a long definition, or hard against the
    // right/left edge could still render partially off-screen. Measure the
    // popover's real (content-dependent) box — it's already visible via the
    // .show class above, so offsetWidth/Height reflect the actual text —
    // and clamp every edge against it.
    const r = trigger.getBoundingClientRect();
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    const margin = 8;
    let top = r.bottom + margin;
    if (top + ph > window.innerHeight - margin) {
      const above = r.top - margin - ph;
      top = above >= margin ? above : Math.max(margin, window.innerHeight - margin - ph);
    }
    top = Math.max(margin, top);
    let left = r.left;
    left = Math.min(left, window.innerWidth - margin - pw);
    left = Math.max(margin, left);
    pop.style.top = top + "px";
    pop.style.left = left + "px";
  }
  function closeGlossaryPopover() {
    const pop = $id("dlv-gloss-pop");
    if (pop) pop.classList.remove("show");
  }

  /* ============================================================
     7. In-tool data view — datasets are still built as CSV text
        (same generators as before, so every view matches exactly
        what the old CSV export contained) but are now parsed and
        rendered as a read-only table inside a modal instead of
        ever being downloaded. No Blob, no createObjectURL, no
        <a download> anywhere in this file anymore.
     ============================================================ */
  function csvCell(v) {
    if (v == null) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function toCSV(headers, rows) {
    const lines = [headers.join(",")];
    rows.forEach((r) => lines.push(headers.map((h) => csvCell(r[h])).join(",")));
    return lines.join("\n");
  }
  // Minimal RFC4180-ish single-line parser (handles quoted fields with
  // embedded commas/escaped quotes) — enough to round-trip whatever toCSV()
  // above produced, without needing per-dataset column wiring on the view side.
  function parseCSVLine(line) {
    const out = [];
    let cur = "", inQ = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (inQ) {
        if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else inQ = false; }
        else cur += c;
      } else if (c === '"') inQ = true;
      else if (c === ",") { out.push(cur); cur = ""; }
      else cur += c;
    }
    out.push(cur);
    return out;
  }
  function parseCSV(csvText) {
    const lines = (csvText || "").split("\n").filter((l) => l.length > 0);
    if (!lines.length) return { header: [], rows: [] };
    return { header: parseCSVLine(lines[0]), rows: lines.slice(1).map(parseCSVLine) };
  }
  // Reusable in-tool viewer — every former CSV download opens this instead.
  // `title` is shown in the modal head; `csvText` is one of the CSV_BUILDERS'
  // strings (or any other toCSV()-shaped string). Renders into the persistent
  // dlv-view-overlay modal (see ensureModals()) using the app's existing
  // table.tbl styling, scrollable so 60+ row datasets don't blow the modal up.
  function openDataView(title, csvText) {
    let titleEl = $id("dlv-view-title"), countEl = $id("dlv-view-count"), bodyEl = $id("dlv-view-body");
    if (!titleEl || !countEl || !bodyEl) {
      ensureModals();
      titleEl = $id("dlv-view-title"); countEl = $id("dlv-view-count"); bodyEl = $id("dlv-view-body");
    }
    if (!titleEl || !countEl || !bodyEl) return;
    const { header, rows } = parseCSV(csvText);
    titleEl.textContent = title;
    if (!rows.length) {
      countEl.textContent = "";
      bodyEl.innerHTML = `<div class="dlv-empty">Nothing to show — all clear.</div>`;
    } else {
      countEl.textContent = rows.length + " row" + (rows.length === 1 ? "" : "s");
      const theadHtml = "<tr>" + header.map((h) => `<th>${esc(h)}</th>`).join("") + "</tr>";
      const tbodyHtml = rows.map((r) => "<tr>" + header.map((_, i) => `<td>${esc(r[i] != null ? r[i] : "")}</td>`).join("") + "</tr>").join("");
      bodyEl.innerHTML = `<table class="tbl"><thead>${theadHtml}</thead><tbody>${tbodyHtml}</tbody></table>`;
    }
    openModal("dlv-view-overlay");
  }

  const CSV_BUILDERS = {
    blacklist: () => toCSV(["domain", "blacklists"], S.A.blacklistRows.map((r) => ({ domain: r.domain, blacklists: r.lists }))),
    blocked: () => toCSV(["email", "domain", "reason_category", "smtp_ok", "imap_ok", "blocked_reason"], S.A.inboxRows.filter((r) => r.kind === "blocked").map((r) => ({ email: r.email, domain: r.domain, reason_category: r.reason_category, smtp_ok: true, imap_ok: true, blocked_reason: r.reason }))),
    inactive: () => toCSV(["email", "domain", "smtp_host", "smtp_ok", "reputation", "error"], S.A.inactiveRows),
    "new-mailboxes": () => toCSV(["email", "domain", "tagged", "in_campaign"], S.A.lifecycle.newUnprocessed.map((r) => ({ email: r.email, domain: r.domain, tagged: r.tagged, in_campaign: r.inCampaign }))),
    retired: () => toCSV(["domain", "mailboxes"], S.A.lifecycle.retired),
    "sending-deviation": () => toCSV(["email", "domain", "batch", "cap", "baseline", "direction"], [].concat(S.A.sendingDeviation.over, S.A.sendingDeviation.under)),
    signature: () => toCSV(["email", "domain", "from_name", "issue", "signature"], [].concat(
      S.A.signature.missing.map((r) => ({ email: r.email, domain: r.domain, from_name: r.from_name, issue: "missing", signature: "" })),
      S.A.signature.mismatch.map((r) => ({ email: r.email, domain: r.domain, from_name: r.from_name, issue: r.issue, signature: "" })),
    )),
    "warmup-config": () => toCSV(["email", "domain", "issue", "detail"], [].concat(
      S.A.warmupConfig.notWarming.map((r) => ({ email: r.email, domain: r.domain, issue: "not warming", detail: r.reason })),
      S.A.warmupConfig.wrongSettings.map((r) => ({ email: r.email, domain: r.domain, issue: "wrong settings", detail: r.issue })),
    )),
    "batch-stats": () => toCSV(["batch", "mailboxes", "domains", "sending", "warmup", "dead", "blocked", "blacklisted", "sent", "reply_rate", "bounce_rate", "positive_rate"], S.A.batchStats),
    "domain-health": () => toCSV(["domain", "sent", "leads_contacted", "replied", "reply_rate_pct", "positive_replied", "bounce_rate_pct", "action"], S.A.domainHealth.rows.map((d) => ({ domain: d.domain, sent: d.sent, leads_contacted: d.lead, replied: d.replied, reply_rate_pct: d.reply_rate, positive_replied: d.positive, bounce_rate_pct: d.bounce_rate, action: dhFlag(d, dhCutoffMin().minSent, dhCutoffMin().cutoff) === "warmup" ? "MOVE TO WARMUP" : "keep active" }))),
    "domain-health-warmup": () => toCSV(["domain", "sent", "leads_contacted", "replied", "reply_rate_pct", "positive_replied", "bounce_rate_pct", "action"], S.A.domainHealth.rows.filter((d) => dhFlag(d, dhCutoffMin().minSent, dhCutoffMin().cutoff) === "warmup").map((d) => ({ domain: d.domain, sent: d.sent, leads_contacted: d.lead, replied: d.replied, reply_rate_pct: d.reply_rate, positive_replied: d.positive, bounce_rate_pct: d.bounce_rate, action: "MOVE TO WARMUP" }))),
    mailboxes: () => toCSV(["email", "domain", "provider", "kind", "warmup_status", "reason_category", "smtp_ok", "imap_ok", "reputation", "eligible", "reason"], S.A.inboxRows.filter((r) => r.kind !== "ok").map((r) => ({ email: r.email, domain: r.domain, provider: r.provider, kind: r.kind, warmup_status: r.warmup_status, reason_category: r.reason_category, smtp_ok: true, imap_ok: true, reputation: "", eligible: r.kind === "warmupoff", reason: r.reason }))),
  };
  // Friendly modal titles for each CSV_BUILDERS key — falls back to the raw
  // key if a new builder is ever added without a title.
  const DATA_TITLES = {
    blacklist: "Blacklisted domains",
    blocked: "Blocked mailboxes",
    inactive: "Inactive mailboxes",
    "new-mailboxes": "New / untagged mailboxes",
    retired: "Retired domains",
    "sending-deviation": "Sending deviations vs batch baseline",
    signature: "Signature issues",
    "warmup-config": "Warmup config issues",
    "batch-stats": "Performance by batch",
    "domain-health": "Domain health — full table",
    "domain-health-warmup": "Domains to warm up",
    mailboxes: "Problem mailboxes",
  };
  function viewData(name) {
    const build = CSV_BUILDERS[name];
    if (!build) return;
    const csv = build();
    const title = DATA_TITLES[name] || name;
    openDataView(title, csv);
    // Row count = every CSV line minus its one header line.
    const n = Math.max(0, csv.split("\n").length - 1);
    // Item 1 (carried over from the old CSV-download history entries): every
    // view still leaves a trace in "Recent actions" — one of the "did 5+
    // actions, log stayed empty" contributors this file already fixed once.
    logAction({ action: "view_data", count: n, scope: title });
  }
  function viewVerifyData(kind, campId, rows) {
    const title = (kind === "keep" ? "Verify — kept (deliverable)" : "Verify — bad (confirmed invalid)") + " · campaign " + campId;
    openDataView(title, toCSV(["email", "result"], rows));
    logAction({ action: "view_data", count: (rows || []).length, scope: title });
  }

  /* ============================================================
     8. Today's to-do — item specs + live text/count builder
     ============================================================ */
  // Defensive filters here are belt-and-braces on top of normalizeState()'s
  // load-time sanitizing — they mean an in-session write (this tab, before the
  // next save/reload round-trips through normalizeState) can never crash these
  // reads either, even if some future writer regresses the shape.
  function ackOf(key) { return (S.A.acks || []).filter((x) => x && typeof x === "object" && x.key === key && Number.isFinite(Number(x.ts))).sort((a, b) => b.ts - a.ts)[0]; }
  function isAcked(item) { if (!item.key) return false; const ac = ackOf(item.key); return !!(ac && item.count != null && Number(item.count) <= Number(ac.count)); }

  /* Every kind either returns an active item (count > 0), a `resolved: true`
     item (count dropped to 0 through in-session actions — rendered as a green
     "✓ handled" chip, distinct from a manually-acked item), or null if the
     category fundamentally doesn't apply. Counts are read straight off S/D on
     every call, so the numbers can never go stale between actions. */
  function buildTodoItem(kind, D) {
    switch (kind) {
      case "blacklist": {
        const total = S.A.blacklistRows.length; if (!total) return null;
        const actionable = S.A.blacklistRows.filter((r) => !r.cleared && (r.rested || 0) < r.mailboxes).length;
        if (!actionable) return { key: "blacklist", level: "red", count: 0, resolved: true, text: total + " domain(s) were on SURBL / Spamhaus blocklists — all now paused or cleared." };
        // Item 3 (#1 to-do self-service): "fix the underlying cause" gave no
        // path — replaced with three concrete sub-steps, each pointing at a
        // button/section that already exists on this page.
        return { key: "blacklist", level: "red", count: actionable, short: "blacklisted domains still sending",
          text: actionable + " of " + total + " domain(s) on SURBL / Spamhaus blocklists still sending.",
          actionLines: [
            "1) Pause the still-sending domains (⏸ buttons below).",
            "2) The usual cause is bad lead lists or spammy copy — run the lead verification in the campaigns item below / review your copy.",
            // Fix #3b (holdout VA): expectation-setting — delisting is NOT a
            // button in this tool, it's a manual form on each blocklist's site.
            "3) Then file for delisting (📋 Delisting prep below) — a manual step on each blocklist's own website (has a CAPTCHA): copy the prepared request text, or hand this to your admin.",
          ],
          action: "Pause sending, fix the cause (lead lists / copy), then file for delisting.",
          blacklistRows: S.A.blacklistRows };
      }
      case "blocked": {
        const n = D.blockedReal;
        if (!n) return { key: "blocked-real", level: "red", count: 0, resolved: true, text: "No mailboxes blocked by receiving providers right now." };
        return { key: "blocked-real", level: "red", count: n, short: "mailboxes blocked by providers", text: n + " mailbox(es) blocked by receiving providers (real blocks, not warmup noise)" + (D.blockedSoft ? " · +" + D.blockedSoft + " soft (no action)" : "") + ".", action: "Escalate to Hypertide with the domain list and blocked reasons.", hypertide: true };
      }
      case "verify": {
        const n = D.uncleanedVerifyCamps.length;
        if (!n) return { key: "verify-campaigns", level: "red", count: 0, resolved: true, text: "All flagged campaigns have been re-verified and cleaned." };
        return { key: "verify-campaigns", level: "red", count: n, short: "low-reply campaigns need lead verification", text: n + " campaign(s) below 1% reply with elevated bounce — leads likely need re-verifying.", action: "Run ListMint (or MillionVerifier → ListMint) on each, then remove confirmed-bad leads.", verifyCamps: D.uncleanedVerifyCamps };
      }
      case "signatures": {
        const n = D.signatureCount;
        if (!n) return { key: "signatures", level: "yellow", count: 0, resolved: true, text: "No signature issues — every mailbox has a matching signature." };
        return { key: "signatures", level: "yellow", count: n, text: n + " mailbox(es) missing a signature or with a name mismatch (" + S.A.signature.missing.length + " missing · " + S.A.signature.mismatch.length + " mismatch).", action: "Apply a signature to every OAuth mailbox missing one, or fix the mismatch.", sigCsv: true };
      }
      case "new-unprocessed": {
        const n = D.newCount;
        if (!n) return { key: "new-unprocessed", level: "yellow", count: 0, resolved: true, text: "No new mailboxes waiting to be tagged or added to a campaign." };
        return { key: "new-unprocessed", level: "yellow", count: n, text: n + " new mailbox(es) untagged or not yet in a campaign.", action: "Tag them and/or add the ones not yet assigned to a campaign.", newCsv: true };
      }
      case "warmup-notwarming": {
        const n = S.A.warmupConfig.notWarming.length, w = S.A.warmupConfig.wrongSettings.length;
        if (!n && !w) return { key: "warmup-notwarming", level: "yellow", count: 0, resolved: true, text: "No warmup-configuration issues — every mailbox is warming correctly." };
        const bits = []; if (n) bits.push(n + " mailbox(es) with warmup off"); if (w) bits.push(w + " with wrong settings");
        return { key: "warmup-notwarming", level: "yellow", count: n || w, text: bits.join(" · ") + ".", action: n ? "Enable warmup on all of them with the fleet's standard settings." : "Review and correct their warmup settings.", wcCsv: true };
      }
      case "sending-deviation": {
        const n = D.deviationCount;
        if (!n) return { key: "sending-deviation", level: "yellow", count: 0, resolved: true, text: "Every mailbox is sending at its batch baseline." };
        return { key: "sending-deviation", level: "yellow", count: n, text: n + " mailbox(es) sending above or below their batch baseline (" + S.A.sendingDeviation.over.length + " over · " + S.A.sendingDeviation.under.length + " under).", action: "Review and align sending caps back to the batch baseline.", devCsv: true };
      }
      case "reminder-due": {
        const n = D.reminderDueCount;
        if (!n) return { key: "reminder-due", level: "yellow", count: 0, resolved: true, text: "No restore reminders due." };
        return { key: "reminder-due", level: "yellow", count: n, text: n + " restore reminder(s) due today or overdue.", action: "Check warm-up health and either add back to a campaign or extend the reminder.", reminderDue: true };
      }
      case "retired-domains": {
        const n = D.retiredCount;
        if (!n) return { key: "retired-domains", level: "note", count: 0, resolved: true, text: "No fully-dead retired domains right now." };
        return { key: "retired-domains", level: "note", count: n, text: n + " fully-dead domain(s) with every mailbox retired.", action: "Remove these from Smartlead — they're not recoverable.", retiredCsv: true };
      }
      default: return null;
    }
  }

  /* Derives every to-do bucket fresh from the current state on every paint —
     the single source of truth for counts/text/resolved-status so nothing can
     go stale after an action (fix: to-do items used to only refresh on
     "Mark done"; now every mutating action feeds straight back in here). */
  function recomputeTodos(D) {
    const kinds = ["blacklist", "blocked", "verify", "signatures", "new-unprocessed", "warmup-notwarming", "sending-deviation", "reminder-due", "retired-domains"];
    let raw = kinds.map((k) => buildTodoItem(k, D)).filter(Boolean);

    // Dynamic: domains flagged for warm-up rotation that aren't resting yet.
    // Uses flaggedActionable (not flaggedTotal) so the count actually drops
    // as domains get moved into warm-up instead of staying stuck forever.
    if (D.flaggedTotal > 0) {
      if (D.flaggedActionable > 0) {
        raw.push({ key: "warmup-rotation", level: "yellow", count: D.flaggedActionable, _openManager: true,
          text: D.flaggedActionable + " domain(s) sending with a reply rate under " + S.A.domainHealth.cutoff + "% — they should go into warm-up.",
          action: "Open the inbox & domain manager below and move the flagged domains to warm-up (or reactivate any that recovered)." });
      } else {
        raw.push({ key: "warmup-rotation", level: "yellow", count: 0, resolved: true, text: D.flaggedTotal + " flagged domain(s) have all been moved to warm-up." });
      }
    }

    const ord = { red: 0, yellow: 1, note: 2 };
    raw.sort((a, b) => (ord[a.level] ?? 9) - (ord[b.level] ?? 9));
    const activeTodo = raw.filter((it) => !it.resolved && !isAcked(it));
    const doneTodo = raw.filter((it) => !it.resolved && isAcked(it));
    const resolvedTodo = raw.filter((it) => it.resolved && !isAcked(it));
    return { activeTodo, doneTodo, resolvedTodo, raw };
  }

  function buildGoodChips(D) {
    const chips = [];
    if (S.A.noNS === 0) chips.push("Nameserver zones clean — no drift");
    if (S.A.spfMiss === 0 && S.A.dkimMiss === 0) chips.push("SPF & DKIM present across the fleet");
    if (S.A.smtp <= 5) chips.push("SMTP/IMAP auth mostly healthy (" + S.A.smtp + " / " + S.A.imap + " issues)");
    if (S.A.bounce_pct < 2) chips.push("Bounce rate healthy at " + S.A.bounce_pct + "%");
    if (S.A.reply_pct >= 1) chips.push("Reply rate at/above the 1% benchmark (" + S.A.reply_pct + "%)");
    if (D.domainHealthCounts.keep > 0) chips.push(D.domainHealthCounts.keep + " domain(s) sending cleanly, no action needed");
    return chips;
  }

  function computeStatus(D) {
    const red = D.activeTodo.filter((x) => x.level === "red").length;
    const yellow = D.activeTodo.filter((x) => x.level === "yellow").length;
    // Note-level items (e.g. retired domains) are real active to-do rows too —
    // tracked separately so the banner math always adds up to the list count
    // (fix: banner used to only add red+yellow, silently dropping notes).
    const note = D.activeTodo.filter((x) => x.level === "note").length;
    // Item 4: how many still-active red items have a live count strictly
    // below their session-start snapshot — i.e. partial progress (some
    // blacklisted domains paused, some blocked mailboxes cleared…) that
    // hasn't fully resolved the category yet, so `red` above alone can't
    // show it.
    const snap = (S.ui && S.ui.redSnapshot) || {};
    const redInProgress = D.activeTodo.filter((x) => x.level === "red" && snap[x.key] != null && Number(x.count) < Number(snap[x.key])).length;
    if (red > 0) return { status: "URGENT", dot: "r", red, yellow, note, redInProgress };
    if (yellow > 0) return { status: "WATCH", dot: "a", red, yellow, note, redInProgress: 0 };
    return { status: "HEALTHY", dot: "g", red, yellow, note, redInProgress: 0 };
  }

  /* Shared facts for the glance-layer health strip AND the technical-details
     fold's closed-state summary, so the two never disagree on what "OK" means.
     authIssueDomains: the SPF/DKIM/DMARC miss counts are tracked as separate
     per-record tallies (a domain can be missing more than one record) and the
     mock data has no per-domain auth breakdown to union them properly — the
     largest single tally is used as a conservative floor on how many DISTINCT
     domains have at least one issue. */
  function computeHealthFacts(D) {
    const A = S.A;
    const bounceOk = A.bounce_pct < 2;
    const bounceWarn = A.bounce_pct < 3;
    const authIssueDomains = Math.max(A.spfMiss || 0, A.dkimMiss || 0, A.dmarcMiss || 0);
    const authOkDomains = Math.max(0, A.domains - authIssueDomains);
    const nsIssues = A.noNS || 0;
    const anyInfraIssue = A.smtp > 0 || (A.spfMiss + A.dkimMiss + A.dmarcMiss) > 0 || A.noNS > 0;
    return { bounceOk, bounceWarn, authIssueDomains, authOkDomains, nsIssues, anyInfraIssue };
  }

  /* ============================================================
     9. Verify pipeline simulation (ListMint / MV→ListMint)
     ============================================================ */
  function simulateVerify(campId, mode) {
    const camp = S.A.campaignsFlagged.find((c) => String(c.id) === String(campId));
    const total = camp ? Math.max(40, Math.round(camp.sent * 0.62)) : 500;
    const l1Drop = Math.round(total * 0.055);
    const l1Catch = Math.round(total * 0.14);
    const l1Keep = total - l1Drop - l1Catch;
    const l2Drop = Math.round(l1Catch * 0.32);
    const l2Keep = l1Catch - l2Drop;
    const keep = l1Keep + l2Keep;
    const remove = l1Drop + l2Drop;
    return {
      total, layer1Tool: mode === "mv" ? "MillionVerifier" : "ListMint", layer2Tool: "ListMint",
      l1_keep: l1Keep, l1_catch: l1Catch, l1_drop: l1Drop, l2_keep: l2Keep, l2_drop: l2Drop,
      keep, remove, unverified: 0,
    };
  }
  function fakeLeadRows(campId, n, tag) {
    const rows = [];
    for (let i = 0; i < n; i++) rows.push({ email: "lead" + i + "@" + tag + campId + ".example.com", result: tag });
    return rows;
  }

  /* ============================================================
     10. Hypertide draft + "Copy for Claude" context (built live)
     ============================================================ */
  function buildHypertideEmail(D) {
    const blocked = S.A.inboxRows.filter((r) => r.kind === "blocked");
    const domains = [...new Set(blocked.map((r) => r.domain))];
    const byReason = D.reasonCounts;
    const reasonLines = Object.entries(byReason).filter(([k]) => k !== "soft").map(([k, v]) => "  - " + k + ": " + v).join("\n");
    return "Subject: Escalation — sending blocked across " + D.blockedReal + " mailbox(es)\n\n" +
      "Hi team,\n\n" +
      "During today's audit (" + S.A.date + ") we found " + D.blockedReal + " mailbox(es) across " + domains.length + " domain(s) blocked by receiving providers (excluding routine soft/warmup noise). Breakdown:\n" +
      reasonLines + "\n\n" +
      "Domains affected:\n" + domains.map((d) => "  - " + d).join("\n") + "\n\n" +
      "Could you check these domains' sending IP reputation and authentication (SPF/DKIM/DMARC), and let us know once they're clear so we can resume?\n\n" +
      "Thanks,\nNavreo";
  }
  function buildContext(D) {
    const st = computeStatus(D);
    const lines = [];
    lines.push("NAVREO DELIVERABILITY AUDIT — " + S.A.date + " — " + st.status);
    lines.push(fmtN(S.A.inboxes) + " inboxes · " + S.A.domains + " domains · " + S.A.active + " active campaigns");
    lines.push("Reply rate " + S.A.reply_pct + "% · Bounce rate " + S.A.bounce_pct + "% · Sent " + fmtN(S.A.sent));
    lines.push("");
    lines.push("TODAY'S TO-DO (" + D.activeTodo.length + "):");
    D.activeTodo.forEach((it, i) => { lines.push((i + 1) + ". [" + it.level.toUpperCase() + "] " + it.text + " -> " + it.action); });
    if (!D.activeTodo.length) lines.push("(all clear — nothing needs action today)");
    lines.push("");
    lines.push("BLACKLISTED DOMAINS (" + S.A.blacklistRows.length + "): " + S.A.blacklistRows.map((r) => r.domain).join(", "));
    lines.push("");
    lines.push("Paste this into a Claude chat to assign follow-up tasks.");
    return lines.join("\n");
  }

  /* ============================================================
     11. Header + tab strip + banner
     ============================================================ */
  function renderHeaderTabs() {
    // On the standalone rail page the left rail IS the top-level nav, so the old
    // in-page Campaigns/Deliverability toggle is redundant (and would stack a
    // second tab strip right above the sub-tab bar) — suppress it there. When the
    // tab is mounted inside campaigns.html (hash route), keep the toggle.
    const topToggle = window.DLV_STANDALONE ? "" : `
    <div class="tabs" style="margin-bottom:14px">
      <button class="tab" data-act="goto-campaigns">Campaigns</button>
      <button class="tab on">Deliverability</button>
    </div>`;
    return `${topToggle}
    <div class="pagehead">
      <div>
        <div class="eyebrow">Deliverability</div>
        <h1>Fleet health audit.</h1>
      </div>
      <div class="dlv-actions">
        <button class="dlv-tips-btn" data-act="show-coach" title="Show the quick intro / tips for this page again">? Show tips</button>
        <button class="btn" data-act="copy-claude" title="Copies a text summary you can paste to an AI assistant or teammate.">📋 Copy for Claude</button>
        <button class="btn" data-act="sync-notion">🗂 Sync to Notion</button>
        <button class="btn" data-act="send-slack">📤 Send to Slack</button>
        <span class="dlv-hdr-sep" aria-hidden="true"></span>
        <button class="btn dlv-btn-caution" data-act="run-audit" id="dlv-run-btn" title="Destructive — wipes every action taken this session and pulls a fresh snapshot.">⚠ Run Live Audit</button>
      </div>
    </div>`;
  }

  /* Sub-tab bar — directly under the page header, above every panel. Always
     shows regardless of subtab so the moved sections stay one click away from
     anywhere on the page. Reuses the shared .tabs/.tab classes (see
     campaigns.html's "Campaigns/Deliverability" toggle above and its own
     detail-view sub-tabs) so it matches the rest of the tool. */
  function renderSubtabBar() {
    return `<div class="tabs dlv-subtabs" role="tablist">` +
      DLV_SUBTABS.map(([id, label]) => `<button class="tab ${dlvSubtab === id ? "on" : ""}" data-act="dlv-subtab" data-subtab="${id}" role="tab" aria-selected="${dlvSubtab === id}">${esc(label)}</button>`).join("") +
      `</div>`;
  }

  /* Part B1: first-run onboarding coach. Shown when the user has never
     dismissed it (localStorage "dlv_coach_seen") OR when they re-open it via
     the header "? Show tips" button (transient UI.coachOpen flag). Never a
     blocking modal — a dismissible inline callout at the very top of the tab. */
  function coachSeen() { try { return localStorage.getItem("dlv_coach_seen") === "1"; } catch (e) { return false; } }
  function renderCoach() {
    if (coachSeen() && !UI.coachOpen) return "";
    return `<div class="dlv-coach" id="dlv-coach">
      <button class="dlv-coach-x" data-act="coach-dismiss" title="Dismiss">&times;</button>
      <h3>👋 New here? This page lists what needs attention today.</h3>
      <ul>
        <li>Click any <b>?</b> for a plain-English definition of any term.</li>
        <li>Every button that changes something asks you to <b>confirm first</b> — and can be undone.</li>
        <li>Start at the top of <b>“Today’s to-do”</b> and work down.</li>
      </ul>
      <button class="dlv-coach-got" data-act="coach-dismiss">Got it</button>
    </div>`;
  }

  /* Part C(c): one-glance verdict line at the very top of the health layer —
     summarises overall state in a single plain-English phrase so the owner
     persona gets a verdict without assembling it from the chips below. Numbers
     come straight off computeStatus()/S.A so it can never disagree with them. */
  function renderVerdict(D) {
    const st = D.status || computeStatus(D);
    const A = S.A;
    const bounceBad = Number(A.bounce_pct) >= 2;
    const repliesDown = A.replyTrend && A.replyTrend.drop;
    let sev, dot, phrase;
    if (st.red > 0) {
      sev = "r"; dot = "🔴";
      const topRed = D.activeTodo.find((x) => x.level === "red");
      const start = topRed && topRed.short ? topRed.short : (topRed ? topRed.text : "the urgent items");
      const bits = [st.red + " urgent fix" + (st.red === 1 ? "" : "es")];
      if (repliesDown) bits.push("replies slipping");
      if (bounceBad) bits.push("bounce over limit");
      phrase = "Needs attention — " + bits.join(" and ") + ". Start with: " + start + ".";
    } else if (st.yellow > 0 || repliesDown) {
      sev = "a"; dot = "🟡";
      const bits = [];
      if (st.yellow > 0) bits.push(st.yellow + " thing" + (st.yellow === 1 ? "" : "s") + " to review");
      if (repliesDown) bits.push("replies trending down");
      phrase = "Mostly healthy — " + (bits.join(" and ") || "a few things to review") + ". No fires, but worth a look today.";
    } else {
      sev = "g"; dot = "🟢";
      phrase = "Healthy sending — nothing urgent today. The numbers below are for reference.";
    }
    return `<div class="dlv-verdict ${sev}"><span class="vdot">${dot}</span><span>Overall: ${esc(phrase)}</span></div>`;
  }

  function renderBanner(D) {
    const st = computeStatus(D);
    const emoji = { g: "🟢", a: "🟡", r: "🔴" }[st.dot];
    const parts = [fmtN(S.A.inboxes) + " inboxes", S.A.domains + " domains", S.A.active + " active"];
    if (st.red) parts.push("🔴 " + st.red + " urgent");
    if (st.yellow) parts.push("🟡 " + st.yellow + " to review");
    if (st.note) parts.push("📝 " + st.note + " note" + (st.note === 1 ? "" : "s"));
    if (!st.red && !st.yellow && !st.note) parts.push("✓ rest healthy");
    return `
    <div class="dlv-banner">
      <div class="dlv-dot ${st.dot}"></div>
      <div><h2>${emoji} ${esc(S.A.date)} — ${st.status}</h2><div class="sub">${parts.join(" · ")}</div></div>
    </div>`;
  }

  /* Health summary strip — the FIRST content below the banner, answering "am I
     okay?" in 2 seconds for a non-technical reader (fix: the agency-owner
     persona scored this 7 every round because the top of the page was jargon
     tiles with no plain-English glance layer). 3-5 chips, every number pulled
     straight off D/S.A — never a separate calculation from the banner/tiles
     below it, so the two can never disagree. */
  function renderHealthStrip(D) {
    const A = S.A;
    const F = computeHealthFacts(D);
    const chips = [];
    // 1. Sending health — always shown.
    // Fix #4c (panels 9-10): "✓ Sending healthy" read as a page-level
    // all-clear that contradicted the "3 urgent" chip beside it — scope the
    // claim to the one metric it's actually about (bounce rate).
    if (F.bounceOk) chips.push({ sev: "g", html: "✓ Bounce rate healthy — " + A.bounce_pct + "%, under the 2% limit" });
    else chips.push({ sev: F.bounceWarn ? "a" : "r", html: (F.bounceWarn ? "⚠" : "🔴") + " Bounce rate elevated — " + A.bounce_pct + "% (fleet limit 2%)" });
    // 2. Reply trend — surfaced ONLY when it's actually declining; a flat/rising
    // trend has nothing urgent to say here (it's still in "Fleet by the numbers").
    if (A.replyTrend && A.replyTrend.drop) {
      chips.push({ sev: "a", html: "⚠ Replies trending down — " + A.replyTrend.wkRate + "% this week ▼ vs " + A.replyTrend.prevRate + "% prior 4-wk avg" });
    }
    // 3. Action needed — reuses computeStatus()'s own red/yellow/note counts
    // (same numbers the banner above prints), so this can't ever show a
    // different total than what the to-do list below actually contains.
    // Defect F fix: this used to say "N things need action today", sitting
    // right beside the banner's own "N urgent · N to review · N note" — two
    // different-looking counts a reader has to reconcile. Reworded so the
    // headline number is explicitly the URGENT (red) count, with the
    // remaining yellow+note count folded in as a parenthetical instead of
    // reading like a competing total.
    if (D.status.red > 0) {
      // Fix F(ii): this parenthetical used to collapse yellow+note into one
      // number ("N more to review") while the banner right above spells the
      // same two counts out separately ("N to review · N note") — same total,
      // different-looking breakdown, so a reader comparing the two would see
      // numbers that don't appear to match (e.g. banner "6 to review · 1
      // note" next to strip chip "(7 more to review)"). Mirror the banner's
      // own wording exactly so the two can never look inconsistent.
      let more = "";
      if (D.status.yellow > 0 && D.status.note > 0) more = " (" + D.status.yellow + " to review · " + D.status.note + " note" + (D.status.note === 1 ? "" : "s") + ")";
      else if (D.status.yellow > 0) more = " (" + D.status.yellow + " more to review)";
      else if (D.status.note > 0) more = " (" + D.status.note + " note" + (D.status.note === 1 ? "" : "s") + ")";
      // Item 5b: name the top fire right in the chip, so "3 urgent" is never
      // an abstract number — the first red item in the sorted to-do list is by
      // definition the one this chip scrolls to.
      const topRed = D.activeTodo.find((x) => x.level === "red");
      const topTxt = topRed ? " — top: " + esc(topRed.short || topRed.text) : "";
      // Item 4: "3 urgent" alone can't show partial progress WITHIN a
      // category (pausing 1 of 3 blacklisted domains doesn't resolve the
      // "blacklist" category, so the count above doesn't move) — this reads
      // as "nothing happened" to an owner who just did something. Call out
      // how many active red items have moved since session start.
      const prog = D.status.redInProgress > 0 ? " (" + D.status.redInProgress + " in progress)" : "";
      chips.push({ sev: "r", html: "🔴 " + D.status.red + " urgent" + prog + topTxt + " →" + more, act: "scroll-todo" });
    } else if (D.status.yellow > 0) {
      chips.push({ sev: "a", html: "🟡 " + D.status.yellow + " thing" + (D.status.yellow === 1 ? "" : "s") + " to review today →", act: "scroll-todo" });
    }
    // 4. Authentication — always shown. Fix #8b: lead with the problem count
    // instead of burying it in an "X of Y" ratio a reader has to do subtraction
    // on, and say "all N" rather than the more awkward "N of N" when clean.
    if (F.authIssueDomains === 0) chips.push({ sev: "g", html: "✓ Authentication OK on all " + A.domains + " domains" });
    else chips.push({ sev: "a", html: "⚠ " + F.authIssueDomains + " domain" + (F.authIssueDomains === 1 ? "" : "s") + " missing auth records — " + F.authOkDomains + " of " + A.domains + " OK" });
    return `<div class="dlv-health-strip">` + chips.map((c) =>
      `<div class="dlv-health-chip ${c.sev}"${c.act ? ` data-act="${c.act}"` : ""}>${c.html}</div>`
    ).join("") + `</div>`;
  }

  /* ============================================================
     12. Fleet by the numbers — 3 groups + blocked breakdown, every
         CSV link is a real Blob download. (Fleet lifecycle's four
         warmup-related tiles are merged into one "Warmup" tile —
         see warmupTile() above — so the group runs shorter than it
         once did.)
     ============================================================ */
  function tile(label, value, note, sev, csvName, fixAction, extra, glossLabel) {
    const csv = csvName ? `<div class="dlv-stat-csv"><a class="dlv-dl" data-act="view-data" data-file="${csvName}">👁 View list</a></div>` : "";
    // Actionable tiles get a small link straight to their fix, reusing the
    // same data-act handlers already wired for the to-do cards below — so a
    // tester scanning the numbers doesn't have to hunt for the matching action.
    const act = fixAction ? `<div class="dlv-stat-csv"><a class="dlv-dl" data-act="${esc(fixAction.act)}">${fixAction.label}</a></div>` : "";
    // Design-fix: the full jargon-dictionary sentence (SURBL/Spamhaus's ~40-word
    // definition, etc.) used to render unconditionally as an inline paragraph
    // here — turning tiles like "Blacklisted domains" into a wall of text and,
    // via CSS Grid's default row-stretch, forcing every OTHER tile in that row
    // to inflate to match its height. It now attaches to the LABEL as a "?"
    // popover (same mechanism glossLabel/glossify already use elsewhere) so the
    // full definition is still one click away, but the tile body stays compact.
    const plain = plainLineFor(label + " " + (note || ""));
    // `glossLabel`: a pre-glossified (already-escaped, "?" sup already inserted) label
    // HTML string — used by the technical-details tiles whose LABEL itself is the jargon
    // needing a click-popover (fix #5b), passed instead of the default esc(label) so the
    // inserted <sup> markup isn't re-escaped into visible text.
    const labelHtml = glossLabel != null ? glossLabel : (plain ? esc(label) + glossMark(plain) : glossify(label));
    // `note`: the ONE short hint line under the number (e.g. "last 7 days", "on
    // SURBL / Spamhaus") — same typography as the Dashboard's .hint.
    const hintHtml = note ? `<div class="hint">${esc(note)}</div>` : "";
    // `extra`: a live, state-derived breakdown line for tiles whose headline number is
    // easy to confuse with a different count shown elsewhere (e.g. a manager's
    // actionable subset) — kept as a SECOND, hint-sized line, but skipped when it's
    // identical to `note` so that text isn't printed twice.
    // Defect 6a: glossify() (not plain esc()) so a jargon word inside this line
    // — e.g. "batch baseline" on the Sending-vs-batch tile — gets its own
    // clickable "?" instead of only ever getting the muted auto-line above.
    const extraHtml = (extra && extra !== note) ? `<div class="dlv-stat-plain">${glossify(extra)}</div>` : "";
    return `<div class="stat dlv-stat ${sev || ""}"><div class="lab">${labelHtml}</div><div class="num-hero">${value}</div>${hintHtml}${extraHtml}${csv}${act}</div>`;
  }
  function sevOf(ok, warnOk) { return ok ? "" : (warnOk ? "warn" : "bad"); }

  // Reply-trend tile builder — pulled out so the ▼/▲ + delta lives visibly in
  // BOTH the tile value and its note-turned-visible extra line (fix: the trend
  // used to only show its delta via the `note` param, which tile() renders
  // solely as a `title` hover tooltip — a tester scanning tiles with a mouse
  // never sees a hover-only number, so the reply decline was invisible).
  function replyTrendTile(A) {
    const rt = A.replyTrend;
    if (!rt) return tile("Reply trend (wk vs 4-wk)", "—", "", "");
    const drop = !!rt.drop;
    const arrow = drop ? "▼" : "▲";
    const value = rt.wkRate + "% " + arrow;
    const extra = (drop ? "Down" : "Up") + " from " + rt.prevRate + "% prior 4-wk avg";
    return tile("Reply trend (wk vs 4-wk)", value, extra, sevOf(!drop, false), null, null, extra);
  }

  /* Fix #7 / defect E: "Warmup inactive", "Domains to warm up", "Warmup due
     back" and "New warmup issues" used to be four separate tiles that all fed
     the same greedy jargon-dictionary subtitle (fix #6) and forced a reader to
     add four numbers together to know what actually needed doing. Merged into
     one "Warmup" tile. Root cause of the round-5 regression: the headline
     number (actionableToWarmUp + configIssues + dueBack) did NOT equal the sum
     of what a reader could plainly see, because the visible lines printed the
     wrong numbers next to it — "to warm up 9 (3 actionable)" shows 9 in the
     sentence a skimming reader adds up, not the 3 that's actually counted, AND
     "inactive 8" sat in the same list even though it's excluded from the
     total. Fixed by only ever showing, as separate summed lines, the exact
     numbers that make up the headline (actionable-to-warm-up + due-back), and
     moving inactive (by-design, not actionable) and config issues (actionable,
     but deliberately NOT part of this headline per the fix spec) to their own
     clearly-labelled non-summed lines. Bypasses the generic tile() helper
     (rather than stretching its single-fixAction/single-CSV shape) since this
     tile alone needs two fix-links and three stacked CSV downloads. Built as
     its own function, not inline in renderFleetTiles(), purely to keep that
     function's tile list readable. */
  function warmupTile(D) {
    const A = S.A;
    // Live mode carries the full-fleet inactive count as a scalar (A.inactive);
    // the mock base only has a handful of inactiveRows for the View modal.
    const inactiveN = (A._live && A.inactive != null) ? Number(A.inactive) : A.inactiveRows.length;
    const toWarmUpTotal = D.domainHealthCounts.flagged;
    const actionableToWarmUp = D.flaggedActionable;
    const dueBack = A.warmupDue;
    const configIssues = A.warmupConfig.notWarming.length + A.warmupConfig.wrongSettings.length;
    // Headline = exactly the sum of the two "actionable" lines below — nothing
    // else feeds it, so the reader's addition always checks out.
    const actionableTotal = actionableToWarmUp + dueBack;
    const lines = [
      // Fix F(iii): the two lines below always summed to the headline number,
      // but nothing ever SAID so — a reader had to do that addition
      // themselves. Spell the sum out explicitly as its own first line.
      actionableTotal + " = " + actionableToWarmUp + " to warm up + " + dueBack + " due back",
      "actionable to warm up " + actionableToWarmUp + (toWarmUpTotal > actionableToWarmUp ? " (of " + toWarmUpTotal + " flagged — rest already resting)" : ""),
      "due back " + dueBack,
    ];
    // Not part of the headline sum — called out separately so nobody adds them in.
    lines.push("also: " + inactiveN + " inactive mailbox(es) (mostly Maildoso, by design — no action)");
    if (configIssues) lines.push("also: " + configIssues + " mailbox(es) with wrong warmup settings — see CSV");
    // Design-fix: kept as hint-sized (.dlv-stat-plain now matches .hint's
    // typography) rather than full body text, so the merged tile stays compact.
    const extraHtml = lines.map((l) => `<div class="dlv-stat-plain">${esc(l)}</div>`).join("");
    const fixLinks = [];
    if (actionableToWarmUp) fixLinks.push(`<a class="dlv-dl" data-act="open-manager">🛠 Open manager ↓</a>`);
    if (configIssues) fixLinks.push(`<a class="dlv-dl" data-act="open-warmup-fix">⚡ Enable warmup…</a>`);
    const fixHtml = fixLinks.length ? `<div class="dlv-stat-csv">${fixLinks.join("")}</div>` : "";
    const csvLinks = [
      `<a class="dlv-dl" data-act="view-data" data-file="inactive">👁 View inactive</a>`,
      `<a class="dlv-dl" data-act="view-data" data-file="domain-health-warmup">👁 View to warm up</a>`,
    ];
    if (configIssues) csvLinks.push(`<a class="dlv-dl" data-act="view-data" data-file="warmup-config">👁 View config issues</a>`);
    const csvHtml = `<div class="dlv-stat-csv">${csvLinks.join("")}</div>`;
    const sev = sevOf(actionableTotal === 0, actionableTotal < 20);
    return `<div class="stat dlv-stat ${sev}" title="Everything warmup-related — inactive mailboxes, domains flagged for rotation, rests past due, and config issues"><div class="lab">Warmup${glossMark(WARMUP_DEF)}</div><div class="num-hero">${actionableTotal}</div>${extraHtml}${fixHtml}${csvHtml}</div>`;
  }

  function renderFleetTiles(D) {
    const A = S.A;
    const replyOk = A.reply_pct >= 1, bounceOk = A.bounce_pct < 2;
    const dmarcSum = A.quarantine + A.reject + A.none;
    const groups = { D: "Deliverability", F: "Fleet lifecycle" };
    const tilesByGroup = {
      D: [
        tile("Reply rate", A.reply_pct + "%", A.reply_pct + "% of " + fmtN(A.sent) + " sent", sevOf(replyOk, A.reply_pct >= 0.8)),
        tile("Bounce rate", A.bounce_pct + "%", "last 7 days", sevOf(bounceOk, A.bounce_pct < 3)),
        // Defect E fix: this subtitle used to print the reply count (e.g. "102
        // replies") under a tile headlined "Emails sent" — describing a
        // different metric than the one in the number above it. Say what the
        // number actually is instead.
        tile("Emails sent", fmtN(A.sent), "last 7 days across all campaigns", ""),
        replyTrendTile(A),
        tile("Blacklisted domains", A.blacklistRows.length, A.blacklistRows.length ? "Spamhaus DBL / SURBL" : "clean", sevOf(A.blacklistRows.length === 0, false), A.blacklistRows.length ? "blacklist" : null, A.blacklistRows.length ? { act: "open-blacklist", label: "🚫 Manage ↓" } : null),
        // Defect 5: this used to read the static seed value A.campLow, which
        // never moved even after a campaign got verified+cleaned — while the
        // to-do's "verify" card counts the exact same campaigns live off
        // D.uncleanedVerifyCamps. Read off the same derived value so the two
        // can never disagree, before OR after cleaning a campaign.
        tile("Campaigns < 1% reply", D.uncleanedVerifyCamps.length + " of " + A.active, A.highb + " high-bounce", sevOf(D.uncleanedVerifyCamps.length === 0, true), null, null, "listed in Today's to-do with one-click verify"),
        // Fix #6: this note used to say "warmup noise" — an incidental mention of
        // the word "warmup" that made the greedy JARGON_DICT resting/warmup entry
        // misfire "Sending paused while reputation recovers" under this totally
        // unrelated tile. Reworded (and the dictionary regex tightened) so neither
        // depends on the other to stay correct.
        tile("Blocked (real)", D.blockedReal, D.blockedSoft ? "+" + D.blockedSoft + " soft bounces (no action needed)" : "hosting blocks → Hypertide", sevOf(D.blockedReal === 0, D.blockedReal < 20), D.blockedTotal ? "blocked" : null),
      ],
      F: [
        warmupTile(D),
        tile("New unprocessed", D.newCount, D.newCount + " new/untagged mailbox(es)", sevOf(D.newCount === 0, true), D.newCount ? "new-mailboxes" : null, D.newCount ? { act: "open-process-new", label: "🏷 Process…" } : null),
        tile("Signature issues", D.signatureCount, A.signature.missing.length + " missing · " + A.signature.mismatch.length + " name-mismatch", sevOf(D.signatureCount === 0, true), "signature", D.signatureCount ? { act: "open-sig-fix", label: "✍️ Fix…" } : null, A.signature.missing.length + " missing · " + A.signature.mismatch.length + " name-mismatch"),
        tile("Sending vs batch", D.deviationCount, A.sendingDeviation.over.length + " over · " + A.sendingDeviation.under.length + " under their batch baseline", sevOf(D.deviationCount === 0, true), "sending-deviation", null, A.sendingDeviation.over.length + " over · " + A.sendingDeviation.under.length + " under their batch baseline"),
        tile("Retired domains", D.retiredCount, D.retiredCount ? "all mailboxes dead → remove" : "none", sevOf(D.retiredCount === 0, false), D.retiredCount ? "retired" : null),
      ],
    };
    let html = `<div class="dlv-fleet-group"><div class="dlv-fleet-glabel">${groups.D}</div><div class="dlv-stat-grid">${tilesByGroup.D.join("")}</div></div>`;
    html += renderTechFold(D);
    // Defect 6a: "Fleet lifecycle" itself never mentions the word "warmup", so
    // glossify()'s regex match against the visible label text can't attach a
    // mark here the way it does elsewhere — glossMark() attaches one directly.
    html += `<div class="dlv-fleet-group"><div class="dlv-fleet-glabel">${groups.F}${glossMark(WARMUP_DEF)}</div><div class="dlv-stat-grid">${tilesByGroup.F.join("")}</div></div>`;
    if (Object.keys(D.reasonCounts).length) {
      // Item 5e: each category tile carries a plain-English title-tooltip
      // (hosting block = provider-side block, spam complaint = recipient
      // complaints, mailbox full = bounce back) via tile()'s `note` param.
      const items = Object.entries(D.reasonCounts).sort((a, b) => b[1] - a[1]).map(([k, v]) => tile(k, v, BLOCK_REASON_TIPS[k] || "", "")).join("");
      html += `<div class="dlv-fleet-group"><div class="dlv-fleet-glabel">Blocked breakdown</div><div class="dlv-stat-grid">${items}</div></div>`;
    }
    html += `<div class="dlv-signpost-row">
      <a class="dlv-dl" data-act="open-batch">▲▼ Best &amp; worst batch ↓</a>
      <a class="dlv-dl" data-act="open-manager">🛠 Open manager ↓</a>
    </div>`;
    return `<div class="dlv-section-title">Fleet by the numbers</div>${html}`;
  }

  /* Technical-details fold — the "Infrastructure & auth" tiles (SMTP/IMAP,
     SPF/DKIM/DMARC, nameservers, DMARC enforcement) are the densest jargon on
     the page and rarely need a glance unless something's actually wrong, so
     they're tucked behind a fold instead of sitting permanently in the glance
     path (fix: this whole group used to sit unconditionally above the fold,
     competing for attention with the tiles that actually need daily eyes).
     Default state is computed from the tiles' own alarm status every render;
     a manual user toggle (tracked via the native `toggle` event → S.ui.techOpen)
     overrides that default until the user reloads/resets the session. */
  function renderTechFold(D) {
    const A = S.A;
    const F = computeHealthFacts(D);
    const dmarcSum = A.quarantine + A.reject + A.none;
    // Fix (2026-07-09): these four tiles used to carry a THIRD line that just
    // restated the headline number in prose (e.g. "3 SMTP auth errors · 1 IMAP
    // sync error" under "3 / 1") — pure repetition, and glossify()'d so nearly
    // every jargon word in that small grey text got its own inline "?" on top
    // of the one already on the tile's label. Dropped the restate line
    // entirely (7th `extra` arg → null) so each tile is just NUMBER + one
    // plain-esc()'d hint line; the single "?" that survives lives only on the
    // label (glossLabel, 8th arg), where the concept's full definition is
    // still one click away.
    const tiles = [
      tile("SMTP / IMAP fails", A.smtp + " / " + A.imap, "auth / sync errors", sevOf(A.smtp === 0, A.smtp < 10), null, null, null, glossify("SMTP / IMAP fails")),
      // Hint renamed from "sending-domain auth" to spell out the record order
      // (SPF / DKIM / DMARC) so it maps 1:1 onto the "0 / 0 / 1" headline
      // instead of a reader having to guess which number is which record.
      tile("Missing SPF/DKIM/DMARC", A.spfMiss + " / " + A.dkimMiss + " / " + A.dmarcMiss, "SPF / DKIM / DMARC missing", sevOf(A.spfMiss + A.dkimMiss + A.dmarcMiss === 0, true), null, null, null, glossify("Missing SPF/DKIM/DMARC")),
      tile("Nameserver issues", A.noNS, "drift / broken zones", sevOf(A.noNS === 0, true), null, null, null, glossify("Nameserver issues")),
      tile("DMARC enforcing", A.quarantine + " / " + A.reject, "quarantine / reject · " + A.none + " none of " + dmarcSum, "", null, null, null, glossify("DMARC enforcing")),
    ].join("");
    const open = (S.ui && S.ui.techOpen != null) ? S.ui.techOpen : F.anyInfraIssue;
    const summary = F.authIssueDomains + " domain(s) missing auth records · " + F.nsIssues + " nameserver issue(s)";
    return `<details class="dlv-fold" id="dlv-fold-tech" ${open ? "open" : ""}>
      <summary>🔧 Technical details — authentication &amp; DNS<span class="hint">${esc(summary)}</span></summary>
      <div class="dlv-fold-body"><div class="dlv-stat-grid">${tiles}</div></div>
    </details>`;
  }

  /* ============================================================
     13. Today's to-do
     ============================================================ */
  function renderVerifyCampRow(c) {
    const cl = (S.A.history || []).find((h) => String(h.campaign) === String(c.id));
    const badge = cl ? `<span class="dlv-badge-cleaned" title="Already actioned ${esc(cl.date)}">✓ already actioned ${esc(cl.date)}${cl.removed != null ? " · −" + cl.removed : ""}</span>` : "";
    return `<div class="dlv-vcamp"${cl ? ' style="opacity:.7"' : ""}>
      <a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)}</a>
      <span class="dlv-vmeta">${c.bounce_pct}% bounce · ${fmtN(c.sent)} sent</span>${badge}
      <div class="dlv-vbtns" style="gap:10px">
        <button class="btn sm" data-act="verify-campaign" data-id="${c.id}" data-mode="listmint" data-done="${cl ? esc(cl.date) : ""}" title="ListMint verification">✓ ${glossify("ListMint")}</button>
        <span class="dlv-vsep" aria-hidden="true"></span>
        <button class="btn sm" data-act="verify-campaign" data-id="${c.id}" data-mode="mv" data-done="${cl ? esc(cl.date) : ""}" title="MillionVerifier first, ListMint confirms catch-alls">✓ ${glossify("MillionVerifier")} → ${glossify("ListMint")}</button>
      </div>
      <div class="dlv-vresult" id="dlv-vr-${c.id}">${renderVerifyResultBox(c.id, (S.ui && S.ui.verifyResults) ? S.ui.verifyResults[c.id] : null)}</div>
    </div>`;
  }

  function renderTodoCard(it, i) {
    const extraBits = [];
    if (it.verifyCamps && it.verifyCamps.length) extraBits.push(`<div class="dlv-vcamps">${it.verifyCamps.map(renderVerifyCampRow).join("")}</div>`);
    // Item 5a: the card's own "🚫 Manage ↓" button (below) deliberately opens
    // just the Blacklisted-domains fold — the simple, matching-scope target
    // for "pause these domains". The full inbox & domain manager (bulk
    // multi-domain rotation, filters, CSV export) is a different, heavier
    // tool — mentioned here as a plain secondary link so it's still one
    // click away for anyone who needs it, without it being the DEFAULT
    // target of the primary action.
    if (it.blacklistRows && it.blacklistRows.length) extraBits.push(`<div class="dlv-ai-action" style="margin-top:6px">${it.blacklistRows.length} domain(s) listed. Full list + actions in the <b>Blacklisted domains</b> tab, or <a class="dlv-dl" data-act="open-manager">open the manager for advanced rotation</a>.</div>`);
    // (The old "Usual causes:" plain line was folded into the card's numbered
    // step 2 — item 3 — so the same advice isn't printed twice.)
    if (it.sigCsv) extraBits.push(`<div style="margin-top:6px"><a class="dlv-dl" data-act="view-data" data-file="signature">👁 View signature issues</a></div>`);
    if (it.devCsv) extraBits.push(`<div style="margin-top:6px"><a class="dlv-dl" data-act="view-data" data-file="sending-deviation">👁 View deviations</a></div>`);
    if (it.newCsv) extraBits.push(`<div style="margin-top:6px"><a class="dlv-dl" data-act="view-data" data-file="new-mailboxes">👁 View new/untagged</a></div>`);
    if (it.retiredCsv) extraBits.push(`<div style="margin-top:6px"><a class="dlv-dl" data-act="view-data" data-file="retired">👁 View retired domains</a></div>`);
    if (it.wcCsv) extraBits.push(`<div style="margin-top:6px"><a class="dlv-dl" data-act="view-data" data-file="warmup-config">👁 View warmup-config issues</a></div>`);
    const btns = [];
    if (it.hypertide) {
      btns.push(`<button class="btn sm" data-act="draft-email">✉️ Draft email</button>`);
      // Item 2: once "Draft email" has been used this session, the card carries
      // a small durable chip — evidence that outlives the toast and the modal.
      if ((S.A.history || []).some((h) => h && h.action === "hypertide_draft" && h.ts != null)) {
        btns.push(`<span class="dlv-tag ok" style="align-self:center" title="The escalation email was drafted this session">✉️ drafted</span>`);
      }
    }
    if (it._openManager) btns.push(`<button class="btn sm" data-act="open-manager">Open manager ↓</button>`);
    if (it.reminderDue) btns.push(`<button class="btn sm" data-act="open-reminders">⏰ Reminders ↓</button>`);
    if (it.key === "warmup-notwarming" && it.count > 0) btns.push(`<button class="btn sm primary" data-act="open-warmup-fix">⚡ Enable warmup on all</button>`);
    if (it.key === "signatures") btns.push(`<button class="btn sm primary" data-act="open-sig-fix">✍️ Fix signatures…</button>`);
    if (it.key === "new-unprocessed") btns.push(`<button class="btn sm primary" data-act="open-process-new">🏷 Process…</button>`);
    if (it.blacklistRows) btns.push(`<button class="btn sm" data-act="open-blacklist">🚫 Manage ↓</button>`);
    if (it.key) btns.push(`<button class="btn sm" data-act="mark-done" data-key="${it.key}" data-count="${it.count || 0}" title="Mark as actioned">✓ Mark done</button>`);
    const plain = plainLineFor(it.text + " " + (it.action || ""));
    // Item 3: multi-step cards render each numbered step on its own line —
    // single-action cards keep the one-line "→ action" form.
    const actionHtml = (it.actionLines && it.actionLines.length)
      ? it.actionLines.map((l, li) => `<div class="dlv-ai-action"${li ? ' style="margin-top:3px"' : ""}><span class="arrow">→</span>${glossify(l)}</div>`).join("")
      : `<div class="dlv-ai-action"><span class="arrow">→</span>${glossify(it.action || "")}</div>`;
    return `<div class="dlv-ai ${it.level}">
      <span class="dlv-ai-n ${it.level}">${i + 1}</span>
      <div class="dlv-ai-body">
        <div class="dlv-ai-text">${glossify(it.text)}</div>
        ${actionHtml}
        ${plain ? `<div class="dlv-plain">${esc(plain)}</div>` : ""}
        ${extraBits.join("")}
      </div>
      <div class="dlv-ai-btns">${btns.join("")}</div>
    </div>`;
  }

  function renderTodo(D) {
    let html = "";
    // Fix #1: items marked done in the last ~12s render a temporary inline
    // stub in the exact slot the card occupied — interleave by walking rawTodo
    // (the canonical order activeTodo is filtered from) so the stub sits where
    // the item was, not appended at the bottom.
    const now = Date.now();
    const stubOf = (it) => (it.key && _doneStubs[it.key] && _doneStubs[it.key] > now) ? renderDoneStub(it) : "";
    if (D.activeTodo.length) {
      html += `<div class="dlv-todo-head">Today's to-do <span class="dlv-todo-count">${D.activeTodo.length}</span></div><div class="dlv-actions-list">`;
      let ai = 0;
      (D.rawTodo || D.activeTodo).forEach((it) => {
        if (D.activeTodo.indexOf(it) !== -1) html += renderTodoCard(it, ai++);
        else if (D.doneTodo.indexOf(it) !== -1) html += stubOf(it);
      });
      html += "</div>";
    } else {
      // Zero active items left — a just-marked-done stub still needs its slot
      // (this is exactly the "last item vanished into All clear" moment).
      const stubs = D.doneTodo.map(stubOf).join("");
      if (stubs) html += `<div class="dlv-actions-list" style="margin-bottom:12px">${stubs}</div>`;
      html += `<div class="dlv-all-clear"><div class="big">🟢 All clear</div><div class="sub">${(D.doneTodo.length || D.resolvedTodo.length) ? "Everything flagged today has been handled." : "Nothing needs action today — the numbers above are for reference."}</div></div>`;
    }
    if (D.resolvedTodo.length) {
      html += `<div class="dlv-todo-resolved-label">Auto-resolved today</div><div class="dlv-good-row">${D.resolvedTodo.map((it) => `<span class="dlv-good-chip dlv-resolved-chip" title="${esc(it.text)}">✓ handled</span>`).join("")}</div>`;
    }
    if (D.doneTodo.length) {
      // Defect 3: needs an id so the undo toast's hint (and anything else)
      // can actually openFold()/scroll to this specific fold — it had none
      // before, so any attempt to target it directly was a silent no-op.
      // Item 5c: the toast's "undo later from ✅ Actioned ↓" hint disappears
      // in ~3s — the ONLY other way to know this fold is where undos live was
      // reading that toast at the moment it fired. A persistent hint right on
      // the (always-visible) summary means it's still findable tomorrow.
      html += `<details class="dlv-fold" id="dlv-fold-actioned"><summary>✅ Actioned<span class="hint">${D.doneTodo.length} marked done — reappears only if it grows · (undo items you marked done here — any time)</span></summary><div class="dlv-fold-body"><div class="dlv-actions-list">` +
        D.doneTodo.map(renderAckRow).join("") +
        "</div></div></details>";
    }
    if (D.goodChips.length) {
      html += `<div class="dlv-good-row">${D.goodChips.map((g) => `<span class="dlv-good-chip">✓ ${esc(g)}</span>`).join("")}</div>`;
    }
    return html;
  }

  /* ============================================================
     14. Blacklisted domains fold
     ============================================================ */
  function blDueChip(ts) {
    if (!ts) return "";
    const left = ts - Date.now();
    if (left <= 0) return ' <span class="dlv-tag blocked">due now</span>';
    const dl = Math.ceil(left / 864e5);
    return ` <span class="dlv-tag ${dl <= 2 ? "inactive" : "md"}">due in ${dl}d</span>`;
  }
  function renderBlacklistRow(b) {
    const chips = [];
    if (b.batch) chips.push(b.batch);
    // Bookkeeping tags like "dash-rest-2"/"dash-rest-15" are internal rest-batch
    // numbers, not something a tester should ever see as raw text — the resting
    // state they encode is already conveyed by the friendlier restChip below.
    (b.tags || []).forEach((t) => { if (!/^dash-rest-\d+$/i.test(t)) chips.push(t); });
    const tagChips = chips.length ? chips.map((t) => `<span class="dlv-tag md">${esc(t)}</span>`).join("") : `<span class="dlv-tag md" style="opacity:.6">untagged</span>`;
    const restChip = b.rested > 0 ? `<span class="dlv-tag inactive">🌙 ${glossify("resting")} (${b.rested})</span>${blDueChip(b.restedDue)}` : (b.cleared ? `<span class="dlv-tag ok">✓ cleared</span>` : "");
    const reBtn = b.rested > 0 ? `<button class="btn sm" data-act="domain-reactivate-bl" data-domain="${esc(b.domain)}" title="Restore saved caps and resume sending">☀️ Reactivate</button>` : "";
    // Still-sending (not resting, not cleared) domains get their own per-domain
    // Pause — the bulk "⏸ Pause sending" button above stays, this is just a
    // faster path when only one domain needs it (fix #7a).
    const pauseBtn = (!(b.rested > 0) && !b.cleared) ? `<button class="btn sm" data-act="pause-blacklist-domain" data-domain="${esc(b.domain)}" title="Pause sending on just this domain">⏸ Pause</button>` : "";
    return `<div class="dlv-vcamp">
      <a href="${esc(b.url)}" target="_blank" rel="noopener">${esc(b.domain)}</a>${tagChips}
      <span class="dlv-vmeta"><b>${b.mailboxes}</b> mbx</span>
      <span class="dlv-vmeta">${glossify(b.lists)}</span>
      <span class="dlv-tag blocked">${glossify(b.advice)}</span>${restChip}
      <div class="dlv-vbtns">${pauseBtn}${reBtn}<a class="btn sm" href="${esc(b.url)}" target="_blank" rel="noopener">${glossify("MXToolbox")} ↗</a></div>
    </div>`;
  }
  // Formerly a collapsible <details class="dlv-fold"> that only rendered when
  // there were rows — now its own always-visible "Blacklisted domains" tab
  // panel, so it renders (with an empty state) even when the fleet is clean.
  function renderBlacklistPanel(D) {
    const rows = S.A.blacklistRows;
    const hint = rows.length ? rows.length + " listed · pause · reactivate · delist" : "clean — nothing listed";
    let body;
    if (rows.length) {
      const summaryBits = [rows.length + " domain(s) on SURBL / Spamhaus", D.blSending + " mailbox(es) still sending", D.blResting + " rested"];
      if (D.blClearedCount > 0) summaryBits.push(D.blClearedCount + " cleared, ready to reactivate");
      body = `<div class="dlv-bl-summary">${summaryBits.join(" · ")}</div>
        <div class="dlv-bl-actions">
          ${(() => { const n = rows.filter((r) => !(r.rested > 0) && !r.cleared).length; return n ? `<button class="btn sm" data-act="pause-blacklisted" title="Pauses every blacklisted domain that is still sending — the bulk action, distinct from each row's own ⏸ Pause">⏸ Pause all still-sending (${n})</button>` : ""; })()}
          ${D.blClearedCount > 0 ? `<button class="btn sm" data-act="reactivate-cleared">☀️ Reactivate cleared (${D.blClearedCount})</button>` : ""}
          <button class="btn sm" data-act="open-delisting">📋 Delisting prep</button>
          <a class="dlv-dl" data-act="view-data" data-file="blacklist" style="align-self:center;margin-left:4px">👁 View</a>
        </div>
        <div class="dlv-bl-scroll"><div class="dlv-vcamps">${rows.map(renderBlacklistRow).join("")}</div></div>`;
    } else {
      body = `<div class="dlv-empty">✓ No domains currently blacklisted.</div>`;
    }
    return `<div class="dlv-subtab-panel" id="dlv-fold-blacklist">
      <div class="dlv-subtab-head">🚫 Blacklisted domains<span class="hint">${hint}</span></div>
      <div class="dlv-fold-body">${body}</div>
    </div>`;
  }

  /* ============================================================
     15. Inbox & domain manager — 8-view selector, shared search +
         batch dropdown, per-row + bulk actions, caps-by-reply-rate.
     ============================================================ */
  function mgrRowsForView(D) {
    const A = S.A;
    switch (UI.mgr.view) {
      case "reconnect": return A.inboxRows.filter((r) => r.kind === "reconnect");
      case "warmupoff": return A.inboxRows.filter((r) => r.kind === "warmupoff");
      case "blocked": return A.inboxRows.filter((r) => r.kind === "blocked");
      case "inwarmup": return A.inboxRows.filter((r) => r.kind === "ok" && r.cap === 0 && !r.rested);
      case "rested": return A.inboxRows.filter((r) => r.kind === "ok" && r.rested);
      case "sending": return A.inboxRows.filter((r) => r.kind === "ok" && r.cap > 0);
      case "all": return A.inboxRows.slice();
      default: return [];
    }
  }

  /* Defaults the domain-filter dropdown to "Needs warm-up" whenever the domain
     view is entered while there are actionable flagged domains, instead of
     always landing on "resting" (which buried the discoverability of warm-up
     work). Respects a manual pick — see the mgr-domfilter change handler,
     which sets UI.mgr._domFilterUserSet so we never fight the user. */
  function autoDefaultDomFilter(D) {
    if (UI.mgr.view !== "domain" || UI.mgr._domFilterUserSet) return;
    UI.mgr.domFilter = D.flaggedActionable > 0 ? "warmup" : "resting";
  }

  // Formerly a collapsible <details class="dlv-fold"> — now its own always-
  // visible "Inbox & domain manager" tab panel (dropped the <details> wrapper,
  // kept everything else: intro line, 8-view selector, filters, table, CSV).
  function renderManagerPanel(D) {
    autoDefaultDomFilter(D);
    const isD = UI.mgr.view === "domain";
    const mc = D.inboxCounts;
    const dc = D.domainHealthCounts;
    const batches = isD ? D.dhBatches : D.inboxBatches;
    const viewSel = `<select class="dlv-select" style="width:auto" data-act="mgr-view">
      <option value="domain" ${isD ? "selected" : ""}>Domain reply-rate · rotation (${D.flaggedActionable} flagged)</option>
      <option value="reconnect" ${UI.mgr.view === "reconnect" ? "selected" : ""}>Connection failed · reconnect (${mc.reconnect})</option>
      <option value="warmupoff" ${UI.mgr.view === "warmupoff" ? "selected" : ""}>Warmup off · re-enable (${mc.warmupoff})</option>
      <option value="blocked" ${UI.mgr.view === "blocked" ? "selected" : ""}>Blocked → Hypertide (${mc.blocked})</option>
      <option value="inwarmup" ${UI.mgr.view === "inwarmup" ? "selected" : ""}>In warmup · 0/day (${mc.inwarmup})</option>
      <option value="rested" ${UI.mgr.view === "rested" ? "selected" : ""}>Rested by dashboard · due tracking (${mc.rested})</option>
      <option value="sending" ${UI.mgr.view === "sending" ? "selected" : ""}>Sending · &gt;0/day (${mc.sending})</option>
      <option value="all" ${UI.mgr.view === "all" ? "selected" : ""}>All mailboxes (${mc.total})</option>
    </select>`;
    const domFilter = isD ? `<select class="dlv-select" style="width:auto" data-act="mgr-domfilter">
      <option value="resting" ${UI.mgr.domFilter === "resting" ? "selected" : ""}>🌙 Warmed up by dashboard (${dc.resting})</option>
      <option value="warmup" ${UI.mgr.domFilter === "warmup" ? "selected" : ""}>Needs warm-up · flagged (${dc.flagged})</option>
      <option value="maildoso" ${UI.mgr.domFilter === "maildoso" ? "selected" : ""}>Maildoso (by design)</option>
      <option value="keep" ${UI.mgr.domFilter === "keep" ? "selected" : ""}>Keep active</option>
      <option value="all" ${UI.mgr.domFilter === "all" ? "selected" : ""}>All domains</option>
    </select>` : "";
    const batchSel = `<select class="dlv-select" style="width:auto" data-act="mgr-batch"><option value="">All batches</option>${batches.map((b) => `<option value="${esc(b.name)}" ${UI.mgr.batch === b.name ? "selected" : ""}>${esc(b.name)} (${b.count})</option>`).join("")}</select>`;
    const { minSent, cutoff } = dhCutoffMin();
    // Item 4: every control in this filter row now carries a visible label —
    // "Window:" alone left the two bare date inputs and the numeric cutoffs
    // for the reader to decode ("from/to" what? under what?).
    const domCtrl = isD ? `<div class="dlv-mb-bar" style="margin-bottom:8px">
        <span class="dlv-mb-count">Window: from</span>
        <input class="dlv-input" style="width:auto" type="date" value="${S.A.domainHealth.start}" data-act="mgr-dh-start" title="Start of the reporting window">
        <span class="dlv-mb-count">to</span>
        <input class="dlv-input" style="width:auto" type="date" value="${S.A.domainHealth.end}" data-act="mgr-dh-end" title="End of the reporting window">
        <span class="dlv-mb-count">min sent</span><input class="dlv-input" style="width:78px" type="number" value="${minSent}" data-act="mgr-dh-minsent" title="Only judge domains with at least this many sends in the window">
        <span class="dlv-mb-count">flag if reply % under</span><input class="dlv-input" style="width:70px" type="number" step="0.1" value="${cutoff}" data-act="mgr-dh-cutoff" title="Domains replying below this rate get flagged for warm-up">${glossMark("Only domains with at least 'min sent' emails in the window are judged; any of them replying under the cutoff % gets flagged for warm-up rest.")}
      </div>` : "";
    const head = isD
      ? `<th>Domain</th><th style="text-align:right">Sent</th><th style="text-align:right">Leads</th><th style="text-align:right">Reply rate</th><th style="text-align:right">Positive</th><th style="text-align:right">Bounce</th><th style="text-align:right">Action</th>`
      : `<th class="ck"><input type="checkbox" data-act="mgr-select-all"></th><th>Mailbox</th><th>Batch</th><th style="text-align:right">Cap/day</th><th style="text-align:right">Due back</th><th>Warmup / status</th><th>Issue</th><th style="text-align:right">Action</th>`;
    const foot = isD
      ? `<div style="margin-top:8px"><a class="dlv-dl" data-act="view-data" data-file="domain-health-warmup">👁 View warmup list</a> &nbsp; <a class="dlv-dl" data-act="view-data" data-file="domain-health">👁 View full table</a></div>`
      : `<div style="margin-top:8px"><a class="dlv-dl" data-act="view-data" data-file="mailboxes">👁 View problem mailboxes</a></div>`;
    return `<div class="dlv-subtab-panel" id="dlv-fold-manager">
      <div class="dlv-subtab-head">🛠 Inbox &amp; domain manager<span class="hint">${D.flaggedActionable ? D.flaggedActionable + " domain(s) need warm-up →" : ""} pause · reactivate · reconnect</span></div>
      <div class="dlv-fold-body">
        <div class="dlv-plain" style="margin:-2px 0 12px">Rotate tired domains into warm-up rest, reconnect failed mailboxes, and adjust daily sending caps. Changes confirm before applying.</div>
        ${domCtrl}
        <div class="dlv-mb-bar">
          <span class="dlv-mb-cap">View</span>${viewSel}${isD ? `<span class="dlv-mb-cap">Show</span>` : ""}${domFilter}${batchSel}
          <input class="dlv-input" style="flex:1;min-width:160px" type="text" placeholder="Search ${isD ? "domain" : "email or domain"}…" value="${esc(UI.mgr.search)}" data-act="mgr-search">
          <button class="btn sm" data-act="mgr-refresh" title="Re-pull the current view from Smartlead">↻ Refresh</button>
          ${isD ? `<button class="btn sm primary" data-act="open-caps-preview" title="Set daily cap by reply-rate tier on Outlook/Azure mailboxes">⚙ Caps by reply rate</button>${glossMark("Sets each mailbox's daily send limit based on how well its domain is replying.")}` : ""}
          <span class="dlv-mb-count" id="dlv-mgr-count"></span>
          <span id="dlv-mgr-bulk" style="margin-left:auto;display:flex;gap:7px;align-items:center"></span>
        </div>
        <div class="dlv-mb-wrap"><div class="dlv-mb-scroll"><table class="dlv-mb"><thead><tr>${head}</tr></thead><tbody id="dlv-mgr-body"></tbody></table></div></div>
        ${foot}
      </div>
    </div>`;
  }

  function paintManagerRows() {
    const body = $id("dlv-mgr-body");
    if (!body) return;
    if (UI.mgr.view === "domain") paintDomainRows(); else paintMailboxRows();
  }

  function paintMailboxRows() {
    const body = $id("dlv-mgr-body");
    if (!body) return;
    let rows;
    if (isLive()) {
      // Live: rows for this view+batch come from GET /inboxes (endpoint already
      // filters by view & batch; search stays a client-side filter below).
      if (!ensureMgrLive()) {
        body.innerHTML = DATA.mgr.error
          ? `<tr><td colspan="8" class="dlv-empty">Couldn't load live mailboxes — <a class="dlv-dl" data-act="mgr-refresh">retry</a>.</td></tr>`
          : `<tr><td colspan="8" class="dlv-empty"><span class="dlv-spinner ink"></span> &nbsp;Loading live mailboxes…</td></tr>`;
        const bw0 = $id("dlv-mgr-bulk"); if (bw0) bw0.innerHTML = "";
        const cnt0 = $id("dlv-mgr-count"); if (cnt0) cnt0.textContent = DATA.mgr.error ? "load failed" : "loading…";
        return;
      }
      rows = (DATA.mgr.rows || []).slice();
    } else {
      const D = fullDerive();
      rows = mgrRowsForView(D);
    }
    const q = (UI.mgr.search || "").trim().toLowerCase();
    if (q) rows = rows.filter((r) => (r.email || "").toLowerCase().includes(q) || (r.domain || "").toLowerCase().includes(q));
    if (UI.mgr.batch) rows = rows.filter((r) => (r.tags || []).includes(UI.mgr.batch));
    const selectable = UI.mgr.view !== "blocked";
    const cnt = $id("dlv-mgr-count");
    if (cnt) cnt.textContent = rows.length + " shown" + (selectable ? " · " + UI.mgr.sel.size + " selected" : "");
    const bw = $id("dlv-mgr-bulk");
    if (bw) {
      const n = UI.mgr.sel.size;
      if (UI.mgr.view === "reconnect") bw.innerHTML = `<button class="btn sm" ${n ? "" : "disabled"} data-act="bulk-reconnect">🔌 Reconnect (${n})</button>`;
      else if (UI.mgr.view === "warmupoff") bw.innerHTML = `<button class="btn sm" ${n ? "" : "disabled"} data-act="bulk-reenable">⚡ Re-enable (${n})</button>`;
      else if (UI.mgr.view === "blocked") bw.innerHTML = "";
      else bw.innerHTML = `<button class="btn sm" ${n ? "" : "disabled"} data-act="bulk-warmup">🌙 Put in warmup (${n})</button><button class="btn sm primary" ${n ? "" : "disabled"} data-act="bulk-restore">☀️ Restore sending (${n})</button>`;
    }
    body.innerHTML = rows.map((r) => {
      const ck = selectable ? `<td class="ck"><input type="checkbox" ${UI.mgr.sel.has(r.id) ? "checked" : ""} data-act="mgr-row-select" data-id="${r.id}"></td>` : `<td class="ck"></td>`;
      const capCell = r.cap === 0 ? `<span class="dlv-tag inactive">0 · warmup</span>` : `<b>${r.cap}</b>/day`;
      const rested = r.rested ? ` <span class="dlv-tag md">rested</span>` : "";
      let dueCell = `<span class="dlv-mb-dom">—</span>`;
      if (r.restedAt) { const left = (r.restedAt + 7 * 864e5) - Date.now(); if (left <= 0) dueCell = `<span class="dlv-tag blocked">due now</span>`; else { const dl = Math.ceil(left / 864e5); dueCell = `<span class="${dl <= 2 ? "dlv-tag inactive" : "dlv-mb-dom"}">in ${dl}d</span>`; } }
      let st;
      if (r.kind === "blocked") st = `<span class="dlv-tag blocked">blocked</span>`;
      else if (r.kind === "reconnect") st = `<span class="dlv-tag blocked">${esc(r.reason_category || "conn fail")}</span>`;
      else if (r.kind === "warmupoff") st = `<span class="dlv-tag inactive">warmup off</span>`;
      else st = esc(r.warmup_status);
      if (r.maildoso) st += ` <span class="dlv-tag md">Maildoso</span>`;
      let action;
      if (r.kind === "blocked") action = `<span class="dlv-mb-dom">${esc(r.reason_category || "hosting")} → Hypertide</span>`;
      else if (r.kind === "reconnect") action = `<button class="btn sm" data-act="reconnect-one" data-id="${r.id}">🔌 Reconnect</button>`;
      else if (r.kind === "warmupoff") action = `<button class="btn sm" data-act="reenable-one" data-id="${r.id}">⚡ Re-enable</button>`;
      else action = "";
      return `<tr id="dlv-mb-${r.id}">${ck}
        <td><div class="dlv-mb-email">${esc(r.email)}</div><div class="dlv-mb-dom">${esc(r.domain)}</div></td>
        <td><div class="dlv-mb-dom">${(r.tags || []).slice(0, 2).join(" · ")}</div></td>
        <td style="text-align:right">${capCell}${rested}</td>
        <td style="text-align:right">${dueCell}</td>
        <td>${st}</td>
        <td><div class="dlv-mb-reason" title="${esc(r.reason)}">${glossify(r.reason || "")}</div></td>
        <td style="text-align:right">${action}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="8" class="dlv-empty">No mailboxes in this view</td></tr>`;
    const selAll = document.querySelector('[data-act="mgr-select-all"]');
    if (selAll) { const ids = rows.map((r) => r.id); selAll.checked = selectable && ids.length > 0 && ids.every((id) => UI.mgr.sel.has(id)); selAll.style.visibility = selectable ? "visible" : "hidden"; }
  }

  function paintDomainRows() {
    const body = $id("dlv-mgr-body");
    // Live: the /run blob already seeded a live domainHealth, so render current
    // rows immediately; ensureDhLive() refetches (non-blocking) only when the
    // window / min-sent / cutoff controls change the query key, then repaints.
    if (isLive()) ensureDhLive();
    const D = fullDerive();
    const { minSent, cutoff } = dhCutoffMin();
    const resting = D.resting, restingDue = D.restingDue;
    let rows = D.dhRows.slice();
    rows.sort((a, b) => (a.flag === "warmup" ? 0 : 1) - (b.flag === "warmup" ? 0 : 1) || a.reply_rate - b.reply_rate || b.sent - a.sent);
    const f = UI.mgr.domFilter;
    rows = rows.filter((d) => {
      if (f === "warmup") return d.flag === "warmup";
      if (f === "resting") return (resting[d.domain] || 0) > 0 && d.sent >= minSent && d.reply_rate < cutoff;
      if (f === "maildoso") return d.flag === "maildoso";
      if (f === "keep") return d.sent >= minSent && d.flag !== "warmup" && d.flag !== "maildoso";
      return true;
    });
    if (f === "resting") rows.sort((a, b) => (restingDue[a.domain] || 0) - (restingDue[b.domain] || 0));
    const q = (UI.mgr.search || "").trim().toLowerCase();
    if (q) rows = rows.filter((d) => d.domain.toLowerCase().includes(q));
    if (UI.mgr.batch) rows = rows.filter((d) => (d.batches || []).includes(UI.mgr.batch));
    const recovered = D.recovered;
    window._dlvRecovered = recovered;
    const cnt = $id("dlv-mgr-count");
    if (f === "resting") cnt.innerHTML = rows.length + " still resting (sent ≥" + minSent + " · reply &lt;" + cutoff + "%)" + (recovered.length ? ` · <b style="color:var(--green)">${recovered.length} recovered — ready to reactivate</b>` : "");
    else cnt.textContent = rows.length + " shown · " + D.flaggedActionable + " to warm up" + (D.restingCount ? " · " + D.restingCount + " resting fleet-wide" : "");
    const bulk = $id("dlv-mgr-bulk");
    if (bulk) {
      let b = "";
      if (f === "resting" && recovered.length) b += `<button class="btn sm" style="background:var(--green);color:#fff;border-color:var(--green)" data-act="domain-reactivate-recovered">☀️ Reactivate recovered (${recovered.length})</button>`;
      if (D.flaggedActionable) b += `<button class="btn sm" data-act="domain-bulk-flagged">🌙 Move all flagged (${D.flaggedActionable})</button>`;
      if (D.restingCount) b += `<button class="btn sm primary" data-act="domain-reactivate-all">☀️ Reactivate all (${D.restingCount})</button>`;
      bulk.innerHTML = b;
    }
    const isRec = (d) => d.sent > 0 && d.reply_rate >= cutoff;
    body.innerHTML = rows.map((d) => {
      const rr = d.reply_rate.toFixed(2) + "%";
      const brHot = d.bounce_rate >= 3 ? ' style="color:var(--red);font-weight:700"' : "";
      const rrCol = d.flag === "warmup" ? "color:var(--red);font-weight:700" : (d.reply_rate >= 1 ? "color:var(--green);font-weight:700" : "");
      const restN = resting[d.domain] || 0;
      let action;
      if (restN > 0) {
        const pill = isRec(d) ? `<span class="dlv-tag ok" title="Reply rate recovered — reactivate">✓ recovered ${rr} (${restN} mbx)</span>` : `<span class="dlv-tag inactive">🌙 resting (${restN})</span>${blDueChip(restingDue[d.domain])}`;
        action = pill + ` <button class="btn sm" data-act="domain-reactivate" data-domain="${esc(d.domain)}">☀️ Reactivate</button>`;
      } else if (d.flag === "maildoso") action = `<span class="dlv-tag md">Maildoso · warming</span>`;
      else if (d.flag === "warmup") action = `<button class="btn sm" data-act="domain-warmup" data-domain="${esc(d.domain)}">🌙 Warm up</button>`;
      else if (d.flag === "watch") action = `<span class="dlv-tag inactive">watch</span>`;
      else action = `<span class="dlv-tag ok">keep</span>`;
      return `<tr><td><div class="dlv-mb-email">${esc(d.domain)}</div>${(d.batches && d.batches.length) ? `<div class="dlv-mb-dom">${d.batches.slice(0, 3).join(" · ")}</div>` : ""}</td>
        <td style="text-align:right">${d.sent}</td>
        <td style="text-align:right">${d.lead}</td>
        <td style="text-align:right;${rrCol}">${rr} <span class="dlv-mb-dom">(${d.replied})</span></td>
        <td style="text-align:right">${d.positive_rate.toFixed(2)}%</td>
        <td style="text-align:right"${brHot}>${d.bounce_rate.toFixed(2)}%</td>
        <td style="text-align:right">${action}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="7" class="dlv-empty">No domains in this view</td></tr>`;
  }

  /* ============================================================
     16. Performance by batch / provider
     ============================================================ */
  // Formerly a collapsible <details class="dlv-fold"> — now its own always-
  // visible "Performance by batch" tab panel (best/worst chips + full table +
  // CSV, unchanged).
  function renderBatchPanel() {
    const bs = S.A.batchStats.filter((b) => b.mailboxes > 0);
    // NOTE: this panel must always render, even with zero batches — the
    // "▲▼ Best & worst batch ↓" signpost link (renderFleetTiles) switches to
    // this tab unconditionally (fix: that early-return "" here was the one
    // fold link, out of the four, whose target could vanish — clicking it
    // then just left the page wherever it already was, which reads as
    // "landed on the to-do list" right below the signpost).
    let summary = "";
    let body;
    if (bs.length) {
      const strictCand = bs.filter((b) => b.sent >= 1000);
      let cand = strictCand; if (cand.length < 2) cand = bs.filter((b) => b.sent > 0);
      if (cand.length >= 2) {
        const byReply = [...cand].sort((a, b) => b.reply_rate - a.reply_rate);
        const best = byReply[0], worst = byReply[byReply.length - 1];
        // Fix #8a: only claim the ≥1,000-sent qualifier when that's actually the
        // filter in effect — the low-volume fallback below (used when fewer than
        // 2 batches clear 1,000 sent) would make the claim false otherwise.
        // Fix #4b (panels 9-10): the volume floor now sits INLINE in the chip
        // line itself ("▲ Best (≥1,000 sent): …") instead of trailing at the
        // end where it read as fine print detached from the verdict.
        const floor = cand === strictCand ? "(≥1,000 sent)" : "(any sends — too few clear 1,000)";
        summary = `<div class="dlv-bt-summary">
          <span class="dlv-bt-sum best">▲ Best ${floor}${glossMark(BATCH_DEF)}: <b>${esc(best.batch)}</b> — ${best.reply_rate}% reply · ${best.bounce_rate}% bounce · last 7 days</span>
          <span class="dlv-bt-sum worst">▼ Worst ${floor}${glossMark(BATCH_DEF)}: <b>${esc(worst.batch)}</b> — ${worst.reply_rate}% reply · ${worst.bounce_rate}% bounce · last 7 days</span>
        </div>`;
      }
      body = renderBatchRows(bs);
    } else {
      body = `<div class="dlv-empty">No batch/provider data yet.</div>`;
    }
    return `<div class="dlv-subtab-panel" id="dlv-fold-batch">
      <div class="dlv-subtab-head">📦 Performance by batch (client / mailbox pool)${glossMark(BATCH_DEF)}<span class="hint">${bs.length ? bs.length + " batches · compare deliverability" : "no data yet"}</span></div>
      <div class="dlv-fold-body">${summary}${body}</div>
    </div>`;
  }
  function renderBatchRows(bs) {
    const rr = (v) => (v >= 1 ? "g" : v >= 0.5 ? "y" : "r");
    const brc = (v) => (v < 2 ? "g" : v < 3 ? "y" : "r");
    const rowsHtml = bs.map((b) => {
      const reply = b.sent ? `<span class="dlv-bt-${rr(b.reply_rate)}">${b.reply_rate}%</span>` : `<span class="dlv-bt-mut">—</span>`;
      const bounce = b.sent ? `<span class="dlv-bt-${brc(b.bounce_rate)}">${b.bounce_rate}%</span>` : `<span class="dlv-bt-mut">—</span>`;
      const blk = b.blacklisted ? `<span class="dlv-bt-r">${b.blacklisted}</span>` : `<span class="dlv-bt-mut">0</span>`;
      const issues = b.dead + b.blocked;
      return `<tr><td class="dlv-bt-name">${esc(b.batch)}</td><td>${b.mailboxes}</td><td>${b.sending}</td><td>${b.warmup}</td><td>${b.sent ? fmtN(b.sent) : `<span class="dlv-bt-mut">—</span>`}</td><td>${reply}</td><td>${bounce}</td><td>${blk}</td><td>${issues ? `<span class="dlv-bt-y">${issues}</span>` : `<span class="dlv-bt-mut">0</span>`}</td></tr>`;
    }).join("");
    return `<div class="dlv-bt-wrap"><table class="dlv-bt"><thead><tr><th>Batch</th><th>Mailboxes</th><th>Sending</th><th>Warmup</th><th>Sent (7d)</th><th>Reply&nbsp;%</th><th>Bounce&nbsp;%</th><th>Blacklist</th><th>Issues</th></tr></thead><tbody>${rowsHtml}</tbody></table></div>
      <div class="dlv-mb-count" style="margin-top:10px">Reply / Bounce are volume-weighted over the last 7 days. "Issues" = dead + blocked. <a class="dlv-dl" data-act="view-data" data-file="batch-stats">👁 View batch performance</a></div>`;
  }

  /* ============================================================
     17. Restore reminders
     ============================================================ */
  const WU_REASON_TXT = { off: "warmup off — enable", missing: "mailbox missing at provider", transient: "transient bounce (self-clears)", blocked: "warmup blocked by provider", dead: "dead — needs reconnect" };
  function renderReminderRow(r) {
    const today = todayISO();
    const due = r.dueDate <= today;
    const daysLeft = daysUntil(r.dueDate);
    const status = r.done ? `<span class="dlv-rem-tag done">✓ added back</span>` : (due ? `<span class="dlv-rem-tag due">DUE now</span>` : `<span class="dlv-rem-tag wait">in ${daysLeft}d</span>`);
    const h = S.A.remHealth[r.id];
    let healthLine = "";
    if (!r.done && h) {
      const enableable = h.reasons.off || 0;
      let s = `<b>${h.total}</b> mailboxes · <span style="color:var(--green)">${h.warming} warming</span>`;
      if (h.failed) s += ` · <span style="color:var(--red);font-weight:700">${h.failed} not warming</span>` + (enableable ? ` <button class="btn sm" style="padding:4px 9px;font-size:11px" data-act="rem-enable-warmup" data-id="${r.id}">⚡ Enable warmup (${enableable})</button>` : "");
      else s += ` <span style="color:var(--green)">✓ all warming</span>`;
      if (h.dead) s += ` · <span style="color:var(--ink-3)">${h.dead} dead (needs reconnect)</span>`;
      const parts = Object.entries(h.reasons || {}).filter(([k, v]) => v > 0).map(([k, v]) => `<b>${v}</b> ${WU_REASON_TXT[k] || k}`);
      if (parts.length) s += `<div style="margin-top:4px;font-size:11px">${parts.join(" &nbsp;·&nbsp; ")}</div>`;
      healthLine = `<div class="dlv-rem-health">${s}</div>`;
    }
    return `<div class="dlv-rem-row ${r.done ? "done" : ""}">
      <div class="dlv-rem-main">
        <div class="dlv-rem-doms">${esc((r.domains || []).join(", "))}</div>
        <div class="dlv-rem-meta">restored ${esc(r.restoredDate)} · due ${esc(r.dueDate)}${r.note ? " · " + esc(r.note) : ""}</div>
        ${healthLine}
      </div>
      <div class="dlv-rem-acts">${status}${r.done ? `<button class="btn sm" data-act="rem-undo" data-id="${r.id}">↩ Undo</button>` : `<button class="btn sm primary" data-act="rem-done" data-id="${r.id}">✓ Mark added</button>`}<button class="btn sm" data-act="rem-remove" data-id="${r.id}" title="Delete this reminder">🗑 Remove</button></div>
    </div>`;
  }
  // Formerly a collapsible <details class="dlv-fold"> inside the Overview
  // scroll — now its own always-visible "Restore reminders" tab panel (dropped
  // the <details> wrapper, kept everything else: the add-reminder form, empty-
  // domain inline validation, live "will be due" preview, and per-reminder rows
  // with warm-up health line + enable-warmup / mark-added / undo / remove).
  function renderRemindersPanel(D) {
    const rem = S.A.reminders || [];
    const pending = rem.filter((r) => !r.done);
    const dueN = pending.filter((r) => r.dueDate <= todayISO()).length;
    // Defect 6c: the hint used to only count reminders ("N pending"), leaving
    // a reader to guess how many domains that actually covers (one reminder
    // can bundle several domains — see r2's two). Count both, straight off
    // the same rows the panel lists below.
    const domainSet = new Set();
    rem.forEach((r) => (r.domains || []).forEach((d) => domainSet.add(d)));
    const hintBits = [rem.length + " reminder" + (rem.length === 1 ? "" : "s"), domainSet.size + " domain" + (domainSet.size === 1 ? "" : "s")];
    if (dueN) hintBits.push(dueN + " due");
    const list = rem.length ? rem.map(renderReminderRow).join("") : `<div class="dlv-mb-count" style="padding:10px 0">No reminders yet.</div>`;
    return `<div class="dlv-subtab-panel" id="dlv-fold-reminders">
      <div class="dlv-subtab-head">⏰ Restore reminders<span class="hint">${hintBits.join(" · ")}</span></div>
      <div class="dlv-fold-body">
        <label class="dlv-field-label" for="dlv-rem-date">Date the domain was rested/restored <span class="dlv-field-hint">(due date = +14 days)</span></label>
        <div class="dlv-rem-add">
          <input class="dlv-input" type="text" id="dlv-rem-doms" placeholder="domains — e.g. getnavreogrowth.org, arnicbiz.biz" data-act="rem-doms-input">
          <input class="dlv-input" style="width:auto" type="date" id="dlv-rem-date" value="${todayISO()}" data-act="rem-date-input">
          <button class="btn primary" data-act="rem-add">+ Add 14-day reminder</button>
        </div>
        <div class="dlv-rem-err" id="dlv-rem-err">Type at least one domain first</div>
        <div class="dlv-mb-count" id="dlv-rem-hint" style="margin:-6px 0 14px">Will be due ${esc(addDays(todayISO(), 14))}</div>
        ${list}
      </div>
    </div>`;
  }

  /* ============================================================
     18. Recent actions
     ============================================================ */
  function renderHistoryRow(h) {
    const map = {
      reenable: () => `⚡ ${h.date} — Re-enabled warmup — <b>${h.count}</b> mailbox(es)${h.failed ? " · " + h.failed + " failed" : ""}${h.scope ? " · " + h.scope : ""}`,
      reconnect: () => `🔌 ${h.date} — Reconnected — queued <b>${h.count}</b> mailbox(es)`,
      // Item 5b: domain-health rotation pauses only — blacklist pauses now log
      // as their own `blacklist_pause` action below so the two never read the
      // same in the log (a rotation pause and "I paused the blacklisted
      // domain I was just looking at" are different situations to a reader
      // scanning Recent actions).
      warmup_pause: () => (h.domains === 1 && h.scope && h.scope !== "bulk flagged")
        ? `🌙 ${h.date} — Moved ${esc(h.scope)} to warm-up — <b>${h.mailboxes}</b> mailbox(es)`
        : `🌙 ${h.date} — Moved to warm-up — <b>${h.mailboxes}</b> mailbox(es) across ${h.domains} domain(s)${h.scope ? " · " + h.scope : ""}`,
      blacklist_pause: () => (h.domains === 1 && h.scope && h.scope !== "blacklist")
        ? `⏸ ${h.date} — Paused blacklisted domain ${esc(h.scope)} — <b>${h.mailboxes}</b> mailbox(es)`
        : `⏸ ${h.date} — Paused ${h.domains} blacklisted domain(s) — <b>${h.mailboxes}</b> mailbox(es)`,
      warmup_resume: () => `☀️ ${h.date} — Reactivated — restored <b>${h.mailboxes}</b> mailbox(es)`,
      notion_sync: () => `🗂 ${h.date} — Synced to Notion — <b>${h.count}</b> domain(s) (${h.scope || "changed"})`,
      signatures: () => `✍️ ${h.date} — Applied signatures — <b>${h.count}</b> mailbox(es)${h.failed ? " · " + h.failed + " failed" : ""}${h.scope ? " · " + h.scope : ""}`,
      process_new: () => `🏷 ${h.date} — Processed new mailboxes — <b>${h.count}</b> mailbox(es)${h.scope ? " · " + h.scope : ""}`,
      reply_caps: () => `⚙ ${h.date} — Set caps by reply rate — <b>${h.count}</b> mailbox(es)`,
      slack_post: () => `📤 ${h.date} — Posted the deliverability summary to #team-hangout`,
      reminder_add: () => `⏰ ${h.date} — Added restore reminder — <b>${h.count}</b> domain(s)${h.scope ? " · " + esc(h.scope) : ""}`,
      reminder_done: () => `✓ ${h.date} — Reminder marked added back${h.scope ? " · " + esc(h.scope) : ""}`,
      reminder_undo: () => `↩ ${h.date} — Reminder restored to pending${h.scope ? " · " + esc(h.scope) : ""}`,
      reminder_removed: () => `🗑 ${h.date} — Removed restore reminder${h.scope ? " · " + esc(h.scope) : ""}`,
      delist_submitted: () => `📋 ${h.date} — Marked <b>${esc(h.scope || "")}</b> as submitted for delisting`,
      delist_undo: () => `↩ ${h.date} — Unmarked <b>${esc(h.scope || "")}</b> as submitted`,
      hypertide_draft: () => `✉️ ${h.date} — Drafted the Hypertide escalation email`,
      // Item 1: five action types that previously wrote NO history row at all
      // (or wrote to a different store) — the biggest contributor to
      // "did 5+ actions and the log stayed empty".
      mark_done: () => `✓ ${h.date} — Marked to-do done · ${esc(h.scope || h.key || "")}`,
      mark_undone: () => `↩ ${h.date} — Un-marked to-do · ${esc(h.scope || h.key || "")}`,
      csv_download: () => `⬇ ${h.date} — Downloaded <b>${esc(h.scope || "CSV")}</b>${h.count != null ? " · " + h.count + " row(s)" : ""}`,
      view_data: () => `👁 ${h.date} — Viewed <b>${esc(h.scope || "dataset")}</b>${h.count != null ? " · " + h.count + " row(s)" : ""}`,
      copy: () => `⧉ ${h.date} — Copied ${esc(h.scope || "text")}`,
      verify_run: () => `🔍 ${h.date} — Verified <b>${esc(h.scope || "")}</b> — ${h.count != null ? h.count + " leads checked · " : ""}keep ${h.keep != null ? h.keep : "?"} / remove ${h.remove != null ? h.remove : "?"}`,
    };
    // Item 1: rows written by THIS session carry a `ts` (stamped by
    // logAction()); seed rows from buildMock() never do. Session rows get an
    // orange left border so they're visually distinct from the seeded
    // "earlier" block even when scrolled together.
    const sess = h.ts != null ? " dlv-hist-sess" : "";
    // A mark_done row keeps its own ↩ Undo as long as that key is still acked,
    // so the Recent-actions fold remains a working undo path (defect 3(b)).
    const undoBtn = (h.action === "mark_done" && h.key && ackOf(h.key)) ? `<button class="btn sm" data-act="unmark-done" data-key="${esc(h.key)}">↩ Undo</button>` : "";
    if (map[h.action]) return `<div class="dlv-ai note${sess}" style="border-left-color:var(--green)"><span class="dlv-ai-n note">✓</span><div class="dlv-ai-body"><div class="dlv-ai-action">${map[h.action]()}</div></div>${undoBtn}</div>`;
    if (h.action) return `<div class="dlv-ai note${sess}" style="border-left-color:var(--green)"><span class="dlv-ai-n note">✓</span><div class="dlv-ai-body"><div class="dlv-ai-action">${h.date} — ${String(h.action).replace(/_/g, " ")}${h.count != null ? " · <b>" + h.count + "</b> item(s)" : ""}</div></div></div>`;
    return `<div class="dlv-ai note${sess}" style="border-left-color:var(--green)"><span class="dlv-ai-n note">✓</span><div class="dlv-ai-body"><div class="dlv-ai-text">${h.date} — ${esc(h.name || ("campaign " + h.campaign))}</div><div class="dlv-ai-action">Removed <b>${h.removed}</b> bad lead(s)${h.guarded ? " · " + h.guarded + " reply-guarded kept" : ""} · ${h.before} → ${h.after}</div></div></div>`;
  }
  // "✅ Actioned" fold rows (renderTodo) — mark-done acks with their ↩ Undo.
  function renderAckRow(it) {
    const ac = ackOf(it.key);
    return `<div class="dlv-ai done"><span class="dlv-ai-n note">✓</span><div class="dlv-ai-body"><div class="dlv-ai-text">${esc(it.text)}</div><div class="dlv-ai-action">Marked done ${esc(ac ? ac.date : "")}${it.count != null ? " · was " + it.count : ""}</div></div><button class="btn sm" data-act="unmark-done" data-key="${it.key}">↩ Undo</button></div>`;
  }
  /* Item 1: the fold now (a) splits "today — this session" (rows with a
     logAction() ts) from "earlier" (seed/mock rows), so seeded history can
     never again read as either fake ("static demo placeholder") or as
     something the current user did; and (b) shows a live per-session count in
     the summary hint. Mark-done acks no longer get a mirrored pseudo-row here —
     markDone()/unmarkDone() write real typed history rows now instead. */
  function renderHistoryFold(D) {
    const hist = S.A.history || [];
    const sessRows = hist.filter((h) => h.ts != null).slice(0, 60);
    const earlierRows = hist.filter((h) => h.ts == null).slice(0, 25);
    let inner = `<div class="dlv-hist-glabel">Today — this session (${sessRows.length})</div>`;
    inner += sessRows.length
      ? sessRows.map(renderHistoryRow).join("")
      : `<div class="dlv-mb-count" style="padding:2px 0 4px">No actions taken this session yet — everything you do here will be logged live.</div>`;
    if (earlierRows.length) inner += `<div class="dlv-hist-glabel" style="margin-top:10px">Earlier (${earlierRows.length})</div>` + earlierRows.map(renderHistoryRow).join("");
    const hint = sessRows.length + " this session · " + earlierRows.length + " earlier — already done, don't redo";
    return `<details class="dlv-fold" id="dlv-fold-history">
      <summary>🕓 Recent actions<span class="hint">${esc(hint)}</span></summary>
      <div class="dlv-fold-body"><div class="dlv-actions-list">${inner}</div></div>
    </details>`;
  }
  /* Item 1 (root cause, part 2): actions that never call paintPage() — CSV
     downloads, copies, a verify run — still have to update an OPEN fold
     immediately. logAction() calls this after every append: it re-renders just
     the fold in place, preserving its open state. Cheap, targeted, and safe to
     run even when a full paintPage() follows a moment later. */
  function repaintHistoryFold() {
    const f = $id("dlv-fold-history");
    if (!f) return;
    const wasOpen = f.open;
    const tmp = document.createElement("div");
    tmp.innerHTML = renderHistoryFold();
    const fresh = tmp.firstElementChild;
    if (!fresh) return;
    fresh.open = wasOpen;
    f.replaceWith(fresh);
  }

  function renderFooter() {
    return `<div class="dlv-footer">Deliverability audit · demo mode — mock data</div>`;
  }

  /* ============================================================
     19. Modals + toast — persistent DOM nodes appended once to
         <body>, updated in place (never destroyed by paintPage()
         so open state / focus survive background repaints).
     ============================================================ */
  // Fix (hypothesis 3) — every modal node is a persistent child of <body>
  // (outside #main/#dlv-root, never touched by paintPage() or a repaint's
  // main.innerHTML reset) and is always re-resolved by id at open/close time,
  // never cached — so the only way this system can go dark is if the nodes
  // themselves are missing. The old guard (`if ($id("dlv-toast")) return`)
  // only ever checked ONE of the dozen ids in the template; if anything left
  // that single node in place while some other modal id was missing (or not
  // yet created on this page), every open*Modal() call below would silently
  // no-op forever with no visible error. Check every id this file opens and
  // rebuild the whole set (after clearing any partial remnant) if any is gone.
  const MODAL_IDS = [
    "dlv-toast-stack", "dlv-confirm-overlay", "dlv-hypertide-overlay", "dlv-ctx-overlay",
    "dlv-sig-overlay", "dlv-pn-overlay", "dlv-wu-overlay", "dlv-delist-overlay",
    "dlv-caps-overlay", "dlv-slack-overlay", "dlv-notion-overlay", "dlv-gloss-pop",
    "dlv-copy-fallback",
  ];
  function ensureModals() {
    if (MODAL_IDS.every($id)) return;
    MODAL_IDS.forEach((id) => { const el = $id(id); if (el) el.remove(); });
    const wrap = document.createElement("div");
    wrap.innerHTML = `
    <div class="dlv-toast-stack" id="dlv-toast-stack"></div>

    <div class="dlv-modal-overlay" id="dlv-confirm-overlay" data-act="overlay-bg" data-modal="dlv-confirm-overlay">
      <div class="dlv-modal narrow">
        <div class="dlv-modal-head"><h3 id="dlv-confirm-title">Please confirm</h3></div>
        <div class="dlv-modal-body"><div class="dlv-confirm-body" id="dlv-confirm-body"></div></div>
        <div class="dlv-modal-foot"><button class="btn" data-act="confirm-no">Cancel</button><button class="btn primary" id="dlv-confirm-yes" data-act="confirm-yes">Proceed</button></div>
      </div>
    </div>

    <div class="dlv-modal-overlay" id="dlv-hypertide-overlay" data-act="overlay-bg" data-modal="dlv-hypertide-overlay">
      <div class="dlv-modal">
        <div class="dlv-modal-head"><h3>✉️ Hypertide escalation — draft</h3><button class="x" data-act="close-modal" data-modal="dlv-hypertide-overlay">&times;</button></div>
        <div class="dlv-modal-body"><pre id="dlv-hypertide-body"></pre></div>
        <div class="dlv-modal-foot"><button class="btn" data-act="close-modal" data-modal="dlv-hypertide-overlay">Close</button><button class="btn primary" data-act="copy-hypertide">Copy email</button></div>
      </div>
    </div>

    <div class="dlv-modal-overlay" id="dlv-ctx-overlay" data-act="overlay-bg" data-modal="dlv-ctx-overlay">
      <div class="dlv-modal">
        <div class="dlv-modal-head"><h3>📋 Audit context — paste into a Claude chat</h3><button class="x" data-act="close-modal" data-modal="dlv-ctx-overlay">&times;</button></div>
        <div class="dlv-modal-body"><pre id="dlv-ctx-body"></pre></div>
        <div class="dlv-modal-foot"><button class="btn" data-act="close-modal" data-modal="dlv-ctx-overlay">Close</button><button class="btn primary" data-act="copy-ctx">📋 Copy all</button></div>
      </div>
    </div>

    <div class="dlv-modal-overlay" id="dlv-sig-overlay" data-act="overlay-bg" data-modal="dlv-sig-overlay">
      <div class="dlv-modal">
        <div class="dlv-modal-head"><h3>✍️ Apply signatures</h3><button class="x" data-act="close-modal" data-modal="dlv-sig-overlay">&times;</button></div>
        <div class="dlv-modal-body">
          <label class="dlv-field-label">Apply to <span class="dlv-field-hint">(pick a brand/batch — or explicitly choose “All brands”)</span></label>
          <select class="dlv-select" id="dlv-sig-batch" style="margin-bottom:6px" data-act="sig-batch-change"></select>
          <p class="dlv-sig-helper" id="dlv-sig-helper">Pick a brand to load its signature.</p>
          <label class="dlv-field-label" style="margin-top:6px">Signature template <span class="dlv-field-hint">— use <code>{{name}}</code> for the sender's name, replaced per mailbox with that inbox's from_name</span></label>
          <textarea class="dlv-textarea" id="dlv-sig-tpl" rows="5" data-act="sig-tpl-input" style="margin-top:6px">Best,
{{name}}</textarea>
          <div class="small muted" style="margin-top:10px">Preview (for "Jacki Arnic"):</div>
          <pre class="dlv-preview" id="dlv-sig-preview"></pre>
          <div id="dlv-sig-warn" style="display:none;font-size:12px;color:#6B4A00;background:var(--amber-bg);border:1px solid var(--amber-line);border-radius:8px;padding:8px 11px;margin:12px 0">⚠ This writes the same signature to every brand. Pick a brand above to load its own saved signature.</div>
          <p class="small muted" style="margin:12px 0 10px">Writes to <b id="dlv-sig-n">0</b> mailbox(es):</p>
          <input class="dlv-input" id="dlv-sig-search" type="text" placeholder="🔍 search inboxes… (e.g. henry)" style="margin-bottom:8px" data-act="sig-search">
          <div class="small muted" style="margin-bottom:5px">Inboxes that will be updated (<span id="dlv-sig-target-n">0</span>):</div>
          <div id="dlv-sig-targets" style="max-height:140px;overflow:auto;border:1px solid var(--line);border-radius:9px;background:var(--bg-sunken)"></div>
        </div>
        <div class="dlv-modal-foot"><span class="small muted" style="margin-right:auto;max-width:60%">Overwrites existing signatures — reversible by re-applying.</span><button class="btn" data-act="close-modal" data-modal="dlv-sig-overlay">Cancel</button><button class="btn primary" id="dlv-sig-apply-btn" data-act="sig-apply">Apply to <span id="dlv-sig-n2">0</span></button></div>
      </div>
    </div>

    <div class="dlv-modal-overlay" id="dlv-pn-overlay" data-act="overlay-bg" data-modal="dlv-pn-overlay">
      <div class="dlv-modal">
        <div class="dlv-modal-head"><h3>🏷 Process <span id="dlv-pn-n">0</span> new mailbox(es)</h3><button class="x" data-act="close-modal" data-modal="dlv-pn-overlay">&times;</button></div>
        <div class="dlv-modal-body">
          <p class="small muted" style="margin-bottom:12px">Tag the untagged ones, and/or add the ones not yet in a campaign. Leave a field blank to skip it.</p>
          <input class="dlv-input" id="dlv-pn-search" type="text" placeholder="🔍 search inboxes…" style="margin-bottom:8px" data-act="pn-search">
          <div class="small muted" style="margin-bottom:5px">These mailboxes (<span id="dlv-pn-target-n">0</span>):</div>
          <div id="dlv-pn-targets" style="max-height:140px;overflow:auto;border:1px solid var(--line);border-radius:9px;background:var(--bg-sunken);margin-bottom:14px"></div>
          <label class="dlv-field-label">Batch tag <span class="dlv-field-hint">(applied to untagged mailboxes)</span></label>
          <input class="dlv-input" id="dlv-pn-tag" type="text" placeholder="e.g. Hypertide (Odd - 2026)" style="margin-bottom:14px">
          <label class="dlv-field-label">Add to campaign <span class="dlv-field-hint">(mailboxes not yet assigned)</span></label>
          <select class="dlv-select" id="dlv-pn-camp"><option value="">— don't add —</option></select>
        </div>
        <div class="dlv-modal-foot"><span class="small muted" style="margin-right:auto;max-width:60%">Tagging &amp; campaign changes are reversible afterwards.</span><button class="btn" data-act="close-modal" data-modal="dlv-pn-overlay">Cancel</button><button class="btn primary" data-act="pn-apply">Apply</button></div>
      </div>
    </div>

    <div class="dlv-modal-overlay" id="dlv-wu-overlay" data-act="overlay-bg" data-modal="dlv-wu-overlay">
      <div class="dlv-modal">
        <div class="dlv-modal-head"><h3>⚡ Enable warmup on <span id="dlv-wu-n">0</span> mailbox(es)</h3><button class="x" data-act="close-modal" data-modal="dlv-wu-overlay">&times;</button></div>
        <div class="dlv-modal-body">
          <p class="small muted" id="dlv-wu-std" style="margin-bottom:12px"></p>
          <input class="dlv-input" id="dlv-wu-search" type="text" placeholder="🔍 search inboxes…" style="margin-bottom:8px" data-act="wu-search">
          <div class="small muted" style="margin-bottom:5px">These mailboxes (<span id="dlv-wu-target-n">0</span>):</div>
          <div id="dlv-wu-targets" style="max-height:140px;overflow:auto;border:1px solid var(--line);border-radius:9px;background:var(--bg-sunken);margin-bottom:16px"></div>
          <div style="display:flex;gap:12px;flex-wrap:wrap">
            <label style="flex:1;min-width:130px" class="dlv-field-label">Warm-up / day<input class="dlv-input" id="dlv-wu-perday" type="number" min="1" value="35" style="margin-top:6px"></label>
            <label style="flex:1;min-width:130px" class="dlv-field-label">Daily ramp-up<input class="dlv-input" id="dlv-wu-ramp" type="number" min="0" value="5" style="margin-top:6px"></label>
            <label style="flex:1;min-width:130px" class="dlv-field-label">Reply rate %<input class="dlv-input" id="dlv-wu-reply" type="number" min="0" max="100" value="38" style="margin-top:6px"></label>
          </div>
        </div>
        <div class="dlv-modal-foot"><span class="small muted" style="margin-right:auto;max-width:60%">Reversible — you can adjust or disable warmup again later.</span><button class="btn" data-act="close-modal" data-modal="dlv-wu-overlay">Cancel</button><button class="btn primary" data-act="wu-apply">Enable warmup</button></div>
      </div>
    </div>

    <div class="dlv-modal-overlay" id="dlv-delist-overlay" data-act="overlay-bg" data-modal="dlv-delist-overlay">
      <div class="dlv-modal wide">
        <div class="dlv-modal-head"><h3>📋 ${glossify("Delisting prep")}</h3><button class="x" data-act="close-modal" data-modal="dlv-delist-overlay">&times;</button></div>
        <!-- Fix #3b (holdout VA): plain expectation-setting intro — delisting is
             a manual form on each blocklist's own website, not a button here. -->
        <p class="small muted" id="dlv-dl-intro" style="padding:12px 22px 0">Delisting is a manual step on each blocklist's own website (has a CAPTCHA) — copy the prepared request text below, or hand this to your admin.</p>
        <div style="padding:12px 22px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;border-bottom:1px solid var(--line)">
          <label class="small" style="display:flex;align-items:center;gap:7px;cursor:pointer"><input type="checkbox" id="dlv-dl-all" data-act="dl-include-young"> ${glossify("Include young (replace-instead) domains")}</label>
          <button class="btn sm" data-act="dl-copy-all">⧉ Copy all domains</button>
          <span class="small muted" id="dlv-dl-count" style="margin-left:auto"></span>
        </div>
        <div class="dlv-modal-body" id="dlv-dl-body"></div>
        <div class="dlv-modal-foot"><span class="small muted" style="margin-right:auto;max-width:60%">Submitting is manual (CAPTCHA). Pause + fix the cause first, file via the links, then mark each as submitted.</span><button class="btn" data-act="close-modal" data-modal="dlv-delist-overlay">Close</button></div>
      </div>
    </div>

    <div class="dlv-modal-overlay" id="dlv-caps-overlay" data-act="overlay-bg" data-modal="dlv-caps-overlay">
      <div class="dlv-modal">
        <div class="dlv-modal-head"><h3>⚙ Caps by reply rate — preview</h3><button class="x" data-act="close-modal" data-modal="dlv-caps-overlay">&times;</button></div>
        <div class="dlv-modal-body" id="dlv-caps-body"></div>
        <div class="dlv-modal-foot"><span class="small muted" style="margin-right:auto;max-width:60%">A backup of current caps is saved first — reversible.</span><button class="btn" data-act="close-modal" data-modal="dlv-caps-overlay">Cancel</button><button class="btn primary" data-act="caps-apply">Apply</button></div>
      </div>
    </div>

    <div class="dlv-modal-overlay" id="dlv-slack-overlay" data-act="overlay-bg" data-modal="dlv-slack-overlay">
      <div class="dlv-modal">
        <div class="dlv-modal-head"><h3>📤 Send to Slack — preview</h3><button class="x" data-act="close-modal" data-modal="dlv-slack-overlay">&times;</button></div>
        <div class="dlv-modal-body"><p class="small muted" style="margin-bottom:10px">This is the exact message that will post — nothing is sent until you confirm.</p><pre id="dlv-slack-body"></pre></div>
        <div class="dlv-modal-foot"><span class="small muted" style="margin-right:auto">Mock — no network call.</span><button class="btn" data-act="close-modal" data-modal="dlv-slack-overlay">Cancel</button><button class="btn primary" data-act="slack-send">Send to #team-hangout</button></div>
      </div>
    </div>

    <div class="dlv-modal-overlay" id="dlv-notion-overlay" data-act="overlay-bg" data-modal="dlv-notion-overlay">
      <div class="dlv-modal">
        <div class="dlv-modal-head"><h3>🗂 Sync to Notion — preview</h3><button class="x" data-act="close-modal" data-modal="dlv-notion-overlay">&times;</button></div>
        <div class="dlv-modal-body"><p class="small muted" style="margin-bottom:10px">This is exactly what would be written — nothing is sent until you confirm.</p><div id="dlv-notion-body"></div></div>
        <div class="dlv-modal-foot"><span class="small muted" style="margin-right:auto">Mock — no network call.</span><button class="btn" data-act="close-modal" data-modal="dlv-notion-overlay">Cancel</button><button class="btn primary" id="dlv-notion-sync-btn" data-act="notion-sync">Sync 0 domain(s)</button></div>
      </div>
    </div>

    <div class="dlv-modal-overlay" id="dlv-view-overlay" data-act="overlay-bg" data-modal="dlv-view-overlay">
      <div class="dlv-modal wide">
        <div class="dlv-modal-head"><h3 id="dlv-view-title">View</h3><button class="x" data-act="close-modal" data-modal="dlv-view-overlay">&times;</button></div>
        <div class="dlv-modal-body"><div class="dlv-mb-count" id="dlv-view-count" style="margin-bottom:8px"></div><div class="dlv-view-scroll" id="dlv-view-body"></div></div>
        <div class="dlv-modal-foot"><span class="small muted" style="margin-right:auto">Read-only view — no file is downloaded.</span><button class="btn" data-act="close-modal" data-modal="dlv-view-overlay">Close</button></div>
      </div>
    </div>

    <div class="dlv-gloss-pop" id="dlv-gloss-pop"><span class="x" data-act="gloss-close">&times;</span><span id="dlv-gloss-pop-text"></span></div>

    <div class="dlv-copy-fallback" id="dlv-copy-fallback">
      <div class="dlv-copy-fallback-head"><span>Clipboard blocked — text selected below, press Ctrl/Cmd+C</span><span class="x" data-act="copy-fallback-close">&times;</span></div>
      <textarea id="dlv-copy-fallback-ta" readonly></textarea>
    </div>`;
    while (wrap.firstChild) document.body.appendChild(wrap.firstChild);
  }

  /* ============================================================
     20. Main paint pipeline
     ============================================================ */
  // Stage-A data-source banner: a dismissible "sample data" notice when the
  // live backend isn't configured, or a non-blocking "Running live audit…"
  // strip while a POST /run is in flight. Rendered at the very top of #dlv-root
  // (above the header) so it's the first thing the owner sees in either state.
  function renderDataBanner() {
    if (DATA.mode === "sample" && !DATA.sampleDismissed) {
      return `<div class="dlv-data-banner sample" id="dlv-data-banner">
        <span class="dlv-data-banner-txt">Showing <b>sample data</b> — the live deliverability backend isn't configured yet.` +
        glossMark("The navreo-signals server needs the DELIV_AUDIT_AUTH env var set so its /api/deliverability proxy can reach the live audit backend.") +
        `</span>
        <button class="dlv-data-banner-x" data-act="dismiss-sample-banner" title="Dismiss">&times;</button>
      </div>`;
    }
    if (isLive() && DATA.runLoading) {
      return `<div class="dlv-data-banner running" id="dlv-data-banner">
        <span class="dlv-spinner ink"></span>
        <span class="dlv-data-banner-txt">Running live audit… (~1–2 min) — the numbers below refresh automatically when it finishes.</span>
      </div>`;
    }
    if (isLive() && DATA.runError) {
      return `<div class="dlv-data-banner err" id="dlv-data-banner">
        <span class="dlv-data-banner-txt">Live audit couldn't complete (${esc(DATA.runError)}) — showing the last snapshot. Retry with ⚠ Run Live Audit.</span>
        <button class="dlv-data-banner-x" data-act="dismiss-run-error" title="Dismiss">&times;</button>
      </div>`;
    }
    return "";
  }

  function paintPage() {
    const root = $id("dlv-root");
    if (!root) return;
    closeGlossaryPopover(); // avoid an orphaned popover surviving a full repaint
    closeCopyFallback(); // same for item 2's manual-copy fallback box
    // Item 1 (root cause, part 1): paintPage() rebuilds root.innerHTML from
    // scratch, and the Recent-actions fold renders with no `open` attribute —
    // so EVERY state-changing action (each ends in paintPage()) silently
    // snapped an open fold shut. A tester who opened the log and then worked
    // through 5+ actions watched it collapse on the first one and never saw a
    // single live entry land — "the log stayed empty all session". Capture
    // every fold's actual open/closed state before the rebuild and re-apply it
    // after, so a fold the user opened (or closed) stays that way across
    // repaints — and a new history row lands VISIBLY in the already-open fold.
    const foldState = {};
    root.querySelectorAll("details.dlv-fold[id]").forEach((d) => { foldState[d.id] = d.open; });
    const D = fullDerive();
    // Sub-tab shell: Overview keeps everything except the 3 heavy sections,
    // which now render as their own always-expanded tab panel instead —
    // exactly one of the four branches below paints on any given call.
    let panel;
    if (dlvSubtab === "blacklist") panel = renderBlacklistPanel(D);
    else if (dlvSubtab === "manager") panel = renderManagerPanel(D);
    else if (dlvSubtab === "batch") panel = renderBatchPanel();
    else if (dlvSubtab === "reminders") panel = renderRemindersPanel(D);
    else panel = renderOverviewPanel(D);
    root.innerHTML = [
      renderDataBanner(),
      renderHeaderTabs(),
      renderSubtabBar(),
      panel,
      renderFooter(),
    ].join("");
    root.querySelectorAll("details.dlv-fold[id]").forEach((d) => { if (foldState[d.id] != null) d.open = foldState[d.id]; });
    paintManagerRows(); // no-ops safely (guarded on $id("dlv-mgr-body")) unless the Manager tab is active
    scheduleStubTimers(); // fix #1: (re)arm the mark-done stubs' collapse timers
  }

  // Overview = every section that stayed in the main scroll (order preserved):
  // coach, verdict, banner, health strip, fleet-by-the-numbers (incl. the
  // technical-details fold), today's to-do (incl. the Actioned fold), recent
  // actions. The 3 heavy sections + Restore reminders moved out to their own tabs.
  function renderOverviewPanel(D) {
    return [
      renderCoach(),
      renderVerdict(D),
      renderBanner(D),
      renderHealthStrip(D),
      renderFleetTiles(D),
      `<div id="dlv-todo-anchor">${renderTodo(D)}</div>`,
      renderHistoryFold(D),
    ].join("");
  }

  /* ============================================================
     21. Modal open/populate helpers
     ============================================================ */
  function inboxFilterRows(containerId, term) {
    term = String(term || "").trim().toLowerCase();
    const rows = [...document.querySelectorAll("#" + containerId + " .dlv-sig-trow")];
    let shown = 0;
    rows.forEach((r) => {
      const em = ((r.querySelector(".dlv-sig-email") || {}).textContent || "").toLowerCase();
      const vis = !term || em.includes(term);
      r.style.display = vis ? "" : "none";
      if (vis) shown++;
    });
    return { shown, total: rows.length };
  }
  function trowHtml(email, when) { return `<div class="dlv-sig-trow"><span class="dlv-sig-email">${esc(email)}</span><span class="dlv-sig-when">${esc(when)}</span></div>`; }
  function agoStr(created) {
    if (!created) return "date unknown";
    const t = new Date(created);
    if (isNaN(t)) return "date unknown";
    const ago = Math.max(0, Math.floor((Date.now() - t.getTime()) / 864e5));
    return created + " · " + ago + "d ago";
  }

  function openHypertideModal() {
    const D = fullDerive();
    $id("dlv-hypertide-body").textContent = buildHypertideEmail(D);
    openModal("dlv-hypertide-overlay");
  }
  // Fix #2: "Draft email" used to only open the modal — if that ever silently
  // failed (or a tester didn't notice the modal appear behind something), there
  // was zero OTHER evidence the click did anything. Now every click also drops
  // a toast and a Recent-actions entry, so there's confirmation even if the
  // modal itself goes unnoticed, and per fix #3 this also lets "Mark done" on
  // the blocked-real to-do card know the suggested action was actually run.
  function onDraftEmailClick() {
    openHypertideModal();
    logAction({ action: "hypertide_draft", count: 1 });
    saveState();
    // Item 2: repaint so the to-do card picks up its "✉️ drafted" chip (the
    // modal is a persistent node outside #dlv-root, unaffected by the repaint).
    paintPage();
    toast("Escalation email drafted — copy it from this window", "ok");
  }
  function openCtxModal() {
    const D = fullDerive();
    $id("dlv-ctx-body").textContent = buildContext(D);
    openModal("dlv-ctx-overlay");
  }

  function brandKeyOf(b) { b = String(b || "").toLowerCase(); if (/arnic/.test(b)) return "arnic"; if (/amplify/.test(b)) return "amplifyy"; if (/navreo|thunderbird|hypertide|sender/.test(b)) return "navreo"; return null; }
  function savedTplFor(batch) {
    const tpls = S.A.sigTemplates || {};
    if (tpls[batch] != null) return tpls[batch];
    const k = brandKeyOf(batch);
    if (k && tpls[k] != null) return tpls[k];
    return tpls._all;
  }
  function sigRows() { return [].concat(S.A.signature.missing, S.A.signature.mismatch); }
  // Part B3: sentinels for the two non-brand select states. SIG_PICK is the
  // default on open (nothing chosen yet → Apply disabled, helper shown);
  // SIG_ALL is the EXPLICIT opt-in to write every brand (the old risky
  // default). A real brand value is anything else.
  const SIG_PICK = "__pick", SIG_ALL = "__all";
  function openSigFixModal() {
    UI.sig.batch = SIG_PICK; UI.sig.search = "";
    const rows = sigRows();
    const counts = groupCount(rows, (r) => r.batch || "(no batch)");
    const total = rows.length;
    const sel = $id("dlv-sig-batch");
    // Default selection is the non-committal placeholder, NOT "All brands".
    sel.innerHTML = `<option value="${SIG_PICK}" selected>— Pick a brand —</option>`
      + Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([b, c]) => `<option value="${esc(b)}">${esc(b)} · ${c}</option>`).join("")
      + `<option value="${SIG_ALL}">All brands · ${total} mailbox(es)</option>`;
    $id("dlv-sig-search").value = "";
    sigOnBatchChange();
    openModal("dlv-sig-overlay");
  }
  function sigOnBatchChange() {
    const raw = $id("dlv-sig-batch").value;
    UI.sig.batch = raw;
    const isPick = raw === SIG_PICK;
    const isAll = raw === SIG_ALL;
    const v = (isPick || isAll) ? "" : raw; // effective brand filter ("" = every row)
    const rows = sigRows();
    const sub = isPick ? [] : (v ? rows.filter((r) => (r.batch || "(no batch)") === v) : rows);
    $id("dlv-sig-n").textContent = sub.length; $id("dlv-sig-n2").textContent = sub.length; $id("dlv-sig-target-n").textContent = sub.length;
    // Apply is disabled until a real choice (a brand, or explicit All) is made.
    const applyBtn = $id("dlv-sig-apply-btn");
    if (applyBtn) applyBtn.disabled = isPick;
    const helper = $id("dlv-sig-helper");
    if (helper) helper.classList.toggle("show", isPick);
    if (!isPick) {
      const saved = savedTplFor(v);
      const ta = $id("dlv-sig-tpl");
      if (saved) ta.value = saved;
    }
    // The "writes to every brand" warning shows ONLY for the explicit All opt-in.
    $id("dlv-sig-warn").style.display = isAll ? "block" : "none";
    const sorted = [...sub].sort((a, b) => new Date(b.created || 0) - new Date(a.created || 0));
    $id("dlv-sig-targets").innerHTML = sorted.length ? sorted.map((r) => trowHtml(r.email, agoStr(r.created))).join("") : `<div class="dlv-mb-count" style="padding:8px 12px">${isPick ? "Pick a brand to see its inboxes" : "No inboxes"}</div>`;
    sigUpdatePreview();
  }
  function sigUpdatePreview() {
    const ta = $id("dlv-sig-tpl");
    $id("dlv-sig-preview").textContent = ta.value.replace(/\{\{\s*name\s*\}\}/gi, "Jacki Arnic");
  }
  async function sigApply() {
    // The modal's own Apply button IS the commitment point — no second stacked
    // confirm. The consequence/reversibility line lives in the modal footer
    // instead (fix: testers had to click through two dialogs to do one thing).
    // Part B3: block the still-un-chosen placeholder outright (Apply is also
    // disabled in the UI, but guard here too). SIG_ALL maps to the "" = every
    // brand path; a real brand value scopes to that brand.
    if (UI.sig.batch === SIG_PICK) { toast("Pick a brand to load its signature first", "err"); return; }
    const tpl = $id("dlv-sig-tpl").value;
    if (!tpl.trim()) { toast("Enter a signature first", "err"); return; }
    const batch = UI.sig.batch === SIG_ALL ? "" : UI.sig.batch;
    const n = batch ? sigRows().filter((r) => (r.batch || "(no batch)") === batch).length : sigRows().length;
    if (!n) { toast("No mailboxes to update", "err"); return; }
    if (batch) {
      S.A.signature.missing = S.A.signature.missing.filter((r) => (r.batch || "(no batch)") !== batch);
      S.A.signature.mismatch = S.A.signature.mismatch.filter((r) => (r.batch || "(no batch)") !== batch);
    } else {
      S.A.signature.missing = [];
      S.A.signature.mismatch = [];
    }
    if (batch) S.A.sigTemplates[batch] = tpl; else S.A.sigTemplates._all = tpl;
    logAction({action: "signatures", count: n, failed: 0, scope: batch || "all brands" });
    saveState();
    closeModal("dlv-sig-overlay");
    toast("Signatures applied to " + n + " mailbox(es)" + (batch ? " in " + batch : ""), "ok");
    paintPage();
  }

  function openProcessNewModal() {
    UI.pn.search = "";
    const rows = S.A.lifecycle.newUnprocessed.length ? S.A.lifecycle.newUnprocessed : S.A.lifecycle.untagged;
    $id("dlv-pn-n").textContent = rows.length;
    $id("dlv-pn-target-n").textContent = rows.length;
    $id("dlv-pn-tag").value = "";
    $id("dlv-pn-search").value = "";
    const sorted = [...rows].sort((a, b) => new Date(b.created || 0) - new Date(a.created || 0));
    $id("dlv-pn-targets").innerHTML = sorted.length ? sorted.map((r) => {
      const flags = []; if (!r.tagged) flags.push("untagged"); if (r.inCampaign === false) flags.push("no campaign");
      return trowHtml(r.email, agoStr(r.created) + (flags.length ? " · " + flags.join(" · ") : ""));
    }).join("") : `<div class="dlv-mb-count" style="padding:8px 12px">No mailboxes</div>`;
    const sel = $id("dlv-pn-camp");
    sel.innerHTML = `<option value="">— don't add —</option>` + S.campaigns.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
    openModal("dlv-pn-overlay");
  }
  async function pnApply() {
    // Single-confirm flow: Apply below is the commitment point (see sigApply).
    const tag = $id("dlv-pn-tag").value.trim();
    const camp = $id("dlv-pn-camp").value;
    if (!tag && !camp) { toast("Enter a tag or pick a campaign", "err"); return; }
    const rows = S.A.lifecycle.newUnprocessed;
    const tagged = tag ? rows.filter((r) => !r.tagged).length : 0;
    const added = camp ? rows.filter((r) => r.inCampaign === false).length : 0;
    if (tag) rows.forEach((r) => { if (!r.tagged) { r.tagged = true; r.tags = [tag]; } });
    if (camp) rows.forEach((r) => { r.inCampaign = true; });
    S.A.lifecycle.newUnprocessed = rows.filter((r) => !(r.tagged && r.inCampaign));
    logAction({action: "process_new", count: tagged + added, scope: (tag ? "tagged " + tagged : "") + (tag && camp ? " · " : "") + (camp ? "added " + added : "") });
    saveState();
    closeModal("dlv-pn-overlay");
    toast("Tagged " + tagged + " · added " + added + " to campaign", "ok");
    paintPage();
  }

  function openWarmupFixModal() {
    UI.wu.search = "";
    const rows = S.A.warmupConfig.notWarming || [];
    $id("dlv-wu-n").textContent = rows.length;
    $id("dlv-wu-target-n").textContent = rows.length;
    $id("dlv-wu-search").value = "";
    const sorted = [...rows].sort((a, b) => new Date(b.created || 0) - new Date(a.created || 0));
    $id("dlv-wu-targets").innerHTML = sorted.length ? sorted.map((r) => trowHtml(r.email, agoStr(r.created) + " · warmup off")).join("") : `<div class="dlv-mb-count" style="padding:8px 12px">No mailboxes</div>`;
    const std = S.A.warmupConfig.standard || "";
    if (std) { const p = std.split("/"); if (p[0]) $id("dlv-wu-reply").value = p[0]; if (p[1]) $id("dlv-wu-perday").value = p[1]; $id("dlv-wu-std").textContent = "Your fleet's most common setting is " + p[0] + "% reply · " + p[1] + " warm-up/day (pre-filled below)."; }
    else $id("dlv-wu-std").textContent = "No fleet standard detected — using the Navreo default (35/day · 5 ramp-up · 38% reply).";
    openModal("dlv-wu-overlay");
  }
  async function wuApply() {
    // Single-confirm flow: Apply below is the commitment point (see sigApply).
    const perDay = $id("dlv-wu-perday").value || 35, ramp = $id("dlv-wu-ramp").value || 5, reply = $id("dlv-wu-reply").value || 38;
    const rows = S.A.warmupConfig.notWarming;
    const n = rows.length;
    if (!n) { toast("Nothing to enable", "err"); return; }
    rows.forEach((r) => {
      const inv = S.A.inboxRows.find((x) => x.email === r.email);
      if (inv) { inv.kind = "ok"; inv.warmup_status = "ACTIVE"; inv.cap = Number(perDay); }
    });
    S.A.warmupConfig.notWarming = [];
    logAction({action: "reenable", count: n, failed: 0, scope: perDay + "/day · " + ramp + " ramp · " + reply + "% reply" });
    saveState();
    closeModal("dlv-wu-overlay");
    toast("Warmup enabled on " + n + " mailbox(es)", "ok");
    paintPage();
  }

  function delistBlurb(d, lists) {
    return "Domain: " + d + "\nThis domain was listed on " + lists + ". We have paused all sending from it, identified and corrected the underlying cause (list hygiene + sending-domain authentication), and are requesting removal. Please re-evaluate. Thank you.";
  }
  function delistVisibleRows() {
    let rows = S.A.blacklistRows;
    if (!UI.delist.includeYoung) rows = rows.filter((r) => !/^replace/i.test(r.advice || ""));
    return rows;
  }
  function renderDelistBody() {
    const submitted = new Set((S.A.delisting || []).map((x) => x.domain));
    const rows = delistVisibleRows();
    $id("dlv-dl-count").textContent = rows.length + " domain(s)" + (rows.filter((r) => submitted.has(r.domain)).length ? " · " + rows.filter((r) => submitted.has(r.domain)).length + " submitted" : "");
    $id("dlv-dl-body").innerHTML = rows.length ? rows.map((r) => {
      const done = submitted.has(r.domain);
      const mx = r.url ? `<a class="dlv-dl" href="${esc(r.url)}" target="_blank" rel="noopener">Check ↗</a>` : "";
      const sp = /spamhaus/i.test(r.lists) ? `<a class="dlv-dl" href="https://check.spamhaus.org/" target="_blank" rel="noopener">Spamhaus ↗</a>` : "";
      const su = /surbl/i.test(r.lists) ? `<a class="dlv-dl" href="https://www.surbl.org/lookup" target="_blank" rel="noopener">SURBL ↗</a>` : "";
      return `<div class="dlv-dl-row ${done ? "done" : ""}">
        <div class="dlv-dl-main">
          <div class="dlv-dl-dom">${esc(r.domain)}${done ? '<span class="dlv-dl-tag">✓ submitted</span>' : ""}</div>
          <div class="dlv-dl-meta">${glossify(r.lists)} · <span>${glossify(r.advice || "")}</span>${r.batch ? " · " + esc(r.batch) : ""}</div>
          <div class="dlv-dl-links">${mx}${sp}${su}</div>
        </div>
        <div class="dlv-dl-acts">
          <button class="btn sm" data-act="dl-copy-req" data-domain="${esc(r.domain)}">⧉ Copy request</button>
          <button class="btn sm ${done ? "" : "primary"}" data-act="dl-toggle" data-domain="${esc(r.domain)}" data-done="${done ? "1" : "0"}">${done ? "↩ Undo" : "Mark submitted"}</button>
        </div>
      </div>`;
    }).join("") : `<div class="dlv-mb-count" style="padding:18px 0">Nothing to delist in this view.</div>`;
  }
  function openDelistingModal() { $id("dlv-dl-all").checked = UI.delist.includeYoung; renderDelistBody(); openModal("dlv-delist-overlay"); }

  /* ============================================================
     22. Caps by reply rate — preview → apply
     ============================================================ */
  function capsCandidates() {
    const { minSent } = dhCutoffMin();
    const tiers = { 1: [], 2: [], 4: [] };
    const D = fullDerive();
    D.dhRows.forEach((d) => {
      if (d.maildoso || d.sent < minSent || (D.resting[d.domain] || 0) > 0) return;
      let tier = null;
      if (d.reply_rate >= 0.8 && d.reply_rate < 1.0) tier = 1;
      else if (d.reply_rate >= 1.0 && d.reply_rate < 1.2) tier = 2;
      else if (d.reply_rate >= 1.2) tier = 4;
      if (!tier) return;
      const mbx = S.A.inboxRows.filter((r) => r.domain === d.domain && /outlook|azure/i.test(r.provider) && r.cap !== tier);
      mbx.forEach((r) => tiers[tier].push(r));
    });
    return tiers;
  }
  function openCapsPreviewModal() {
    const tiers = capsCandidates();
    const total = tiers[1].length + tiers[2].length + tiers[4].length;
    const domains = new Set([].concat(tiers[1], tiers[2], tiers[4]).map((r) => r.domain)).size;
    $id("dlv-caps-body").innerHTML = total ? `
      <p class="small muted" style="margin-bottom:10px">Set daily send caps by reply rate — OUTLOOK/AZURE mailboxes only (Maildoso excluded):</p>
      <div class="small" style="margin-bottom:10px">0.8–1.0% reply → 1/day &nbsp;·&nbsp; 1.0–1.2% → 2/day &nbsp;·&nbsp; ≥1.2% → 4/day</div>
      <div class="small" style="margin-bottom:10px"><b>${domains}</b> domain(s) qualify · <b>${total}</b> mailbox(es) will change</div>
      <div class="small muted">→ 1/day: ${tiers[1].length} mbx · 2/day: ${tiers[2].length} mbx · 4/day: ${tiers[4].length} mbx</div>
      <div class="small muted" style="margin-top:10px">Resting and below-0.8% domains are left alone. A backup is saved.</div>` : `<div class="dlv-empty">Nothing to change — Outlook/Azure caps already match their reply-rate tier.</div>`;
    $id("dlv-caps-overlay").querySelector('[data-act="caps-apply"]').disabled = !total;
    openModal("dlv-caps-overlay");
  }
  async function capsApply() {
    // Single-confirm flow: Apply below is the commitment point (see sigApply).
    const tiers = capsCandidates();
    const total = tiers[1].length + tiers[2].length + tiers[4].length;
    if (!total) { toast("Nothing to change", "err"); return; }
    let changed = 0;
    [1, 2, 4].forEach((tier) => tiers[tier].forEach((r) => { r.cap = tier; changed++; }));
    logAction({action: "reply_caps", count: changed });
    saveState();
    closeModal("dlv-caps-overlay");
    toast("Set caps on " + changed + " Outlook/Azure mailbox(es)", "ok");
    paintPage();
  }

  /* ============================================================
     23. Verify pipeline — per-campaign simulate → keep/remove
     ============================================================ */
  const _verifyState = {}; // campId -> last verify result (legacy in-memory mirror; source of truth is S.ui.verifyResults)
  // Part A2 (regression fix): the keep/bad results box used to be written
  // straight into the (empty-on-every-repaint) #dlv-vr-<id> div and held ONLY
  // in the in-memory _verifyState — so ANY unrelated action's paintPage()
  // (e.g. undoing another to-do) wiped it. Results now live in
  // S.ui.verifyResults[id] and are re-rendered from state on every paint (see
  // renderVerifyCampRow), so they survive until the user removes-bad or
  // dismisses them.
  function verifyResults() { if (!S.ui) S.ui = {}; if (!S.ui.verifyResults) S.ui.verifyResults = {}; return S.ui.verifyResults; }
  function renderVerifyResultBox(id, v) {
    if (!v) return "";
    if (v.removedSummary) {
      const r = v.removedSummary;
      return `<div class="dlv-vbox">
        <div class="dlv-vrow dlv-vremove">✅ Removed <b>${r.removed}</b> · reply-guarded (kept) ${r.guarded} · total ${r.before} → ${r.after} · backup saved</div>
        <div class="dlv-vrow"><a class="dlv-dl" data-act="verify-dismiss" data-id="${esc(id)}">✕ dismiss</a></div>
      </div>`;
    }
    return `<div class="dlv-vbox">
      <div class="dlv-vrow"><b>${v.total}</b> leads &nbsp;·&nbsp; ${v.layer1Tool} good <b>${v.l1_keep}</b> &nbsp;·&nbsp; catch-all <b>${v.l1_catch}</b> (${v.layer2Tool} kept ${v.l2_keep} / dropped ${v.l2_drop}) &nbsp;·&nbsp; ${v.layer1Tool} bad <b>${v.l1_drop}</b></div>
      <div class="dlv-plain">Catch-all: domain accepts any address — risky to email, so a second tool double-checks it.</div>
      <div class="dlv-vrow dlv-vkeep">✅ Keep (deliverable): <b>${v.keep}</b> &nbsp; <a class="dlv-dl" data-act="verify-view" data-id="${esc(id)}" data-kind="keep">👁 View kept (${v.keep})</a></div>
      <div class="dlv-vrow dlv-vremove">🗑 Bad (confirmed invalid): <b>${v.remove}</b> &nbsp; <a class="dlv-dl" data-act="verify-view" data-id="${esc(id)}" data-kind="remove">👁 View bad (${v.remove})</a></div>
      <div class="dlv-vrow"><button class="btn sm danger" data-act="remove-bad" data-id="${esc(id)}" data-count="${v.remove}">🗑 Remove bad — no-reply only (${v.remove} flagged, replies auto-kept)</button> &nbsp; <a class="dlv-dl" data-act="verify-dismiss" data-id="${esc(id)}">✕ dismiss</a></div>
      <div class="dlv-plain">Reply-guard: anyone who replied is automatically kept, never deleted.</div>
    </div>`;
  }
  async function verifyCampaignAction(id, mode, btn) {
    const done = btn.dataset.done;
    const camp = S.A.campaignsFlagged.find((c) => String(c.id) === String(id));
    const estTotal = camp ? Math.max(40, Math.round(camp.sent * 0.62)) : 500;
    const flowName = mode === "listmint" ? "ListMint" : "MillionVerifier → ListMint";
    // Every run — ListMint or MV→ListMint — gets a styled confirm before it
    // fires (fix #5): testers were surprised a "✓ ListMint" click started
    // pulling leads immediately with no heads-up that it's read-only. The
    // already-actioned warning (when present) is folded into the same dialog
    // rather than stacked as a second confirm.
    let msg = "Runs a mock verification of this campaign's ~" + estTotal + " leads via " + flowName + " — read-only, nothing is removed until you choose.\n\nProceed?";
    if (done) msg = "This campaign was already verified + cleaned on " + done + ". Re-running costs credits and shouldn't usually be needed.\n\n" + msg;
    const ok = await dlvConfirm(msg, { title: "Verify campaign" });
    if (!ok) return;
    const grp = btn.closest(".dlv-vbtns");
    const btns = grp ? grp.querySelectorAll("button") : [btn];
    btns.forEach((b) => (b.disabled = true));
    const orig = btn.innerHTML;
    btn.innerHTML = '<span class="dlv-spinner"></span> Verifying…';
    const out = $id("dlv-vr-" + id);
    const flow = mode === "listmint" ? "ListMint (general + catch-all)" : "MillionVerifier → ListMint (catch-alls)";
    if (out) out.innerHTML = `<div class="dlv-vrun">Pulling leads → ${flow}… simulating.</div>`;
    await new Promise((r) => setTimeout(r, 1500));
    const v = simulateVerify(id, mode);
    _verifyState[id] = v;
    verifyResults()[id] = v; // Part A2: persist so the box survives repaints
    // Item 1: the verify run itself now leaves a typed history row (removal
    // already did). NOTE: deliberately no `campaign` field — derive()'s
    // cleanedCampaignIds treats `h.campaign != null` as "cleaned", and a
    // read-only verify must not mark the campaign clean.
    logAction({ action: "verify_run", count: v.total, keep: v.keep, remove: v.remove, scope: (camp ? camp.name : "campaign " + id) + " · " + flowName });
    saveState();
    if (out) out.innerHTML = renderVerifyResultBox(id, v);
    toast("Verified " + v.total + " (" + v.layer1Tool + "→" + v.layer2Tool + ") — keep " + v.keep + ", remove " + v.remove, "ok");
    btns.forEach((b) => (b.disabled = false));
    btn.innerHTML = orig;
  }
  async function removeBadAction(id, btn) {
    const count = Number(btn.dataset.count || 0);
    const ok = await dlvConfirm("Delete " + count + " bad leads from this campaign?\n\n• A full backup is saved first (recoverable)\n• Any lead that replied is auto-kept (reply-guard)\n\nProceed?", { title: "Remove bad leads", danger: true, yesLabel: "Delete " + count });
    if (!ok) return;
    btn.disabled = true; const orig = btn.innerHTML; btn.innerHTML = '<span class="dlv-spinner"></span> Removing…';
    await new Promise((r) => setTimeout(r, 700));
    const camp = S.A.campaignsFlagged.find((c) => String(c.id) === String(id));
    const guarded = Math.max(1, Math.round(count * 0.03));
    const removed = count - guarded > 0 ? count - guarded : count;
    const before = camp ? camp.sent : 0;
    const after = Math.max(0, before - removed);
    if (camp) camp.sent = after;
    logAction({campaign: id, name: camp ? camp.name : ("campaign " + id), removed, guarded, before, after, total: count });
    // Part A2: replace the persisted result with a "removed" summary so the box
    // still shows (and survives repaints) after the bad leads are gone.
    verifyResults()[id] = { removedSummary: { removed, guarded, before, after } };
    delete _verifyState[id];
    saveState();
    toast("Removed " + removed + " · kept " + guarded + " replied", "ok");
    paintPage();
  }

  /* ============================================================
     24. Mark done / undo
     ============================================================ */
  // Fix #1 (holdout VA): "item just disappeared, no toast, hunted for the
  // undo". Path audit: BOTH mark-done flows (action-ran → no nudge, and
  // not-ran → "mark done anyway?" nudge) converge on this ONE markDone() —
  // onMarkDoneClick() is the only caller and the mark-done button is the only
  // dispatcher — so the undo toast below provably fires on every path. But a
  // toast is still missable (glance away for 10s and it's gone), so mark-done
  // ALSO leaves an in-place trace: a temporary inline stub rendered in the
  // exact slot the card occupied, with its own working ↩ Undo and a link that
  // scrolls to + opens the ✅ Actioned fold. The stub collapses smoothly after
  // ~12s. Transient by design (in-memory only, never persisted): it's a
  // "what just happened" cue, not state — after a reload the durable records
  // (✅ Actioned fold + Recent-actions row, both with Undo) take over.
  const STUB_MS = 12000;
  const _doneStubs = Object.create(null); // key -> expiry epoch-ms
  let _stubTimers = [];
  function clearDoneStubs() { Object.keys(_doneStubs).forEach((k) => { delete _doneStubs[k]; }); }
  // (Re)arm one collapse timer per live stub. Called at the end of every
  // paintPage() — repaints rebuild the DOM, so timers always re-resolve the
  // node by id at fire time instead of closing over a dead element.
  function scheduleStubTimers() {
    _stubTimers.forEach(clearTimeout);
    _stubTimers = [];
    const now = Date.now();
    Object.keys(_doneStubs).forEach((key) => {
      const left = _doneStubs[key] - now;
      if (left <= 0) { delete _doneStubs[key]; return; }
      _stubTimers.push(setTimeout(() => {
        delete _doneStubs[key];
        const el = $id("dlv-stub-" + key);
        if (!el) return;
        el.classList.add("dlv-stub-out"); // CSS max-height/opacity collapse
        setTimeout(() => el.remove(), 450);
      }, left));
    });
  }
  function renderDoneStub(it) {
    return `<div class="dlv-done-stub" id="dlv-stub-${esc(it.key)}">✓ Marked done — <a data-act="unmark-done" data-key="${esc(it.key)}">↩ Undo</a> · it's now in <a data-act="scroll-actioned">✅ Actioned ↓</a><span class="dlv-stub-what">${esc(it.short || it.text)}</span></div>`;
  }
  function markDone(key, count) {
    S.A.acks = (S.A.acks || []).filter((x) => x && typeof x === "object" && x.key !== key);
    S.A.acks.unshift({ key, count: Number(count) || 0, date: todayISO(), ts: Date.now() });
    // Item 1: mark-done used to live ONLY in S.A.acks — the Recent-actions
    // fold (which renders S.A.history) never saw it, so a tester whose 5
    // actions were mostly mark-dones saw an empty log. Now it's a real typed
    // history row too, carrying `key` so the row keeps a working ↩ Undo.
    logAction({ action: "mark_done", key, count: Number(count) || 0, scope: todoLabelOf(key) });
    _doneStubs[key] = Date.now() + STUB_MS; // fix #1: in-place stub, see above
    saveState();
    paintPage();
    toast("Marked done", "ok", { undoKey: key });
  }
  // Short human label for a to-do key, for history rows — falls back to the key.
  function todoLabelOf(key) {
    try {
      const it = (recomputeTodos(derive()).raw || []).find((x) => x.key === key);
      return (it && (it.short || it.text)) || String(key || "");
    } catch (e) { return String(key || ""); }
  }
  // Fix #3: maps each to-do key to a test for "did the user actually run this
  // key's suggested action" — read against S.A.history. Every seed/mock history
  // row is dated before today (S.A.date), and every action taken IN this
  // session unshifts its own row dated todayISO(), so a same-day match reliably
  // means "ran this session" without needing separate session-only tracking.
  // Deliberately keyed off the SAME history rows the "Recent actions" fold
  // already renders, per the task's own hint, rather than adding new state.
  const TODO_ACTION_MATCH = {
    // Item 5b: blacklist pauses now log their own distinct `blacklist_pause`
    // action (see logAction call sites in pauseBlacklisted()/
    // pauseBlacklistDomain() and the renderHistoryRow map above), so this no
    // longer needs to heuristically guess "was this domain in the blacklist
    // fold" off a shared `warmup_pause` action.
    blacklist: (h) => h.action === "blacklist_pause",
    "blocked-real": (h) => h.action === "hypertide_draft",
    "verify-campaigns": (h) => h.campaign != null || h.action === "verify_run", // removeBadAction() rows carry `.campaign`; a verify run alone also counts as "did the work"
    signatures: (h) => h.action === "signatures",
    "new-unprocessed": (h) => h.action === "process_new",
    "warmup-notwarming": (h) => h.action === "reenable",
    "sending-deviation": (h) => h.action === "reply_caps",
    "reminder-due": (h) => h.action === "reminder_done",
    "warmup-rotation": (h) => h.action === "warmup_pause",
    // "retired-domains" has no in-app action (its instruction is "remove these
    // in Smartlead", entirely outside this tool) — no history signal is
    // possible for it, so it's intentionally absent here and always nudges.
  };
  function actionRanToday(key) {
    const test = TODO_ACTION_MATCH[key];
    if (!test) return false;
    const today = todayISO();
    // `h && typeof h === "object"` guards every TODO_ACTION_MATCH test above,
    // each of which dereferences `.action`/`.scope`/`.campaign` unconditionally
    // — normalizeState() already keeps non-object rows out of S.A.history, but
    // this is a second, cheap line of defense so a single bad row can never
    // turn "mark done" into a permanent, session-wide dead click.
    return (S.A.history || []).some((h) => h && typeof h === "object" && h.date === today && test(h));
  }
  // "Mark done" on an item that still has a live count > 0 and a suggested
  // action means the underlying problem wasn't actually fixed this session —
  // confirm before dismissing it, so it doesn't silently vanish from the list.
  // Items that already auto-resolved to 0 (or are pure notes with no action)
  // skip the confirm since there's nothing dishonest about marking them done —
  // and so does an item whose suggested action DID run today (fix #3): e.g.
  // verifying + cleaning one of three flagged campaigns leaves the count > 0
  // (two campaigns remain), but the user demonstrably did the work, so nagging
  // them anyway was the actual bug testers hit.
  async function onMarkDoneClick(key, countAttr) {
    const D = fullDerive();
    const item = (D.rawTodo || []).find((it) => it.key === key);
    const liveCount = item ? Number(item.count) || 0 : Number(countAttr) || 0;
    const hasAction = !!(item && item.action);
    if (hasAction && liveCount > 0 && !actionRanToday(key)) {
      const ok = await dlvConfirm("You haven't run the suggested action for this item — mark it done anyway? It will reappear if the problem grows.", { title: "Mark done anyway?" });
      if (!ok) return;
    }
    markDone(key, liveCount);
  }
  function unmarkDone(key) {
    delete _doneStubs[key]; // fix #1: undoing removes the "marked done" stub too
    // No-op guard: the same undo can be reachable from several places (toast,
    // Actioned fold, history row, inline stub) — only log/repaint when
    // something changed.
    const before = (S.A.acks || []).length;
    S.A.acks = (S.A.acks || []).filter((x) => x && typeof x === "object" && x.key !== key);
    if (S.A.acks.length === before) return;
    logAction({ action: "mark_undone", key, scope: todoLabelOf(key) });
    saveState();
    paintPage();
    // Fix #4: this had no toast at all — clicking "↩ Undo" in the Actioned
    // fold (a separate button from the toast's own inline Undo) gave no
    // confirmation beyond the item quietly reappearing further up the page.
    toast("Undone — back on today's list", "ok");
  }

  /* ============================================================
     25. Blacklist pause / reactivate
     ============================================================ */
  async function pauseBlacklisted(btn) {
    const rows = S.A.blacklistRows.filter((r) => !(r.rested > 0));
    if (!rows.length) { toast("Nothing to pause — all already resting", "err"); return; }
    const mbx = rows.reduce((s, r) => s + r.mailboxes, 0);
    const ok = await dlvConfirm("Pause sending on " + mbx + " mailbox(es) across " + rows.length + " blacklisted domain(s)?\n\nSets their daily cap to 0 and rests them for 7 days while you fix the underlying cause.\n\nReversible — reactivate any domain at any time.", { title: "Pause sending" });
    if (!ok) return;
    btn.disabled = true; const orig = btn.textContent; btn.textContent = "Pausing…";
    await new Promise((r) => setTimeout(r, 500));
    let paused = 0;
    rows.forEach((r) => { r.rested = r.mailboxes; r.restedDue = Date.now() + 7 * 864e5; paused += r.mailboxes; });
    logAction({action: "blacklist_pause", mailboxes: paused, domains: rows.length, scope: "blacklist" });
    saveState();
    toast("Paused sending on " + paused + " mailbox(es) across " + rows.length + " domain(s) — resting 7 days", "ok");
    paintPage();
  }
  async function reactivateCleared(btn) {
    const rows = S.A.blacklistRows.filter((r) => r.cleared && r.rested > 0);
    if (!rows.length) { toast("Nothing cleared to reactivate", "err"); return; }
    const mbx = rows.reduce((s, r) => s + r.rested, 0);
    const ok = await dlvConfirm("Reactivate " + rows.length + " cleared domain(s) — " + mbx + " mailbox(es)?\n\nRestores each mailbox to its saved daily cap and resumes sending immediately.\n\nReversible — you can pause them again any time.", { title: "Reactivate cleared" });
    if (!ok) return;
    let resumed = 0;
    rows.forEach((r) => { resumed += r.rested; r.rested = 0; r.restedDue = null; });
    logAction({action: "warmup_resume", mailboxes: resumed });
    saveState();
    toast("Reactivated " + resumed + " mailbox(es) across " + rows.length + " cleared domain(s)", "ok");
    paintPage();
  }
  async function reactivateBlacklistDomain(domain) {
    const ok = await dlvConfirm("Reactivate " + domain + "?\n\nRestores its saved daily cap and resumes sending.\n\nProceed?", { title: "Reactivate domain" });
    if (!ok) return;
    const row = S.A.blacklistRows.find((r) => r.domain === domain);
    if (!row) return;
    const resumed = row.rested;
    row.rested = 0; row.restedDue = null;
    logAction({action: "warmup_resume", mailboxes: resumed });
    saveState();
    toast("Reactivated " + domain + " — " + resumed + " mailbox(es)", "ok");
    paintPage();
  }
  // Per-domain counterpart to pauseBlacklisted() (the bulk button) — fix #7a:
  // testers wanted to pause the one domain they were looking at without also
  // pausing every other still-sending blacklisted domain in the fold.
  async function pauseBlacklistDomain(domain) {
    const row = S.A.blacklistRows.find((r) => r.domain === domain);
    if (!row || row.rested > 0) { toast("Already resting", "err"); return; }
    const ok = await dlvConfirm("Pause sending on " + domain + "?\n\nSets its daily cap to 0 and rests it for 7 days across " + row.mailboxes + " mailbox(es) while you fix the underlying cause.\n\nReversible — reactivate any time.", { title: "Pause sending" });
    if (!ok) return;
    row.rested = row.mailboxes;
    row.restedDue = Date.now() + 7 * 864e5;
    logAction({action: "blacklist_pause", mailboxes: row.mailboxes, domains: 1, scope: domain });
    saveState();
    toast("Paused sending on " + domain + " — " + row.mailboxes + " mailbox(es) resting 7 days", "ok");
    paintPage();
  }

  /* ============================================================
     26. Delisting prep actions
     ============================================================ */
  async function delistCopyReq(domain, btn) {
    const row = S.A.blacklistRows.find((r) => r.domain === domain);
    const text = delistBlurb(domain, row ? row.lists : "");
    // No visible node on screen holds this text (it's built on the fly) — on
    // a clipboard failure copyText() falls back to its own floating,
    // pre-selected textarea anchored at `btn` (item 2).
    await copyText(text, "Copied ✓ — request text for " + domain, "delisting request for " + domain, { btn });
  }
  function delistToggle(domain, wasDone) {
    S.A.delisting = (S.A.delisting || []).filter((x) => x.domain !== domain);
    if (!wasDone) S.A.delisting.unshift({ domain, date: todayISO(), ts: Date.now() });
    logAction({action: wasDone ? "delist_undo" : "delist_submitted", count: 1, scope: domain });
    saveState();
    renderDelistBody();
    toast(wasDone ? "Unmarked " + domain + " as submitted" : "Marked " + domain + " as submitted for delisting", "ok");
    paintPage();
  }
  async function delistCopyAll(btn) {
    const rows = delistVisibleRows();
    await copyText(rows.map((r) => r.domain).join("\n"), "Copied ✓ — " + rows.length + " domain(s)", rows.length + " blacklisted domain(s)", { btn });
  }

  /* ============================================================
     27. Domain-health rotation actions
     ============================================================ */
  async function domainWarmup(domain, btn) {
    const ok = await dlvConfirm("Move " + domain + " to warmup?\n\n• Sets sending capacity to 0 for all its mailboxes\n• Warmup keeps running\n• Current caps are saved so Reactivate restores them\n\nProceed?", { title: "Move to warmup" });
    if (!ok) return;
    const mbx = S.A.inboxRows.filter((r) => r.domain === domain && r.kind === "ok" && r.cap > 0);
    mbx.forEach((r) => { r._savedCap = r.cap; r.cap = 0; });
    S.A.domainHealth.resting[domain] = mbx.length || 1;
    S.A.domainHealth.restingDue[domain] = Date.now() + 7 * 864e5;
    logAction({action: "warmup_pause", mailboxes: mbx.length, domains: 1, scope: domain });
    saveState();
    // Part A1 (make the state change unmistakable): name the domain, the count,
    // and that it's now resting with a due-back date — the row itself now reads
    // "🌙 resting · due in 7d".
    toast("🌙 " + domain + " moved to warm-up — " + mbx.length + " mailbox(es) resting, due back in 7d", "ok");
    paintPage();
  }
  async function domainReactivate(domain, btn) {
    const ok = await dlvConfirm("Reactivate " + domain + "?\n\nRestores each mailbox to its saved daily cap and resumes sending.\n\nProceed?", { title: "Reactivate domain" });
    if (!ok) return;
    const mbx = S.A.inboxRows.filter((r) => r.domain === domain);
    mbx.forEach((r) => { if (r._savedCap != null) { r.cap = r._savedCap; delete r._savedCap; } else if (r.cap === 0) r.cap = 20; });
    const resumed = S.A.domainHealth.resting[domain] || mbx.length;
    delete S.A.domainHealth.resting[domain];
    delete S.A.domainHealth.restingDue[domain];
    logAction({action: "warmup_resume", mailboxes: resumed });
    saveState();
    toast("Reactivated " + domain + " — " + resumed + " mailbox(es)", "ok");
    paintPage();
  }
  async function domainBulkFlagged() {
    const D = fullDerive();
    const { minSent, cutoff } = dhCutoffMin();
    const domains = D.dhRows.filter((d) => d.flag === "warmup" && !(D.resting[d.domain] > 0)).map((d) => d.domain);
    if (!domains.length) { toast("No flagged domains", "err"); return; }
    const ok = await dlvConfirm("Move ALL " + domains.length + " flagged domains to warmup?\n\n• Sets sending capacity to 0 for every mailbox on these domains\n• Warmup keeps running; saved caps let you Reactivate later\n\nProceed?", { title: "Move all flagged", yesLabel: "Move " + domains.length });
    if (!ok) return;
    let paused = 0;
    domains.forEach((domain) => {
      const mbx = S.A.inboxRows.filter((r) => r.domain === domain && r.kind === "ok" && r.cap > 0);
      mbx.forEach((r) => { r._savedCap = r.cap; r.cap = 0; });
      S.A.domainHealth.resting[domain] = mbx.length || 1;
      S.A.domainHealth.restingDue[domain] = Date.now() + 7 * 864e5;
      paused += mbx.length;
    });
    logAction({action: "warmup_pause", mailboxes: paused, domains: domains.length, scope: "bulk flagged" });
    saveState();
    toast("🌙 Moved " + domains.length + " flagged domain(s) to warm-up — " + paused + " mailbox(es) resting, due back in 7d", "ok");
    paintPage();
  }
  async function domainReactivateAll() {
    const D = fullDerive();
    const domains = Object.keys(D.resting);
    if (!domains.length) { toast("Nothing resting", "err"); return; }
    const ok = await dlvConfirm("Reactivate ALL " + domains.length + " resting domains?\n\nRestores each to its saved daily cap and resumes sending.\n\nProceed?", { title: "Reactivate all", yesLabel: "Reactivate " + domains.length });
    if (!ok) return;
    let resumed = 0;
    domains.forEach((domain) => {
      const mbx = S.A.inboxRows.filter((r) => r.domain === domain);
      mbx.forEach((r) => { if (r._savedCap != null) { r.cap = r._savedCap; delete r._savedCap; } else if (r.cap === 0) r.cap = 20; });
      resumed += S.A.domainHealth.resting[domain] || mbx.length;
      delete S.A.domainHealth.resting[domain];
      delete S.A.domainHealth.restingDue[domain];
    });
    logAction({action: "warmup_resume", mailboxes: resumed });
    saveState();
    toast("Reactivated " + resumed + " mailbox(es)", "ok");
    paintPage();
  }
  async function domainReactivateRecovered() {
    const doms = window._dlvRecovered || [];
    if (!doms.length) { toast("Nothing recovered", "err"); return; }
    const ok = await dlvConfirm("Reactivate " + doms.length + " recovered domain(s)?\n\n" + doms.join(", ") + "\n\nProceed?", { title: "Reactivate recovered", yesLabel: "Reactivate " + doms.length });
    if (!ok) return;
    let resumed = 0;
    doms.forEach((domain) => {
      const mbx = S.A.inboxRows.filter((r) => r.domain === domain);
      mbx.forEach((r) => { if (r._savedCap != null) { r.cap = r._savedCap; delete r._savedCap; } else if (r.cap === 0) r.cap = 20; });
      resumed += S.A.domainHealth.resting[domain] || mbx.length;
      delete S.A.domainHealth.resting[domain];
      delete S.A.domainHealth.restingDue[domain];
    });
    logAction({action: "warmup_resume", mailboxes: resumed });
    saveState();
    toast("Reactivated " + resumed + " mailbox(es) across " + doms.length + " recovered domain(s)", "ok");
    paintPage();
  }

  /* ============================================================
     28. Mailbox per-row + bulk actions
     ============================================================ */
  function reconnectOne(id) {
    const r = S.A.inboxRows.find((x) => x.id === id);
    if (!r) return;
    r.kind = "ok"; r.warmup_status = "ACTIVE"; r.cap = 20; r.reason = ""; r.reason_category = "";
    logAction({action: "reconnect", count: 1 });
    saveState();
    toast("Reconnect queued", "ok");
    paintPage();
  }
  function reenableOne(id) {
    const r = S.A.inboxRows.find((x) => x.id === id);
    if (!r) return;
    r.kind = "ok"; r.warmup_status = "ACTIVE"; r.cap = 15;
    S.A.warmupConfig.notWarming = S.A.warmupConfig.notWarming.filter((x) => x.email !== r.email);
    logAction({action: "reenable", count: 1, failed: 0 });
    saveState();
    toast("Warmup re-enabled", "ok");
    paintPage();
  }
  async function bulkAction(kind) {
    const ids = [...UI.mgr.sel];
    if (!ids.length) return;
    const rows = S.A.inboxRows.filter((r) => ids.includes(r.id));
    const confirms = {
      reconnect: "Reconnect " + ids.length + " selected mailbox(es)? Smartlead re-attempts the connection.",
      reenable: "Re-enable warmup on " + ids.length + " selected mailbox(es)?",
      warmup: "Put " + ids.length + " selected mailbox(es) into warmup?\n\n• Sets daily cap to 0 (warmup keeps running)\n• Saved caps let you Restore later",
      restore: "Restore " + ids.length + " selected mailbox(es) to sending?\n\nRestores each to the cap saved when the dashboard rested it.",
    };
    const ok = await dlvConfirm(confirms[kind], { title: "Confirm bulk action" });
    if (!ok) return;
    let n = 0;
    if (kind === "reconnect") { rows.forEach((r) => { r.kind = "ok"; r.warmup_status = "ACTIVE"; r.cap = 20; n++; }); logAction({action: "reconnect", count: n }); toast("Queued " + n + " mailbox(es) for reconnect", "ok"); }
    else if (kind === "reenable") { rows.forEach((r) => { r.kind = "ok"; r.warmup_status = "ACTIVE"; r.cap = 15; n++; }); S.A.warmupConfig.notWarming = S.A.warmupConfig.notWarming.filter((x) => !ids.includes((S.A.inboxRows.find((y) => y.email === x.email) || {}).id)); logAction({action: "reenable", count: n, failed: 0 }); toast("Re-enabled warmup on " + n + " mailbox(es)", "ok"); }
    else if (kind === "warmup") { const doms = new Set(); rows.forEach((r) => { if (r.cap > 0) { r._savedCap = r.cap; r.cap = 0; n++; doms.add(r.domain); } }); logAction({action: "warmup_pause", mailboxes: n, domains: doms.size }); toast("Paused sending on " + n + " mailbox(es) across " + doms.size + " domain(s) — resting 7 days", "ok"); }
    else if (kind === "restore") { rows.forEach((r) => { if (r.rested || r._savedCap != null) { r.cap = r._savedCap != null ? r._savedCap : 20; delete r._savedCap; r.rested = false; r.restedAt = null; n++; } }); logAction({action: "warmup_resume", mailboxes: n }); toast("Restored " + n + " mailbox(es) to sending", "ok"); }
    UI.mgr.sel = new Set();
    saveState();
    paintPage();
  }

  /* ============================================================
     29. Reminders
     ============================================================ */
  function remAdd() {
    const domsEl = $id("dlv-rem-doms");
    const doms = domsEl.value.trim();
    const date = $id("dlv-rem-date").value || todayISO();
    // Item 5a: an empty submit gets an INLINE red hint right under the field
    // (plus a red border + focus) instead of a bottom-of-screen toast the
    // tester's eyes aren't anywhere near.
    if (!doms) {
      const err = $id("dlv-rem-err");
      if (err) err.classList.add("show");
      domsEl.classList.add("dlv-input-err");
      domsEl.focus();
      return;
    }
    const errEl = $id("dlv-rem-err");
    if (errEl) errEl.classList.remove("show");
    domsEl.classList.remove("dlv-input-err");
    const domains = doms.split(/[\s,;]+/).filter(Boolean);
    const id = uid("r");
    S.A.reminders.unshift({ id, domains, note: "", restoredDate: date, dueDate: addDays(date, 14), done: false, ts: Date.now() });
    S.A.remHealth[id] = { total: domains.length, warming: domains.length, failed: 0, dead: 0, reasons: {} };
    logAction({action: "reminder_add", count: domains.length, scope: domains.join(", ") });
    saveState();
    toast("Reminder added for " + domains.length + " domain(s) — due in 14 days", "ok");
    paintPage();
  }
  function remDone(id, undo) {
    const r = S.A.reminders.find((x) => x.id === id);
    S.A.reminders = S.A.reminders.map((x) => (x.id === id ? Object.assign({}, x, { done: !undo }) : x));
    logAction({action: undo ? "reminder_undo" : "reminder_done", count: 1, scope: r ? (r.domains || []).join(", ") : "" });
    saveState();
    toast(undo ? "Reminder restored to pending" : "Reminder marked added back", "ok");
    paintPage();
  }
  function remEnableWarmup(id) {
    const h = S.A.remHealth[id];
    if (!h) return;
    const n = h.reasons.off || 0;
    if (!n) { toast("Nothing to enable — those mailboxes are already warming or blocked/missing", ""); return; }
    h.warming += n; h.failed -= n; h.reasons = Object.assign({}, h.reasons, { off: 0 });
    logAction({action: "reenable", count: n, failed: 0, scope: "restore reminder" });
    saveState();
    toast("Warm-up enabled on " + n + " mailbox(es)", "ok");
    paintPage();
  }
  async function remRemove(id) {
    const r = S.A.reminders.find((x) => x.id === id);
    if (!r) return;
    const label = (r.domains || []).join(", ") || "this reminder";
    const ok = await dlvConfirm("Remove the restore reminder for " + label + "?\n\nThis deletes it outright — re-add it from the form above if you change your mind.", { title: "Remove reminder", danger: true, yesLabel: "Remove" });
    if (!ok) return;
    S.A.reminders = S.A.reminders.filter((x) => x.id !== id);
    delete S.A.remHealth[id];
    logAction({action: "reminder_removed", count: 1, scope: label });
    saveState();
    toast("Reminder removed", "ok");
    paintPage();
  }

  /* ============================================================
     30. Header actions — run audit / copy / notion / slack
     ============================================================ */
  async function runLiveAudit() {
    const btn = $id("dlv-run-btn");
    if (!btn || btn.dataset.busy) return;
    // Live mode: force a fresh POST /run (~1-2 min) against the real backend.
    if (isLive()) {
      const ok = await dlvConfirm("Pull a fresh live audit?\n\nThis runs a brand-new live snapshot from Smartlead (~1–2 min) and clears every action you've taken this session (marked-done items, pauses, signatures, tags…).\n\nNot reversible.", { title: "Run Live Audit", danger: true, yesLabel: "Run audit" });
      if (!ok) return;
      btn.dataset.busy = "1";
      await runLiveAuditBg(true); // shows the running banner + repaints on resolve
      clearDoneStubs();
      UI.mgr.sel = new Set();
      delete btn.dataset.busy;
      toast(DATA.runError ? "Live audit failed — showing the last snapshot" : "Live audit complete", DATA.runError ? "" : "ok");
      return;
    }
    // Sample mode: no live backend to hit — just rebuild the mock snapshot.
    const ok = await dlvConfirm("Reset the sample data?\n\nThe live deliverability backend isn't configured, so this only rebuilds the demo snapshot and clears every action you've taken this session (marked-done items, pauses, signatures, tags…).\n\nNot reversible.", { title: "Reset sample data", danger: true, yesLabel: "Reset" });
    if (!ok) return;
    btn.dataset.busy = "1"; btn.disabled = true;
    const orig = btn.innerHTML;
    btn.innerHTML = '<span class="dlv-spinner"></span> Resetting…';
    await new Promise((r) => setTimeout(r, 600));
    resetState();
    clearDoneStubs(); // fix #1: stubs describe pre-reset state — drop them
    UI.mgr.sel = new Set();
    delete btn.dataset.busy;
    paintPage();
    toast("Sample data reset", "ok");
  }
  function copyForClaude() { openCtxModal(); }
  async function copyCtx(btn) {
    // Item 2: on a clipboard failure the modal stays open (only a success
    // closes it, below) and copyText() range-selects the visible <pre> the
    // text actually came from, so the tester's next Ctrl/Cmd+C copies exactly
    // what they were looking at — no separate "where did the text go" hunt.
    const body = $id("dlv-ctx-body");
    const ok = await copyText(body ? body.textContent : "", "Copied ✓ — paste into a Claude chat", "audit context for Claude", { btn, sourceEl: body });
    if (ok) closeModal("dlv-ctx-overlay");
  }
  async function copyHypertide(btn) {
    // Item 2: flash the "Copy email" button itself — the modal stays open, so
    // the receipt (success or failure) sits exactly where the user just
    // clicked; a failure also range-selects the visible <pre> preview.
    const body = $id("dlv-hypertide-body");
    await copyText(body ? body.textContent : "", "Copied ✓ — Hypertide email", "Hypertide escalation email", { btn, sourceEl: body });
  }
  /* Builds the exact domain + field list a Notion sync would write, straight
     off S — same "preview before you send" treatment as Slack, so nothing
     gets pushed blind. Deduped by domain, merging every field that changed. */
  function notionSyncPlan() {
    const D = fullDerive();
    const map = new Map();
    const add = (domain, field) => { if (!map.has(domain)) map.set(domain, new Set()); map.get(domain).add(field); };
    Object.keys(D.resting || {}).forEach((d) => add(d, "resting status"));
    Object.keys(D.restingDue || {}).forEach((d) => { if (D.restingDue[d]) add(d, "resting due date"); });
    D.dhRows.filter((d) => d.flag === "warmup" && !(D.resting[d.domain] > 0)).forEach((d) => add(d.domain, "reply rate"));
    S.A.blacklistRows.forEach((b) => { add(b.domain, "blacklist status"); if (b.cleared) add(b.domain, "cleared flag"); });
    return [...map.entries()].map(([domain, fields]) => ({ domain, fields: [...fields] })).sort((a, b) => a.domain.localeCompare(b.domain));
  }
  function openNotionModal() {
    const rows = notionSyncPlan();
    const body = $id("dlv-notion-body");
    body.innerHTML = rows.length
      ? `<div class="dlv-mb-wrap"><div class="dlv-mb-scroll" style="max-height:280px">` +
        rows.map((r) => `<div class="dlv-rem-row"><div class="dlv-rem-main"><div class="dlv-rem-doms">${esc(r.domain)}</div><div class="dlv-rem-meta">${r.fields.map(esc).join(" · ")}</div></div></div>`).join("") +
        `</div></div>`
      : `<div class="dlv-empty">Nothing to sync — no domain state has changed.</div>`;
    const btn = $id("dlv-notion-sync-btn");
    btn.textContent = "Sync " + rows.length + " domain(s)";
    btn.disabled = !rows.length;
    openModal("dlv-notion-overlay");
  }
  async function doNotionSync() {
    const rows = notionSyncPlan();
    const n = rows.length;
    if (!n) { toast("Nothing to sync", "err"); return; }
    const btn = $id("dlv-notion-sync-btn");
    busySet(btn, '<span class="dlv-spinner"></span> Syncing…');
    await new Promise((r) => setTimeout(r, 900));
    logAction({action: "notion_sync", count: n, scope: "changed" });
    saveState();
    busyRestore(btn);
    closeModal("dlv-notion-overlay");
    toast("Notion: updated " + n + " domain(s)", "ok");
    paintPage();
    // Item 2: same durable receipt treatment as Slack — flash the header button.
    flashBtn(document.querySelector('[data-act="sync-notion"]'), "✓ Synced");
  }
  function buildSlackMessage(D) {
    const st = computeStatus(D);
    const emoji = { g: "🟢", a: "🟡", r: "🔴" }[st.dot];
    const lines = [];
    lines.push(emoji + " *Navreo Deliverability — " + S.A.date + "* — " + st.status);
    lines.push(fmtN(S.A.inboxes) + " inboxes · " + S.A.domains + " domains · " + S.A.active + " active campaigns");
    lines.push("Reply " + S.A.reply_pct + "% · Bounce " + S.A.bounce_pct + "% · Sent " + fmtN(S.A.sent));
    lines.push("");
    lines.push("*Today's to-do (" + D.activeTodo.length + "):*");
    // Fix F(i): this used to cap the enumeration at 8 (`.slice(0, 8)`) while the
    // headline above prints the FULL `D.activeTodo.length` (9, 10…) — a reader
    // counting the numbered lines against the "(N)" in the heading would always
    // come up short by however many items ran past 8. Enumerate every item so
    // the count in the heading always equals what's actually listed below it.
    D.activeTodo.forEach((it, i) => lines.push((i + 1) + ". [" + it.level.toUpperCase() + "] " + it.text));
    if (!D.activeTodo.length) lines.push("_All clear — nothing needs action today._");
    return lines.join("\n");
  }
  function openSlackModal() {
    const D = fullDerive();
    $id("dlv-slack-body").textContent = buildSlackMessage(D);
    openModal("dlv-slack-overlay");
  }
  async function doSlackSend() {
    const btn = document.querySelector('[data-act="slack-send"]');
    if (!btn) return;
    busySet(btn, '<span class="dlv-spinner"></span> Sending…');
    await new Promise((r) => setTimeout(r, 900));
    logAction({action: "slack_post", count: 1 });
    saveState();
    busyRestore(btn);
    closeModal("dlv-slack-overlay");
    toast("Posted to #team-hangout ✓", "ok");
    paintPage();
    // Item 2: the modal just closed — flash the header "Send to Slack" button
    // (queried AFTER paintPage so it's the freshly-rendered node) so there's a
    // 2.5s on-page receipt even if the toast goes unseen.
    flashBtn(document.querySelector('[data-act="send-slack"]'), "✓ Posted");
  }
  function busySet(btn, html) { btn.disabled = true; btn.dataset._orig = btn.innerHTML; btn.innerHTML = html; }
  function busyRestore(btn, orig) { btn.disabled = false; btn.innerHTML = orig != null ? orig : btn.dataset._orig; delete btn.dataset._orig; }

  /* ============================================================
     31. Fold open/scroll/flash helper — a native `behavior:'smooth'`
         scrollIntoView() can get silently cut short if a reflow (e.g. a
         late-loading web font swap) shifts the target mid-animation, which
         read to testers as "Manage ↓ does nothing". This self-corrects by
         re-measuring the target every frame instead of committing to one
         fixed distance up front, then flashes an outline so the jump is
         unmistakable even when the fold was already open/in view.
     ============================================================ */
  function easeScrollTo(el) {
    // setTimeout-driven rather than requestAnimationFrame: rAF can be fully
    // paused for a backgrounded/inactive tab, which is exactly the failure
    // mode that made native scrollIntoView({behavior:'smooth'}) look like it
    // "did nothing" — a plain timer keeps converging regardless.
    const start = Date.now();
    const maxDur = 650;
    function step() {
      const rect = el.getBoundingClientRect();
      const delta = rect.top - 16;
      if (Math.abs(delta) <= 2) return;
      if (Date.now() - start >= maxDur) { window.scrollBy(0, delta); return; }
      window.scrollBy(0, delta * 0.3);
      setTimeout(step, 16);
    }
    step();
  }
  function flashEl(el) {
    el.classList.remove("dlv-flash");
    void el.offsetWidth; // restart the CSS animation if it's already mid-flash
    el.classList.add("dlv-flash");
    clearTimeout(el._flashT);
    el._flashT = setTimeout(() => el.classList.remove("dlv-flash"), 1500);
  }
  /* Item 2 (durable near-click receipts): toasts appear at the bottom of the
     viewport and die in ~3s — several testers never saw them. In ADDITION to
     the toast, the clicked control itself flashes a temporary success state
     for ~2.5s ("✓ Copied", "✓ Downloaded", "✓ Posted", "✓ Synced") right
     where the user's eyes already are, then restores its original content.
     Safe against double-clicks (original content captured once, timer reset)
     and against repaints (a replaced node's timer just fizzles on a detached
     element). */
  function flashBtn(el, label) {
    if (!el) return;
    if (el._flashOrig == null) el._flashOrig = el.innerHTML;
    el.innerHTML = esc(label);
    el.classList.add("dlv-btn-flash");
    clearTimeout(el._flashBtnT);
    el._flashBtnT = setTimeout(() => {
      el.classList.remove("dlv-btn-flash");
      if (el._flashOrig != null) el.innerHTML = el._flashOrig;
      el._flashOrig = null;
    }, 2500);
  }
  function openFold(id) {
    const f = $id(id);
    if (!f) return;
    f.open = true; // getBoundingClientRect() below forces the layout to settle first
    easeScrollTo(f);
    flashEl(f);
  }
  // Same scroll+flash treatment as openFold(), but for a plain wrapper div
  // (the to-do list isn't a <details> fold) — used by the health strip's
  // "N things need action today →" chip (fix #1).
  function openFoldlessScroll(id) {
    const f = $id(id);
    if (!f) return;
    easeScrollTo(f);
    flashEl(f);
  }
  // Deep-link target for the 3 sections that moved out of the Overview scroll
  // into their own sub-tab: switch tabs, repaint, jump to the top of the page
  // (the panel now starts right under the sub-tab bar), then briefly flash its
  // heading so the jump reads as unmistakably as the old openFold() did.
  function gotoSubtab(id, flashId) {
    setSubtab(id);
    paintPage();
    window.scrollTo(0, 0);
    if (flashId) {
      const el = $id(flashId);
      if (el) flashEl(el);
    }
  }
  // A deep link that targets an Overview-only section (Reminders / Recent
  // actions / Actioned) can, in principle, be clicked from a persistent node
  // (e.g. a toast) while a different sub-tab is active — force back to
  // Overview first so the target is guaranteed to exist in the DOM.
  function ensureOverviewThenOpenFold(id) {
    if (dlvSubtab !== "overview") { setSubtab("overview"); paintPage(); }
    openFold(id);
  }

  /* ============================================================
     32. Event delegation — the ONLY listeners this file installs.
         Covers #dlv-root (repainted often) and the modal nodes
         (persistent), so one wiring pass handles everything.
     ============================================================ */
  let _wired = false;
  function wireEvents() {
    if (_wired) return;
    _wired = true;
    document.addEventListener("click", onDlvClick);
    document.addEventListener("change", onDlvChange);
    document.addEventListener("input", onDlvInput);
    // Native <details> "toggle" event doesn't bubble in every browser, but the
    // capture phase always reaches the target regardless — used only to persist
    // the technical-details fold's manual open/close state (see renderTechFold).
    document.addEventListener("toggle", onDlvToggle, true);
    // Defect 4: now that clicking the backdrop no longer dismisses a modal,
    // Escape has to actually do it — it's named as one of the three ways out
    // (×, Cancel, Escape) but nothing wired it up before.
    document.addEventListener("keydown", onDlvKeydown);
  }

  function onDlvKeydown(e) {
    if (e.key !== "Escape" && e.key !== "Esc") return;
    runAct("escape-close", () => {
      // openModal()'s own exclusivity guarantees at most one id is ever
      // tracked open at a time — close whichever one that is. Falls back to
      // dismissing the glossary popover (a separate, non-modal overlay) so
      // Escape still does something sensible if no modal is open.
      if (_openModalIds.size) {
        const ids = [..._openModalIds];
        closeModal(ids[ids.length - 1]);
      } else {
        closeGlossaryPopover();
        closeCopyFallback();
      }
    });
  }

  function onDlvToggle(e) {
    if (e.target && e.target.id === "dlv-fold-tech") {
      S.ui = S.ui || {};
      S.ui.techOpen = !!e.target.open;
      saveState();
    }
  }

  // Defect A fix (hypothesis 2) — root cause of the intermittent "click does
  // nothing" reports: none of these handlers were guarded. Any exception
  // thrown anywhere in a handler — a null-deref on session state one tester's
  // mutations happened to produce but another tester's didn't, say — aborted
  // the WHOLE delegated listener for that click with no visible sign it had
  // even run, which is exactly "intermittent by session state". runAct() below
  // wraps every dispatch (sync throw AND async rejection, since most of these
  // handlers are `async function`s that can throw after their first await,
  // past the point a plain try/catch around the call would still be on the
  // stack) so a broken action always surfaces as a toast + console.error
  // instead of silent nothing.
  function reportActionError(act, err) {
    console.error("[deliverability] action failed:", act, err);
    toast("⚠ Action failed" + (act ? " — " + act : ""), "err");
  }
  function runAct(act, fn) {
    try {
      const r = fn();
      if (r && typeof r.then === "function") r.catch((err) => reportActionError(act, err));
    } catch (err) {
      reportActionError(act, err);
    }
  }

  function onDlvClick(e) {
    try {
      dispatchDlvClick(e);
    } catch (err) {
      // Belt-and-braces: everything inside dispatchDlvClick's own per-act
      // dispatch already goes through runAct(), but this outer catch covers
      // the dispatch logic itself (e.g. a broken selector above the act
      // lookup) so literally nothing in this listener can fail silently.
      let act = null;
      try { const t = e.target && e.target.closest && e.target.closest("[data-act]"); act = t ? t.dataset.act : null; } catch (_) {}
      reportActionError(act, err);
    }
  }
  function dispatchDlvClick(e) {
    // Fix #2 — root-cause hardening: e.target.closest() throws if e.target
    // isn't an Element (e.g. a Text node), which would silently abort this
    // WHOLE delegated handler for that click — reading as "I clicked and
    // nothing happened" for whatever was under the cursor (a to-do card's
    // glossify()-inserted <sup> sitting right next to a button is exactly the
    // kind of DOM shape that raises the odds of that happening). Normalize to
    // the nearest Element first so a stray non-Element target degrades to
    // "look at the parent" instead of throwing.
    const targetEl = e.target && e.target.nodeType === 1 ? e.target : (e.target && e.target.parentElement);
    // Glossary popover is dismissable on any outside click — checked ahead of
    // the data-act lookup below so it also closes on clicks that don't carry
    // a data-act at all (e.g. clicking blank page background).
    const gpop = $id("dlv-gloss-pop");
    if (gpop && gpop.classList.contains("show") && !gpop.contains(e.target) && !(targetEl && targetEl.closest('[data-act="gloss-open"]'))) {
      closeGlossaryPopover();
    }
    // Item 2's manual-copy fallback box is dismissable the same way — any
    // click outside it (other than the copy button that might reopen it with
    // fresh text) closes it.
    const cfb = $id("dlv-copy-fallback");
    if (cfb && cfb.classList.contains("show") && !cfb.contains(e.target)) {
      closeCopyFallback();
    }
    // Defect D fix (belt-and-braces): drive every <summary> fold toggle
    // explicitly instead of depending only on the browser's native
    // click-to-toggle activation for <details> — verified some click-delivery
    // paths land the click on a fold's summary without ever invoking that
    // native behavior, which reads exactly like "the toggle doesn't collapse".
    // preventDefault() suppresses the native toggle so it can't ALSO fire and
    // cancel this one back out (double-toggle = no visible change at all).
    // Item 5c: glossary "?" markers now also live INSIDE fold summaries (batch
    // fold header) — resolve a gloss click before the summary-toggle logic
    // below, or the click would toggle the fold instead of opening the popover.
    const glossTrigger = targetEl && targetEl.closest('[data-act="gloss-open"]');
    if (glossTrigger) {
      e.preventDefault();
      runAct("gloss-open", () => openGlossaryPopover(glossTrigger));
      return;
    }
    const foldSummary = targetEl && targetEl.closest("details.dlv-fold > summary");
    if (foldSummary) {
      e.preventDefault();
      const details = foldSummary.parentElement;
      runAct("fold-toggle", () => {
        details.open = !details.open;
        details.dispatchEvent(new Event("toggle"));
      });
      return;
    }
    const t = targetEl && targetEl.closest("[data-act]");
    if (!t) return;
    const act = t.dataset.act;
    // Guard: this delegated listener is global (attached once to `document`,
    // per hypothesis 1) so it keeps working after any number of repaints —
    // but it should still no-op once every trace of this tab is gone from the
    // page (both the live #dlv-root AND the persistent toast stack / modals).
    if (!$id("dlv-root") && !$id("dlv-toast-stack")) return;

    // Defect 4 (click-shield): the overlay backdrop used to close the modal
    // on a direct click — meant as a convenience "click outside to dismiss",
    // but it meant ANY click that landed on the backdrop (including one aimed
    // at a background button the overlay happens to cover, or a stray click
    // while filling in a modal's own form) silently discarded whatever the
    // user had open, with zero warning. The overlay still physically blocks
    // clicks from reaching anything behind it (it's a full-viewport, higher
    // z-index fixed element) — this just stops the backdrop itself from
    // ALSO acting as a dismiss target. ×, Cancel, and Escape remain the only
    // ways out.
    if (act === "overlay-bg") { return; }
    if (act === "close-modal") { runAct(act, () => closeModal(t.dataset.modal)); return; }
    if (act === "confirm-yes") { runAct(act, () => closeConfirm(true)); return; }
    if (act === "confirm-no") { runAct(act, () => closeConfirm(false)); return; }
    if (act === "gloss-open") { e.preventDefault(); runAct(act, () => openGlossaryPopover(t)); return; }
    if (act === "gloss-close") { runAct(act, () => closeGlossaryPopover()); return; }
    if (act === "copy-fallback-close") { runAct(act, () => closeCopyFallback()); return; }
    // Part B1: onboarding coach — dismiss persists the seen flag; Show tips
    // re-opens it transiently for the current view.
    if (act === "coach-dismiss") { runAct(act, () => { try { localStorage.setItem("dlv_coach_seen", "1"); } catch (e) {} UI.coachOpen = false; paintPage(); }); return; }
    if (act === "show-coach") { runAct(act, () => { UI.coachOpen = true; paintPage(); const c = $id("dlv-coach"); if (c) easeScrollTo(c); }); return; }
    // Part A2: dismiss a persisted per-campaign verify result box.
    if (act === "verify-dismiss") { runAct(act, () => { if (S.ui && S.ui.verifyResults) { delete S.ui.verifyResults[t.dataset.id]; saveState(); paintPage(); } }); return; }
    if (act === "scroll-todo") { runAct(act, () => openFoldlessScroll("dlv-todo-anchor")); return; }
    // Stage-A data-source banner dismiss buttons.
    if (act === "dismiss-sample-banner") { runAct(act, () => { DATA.sampleDismissed = true; paintPage(); }); return; }
    if (act === "dismiss-run-error") { runAct(act, () => { DATA.runError = null; paintPage(); }); return; }
    // Defect H: the "or undo later from Recent actions ↓" hint line inside an
    // undo toast — scrolls to (and opens) the Recent-actions fold. Recent
    // actions stayed in Overview (it wasn't one of the 3 moved sections), but
    // this can fire from a persistent toast while another sub-tab is active,
    // so force back to Overview first.
    if (act === "scroll-history") { runAct(act, () => ensureOverviewThenOpenFold("dlv-fold-history")); return; }
    // Defect 3: the undo toast's hint now points here — the "✅ Actioned"
    // fold (part of Overview's "today's to-do"), which is where its per-item
    // ↩ Undo button actually lives.
    if (act === "scroll-actioned") { runAct(act, () => ensureOverviewThenOpenFold("dlv-fold-actioned")); return; }

    // Sub-tab bar — switches which panel paintPage() renders, persists the
    // choice in sessionStorage, and scrolls back to the top (each panel is a
    // fresh view, not a scroll position within the same document).
    if (act === "dlv-subtab") {
      runAct(act, () => {
        const id = t.dataset.subtab;
        if (id === dlvSubtab) return;
        setSubtab(id);
        paintPage();
        window.scrollTo(0, 0);
      });
      return;
    }
    if (act === "goto-campaigns") { runAct(act, () => { location.hash = ""; }); return; }
    if (act === "run-audit") { runAct(act, () => runLiveAudit()); return; }
    if (act === "copy-claude") { runAct(act, () => copyForClaude()); return; }
    if (act === "copy-ctx") { runAct(act, () => copyCtx(t)); return; }
    if (act === "copy-hypertide") { runAct(act, () => copyHypertide(t)); return; }
    if (act === "sync-notion") { runAct(act, () => openNotionModal()); return; }
    if (act === "notion-sync") { runAct(act, () => doNotionSync()); return; }
    if (act === "send-slack") { runAct(act, () => openSlackModal()); return; }
    if (act === "slack-send") { runAct(act, () => doSlackSend()); return; }
    // Each toast is now its own DOM node (defect B) — dismiss the one this
    // button actually lives in, not a single shared-by-id node.
    if (act === "toast-undo") { runAct(act, () => { dismissToastEl(t.closest(".dlv-toast")); unmarkDone(t.dataset.key); }); return; }
    if (act === "draft-email") { runAct(act, () => onDraftEmailClick()); return; }
    if (act === "view-data") { runAct(act, () => viewData(t.dataset.file)); return; }
    if (act === "verify-view") {
      runAct(act, () => {
        const v = _verifyState[t.dataset.id] || ((S.ui && S.ui.verifyResults) ? S.ui.verifyResults[t.dataset.id] : null);
        const kind = t.dataset.kind;
        const n = v ? (kind === "keep" ? v.keep : v.remove) : 0;
        viewVerifyData(kind, t.dataset.id, fakeLeadRows(t.dataset.id, n, kind));
      });
      return;
    }
    if (act === "mark-done") { runAct(act, () => onMarkDoneClick(t.dataset.key, t.dataset.count)); return; }
    if (act === "unmark-done") { runAct(act, () => unmarkDone(t.dataset.key)); return; }
    // Part C(b): opening the manager via a to-do deep link resets the VIEW to
    // the domain reply-rate rotation table and its filter to the relevant
    // "needs warm-up" set, then switches to its tab — so a user arriving from
    // "these domains should go into warm-up" lands on exactly that list rather
    // than whatever view/filter was left selected from a previous poke.
    // Rewired: "Inbox & domain manager" is now its own sub-tab rather than a
    // fold further down the scroll (blacklist to-do's "advanced rotation"
    // link, the warm-up to-do's "Open manager ↓", the Warmup tile's fix-link,
    // and the Fleet-tiles signpost row all land here the same way).
    if (act === "open-manager") { runAct(act, () => {
      UI.mgr.view = "domain";
      UI.mgr.domFilter = "warmup";
      UI.mgr._domFilterUserSet = true; // honour this deliberate reset over autoDefault
      gotoSubtab("manager", "dlv-fold-manager");
    }); return; }
    // Rewired: "Restore reminders" is now its own sub-tab (the to-do card's
    // "⏰ Reminders ↓" button lands here) — switch tab, repaint, jump to top,
    // flash the heading, exactly like the other three moved sections.
    if (act === "open-reminders") { runAct(act, () => gotoSubtab("reminders", "dlv-fold-reminders")); return; }
    // Rewired: "Blacklisted domains" is now its own sub-tab (the to-do card's
    // "🚫 Manage ↓" and the Blacklisted-domains tile's fix-link both land here).
    if (act === "open-blacklist") { runAct(act, () => gotoSubtab("blacklist", "dlv-fold-blacklist")); return; }
    // Rewired: "Performance by batch" is now its own sub-tab (the Fleet-tiles
    // "▲▼ Best & worst batch ↓" signpost lands here).
    if (act === "open-batch") { runAct(act, () => gotoSubtab("batch", "dlv-fold-batch")); return; }
    if (act === "open-warmup-fix") { runAct(act, () => openWarmupFixModal()); return; }
    if (act === "open-sig-fix") { runAct(act, () => openSigFixModal()); return; }
    if (act === "open-process-new") { runAct(act, () => openProcessNewModal()); return; }
    if (act === "open-delisting") { runAct(act, () => openDelistingModal()); return; }
    if (act === "open-caps-preview") { runAct(act, () => openCapsPreviewModal()); return; }
    if (act === "caps-apply") { runAct(act, () => capsApply()); return; }
    if (act === "sig-apply") { runAct(act, () => sigApply()); return; }
    if (act === "pn-apply") { runAct(act, () => pnApply()); return; }
    if (act === "wu-apply") { runAct(act, () => wuApply()); return; }
    if (act === "verify-campaign") { runAct(act, () => verifyCampaignAction(t.dataset.id, t.dataset.mode, t)); return; }
    if (act === "remove-bad") { runAct(act, () => removeBadAction(t.dataset.id, t)); return; }
    if (act === "pause-blacklisted") { runAct(act, () => pauseBlacklisted(t)); return; }
    if (act === "reactivate-cleared") { runAct(act, () => reactivateCleared(t)); return; }
    if (act === "domain-reactivate-bl") { runAct(act, () => reactivateBlacklistDomain(t.dataset.domain)); return; }
    if (act === "pause-blacklist-domain") { runAct(act, () => pauseBlacklistDomain(t.dataset.domain)); return; }
    if (act === "dl-copy-all") { runAct(act, () => delistCopyAll(t)); return; }
    if (act === "dl-copy-req") { runAct(act, () => delistCopyReq(t.dataset.domain, t)); return; }
    if (act === "dl-toggle") { runAct(act, () => delistToggle(t.dataset.domain, t.dataset.done === "1")); return; }
    if (act === "mgr-refresh") { runAct(act, () => {
      if (isLive()) {
        // Drop the per-panel live caches so the current view re-pulls fresh.
        DATA.mgr.key = null; DATA.mgr.rows = null; DATA.mgr.counts = null; DATA.mgr.batches = null;
        DATA.dh.key = null; DATA.dh.done = false;
        toast("Re-pulling live from Smartlead…", "");
        paintPage();
      } else {
        toast("Refreshed (mock) from Smartlead", "ok");
        paintPage();
      }
    }); return; }
    if (act === "domain-warmup") { runAct(act, () => domainWarmup(t.dataset.domain, t)); return; }
    if (act === "domain-reactivate") { runAct(act, () => domainReactivate(t.dataset.domain, t)); return; }
    if (act === "domain-bulk-flagged") { runAct(act, () => domainBulkFlagged()); return; }
    if (act === "domain-reactivate-all") { runAct(act, () => domainReactivateAll()); return; }
    if (act === "domain-reactivate-recovered") { runAct(act, () => domainReactivateRecovered()); return; }
    if (act === "reconnect-one") { runAct(act, () => reconnectOne(Number(t.dataset.id))); return; }
    if (act === "reenable-one") { runAct(act, () => reenableOne(Number(t.dataset.id))); return; }
    if (act === "bulk-reconnect") { runAct(act, () => bulkAction("reconnect")); return; }
    if (act === "bulk-reenable") { runAct(act, () => bulkAction("reenable")); return; }
    if (act === "bulk-warmup") { runAct(act, () => bulkAction("warmup")); return; }
    if (act === "bulk-restore") { runAct(act, () => bulkAction("restore")); return; }
    if (act === "rem-add") { runAct(act, () => remAdd()); return; }
    if (act === "rem-done") { runAct(act, () => remDone(t.dataset.id, false)); return; }
    if (act === "rem-undo") { runAct(act, () => remDone(t.dataset.id, true)); return; }
    if (act === "rem-enable-warmup") { runAct(act, () => remEnableWarmup(t.dataset.id)); return; }
    if (act === "rem-remove") { runAct(act, () => remRemove(t.dataset.id)); return; }
  }

  function onDlvChange(e) {
    let act = null;
    try {
      const t = e.target.closest("[data-act]");
      if (!t) return;
      act = t.dataset.act;
      dispatchDlvChange(t, act);
    } catch (err) {
      reportActionError(act, err);
    }
  }
  function dispatchDlvChange(t, act) {
    if (act === "mgr-view") { UI.mgr.view = t.value; UI.mgr.sel = new Set(); UI.mgr.search = ""; paintPage(); return; }
    if (act === "mgr-domfilter") { UI.mgr.domFilter = t.value; UI.mgr._domFilterUserSet = true; paintManagerRows(); return; }
    if (act === "mgr-batch") { UI.mgr.batch = t.value; UI.mgr.sel = new Set(); paintManagerRows(); return; }
    if (act === "mgr-dh-start") { S.A.domainHealth.start = t.value; saveState(); paintManagerRows(); return; }
    if (act === "mgr-dh-end") { S.A.domainHealth.end = t.value; saveState(); paintManagerRows(); return; }
    if (act === "mgr-select-all") {
      const D = fullDerive(); let rows = mgrRowsForView(D);
      const q = (UI.mgr.search || "").trim().toLowerCase();
      if (q) rows = rows.filter((r) => (r.email || "").toLowerCase().includes(q) || (r.domain || "").toLowerCase().includes(q));
      if (t.checked) rows.forEach((r) => UI.mgr.sel.add(r.id)); else rows.forEach((r) => UI.mgr.sel.delete(r.id));
      paintManagerRows();
      return;
    }
    if (act === "mgr-row-select") { const id = Number(t.dataset.id); if (t.checked) UI.mgr.sel.add(id); else UI.mgr.sel.delete(id); paintManagerRows(); return; }
    if (act === "sig-batch-change") { sigOnBatchChange(); return; }
    if (act === "dl-include-young") { UI.delist.includeYoung = t.checked; renderDelistBody(); return; }
    if (act === "rem-date-input") { updateRemDateHint(t.value); return; }
  }

  // Live "Will be due {date}" hint under the reminder-add form — recomputed on
  // every keystroke/pick so the +14-day math is never a surprise on submit.
  function updateRemDateHint(v) {
    const hint = $id("dlv-rem-hint");
    if (!hint) return;
    const d = v || todayISO();
    hint.textContent = "Will be due " + addDays(d, 14);
  }

  function onDlvInput(e) {
    let act = null;
    try {
      const t = e.target.closest("[data-act]");
      if (!t) return;
      act = t.dataset.act;
      dispatchDlvInput(t, act);
    } catch (err) {
      reportActionError(act, err);
    }
  }
  function dispatchDlvInput(t, act) {
    if (act === "mgr-search") { UI.mgr.search = t.value; paintManagerRows(); return; }
    if (act === "mgr-dh-minsent") { UI.dh.minSent = Number(t.value) || 500; paintManagerRows(); return; }
    if (act === "mgr-dh-cutoff") { UI.dh.cutoff = Number(t.value) || 0.8; paintManagerRows(); return; }
    if (act === "rem-date-input") { updateRemDateHint(t.value); return; }
    // Item 5a: typing in the domains field clears the inline "type a domain
    // first" error state as soon as it's no longer true.
    if (act === "rem-doms-input") {
      if (t.value.trim()) {
        const err = $id("dlv-rem-err");
        if (err) err.classList.remove("show");
        t.classList.remove("dlv-input-err");
      }
      return;
    }
    if (act === "sig-search") { const r = inboxFilterRows("dlv-sig-targets", t.value); $id("dlv-sig-target-n").textContent = t.value.trim() ? r.shown + " of " + r.total : String(r.total); return; }
    if (act === "sig-tpl-input") { sigUpdatePreview(); return; }
    if (act === "pn-search") { const r = inboxFilterRows("dlv-pn-targets", t.value); $id("dlv-pn-target-n").textContent = t.value.trim() ? r.shown + " of " + r.total : String(r.total); return; }
    if (act === "wu-search") { const r = inboxFilterRows("dlv-wu-targets", t.value); $id("dlv-wu-target-n").textContent = t.value.trim() ? r.shown + " of " + r.total : String(r.total); return; }
  }

  /* ============================================================
     33. Public entry point — the ONE global this file adds.
     ============================================================ */
  window.renderDeliverability = function () {
    injectStyles();
    ensureModals();
    wireEvents();
    if (!S) loadState();
    loadSubtab(); // restore the sub-tab the owner was on (sessionStorage "dlv_subtab")
    const main = document.getElementById("main");
    if (!main) return false;
    main.innerHTML = '<div id="dlv-root" class="dlv"></div>';
    paintPage();
    maybePulseFirstGloss();
    // Stage A: probe the live backend and (in live mode) pull the real data.
    // Non-blocking — the mock/cached snapshot above renders instantly; bootData
    // repaints once the probe (and any background /run) resolve. Short-circuits
    // on later mounts (tab switches) via DATA.probed so it runs at most once.
    bootData();
    return true;
  };

  // Part B2: the least-intrusive glossary-discoverability nudge — pulse the
  // FIRST "?" marker on the page a few times on first load only (guarded by
  // localStorage so it never repeats), so a new user notices the "?" is
  // interactive without any extra banner or tip text competing for attention.
  function maybePulseFirstGloss() {
    try { if (localStorage.getItem("dlv_gloss_hint_seen") === "1") return; } catch (e) { return; }
    // Defer one frame so the freshly-painted DOM is present.
    setTimeout(() => {
      const g = document.querySelector("#dlv-root .dlv-gloss");
      if (!g) return;
      g.classList.add("dlv-gloss-pulse");
      try { localStorage.setItem("dlv_gloss_hint_seen", "1"); } catch (e) {}
      setTimeout(() => g.classList.remove("dlv-gloss-pulse"), 3600);
    }, 350);
  }

  /* campaigns.html's own init() calls route() synchronously the moment its inline
     <script> block runs — which is BEFORE this file's <script src> tag (loaded last,
     per the integration spec) has executed. On a hard load/refresh landing straight on
     #deliverability, that first route() call can't see window.renderDeliverability yet
     and falls back to renderList(), whose OWN async data loads then resolve a beat later
     and re-paint #main out from under us. Self-heal: paint immediately, then watch #main
     for a few seconds and re-assert our paint if that stale renderList() clobbers it. */
  if (location.hash.replace("#", "") === "deliverability") {
    window.renderDeliverability();
    const mainEl = document.getElementById("main");
    if (mainEl && window.MutationObserver) {
      const reassert = () => {
        if (location.hash.replace("#", "") === "deliverability" && !document.getElementById("dlv-root")) {
          window.renderDeliverability();
        }
      };
      const mo = new MutationObserver(reassert);
      mo.observe(mainEl, { childList: true });
      setTimeout(() => mo.disconnect(), 4000);
    }
  }
})();
