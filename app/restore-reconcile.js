/* ============================================================================
   restore-reconcile.js — the ONE source of truth for "which resting domains are
   due to be restored", shared by every restore surface so their numbers can
   never disagree again.

   The bug this exists to prevent (2026-07-20): the Today feed had TWO restore
   signals on TWO different clocks — a legacy "reminder-due" card counting the
   audit service's manual reminders by their own dueDate, and a "restore-due"
   card reading the rest LEDGER (first-rested + 7d), which is the same clock the
   In-warm-up list uses. They routinely disagreed ("5 restore reminders due"
   while the In-warm-up list showed 0 due now), and the 5 were blacklisted
   domains that can't be restored at all. Now every surface calls reconcile()
   below, so the banner count == the "Restore all due" button == what the list
   shows, and a blacklisted domain is never counted as "ready to restore".

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

  function overdue(dueDate, nowMs) {
    // Reminders carry an ISO calendar date ("YYYY-MM-DD"). "Due today or
    // overdue" == its end-of-day is at/behind now. Compare on the same UTC
    // calendar day the rest of the tab uses (todayISO()).
    if (!dueDate) return false;
    var today = new Date(nowMs).toISOString().slice(0, 10);
    return String(dueDate).slice(0, 10) <= today;
  }

  /* Given the resting ledger, the blacklist, the open manual reminders and
     "now", return the single split every restore surface agrees on:

       dueDomains      resting domains whose due-back has arrived AND that can
                       actually be restored (NOT blacklisted). This is exactly
                       what the In-warm-up "Restore all due" button acts on and
                       what the Today restore card headlines.
       upcomingDomains resting domains still inside their warm-up window.
       blockedDomains  domains that ARE due (ledger-due, or an overdue manual
                       reminder) but are blacklisted, so they CANNOT be restored
                       — surfaced honestly ("delist first"), never counted as
                       ready-to-restore. This is where the old phantom "5 due"
                       correctly lands instead of nagging you to restore burned
                       domains.

     opts = { restDue: {domain: dueBackMs}, blacklist: Set|Array<domain>,
              reminders: [{domains, dueDate, done}], now: ms } */
  function reconcile(opts) {
    opts = opts || {};
    var restDue = opts.restDue || {};
    var now = opts.now != null ? opts.now : Date.now();
    var bl = toSet(opts.blacklist);
    var reminders = Array.isArray(opts.reminders) ? opts.reminders : [];

    var due = new Set(), upcoming = new Set(), blocked = new Set();

    Object.keys(restDue).forEach(function (raw) {
      var t = restDue[raw];
      if (t == null) return;
      var dom = String(raw).toLowerCase();
      if (t > now) { upcoming.add(dom); return; }
      // Due by the ledger clock — but a blacklisted domain can't be restored.
      if (bl.has(dom)) blocked.add(dom);
      else due.add(dom);
    });

    // Overdue manual reminders whose domain is blacklisted (and isn't already
    // represented as ledger-due) land in "blocked" — they are the real reason a
    // reminder can sit overdue forever: the domain is listed and restore 409s
    // it. A non-blacklisted overdue reminder for a resting domain is already
    // covered by the ledger pass above; one for a domain that isn't resting at
    // all has nothing to restore, so it is intentionally not counted as due.
    reminders.forEach(function (r) {
      if (!r || r.done || !overdue(r.dueDate, now)) return;
      (r.domains || []).forEach(function (raw) {
        var dom = String(raw).toLowerCase();
        if (bl.has(dom) && !due.has(dom)) blocked.add(dom);
      });
    });

    return {
      dueDomains: Array.from(due),
      upcomingDomains: Array.from(upcoming),
      blockedDomains: Array.from(blocked),
    };
  }

  return { reconcile: reconcile, _overdue: overdue };
});
