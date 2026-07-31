#!/usr/bin/env python3
"""Build 5 prototypes of the EXISTING strategy-page idea view (the "campaign at a glance"
showcase — see the live page https://navreo-signals.onrender.com/app/strategy.html).

Each prototype is a SIMPLER take on the SAME real idea (Food & Beverage / CPG, campaign 01
of the live KRG run), applying the original brief: simple, skim-first, highly visual, plain
16-year-old English, roomy, one orange accent — less explanation, more intuitive.

Faithful to the live data (pulled from /api/strategy/run → strategy-real-run.json), fully
STATIC (no JS needed to see anything), real Acid Grotesk embedded + exact navreo.css tokens.
Run:  python3 build_protos.py
"""
import base64, html, json, pathlib

HERE = pathlib.Path(__file__).parent
FONT_B64 = base64.b64encode((HERE.parent / "fonts" / "AcidGrotesk-Normal.otf").read_bytes()).decode()
DATA = json.loads((HERE / "strategy-real-run.json").read_text())
IDEA = DATA["idea"]

def esc(s): return html.escape(str(s or ""))
def num(n): return f"{int(n):,}"

# ---- pull real fields --------------------------------------------------
NAME     = IDEA["name"]                       # Food & Beverage / CPG
CAMPNO   = IDEA.get("campaignNo", "01")
TAG      = IDEA.get("shortTag") or IDEA.get("tag", "")
CAPTION  = IDEA.get("caption", "")
SERVICE  = IDEA["service"].replace("->", "→")  # Earned media → top-of-funnel sales
POOL     = IDEA["reachablePool"]
MINCAP   = IDEA.get("minCapacity", 5000)
POOLLBL  = IDEA.get("reachablePoolLabel", "measured live")
WHO      = IDEA["who"]
PAIN     = IDEA["pain"]
MOMENT   = IDEA.get("moment", "")
OFFER    = IDEA["offer"]
ANCHORS  = IDEA["anchors"]
CASES    = IDEA["cases"]
ROLES    = IDEA["targeting"]["roles"]
EMAIL    = IDEA["email"]
PEER     = IDEA.get("peerProofLine", "")
STAGES   = ["Targeting", "Copy", "First line", "Checks", "Live"]

def case_chip(c):
    ix = str(c).find(" — ")
    if ix == -1: return f'<span class="chip">{esc(c)}</span>'
    return f'<span class="chip">{esc(c[:ix])}<span class="chip-sub"> — {esc(c[ix+3:])}</span></span>'

def email_frame(cls="mail"):
    body = esc(EMAIL).replace("\n", "<br>")
    return (f'<div class="{cls}"><div class="mh">Sample email — signed Nathan</div>'
            f'<div class="mb">{body}</div></div>')

def roles_chips(n):
    shown = "".join(f'<span class="chip">{esc(r)}</span>' for r in ROLES[:n])
    more = len(ROLES) - n
    if more > 0: shown += f'<span class="chip chip-more">+{more} more</span>'
    return shown

def anchor_chips():
    return "".join(f'<span class="chip">{esc(a)}</span>' for a in ANCHORS)

def case_chips():
    return "".join(case_chip(c) for c in CASES)

