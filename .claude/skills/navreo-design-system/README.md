# Navreo Design System

A minimal, warm, editorial design language for **Navreo** — set in a low-key cream paper palette with a single high-voltage orange accent and a confident grotesque wordmark.

## Index

| File / Folder | Purpose |
|---|---|
| `README.md` | This file — brand context, content fundamentals, visual foundations, iconography. |
| `SKILL.md` | Agent skill manifest. Tells Claude (or any agent) how to use this system. |
| `colors_and_type.css` | Color tokens, type scale, spacing, radius, shadows. Import in every artifact. |
| `assets/` | Logos, marks, brand imagery. |
| `fonts/` | Webfonts (currently linked from Google Fonts — see *Type substitution*). |
| `preview/` | Cards rendered in the project's Design System tab — swatches, type specimens, components. |
| `ui_kits/` | High-fidelity component libraries per product surface. |
| `slides/` | (Not built — no deck template was provided.) |

## Sources used

- **`uploads/logo.png`** — the Navreo wordmark (`navreo` lowercase, black on transparent, 382×57). Re-tinted to white and orange in `assets/`.
- **`fonts/AcidGrotesk-Normal.otf`** — the licensed brand face, loaded via `@font-face` and active across all artifacts. Only the Normal weight is present; bolder weights are browser-synthesized. See *Acid Grotesk — installed* below.
- **Brand color notes** (provided directly):
  - Dark Brown `#C0B0A0`
  - Cream `#F9F0E7`
  - Orange `#FF4D00`
  - Light Brown `#F2E5D9`
- **navreo.ai** — fetched April 2026 for content fundamentals, voice, structure, and the canonical eyebrow/CTA vocabulary.

No internal codebase or Figma was provided, so the *visual* foundations below are an interpretation derived from the wordmark, palette, typeface, and the public site — not a recreation of an internal kit. The *content* fundamentals are grounded in observed copy.

---

## Brand context

**Navreo** builds **go-to-market systems** for B2B sales teams — outbound, content, and intent-signal engines that run on autopilot. It's a *services + systems* business, not a SaaS product. The headline promise on navreo.ai: **"Go-to-market systems that scale your revenue, not your headcount."**

What this means for the design system:

- **Operator-confident, not startup-shiny.** The audience is COOs, founders, agency owners, and sales leaders who have heard every lead-gen pitch. The visual language must read as senior, considered, and proven — closer to a private consultancy than to a B2B SaaS landing page.
- **Cream + ink + one orange.** The cream palette signals craft and patience (these are 90-day systems, not magic buttons). The orange (`#FF4D00`) is the moment of conviction — the CTA, the headline number, the moment we say "this works."
- **Numbers carry the story.** The site leads with hard counters: *1,500+ hours saved · $15M+ pipeline · 50+ teams · 5M emails · 12M impressions · 7-figure partnerships*. Treat large numerals as a hero element in their own right.
- **Process, not product.** The site is structured as *system → method → proof*. Components are designed to support diagrammatic content (process steps 01/02/03, before-vs-after comparisons, case-study tiles), not feature grids.

Treat Navreo as *quiet by default, loud when it matters.*

---

## Content fundamentals

The voice rules below are derived from observed copy on **navreo.ai**.

**Voice.** Direct, plain, confident. The site is full of declarative statements: *"The tools exist. The channels are live. What is missing is one connected system."* Short sentences. Verbs do the work. Hedging is rare. Hype words ("revolutionary", "game-changing", "AI-powered") are absent — even though the company is `.ai`, it never leans on the phrase "AI-powered" as a value prop. Don't add it.

**A signature rhythm: contrast pairs.** Navreo's strongest lines work by setting one thing against another:
- *"…scale your revenue, not your headcount."*
- *"…stops depending on referrals and starts running on a system."*
- *"…not just a list of leads."*
- *"The old way · Modern GTM System."*

Use this construction in headlines and section leads. It carries the brand tone better than a single declarative line.

**Person.** Speak as **we** about Navreo, address the reader as **you**. *"We build outbound and content systems… Either way, your pipeline stops depending on referrals."* Avoid third-person ("Navreo helps companies…") on owned surfaces.

**Casing.**
- **Sentence case for body and most headers.** *"How we generate your pipeline."*
- **Title Case is acceptable on labelled section bullets and pillar names** — the site does this for *Cold Outreach That Actually Converts* and *Drive Warm Inbound*. Treat these as named offerings, not headlines.
- The wordmark is always lowercase: **navreo**. In running prose, "Navreo" is correct.
- Eyebrow labels are uppercase, tracked +0.12em. Examples observed on the site: `WHO WE ARE`, `WHY CHOOSE US`, `WHAT DO WE DO?`, `HOW WE WORK`, `CASE STUDY`, `FAQ`.

