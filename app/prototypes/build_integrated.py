#!/usr/bin/env python3
"""Integrate the winning idea-homepage design (P4) into the STRATEGY shell.

- Left: the strategy sidebar — every idea is a card (the "other pages"), like the real
  #idea-list (name · caption · count + tag · 5-stage track), but warm, not gray.
- Right: the selected idea shown in the NEW P4 design (capped description + top-right stage
  tabs Targeting/Copy/First line/Checks/Live + P1's targeting UI). NONE of the old workspace
  pages are included.
- Sidebar navigates the 9 real ideas; each idea's tabs work — all pure CSS, no JS.

Reads the live run (strategy-real-run.json, all 9 ideas). Acid Grotesk embedded, navreo.css tokens.
Run:  python3 build_integrated.py
"""
import base64, html, json, pathlib, re

HERE = pathlib.Path(__file__).parent
FONT_B64 = base64.b64encode((HERE.parent / "fonts" / "AcidGrotesk-Normal.otf").read_bytes()).decode()
IDEAS = json.loads((HERE / "strategy-real-run.json").read_text())["ideas"]

def esc(s): return html.escape(str(s or ""))
def num(n): return f"{int(n):,}"
# Targeting → Copy → First line → Build (the only step that pulls real data / arms the trigger — a
# final confirm) → Live. "Build" chosen over "Checks/Set up/Launch": it fits both a one-off list pull
# and a standing trigger, and stays distinct from "Live".
TABS = [("tgt", "Targeting"), ("copy", "Copy"), ("first", "Icebreaker"), ("build", "Build"), ("live", "Live")]
STAGE_LABELS = [t[1] for t in TABS]

def case_chip(c):
    ix = str(c).find(" — ")
    if ix == -1: return f'<span class="chip">{esc(c)}</span>'
    return f'<span class="chip">{esc(c[:ix])}<span class="chip-sub"> — {esc(c[ix+3:])}</span></span>'
def anchor_chips(idea): return "".join(f'<span class="chip">{esc(a)}</span>' for a in idea.get("anchors", []))
def case_chips(idea):   return "".join(case_chip(c) for c in idea.get("cases", []))
def roles_chips(idea, n=8):
    roles = (idea.get("targeting") or {}).get("roles", [])
    shown = "".join(f'<span class="chip">{esc(r)}</span>' for r in roles[:n])
    if len(roles) - n > 0: shown += f'<span class="chip chip-more">+{len(roles)-n} more</span>'
    return shown
def email_frame(idea):
    body = esc(idea.get("email", "")).replace("\n", "<br>")
    sign = [l.strip() for l in str(idea.get("email", "")).split("\n") if l.strip()]
    sign = sign[-1] if sign else ""
    return (f'<div class="mail"><div class="mh">Sample email — signed {esc(sign)}</div>'
            f'<div class="mb">{body}</div></div>')

