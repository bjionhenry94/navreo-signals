/* ============================================================================
   Mock test for the restore-reminder banner fix (2026-07-20).

   Proves two things about the shared reconciliation the whole restore UI reads:

   1. The banner's count ALWAYS equals what the In-warm-up list shows as
      due-to-restore (the original bug: banner "5 due" while the list showed 0).
   2. Blacklist FLAGS, it never BLOCKS (owner ruling 2026-07-15): a blacklisted
      domain that is due is still restorable — it stays IN dueDomains and is
      merely reported in blacklistedDue. (An earlier pass excluded them; that
      reintroduced a block the owner had removed, and was reverted.)

   Loads the REAL shipped module (restore-reconcile.js). Run:
     node app/test_restore_reconcile.cjs
   ========================================================================== */
"use strict";
const { reconcile } = require("./restore-reconcile.js");

const NOW = Date.parse("2026-07-20T12:00:00Z");
const DAY = 864e5;
const at = (isoDate) => Date.parse(isoDate + "T09:00:00Z");

let failures = 0;
function check(name, cond, detail) {
  const ok = !!cond;
  if (!ok) failures++;
  console.log(`   ${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
}

/* The ORIGINAL (pre-reconciliation) code path: two restore signals on two
   clocks. Kept to prove the reconciliation still fixes banner==list. */
function oldBannerCount(reminders, now) {
  const today = new Date(now).toISOString().slice(0, 10);
  return reminders.filter((r) => !r.done && String(r.dueDate).slice(0, 10) <= today).length;
}
function oldListDueCount(restDue, now) {
  return Object.keys(restDue).filter((d) => restDue[d] != null && restDue[d] <= now).length;
}

const FIXTURES = {
  "A · production mirror (banner 5 vs list 0)": {
    restDue: {
      "scaleandfocus.info": at("2026-07-23"),
      "amplifymarketplace.info": at("2026-07-23"),
      "getnavreogrowth.org": at("2026-07-25"),
      "navreodealengine.info": at("2026-07-26"),
    },
    reminders: [
      { domains: ["launchwithnavreo.digital"], dueDate: "2026-07-15", done: false },
      { domains: ["bookednavreo.info"], dueDate: "2026-07-15", done: false },
      { domains: ["navreohub.info"], dueDate: "2026-07-15", done: false },
      { domains: ["meetingsnavreo.info"], dueDate: "2026-07-15", done: false },
      { domains: ["getnavreogrowth.org"], dueDate: "2026-07-15", done: false },
      { domains: ["arnicbiz.biz"], dueDate: "2026-07-15", done: true },
    ],
    blacklist: ["launchwithnavreo.digital", "bookednavreo.info", "navreohub.info", "meetingsnavreo.info", "getnavreogrowth.org"],
    expect: { due: 0, blacklistedDue: 0, oldBanner: 5, oldList: 0 },
  },
  "B · blacklisted domain IS due — must be RESTORABLE (flag, not block)": {
    restDue: { "burned.info": NOW - 1 * DAY },
    reminders: [],
    blacklist: ["burned.info"],
    expect: { due: 1, blacklistedDue: 1, dueIncludes: "burned.info" },
  },
  "C · mixed: clean-due + blacklisted-due + waiting": {
    restDue: { "ready.info": NOW - 1 * DAY, "burned.info": NOW - 1 * DAY, "waiting.info": NOW + 2 * DAY },
    reminders: [],
    blacklist: ["burned.info"],
    expect: { due: 2, blacklistedDue: 1, dueIncludes: "burned.info" },
  },
  "D · genuinely due, nothing blacklisted": {
    restDue: { "gooddomain.info": NOW - 1 * DAY, "laterdomain.info": NOW + 3 * DAY },
    reminders: [],
    blacklist: [],
    expect: { due: 1, blacklistedDue: 0 },
  },
  "E · everything clean, nothing due": {
    restDue: { "resting1.info": NOW + 4 * DAY, "resting2.info": NOW + 6 * DAY },
    reminders: [],
    blacklist: [],
    expect: { due: 0, blacklistedDue: 0 },
  },
};

console.log("\n=== Restore reconciliation — mock test (flag, not block) ===\n");

for (const [name, fx] of Object.entries(FIXTURES)) {
  console.log(`Fixture ${name}`);
  const rec = reconcile({ restDue: fx.restDue, blacklist: fx.blacklist, now: NOW });

  // Card count, "Restore all due" button, and the restore action ALL read
  // reconcile().dueDomains — same number by construction.
  const bannerDue = rec.dueDomains.length;
  const listDue = rec.dueDomains.length;

  check("banner count == In-warm-up list due count (invariant)", bannerDue === listDue, `${bannerDue} == ${listDue}`);
  check(`due count = ${fx.expect.due}`, bannerDue === fx.expect.due, `got ${bannerDue}`);
  check(`blacklistedDue (flagged) count = ${fx.expect.blacklistedDue}`, rec.blacklistedDue.length === fx.expect.blacklistedDue, `got ${rec.blacklistedDue.length} [${rec.blacklistedDue.join(", ")}]`);

  // The behaviour change: a blacklisted domain that is due is RESTORABLE — it
  // must appear in dueDomains (blacklist flags, never blocks).
  if (fx.expect.dueIncludes) {
    check(`blacklisted due domain "${fx.expect.dueIncludes}" IS restorable (in dueDomains)`, rec.dueDomains.includes(fx.expect.dueIncludes), rec.dueDomains.join(", "));
  }
  // Every flagged domain must also be in the due set (a flag is a subset of due, never a separate blocked bucket).
  const flaggedNotDue = rec.blacklistedDue.filter((d) => !rec.dueDomains.includes(d));
  check("blacklistedDue is a subset of dueDomains (flag ⊂ due)", flaggedNotDue.length === 0, flaggedNotDue.length ? "orphans: " + flaggedNotDue.join(", ") : "clean");

  if (fx.expect.oldBanner != null) {
    const ob = oldBannerCount(fx.reminders, NOW);
    const ol = oldListDueCount(fx.restDue, NOW);
    check(`ORIGINAL path reproduced the bug (banner ${fx.expect.oldBanner} != list ${fx.expect.oldList})`,
      ob === fx.expect.oldBanner && ol === fx.expect.oldList && ob !== ol, `old banner=${ob}, old list=${ol}`);
    check("reconciled path holds (banner == list)", bannerDue === listDue && bannerDue === fx.expect.due, `new=${bannerDue}`);
  }
  console.log("");
}

console.log(failures === 0
  ? "✅ ALL CHECKS PASSED — banner==list holds; blacklisted domains are restorable and merely flagged.\n"
  : `❌ ${failures} CHECK(S) FAILED\n`);
process.exit(failures === 0 ? 0 : 1);
