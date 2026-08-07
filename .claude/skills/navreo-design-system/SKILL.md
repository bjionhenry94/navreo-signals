# Navreo Design System — Skill

Use this skill whenever you're producing artifacts for **Navreo** (decks, prototypes, web pages, marketing). It contains the absolute essentials. Read `README.md` for the full rationale.

## ⚪ WHITE APP VARIANT — canonical for product UI, prototypes and ALL artifacts (Bjion, 2026-07-18)

The live signals tool sets the colourway. **Page is WHITE; cream demotes to secondary surfaces.** Source of truth: `app/navreo.css` in the Navreo repo.

- Page `#FFFFFF` · sunken/secondary surface `#F7F7F6` · cards white with border `--line #ECECEA` (stronger divider `--line-2 #DDDDDA`)
- Ink scale unchanged: `#14110E` / `#3A332C` / `#6B6055` · orange `#FF4D00` still the ONE accent (soft fill `#FFE4D6`)
- Cream `#F9F0E7` = occasional secondary surface only (e.g. a mail-frame header band) — never the page
- Semantic triples: green `#2E7D5B` on `#E2F1E9` (line `#C4E2D3`) · amber `#8F6600` on `#F8EAC4` (`#EBD79E`) · red `#C2371F` on `#F7DCD5` (`#EFC7BB`)
- Chart/data series ONLY: blue `#1971C2` · purple `#7048E8` · green `#2F9E44` · orange `#E8590C` · red `#E03131`
- Radius 12px · focus ring `rgba(255,77,0,.32)` · white-on-white cards MUST carry their line border
- Type rules unchanged (Acid Grotesk display, DM Sans body, mono numbers)

The cream-page palette below remains for **brand/marketing moments** (decks, carousels, print) — not for product-style surfaces.

## TL;DR

- **Voice:** direct, plain, confident. Use contrast pairs (*"…not your headcount"*). No hype words. No emoji.
- **Palette (brand/marketing):** cream `#F9F0E7` is the page. Ink `#14110E` is text. Orange `#FF4D00` is the *one* accent. Light brown `#F2E5D9` is for cards. Dark brown `#C0B0A0` is muted/dividers. **For product UI / artifacts use the WHITE APP VARIANT above.**
- **Type:** Acid Grotesk for display (h1, h2, hero numbers — Regular only, large + tight). DM Sans for body, UI, h3+, eyebrows. Negative tracking on display (-0.03em). Headlines end in periods.
- **Layout:** lots of cream space. One orange element per screen. Generous gutters. Asymmetric columns over centered.
- **Numbers are heroes.** `1,500+`, `$15M+`, `50+` — set them at 76–128px, weight 500.
- **Process steps** are always two-digit: `01 / 02 / 03`. Pair with `Month 1` / `Month 2` / `Month 3` when relevant.

## Setup in any artifact

```html
<link rel="stylesheet" href="path/to/colors_and_type.css">
<body class="navreo">…</body>
```

The `navreo` class on `<body>` applies font, background, and color defaults. Tokens are CSS variables — see `colors_and_type.css`.

## Logos

- `assets/logo-navreo.png` — black on transparent. Use on cream / light brown.
- `assets/logo-navreo-white.png` — cream/white. Use on ink or orange.
- `assets/logo-navreo-orange.png` — orange. Sparingly, one editorial moment max.

Min size 64px wide. Clear-space ≥ height of the `n`.

## CTA copy

Use only:
- **Primary:** *Book a call* / *Book a free call* (orange pill)
- **Closing:** *Let's Chat* (closing footer band)

Don't introduce *Sign up*, *Get started*, *Try free* — Navreo isn't self-serve.

## Eyebrow vocabulary (from navreo.ai)

`WHO WE ARE` · `WHY CHOOSE US` · `WHAT DO WE DO?` · `HOW WE WORK` · `CASE STUDY` · `FAQ`

Add new ones in the same register: short, uppercase, tracked +0.12em.

## Don't

- Don't say "AI-powered" — even though the domain is `.ai`, the brand never leans on this phrase.
- Don't use Title Case for headlines (sentence case; named offerings can be Title Case).
- Don't add gradients, glassmorphism, or neon glows.
- Don't use shadows + heavy borders together. Pick one.
- Don't use emoji.
- Don't put orange on light brown without a 1px darker border.
- Don't invent new accent colors. The system has one.

## Quick references

- Buttons primary: `--nav-orange` bg, `--nav-cream` text, `--r-pill` radius, `10px 20px` padding.
- Cards: glass — `rgba(255,255,255,0.18)` + `backdrop-filter: blur(22px) saturate(140%)`, 1px white-tinted hairline `rgba(255,255,255,0.35)`, inset top highlight, **no drop shadow**. White text. Must sit on a multi-hue blurred backdrop (violet → peach canonical). On flat cream, fall back to cream-50 fill + hairline.
- Hero number block: 3-column grid, top hairline border, weight 500, 76–92px, line-height 0.95.
- Process step card: ink black + cream text for the active step; cream-50 + ink for the others.

## Caveats

- Only `AcidGrotesk-Normal.otf` is licensed in this project, so Acid Grotesk is restricted to display sizes (h1/h2/hero numbers, Regular only). DM Sans handles everything below h2 because it ships full weight range. Drop additional Acid Grotesk `.otf`s in `fonts/` and add `@font-face` rules to lift more of the system back to the brand face.
- No internal codebase or Figma was provided. The component shapes in `preview/` are extrapolated from the public site — review against real product before treating as canonical.
