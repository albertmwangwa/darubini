# Evaluation

Results will be filled in during the build. This page fixes the protocol **before** looking at results, so the numbers cannot be tuned to the test set.

## Questions

1. Does Darubini find parasites and WBC as an expert labelled them?
2. Does its count, and therefore its density estimate, agree with the expert's?
3. Does it call positive and negative slides correctly, on Tanzanian slides it never trained on?
4. How much does each Meta capability add?

## Splits

| Dataset | Use | Split rule |
| --- | --- | --- |
| `nih-thick-pf-150` | Prompt tuning, exemplar selection, detector head (if needed) | 70 / 15 / 15 **by patient** |
| `nih-thick-uninfected` | Specificity, negative stopping rule | Same patient-level rule |
| `udom-tz-thick` | **Held-out Tanzanian test.** No tuning on it. | Test only |
| `nm-aist-tz` | Held-out slide-level test | Test only |

## Metrics

| Metric | Definition | Implemented in |
| --- | --- | --- |
| Detection precision, recall, F1 | Greedy one-to-one matching, IoU ≥ 0.3 | `evaluation.match_detections` |
| Count MAE, mean bias, Pearson *r* | Per field, predicted vs expert counts | `evaluation.count_agreement` |
| Slide sensitivity, specificity | Positive/negative call vs label | `evaluation.slide_accuracy` |

## Ablations

| Variant | Parasite F1 | WBC F1 | Count MAE (UDOM TZ) | Sensitivity | Specificity |
| --- | --- | --- | --- | --- | --- |
| Baseline (stain threshold) | | | | | |
| SAM 3, text prompt | | | | | |
| SAM 3, best text prompt | | | | | |
| SAM 3, text + exemplars | | | | | |
| SAM 3 + exemplars + Muse Spark QC | | | | | |

## Reporting rules

- Report 95% confidence intervals (bootstrap over patients).
- Report failures with example images, not just averages.
- Never report results on data used for tuning as test results.
