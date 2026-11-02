# Evaluation

Results will be filled in during the build. This page fixes the protocol **before** looking at results, so the numbers cannot be tuned to the test set.

## Questions

1. Does Darubini find parasites and WBC as an expert labelled them?
2. Does its count, and therefore its density estimate, agree with the expert's?
3. Does it call positive and negative slides correctly, on Tanzanian slides it never trained on?
4. How much does each Meta capability add?

## Splits

The frozen lists are in [`docs/splits/`](splits/): one row per patient or photo with its split. `darubini splits` writes them from the hash rule in `data/fields.py`.


| Dataset | Use | Split rule |
| --- | --- | --- |
| `nih-thick-pf-150` | Prompt tuning, parasite verifier training | 70 / 15 / 15 **by patient** |
| `nih-thick-uninfected` | Specificity, negative stopping rule | Same patient-level rule |
| `udom-tz-thick` | **Tanzanian train and held-out test.** 5,453 tiles from 611 photos; report per photo as well as per tile. Since 2 Nov (no lab session), 70% of photos are for development: the `adapt` half (217 photos, 1,866 tiles) trains domain adaptation and the `check` half (214 photos, 1,881 tiles) measures it. Until 2 Nov the development share was 15%; the new test photos are a subset of the old test set, which had never been scored. | 30% test (180 photos, 1,706 tiles), by photo |
| `nm-aist-tz` | Held-out slide-level test | Test only |

## Metrics

| Metric | Definition | Implemented in |
| --- | --- | --- |
| Detection precision, recall, F1 | Greedy one-to-one matching by centres: a hit when either box's centre lies inside the other. IoU ≥ 0.3 (`match_detections`) is kept for box-labelled data | `evaluation.match_centres` |
| Count MAE, mean bias, Pearson *r* | Per field, predicted vs expert counts | `evaluation.count_agreement` |
| Slide sensitivity, specificity | Positive/negative call vs label | `evaluation.slide_accuracy` |

**Why centres, not IoU.** Changed on 28 Oct, after looking at tuning data only. NLM white blood cells are point labels, and NLM parasite circles (about 41 px) include the halo, while SAM boxes only the chromatin dot (about 11 px). A correct SAM hit has an IoU near 0.07, so IoU ≥ 0.3 scored every hit as both a miss and a false positive.

## Quality gate calibration

The focus threshold (`QualityThresholds.min_sharpness`) is set by `darubini calibrate`; the full report is in [`calibration/quality.md`](calibration/quality.md). Focus is measured after downscaling each field to a 1,024 px long side. Sharp fields score about 3 to 300 depending on the camera and source, while blur drops any one source by a large factor, so the threshold is a floor that ≤1% of expert-annotated fields fall below in every dataset. It blocks clearly defocused fields only; it cannot catch mild blur. Fields that are sharp but nearly empty score low too, so they make up much of that 1%.

All checks measure only the illuminated field of view, not the black eyepiece surround that phone photos (UDOM, NIH, and the live demo) include. Focus also ignores a 30 px margin inside the rim, whose bright halo would otherwise make any field look sharp.

**Protocol deviation.** The floor was computed from image pixels (no labels) of every thick-film dataset, including the held-out `udom-tz-thick` and `nm-aist-tz`, before the UDOM development slice existed. A threshold calibrated on NIH alone (about 57) would block nearly every Tanzanian field. Report this deviation next to the test results.

## Prompt and tiling sweep (NIH tuning split)

Run with `darubini sweep` on 8 fields from tuning-split patients; full tables in [`calibration/sam_sweep_parasites.md`](calibration/sam_sweep_parasites.md) and [`calibration/sam_sweep_wbc.md`](calibration/sam_sweep_wbc.md). These are tuning numbers, not test results.

| Class | Best setting | Precision | Recall | F1 | Count MAE per field |
| --- | --- | ---: | ---: | ---: | ---: |
| White blood cell | "cell", whole field, score ≥ 0.7 | 0.93 | 0.98 | 0.95 | 1.0 |
| Parasite | "small dark purple dot", 1,024 px tiles, score ≥ 0.1, WBC interiors excluded | 0.46 | 0.28 | 0.35 | 26.5 |

Medical prompts ("malaria parasite", "parasite", "ring", "white blood cell", "nucleus") return no detections. Parasites are only found on tiles; on whole 4,032 px fields they are too small. Text prompts plateau because platelets and stain debris look like parasites, and SAM's confidence does not separate them (the best threshold is always the lowest tested).

## Development-slice checks (28 to 30 Oct)

