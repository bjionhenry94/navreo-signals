# Campaigns Homepage Redesign — Simulated Tester Panel Results

Target: `https://navreo-signals.onrender.com/app/campaigns.html` (tested via the authenticated prod-mirror proxy).
Panel: 8 simulated user-testers (mix of go-to-market engineers and non-technical founders), each attempting 3 core tasks:
- **(a)** find a given campaign's performance
- **(b)** reach a source's underlying list from inside a campaign
- **(c)** spin up a new campaign (reach the creation flow's final create step)

Gate: all 24 task attempts succeed AND average intuitiveness ≥ 8/10.

---

## Recon rounds (drove the fixes; not part of the final scored panel)

**R1 — Maya (GTM engineer)** · build `43d8574` · intuitiveness **6/10**
- Found: (1) list rows showed the platform target name, not the campaign's own title → searching the real name returned nothing; (2) the campaign search box re-rendered the page and stole input focus. Both FIXED in `3bdee77` (rows now show `title → target`, both names searchable; search is a pure DOM visibility toggle, focus retained).
- Praise: source "View list ↗ (reuse in another campaign)" affordance excellent; performance dashboard rich; wizard flow sensible; paused-by-default safe.

**R2 — Priya (non-technical SaaS founder)** · build `3bdee77` · intuitiveness **5/10**
- Found: New-campaign wizard idea-selection step gave no visible confirmation when an idea was picked (pale bg tint only). FIXED in `175c885` (filled orange checkbox + "✓ selected" pill per selected row + "tap a row to select it" lead text).
- Also noted: homepage subtitle jargon-heavy for a total newcomer; collective "—" tiles read as "broken" (they are honest empty states). Left as-is (truthful; primary audience is GTM).
- All 3 tasks still succeeded; search + reuse affordance praised as obvious.

---

## Final scored panel — build `175c885`

_(populated below once the 8 fresh testers complete on the deployed fix build)_
