---
name: create-figma-diagram
description: Turn campaign copy (cold-email openers plus follow-ups, or any related set of messages or flow) into a FigJam board in Navreo's campaign-map style: one lane per campaign, opener cards on top converging via connectors into Soft and Hard follow-up cards, colour-coded (amber = hard, blue = soft), full verbatim copy, left-aligned text. Use this skill whenever the user wants to map, diagram, lay out, or visualise campaigns, email sequences, or message flows in Figma or FigJam, turn copy into a board, build a campaign map, or compare openers and follow-ups visually, EVEN IF they don't say "FigJam" or name the tool. Trigger phrases: 'create a figma diagram', 'map these campaigns in figma', 'turn this copy into a figma board', 'make a figjam board of these emails', 'visualise the sequence', 'campaign map in figma', 'lay out the openers and follow-ups', 'diagram these campaigns', 'put this copy on a board'. This is for FigJam boards (the /board/ style), not Figma design files.
---

# Create Figma Diagram

Build a FigJam board that maps one or more campaigns the way the Navreo "GenAI Copy" board does: each campaign is a vertical lane, the opener-email variants sit in a row at the top, and connectors fan downward and converge into the follow-up card(s) below.

The visual grammar:

```
   [Opener A] [Opener B] [Opener C] [Opener D]      <- a row of opener cards
        \         \        /          /
         \         \      /          /
          v         v    v          v
        [ Hard follow-up ]  [ Soft follow-up ]      <- openers converge into follow-ups
   ----------------------------------------------    (one lane per campaign, repeated)
```

## Why generate_diagram, not use_figma

Use the Figma MCP `generate_diagram` tool (mermaid to FigJam) to build the structure. It is reliable, creates its own FigJam file, and lays out the cards, connectors, and lanes automatically. Do NOT hand-build the board with `use_figma` for layout: that path is fiddly, easy to get wrong, and reinvents the connector and layout logic `generate_diagram` gives for free. The one thing `generate_diagram` cannot do is left-align text, so a single small `use_figma` pass handles that afterward (Step 4).

## Inputs to gather first

1. The full copy for every opener and every follow-up. Use it VERBATIM in the cards (greeting, body, CTA, signature, and PS where present). The whole point of the board is to review the real copy, so do not paraphrase or trim.
2. The campaign theme and the sender name for each lane (used as the lane title).
3. The Hard/Soft classification of each opener and the follow-up routing. Do not guess this silently. Confirm it with the user, because it drives the connectors. See "Hard vs Soft" below.

If the copy still needs writing or editing, that is a `lilly-copywriter` job; this skill is about laying finished copy onto a board.

## Step 1: Get the plan key

`generate_diagram` needs a `planKey`. Call `whoami` (Figma MCP) and use the team key. For Navreo this is `team::1132024539694497538`, but confirm via `whoami` in case it changed or there are multiple plans.

## Step 2: Build the mermaid

Write a `flowchart TD`. One `subgraph` per campaign (the lane), titled `"CAMPAIGN N · Theme · Sender"`. Inside each lane, declare an opener node per variant and a node per follow-up, then add the edges that route each opener to the follow-up it feeds.

- Node label = an authored tag line, then `<br/><br/>`, then the verbatim copy with each paragraph separated by `<br/><br/>`.
- Tag line carries the email label and the HARD/SOFT classification, e.g. `EMAIL 1A · Capability Intro · HARD`.
- Edges: `C1A --> C1H` (hard opener to hard follow-up), `C1C --> C1S` (soft opener to soft follow-up).
- Colour-code with `classDef`: hard = amber, soft = blue, openers pale, follow-ups saturated. This makes the two tracks readable at a glance. (Exact hex values are in the worked example.)

### Mermaid gotchas (these break the parse or the render)

- Quote every node label: `ID["..."]`.
- Use `<br/>` for line breaks. NEVER a literal `\n`.
- No em-dashes anywhere (Navreo house rule and they read badly). Use `·`, a colon, or a hyphen as separators.
- Replace `&` with the word "and" in any subgraph title or label. A raw ampersand breaks mermaid.
- Inside a label, use parentheses, not square brackets. `[ ]` inside a `["..."]` label can confuse the parser. (`[First Name]` is fine inside the quoted string in practice, but if a parse error appears, suspect brackets first.)
- Node IDs must be unique across the whole diagram. Prefix per campaign (`C1A`, `C2A`, `C3A`).
- Avoid stray pipe `|` characters in label text.

See `references/worked-example.md` for a complete, copy-pasteable lane plus the `classDef` block.

## Step 3: Generate the board

Call `generate_diagram` with the `planKey`, a descriptive `name`, a one-line `userIntent`, and the `mermaidSyntax`. Do NOT pass a `fileKey` (that appends a second diagram to an existing file and overlaps it). Omitting `fileKey` creates a fresh FigJam file. The result returns a `claimFileUrl` like `https://www.figma.com/board/<fileKey>` and the `fileKey` you need for the next steps.

## Step 4: Left-align the text

`generate_diagram` centres card text; the reference style is left-aligned. Run one `use_figma` pass on the new `fileKey` with the snippet in `references/worked-example.md`. It walks every node and sets `textAlignHorizontal = "LEFT"` (on `TEXT` nodes directly, on the `.text` sublayer for `SHAPE_WITH_TEXT` and `STICKY`). This works on FigJam shapes (verified). The tool reports no return value, so do not trust silence; confirm with a screenshot in Step 5.

## Step 5: Verify

Call `get_screenshot` on the new `fileKey`, node `0:1`. Campaign maps are very wide, so a single full-board capture is too short to read. Capture at a high `maxDimension`, download the PNG with `curl`, then crop one lane with Python PIL and read that crop to confirm the copy rendered and the text is left-aligned (ragged-right edges). The exact commands are in the worked example. Shift the crop window to spot-check each lane.

## Step 6: Report and tidy up

Give the user the canonical board URL. Note that `generate_diagram` makes a NEW file on every run, so each revision of the board is a separate file; tell the user which one is current and that earlier iterations can be deleted in Figma (this skill should not delete their files). If a card carries an open question for the client (a missing case-study detail, an unconfirmed claim), surface it in the report so it is not forgotten.

## Hard vs Soft (the routing logic)

This classification drives every connector, so get it right and confirm with the user.

- HARD opener = a direct ask to engage: a call, a consultation, or an invitation to something. CTAs like "Would this be of interest?" or "Want me to send the details?".
- SOFT opener = a permission-to-share value play: "Can I share how it works?", "Mind if I share the case study?".

Follow-ups are the COMPLEMENT of the opener, which avoids repeating the same ask:
- Hard openers feed the value/proof follow-up (a case study). They already asked for the call, so the follow-up brings evidence instead.
- Soft openers feed the consultation/call follow-up. They already offered value, so the follow-up escalates to the direct ask.

So on the board: hard openers connect to the Hard follow-up, soft openers connect to the Soft follow-up. Tag and colour each card by its own class (hard = amber, soft = blue).

## Compatibility

Needs the Figma MCP tools: `whoami`, `generate_diagram`, `use_figma`, `get_screenshot`. Needs `curl` and Python with PIL for the verification crop.