**Exemplar prompting is not available.** The SAM 3.1 API segments only the objects a box or point marks, and rejects text combined with boxes (HTTP 400, "object prompts cannot be combined with a phrase"). Tested on a tuning tile: marking 2 parasites returned exactly 2 objects. The "text + exemplars" ablation row is therefore dropped.

**Candidates plus a verifier replace SAM for parasites.** On 8 NIH tuning fields, SAM's best prompt found 29% of labelled parasites as candidates; stain blobs found 91%. The pipeline now finds parasite candidates by local green-light absorption (`segmentation.candidates`). Giemsa-stained chromatin absorbs green whatever the stain shade, so this works on pale UDOM smears too: candidate recall is 0.90 on UDOM dev and 0.98 on NIH val, against 0.42 and 0.94 for stain blobs. A small NumPy network (`verifier`) then keeps the real parasites, judging each from a crop sized to the candidate and colour-normalised by the field background. SAM 3 still finds white blood cells in `hybrid` mode.

**Domain shift.** A verifier trained on NIH alone reached F1 0.78 on NIH val but 0.12 on UDOM dev. Retrained on NIH tuning fields plus the UDOM `adapt` half (weighted x3), it scores (full tables in [`calibration/verifier.md`](calibration/verifier.md)):

| Parasites, candidates + verifier | Precision | Recall | F1 | Count MAE per field |
| --- | ---: | ---: | ---: | ---: |
| NIH val split, 200 fields | 0.77 | 0.84 | 0.80 | 11.6 |
| UDOM dev `check` half, 200 tiles | 0.40 | 0.53 | 0.46 | 2.8 |

**UDOM white blood cell labels look incomplete.** On 300 dev tiles, every method (stain blobs, SAM "cell") finds about one more WBC per tile than is labelled, with precision near 0.22, including cells cut by tile edges. SAM's WBC F1 on NIH is 0.95. Treat UDOM WBC numbers with caution and report them per photo, where edge effects cancel.

**Per-patient counts (30 Oct).** Field-level F1 hides how errors gather on particular slides. On the 24 NIH val patients (275 fields), predicted over labelled parasites per patient, at the verifier's own threshold:

| Verifier | Field count MAE | Median patient ratio | Patients within 2x | Worst patient |
| --- | ---: | ---: | ---: | ---: |
| v1 | 11.7 | 1.08 | 92% | 16.5x |
| v2 (adds blob elongation and fill) | 10.0 | 1.00 | 92% | 15.0x |

Dense slides are accurate (13 of the 15 densest within 13%). The worst errors are sparse slides where platelets, rods and debris pass as parasites. Raising the threshold trades these for undercounts on dense slides.

**Muse Spark audit (30 Oct).** For each slide, 20 random parasite detections are shown to Muse Spark as a numbered montage; the share it confirms estimates the slide's precision. Checked on 8 NIH val slides against the labels (prompt revised once, after the first 4): the confirmed share was within 0.05 of label precision on 5 slides, and a flag at < 60% confirmed caught all 5 over-counted slides (1.7x to 15x) and none of the 3 accurate ones. On TF31_Sc440 (15 usable fields), the count was 517 against 88 labelled; the audit confirmed 4 of 20 and gave an audited estimate of 103. This is a small development check; the flag threshold must be re-checked on the test sets.

**Agent runs (31 Oct).** The Muse Spark agent counted 3 NIH val slides unattended in Kiswahili (10 to 14 tool calls each; [`calibration/agent_runs.md`](calibration/agent_runs.md)). Densities against the labels: TF31 6.2x (flagged; audited 1.9x), TF52 1.7x (flagged; audited 0.6x), TF30 1.03x (not flagged; audited 0.67x). The flag was right on all three; the audited estimate is too noisy to replace the count. Repeating the audit on the same 20 tiles gave 4 and then 6 confirmations.

**Verifier v3 after the new split (2 Nov).** The UDOM training share rose from 15% to 70% of photos, and the verifier was retrained with 1,604 `adapt` tiles (v2 had 414). On the same 300 `check` tiles, v2 scored F1 0.44, count error 3.0 and bias +1.4; v3 scored F1 0.44, count error 2.5 and bias −0.2. On the same 100 NIH val fields, v2 scored F1 0.78, count error 9.9 and bias +4.4; v3 scored F1 0.81, count error 7.4 and bias +0.9. v3 is in use ([`calibration/verifier.md`](calibration/verifier.md)). The `check` half is development data, not the test set.