**Punctuation.** Periods end sentences and headlines (the site headlines all carry final periods — keep this). Em dashes for asides. Semicolons appear in lists of triggers: *"new funding, hiring surges, leadership changes."* No exclamation marks anywhere.

**Numbers.** **Numerals always**, even at the start of sentences. Big proof numbers are the hero — give them their own line and use the display weight (500 medium) at 80–128px:
- `1,500+` — hours saved per month
- `$15M+` — pipeline generated
- `50+` — teams coached
- `5M` — emails sent
- `12M` — LinkedIn impressions
- `7-fig`, `6 and 7-figure` — deal sizes
- `01 / 02 / 03` — process steps, always two-digit

**Process steps.** Always number them with two digits: `01 Build and Launch · 02 Learn and Amplify · 03 Scale`. Pair each with a Month label (`Month 1`, `Month 2`, `Month 3`) when the timeline is the point.

**CTA vocabulary.** The site uses exactly two:
- **Primary:** `Book a call` / `Book a free call` — orange pill button
- **Secondary:** `Let's Chat` — used in the closing footer band

Stay within this set. Don't introduce *Sign up*, *Get started*, *Try free* — Navreo doesn't sell self-serve software.

**Eyebrow vocabulary, observed.** `WHO WE ARE`, `WHY CHOOSE US`, `WHAT DO WE DO?`, `HOW WE WORK`, `CASE STUDY`, `CASE-STUDIES`, `FAQ`. Short, tracked, all-caps. New eyebrows should fit the same register.

**Don't say.**
- "AI-powered" / "powered by AI" — even though the domain is `.ai`, the site never leans on this phrase. The intelligence is implied through outcomes, not labels.
- "Revolutionary", "game-changing", "next-gen", "cutting-edge".
- "Solutions" used as a noun.
- "Empower", "unlock", "supercharge".
- Emoji. Not on owned surfaces.

**Examples (real lines from navreo.ai, for reference):**
- "Go-to-market systems that scale your revenue, not your headcount."
- "Trusted by B2B leaders who needed pipeline yesterday."
- "Most outreach misses because the timing is wrong."
- "From zero to a pipeline that runs itself."

---

## Visual foundations

### Color

Four brand colors carry the system; everything else is derived.

| Token | Hex | Use |
|---|---|---|
| `--nav-cream` | `#F9F0E7` | Default page background. The "paper". |
| `--nav-light-brown` | `#F2E5D9` | Card fills, sunken regions, alternate stripes. |
| `--nav-dark-brown` | `#C0B0A0` | Muted accents, dividers, disabled state, decorative. |
| `--nav-orange` | `#FF4D00` | The single accent. Primary CTA, focus, key data, links on hover. |
| `--nav-ink` | `#14110E` | Body text. A near-black, never pure black. |

**Rules of thumb.**
- Use orange like a highlighter — *one* meaningful place per screen, not a wash.
- Never put orange on light brown without a 1px darker border; the contrast is real but the boundary helps.
- Pure white is reserved for in-product surfaces that need maximum legibility (modals, code blocks). Cream is the default.
- Dark mode inverts to ink (`#14110E`) backgrounds with cream text; orange stays the same hex.

### Type

- **Display + headlines**: **Acid Grotesk** (`fonts/AcidGrotesk-Normal.otf`). Used for h1, h2, hero numbers, the wordmark.
- **Body, UI, small type**: **DM Sans** (Google Fonts, weights 300–700). Used for everything below h2 — body, buttons, labels, eyebrows, inputs, captions.
- **Mono**: JetBrains Mono.
- **No serif.** A serif would conflict with the grotesque-only mark.

Why split? Only the Normal cut of Acid Grotesk is licensed in the project, so anything that needs heavier weights (button labels, eyebrows, body bolds) uses DM Sans, which carries the full weight range natively. DM Sans is geometrically compatible with Acid Grotesk — similar x-height and aperture — so the pairing reads as one voice.

Weights used: **400, 500, 600, 700** (DM Sans) and **400** (Acid Grotesk, regular only). Display headlines therefore use Acid Grotesk Regular at large sizes — the size + tight tracking carry the weight, no synthetic bolding needed.

Tracking is *negative* on display sizes (`-0.03em` at 80px+) and slightly negative on body (`-0.015em`). Eyebrow labels track *wide* (`+0.12em`) and uppercase.

#### Acid Grotesk + DM Sans pairing — installed

