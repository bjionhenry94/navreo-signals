# Worked Example

A complete, runnable pattern for one campaign lane (two hard openers, two soft openers, two follow-ups). Copy this shape, swap in the real copy, repeat the `subgraph` block per campaign. Node copy below is abbreviated with `...` only to keep this file short; in a real run paste the FULL verbatim copy (greeting, body, CTA, signature, PS) into each node.

## The mermaid (pass as `mermaidSyntax` to `generate_diagram`)

```
flowchart TD

subgraph SG1["CAMPAIGN 1 · Geopolitical Risk · Aidan Harte"]
C1A["EMAIL 1A · Capability Intro (Call) · HARD<br/><br/>Hey [First Name],<br/><br/>A lot of companies we've spoken to recently have mentioned ...<br/><br/>In a 30-minute consultation, ...<br/><br/>Would this be of interest?<br/><br/>Aidan Harte<br/><br/>P.S. We do this for Fortune 100 companies navigating moments exactly like this."]
C1B["EMAIL 1B · Invitation (Chatham House) · HARD<br/><br/>Hi [First Name],<br/><br/>... and I wanted to extend an invite to you.<br/><br/>Happy to send the details and who else will be in the room. Want me to?<br/><br/>Aidan Harte<br/><br/>P.S. ..."]
C1C["EMAIL 1C · Invitation (AI process) · SOFT<br/><br/>Hi [First Name],<br/><br/>...<br/><br/>Can I share how it works?<br/><br/>Aidan Harte<br/><br/>P.S. ..."]
C1D["EMAIL 1D · Case Study · SOFT<br/><br/>Hey [First Name],<br/><br/>...<br/><br/>Mind if I share the case study?<br/><br/>Aidan Harte<br/><br/>P.S. ..."]
C1H["HARD FOLLOW-UP · to hard openers (1A, 1B)<br/><br/>Hey [First Name],<br/><br/>As an alternative in case the previous email wasn't a fit, ...<br/><br/>Mind if I share the case study?<br/><br/>Aidan Harte"]
C1S["SOFT FOLLOW-UP · to soft openers (1C, 1D)<br/><br/>Hey [First Name],<br/><br/>As an alternative in case the previous email wasn't a fit, ...<br/><br/>Would this be of interest?<br/><br/>Aidan Harte"]
C1A --> C1H
C1B --> C1H
C1C --> C1S
C1D --> C1S
end

classDef hardOpener fill:#FFF4E6,stroke:#F4B873,color:#5A3206;
classDef softOpener fill:#EEF5FF,stroke:#9DC3F7,color:#123A6B;
classDef hardFU fill:#FFE0BB,stroke:#E8923C,color:#5A3206;
classDef softFU fill:#D3E4FF,stroke:#5B97E8,color:#0B3D91;
class C1A,C1B hardOpener;
class C1C,C1D softOpener;
class C1H hardFU;
class C1S softFU;
```

Notes on the example:
- Node IDs (`C1A`, `C1H`, ...) must be unique across the WHOLE diagram, so prefix per campaign (`C2A`, `C3A`, ...).
- `flowchart TD` puts openers in a row at the top and follow-ups beneath, so the connectors fan downward and converge, matching the reference board.
- Independent subgraphs (no edges between them) tile as separate lanes; the user can drag them around in FigJam afterward.

## Left-align snippet (pass as `code` to `use_figma`)

`generate_diagram` centres text in every card. Run this once on the new file to left-align everything. It returns no value (the harness does not surface returns), so confirm the result with a screenshot.

```js
const all = figma.currentPage.findAll(() => true);
for (const n of all) {
  try {
    if (n.type === "TEXT") n.textAlignHorizontal = "LEFT";
    else if (n.type === "SHAPE_WITH_TEXT" || n.type === "STICKY") n.text.textAlignHorizontal = "LEFT";
  } catch (e) {}
}
```

## Verify on a wide board

Campaign maps get very wide (often 8:1+), so a full-board screenshot is too short to read. Capture at high resolution, then crop one lane with Python to read the copy and confirm left-alignment.

```bash
curl -s -o /tmp/board.png "<image_url from get_screenshot>"
python3 -c "from PIL import Image; im=Image.open('/tmp/board.png'); im.crop((0,0,2600,im.height)).save('/tmp/lane.png')"
```

Then read `/tmp/lane.png`. Shift the crop window (e.g. `(2600,0,5200,im.height)`) to inspect the next lane.
