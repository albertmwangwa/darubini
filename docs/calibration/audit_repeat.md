# Audit repeatability (2 Nov 2026)

## Setup

- **Question:** does the Muse Spark audit give the same answer when it sees the same tiles again, and does a different prompt make it steadier?
- **Slides:** the 8 NIH validation slides used to set the flag threshold.
- **Tiles:** for each slide, one fixed random sample of 20 verifier detections. The tiles are cut and laid out by `audit.crop_detection` and `audit.montage`, the same as in production.
- **Labels:** each tile is marked real when it matches an expert-labelled parasite.
- **Calls:** each montage was sent 3 times per prompt variant, 96 Muse Spark calls in all.

## Prompt variants

- **list:** the 31 Oct prompt, which replies `{"parasites": [tile numbers]}`.
- **list_t0:** the same with `temperature: 0`. The API accepts it.
- **per_tile:** the same morphology guidance, but asks for one verdict per tile, in order: `{"tiles": [{"n": 1, "parasite": true}, ...]}`.
- **per_tile_t0:** per-tile with `temperature: 0`.

## Over-count of each slide

The over-count is detections divided by expert parasites. A slide counts as over-counted at 1.5× or more.

| Slide | Over-count |
| --- | ---: |
| TF142_US27 | 15.00× |
| TF31_Sc440 | 4.77× |
| TF52_CW36 | 1.82× |
| TF128_S503 | 1.74× |
| TF137_US8 | 1.72× |
| TF30_W13B1 | 0.94× |
| TF110_270 | 0.89× |
| TF77_CO15 | 0.62× |

## Confirmed share, 3 repeats each

The expert-label share of the same 20 tiles is in brackets in the header.

| Variant | TF110 (0.70) | TF128 (0.35) | TF137 (0.50) | TF142 (0.10) | TF30 (1.00) | TF31 (0.15) | TF52 (0.50) | TF77 (0.75) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| list | 0.60 / 0.65 / 0.70 | 0.40 / 0.40 / 0.45 | 0.65 / 0.40 / 0.60 | 0.25 / 0.30 / 0.25 | 0.95 / 0.80 / 0.90 | 0.30 / 0.25 / 0.20 | 0.55 / 0.55 / 0.55 | 0.50 / 0.55 / 0.50 |
| list_t0 | 0.60 / 0.80 / 0.70 | 0.40 / 0.40 / 0.35 | 0.55 / 0.40 / 0.35 | 0.20 / 0.35 / 0.25 | 0.90 / 0.90 / 0.90 | 0.25 / 0.15 / 0.25 | 0.65 / 0.60 / 0.60 | 0.60 / 0.55 / 0.55 |
| per_tile | 0.70 / 0.75 / 0.70 | 0.45 / 0.55 / 0.45 | 0.60 / 0.50 / 0.55 | 0.25 / 0.30 / 0.30 | 0.90 / 0.90 / 0.85 | 0.20 / 0.20 / 0.25 | 0.65 / 0.65 / 0.60 | 0.50 / 0.50 / 0.50 |
| per_tile_t0 | 0.70 / 0.60 / 0.60 | 0.55 / 0.50 / 0.50 | 0.55 / 0.50 / 0.45 | 0.25 / 0.30 / 0.25 | 0.90 / 0.85 / 0.90 | 0.35 / 0.30 / 0.30 | 0.65 / 0.55 / 0.65 | 0.40 / 0.50 / 0.50 |

## Summary

| Variant | Largest spread in a slide | Correct flags (out of 24) | Slide whose flag flips | Tile agreement with labels |
| --- | ---: | ---: | --- | ---: |
| list | 0.25 | 19 | TF137 | 75% |
| list_t0 | 0.20 | 19 | TF77 | 78% |
| per_tile | **0.10** | 17 | TF137 | 75% |
| per_tile_t0 | 0.10 | 19 | TF52 | 75% |

A flag is correct when it is raised (confirmed share below 0.6) on a slide over-counted 1.5× or more, or not raised on any other slide. No reply failed to parse.

## Findings

- **Asking for a verdict per tile meets the repeatability target.** Every slide stays within 0.10 across repeats, against 0.25 for the list prompt.
- **Temperature 0 does not make the audit deterministic.** It is accepted, but answers still vary by up to 0.20.
- **The gross over-counts are flagged every time, in every variant:** TF142 (15×) and TF31 (4.8×). The accurate TF30 is never flagged.
- **The errors are on borderline slides:**
  - TF52, TF128 and TF137, over-counted about 1.7×, score 0.45 to 0.65, around the 0.6 line.
  - TF77, which is under-counted (0.62×), scores 0.50 and is flagged. A flag on an accurate count only asks for a manual review.
- **The sample is as noisy as the model.** With 20 tiles, sampling error alone is about ±0.11 (binomial). Repeating the audit cannot remove it; only a larger sample can.
- **Taking the majority of 3 repeats did not change any flag decision.**

## Decision

- The audit now uses the per-tile prompt (`audit.AUDIT_SYSTEM`). `parse_confirmed` still reads the old list form.
- The flag threshold stays at 0.6.
- The flag is reported as reliable for gross over-counts (3× or more) and borderline for mild ones (about 1.7×).