# ---------------------------------------------------------------- CSS
BASE_CSS = """
@font-face{font-family:"Acid Grotesk";src:url(data:font/otf;base64,__FONT__) format("opentype");font-weight:400;font-display:swap;}
:root{
  --orange:#FF4D00;--orange-600:#DB4100;--orange-100:#FFE4D6;
  --ink:#14110E;--ink-2:#3A332C;--ink-3:#6B6055;
  --cream:#F9F0E7;--cream-50:#FCF7F1;--light-200:#E8D7C4;
  --bg:#FFFFFF;--card:#FFFFFF;--line:#ECECEA;--line-2:#DDDDDA;
  --green:#2E7D5B;--amber:#8F6600;
  --font-sans:"DM Sans",system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --font-display:"Acid Grotesk","DM Sans",system-ui,sans-serif;--radius:12px;
}
*{box-sizing:border-box} html,body{margin:0}
body{font-family:var(--font-sans);background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased;font-size:15px;line-height:1.55;}
.page{max-width:820px;margin:0 auto;padding:26px 34px 90px;}
.back{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--ink-2);border:1px solid var(--line);border-radius:999px;padding:6px 14px;}
.status{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);margin:22px 0 8px;}
.h1{font-family:var(--font-display);font-size:34px;letter-spacing:-.03em;line-height:1.08;margin:0;}
.capline{font-size:15px;color:var(--ink-3);margin-top:6px;}
.recc{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--orange-600);background:var(--orange-100);border-radius:999px;padding:3px 10px;margin-left:10px;vertical-align:middle;}
/* stage pills (kept, muted — the launch tracker) */
.stages{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0 26px;}
.spill{display:inline-flex;align-items:center;gap:7px;font-size:13px;color:var(--ink-3);border:1px solid var(--line);border-radius:999px;padding:6px 14px;}
.spill .ring{width:9px;height:9px;border-radius:50%;border:1.5px solid var(--line-2);}
/* shared bits */
.eyb{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);margin:0 0 12px;}
.chip{display:inline-flex;font-size:13.5px;padding:6px 12px;border-radius:9px;background:var(--cream-50);border:1px solid var(--line);color:var(--ink-2);}
.chip-sub{color:var(--ink-3);} .chip-more{color:var(--ink-3);background:transparent;}
.chips{display:flex;flex-wrap:wrap;gap:8px;}
.num{font-family:var(--font-display);letter-spacing:-.04em;line-height:.85;}
.mail{border:1px solid var(--line);border-radius:14px;overflow:hidden;}
.mail .mh{background:var(--cream);padding:11px 16px;border-bottom:1px solid var(--line);font-size:12.5px;letter-spacing:.03em;text-transform:uppercase;color:var(--ink-3);}
.mail .mb{padding:18px;font-size:15px;line-height:1.7;color:var(--ink-2);}
.mech{display:inline-flex;align-items:center;font-family:var(--font-display);font-size:15px;background:var(--cream-50);border:1px solid var(--line);border-radius:999px;padding:8px 16px;}
.trust{font-size:12.5px;color:var(--ink-3);}
@media(max-width:760px){.page{padding:22px 20px 70px}}
"""
def font_css(): return BASE_CSS.replace("__FONT__", FONT_B64)

def stages_html():
    return '<div class="stages">' + "".join(f'<span class="spill"><span class="ring"></span>{esc(s)}</span>' for s in STAGES) + '</div>'

def chrome(extra_css=""):
    return (f'<a class="back" href="#">‹ Back</a>'
            f'<div class="status">Not started</div>'
            f'<h1 class="h1">{esc(NAME)}<span class="recc">★ {esc(TAG)}</span></h1>'
            f'<div class="capline">{esc(CAPTION)} · Campaign {esc(CAMPNO)} of 9</div>'
            f'{stages_html()}')

def page(title, extra_css, body):
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{esc(title)}</title><style>{font_css()}{extra_css}</style></head><body>"
            f'<div class="page">{chrome()}{body}</div></body></html>')

# ================================================================ P1 · Tidy
# The existing page, just calmer: number as hero, roomy sections, DM list trimmed.
def build_p1():
    css = """
    .top{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;padding-bottom:24px;border-bottom:1px solid var(--line);margin-bottom:24px;}
    .top .n{font-size:64px;} .top .ncap{font-size:14px;color:var(--ink-3);text-align:right;} .top .ncap b{color:var(--ink);}
    .sect{margin-bottom:24px;} .who{font-size:16px;color:var(--ink-2);max-width:600px;}
    .offer{font-size:16px;color:var(--ink-2);max-width:640px;}
    """
    body = (f'<div class="top"><div class="mech">{esc(SERVICE)}</div>'
            f'<div style="text-align:right"><div class="num n">{num(POOL)}</div>'
            f'<div class="ncap"><b>reachable — we email all</b><br><span class="trust">{esc(POOLLBL)} · minimum {num(MINCAP)}, not a cap</span></div></div></div>'
            f'<div class="sect"><p class="eyb">Who we\'d email</p><p class="who">{esc(WHO)}</p></div>'
            f'<div class="sect"><p class="eyb">Companies like these</p><div class="chips">{anchor_chips()}</div></div>'
            f'<div class="sect"><p class="eyb">Case studies we pull</p><div class="chips">{case_chips()}</div></div>'
            f'<div class="sect"><p class="eyb">Decision-makers we email</p><div class="chips">{roles_chips(8)}</div></div>'
            f'<div class="sect"><p class="eyb">How we\'d help</p><p class="offer">{esc(OFFER)}</p></div>'
            f'<div class="sect">{email_frame()}</div>')
    return page("Strategy idea · P1 Tidy", css, body)