- **Acid Grotesk** (`fonts/AcidGrotesk-Normal.otf`) — the licensed brand face. Display + headlines (h1, h2, hero numbers) only. Regular weight only — keep it large and well-tracked; no synthetic bolding.
- **DM Sans** (loaded from Google Fonts) — body, UI, h3+, buttons, labels, eyebrows. Carries the full 300/400/500/600/700 range natively.
- **Action when needed:** drop additional Acid Grotesk weights (e.g. `AcidGrotesk-Medium.otf`) into `fonts/` and add matching `@font-face` blocks to lift more of the system back onto the brand face.

### Spacing

A 4-pt grid. Tokens `--sp-1` (4px) through `--sp-32` (128px). Default page gutter is `clamp(20px, 4vw, 56px)`. Sections breathe — vertical rhythm between sections is 96–128px on desktop, 56–80px on mobile.

### Backgrounds

- **Default:** flat cream. No gradients on default surfaces.
- **Hero / section breaks:** flat orange (`#FF4D00`) full-bleed bands, with cream text. Sparingly — once per page max.
- **Decorative:** subtle paper-grain noise overlay at ~3% opacity is allowed (`assets/grain.svg`). It must never be readable as a texture; it should disappear at arm's length.
- **Imagery:** warm, slightly desaturated, natural light. Avoid cool/blue-cast photography. Avoid stock-y office photography. If illustration is used, it should be flat, single-color (orange or ink), no gradients.
- **Never:** purple-blue gradients, glassmorphism, mesh gradients, neon glows.

### Animation

- **Default easing:** `cubic-bezier(0.2, 0.7, 0.2, 1)` — fast-out, settle. Feels like paper landing.
- **Durations:** 120 / 180 / 260 / 420 ms. Anything longer than 420 ms on a UI control is too long.
- **No bounces.** Springs only on illustrative elements (e.g. a confetti drop), never on buttons or menus.
- **Page transitions:** 12px upward translate + opacity fade, 260 ms.
- **Reduced motion:** respect `prefers-reduced-motion` — disable all transforms, keep opacity only.

### Hover states

- **Buttons (primary):** `--nav-orange-600` (`#DB4100`, ~6% darker). No scale, no shadow change.
- **Buttons (secondary, on cream):** background shifts to `--nav-light-200`, border darkens to `border-strong`.
- **Links:** underline appears (text-decoration: underline; thickness 1.5px; offset 3px). Color stays ink unless inside a body paragraph where the link is already orange.
- **Cards:** `transform: translateY(-2px)` and shadow steps from `--shadow-1` to `--shadow-2`. 180 ms.

### Press states

- **Buttons:** `--nav-orange-700` (`#A83100`) and `transform: translateY(1px)`. No scale.
- **Touch targets:** minimum 44×44 px.

### Borders & dividers

- **Hairlines** are `rgba(20,17,14,0.10)` (`--border`) — barely visible, define the form, never compete with content.
- **Strong borders** (`--border-strong`, `0.22`) only on focused inputs and active selection.
- Dividers between rows use `--divider` (`#E8D7C4` — light brown 200), 1px, full-bleed inside containers.

### Shadows / Elevation

Navreo prefers **borders + flat fills** over shadows. The shadow scale is intentionally short:

- `--shadow-1` — resting card. Almost imperceptible; just lifts off cream.
- `--shadow-2` — hovered card, inline popover.
- `--shadow-3` — floating menu, dialog. The deepest shadow in the system.
- `--shadow-inset` — used on input fields when paired with a flat background to suggest depth without a border.

Never stack shadow with a heavy border — pick one.

### Capsules vs. protection gradients

Navreo uses **capsules over gradients**. A pill-shaped chip on the cream background is the canonical way to put text over imagery. Reserve protection gradients for full-bleed orange or ink hero photography only.

### Layout rules

- **Max page width:** 1280px, but most content sits in a 960px reading column.
- **Asymmetric columns** are encouraged — the brand likes a 5/7 or 4/8 split with editorial rag rather than dead-centered hero copy.
- **Fixed elements:** header is `position: sticky; top: 0;` with `backdrop-filter: blur(12px)` and a translucent cream background (`rgba(249,240,231,0.78)`). No fixed footer chat bubbles, no cookie banners that overlay content.

### Transparency & blur

- **Sticky header**: 78% cream + 12px backdrop-blur.
- **Modals**: scrim is `rgba(20,17,14,0.45)` over the page, content sits on cream-50.
- **Glass is allowed on content cards** — see *Cards* below — but never on inputs, modals, or chrome.

### Corner radii

The system has a **specific personality**: small radii on inputs, generous on cards, full-pill on chips and primary CTAs.

- Buttons (primary): `--r-pill` (full pill).
- Buttons (secondary, icon): `--r-md` (8px).
- Inputs: `--r-md` (8px).
- Cards: `--r-xl` (18px).
- Hero modules / large surfaces: `--r-2xl` (28px).
- Avatars: `--r-pill`.