# ---------------------------------------------------------------- CSS
CSS = """
@font-face{font-family:"Acid Grotesk";src:url(data:font/otf;base64,__FONT__) format("opentype");font-weight:400;font-display:swap;}
:root{
  --orange:#FF4D00;--orange-600:#DB4100;--orange-100:#FFE4D6;
  --ink:#14110E;--ink-2:#3A332C;--ink-3:#6B6055;
  --cream:#F7F7F6;--cream-50:#F7F7F6;--light-200:#DDDDDA;  /* beige retired → tool neutral (black/white/orange) */
  --bg:#FFFFFF;--card:#FFFFFF;--line:#ECECEA;--line-2:#DDDDDA;
  --green:#2E7D5B;--amber:#8F6600;
  --font-sans:"DM Sans",system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --font-display:"Acid Grotesk","DM Sans",system-ui,sans-serif;--radius:12px;
}
*{box-sizing:border-box} html,body{margin:0;height:100%}
body{font-family:var(--font-sans);background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased;font-size:15px;line-height:1.55;}
a{color:inherit;text-decoration:none}
.app{display:grid;grid-template-columns:312px 1fr;height:100%;}
/* ---------- sidebar (the idea list = the "other pages"); warm, not gray ---------- */
.side{background:var(--bg);border-right:1px solid var(--line);padding:22px 14px;overflow:auto;}
.brand{display:flex;align-items:baseline;gap:8px;padding:2px 10px 14px;}
.brand b{font-family:var(--font-display);font-size:20px;letter-spacing:-.02em;}
.brand .ey{font-size:10.5px;letter-spacing:.16em;color:var(--ink-3);text-transform:uppercase;}
.client{margin:0 10px 12px;padding:12px 14px;background:var(--bg);border:1px solid var(--line);border-radius:12px;}
.client .lbl{font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;color:var(--ink-3);}
.client .name{font-size:14.5px;font-weight:600;margin-top:3px;}
.sechead{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);padding:8px 12px 6px;}
.im{display:block;position:relative;border:1px solid transparent;border-radius:12px;padding:13px 14px;margin-bottom:5px;transition:.13s;}
.im:hover{background:var(--cream-50);border-color:var(--line);}
.im-name{font-size:14px;font-weight:600;line-height:1.3;margin:0;}
.im-caption{font-size:12.5px;color:var(--ink-3);margin:3px 0 10px;}
.im-count{display:flex;align-items:center;gap:8px;margin:0 0 9px;font-size:12.5px;color:var(--ink-3);}
.im-number{font-family:var(--font-display);font-size:16px;letter-spacing:-.02em;color:var(--ink);}
.im-type{display:inline-flex;font-size:11px;font-weight:600;color:var(--ink-2);background:transparent;border:1px solid var(--line-2);border-radius:999px;padding:3px 10px;margin:0 0 10px;}
.im-track{display:flex;gap:3px;}
.im-track i{flex:1;height:4px;border-radius:2px;background:var(--line-2);}
/* active card (default = first; :has lights the targeted one) */
.im.on{background:var(--bg);border-color:var(--line-2);}
.im.on::before{content:"";position:absolute;left:-14px;top:14px;bottom:14px;width:3px;border-radius:2px;background:var(--orange);}
/* ---------- workspace ---------- */
.work{overflow:auto;}
.idea-view{display:none;}   /* shown by the checked idea radio — see ideanav_css() */
.wrap{max-width:860px;padding:30px 40px 90px;}
.wtop{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;flex-wrap:wrap;}
.status{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);margin-bottom:8px;}
.h1{font-family:var(--font-display);font-size:32px;letter-spacing:-.03em;line-height:1.08;margin:0;}
.recc{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--orange-600);background:var(--orange-100);border-radius:999px;padding:3px 10px;margin-left:10px;vertical-align:middle;}
.capline{font-size:14px;color:var(--ink-3);margin-top:6px;}
.tabin{position:absolute;width:0;height:0;opacity:0;pointer-events:none;}
.tabs{display:flex;gap:7px;flex-wrap:wrap;}
.tabs label{display:inline-flex;align-items:center;gap:7px;font-size:13px;color:var(--ink-3);border:1px solid var(--line);border-radius:999px;padding:6px 13px;cursor:pointer;transition:.12s;}
.tabs label:hover{border-color:var(--line-2);}
.tabs .ring{width:9px;height:9px;border-radius:50%;border:1.5px solid var(--line-2);}
.toptabs{margin-bottom:22px;}
.typetag{display:inline-flex;align-items:center;font-size:12px;font-weight:600;letter-spacing:.02em;color:var(--ink-2);background:var(--cream-50);border:1px solid var(--line-2);border-radius:999px;padding:5px 13px;margin-left:12px;vertical-align:middle;white-space:nowrap;}
.desc{font-size:17px;line-height:1.55;color:var(--ink);max-width:640px;margin:18px 0 4px;letter-spacing:-.01em;}
.desc b{background:linear-gradient(transparent 62%, var(--orange-100) 62%);font-weight:600;}
.panels{margin-top:22px;}
.panel{display:none;}
.eyb{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);margin:0 0 12px;}
.chip{display:inline-flex;font-size:13.5px;padding:6px 12px;border-radius:9px;background:var(--cream-50);border:1px solid var(--line);color:var(--ink-2);}
.chip-sub{color:var(--ink-3);} .chip-more{color:var(--ink-3);background:transparent;}
.chips{display:flex;flex-wrap:wrap;gap:8px;}
.mech{display:inline-flex;align-items:center;font-family:var(--font-display);font-size:15px;background:var(--cream-50);border:1px solid var(--line);border-radius:999px;padding:8px 16px;}
.tnum{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;padding-bottom:22px;border-bottom:1px solid var(--line);margin-bottom:22px;}
.tnum .n{font-family:var(--font-display);font-size:60px;letter-spacing:-.04em;line-height:.85;}
.tnum .cap{font-size:14px;color:var(--ink-3);text-align:right;max-width:220px;} .tnum .cap b{color:var(--ink);}
.sect{margin-bottom:22px;} .sect .who{font-size:16px;color:var(--ink-2);max-width:600px;}
.offer{font-size:16px;color:var(--ink-2);max-width:640px;margin:0 0 20px;}
.mail{border:1px solid var(--line);border-radius:14px;overflow:hidden;}
.mail .mh{background:var(--cream);padding:11px 16px;border-bottom:1px solid var(--line);font-size:12.5px;letter-spacing:.03em;text-transform:uppercase;color:var(--ink-3);}
.mail .mb{padding:18px;font-size:15px;line-height:1.7;color:var(--ink-2);}
.hook{font-family:var(--font-display);font-size:25px;line-height:1.35;letter-spacing:-.02em;color:var(--ink);max-width:660px;}
.hooknote{font-size:14px;color:var(--ink-3);margin-top:16px;}
.ph{border:1px dashed var(--line-2);border-radius:14px;padding:24px;color:var(--ink-3);font-size:15px;max-width:640px;}
/* the big number (size kept — Bjion likes it) + 3 placement variants */
.numbig .n{font-family:var(--font-display);font-size:76px;letter-spacing:-.04em;line-height:.82;}
.numbig .rl{font-size:15px;font-weight:600;color:var(--ink);margin-top:6px;}
.numbig .ml{font-size:13.5px;color:var(--ink-3);margin-top:3px;}
.numbig.right{text-align:right;}
.tgt-hero{padding-bottom:24px;border-bottom:1px solid var(--line);margin-bottom:24px;}      /* A */
.tgt-hero .mech{margin-bottom:18px;}
.hdr-b{display:flex;justify-content:space-between;align-items:flex-start;gap:28px;flex-wrap:wrap;}  /* B */
.hdr-b .hl{min-width:260px;} .hdr-b .mech{margin-top:14px;}
.band{display:flex;justify-content:space-between;align-items:center;gap:24px;flex-wrap:wrap;         /* C */
  background:var(--cream-50);border:1px solid var(--line);border-radius:16px;padding:20px 26px;margin:24px 0 4px;}
.band .band-l .eyb{margin-bottom:10px;}
/* Checks tab — pre-launch checklist */
.chkhead{font-size:15px;color:var(--ink-2);margin:0 0 14px;max-width:600px;}
.checks{max-width:640px;}
.chk{display:flex;align-items:flex-start;gap:12px;padding:13px 0;border-bottom:1px solid var(--line);}
.chk:last-child{border-bottom:none;}
.chk .ck{width:17px;height:17px;border-radius:50%;border:1.5px solid var(--line-2);margin-top:2px;flex:none;}
.chk .cl{font-size:15px;font-weight:600;} .chk .cn{font-size:13px;color:var(--ink-3);margin-top:2px;}
/* Live tab — goes-live preview */
.livebanner{background:var(--cream-50);border:1px solid var(--line);border-radius:12px;padding:14px 18px;font-size:14px;color:var(--ink-2);margin-bottom:16px;}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:0 0 18px;max-width:660px;}
.tile{border:1px solid var(--line);border-radius:14px;padding:16px 18px;}
.tile .tn{font-family:var(--font-display);font-size:30px;letter-spacing:-.03em;line-height:1;}
.tile .tl{font-size:12.5px;color:var(--ink-3);margin-top:6px;}
.planline{font-size:14px;color:var(--ink-3);max-width:600px;}
.build-btn{margin-top:22px;font-family:var(--font-sans);font-size:15px;font-weight:600;color:#fff;background:var(--orange);border:none;border-radius:999px;padding:12px 26px;cursor:pointer;transition:.12s;}
.build-btn:hover{background:var(--orange-600);}
/* Copy screen (Your emails) + Icebreaker screen (The opener) — the tool's real UI, reskinned */
.copy-heading{font-family:var(--font-display);font-size:22px;letter-spacing:-.02em;margin:0 0 18px;}
.pager{display:flex;align-items:center;gap:16px;margin-bottom:18px;}
.pager-arrow{width:32px;height:32px;border-radius:50%;border:1px solid var(--line-2);background:var(--bg);color:var(--ink-2);cursor:pointer;font-size:16px;line-height:1;}
.pager-arrow:disabled{opacity:.35;cursor:default;}
.pager-mid{display:flex;align-items:center;gap:14px;}
.pager-dots{display:flex;align-items:center;gap:8px;}
.pager-dot{width:9px;height:9px;border-radius:50%;border:none;background:var(--line-2);cursor:pointer;padding:0;}
.pager-dot.active{background:var(--orange);}
.pager-divider{width:1px;height:14px;background:var(--line-2);}
.pager-fu{font-size:12px;color:var(--ink-3);margin-left:2px;}
.pager-label{font-family:var(--font-display);font-size:14px;color:var(--ink);}
.actions-center{display:flex;justify-content:center;margin-top:22px;}
.btn-ink{font-family:var(--font-sans);font-size:14px;font-weight:600;color:#fff;background:var(--ink);border:none;border-radius:999px;padding:11px 22px;cursor:pointer;}
.btn-ink:hover{background:#2a241e;}
.opener-list{display:flex;flex-direction:column;gap:10px;max-width:700px;}
.opener-row{display:grid;grid-template-columns:auto 1fr auto;gap:16px;align-items:start;border:1px solid var(--line);border-radius:14px;padding:16px 18px;}
.opener-order{display:flex;flex-direction:column;align-items:center;gap:5px;padding-top:2px;}
.opos{font-family:var(--font-display);font-size:14px;color:var(--ink-3);}
.oarrow{width:24px;height:18px;border:1px solid var(--line);background:var(--bg);border-radius:6px;color:var(--ink-3);cursor:pointer;font-size:9px;line-height:1;padding:0;}
.oarrow:disabled{opacity:.3;cursor:default;}
.ib-name{font-size:15px;font-weight:600;margin:0 0 5px;display:flex;align-items:center;gap:9px;}
.ib-rec{font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--orange-600);background:var(--orange-100);border-radius:999px;padding:2px 8px;}
.ib-plain{font-size:13.5px;color:var(--ink-3);margin:0 0 8px;}
.ib-example{font-size:14px;color:var(--ink-2);margin:0;font-style:italic;}
.otog{font-size:12px;font-weight:600;color:var(--orange-600);background:var(--orange-100);border-radius:999px;padding:4px 13px;white-space:nowrap;height:fit-content;}
@media(max-width:760px){.tiles{grid-template-columns:1fr 1fr}}
@media(max-width:900px){.app{grid-template-columns:1fr}.side{border-right:none;border-bottom:1px solid var(--line)}}
"""