# ================================================================ P2 · Number-first
# Lead with the one big thing; email prominent; proof + roles compressed to a line.
def build_p2():
    css = """
    .hero{padding:10px 0 26px;border-bottom:1px solid var(--line);margin-bottom:24px;}
    .hero .n{font-size:104px;}
    .hero .cap{font-size:19px;color:var(--ink);margin-top:4px;} .hero .sub{font-size:14px;color:var(--ink-3);margin-top:8px;}
    .lead{font-size:17px;color:var(--ink-2);max-width:640px;margin:0 0 22px;}
    .lead .mech2{color:var(--orange-600);font-weight:600;}
    .proof{font-size:14.5px;color:var(--ink-3);margin:22px 0 0;} .proof b{color:var(--ink-2);}
    .metaline{font-size:14px;color:var(--ink-3);margin-top:8px;}
    """
    body = (f'<div class="hero"><div class="num n">{num(POOL)}</div>'
            f'<div class="cap">marketing leaders we can email</div>'
            f'<div class="sub">{esc(POOLLBL)} · minimum {num(MINCAP)}, not a cap</div></div>'
            f'<p class="lead"><span class="mech2">{esc(SERVICE)}.</span> {esc(WHO)}</p>'
            f'{email_frame()}'
            f'<p class="proof"><b>Proof:</b> {esc(PEER)}.</p>'
            f'<p class="metaline">We email the CMO down to Head of PR — {len(ROLES)} roles across {len(ANCHORS)} anchor brands.</p>')
    return page("Strategy idea · P2 Number-first", css, body)

# ================================================================ P3 · Two-column glance
# Skim facts on the left, the email on the right — one screen, little scroll.
def build_p3():
    css = """
    .cols{display:grid;grid-template-columns:1fr 1fr;gap:26px;align-items:start;}
    .facts .row{padding:14px 0;border-bottom:1px solid var(--line);}
    .facts .row:first-child{padding-top:0;}
    .facts .k{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);margin-bottom:6px;}
    .facts .n{font-size:52px;} .facts .ncap{font-size:13px;color:var(--ink-3);}
    .facts .v{font-size:15px;color:var(--ink-2);}
    .facts .mech{margin-top:2px;}
    .anch{font-size:14.5px;color:var(--ink-2);line-height:1.6;}
    @media(max-width:760px){.cols{grid-template-columns:1fr}}
    """
    anchors_line = ", ".join(ANCHORS[:5]) + f" +{len(ANCHORS)-5} more"
    body = (f'<div class="cols"><div class="facts">'
            f'<div class="row"><div class="k">The angle</div><div class="mech">{esc(SERVICE)}</div></div>'
            f'<div class="row"><div class="k">How many we can email</div><div class="num n">{num(POOL)}</div>'
            f'<div class="ncap">reachable — we email all · {esc(POOLLBL)}</div></div>'
            f'<div class="row"><div class="k">Who</div><div class="v">{esc(WHO)}</div></div>'
            f'<div class="row"><div class="k">Companies like these</div><div class="anch">{esc(anchors_line)}</div></div>'
            f'<div class="row"><div class="k">Decision-makers</div><div class="v">The CMO down to Head of PR — {len(ROLES)} roles.</div></div>'
            f'<div class="row" style="border-bottom:none"><div class="k">How we\'d help</div><div class="v">{esc(OFFER)}</div></div>'
            f'</div><div class="email-col"><p class="eyb">The email we\'d send</p>{email_frame()}</div></div>')
    return page("Strategy idea · P3 Two-column", css, body)