**Audit repeatability (2 Nov).** The same 20 tiles per slide (8 NIH val slides) went to Muse Spark 3 times for each of 4 prompts ([`calibration/audit_repeat.md`](calibration/audit_repeat.md)). Asking for one verdict per tile, in order, kept every slide's confirmed share within 0.10 across repeats, against 0.25 for the list prompt; that prompt is now used. `temperature: 0` did not make answers repeat. With a fresh sample, the flag was right every time on the gross over-counts (15x, 4.8x) and on the accurate TF30. It was borderline on slides over-counted about 1.7x (shares 0.45 to 0.65), and it raised a precautionary flag on the under-counted TF77. A 20-tile sample alone carries about ±0.11 of noise.

**Video tracking (30 Oct, synthetic).** A 60-frame, 1280x720 pan across an NIH tuning field with an eyepiece mask: SAM 3.1 box tracking and the offline shift tracker both counted 18 parasites and 5 WBC once each, with no duplicates, against 47 and 11 counted naively over 7 keyframes. SAM cost US$0.04. Real eyepiece video is still to be tested.

## Ablations

| Variant | Parasite F1 | WBC F1 | Count MAE (UDOM TZ) | Sensitivity | Specificity |
| --- | --- | --- | --- | --- | --- |
| Baseline (stain threshold) | | | | | |
| SAM 3, text prompt | | | | | |
| SAM 3, best text prompt | | | | | |
| Candidates + verifier (offline) | | | | | |
| SAM 3 WBC + candidates + verifier (hybrid) | | | | | |
| Hybrid + Muse Spark agent (QC review, exclusions) | | | | | |
| Hybrid + Muse Spark audit flag (slide-level) | | | | | |

## Final test protocol (fixed 2 Nov 2026, before any test data was scored)

Written down before the run, so that no scope, threshold or metric can be chosen after seeing test results. The models are frozen: verifier v3 (threshold 0.75), the SAM "cell" WBC prompt at score 0.7, and the per-tile audit prompt. The script is `scripts/final_eval.py`, which caches every detection under `datasets/processed/final/`.

**Test sets.**

| Set | What | Segmenters |
| --- | --- | --- |
| NIH test | 24 infected patients, 270 fields, expert boxes | baseline, verified, hybrid; sam3 on a fixed sample of 60 fields (seed 0) |
| NIH uninfected test | 7 patients (patient-level hash rule) | verified, hybrid |
| UDOM test | 180 photos, 1,706 tiles | baseline, verified, hybrid; sam3 on a fixed sample of 300 tiles (seed 0) |
| NM-AIST thick | Image-level labels; a fixed sample of 400 infected and 400 uninfected images (seed 0) | verified, hybrid |

**Development sets, used only to choose the two decision thresholds below.**

| Set | What |
| --- | --- |
| NIH val | 24 infected patients |
| NIH uninfected dev | all 4 val patients and 16 tune patients (sampled with seed 0) |

**Metrics.**

1. **Field level** (NIH test, UDOM test): parasite and WBC precision, recall, F1, count MAE and count bias, over all fields, matched by centres.
2. **Slide density** (24 infected NIH test patients): predicted density = 8,000 × parasites / WBC over the fields that pass the quality gate. The expert density uses the labels on the same fields. Reported: the median predicted/expert ratio, the share of slides within ±25%, the share within 2×, and Pearson *r* of log₁₀ densities.
3. **Slide call** (the 31 NIH test slides): positive when the mean parasites per usable field is at least *T*.
   - *T* is chosen per segmenter on the development slides, maximising Youden's J. Ties go to the lowest *T*, which favours sensitivity for screening. *T* is placed midway between neighbouring observed values.
   - Also reported: the "any parasite" rule (*T* > 0).
   - Sensitivity and specificity, with Wilson 95% intervals.
4. **Image call** (NM-AIST): positive when the parasites in the image are at least *k*.
   - *k* is chosen the same way, on development fields: NIH val fields with at least one labelled parasite against fields from the uninfected development patients.
   - Sensitivity and specificity, with Wilson 95% intervals.
5. **Muse Spark** (hybrid, the 31 NIH test slides):
   - **Agent** (English): its density, exclusions and audit flag.
   - **Audit alone** on each slide's detections: does the flag pick out slides over-counted by 1.5× or more, and how many uninfected slides it would send for review?

**Expected SAM cost:** about US$13 (about 5,000 requests at US$0.0025).

**Deviation from the reporting rules.** Intervals for proportions are Wilson intervals. With 24 and 7 test patients, bootstrap intervals over patients would add little.

## Reporting rules

- Report 95% confidence intervals (bootstrap over patients).
- Report failures with example images, not just averages.
- Never report results on data used for tuning as test results.
