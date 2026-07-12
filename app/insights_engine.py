"""Daily insight engine for the Today homepage.

GET /api/insights serves {date, widgets:[{tag,type,data,caption,act,prompt,wide?}]}.
Metrics come from one Supabase RPC (insights_metrics); this module shapes them
into widgets, enforces the never-repeat ledger (insights_shown, per-recipe
cooldowns), and caches one payload per day (insights_daily) so the numbers are
stable all day and survive server restarts. Times stay UTC in the payload —
the page rotates them into the viewer's timezone.
"""
import datetime
import sys

DB = "Supabase project fnykldftbkrccihdjayl"
LILLY = f"Use the lilly-data skill ({DB})."

# how many days before the same insight key may reappear
COOLDOWN = {
    "unanswered": 2, "gone_cold": 5, "ooo": 3, "wrong_person": 3,
    "hour_window": 21, "weekday": 21, "followup_share": 30,
    "collisions": 10, "wow": 6, "negratio": 21, "zeropos": 14, "hot": 10,
}


def _pct(a, b):
    return int(round(100.0 * a / b)) if b else 0


def _c(key, score, widget):
    widget.setdefault("wide", False)
    return {"key": key, "score": score, "widget": widget}


def build_candidates(m):
    out = []

    u = m.get("unanswered") or {}
    if (u.get("waiting") or 0) > 0:
        w, t, mr = u["waiting"], u["total"], u.get("waiting_meetings") or 0
        out.append(_c("unanswered", 100 + w, {
            "tag": "Unanswered · conversion", "type": "fraction",
            "data": {"num": w, "of": t, "ofLabel": f"of {t} positives, last 30 days",
                     "color": "var(--orange)"},
            "caption": f"<b>{w} warm replies, no answer from us.</b> {mr} asked for a meeting.",
            "act": f"Clear the {mr} meeting requests first." if mr else "Clear the oldest ten today.",
            "prompt": (f"{LILLY} Finding from my Navreo Today dashboard: {w} of {t} positive replies "
                       f"in the last 30 days have had no answer from us - {mr} are meeting requests. "
                       "Rebuild the list (positive categories in the replies table with no later "
                       "sent_messages row for the same email), show every waiting lead with days "
                       "waiting and reply text, prioritise meeting requests, then draft a short reply "
                       "for each in my voice (Bjion, Navreo) and stage them for approval in Smartlead.")}))

    gc = m.get("gone_cold") or 0
    if gc >= 50:
        out.append(_c("gone_cold", 90, {
            "tag": "Left to go cold · conversion", "type": "fraction", "wide": True,
            "data": {"num": gc, "of": gc, "ofLabel": "said yes, then heard nothing for 14+ days",
                     "color": "var(--orange)"},
            "caption": f"<b>{gc} leads replied positively and never heard from us again.</b> All-time, still unsuppressed.",
            "act": "Stage a revival campaign this week.",
            "prompt": (f"{LILLY} Finding: {gc} leads across all time replied positively and never "
                       "received another message - their reply is 14+ days old with no later "
                       "sent_messages row. Rebuild the list with last-reply date, campaign and reply "
                       "text, check suppressions, segment by how they said yes, then design a revival "
                       "campaign that picks each conversation back up and stage it in Smartlead for my approval.")}))

    o = m.get("ooo") or {}
    if (o.get("with_date") or 0) >= 20:
        out.append(_c("ooo", 70 + o["with_date"] // 10, {
            "tag": "Hidden pipeline · conversion", "type": "ring",
            "data": {"num": o["with_date"], "of": o["total"]},
            "caption": f"<b>{o['with_date']} out-of-office replies name a return date.</b> A free follow-up calendar.",
            "act": "Queue a touch for the day after each return.",
            "prompt": (f"{LILLY} Finding: {o['with_date']} of this week's {o['total']} Out Of Office "
                       "replies contain a return date. Pull them from the replies table, parse each "
                       "body for the stated return date, build the follow-up calendar (lead, campaign, "
                       "return date) and stage day-after welcome-back touches for my approval.")}))

    wp = m.get("wrong_person") or {}
    if (wp.get("with_pointer") or 0) >= 10:
        out.append(_c("wrong_person", 70, {
            "tag": "Hidden pipeline · conversion", "type": "fraction",
            "data": {"num": wp["with_pointer"], "of": wp["total"], "ofLabel": "",
                     "color": "var(--ink)", "small": True},
            "caption": f"<b>{_pct(wp['with_pointer'], wp['total'])}% of &quot;wrong person&quot; replies name the right one.</b>",
            "act": "New thread: “your colleague suggested I ask you.”",
            "prompt": (f"{LILLY} Finding: {wp['with_pointer']} of {wp['total']} Wrong Person replies "
                       "this week point at the right contact. Pull them, extract the referred "
                       "name/role/email from each body, enrich missing emails via "
                       "lilly-decision-maker-finder, and prepare a referral campaign whose opener "
                       "says their colleague suggested I reach out. Show me the list before creating "
                       "anything in Smartlead.")}))

    hist = m.get("hour_hist") or []
    if len(hist) == 24 and sum(hist) >= 100:
        best_start, best_sum = 0, -1
        for h in range(24):
            s = sum(hist[(h + i) % 24] for i in range(4))
            if s > best_sum:
                best_start, best_sum = h, s
        share = _pct(best_sum, sum(hist))
        if share >= 35:
            out.append(_c("hour_window", 60, {
                "tag": "Timing · conversion", "type": "pulse24",
                "data": {"values": hist, "utc": True,
                         "hotFrom": best_start, "hotTo": (best_start + 3) % 24},
                "caption": ("<b>" + str(share) + "% of positives arrive between {{hotStart}} and {{hotEnd}} {{tz}}.</b>"),
                "act": "Hold a daily {{hotStart}} {{tz}} reply block.",
                "prompt": (f"{LILLY} Finding: {share}% of our positive replies arrive between "
                           "{{hotStart}} and {{hotEnd}} {{tz}} (reply-hour histogram of the replies "
                           "table, last 45 days; stored UTC). Verify the histogram in my timezone, "
                           "then set up my daily reply block: a recurring {{hotStart}} {{tz}} calendar "
                           "hold plus a checklist pulling that day's unanswered positives from Smartlead.")}))

    wd = m.get("weekday") or []
    rates = [(d["dow"], 1000.0 * d["pos"] / d["sends"]) for d in wd if d.get("sends")]
    if len(rates) == 5:
        vals = [round(r) for _, r in rates]
        hi, lo = vals.index(max(vals)), vals.index(min(vals))
        if min(vals) and max(vals) / min(vals) >= 1.3:
            lift = _pct(max(vals) - min(vals), min(vals))
            names = ["MON", "TUE", "WED", "THU", "FRI"]
            out.append(_c("weekday", 55, {
                "tag": "Timing · conversion", "type": "bars",
                "data": {"items": [{"label": names[i], "v": vals[i]} for i in range(5)],
                         "hotIdx": hi, "lowIdx": lo, "unit": "positives per 1k sends"},
                "caption": f"<b>{names[hi].title()} converts {lift}% better than {names[lo].title()}.</b> Positives per 1k sends, last 4 weeks.",
                "act": f"Shift {names[lo].title()} volume into {names[hi].title()}.",
                "prompt": (f"{LILLY} Finding: over the last 4 weeks {names[hi].title()} produces about "
                           f"{vals[hi]} positives per 1k sends versus {names[lo].title()}'s {vals[lo]} "
                           "(sent_messages vs positive replies by weekday - a proxy). Validate it by "
                           "attributing each positive to the send-day of the message it answered; if it "
                           "holds, rebalance the Smartlead schedules and show me the diff before applying.")}))

    fs = m.get("followup_share") or {}
    if (fs.get("total") or 0) >= 100:
        pct = _pct(fs["followup"], fs["total"])
        if pct >= 25:
            out.append(_c("followup_share", 50, {
                "tag": "Sequence depth · conversion", "type": "ring",
                "data": {"num": fs["followup"], "of": fs["total"], "show": f"{pct}%"},
                "caption": f"<b>{pct}% of positives come from a follow-up, not the opener.</b>",
                "act": "No campaign ships with fewer than 3 steps.",
                "prompt": (f"{LILLY} Finding: {pct}% of positive replies in the last 45 days "
                           f"({fs['followup']} of {fs['total']}) arrived after a follow-up, not email 1. "
                           "Audit every ACTIVE Smartlead campaign's sequence length, list the ones with "
                           "fewer than 3 steps, and draft the missing follow-ups in each campaign's "
                           "existing voice for my approval.")}))

    col = m.get("collisions") or 0
    if col >= 10:
        out.append(_c("collisions", 45 + col, {
            "tag": "Collisions · deliverability", "type": "big",
            "data": {"value": str(col), "color": "var(--ink)", "sub": "leads, 2+ campaigns at once"},
            "caption": f"<b>{col} leads got emails from two of our campaigns in the same fortnight.</b>",
            "act": "Suppress cross-campaign at upload.",
            "prompt": (f"{LILLY} Finding: in the last 14 days, {col} leads received emails from two or "
                       "more of our Smartlead campaigns at once (sent_messages grouped by email with "
                       "distinct campaign ids). List every collision with both campaign names and dates, "
                       "pause the duplicate enrollment for each lead, and propose cross-campaign "
                       "suppression at upload via lilly-upload-gate as the standing fix.")}))

    wow = m.get("wow") or {}
    if (wow.get("last") or 0) >= 20:
        delta = _pct(wow["this"] - wow["last"], wow["last"])
        if abs(delta) >= 30:
            up = delta > 0
            out.append(_c("wow", 65, {
                "tag": "Momentum · conversion", "type": "big",
                "data": {"value": f"{'+' if up else ''}{delta}%",
                         "color": "var(--green)" if up else "var(--red)", "sub": "positives, week on week"},
                "caption": f"<b>Positive replies went {wow['last']} → {wow['this']} week on week.</b>",
                "act": "Find what changed and do more of it." if up else "Find what changed and stop it.",
                "prompt": (f"{LILLY} Finding: positive replies moved {wow['last']} to {wow['this']} week "
                           "on week ({delta:+d}%). Break the change down by campaign, mechanism and copy "
                           "variant to isolate what drove it, and recommend what to scale up or roll "
                           "back - with the specific Smartlead changes staged for my approval.").replace("{delta:+d}", f"{delta:+d}")}))

    for c in (m.get("campaign_week") or []):
        name, rep = (c.get("name") or "").strip(), c.get("replies") or 0
        pos, negs, dnc = c.get("pos") or 0, c.get("negs") or 0, c.get("dnc") or 0
        if not name:
            continue
        if negs >= 8 and pos * 5 <= negs:
            ratio = max(2, int(round(negs / max(pos, 1))))
            out.append(_c(f"negratio:{name}", 60 + negs, {
                "tag": "Copy fatigue · risk", "type": "big",
                "data": {"value": f"{ratio}:1", "color": "var(--red)", "sub": "nos per yes"},
                "caption": f"<b>{name} took {negs} nos for {pos} yes{'es' if pos != 1 else ''} this week</b> ({dnc} do-not-contact).",
                "act": "Pause it. Rewrite the offer first.",
                "prompt": (f"Finding on my Navreo Smartlead workspace: the campaign '{name}' produced "
                           f"{negs} negative replies ({dnc} Do Not Contact) against {pos} positives this "
                           f"week. Pull its sequence copy and this week's reply bodies (lilly-data, {DB}), "
                           "diagnose why the offer misses - audience, angle or tone - then pause the "
                           "campaign and propose a rewrite using the lilly-copywriter framework for my approval.")}))
        elif rep >= 20 and pos == 0:
            out.append(_c(f"zeropos:{name}", 55 + rep // 2, {
                "tag": "Dead angle · conversion", "type": "big",
                "data": {"value": "0", "color": "var(--red)", "sub": f"positives / {rep} replies"},
                "caption": f"<b>{name}: {rep} replies this week, none positive.</b>",
                "act": "Re-angle or retire it.",
                "prompt": (f"Finding on my Navreo Smartlead workspace: '{name}' generated {rep} replies "
                           f"this week and zero positives. Pull the reply bodies and sequence copy "
                           f"(lilly-data, {DB}), diagnose whether it's the list or the angle, and either "
                           "propose a new angle (lilly-copywriter) or recommend retiring it - with "
                           "evidence either way.")}))
        elif pos >= 8 and rep and pos / rep >= 0.25:
            share = _pct(pos, rep)
            out.append(_c(f"hot:{name}", 50 + pos, {
                "tag": "Working · double down", "type": "fraction",
                "data": {"num": pos, "of": rep, "ofLabel": f"{share}% of its replies are positive",
                         "color": "var(--green)", "small": True},
                "caption": f"<b>{name} turns {share}% of replies positive.</b> Book average is ~10%.",
                "act": "Feed it more leads while it's hot.",
                "prompt": (f"Finding on my Navreo Smartlead workspace: '{name}' converted {pos} of its "
                           f"{rep} replies to positive this week ({share}%), far above the book. Check "
                           "its remaining lead runway in Smartlead, and if it's thin, expand the same "
                           "list profile (lilly-prospeo-list-builder or lilly-ai-ark-list-builder, then "
                           "lilly-decision-maker-finder) and stage the upload through lilly-upload-gate.")}))

    return out