# ---------------------------------------------------------------- per-idea tab CSS + nav-active CSS
def tab_css():
    out = []
    for n in range(1, len(IDEAS) + 1):
        for k, _lbl in TABS:
            out.append(f'#t-i{n}-{k}:checked ~ .panels .p-{k}{{display:block;}}')
            out.append(f'#t-i{n}-{k}:checked ~ .tabs label[for="t-i{n}-{k}"]{{color:var(--ink);border-color:var(--orange);background:var(--bg);}}')
            out.append(f'#t-i{n}-{k}:checked ~ .tabs label[for="t-i{n}-{k}"] .ring{{border-color:var(--orange);background:var(--orange);}}')
    return "\n".join(out)

def ideanav_css():
    """Radio-driven idea navigation (works with no JS / no :target / no :has)."""
    out = []
    for n in range(1, len(IDEAS) + 1):
        out.append(f'#idea-i{n}:checked ~ .work .iv-{n}{{display:block;}}')
        out.append(f'#idea-i{n}:checked ~ .side .nav-i{n}{{background:var(--orange-100);border-color:var(--orange-100);}}')
        out.append(f'#idea-i{n}:checked ~ .side .nav-i{n}::before{{content:"";position:absolute;left:-14px;top:14px;bottom:14px;width:3px;border-radius:2px;background:var(--orange);}}')
    return "\n".join(out)