### Cards

Cards use a **glass** treatment — translucent white over a multi-hue blurred backdrop, with a soft inner highlight and **almost no drop shadow**. They feel lifted by light, not by elevation. The reference is the diagram cards on navreo.ai (orange + violet + cream hue field with white pill cards floating over it).

- **Glass fill:** `rgba(255,255,255,0.18)` over the backdrop.
- **Backdrop filter:** `blur(22px) saturate(140%)`.
- **Hairline:** 1px in `rgba(255,255,255,0.35)` — a *light-edge* border, not a dark one.
- **Inner highlight:** `inset 0 1px 0 rgba(255,255,255,0.35)` — gives the card its top-edge gleam.
- **Shadow:** none, or at most `0 1px 0 rgba(0,0,0,0.04)`. The lift comes from the light edge + blur, not a drop shadow.
- **Type on glass:** white, weight 500. Display headlines stay in Acid Grotesk; body in DM Sans.
- **Shape:** pill (`--r-pill`) for diagram nodes and small cards; `--r-2xl` (28px) for larger content tiles.
- **Padding:** `--sp-5` `--sp-6` for pill nodes, `--sp-8` for content tiles.

#### Backdrop — required canvas

Glass cards need a **multi-coloured blurred hue field** behind them. The canonical recipe:

```css
background:
  radial-gradient(28% 32% at 78% 62%, rgba(255,140,80,0.95) 0%, transparent 70%),
  radial-gradient(34% 30% at 60% 78%, rgba(255,90,140,0.70) 0%, transparent 70%),
  radial-gradient(40% 36% at 22% 30%, rgba(150,120,220,0.80) 0%, transparent 70%),
  radial-gradient(30% 28% at 88% 18%, rgba(240,210,230,0.70) 0%, transparent 70%),
  linear-gradient(140deg, #7a63b4 0%, #a07cc2 55%, #ffb38a 100%);
filter: blur(28px) saturate(120%);
```

Three palettes are approved: **violet→peach** (canonical), **violet→teal→ochre** (cool variant), and **violet→magenta→orange** (warm variant). Always blur the field by 24–32px so the colors read as washes, not shapes.

> Glass is reserved for **diagram cards and content cards** that sit on a hue backdrop. On flat cream pages, cards fall back to flat cream-50 with a hairline — no glass.

### Imagery & color vibe

- **Warm, natural, slightly grainy.** Think 35mm film, golden hour.
- **Never cool blue, never high-saturation neon, never AI-cinematic with rim-light.**
- **B&W is allowed** for portraits and editorial — it pairs naturally with cream.
- Avoid stock-photo tropes (laptops + smiles, conference rooms, abstract data visualisations).

---

## Iconography

> ⚠️ No icon set was provided in the upload.

**Recommendation: [Lucide Icons](https://lucide.dev/)** — open source, MIT-licensed, geometric, 1.75px stroke weight that pairs naturally with Space Grotesk's geometry. Loaded from CDN:

```html
<script src="https://unpkg.com/lucide@latest"></script>
<i data-lucide="arrow-right"></i>
<script>lucide.createIcons();</script>
```

**Stroke and size guidance.**
- Stroke width: **1.75px** (Lucide default). Do not mix 1px and 2px icons in the same view.
- Sizes: 16, 20, 24, 32 px. 16/20 in dense UI, 24 inline with body, 32 in hero modules.
- Color: inherits text color. The only icon that ever takes orange is a state icon (e.g. an active filter dot).

**Emoji.** Not used in product or marketing. Not used as section markers. Not used in error states.

**Unicode glyphs.** Acceptable for arrows in dense data UI: `→`, `↗`, `–`, `·`, `×`. Never `✓` or `✕` — use Lucide's `check` and `x` so stroke weights match.

**Logo usage.**
- `assets/logo-navreo.png` — black wordmark, transparent. Use on cream / light brown.
- `assets/logo-navreo-white.png` — cream wordmark. Use on ink or full-bleed orange.
- `assets/logo-navreo-orange.png` — orange wordmark. Use sparingly — typically a single editorial moment per artifact.
- Minimum clear-space around the wordmark: equal to the height of the `n`. Minimum size: 64px wide on screen, 18mm in print.
- Never stretch, recolor outside the three approved tints, add a drop-shadow, or place on a busy photograph without a flat backdrop.

---

## Caveats & open questions

1. **Only the Normal weight of Acid Grotesk is installed.** Other weights are synthesized — drop additional `.otf` files in `fonts/` to upgrade.
2. **No internal codebase / Figma was provided.** Component shapes are extrapolated from navreo.ai. Review against real product before treating as canonical.
3. **No deck template provided** → `slides/` is intentionally empty.

