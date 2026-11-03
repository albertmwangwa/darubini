# Model Card: Darubini

## Overview

Darubini is a pipeline, not a single model. It combines an image quality gate, white blood cell detection (Meta SAM 3, or an offline baseline), parasite candidates kept by a small verifier network trained on NIH and Tanzanian (UDOM) fields, a deterministic counting engine and a report writer (template, optionally narrated by Meta Muse Spark). A Muse Spark agent can run the count through tools and audits a random sample of parasite detections; SAM 3.1 video tracking counts each object once across a panning clip.

## Intended use

- **Users:** trained laboratory technicians and microscopists.
- **Task:** count *Plasmodium* parasites against white blood cells in Giemsa-stained thick blood films and estimate parasite density.
- **Setting:** research, training and decision support in laboratories that already perform malaria microscopy.

## Not intended for

- Diagnosis without confirmation by a qualified microscopist.
- Species identification or treatment decisions.
- Thin films, other stains, or non-blood samples (not yet evaluated).
- Use by people without microscopy training.

## Data

See [`datasets/README.md`](datasets/README.md).

- **Training and tuning:**
  - NLM thick smears from Bangladesh, split by patient.
  - 70% of the University of Dodoma (UDOM) Tanzanian photos, split by photo.
- **Held out for testing:**
  - NLM test patients;
  - the other 30% of UDOM photos;
  - NM-AIST (Tanzania), never used for training or tuning.
- The frozen lists are in [`docs/splits/`](docs/splits/).

## Evaluation

The protocol was fixed before any test image was scored, and the test sets were scored once, on 2 Nov 2026. Full results with Wilson 95% intervals: [`docs/calibration/final_test.md`](docs/calibration/final_test.md). Summary and ablations: [`docs/EVALUATION.md`](docs/EVALUATION.md#ablations).

Hybrid mode (SAM 3.1 for white blood cells, candidates + verifier for parasites), on held-out data:

| Measure | Result |
| --- | --- |
| Parasite F1, NLM test fields (270) | 0.80 (count bias −1.5 per field) |
| Parasite F1, UDOM Tanzania test tiles (1,706) | 0.48 (count MAE 2.7 per tile) |
| White blood cell F1, NLM test fields | 0.90 |
| Slide density against the expert, 24 infected NLM test patients | median ratio 1.02; 19/24 within 2×; 11/24 within ±25% |
| Slide call, infected against uninfected (24 + 7 NLM slides) | sensitivity 50%, specificity 86% |
| Muse Spark audit flag | flagged 8/8 slides over-counted ≥1.5×, 7/7 uninfected slides, and 5/16 correctly counted slides |
| NM-AIST Tanzania, image call (400 + 400) | failed: sensitivity 0% (AUC 0.52) |

## Known limitations

- Very small or faint ring forms may be missed; heavy staining and thick areas cause false positives.
- **Platelets, bacteria and stain debris can pass as parasites.** On some low-density NIH validation slides this inflated the count 5 to 15 times. The Muse Spark audit flags such slides for manual review (it caught all 5 over-counted slides of 8 checked); it does not correct the WHO count.
- **It cannot tell an uninfected slide from an infected one.** Every uninfected test slide had some false-positive parasites, so "any parasite" calls every slide positive. A count threshold reached only 50% sensitivity on test. Use Darubini to estimate density on a slide a microscopist has already read positive, not to screen.
- **Tanzanian smears are harder.** UDOM parasite F1 is 0.48, against 0.80 on NLM. The UDOM parasites are faint, and only 70% of one Tanzanian dataset was available for adaptation.
- **Image scale matters.** On NM-AIST whole-frame 4K photos, parasites are only a few pixels across and almost none are found. Fields must be captured at a magnification similar to the NLM and UDOM images (one oil-immersion field per photo).
- Density uses an **assumed** 8,000 WBC/µL; true WBC counts vary between patients.
- Smartphone capture quality varies with phone, adapter and illumination.
- Performance on stains, microscopes and populations not represented in the data is unknown.

## Ethical considerations

- A missed infection can cause harm; the tool must never be the final word.
- Field images should contain no patient identifiers.
- Reports state in English and Kiswahili that results need expert confirmation.

## Contact

Albert William Mwangwa · https://github.com/albertmwangwa/darubini/issues
