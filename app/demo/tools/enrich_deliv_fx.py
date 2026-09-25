"""Enrich the demo Analytics page (deliverability.html) fixtures so every client
reads as a realistic, running account: live campaigns with leads still to work,
new campaigns, signals, offers, who-replies + follow-ups, meetings with a prior
window, and sane bounce rates.

Reads the recorded fixtures in fx/, writes page-scoped copies to fx/deliv/ and
fx-deliv-index.js (loaded only by deliverability.html, so campaigns.html and the
setter keep their own data). Deterministic: re-run any time.

    python3 app/demo/tools/enrich_deliv_fx.py
"""
import copy, datetime as dt, hashlib, json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(HERE)
FX = os.path.join(DEMO, "fx")
OUT = os.path.join(FX, "deliv")
os.makedirs(OUT, exist_ok=True)
rnd = random.Random(20260925)

def load(name): return json.load(open(os.path.join(FX, name + ".json")))

ANCHOR = dt.date(2026, 9, 11)          # capture date of the recording
CLIENTS = ["Acme", "Brightcart", "Vellum", "Northwind", "Fieldstone", "Halden",
           "Skylark", "Ascent Capital", "Renova", "Verdant", "Meridian"]
WS = {"Halden": "halden", "Fieldstone": "fieldstone", "Meridian": "meridian"}

# headroom (new leads/day) the page derives per client × target runway days
HEADROOM = {"Acme": 15811, "Brightcart": 5251, "Vellum": 1965, "Northwind": 2882,
            "Fieldstone": 2362, "Halden": 1329, "Skylark": 1244, "Ascent Capital": 1118,
            "Renova": 955, "Verdant": 1595, "Meridian": 1892}
RUNWAY = {"Acme": 26, "Brightcart": 23, "Vellum": 17, "Northwind": 41, "Fieldstone": 33,
          "Halden": 24, "Skylark": 52, "Ascent Capital": 38, "Renova": 29, "Verdant": 36,
          "Meridian": 47}
# 30-day interested / meeting floors (Smartlead positives, hub meetings)
POS_MIN = {"Ascent Capital": 6, "Skylark": 6, "Halden": 5, "Verdant": 4, "Renova": 6, "Meridian": 6}
MTG_ADD = {"Fieldstone": 3, "Halden": 1, "Skylark": 1, "Renova": 1, "Verdant": 1,
           "Meridian": 1, "Vellum": 1, "Northwind": 1}
BOUNCE_TARGET = {"Halden": 2.3, "Vellum": 2.4, "Ascent Capital": 1.7}   # % of sent

cw = load("329ecbd1bd")
hub = load("5a82b1670d")
score = load("2e5a4efbbd")
uni = load("8a3817377b")
sig = load("0a6f535b22")
ins = load("798544d2da")
who_all = load("ece27a1d98")
who_acme = load("b301b4eeb3")

def camps(R, client):
    return sorted([r for r in cw["campaigns"][R] if r["client"] == client], key=lambda r: -r["sent"])

# ── 0. Meridian sends ~1.8x (was 12% of capacity; too thin to price an offer) ──
MF = 1.8
for R in ("7", "14", "30"):
    w = cw["windows"][R]["Meridian"]
    for m in ("sent", "replied", "bounced"):
        add = round(w[m] * (MF - 1)); w[m] += add; cw["windows"][R]["__all"][m] += add
    for r in camps(R, "Meridian"):
        for m in ("sent", "replied", "bounced"): r[m] = round(r[m] * MF)
for m in ("sent", "replied", "bounced"):
    arr = cw["series"]["Meridian"][m]
    for i, v in enumerate(arr):
        add = round(v * (MF - 1)); arr[i] += add; cw["series"]["__all"][m][i] += add
for k in ("Meridian", "__all"):
    if "Meridian" in cw["first_touch"] and k == "Meridian":
        ft = cw["first_touch"]["Meridian"]; ft["total14"] = round(ft["total14"] * MF); ft["ft14"] = round(ft["total14"] * .45)
for i, v in enumerate(hub["series"]["Meridian"]["replies"]):
    add = round(v * (MF - 1)); hub["series"]["Meridian"]["replies"][i] += add; hub["series"]["__all"]["replies"][i] += add

