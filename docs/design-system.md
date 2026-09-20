# Design system

Prosody's interface is a single monochrome system. There is **no accent hue
anywhere in the product**: emphasis is carried by luminance, weight and rule
thickness, the way a well-made plugin panel does it.

Three reasons it is built this way, not just taste:

1. Colour in an arranger should mean something musical. Once nothing is
   coloured, the one thing that *is* — section energy, as a white wash — reads
   instantly.
2. Status stays legible on the badly-calibrated second monitor most studios
   actually use.
3. It cannot drift. There is no palette to extend, so no screen can quietly
   introduce a fifth blue.

## Files

| File | Holds |
| --- | --- |
| `src/styles/tokens.css` | every colour, size, space, radius and duration |
| `src/styles/base.css` | reset, typography scale, shell and rhythm utilities |
| `src/styles/components.css` | the component system |
| `src/styles/home.css` | the drop plate and recent list |
| `src/styles/timeline.css` | the arranger panel |
| `src/styles/player.css` | the preview transport |
| `src/components/ui.tsx` | the React primitives that consume them |

`src/styles/index.css` imports them in that order. Nothing else imports a
stylesheet.

## Tokens

**Surfaces** step up from the window, never down:
`--bg #0A0A0B` → `--surface-1 #0F0F11` (panels) → `--surface-2 #141417`
(inputs, hover) → `--surface-3 #1A1A1E` (selected). `--surface-sunken #070708`
is for wells — the arranger, path readouts, code.

**Text** has four steps: `--text #F2F2F3`, `--text-secondary #9B9BA3`,
`--text-muted #62626B`, `--text-faint #45454C`. Anything quieter than faint is
invisible on a dim panel; anything between these steps is indecision.

**Lines** are hairlines: `--line #1F1F23` for dividers, `--line-strong #2C2C32`
for control edges, `--line-active #4A4A53` for focus and selection.

**State** is `--state-ok`, `--state-warn`, `--state-bad` — all resolved to
luminance, never hue. A failure is a bright glyph plus a heavier rule plus the
word, which survives greyscale, colour-blindness and a bad panel.

**Type** is two families: the system sans for everything, a mono for numbers,
paths, identifiers and technical readouts. Tabular figures throughout so BPM
and bar counts do not shimmer.

Scale: display 40 · title 26 · heading 17 · body 13.5 · small 12.5 · micro 11 ·
label 10.5. The label size is always uppercase with `0.14em` tracking.

**Spacing** is a 4px base, `--s1` through `--s11`. **Radii** are 2/4/6/10 —
present but never bubbly.

## Components

Every control is three moves: a hairline edge, a one-step surface change, and a
luminance shift on the label. Nothing glows, gradients or bounces.

| Component | Where it is used |
| --- | --- |
| `Segmented` | style, structure, creativity, rendering, format, bit depth, planner |
| `Toggle` | export options, with a right-aligned mono reason when disabled |
| `Option` | the Extract / Arrange / Extract + Arrange choice |
| `Note` | every explanation and warning — a left rule and quiet text, never a filled card |
| `Readout` | the tempo/key/bars/length instrument strip |
| `Section` | a tracked label, a hairline underline, optional right-hand meta |
| `Button` | `primary` (white on dark), default, `quiet` |
| `Badge`, `Advanced`, `KeyValues`, `Data`, `Empty` | supporting |

**Notes are not alert boxes.** A filled, bordered block for every warning is
what made the previous build feel like a developer dashboard. A left rule with
a tracked heading says the same thing and disappears when you are not reading
it.

## The arranger

The one screen that had to be excellent.

- Lane labels sit in a fixed gutter (`--lane-label`), so the ruler, the section
  strip and every lane share one x-axis and the panel reads as a single grid.
- Section fill lightness encodes energy: `rgba(242,242,243, 0.04 → 0.20)`. A
  hook is visibly brighter than a verse without a single colour.
- Section boundaries continue down through the lanes as hairlines.
- A drop-out is a dashed notch at the section's tail.
- Drum lanes render one luminance step back so pitched material reads first.
- Section labels clip rather than ellipsis: `INTRO` beats `INT…` at four bars.

## Rules for adding to this

1. No new colour. If something needs emphasis, it needs more luminance, more
   weight, or a heavier rule.
2. No new token without deleting one, or the scale stops being a scale.
3. Raw enum names (`REQUIRES_FREEZE`) never reach a primary surface. They live
   in **Advanced** / **Diagnostics**, where precision is what is wanted.
4. Explanations go behind a left rule, not inside a box.
5. A disabled control always states its reason, right-aligned, in mono.
