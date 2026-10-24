# Model Card: Darubini

## Overview

Darubini is a pipeline, not a single model. It combines an image quality gate, a segmenter (Meta SAM 3, or an offline baseline), a deterministic counting engine and a report writer (template, optionally narrated by Meta Muse Spark).

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

See [`datasets/README.md`](datasets/README.md). Training and tuning use NLM thick smears from Bangladesh. Tanzanian datasets (University of Dodoma, NM-AIST) are held out for testing.

## Evaluation

Protocol and results: [`docs/EVALUATION.md`](docs/EVALUATION.md). Results will be reported with confidence intervals and failure examples.

## Known limitations

- Very small or faint ring forms may be missed; heavy staining and thick areas cause false positives.
- Density uses an **assumed** 8,000 WBC/µL; true WBC counts vary between patients.
- Smartphone capture quality varies with phone, adapter and illumination.
- Performance on stains, microscopes and populations not represented in the data is unknown.

## Ethical considerations

- A missed infection can cause harm; the tool must never be the final word.
- Field images should contain no patient identifiers.
- Reports state in English and Kiswahili that results need expert confirmation.

## Contact

Albert William Mwangwa · https://github.com/albertmwangwa/darubini/issues
