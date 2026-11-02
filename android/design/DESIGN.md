# Darubini design system

Since 2 Nov 2026 the Android app uses the visual language of the **Credit Design** Figma file (`MmEcm4qfaIJpjpCf8nVlh9`, page "11 · Full App"), adopted as Darubini's own. The tokens and components were read through the Figma REST API from its "01 · Foundations" and "02 · Components" pages.

[darubini.m3e.json](darubini.m3e.json) is still the screen-flow sketch: which screens exist, what is on them, and where each tap goes. This document covers how those screens look.

## Principles

These four come from the Figma cover page:

- **One decision per screen.** Each screen has one primary action in the bottom action bar. On Capture, the primary button becomes "Finish slide" once the count is complete.
- **Offline first.** The connection to `darubini serve` is always shown as a badge: Connected, Offline or Checking.
- **Copilot beside every decision.** The Muse Spark agent's steps and summary appear next to the count, never in place of it.
- **Status is colour + word.** Every status is a pill with an icon and a word, never colour alone. Examples: Keep counting, Complete, Counted, Not counted, the audit result.

## Tokens

All tokens are in [`ui/theme/Theme.kt`](../app/src/main/java/app/darubini/ui/theme/Theme.kt). Use a token, never a raw value.

| Group | Tokens |
| --- | --- |
| Brand | primary `#215732`, primary-strong `#16391F`, primary-soft `#E8F3E3`, primary-wash `#F6FAF4`, lime `#43B02A`, lime-soft `#DDF0D5`, lime-text `#2A6E1B`, lime-bright `#9BE36F` |
| Surface | background `#ECEEED`, card `#FFFFFF`, muted `#F4F6F5` (screen background), muted-2 `#EEF1EF`, ink `#1C2420` |
| Text | foreground `#151A17`, muted `#6B736E`, foreground-soft `#2F3832`, on-primary `#FFFFFF` |
| Border | default `#E5E8E6`, input `#DDE2DF`, strong `#CFD8D3`, ring `#3A9A24` |
| Status | warning `#F0A33A` / strong `#9A5B07` / soft `#FDF2E1`; danger `#C8412F` / `#A13322` / `#FBE9E6`; info `#5B5BD6` / `#3E3EB0` / `#ECECFB` |
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
