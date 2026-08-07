// chat-mirror-lab replay timeline (Step 1) · 2026-07-27
// A scripted ~90-second session the prototypes replay hands-free. Events are
// exactly what the live wire would carry: focus signals + run patches. The
// driver below is generic; REPLAY_RUN is injected at build time from the
// launch lab's frozen lab-run.json (4 ideas incl. targeting blocks).

const REPLAY_EVENTS = [
  { at: 0,     kind: "focus", focus: { ideaId: null, view: "board", note: "Reading your board" } },
  { at: 5000,  kind: "focus", focus: { ideaId: "growth-hiring", view: "targeting", note: "Opening the targeting" } },
  { at: 11000, kind: "run",   patch: { id: "growth-hiring", dropRole: "Account Executive" },
               focus: { ideaId: "growth-hiring", view: "targeting", note: "Removing Account Executive" } },
  { at: 19000, kind: "run",   patch: { id: "growth-hiring", addRole: "Marketing Director" },
               focus: { ideaId: "growth-hiring", view: "targeting", note: "Adding Marketing Director" } },
  { at: 27000, kind: "focus", focus: { ideaId: "growth-hiring", view: "emails", note: "Writing your emails" } },
  { at: 35000, kind: "run",   patch: { id: "growth-hiring",
                 pain: "You are about to pay six figures for a growth hire who then spends a quarter warming up before a single meeting lands." },
               focus: { ideaId: "growth-hiring", view: "emails", note: "Sharpening version A" } },
  { at: 46000, kind: "focus", focus: { ideaId: "growth-hiring", view: "opener", note: "Choosing the opener" } },
  { at: 55000, kind: "focus", focus: { ideaId: "growth-hiring", view: "checks", note: "Running the checks" } },
  { at: 62000, kind: "focus", focus: { ideaId: "growth-hiring", view: "checks", note: "Emails double-checked, all good" } },
  { at: 69000, kind: "focus", focus: { ideaId: "growth-hiring", view: "building", note: "Double-checking the list behind the scenes" } },
  { at: 80000, kind: "focus", focus: { ideaId: "growth-hiring", view: "signoff", note: "Ready for your sign-off" } },
  { at: 88000, kind: "focus", focus: { ideaId: null, view: "board", note: "All yours - launch when ready" } }
];

// Generic driver: the page's follower owns HOW things move; this only feeds it.
// applyPatch mutates a copy of the run the same way chat-side edits would, then
// hands the whole run to LIVE.applyRun (source-of-truth semantics preserved).
function replayStart() {
  if (window.__replayTimers) window.__replayTimers.forEach(clearTimeout);
  window.__replayTimers = [];
  const speed = window.REPLAY_SPEED || 1; // tests fast-forward; people watch at 1
  const run = JSON.parse(JSON.stringify(REPLAY_RUN));
  LIVE.updated = "replay-0";
  LIVE.applyRun(run); renderAll(); LIVE.ready();
  REPLAY_EVENTS.forEach((ev, n) => {
    window.__replayTimers.push(setTimeout(() => {
      const applyPatch = () => {
        const idea = run.ideas.find(i => i.id === ev.patch.id);
        if (idea) {
          if (ev.patch.dropRole) {
            idea.targeting.roles = idea.targeting.roles.filter(r => r !== ev.patch.dropRole);
            idea.net = Math.round(idea.net * 0.87);
          }
          if (ev.patch.addRole) {
            idea.targeting.roles = idea.targeting.roles.concat([ev.patch.addRole]);
            idea.net = Math.round(idea.net * 1.09);
          }
          if (ev.patch.pain) idea.pain = ev.patch.pain;
        }
        LIVE.updated = "replay-" + (n + 1);
        LIVE.applyRun(run);
        if (!MIRROR.holdingFocus()) renderAll();
      };
      if (ev.patch) {
        // M3's spotlight pre-animates the element about to change (chip fade);
        // other styles return 0 and the patch lands immediately
        const lead = (MIRROR.beforePatch ? MIRROR.beforePatch(ev.patch) : 0) || 0;
        if (lead) window.__replayTimers.push(setTimeout(applyPatch, lead / speed));
        else applyPatch();
      }
      if (ev.focus) MIRROR.applyFocus({ ...ev.focus, ts: "replay-f" + n });
    }, ev.at / speed));
  });
}