# ---------------------------------------------------------------- fragments
def sidebar():
    cards = []
    for i, idea in enumerate(IDEAS, 1):
        service = idea.get("service", "").replace("->", "→")
        segs = "".join('<i></i>' for _ in TABS)
        cards.append(
            f'<label class="im nav-i{i}" for="idea-i{i}">'
            f'<p class="im-name">{esc(idea.get("name"))}</p>'
            f'<p class="im-caption">{esc(idea.get("caption"))}</p>'
            f'<p class="im-count"><span class="im-number">{num(idea.get("net") or idea.get("reachablePool"))}</span> reachable</p>'
            f'<p class="im-type">{esc(service)}</p>'
            f'<div class="im-track">{segs}</div></label>')
    return ('<aside class="side"><div class="brand"><b>Navreo</b><span class="ey">Strategy</span></div>'
            '<div class="client"><div class="lbl">Building for</div><div class="name">KRG — earned media</div></div>'
            '<div class="sechead">9 campaign ideas</div>' + "".join(cards) + '</aside>')

def num_big(idea, align="", note=True):
    pool = idea.get("reachablePool") or idea.get("net")
    mincap = idea.get("minCapacity", 5000)
    poollbl = idea.get("reachablePoolLabel", "measured live")
    cls = "numbig right" if align == "right" else "numbig"
    ml = f'<div class="ml">{esc(poollbl)} · minimum {num(mincap)}, not a cap</div>' if note else ""
    return (f'<div class="{cls}"><div class="n">{num(pool)}</div>'
            f'<div class="rl">reachable — we email all</div>{ml}</div>')

