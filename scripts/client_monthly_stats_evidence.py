"""Done-rule evidence for Step 1.

(a) sum of client_monthly_stats.sent  vs  the Analytics hub's LIFETIME Sent for
    the client — the hub's client totals are the sum of campaign_scorecard.sent
    over that client's campaigns (server._all_campaign_scorecard(), the exact
    payload /api/campaign-scorecard and the Analytics winners table consume).
(b) earliest client_monthly_stats.month  vs  the client's FIRST campaign month.

    "First campaign month" is the earlier of the contact_history seed
    (earliest first_contacted_at across the client's campaigns) and the first
    month Smartlead actually shows send volume for those campaigns. Comparing
    against the contact_history seed ALONE would be a tautology — the writer
    derives the seed from the same query — and it is also wrong for clients
    whose campaigns predate this system (see monthly_stats._first_active_month).
"""
import sys, urllib.parse
from pathlib import Path
# run from anywhere: the app package is the importable root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import server, monthly_stats

fleet = monthly_stats._client_campaigns()
sc = server._all_campaign_scorecard()["campaigns"]

def hub_lifetime_sent(label):
    ids = set(fleet[label]["ids"])
    return sum(int(c.get("sent") or 0) for cid, c in sc.items() if cid in ids)

rows_out = []
for label in sys.argv[1:]:
    q = "client_monthly_stats?select=month,sent&client=eq." + urllib.parse.quote(label) + "&order=month"
    rows = server.sb("GET", q) or []
    tot = sum(int(r["sent"]) for r in rows)
    hub = hub_lifetime_sent(label)
    delta = (tot - hub) / hub * 100 if hub else 0.0
    ent = fleet[label]
    cm = monthly_stats._contact_months(ent["ids"])
    if cm:
        seed = __import__("datetime").date.fromisoformat(min(cm))
        first_campaign_month = monthly_stats._first_active_month(
            ent["ws"], ent["ids"], seed).isoformat()
    else:
        first_campaign_month = "-"
    earliest_row = rows[0]["month"] if rows else "-"
    rows_out.append((label, fleet[label]["ws"], len(rows), f"{tot:,}", f"{hub:,}",
                     f"{delta:+.2f}%", "PASS" if abs(delta) <= 1.0 else "FAIL",
                     earliest_row, first_campaign_month,
                     "PASS" if earliest_row == first_campaign_month else "FAIL"))

hdr = ("client","workspace","months","sum monthly sent","hub lifetime sent","delta","(a)",
       "earliest row","first campaign month","(b)")
w = [max(len(str(r[i])) for r in (rows_out+[hdr])) for i in range(len(hdr))]
def line(r): return " | ".join(str(r[i]).ljust(w[i]) for i in range(len(hdr)))
print(line(hdr)); print("-+-".join("-"*x for x in w))
for r in rows_out: print(line(r))