# ── 1. bounces: bring the outliers back to realistic levels ──────────────────
for c, tgt in BOUNCE_TARGET.items():
    for R in ("7", "14", "30"):
        w = cw["windows"][R][c]
        new = round(w["sent"] * tgt / 100 * rnd.uniform(0.93, 1.07))
        f = new / w["bounced"] if w["bounced"] else 1
        cw["windows"][R]["__all"]["bounced"] -= w["bounced"] - new
        w["bounced"] = new
        for r in camps(R, c): r["bounced"] = round(r["bounced"] * f)
    s = cw["series"][c]
    f = (cw["windows"]["30"][c]["bounced"] / max(1, sum(s["bounced"])))
    for i, b in enumerate(s["bounced"]):
        nb = round(b * f); cw["series"]["__all"]["bounced"][i] -= b - nb; s["bounced"][i] = nb

# ── 2. interested + meetings for thin clients ────────────────────────────────
days = hub["days"]
weekdays = [i for i, d in enumerate(days) if dt.date.fromisoformat(d[:10]).weekday() < 5]
for c in CLIENTS:
    need = POS_MIN.get(c, 0) - cw["windows"]["30"][c]["positives"]
    if need > 0:
        cs = camps("30", c)[:4]
        idx = rnd.sample(weekdays[-26:], need)
        for n, i in enumerate(idx):
            for key in (c, "__all"): hub["series"][key]["interested"][i] += 1
            back = len(days) - i                      # days before anchor
            for R in ("7", "14", "30"):
                if back <= int(R):
                    cw["windows"][R][c]["positives"] += 1; cw["windows"][R]["__all"]["positives"] += 1
                    tgt = camps(R, c)[n % max(1, min(4, len(camps(R, c))))] if camps(R, c) else None
                    if tgt: tgt["pos"] += 1
            cw["series"][c]["positives"][i] += 1
    for n in range(MTG_ADD.get(c, 0)):
        i = rnd.choice(weekdays[-24:])
        for key in (c, "__all"): hub["series"][key]["meetings"][i] += 1
        back = len(days) - i
        for R in ("7", "14", "30"):
            cs = [r for r in camps(R, c) if r["pos"] > 0] or camps(R, c)
            if back <= int(R) and cs: cs[n % len(cs)]["mtg"] += 1

lat_seed = {"Fieldstone": (95, .42), "Halden": (240, .3), "Skylark": (180, .35), "Ascent Capital": (55, .6), "Meridian": (130, .4), "Verdant": (210, .33), "Brightcart": (340, .31), "Northwind": (260, .33)}
for c, (m, fs) in lat_seed.items():
    hub["latency"][c] = {"n": max(3, cw["windows"]["30"][c]["positives"]), "avg_mins": m, "fast_share": fs}

# campaigns-unified labels a row by workspace (or an Acme-workspace keyword)
UWS = {"Brightcart": "brightcart", "Northwind": "northwind", "Renova": "renova",
       "Verdant": "verdant", "Ascent Capital": "ascent-capital"}
cw["ws_labels"]["Ascent Capital"] = "ascent-capital"