def mech_pill(idea):
    return f'<div class="mech">{esc(idea["service"].replace("->", "→"))}</div>'

def proof_brands(peer):
    """Pull the real client/brand names out of a peerProofLine so they can be highlighted."""
    m = re.search(r'\b(?:for|at) ([A-Z][\w.&\-]*(?:[ ,]+(?:and\s+)?[A-Z][\w.&\-]*)*)', peer or "")
    return m.group(1).strip() if m else ""

def cap120(text, limit=120):
    """Keep the description to <=120 chars, cutting on a word boundary and ending cleanly (no ellipsis)."""
    text = " ".join((text or "").split()).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    stops = {"and", "or", "the", "a", "an", "to", "of", "their", "that", "who", "with",
             "without", "in", "on", "for", "is", "are", "but", "its", "whose", "by", "at", "as", "new"}
    words = cut.rstrip(",;:—- ").split(" ")
    while words and words[-1].lower().strip(",;:") in stops:
        words.pop()
    out = " ".join(words).rstrip(",;:—- ")
    return out + ("" if out[-1:] in ".!?" else ".")

# --- the tool's real Copy + Icebreaker screens, reproduced (reskinned) so the prototype shows
#     the "previous UI" that Copy/Icebreaker keep-and-reskin (not the old simplified placeholders) ---
ICEB = [
    ("Safe opener", True, "A polite, personal-feeling opening line that always works. Our best performer.",
     "Apologies if this isn't relevant, wasn't sure who at {company} was the best person for this."),
    ("Company detail", False, "References something specific we found about their company.",
     "Saw {company} covers three states now. Growth like that usually strains the pipeline side."),
    ("Colleague mention", False, "Names a colleague we found, only where we're confident it's right.",
     "I wasn't sure if you or {colleague} was the right person to ask at {company}."),
]
def opener_rows():
    out = ""
    for i, (name, rec, plain, ex) in enumerate(ICEB):
        rec_html = ' <span class="ib-rec">Recommended</span>' if rec else ""
        up = " disabled" if i == 0 else ""
        dn = " disabled" if i == len(ICEB) - 1 else ""
        out += (f'<div class="opener-row"><div class="opener-order"><span class="opos">{i+1}</span>'
                f'<button class="oarrow"{up}>▲</button><button class="oarrow"{dn}>▼</button></div>'
                f'<div class="opener-body"><p class="ib-name">{esc(name)}{rec_html}</p>'
                f'<p class="ib-plain">{esc(plain)}</p><p class="ib-example">"{esc(ex)}"</p></div>'
                f'<span class="otog">On</span></div>')
    return out
