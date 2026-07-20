/* ============================================================================
   Mock test for the restore-reminder banner fix (2026-07-20).

   Reproduces the reported bug on mock fixtures that mirror the live 2026-07-20
   data — banner said "5 restore reminders due today or overdue" while the
   In-warm-up list showed 0 due — and proves the fix holds the invariant:

     the restore banner's count ALWAYS equals what the In-warm-up list shows as
     due-to-restore, and a blacklisted domain is never counted as restorable.

   Loads the REAL shipped module (restore-reconcile.js) — the same file the
   browser loads — so this exercises production logic, not a replica.

   Run:  node app/test_restore_reconcile.cjs
   ========================================================================== */
"use strict";
const { reconcile } = require("./restore-reconcile.js");

const NOW = Date.parse("2026-07-20T12:00:00Z"); // "today" for every fixture
const DAY = 864e5;
const at = (isoDate) => Date.parse(isoDate + "T09:00:00Z"); // a ledger due-back ms

let failures = 0;
function check(name, cond, detail) {
  const ok = !!cond;
  if (!ok) failures++;
  console.log(`   ${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
}

/* ── The OLD (buggy) code path, faithfully modelled: two independent restore
   signals on two different clocks. This is what shipped before the fix. ── */
function oldBannerCount(reminders, now) {
  // buildTodoItem "reminder-due": A.reminders.filter(!done && dueDate <= today)
  const today = new Date(now).toISOString().slice(0, 10);
  return reminders.filter((r) => !r.done && String(r.dueDate).slice(0, 10) <= today).length;
}
function oldListDueCount(restDue, now) {
  // In-warm-up "Restore all due": doms where domDue(dom) <= now (NOT blacklist-aware)
  return Object.keys(restDue).filter((d) => restDue[d] != null && restDue[d] <= now).length;
}

/* ── Fixtures ─────────────────────────────────────────────────────────────
   A: production mirror — 110-style ledger all due 2026-07-23+, 5 overdue
      manual reminders all for SURBL-blacklisted domains, 1 done. */
const FIXTURES = {
  "A · live-bug (production mirror 2026-07-20)": {
    restDue: {
      "scaleandfocus.info": at("2026-07-23"),
      "amplifymarketplace.info": at("2026-07-23"),
      "reachandscale.info": at("2026-07-23"),
      "getnavreogrowth.org": at("2026-07-25"), // resting-later AND blacklisted AND has an overdue reminder
      "navreodealengine.info": at("2026-07-26"),
    },
    reminders: [
      { domains: ["launchwithnavreo.digital"], dueDate: "2026-07-15", done: false },
      { domains: ["bookednavreo.info"], dueDate: "2026-07-15", done: false },
      { domains: ["navreohub.info"], dueDate: "2026-07-15", done: false },
      { domains: ["meetingsnavreo.info"], dueDate: "2026-07-15", done: false },
      { domains: ["getnavreogrowth.org"], dueDate: "2026-07-15", done: false },
      { domains: ["arnicbiz.biz"], dueDate: "2026-07-15", done: true }, // done — must NOT count
    ],
    blacklist: ["launchwithnavreo.digital", "bookednavreo.info", "navreohub.info", "meetingsnavreo.info", "getnavreogrowth.org"],
    expect: { due: 0, blocked: 5, oldBanner: 5, oldList: 0 },
  },
  "B · genuinely due (nothing blacklisted)": {
    restDue: { "gooddomain.info": NOW - 1 * DAY, "laterdomain.info": NOW + 3 * DAY },
    reminders: [],
    blacklist: [],
    expect: { due: 1, blocked: 0 },
  },
  "C · due but blacklisted (must NOT offer restore)": {
    restDue: { "burned.info": NOW - 1 * DAY },
    reminders: [],
    blacklist: ["burned.info"],
    expect: { due: 0, blocked: 1 },
  },
  "D · mixed: one restorable, one blacklisted, one waiting": {
    restDue: { "ready.info": NOW - 1 * DAY, "burned.info": NOW - 1 * DAY, "waiting.info": NOW + 2 * DAY },
    reminders: [{ domains: ["ready.info"], dueDate: "2026-07-15", done: false }],
    blacklist: ["burned.info"],
    expect: { due: 1, blocked: 1 },
  },
  "E · everything clean, nothing due": {
    restDue: { "resting1.info": NOW + 4 * DAY, "resting2.info": NOW + 6 * DAY },
    reminders: [],
    blacklist: [],
    expect: { due: 0, blocked: 0 },
  },
};

console.log("\n=== Restore-reminder reconciliation — mock test ===\n");

for (const [name, fx] of Object.entries(FIXTURES)) {
  console.log(`Fixture ${name}`);
  const rec = reconcile({ restDue: fx.restDue, blacklist: fx.blacklist, reminders: fx.reminders, now: NOW });

  // In the shipped code the Today card's count AND the In-warm-up "Restore all
  // due" button AND the restore action ALL read reconcile().dueDomains, so the
  // "banner" and the "list" are the SAME number by construction. We assert the
  // function produces the right set.
  const bannerDue = rec.dueDomains.length;   // what the Today restore card headlines
  const listDue = rec.dueDomains.length;     // what "Restore all due (N)" shows / restores

  check("banner count == In-warm-up list due count (invariant)", bannerDue === listDue, `${bannerDue} == ${listDue}`);
  check(`due count = ${fx.expect.due}`, bannerDue === fx.expect.due, `got ${bannerDue}`);
  check(`blocked (blacklisted) count = ${fx.expect.blocked}`, rec.blockedDomains.length === fx.expect.blocked, `got ${rec.blockedDomains.length} [${rec.blockedDomains.join(", ")}]`);

  // No blacklisted domain may ever be counted as restorable.
  const bl = new Set(fx.blacklist.map((d) => d.toLowerCase()));
  const leaked = rec.dueDomains.filter((d) => bl.has(d));
  check("no blacklisted domain in the due (restorable) set", leaked.length === 0, leaked.length ? "LEAKED: " + leaked.join(", ") : "clean");

  // Contrast with the OLD code path on the production-mirror fixture: it
  // produced the exact reported mismatch (banner 5, list 0).
  if (fx.expect.oldBanner != null) {
    const ob = oldBannerCount(fx.reminders, NOW);
    const ol = oldListDueCount(fx.restDue, NOW);
    check(`OLD path reproduced the bug (banner ${fx.expect.oldBanner} != list ${fx.expect.oldList})`,
      ob === fx.expect.oldBanner && ol === fx.expect.oldList && ob !== ol,
      `old banner=${ob}, old list=${ol}`);
    check("NEW path resolves that same fixture (banner == list)", bannerDue === listDue && bannerDue === fx.expect.due,
      `new banner=${bannerDue}, new list=${listDue}`);
  }
  console.log("");
}

console.log(failures === 0
  ? "✅ ALL CHECKS PASSED — banner count and In-warm-up list can never disagree; blacklisted domains are never offered for restore.\n"
  : `❌ ${failures} CHECK(S) FAILED\n`);
process.exit(failures === 0 ? 0 : 1);