# ================================================================ P4 · Story + tabs  (THE WINNER)
# Bjion 2026-07-31: "p4 is the best, but it needs the targeting" (use P1's targeting UI),
# "the brief description of the campaign needs to be capped", and the stage pills go
# "top right, so you can tab between the sections easily". Pure-CSS radio tabs — no JS.
TABS = [("t-tgt", "Targeting", "p-tgt"), ("t-copy", "Copy", "p-copy"),
        ("t-first", "First line", "p-first"), ("t-checks", "Checks", "p-checks"),
        ("t-live", "Live", "p-live")]

def build_p4():
    # per-tab CSS: which panel shows + which pill lights, when its radio is checked
    tabcss = "\n".join(
        f'#{tid}:checked ~ .panels .{pid}{{display:block;}}\n'
        f'#{tid}:checked ~ .topbar label[for="{tid}"]{{color:var(--ink);border-color:var(--orange);background:var(--bg);}}\n'
        f'#{tid}:checked ~ .topbar label[for="{tid}"] .ring{{border-color:var(--orange);background:var(--orange);}}'
        for tid, _lbl, pid in TABS)
    css = """
    .tabin{position:absolute;width:0;height:0;opacity:0;pointer-events:none;}
    .topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;}
    .tabs{display:flex;gap:7px;flex-wrap:wrap;}
    .tabs label{display:inline-flex;align-items:center;gap:7px;font-size:13px;color:var(--ink-3);border:1px solid var(--line);border-radius:999px;padding:6px 13px;cursor:pointer;transition:.12s;}
    .tabs label:hover{border-color:var(--line-2);}
    .tabs .ring{width:9px;height:9px;border-radius:50%;border:1.5px solid var(--line-2);}
    .desc{font-size:18px;line-height:1.55;color:var(--ink);max-width:640px;margin:16px 0 6px;letter-spacing:-.01em;
      display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
    .desc b{background:linear-gradient(transparent 62%, var(--orange-100) 62%);font-weight:600;}
    .panels{margin-top:22px;}
    .panel{display:none;}
    /* Targeting panel (P1's UI) */
    .tnum{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;padding-bottom:22px;border-bottom:1px solid var(--line);margin-bottom:22px;}
    .tnum .n{font-size:60px;} .tnum .cap{font-size:14px;color:var(--ink-3);text-align:right;max-width:220px;} .tnum .cap b{color:var(--ink);}
    .sect{margin-bottom:22px;} .sect .who{font-size:16px;color:var(--ink-2);max-width:600px;}
    .offer{font-size:16px;color:var(--ink-2);max-width:640px;margin:0 0 20px;}
    /* First-line panel */
    .hook{font-family:var(--font-display);font-size:26px;line-height:1.35;letter-spacing:-.02em;color:var(--ink);max-width:660px;}
    .hooknote{font-size:14px;color:var(--ink-3);margin-top:16px;}
    /* placeholder panels */
    .ph{border:1px dashed var(--line-2);border-radius:14px;padding:26px;color:var(--ink-3);font-size:15px;max-width:640px;}
    """ + tabcss
    # radios: Targeting checked by default
    radios = "".join(
        f'<input class="tabin" type="radio" name="tab" id="{tid}"{" checked" if i==0 else ""}>'
        for i, (tid, _l, _p) in enumerate(TABS))
    pills = "".join(
        f'<label for="{tid}"><span class="ring"></span>{esc(lbl)}</label>' for tid, lbl, _p in TABS)
    desc = (f'We can email <b>{num(POOL)}</b> marketing bosses at big food, drink and consumer-goods brands. '
            f'They spend a fortune on press but can\'t tell if it actually brings in buyers — and we\'ve turned '
            f'press into real sales for <b>Coca-Cola, Nestlé and General Mills</b>.')
    # panels
    p_tgt = (f'<section class="panel p-tgt">'
             f'<div class="tnum"><div><div class="mech">{esc(SERVICE)}</div></div>'
             f'<div style="text-align:right"><div class="num n">{num(POOL)}</div>'
             f'<div class="cap"><b>reachable — we email all</b><br>{esc(POOLLBL)} · minimum {num(MINCAP)}, not a cap</div></div></div>'
             f'<div class="sect"><p class="eyb">Who we\'d email</p><p class="who">{esc(WHO)}</p></div>'
             f'<div class="sect"><p class="eyb">Companies like these</p><div class="chips">{anchor_chips()}</div></div>'
             f'<div class="sect"><p class="eyb">Case studies we pull</p><div class="chips">{case_chips()}</div></div>'
             f'<div class="sect"><p class="eyb">Decision-makers we email</p><div class="chips">{roles_chips(8)}</div></div>'
             f'</section>')
    p_copy = (f'<section class="panel p-copy">'
              f'<div class="sect"><p class="eyb">How we\'d help</p><p class="offer">{esc(OFFER)}</p></div>'
              f'{email_frame()}</section>')
    p_first = (f'<section class="panel p-first"><p class="eyb">The line that opens the email</p>'
               f'<p class="hook">"{esc(PAIN)}"</p>'
               f'<p class="hooknote">{esc(MOMENT)}</p></section>')
    p_checks = ('<section class="panel p-checks"><p class="eyb">Checks</p>'
                '<div class="ph">Not started yet. This is where we\'ll check the spelling, the links and that every email reads right — before anything is allowed to send.</div></section>')
    p_live = ('<section class="panel p-live"><p class="eyb">Live</p>'
              '<div class="ph">Not live yet. Once you approve it, the campaign turns on here and we track who replies. Nothing sends until you switch it on.</div></section>')
    body_full = (f'{radios}'
                 f'<div class="topbar"><a class="back" href="#">‹ Back</a><div class="tabs">{pills}</div></div>'
                 f'<div class="status">Not started</div>'
                 f'<h1 class="h1">{esc(NAME)}<span class="recc">★ {esc(TAG)}</span></h1>'
                 f'<div class="capline">{esc(CAPTION)} · Campaign {esc(CAMPNO)} of 9</div>'
                 f'<div class="desc">{desc}</div>'
                 f'<div class="panels">{p_tgt}{p_copy}{p_first}{p_checks}{p_live}</div>')
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>Strategy idea · P4 (winner)</title><style>{font_css()}{css}</style></head><body>"
            f'<div class="page">{body_full}</div></body></html>')