OPENER_HTML = opener_rows()

def version_frame(idea):
    body = esc(idea.get("email", "")).replace("\n", "<br>")
    return (f'<div class="mail"><div class="mh">Subject: {esc(idea.get("caption", ""))}</div>'
            f'<div class="mb">{body}</div></div>')

def targeting_sections(idea, include_who=True):
    who = (f'<div class="sect"><p class="eyb">Who we\'d email</p><p class="who">{esc(idea.get("who"))}</p></div>'
           if include_who else "")
    return (who
            + f'<div class="sect"><p class="eyb">Companies like these</p><div class="chips">{anchor_chips(idea)}</div></div>'
            + f'<div class="sect"><p class="eyb">Case studies we pull</p><div class="chips">{case_chips(idea)}</div></div>'
            + f'<div class="sect"><p class="eyb">Decision-makers we email</p><div class="chips">{roles_chips(idea)}</div></div>')

def idea_view(idea, n, default, layout):
    tag = idea.get("shortTag") or idea.get("tag", "")
    caption = idea.get("caption", "")
    moment = idea.get("moment", "") or idea.get("pain", "")
    pool = idea.get("reachablePool") or idea.get("net")
    radios = "".join(
        f'<input class="tabin" type="radio" name="tab-i{n}" id="t-i{n}-{k}"{" checked" if k=="tgt" else ""}>'
        for k, _l in TABS)
    pills = f'<div class="tabs">' + "".join(
        f'<label for="t-i{n}-{k}"><span class="ring"></span>{esc(lbl)}</label>' for k, lbl in TABS) + '</div>'
    status = '<div class="status">Not started</div>'          # (kept for the B/C variants only)
    title = f'<h1 class="h1">{esc(idea.get("name"))}</h1>'     # title only — no status, no caption, no type pill
    toptabs = f'<div class="toptabs">{pills}</div>'            # tabs sit above the title
    # description = why this campaign is a good idea (who they are + the problem they face), <=120 chars,
    # no headcount (the big number carries that), capped on a word boundary rather than clamped/truncated.
    desc = f'<div class="desc">{esc(cap120(idea.get("who", "")))}</div>'

    # panels shared across variants; the Targeting panel differs (A carries the number)
    # Copy = the tool's "Your emails" screen: Version A/B/C/D + Follow-up pager + the email frame
    p_copy = ('<section class="panel p-copy"><p class="copy-heading">Your emails</p>'
              '<div class="pager"><button class="pager-arrow" disabled>&#8249;</button>'
              '<div class="pager-mid"><div class="pager-dots">'
              '<button class="pager-dot active"></button><button class="pager-dot"></button>'
              '<button class="pager-dot"></button><button class="pager-dot"></button>'
              '<span class="pager-divider"></span><button class="pager-dot"></button>'
              '<span class="pager-fu">Follow-up</span></div>'
              '<span class="pager-label">Version A</span></div>'
              '<button class="pager-arrow">&#8250;</button></div>'
              + version_frame(idea)
              + '<div class="actions-center"><button class="btn-ink">Next: choose the opener</button></div></section>')
    # Icebreaker = the tool's "The opener" waterfall (ranked opener angles, on/off, reorder)
    p_first = ('<section class="panel p-first"><p class="copy-heading">The opener</p>'
               f'<div class="opener-list">{OPENER_HTML}</div>'
               '<p class="hooknote" style="margin-top:16px">We try these in order for each person, and always have the safe opener as backup.</p></section>')
    checks = [
        ("Spelling &amp; grammar", "every line read and fixed"),
        ("Merge fields fill in", "no blank [First name] or [Company] slips through"),
        ("Links work", "every link opened and checked"),
        ("Unsubscribe line present", "an easy opt-out on every email"),
        ("No spam-trigger words", "wording that stays out of the junk folder"),
        ("Sending addresses are healthy", "warmed-up domains, good reputation"),
        ("Daily send caps set", "we ramp up slowly, never blast"),
        ("Nobody emailed twice", "checked against everyone we've contacted before"),
    ]
    chk_rows = "".join(
        f'<div class="chk"><span class="ck"></span><div><div class="cl">{l}</div><div class="cn">{n2}</div></div></div>'
        for l, n2 in checks)
    p_build = ('<section class="panel p-build"><p class="eyb">Build</p>'
               '<p class="chkhead">This is the one step that pulls real data. When you build, we pull the real list '
               '(or arm the trigger for an ongoing signal) and run every check below. Nothing sends until it\'s Live.</p>'
               f'<div class="checks">{chk_rows}</div>'
               '<button class="build-btn">Build the campaign</button></section>')
    p_live = (f'<section class="panel p-live"><p class="eyb">Live</p>'
              f'<div class="livebanner">Not live yet — the campaign turns on when you approve it. Nothing sends until then.</div>'
              f'<div class="tiles">'
              f'<div class="tile"><div class="tn">{num(pool)}</div><div class="tl">in the pool</div></div>'
              f'<div class="tile"><div class="tn">—</div><div class="tl">emailed</div></div>'
              f'<div class="tile"><div class="tn">—</div><div class="tl">replies</div></div>'
              f'<div class="tile"><div class="tn">—</div><div class="tl">meetings booked</div></div></div>'
              f'<p class="planline">Once it\'s on, we email all {num(pool)} at a steady, safe pace and track every reply, positive reply and meeting right here.</p></section>')

    if layout == "a":   # NUMBER LEADS — tabs on top, then title; description + hero number on the Targeting page only
        p_tgt = (f'<section class="panel p-tgt">{desc}<div class="tgt-hero">{num_big(idea, note=False)}</div>'
                 f'{targeting_sections(idea, include_who=False)}</section>')
        head = f'{toptabs}{title}'
    elif layout == "b":  # HEADER KPI — number sits top-right of the page header, always visible
        p_tgt = f'<section class="panel p-tgt">{targeting_sections(idea)}</section>'
        head = (f'<div class="hdr-b"><div class="hl">{status}{title}{mech_pill(idea)}</div>'
                f'{num_big(idea, "right")}</div>{pills}{desc}')
    else:               # C — REACH BAND — a contained band under the tabs, always visible
        p_tgt = f'<section class="panel p-tgt">{targeting_sections(idea)}</section>'
        band = (f'<div class="band"><div class="band-l"><p class="eyb">The angle</p>{mech_pill(idea)}</div>'
                f'{num_big(idea, "right")}</div>')
        head = f'{status}{title}{pills}{band}{desc}'

    return (f'<section id="i{n}" class="idea-view iv-{n}"><div class="wrap">'
            f'{radios}{head}'
            f'<div class="panels">{p_tgt}{p_copy}{p_first}{p_build}{p_live}</div>'
            f'</div></section>')

# ---------------------------------------------------------------- assemble
def build(layout):
    css = CSS.replace("__FONT__", FONT_B64) + tab_css() + "\n" + ideanav_css()
    idea_radios = "".join(
        f'<input class="tabin" type="radio" name="idea" id="idea-i{i}"{" checked" if i==1 else ""}>'
        for i in range(1, len(IDEAS) + 1))
    views = "".join(idea_view(idea, i, i == 1, layout) for i, idea in enumerate(IDEAS, 1))
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>Navreo · Strategy ({layout.upper()})</title><style>" + css + "</style></head><body>"
            f'<div class="app">{idea_radios}{sidebar()}<main class="work">{views}</main></div></body></html>')

out = HERE / "strategy-integrated-a.html"
out.write_text(build("a"), encoding="utf-8")
print(f"wrote {out.name}  ({len(out.read_text())//1024} KB) — Number leads, refined")
