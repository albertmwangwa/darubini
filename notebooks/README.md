# Notebooks

Exploration lives here: dataset profiling, prompt experiments, error analysis. Promote anything reusable into `src/darubini/` with tests.

Strip outputs before committing (`jupyter nbconvert --clear-output --inplace *.ipynb`) so the repository stays small and free of patient images.

Suggested first notebooks:

1. `01_profile_datasets.ipynb`: image sizes, colour statistics, objects per field for each core dataset.
2. `02_baseline_on_udom.ipynb`: baseline segmenter against UDOM Tanzania boxes.
3. `03_sam3_prompts.ipynb`: prompt-variant comparison (day 2).