# ── 3. scorecard: live campaigns with leads still to work ────────────────────
for c in CLIENTS:
    live = [r for r in camps("30", c) if r["sent"] >= 150][: (6 if c == "Acme" else 3 if len(camps("30", c)) > 3 else 2)]
    if c == "Acme":   # keep the recorded five, add the busiest window campaigns
        live = [r for r in live if r["id"] not in score["campaigns"]][:3]
        base = sum(max(0, v["total"] - v["completed"]) for v in score["campaigns"].values())
    else:
        base = 0
    left = HEADROOM[c] * RUNWAY[c] + rnd.randint(0, HEADROOM[c] // 2) - base
    tot_sent = sum(r["sent"] for r in live) or 1
    for r in live:
        share = round(left * r["sent"] / tot_sent)
        completed = round(r["sent"] * rnd.uniform(.35, .45))
        score["campaigns"][r["id"]] = {
            "sent": round(r["sent"] * rnd.uniform(1.3, 1.8)), "replied": round(r["replied"] * 1.5),
            "positives": round(r["pos"] * 1.5), "bounced": round(r["bounced"] * 1.5),
            "completed": completed, "total": completed + share, "not_started": round(share * .72),
            "inprogress": round(share * .28), "paused": rnd.randint(0, 9), "blocked": rnd.randint(10, 90),
            "stopped": 0, "status": "ACTIVE", "client": c, "name": r["name"],
            "workspace": WS.get(c, "acme"), "ws_label": "", "meetings": r["mtg"]}
        # campaigns-unified row → "live right now" and "new campaigns"
        age = rnd.choice([4, 9, 13, 18, 23, 27]) if r is live[-1] or (c == "Acme" and r is live[0]) else rnd.randint(34, 80)
        created = dt.datetime.combine(ANCHOR - dt.timedelta(days=age), dt.time(rnd.randint(8, 17), rnd.randint(0, 59), rnd.randint(0, 59)))
        uni["rows"].append({"key": "camp-sl-" + r["id"], "platform": "smartlead", "platform_id": int(r["id"]),
            "name": r["name"], "status": "ACTIVE", "workspace": UWS.get(c, WS.get(c, "acme")), "workspace_name": c,
            "created_at": created.isoformat() + ".000Z", "draft_id": "camp-sl-" + r["id"],
            "client_id": c.lower().replace(" ", "-"), "managed": True})

# ── 4. signals: every client finds new people ────────────────────────────────
MECH = {"Brightcart": {"lookalike": 9, "engagement": 5}, "Vellum": {"hiring": 3, "engagement": 4},
        "Northwind": {"lookalike": 7, "news": 2}, "Fieldstone": {"engagement": 6, "hiring": 2},
        "Halden": {"news": 4, "followers": 2}, "Skylark": {"hiring": 5, "news": 1},
        "Ascent Capital": {"news": 3, "followers": 2}, "Renova": {"lookalike": 6, "engagement": 2},
        "Verdant": {"hiring": 3, "lookalike": 2}, "Meridian": {"engagement": 2, "news": 2}}
sdays = sig["days"]
for c, mech in MECH.items():
    old = sig["clients"].get(c, {"mech": {}})["mech"]
    out = {}
    for m, avg in mech.items():
        arr = []
        for d in sdays:
            wd = dt.date.fromisoformat(d[:10]).weekday()
            lam = avg * (0.15 if wd >= 5 else 1)
            arr.append(max(0, round(rnd.gauss(lam, lam * .55))))
        if m in old: arr = [a + b for a, b in zip(arr, old[m])]
        out[m] = arr
    for m, arr in old.items(): out.setdefault(m, arr)
    added = [sum(v[i] for v in out.values()) for i in range(len(sdays))]
    prev = sig["clients"].get(c, {}).get("all", [0] * len(sdays))
    sig["all"] = [a + b - p for a, b, p in zip(sig["all"], added, prev)]
    sig["clients"][c] = {"all": added, "mech": out}

src = load("0e95effb64")
fleet = {}
for c, mech in MECH.items():
    for m, arr in sig["clients"][c]["mech"].items():
        base = [0] * len(sdays) if c != "Vellum" or m != "hiring" else None
        if base is None: continue
        fleet[m] = [a + b for a, b in zip(fleet.get(m, [0] * len(sdays)), arr)]
LBL = {"lookalike": "Lookalikes of best customers", "engagement": "Engagers of client LinkedIn posts",
       "news": "Company news (funding, launches, expansion)", "hiring": "Companies hiring for the role",
       "followers": "New followers of competitor pages"}
for m, arr in fleet.items():
    sid = "demo-" + m
    sig["series"].insert(0, {"id": sid, "name": LBL[m], "counts": arr})
    src.append({"id": sid, "name": LBL[m], "type": m, "active": True, "mechanism": m})
sig["all"] = [sum(se["counts"][i] for se in sig["series"]) for i in range(len(sdays))]

# ── 5. offers per client, priced off the window campaigns ────────────────────
OFFERS = {"Brightcart": ["A written breakdown", "A quick call", "A short video"],
          "Vellum": ["A quick call", "A case study", "A short video"],
          "Northwind": ["A written breakdown", "A quick call"],
          "Fieldstone": ["A quick call", "A short video", "Something else"],
          "Halden": ["A written breakdown", "A quick call"],
          "Skylark": ["A case study", "A quick call"],
          "Ascent Capital": ["A quick call", "A written breakdown"],
          "Renova": ["A free sample", "A quick call"],
          "Verdant": ["A quick call", "A written breakdown"],
          "Meridian": ["A case study", "A quick call"]}
row = next(r for r in ins["insights"] if r.get("insight_key") == "offer")
for c, names in OFFERS.items():
    cs = camps("30", c)
    groups = [[] for _ in names]; sums = [0] * len(names)
    for r in cs:                                  # balance sends across offers
        k = sums.index(min(sums)); groups[k].append(r); sums[k] += r["sent"]
    rows = []
    for nm, g in zip(names, groups):
        sent = sum(r["sent"] for r in g); pos = sum(r["pos"] for r in g); mtg = sum(r["mtg"] for r in g)
        rows.append([nm, round(pos / sent * 100, 1) if sent else 0, sent, len(g),
                     round(sent / pos) if pos else None, round(sent / mtg) if mtg else None, pos, mtg,
                     [r["id"] for r in g]])
    rows.sort(key=lambda o: (o[4] is None, o[4] or 0))
    row["payload"]["by_client"][c] = rows

# ── 6. who replies + how fast + follow-ups, per client × range ──────────────
ROLE_MIX = {"Brightcart": [("Founders and CEOs", .55), ("Marketing and Growth", .25), ("Other C-level", .1), ("Other", .1)],
            "Vellum": [("Sales leaders", .5), ("Founders and CEOs", .35), ("Other C-level", .15)],
            "Northwind": [("Founders and CEOs", .5), ("Marketing and Growth", .4), ("Other", .1)],
            "Fieldstone": [("Marketing and Growth", .55), ("Founders and CEOs", .3), ("Other", .15)],
            "Halden": [("Other C-level", .5), ("Marketing and Growth", .3), ("Other", .2)],
            "Skylark": [("Other C-level", .45), ("Other", .35), ("Founders and CEOs", .2)],
            "Ascent Capital": [("Other C-level", .5), ("Founders and CEOs", .3), ("Other", .2)],
            "Renova": [("Founders and CEOs", .7), ("Marketing and Growth", .2), ("Other", .1)],
            "Verdant": [("Other C-level", .4), ("Founders and CEOs", .35), ("Other", .25)],
            "Meridian": [("Founders and CEOs", .5), ("Other C-level", .3), ("Other", .2)]}
SIZE_MIX = {"Brightcart": [.45, .35, .15, .05, 0], "Vellum": [.15, .45, .3, .1, 0], "Northwind": [.35, .4, .2, .05, 0],
            "Fieldstone": [.2, .45, .3, .05, 0], "Halden": [0, .1, .35, .35, .2], "Skylark": [0, .15, .35, .35, .15],
            "Ascent Capital": [.05, .35, .4, .15, .05], "Renova": [.55, .35, .1, 0, 0], "Verdant": [.1, .3, .35, .2, .05],
            "Meridian": [.25, .4, .25, .1, 0], "Acme": None}
SPEED = {"Brightcart": (212, .07), "Vellum": (96, .18), "Northwind": (171, .1), "Fieldstone": (64, .24),
         "Halden": (246, .06), "Skylark": (158, .12), "Ascent Capital": (41, .31), "Renova": (133, .14),
         "Verdant": (205, .08), "Meridian": (118, .16), "Acme": (188, .09), "All": (176, .1)}
SUBSEQ = {"All": (.108, .043), "Acme": (.121, .049), "Brightcart": (.134, .052), "Vellum": (.094, .031),
          "Northwind": (.117, .038), "Fieldstone": (.129, .056), "Halden": (.071, .022), "Skylark": (.083, .027),
          "Ascent Capital": (.142, .061), "Renova": (.112, .036), "Verdant": (.088, .029), "Meridian": (.101, .034)}
SIZES = ["1–10", "11–50", "51–200", "201–1,000", "1,000+"]

def split(n, weights):
    raw = [n * w for w in weights]; out = [int(x) for x in raw]
    for i in sorted(range(len(raw)), key=lambda i: out[i] - raw[i])[: n - sum(out)]: out[i] += 1
    return out

def speed(c, n):
    med, u15 = SPEED[c]; n = max(n, 3)
    b = split(n, [.4, .22, .1, .18, .1]); rates = [31, 22, 17, 14, 6]
    return {"n": n, "avg_mins": round(med * 3.3), "median_mins": med, "under15_share": u15,
            "buckets": [{"label": l, "n": k, "booked": round(k * r / 100), "rate": r if k else 0}
                        for l, k, r in zip(["under 2 h", "2–6 h", "6–12 h", "12–24 h", "over 24 h"], b, rates)]}

def subseq(c, R, pos):
    pr, br = SUBSEQ[c]; scale = int(R) / 30
    enrolled = max(6, round(pos * 2.6 * (30 / int(R)) ** 0 )); sent = max(8, round(enrolled * 2.4))
    return {"sent": sent, "positives": max(1, round(sent * pr)), "booked": max(0, round(sent * br)),
            "enrolled": enrolled, "windowed": True,
            "asof": (dt.datetime.combine(ANCHOR, dt.time(21, 48))).isoformat() + "Z"}

idx = {}
for c in ["All"] + CLIENTS:
    for R in ("7", "14", "30"):
        key = "__all" if c == "All" else c
        pos = cw["windows"][R][key]["positives"]
        if c in ("All", "Acme"):
            base = copy.deepcopy(who_all if c == "All" else who_acme)
            if R != "30":
                wsrc = load({"7": "f0f1cf986c", "14": "7bfc589a6d"}[R]) if c == "All" else None
                if wsrc: base = wsrc
                else:
                    f = int(R) / 30
                    base["n"] = round(base["n"] * f); base["named"] = round(base["named"] * f)
                    base["buckets"] = [[k, max(0, round(v * f))] for k, v in base["buckets"]]
                    base["combos"] = [[a, b, max(1, round(v * f))] for a, b, v in base["combos"]]
                    base["combo_named"] = sum(x[2] for x in base["combos"])
                    base["sizes"] = [[k, round(v * f)] for k, v in base["sizes"]]
                    base["size_named"] = sum(v for _, v in base["sizes"])
            base["days"] = int(R)
        else:
            n = max(3, pos); named = max(2, round(n * .72))
            roles = ROLE_MIX[c]; rc = split(named, [w for _, w in roles])
            sz = split(n, SIZE_MIX[c])
            combos = {}
            for (role, _), k in zip(roles, rc):
                for _ in range(k):
                    s = rnd.choices(SIZES, weights=[w + .001 for w in SIZE_MIX[c]])[0]
                    combos[(role, s)] = combos.get((role, s), 0) + 1
            base = {"client": c, "days": int(R), "n": n, "named": named,
                    "buckets": [[r, k] for (r, _), k in zip(roles, rc) if k],
                    "sizes": [[s, k] for s, k in zip(SIZES, sz)], "size_named": n,
                    "combos": [[a, b, k] for (a, b), k in combos.items()],
                    "combo_named": sum(combos.values()), "size_order": SIZES}
        base["client"] = c
        if not base.get("speed"): base["speed"] = speed(c, round(pos * 2.3))
        base["subseq"] = subseq(c, R, pos)
        base["asof"] = (dt.datetime.combine(ANCHOR, dt.time(22, 12, 30))).isoformat() + "Z"
        fn = "deliv/who-%s-%s.json" % (c.lower().replace(" ", "-"), R)
        json.dump(base, open(os.path.join(FX, fn), "w"))
        idx["/api/who-replies?client=%s&days=%s" % (c.replace(" ", "+"), R)] = "fx/" + fn

for name, obj, keys in [("client-windows", cw, ["/api/client-windows"]),
                        ("analytics-hub-30", hub, ["/api/analytics-hub?days=30"]),
                        ("campaign-scorecard", score, ["/api/campaign-scorecard"]),
                        ("campaigns-unified", uni, ["/api/campaigns-unified"]),
                        ("signals-daily", sig, ["/api/signals/daily"]),
                        ("cockpit-insights", ins, ["/api/cockpit/insights"]),
                        ("sources", src, ["/api/sources?slim=1"])]:
    json.dump(obj, open(os.path.join(OUT, name + ".json"), "w"))
    for k in keys: idx[k] = "fx/deliv/%s.json" % name

with open(os.path.join(DEMO, "fx-deliv-index.js"), "w") as f:
    f.write("/* Page-scoped fixtures for deliverability.html — generated by tools/enrich_deliv_fx.py */\n")
    f.write("window.__FX_OVR=" + json.dumps(idx) + ";window.__FX_ANCHOR=\"%s\";\n" % ANCHOR.isoformat())
print("wrote", len(idx), "overrides")