FAMILY_CAP = {"negratio": 2, "zeropos": 2, "hot": 2}  # keep the daily mix varied


def pick(candidates, ledger, today, n=10):
    """Ledger-aware selection: prefer keys outside their cooldown, highest
    score first, at most FAMILY_CAP per per-campaign recipe family; top up
    with the least-recently-shown if fewer than n remain."""
    def fam(key):
        return key.split(":", 1)[0]

    fresh, cooling = [], []
    for c in sorted(candidates, key=lambda x: -x["score"]):
        last = ledger.get(c["key"])
        if last is None or (today - last).days >= COOLDOWN.get(fam(c["key"]), 14):
            fresh.append(c)
        else:
            cooling.append(c)
    cooling.sort(key=lambda c: ledger.get(c["key"], datetime.date.min))
    chosen, counts = [], {}
    for pool in (fresh, cooling):
        for c in pool:
            if len(chosen) >= n:
                break
            f = fam(c["key"])
            if counts.get(f, 0) >= FAMILY_CAP.get(f, 99):
                continue
            counts[f] = counts.get(f, 0) + 1
            chosen.append(c)
    return chosen


def api_insights(sb):
    """Serve today's payload, generating and persisting it on first request."""
    today = datetime.date.today()
    iso = today.isoformat()
    try:
        row = sb("GET", f"insights_daily?day=eq.{iso}&select=payload")
        if row:
            return row[0]["payload"]
        metrics = sb("POST", "rpc/insights_metrics", {}, prefer="return=representation")
        if not isinstance(metrics, dict):
            return None
        raw = sb("GET", "insights_shown?select=key,last_shown") or []
        ledger = {r["key"]: datetime.date.fromisoformat(r["last_shown"]) for r in raw}
        chosen = pick(build_candidates(metrics), ledger, today)
        if not chosen:
            return None
        payload = {"date": today.strftime("%A %-d %B"),
                   "widgets": [c["widget"] for c in chosen]}
        sb("POST", "insights_shown",
           [{"key": c["key"], "last_shown": iso} for c in chosen],
           prefer="resolution=merge-duplicates")
        sb("POST", "insights_daily", {"day": iso, "payload": payload})
        return payload
    except Exception as e:  # noqa: BLE001 — page falls back to its embedded set
        print(f"[insights] WARNING generation failed: {type(e).__name__}: {e}",
              file=sys.stderr)
        return None
