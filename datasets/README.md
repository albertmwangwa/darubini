# Datasets

Darubini uses openly shared malaria microscopy datasets. **No images are stored in this repository.** The manifest ([`manifest.yaml`](manifest.yaml)) records where each dataset lives, its licence and its role, and the downloader fetches it on your machine.

```bash
make datasets        # list all datasets
make data            # core tier (~6.5 GB)
make data-extended   # core + extended
.venv/bin/darubini download --only udom-tz-thick   # just one
```

On Windows use `scripts\setup.ps1` then `scripts\get-data.ps1 -Tier core` (add `-AcceptLicences` for the large tier).

What the downloader does:

- **Checks disk space** before starting (archive plus extracted copy, about twice the archive size).
- **Resumes** interrupted downloads from a `.part` file.
- **Verifies MD5 checksums** wherever the provider publishes one (UDOM and every Zenodo file).
- **Keeps going** if one source fails and prints a summary: ready, manual step needed, licence not accepted, failed.
- **Skips licence-gated sets** (Colombia, Sudan) unless you pass `--accept-licences` after reading their terms.
- Lands everything in `datasets/raw/<id>/` (git-ignored) with a `.complete` marker so re-runs skip finished sets.

```bash
.venv/bin/darubini verify   # status of every dataset; exits non-zero if a core set is missing
.venv/bin/darubini links    # check every source is still online
```

A GitHub Action (`.github/workflows/dataset-links.yml`) runs the link check every Monday and whenever the manifest changes.

### Sources that need a credential or a decision

| Dataset | What to do |
| --- | --- |
| `nm-aist-tz` | `pip install kaggle`, create an API token at kaggle.com (Settings → API) and save it as `~/.kaggle/kaggle.json`. The downloader then fetches the community mirror; cite the original paper. |
| `colombia-ins-thick` | The Zenodo record states no licence. Confirm you may use it, then pass `--accept-licences`. |
| `nlm-sudan` | Read and accept the NLM data licence agreement on its page (49 GB download), then pass `--accept-licences`. |

## Catalogue

### Core (needed for the build)

**`udom-tz-thick`: Malaria Blood Smear Image Dataset (Tanzania)**
- Creators: Shaka M., Apina F. R., Waigama N., Ngatunga E., Mmaka S., Maneno H., Said S. H. (University of Dodoma); Chaula S., Sulutya I., Mashaka M. (Benjamin Mkapa Hospital)
- Patients resident in Morogoro Region. Giemsa thick smears photographed with an iPhone 6s+ on an Olympus CX21 at 100x.
- Labels: bounding boxes for *plasmodium* and *WBC* in Pascal VOC XML, by three experts. Parse with `darubini.data.annotations.parse_voc`.
- 149 MB zip, MD5 `785f978f766047a7717ebb8dcaeedcdf`. Licence **CC BY 4.0**. [Zenodo record](https://zenodo.org/records/4314960), doi:10.5281/zenodo.4314960
- **Role:** held-out Tanzanian count benchmark.

**`nih-thick-pf-150`: NLM Thick Blood Smears, 150 P. falciparum patients**
- U.S. National Library of Medicine with Mahidol-Oxford Tropical Medicine Research Unit; slides from Chittagong Medical College Hospital, Bangladesh.
- About 12 smartphone images per patient. Each parasite and WBC annotated (points or circles). Parse with `parse_nlm_thick`; check the parser against a few files on first download.
- 3.9 GB. Cite Yang et al., IEEE JBHI 2020. [Data page](https://data.lhncbc.nlm.nih.gov/public/Malaria/Thick_Smears_150/index.html)
- **Role:** main tuning and count set.

**`nih-thick-uninfected`: NLM Thick Blood Smears, uninfected patients**
- 2.5 GB. [Data page](https://data.lhncbc.nlm.nih.gov/public/Malaria/NIH-NLM-ThickBloodSmearsU/index.html)
- **Role:** specificity and the negative stopping rule.

### Extended

**`nm-aist-tz`: Blood smear imagery dataset, a case of Tanzania (Kaggle CLI)**
- Nelson Mandela African Institution of Science and Technology, Arusha. 3,544 images (3840x2160): 1,139 thick infected, 1,071 thick uninfected, 1,064 thin infected, 270 thin uninfected. Image-level labels.
- Downloaded through the Kaggle CLI from a community mirror. The original is on Harvard Dataverse, linked from the [paper](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11648091/); cite the paper either way.
- **Role:** held-out slide-level test on Tanzanian slides.

**`nih-thin-cells`:** NLM thin-smear cell crops (353 MB). Thin-smear stretch goal.

**`mp-idb`:** MP-IDB, University of Cagliari. Thin smears with masks for four species and life stages; cloned with git. Check the repository licence before use.

### Large (opt-in)

**`colombia-ins-thick` (Zenodo, licence check):** 1,000 Romanowsky-stained thick-smear images with 6,188 labelled parasites, about 8 GB. The licence is not stated on the [record](https://zenodo.org/record/7484518); confirm before use.

**`nlm-sudan` (licence agreement):** NLM Malaria Screener, Sudan; 190 patients with expert counts, 49 GB. Requires accepting the [data licence agreement](https://data.lhncbc.nlm.nih.gov/public/Malaria/MalariaScreener/index.html). Cite Yu et al., Malaria Journal 2023.

## Licence decisions on record

On 24 October 2026 the project owner accepted the NLM Malaria Screener (Sudan) terms (use with the credit "Source: U.S. National Library of Medicine" and a citation of Yu et al., Malaria Journal 2023) and chose to use the Colombia INS set for research with attribution, as its record states no licence. `scripts\get-more-data.cmd` downloads both, plus NM-AIST through Kaggle.

## Rules for using the data

1. Split **by patient**, never by image.
2. Never tune anything on the Tanzanian test sets.
3. Keep each dataset's licence and cite its authors in any publication or demo.
4. Do not commit images, archives or derived crops; `.gitignore` and pre-commit enforce this.
