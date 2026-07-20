/* ============================================================================
   restore-reconcile.js — the ONE source of truth for "which resting domains are
   due to be restored", shared by every restore surface so their numbers can
   never disagree again.

   The bug this exists to prevent (2026-07-20): the Today feed had TWO restore
   signals on TWO different clocks — a legacy "reminder-due" card counting the
   audit service's manual reminders by their own dueDate, and a "restore-due"
   card reading the rest LEDGER (first-rested + 7d), which is the same clock the
   In-warm-up list uses. They routinely disagreed ("5 restore reminders due"
   while the In-warm-up list showed 0 due now). Now every surface calls
   reconcile() below, so the banner count == the "Restore all due" button ==
   what the list shows.

   Blacklist policy (owner ruling 2026-07-15): a blocklist hit FLAGS, it never
   BLOCKS. A blacklisted domain is restorable like any other — it stays in
   dueDomains and is merely reported in blacklistedDue so the UI can show it.
   (An earlier 2026-07-20 pass excluded blacklisted domains from restore; that
   reintroduced a block the owner had removed, and was reverted to flag-only.)

   Pure + dependency-free so it runs identically in the browser (window.
   RestoreReconcile) and in a Node mock test (require/import).
   ========================================================================== */
;(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.RestoreReconcile = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function toSet(x) {
    if (x instanceof Set) {
      var s = new Set();
      x.forEach(function (d) { s.add(String(d).toLowerCase()); });
      return s;
    }
    var out = new Set();
    (Array.isArray(x) ? x : []).forEach(function (d) { out.add(String(d).toLowerCase()); });
    return out;
  }

  /* Given the resting ledger, the blacklist and "now", return the single split
     every restore surface agrees on:

       dueDomains      resting domains whose due-back has arrived — ALL of them.
                       This is exactly what the In-warm-up "Restore all due"
                       button acts on and what the Today restore card headlines,
                       so the count can never disagree with the list.
       upcomingDomains resting domains still inside their warm-up window.
       blacklistedDue  the subset of dueDomains that is currently blacklisted.
                       Owner ruling 2026-07-15: a blocklist hit FLAGS, it never
                       blocks — the backend restore-live resumes a listed domain
                       and just reports the listing. So a blacklisted domain is
                       restorable like any other (it stays IN dueDomains) and is
                       merely noted here so the UI can show it without stopping
                       the restore.

     opts = { restDue: {domain: dueBackMs}, blacklist: Set|Array<domain>, now: ms } */
  function reconcile(opts) {
    opts = opts || {};
    var restDue = opts.restDue || {};
    var now = opts.now != null ? opts.now : Date.now();
    var bl = toSet(opts.blacklist);

    var due = new Set(), upcoming = new Set(), flagged = new Set();

    Object.keys(restDue).forEach(function (raw) {
      var t = restDue[raw];
      if (t == null) return;
      var dom = String(raw).toLowerCase();
      if (t > now) { upcoming.add(dom); return; }
      // Due by the ledger clock. Blacklist flags, never blocks — every due
      // domain is restorable; a listed one is additionally noted below.
      due.add(dom);
      if (bl.has(dom)) flagged.add(dom);
    });

    return {
      dueDomains: Array.from(due),
      upcomingDomains: Array.from(upcoming),
      blacklistedDue: Array.from(flagged),
    };
  }

  return { reconcile: reconcile };
});