# ================================================================ P5 · Cards
# A few calm cards you can skim in any order.
def build_p5():
    css = """
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
    .card{border:1px solid var(--line);border-radius:16px;padding:20px 22px;}
    .card.wide{grid-column:span 2;}
    .card .n{font-size:58px;} .card .ncap{font-size:13px;color:var(--ink-3);margin-top:4px;}
    .card .v{font-size:15px;color:var(--ink-2);}
    .card .mech{margin-bottom:12px;}
    .mini{font-size:14px;color:var(--ink-2);line-height:1.6;}
    @media(max-width:760px){.grid{grid-template-columns:1fr}.card.wide{grid-column:auto}}
    """
    anchors_line = ", ".join(ANCHORS[:4]) + f" +{len(ANCHORS)-4}"
    body = (f'<div class="grid">'
            f'<div class="card"><p class="eyb">How many & who</p><div class="mech">{esc(SERVICE)}</div>'
            f'<div class="num n">{num(POOL)}</div><div class="ncap">reachable — we email all · {esc(POOLLBL)}</div>'
            f'<p class="v" style="margin-top:12px">{esc(WHO)}</p></div>'
            f'<div class="card"><p class="eyb">Why now</p><p class="mini">{esc(PAIN)}</p>'
            f'<p class="mini" style="color:var(--ink-3);margin-top:10px">{esc(MOMENT)}</p></div>'
            f'<div class="card wide"><p class="eyb">Proof we can point to</p>'
            f'<p class="mini" style="margin-bottom:12px">Companies like these: <b>{esc(anchors_line)}</b></p>'
            f'<div class="chips">{case_chips()}</div></div>'
            f'<div class="card wide"><p class="eyb">The email</p>{email_frame()}</div>'
            f'</div>')
    return page("Strategy idea · P5 Cards", css, body)

# ---------------------------------------------------------------- write
FILES = {
    "strategy-companion-p1.html": build_p1(),
    "strategy-companion-p2.html": build_p2(),
    "strategy-companion-p3.html": build_p3(),
    "strategy-companion-p4.html": build_p4(),
    "strategy-companion-p5.html": build_p5(),
}
for name, content in FILES.items():
    (HERE / name).write_text(content, encoding="utf-8")
    print(f"wrote {name}  ({len(content)//1024} KB)")
print("done — 5 simpler takes on the real Food & Beverage / CPG idea page.")
