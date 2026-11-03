# Darubini design system

Since 2 Nov 2026 the Android app uses the layout, type and components of the **Credit Design** Figma file (`MmEcm4qfaIJpjpCf8nVlh9`, page "11 · Full App"), adopted as Darubini's own. Since 3 Nov its colours come from the Darubini Proposal. The tokens and components were read through the Figma REST API from its "01 · Foundations" and "02 · Components" pages.

[darubini.m3e.json](darubini.m3e.json) is still the screen-flow sketch: which screens exist, what is on them, and where each tap goes. This document covers how those screens look.

## Principles

These four come from the Figma cover page:

- **One decision per screen.** Each screen has one primary action in the bottom action bar. On Capture, the primary button becomes "Finish slide" once the count is complete.
- **Offline first.** The connection to `darubini serve` is always shown as a badge: Connected, Offline or Checking.
- **Copilot beside every decision.** The Muse Spark agent's steps and summary appear next to the count, never in place of it.
- **Status is colour + word.** Every status is a pill with an icon and a word, never colour alone. Examples: Keep counting, Complete, Counted, Not counted, the audit result.

## Tokens

All tokens are in [`ui/theme/Theme.kt`](../app/src/main/java/app/darubini/ui/theme/Theme.kt). Use a token, never a raw value.

**Since 3 Nov the colours follow the Darubini Proposal palette** ([`docs/proposal/index.html`](../../docs/proposal/index.html)), shared with the web page and the demo video. Type, radii and components still follow Credit Design. The token names are kept, so `Lime*` is now the success and accent role.

| Group | Tokens |
| --- | --- |
| Brand | primary `#2463EB`, primary-strong `#1842B4`, primary-soft `#ECF1FE`, primary-wash `#F7F9FE` |
| Success / accent (`Lime*`) | `#25935F`, soft `#E3F3EA`, text `#1D7A4E`; on blue, highlight `#90C7FE` |
| Surface | background `#E9ECF1`, card `#FFFFFF`, muted `#F3F4F7` (screen background), ink `#0F1729` |
| Text | foreground `#0F1729`, muted `#5D6779`, foreground-soft `#273041`, on-primary `#FFFFFF` |
| Border | default `#DEE1E7`, input `#D5D9E0`, strong `#C8CED8`, ring `#2463EB` |
| Status | warning `#E08A1E` / strong `#A3580A` / soft `#FDF3E2`; danger `#DC2626` / `#B91C1C` / `#FEECEC`; info (stain purple) `#683B9B` / `#522E7B` / `#F1EAF8` |
| Markers | parasite `#DB2777`, white blood cell `#2463EB` |
| Radius | xs 4, sm 10, 12, md 14, 16, card 22, xl 30, pill |

## Type

The typeface is **Plus Jakarta Sans** (SIL Open Font License), bundled as a variable font in `res/font/`.

| Style | Weight | Size / line height | Tracking |
| --- | ---: | --- | ---: |
| Display/Page title | 700 | 28 / 33.6 | −0.9 |
| Display/Metric | 700 | 28 / 32.2 | −1.1 |
| Heading/Title | 700 | 20 / 25 | −0.5 |
| Heading/Card title | 700 | 17 / 22.1 | −0.4 |
| Heading/Section | 600 | 14 / 19.6 | 0 |
| Body/Large | 400 | 16 / 24 | 0 |
| Body/Default | 400 | 14 / 21.7 | 0 |
| Body/Strong | 600 | 14 / 21 | 0 |
| Label/Default | 600 | 13 / 18.2 | 0 |
| Label/Small | 600 | 12 / 16.2 | 0 |
| Body/Small | 400 | 13 / 19.5 | 0 |
| Caption/Default | 400 | 12 / 16.8 | 0 |
| Caption/Eyebrow | 600 | 11.5 / 14.95, upper case | 0.6 |

## Components

The components are in [`ui/screens/Components.kt`](../app/src/main/java/app/darubini/ui/screens/Components.kt).

| Figma component | Compose | Used for |
| --- | --- | --- |
| Button | `DsButton` (Primary, Soft, Outline, Ghost, Danger, Lime; heights 52, 44, 36) | All actions |
| Badge | `Badge` + `Tone` | Connection, counting status, audit, field kept |
| Metric tile | `MetricTile` (one filled, one outlined per row) | Parasites and white blood cells |
| Progress segment | `ProgressSegments` | White blood cells against the target |
| Notice | `Notice` | Next step, retake reason, audit warning |
| Capture section | `CaptureRow` | "How it works", excluded fields, clips |
| Key value row | `KeyValueRow` | Report facts |
| Timeline item | `TimelineItem` | The agent's tool calls |
| Chat bubble (Copilot) | `CopilotCard` | The agent's summary |
| Bottom action bar | `BottomActionBar` | The screen's one decision |
| Option tile | `OptionTile` | Language in Settings |
| Text field | `OutlinedTextField`, white, input border, 14 radius | Server address |

## Not adopted

- **Dark mode.** The design system is light only. Only its camera screens are dark.
- **Floating navigation bar.** Darubini has one linear flow and no tabs.
