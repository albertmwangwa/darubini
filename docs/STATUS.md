# Project status

**As of Mon 2 Nov 2026 (build day 8 of 10; feature freeze today).** Submission closes Thu 5 Nov, 05:00 EAT; the plan targets submitting by Wed 4 Nov, 18:00 EAT. Day-by-day plan: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). Previous status: 28 Oct.

## Summary

**Update, 30 Oct evening.** Both demo centrepieces work.
- **Muse Spark counting agent:** counts a slide unattended through tools, writes the report in Kiswahili, and audits its own parasite detections.
- **SAM 3.1 video tracking:** counts each object once across a panning clip.

The audit catches a serious problem found today, over-counting on sparse slides, but does not fix it. Details in steps 5 to 7 below.

- **Parasite detection now works on NIH and works partly on Tanzanian smears.**
  - On NIH validation patients: F1 0.80, count error 11.6 per field.
  - On the Tanzanian UDOM development slice: F1 0.46, count error 2.8 per tile.
  - Two days ago, SAM's text prompts reached only F1 0.35 on NIH tuning fields.
- **SAM 3 finds white blood cells reliably:** F1 0.95 on NIH tuning fields.
- **Parasites are no longer found by SAM.** The API cannot do exemplar prompting (tested), and a free offline detector finds far more parasites than SAM does.
- **The full pipeline runs end to end** in the new `hybrid` mode (SAM for white blood cells, our verifier for parasites) and in the offline `verified` mode.
- About **US$21** of the US$150 API credit has been spent (about 8,200 SAM requests, most of them in the final test run; voice tests cost cents).
- **Final test results (2 Nov):**
  - On held-out NIH patients: parasite F1 0.80, and density within 2× of the expert on 19 of 24 slides.
  - On UDOM test: parasite F1 0.48.
  - Weak spots: the slide-level negative/positive call, and NM-AIST, which failed because of image scale. See step 15.
- All checks pass (191 Python tests at 97% coverage, and 11 Android tests, as of 2 Nov). Pushed on 2 Nov as branch `feat/agent-tracking-android`.

## Where we are against the plan

| Day | Planned | Status |
| --- | --- | --- |
| 1–2 | Wire the Meta API; SAM at scale with caching | Done (28 Oct) |
| 3 | Exemplar prompting | Not possible through the API; replaced by candidates + verifier (30 Oct) |
| 4 | Tanzanian evaluation tables | Development-slice results done; the frozen test set is scored once, at the end |
| 5 | Muse Spark agent | Done (30 to 31 Oct), with a parasite audit and guardrails |
| 6 (today) | Phone capture app | Done (31 Oct); real-phone test pending |
| 7 | Video tracking, polish | Tracking done early (30 Oct, synthetic clips); real video pending |
| 8 (Mon 2 Nov) | Live lab session, feature freeze | Microscope booking not confirmed |

## Done since 28 Oct

### 1. Exemplar prompting: tested, not available

- The SAM 3.1 API segments only the objects that box or point prompts mark.
- Marking 2 parasites on a tile returned exactly those 2.
- Combining a text phrase with boxes returns HTTP 400 ("object prompts cannot be combined with a phrase").
- Box prompts remain useful for tracking marked parasites across video frames (plan day 7).

### 2. A new parasite pipeline: candidates plus a verifier

- **Candidates.** `segmentation/candidates.py` finds spots that absorb green light relative to their surroundings. Giemsa-stained chromatin does that whatever the stain shade, so the detector works on pale UDOM smears as well as dark NIH ones. It takes 68 ms per UDOM tile and 231 ms per 4K NIH field.
- **Verifier.** `verifier.py` is a small NumPy network that keeps the real parasites among the candidates.
  - It judges each candidate from a crop sized to the candidate and colour-normalised by the field background.
  - Weights are saved as `.npz` (no pickle) at `models/parasite_verifier.npz`, 0.2 MB.
- **Training data.** 300 NIH tuning fields plus the `adapt` half of the UDOM development slice. Run it again with `darubini train-verifier`.
- **Segmenter modes** (`DARUBINI_SEGMENTER`):
  - `baseline`: stain blobs only, offline.
  - `sam3`: SAM text prompts for both classes.
  - `verified`: candidates + verifier, offline.
  - `hybrid`: SAM for white blood cells, candidates + verifier for parasites.

| Parasite candidate recall | UDOM dev | NIH val |
| --- | ---: | ---: |
| SAM, best text prompt | ~0.14 | 0.29 (tuning fields) |
| Old stain-blob detector | 0.42 | 0.94 |
| **Green-absorption candidates** | **0.90** | **0.98** |

| Parasites, candidates + verifier | Precision | Recall | F1 | Count error per field |
| --- | ---: | ---: | ---: | ---: |
| NIH val split, 200 fields | 0.77 | 0.84 | **0.80** | 11.6 |
| UDOM dev `check` half, 200 tiles (never trained on) | 0.40 | 0.53 | **0.46** | 2.8 |

Full tables: [calibration/verifier.md](calibration/verifier.md).

### 3. A UDOM development slice and the `evaluate` command

- **Development slice.** 15% of UDOM photos are set aside for domain checks: 857 tiles from 101 photos. Each photo's tiles stay together.
  - The `adapt` half (477 tiles) may be used to train domain adaptation.
  - The `check` half (380 tiles) measures it.
  - The other 85% (4,596 tiles from 510 photos) is the frozen test set.
- **`darubini evaluate`** scores any segmenter modes on a split. It prints the API cost first, refuses to run above `--max-cost`, and scores the test split only with `--final-test`.
- **First dev-slice run** (300 tiles, before adaptation): [calibration/evaluation_dev.md](calibration/evaluation_dev.md). It showed the NIH-trained verifier failing on UDOM, with F1 0.12.

### 4. Docs brought in line with reality

- **README:** the exemplar claims are removed; it now describes the candidate and verifier design, and the architecture diagram and roadmap are updated.
- **MODEL_CARD:** the pipeline description is updated.
- **EVALUATION:** records the UDOM dev split, the development-slice results and the revised ablation rows.

## Done on 30 Oct (afternoon): the demo centrepiece

### 5. Muse Spark counting agent (`darubini agent`)

- **Tool calling works** through Chat Completions (`tools`, `tool_calls`, `role: tool`; only `tool_choice: auto` is supported).
- **`agent.py`.** Muse Spark runs the slide through five deterministic tools:
  - `examine_next_fields` (1 to 10 fields per call);
  - `review_field`, a second vision reader for quality;
  - `exclude_field`;
  - `get_count`;
  - `finish`.
- **Guardrails:**
  - Every number comes from the counting engine.
  - `finish` is refused while the WHO rule is unmet and fields remain.
  - A narrative that quotes a number no tool returned is dropped.
  - If the agent stalls or the API fails, the remaining fields are counted without it, and the report says so.
- **First unattended run:** NIH validation patient TF31_Sc440, 20 fields, Kiswahili, `hybrid` mode. Trail: [calibration/agent_TF31_Sc440.json](calibration/agent_TF31_Sc440.json).
  - **Process:** 9 tool calls in 3 min 19 s. The agent grew its batch size (2, 3, 10, 5), reviewed 3 fields and excluded 1 (pale staining, soft focus). It stopped at the WHO rule (200 WBC) and wrote a grounded Kiswahili narrative. *Done when the agent finishes a full slide unattended: met.*
  - **Accuracy problem found:** the parasite count is far too high. Fixed in part by step 7 below.

| TF31_Sc440, the same 17 usable fields | Parasites | WBC | Density per µL |
| --- | ---: | ---: | ---: |
| Expert labels | 100 | 204 | 3,922 |
| Darubini (`hybrid`) | 646 | 200 | 25,840 |

### 6. SAM 3.1 video tracking (`darubini track`)

- **The API tracks objects in MP4 clips.**
  - Request: `input_video` plus box prompts `<0f>id<|box;...;w;h|>`, with `propagation_direction: forward`.
  - Reply: one `<Nf>` line per frame, with stable object ids.
  - Limits: at most 16 prompted objects per request. Price: $0.20 per 1,000 frames, with a 50-frame minimum.
  - Gotcha: a box touching the right or bottom edge (x2 == width) is rejected with HTTP 400, so boxes are clamped.
- **`tracking.py`.**
  - It detects objects on keyframes (every 10 frames), drops detections that land on an existing track, and hands only new objects to the tracker. Each track counts once.
  - Two trackers:
    - `SamTracker`: SAM box prompts on the clip.
    - `ShiftTracker`: an offline fallback that follows the pan by phase correlation against a reference frame.
- **`video.py`.** MP4 encode and decode through PyAV (a new core dependency, which bundles ffmpeg), plus `synthetic_pan` with an eyepiece mask for demos and tests.
- **Synthetic pan of an NIH tuning field:** 60 frames at 1280×720, eyepiece masked, verified detector.

| Tracker | Unique parasites | Unique WBC | Naive per-keyframe total | Duplicates | Time | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SAM 3.1 video | 18 | 5 | 47 parasites, 11 WBC | 0 | 29 s | $0.04 |
| Offline shift | 18 | 5 | 47 parasites, 11 WBC | 0 | 10 s | free |

  A synthetic pan is pure translation, which favours the shift tracker. On real phone video (focus breathing, wobble), SAM follows the objects themselves. A real-video check is needed.

### 7. Over-counting on sparse slides: diagnosed, then flagged by a Muse Spark audit

- **Per-patient check, NIH val, 24 patients, 275 fields.** On the 15 densest slides the count is within 13% of the experts' on 13 of them. A few slides carry many false positives, and on sparse slides they dominate: TF142 is 16× too high, TF31 5.5×.
- **Raising the threshold does not fix it.** At 0.8 the worst slide is still 9.7× too high, and dense slides start to undercount.
- **What the false positives are.** From crop galleries:
  - On TF31: mostly purple rods (bacteria or precipitate).
  - On TF142: small round magenta dots, platelet clumps and eyepiece-edge artefacts.
  - Platelets versus ring-stage chromatin is the classic thick-film confusion.
- **Verifier v2** adds orientation-free blob shape features (elongation and fill), so diagonal rods are visible to the model. Retrained on the same data:
  - Aggregate F1 is unchanged (0.81 on 60 NIH val fields, 0.46 on UDOM `check`).
  - Field count error falls from 11.7 to 10.0.
  - Worst slides improve only a little: TF31 4.8×, TF142 15×.
  - v2 is now `models/parasite_verifier.npz`; v1 is kept outside the repo.
- **Second-reader audit (`audit.py`, agent tool `audit_parasites`).**
  - Muse Spark sees 20 randomly sampled detections as one numbered montage and says which are parasites.
  - The WHO count stays as it is. The audit adds an audited estimate (count × confirmed share) and flags the slide for manual review when fewer than 60% are confirmed.
  - `finish` is refused until a slide with parasites has been audited.
  - Report lines are in English and Kiswahili.
- **Audit check on 8 NIH val slides** (prompt revised once after the first 4):
  - On 5 of 8, the confirmed share is within 0.05 of the label precision.
  - The 60% flag catches exactly the 5 over-counted slides (1.7× to 15×) and none of the 3 accurate ones.
  - Eight slides is a small sample; the threshold must be re-checked on more slides.
- **TF31 agent run with the audit** (21 tool calls, finished unattended):

| TF31_Sc440, the 15 usable fields | Parasites | Density per µL |
| --- | ---: | ---: |
| Expert labels | 88 | 3,911 |
| Darubini count (WHO rule) | 517 | 23,634 |
| Audited estimate (4 of 20 confirmed, flagged) | 103 | about 4,700 |

- **New agent behaviour to fix.** The agent reviewed and excluded fields after the stopping rule had fired, which dropped the slide back below 200 WBC with no fields left. The quality reviewer is also strict on NIH's over-exposed phone photos: it excluded 5 of 20 fields.

## Done on 31 Oct

### 8. Agent exclusions fixed; three-slide check

- **Guardrail.** `exclude_field` is refused once the counting rule is met, so a finished count can no longer be reopened.
- **Prompt.** Doubtful fields are reviewed right after each batch. They are excluded only for blocking problems (out of focus, far too thick, no stain); pale or bright fields with clear cells stay in.
- **Robustness.** A SAM failure inside `examine_next_fields` used to crash the agent; the first TF30 run exited silently because of it. The failure is now returned to the agent as an error, the field stays unexamined so a retry picks it up, and the fallback stops on a persistent failure.
- **Runs** (full table: [calibration/agent_runs.md](calibration/agent_runs.md)). All three finished unattended in 10 to 14 tool calls and about 1 to 3.5 minutes each.

| Slide | Excluded | Expert density | Count (WHO rule) | Audited | Flag |
| --- | ---: | ---: | ---: | ---: | --- |
| TF31_Sc440 (sparse) | 2 of 20 | 3,828 | 23,845 (6.2x) | 7,154 (1.9x) | yes |
| TF52_CW36 (sparse) | 0 of 8 | 1,356 | 2,292 (1.7x) | 802 (0.6x) | yes |
| TF30_W13B1 (dense) | 0 of 14 | 124,080 | 127,959 (1.03x) | 83,173 (0.67x) | no |

- **What this shows:**
  - Exclusions are back to normal: 2, 0 and 0, against 5 before.
  - The audit flag is right on all three slides.
  - The audited estimate is noisy (0.6x to 1.9x), so it stays a flag beside the WHO count, not a replacement.
  - Muse Spark's audit is not fully repeatable: on the same 20 TF31 tiles it confirmed 4 one run and 6 the next.

### 9. Phone capture web app (`darubini serve`, page at `/`)

- **Page.** One static HTML page, no external libraries: English and Kiswahili interface, capture through the phone camera, photos shrunk to 2,048 px on the phone (about 230 KB), canvas overlay (parasites circled in magenta, WBC boxed in blue), WBC progress bar, and a retake / next field / finish prompt.
- **Capture.** Endpoints under `/v1/sessions` (`api/sessions.py`): a field or clip is analysed on upload; unusable photos are not kept, and the reply asks for a retake.
- **Finish.** The Muse Spark agent runs over the captured fields in a background thread, reusing their results rather than segmenting again (new `CapturedField`). The phone polls and shows each tool call, then the report with any audit warning. Without an API key the report is deterministic.
- **End-to-end run** against the real API, `hybrid` mode, TF52 photos uploaded as the phone sends them:
  - Each field took 2 to 5 s; the app said "finish" at 202 WBC after 8 fields.
  - A 40-frame clip took 28 s with SAM tracking: 7 unique parasites against 16 counted frame by frame.
  - The agent report took 114 s: it reviewed every field, excluded none, and the audit flagged the slide (10 of 20 confirmed).
- **Checked in headless Chrome at 390 px.** Screenshots: [capture](calibration/app_capture.png), [report](calibration/app_report.png). The prompt banner was English inside the Kiswahili interface; fixed.
- **Robustness.** A failing SAM call returns HTTP 502 rather than crashing. The tests pin the app offline so they never bill the API, whatever `.env` says.
- **PyAV is now a core dependency**, since clip uploads need it.
- **Not yet done:**
  - Not yet tried on a real phone over a real network.
  - Quality flags in the retake prompt are still English.
  - Sessions live in memory: one server process, lost on restart.

### 10. Native Android app, designed in M3E Canvas (`android/`)

- **Design first.** I sketched five screens (Start, Capture, Agent, Report, Settings) as an [M3E Canvas](https://github.com/albertmwangwa/m3e-canvas) document:
  - [android/design/darubini.m3e.json](../android/design/darubini.m3e.json) is the design. It uses the teal palette, light and dark, emphasized type and expressive motion.
  - `canvas-link.txt` is the share link that opens the design in the browser.
- **App.** Kotlin and Jetpack Compose, one activity, no navigation library. It talks to the same `/v1/sessions` API as the web page:
  - The OkHttp client and JSON parsers are in `data/`.
  - The English and Kiswahili strings are copied from the web page.
  - **Capture.** Photos go through the system camera; pans are recorded through the system video recorder, capped at 8 s. Photos and clips can also come from the gallery.
  - **Photos** are shrunk to 2,048 px on the phone and sent as JPEG at quality 85, as the web page does.
  - The **server address** is set in Settings. Plain HTTP is allowed for the clinic Wi-Fi.
- **M3 Expressive parts used:** `MaterialExpressiveTheme` with `MotionScheme.expressive()`, the shape-morphing loading indicator, wavy progress for the WBC target, connected toggle buttons for the language, segmented lists (28dp outer, 8dp inner corners) for the agent's steps, and a cookie-shaped hero.
- **Versions.** AGP 9.5, Kotlin 2.4.21, Gradle 9.6, compile and target SDK 37, min SDK 26.
  - Material 3 is pinned to **1.5.0-beta02**: the Expressive components are not public in 1.4.0, the stable release.
  - The APK is 13.7 MB (debug).
- **Tests.** 10 JVM tests cover JSON parsing, using replies shaped like `sessions.py`, and the API client, against MockWebServer. All pass.
- **End-to-end run on the API 37 emulator** against the local server (`baseline` segmenter, real Muse Spark):
  - A TF52 photo from the gallery came back with the overlay, the wavy progress bar and "next field".
  - Finish slide showed the agent's tool calls live.
  - The report screen showed 27,765 parasites/µL and the audit warning: Muse Spark confirmed 1 of 20 sampled detections, so the app shows "Count probably inflated" in error colours. The `baseline` segmenter circles the bright rim of the field, so this is the over-count case the audit exists to catch.
  - A Kiswahili run was also checked.
  - Screenshots were replaced by the restyled app (step 14).
- **Fixed during the run:**
  - The stat cards had unequal heights when a label wrapped; they are now equal.
  - The Kiswahili photo button label was cut off; it is now shortened to "Piga picha".
  - `ExposedDropdownMenu` is not available in M3 1.5; a plain `DropdownMenu` is used instead.
- **Emulator notes:**
  - The emulator had no network at first, so the run used `adb reverse tcp:8000 tcp:8000` and server address `http://127.0.0.1:8000`.
  - Reinstalling with `adb install -r` while the app was open left a blank window until a cold start. This was an emulator rendering problem, not an app bug.
- **Not yet done:**
  - Not tried on a real phone, a real camera or a recorded pan; the clip path is untested on a device.
  - Sessions do not survive the app being killed while the camera is open.
  - Release signing uses the debug key.

## Done on Mon 2 Nov

### 11. Quality flags localised in the retake prompt

- Field replies now carry `blocking_text`, the blocking problems worded for the technician in English and Kiswahili, for example "too bright" / "mwanga mwingi kupita kiasi". The function is `quality.blocking_text`.
- The internal flags stay in English, because the agent and the reports read them.
- The web page and the Android app show the text for the interface language. Switching language re-renders a pending retake prompt. Against an older server, the Android app falls back to the raw flags.
- Tests:
  - Python: 189 pass, 97% coverage; ruff, mypy and bandit are clean.
  - Android: 11 JVM tests pass.
- The Kiswahili wording has not been checked by a native speaker.

### 12. Audit repeatability: per-tile prompt adopted

- **Experiment.** The same 20 tiles from each of the 8 NIH validation slides went to Muse Spark 3 times for each of 4 prompt variants: 96 calls. Full tables: [calibration/audit_repeat.md](calibration/audit_repeat.md).
- **Repeatability.** Asking for one verdict per tile, in order, keeps every slide's confirmed share within **0.10** across repeats, against 0.25 for the 31 Oct list prompt. This meets the target. `temperature: 0` is accepted but does not make the answers repeat.
- **Flag accuracy did not improve:**
  - The gross over-counts are flagged every time: TF142 (15×) and TF31 (4.8×).
  - The accurate TF30 is never flagged.
  - The slides over-counted about 1.7× (TF52, TF128, TF137) score 0.45 to 0.65, so they sit on the 0.6 line.
  - TF77, which is under-counted, scores 0.50 and gets a precautionary flag.
  - Sampling 20 tiles alone gives about ±0.11 of noise, which no amount of repeating removes.
- **Change.** `audit.AUDIT_SYSTEM` now asks for per-tile verdicts. `parse_confirmed` reads both reply forms, with a test for each. The 0.6 threshold is unchanged.
- **What we can claim:** the audit reliably flags gross over-counts and is borderline for mild ones.

### 13. No lab session: train/test split rebuilt, verifier retrained

- **Decision (user, 2 Nov).** There will be no lab session. The existing datasets are split into training and held-out test sets instead.
- **NIH split unchanged:** 102 tune, 24 val and 24 test patients.
- **UDOM (Tanzania): 70% of photos for training, 30% held out as test, by photo.** It was 15% and 85%.
  - Training: 431 photos, 3,747 tiles. The `adapt` half (1,866 tiles) trains, and the `check` half (1,881 tiles) measures.
  - Test: 180 photos, 1,706 tiles.
  - Neither test set had ever been scored. The hash rule nests, so every new test photo was already a test photo, and every old development photo kept its half. Nothing leaks, and a test checks this.
- **Frozen lists.** The new `darubini splits` command writes [docs/splits/](splits/): one row per patient or photo with its split.
- **Verifier v3**, trained with 1,604 `adapt` tiles (v2 had 414). Compared on the same fields, see [calibration/verifier.md](calibration/verifier.md):

  | Fields | Model | Precision | Recall | F1 | Count error per field | Count bias |
  | --- | --- | ---: | ---: | ---: | ---: | ---: |
  | UDOM check, 300 tiles | v2 | 0.37 | 0.53 | 0.44 | 3.0 | +1.4 |
  | UDOM check, 300 tiles | v3 | 0.45 | 0.43 | 0.44 | 2.5 | −0.2 |
  | NIH val, 100 fields | v2 | 0.75 | 0.82 | 0.78 | 9.9 | +4.4 |
  | NIH val, 100 fields | v3 | 0.80 | 0.81 | 0.81 | 7.4 | +0.9 |

  - v3 is now `models/parasite_verifier.npz`, with threshold 0.75. v2 is kept in the scratchpad.
  - Counts are better on both datasets.
  - Tanzanian F1 did not move. The faint UDOM parasites remain the weak point.

### 14. Android app restyled in the Credit Design Figma language

- **Source.** The user's Figma file "Credit Design", page "11 · Full App". Tokens, the type scale and elevations were read through the Figma REST API. The token is in `.env` as `FIGMA_TOKEN`, which is gitignored.
- **Adopted as Darubini's own.** Plus Jakarta Sans, bundled under the OFL. The brand green `#215732` with lime accents, white cards with hairline borders, pill buttons, and status always shown as colour plus a word.
- **Components rebuilt in Compose:** button (6 variants, 3 heights), badge, metric tile, segmented progress, notice, capture row, key-value row, timeline, Copilot card, bottom action bar and option tile. The full map is in [android/design/DESIGN.md](../android/design/DESIGN.md).
- **Screens follow the Figma layouts:**
  - Start is like the Figma home: connection badge, hero, the flow as capture rows, a language chip and one primary action.
  - Capture is like the visit workspace: metric tiles, segmented WBC progress, a next-step notice and the field with its overlay. The primary button becomes "Finish slide" once the count is complete.
  - Agent is a timeline.
  - Report is like "Visit accepted": an outcome disc and density, the audit notice, key-value facts with badges, and the Copilot summary.
- **The app checks the server connection on launch.** The design is light only.
- **Checked end to end on the emulator** with the real agent. Screenshots: [start](calibration/android_start.png), [capture](calibration/android_capture.png), [report](calibration/android_report.png).
  - Two truncated button labels were fixed.
  - The timeline's connecting line was fixed after the last screenshot, so it has not been seen on screen.

### 15. Final test-set scoring (done 2 Nov)

- The user asked for the one-time scoring of the frozen test sets.
- The protocol was written into [EVALUATION.md](EVALUATION.md#final-test-protocol-fixed-2-nov-2026-before-any-test-data-was-scored) before any test image was run. It fixes the sets, the samples, the metrics and the decision rules.
- **Slide and image calls use thresholds chosen on development data.** Under the WHO rule, a slide reads negative only after 100 clean fields, so with any false positives every uninfected slide would read positive.
- **Script:** `scripts/final_eval.py`. It caches every detection under `datasets/processed/final/`, which is gitignored.
- Six workers ran out of memory on 12 MP fields; the run uses 3.
- **Ran:** 9,665 field results, then the Muse Spark agent and audit on all 31 NIH test slides. The run hit 27 transient DNS failures, and the client's retries recovered every one. No job failed.
- **Cost:** 5,122 new SAM requests, about US$12.80, so about US$18 of the US$150 credit has been spent in total. Muse Spark calls are not cached, so they are not in this count.
- **Results:** [calibration/final_test.md](calibration/final_test.md); summary and ablation table in [EVALUATION.md](EVALUATION.md#ablations).

  | Measure (test) | Hybrid |
  | --- | --- |
  | Parasite F1, NIH / UDOM | 0.80 / 0.48 |
  | WBC F1, NIH | 0.90 |
  | Slide density: median ratio, within ±25%, within 2× | 1.02, 11/24, 19/24 (*r* = 0.93) |
  | Slide call (*T* = 26.2): sensitivity / specificity | 12/24 = 50% / 6/7 = 86% |
  | Audit flag: over-counted / correct / uninfected slides | 8/8 / 5/16 / 7/7 |
  | NM-AIST image call | 0/400 sensitivity, AUC 0.52 |

- **What changes in the pitch.**
  - Darubini estimates density on a slide already read positive. It is not a negative/positive screen: every uninfected slide has false positives, and the count rule's sensitivity fell from 71% in development to 50% on test.
  - The audit is a review trigger that never let an over-count through.
  - NM-AIST failed because of scale (whole 4K frames) and an image-format confound between its folders. This is reported as is, not fixed on the test set.

### 16. Write-up: README results and model card (2 Nov)

- **README:**
  - The "Evaluation plan" section is now **Results**: the test ablation and what it can and cannot do.
  - The "IoU ≥ 0.3" claim was wrong; detections are matched by centre.
  - The split text now says NLM by patient and UDOM by photo.
  - The header links [HACKATHON.md](HACKATHON.md).
- **README "How it uses Meta AI"** lists only the models the code calls, with the file for each:
  - SAM 3.1 images (`segmentation/sam.py`);
  - SAM 3.1 video (`tracking.py`);
  - Muse Spark (`agent.py`, `audit.py`, `meta/reviewer.py`).

  The open-weights and Muse Code rows were removed. No open-weights call exists in the code, and Muse Code was a development tool, not part of the product.
- **MODEL_CARD.md:**
  - The data section is now correct: 70% of UDOM is used for adaptation, and NM-AIST is test only.
  - Added a results table.
  - Added three limitations from the test: it is not a screen; Tanzanian smears are harder; image scale must match one oil-immersion field per photo.
- **Mismatch for the user to settle.** [HACKATHON.md](HACKATHON.md) and the plan describe three things that are not built:
  - Muse Voice Transcribe control;
  - SAM 3.1 box-prompt confirmation of candidates. The API does segment marked boxes, but parasites are confirmed by the verifier;
  - open-weights report drafting.

### 17. Tracking demo clip (2 Nov)

- **What it is.** `scripts/tracking_demo.py` pans 90 frames across one NIH **tuning** field (TF54_CW43), never a test field. It counts the field in hybrid mode with SAM 3.1 video tracking.
- **Outputs**, all in [`demo/`](demo/):
  - [`tracking_demo.mp4`](demo/tracking_demo.mp4), 0.3 MB: each track boxed and numbered, with the running count of unique objects and a closing summary;
  - [`tracking_contact.png`](demo/tracking_contact.png): six frames from the clip;
  - [`tracking_demo.json`](demo/tracking_demo.json): the counts and the label check.
- **Counts.** 12 unique parasites and 17 white cells, against 31 and 34 counted frame by frame. SAM 3.1 video cost US$0.08. The offline shift tracker gives the same counts.
- **Duplicates checked against the expert labels** (automatic, instead of by hand):

  | Duplicates | Parasites | White cells |
  | --- | ---: | ---: |
  | Across frames (tracking failures) | 0 | 0 |
  | Within one frame (detector boxed one object twice) | 2 | 1 |

  - Parasites: 9 of the 10 labelled in view were found, plus 1 track matching no label.
  - White cells: SAM's "cell" prompt splits some lobed white cells into two or three boxes. That explains most of the 10 white-cell tracks matching no label. It is a detection error, visible in the clip at #24 to #26.
- **Done when** (What's next row 2): met for a synthetic pan. Real phone video is still untested.

### 18. Completing the plan: two-stage detection, voice, open weights (2 Nov, evening)

The user asked to complete the implementation plan. Three Meta-tooling items were unbuilt; the API was read from Meta's docs first (voice API reference, SAM segmenting, Muse Spark Open deploy pages).

- **Two-stage detection (plan day 3).**
  - `MetaModelClient.segment_objects` sends up to 16 box prompts per request with `include_confidence`; corners are clamped (SAM rejects negatives, 400). `segmentation/confirm.py`: `BoxConfirmer` (1,024 px tiles) and `ConfirmedSegmenter` (segmenter `confirmed`: hybrid, then SAM confirms each kept parasite at *c* ≥ 0.70).
  - **Development check** (`scripts/two_stage.py`, [calibration/two_stage.md](calibration/two_stage.md)), 20 NIH val fields and 150 UDOM `check` tiles, 986 SAM requests (about US$2.50):

    | Rule | NIH val F1 | UDOM check F1 |
    | --- | ---: | ---: |
    | Candidates alone | 0.29 | 0.17 |
    | Candidates + SAM box confirmation | 0.41 | 0.35 |
    | Candidates + verifier | 0.84 | 0.43 |
    | Candidates + verifier + SAM box confirmation | 0.85 | 0.43 |

  - **Gate "two-stage beats either alone":** met against candidates alone and SAM's text prompt alone; not meaningfully against our verifier. SAM segments 99 to 100% of candidates with confidence 0.55 to 0.82: it confirms objectness, not parasites. `hybrid` stays the default.
- **Muse Voice Transcribe (plan day 5).**
  - `client.transcribe` (multipart `POST /asr/transcribe`, `muse-voice-transcribe-1.0`, keyword biasing); `voice.py` converts any audio PyAV reads to 16 kHz mono WAV and parses commands: next field, retake, finish, and "note …" (English and Kiswahili phrases).
  - `POST /v1/sessions/{id}/voice`; spoken notes are kept on the session and returned with the report as `voice_notes`.
  - **Live check:** synthetic English speech (Windows voice) gave exact transcripts for all four commands, through WAV and through AAC/M4A as the Android app records. **Kiswahili is not on the API's 25-language list**: an English voice reading "Sehemu inayofuata" came back as "See how many of weda" (with or without a Swahili language hint). Kiswahili voice is unconfirmed until a native speaker tries it.
  - **Android:** a microphone button on Capture (tap to record, tap to send; RECORD_AUDIO asked at first use). "Next field" and "retake" open the camera, "finish" finishes the slide, notes show in a snackbar and on the Report screen. Builds and unit tests pass (13). **Checked on the emulator:** the permission prompt, the listening state ([screenshot](calibration/android_voice.png)), and a recording sent end to end; the emulator has no audio input, so the reply was "nothing heard". A spoken command on a real phone is still to do.
  - **Web page:** the same button with `MediaRecorder`. A browser may refuse to open the camera this long after the tap; the photo button still works.
- **Muse Spark Open (open weights).** `OPEN_WEIGHTS_BASE_URL` / `OPEN_WEIGHTS_API_KEY` / `OPEN_WEIGHTS_MODEL` (default `meta-models/muse-spark-open`) and `darubini analyse --narrate open|muse`. The narrative is dropped if it quotes a number the count did not produce. **Not run live: no Baseten, Fireworks or Modal key.**
- Checks: 218 Python tests (97% coverage), ruff, mypy strict; Android unit tests and debug build.

## Open issues

1. **Parasite over-counting on some slides.** It is now flagged by the audit (step 7), not fixed. Remaining options:
   - hard-negative training on platelets and rods from tuning patients;
   - a calibrated audited density (divide by verifier recall, about 0.84);
   - re-checking the 60% flag on more slides.
2. **Audit repeatability.** Resolved 2 Nov by the per-tile prompt (step 12). What remains is that the flag is borderline for slides over-counted about 1.7×. A larger sample (40 tiles) would halve the sampling noise, for twice the image tokens.
3. **UDOM parasite accuracy (F1 0.46) is well below NIH (0.80).** The UDOM parasites are faint pink dots, and the adaptation set has only 414 training tiles. Options:
   - add the rest of the dev `adapt` half's context;
   - try a larger crop or a small convolutional network;
   - accept the result and report it honestly.
4. **UDOM white blood cell labels look incomplete.** On 300 dev tiles, every method (stain blobs, SAM "cell") finds about one more white blood cell per tile than is labelled, with precision near 0.22; some of these are cells cut by tile edges. Report UDOM white blood cell numbers per photo and flag them.
5. **The quality-gate deviation** is recorded and will be reported next to the test results.

## Decisions made

- **2 Nov: no lab session.** The existing datasets supply training and test sets. UDOM is now 70% train and 30% test by photo (step 13).
- **2 Nov: Credit Design Figma language** for the Android app (step 14).

- **30 Oct — Meta tooling in the pitch.** Keep the candidates + verifier design for parasites. The **Muse Spark agent and SAM video tracking are the centrepiece of the demo**. SAM is not added as an extra parasite candidate source.

## Decisions needed

1. **Commit the trained verifier.** `models/` is ignored by git. The demo and a fresh clone need `models/parasite_verifier.npz` (0.2 MB). Either un-ignore that one file or publish it as a release asset.
2. **Default segmenter.** `.env` still says `baseline`. `hybrid` is the best setting with the API and `verified` the best offline.
3. **Merge the branch.** Everything up to 2 Nov, including the final test results, is pushed as `feat/agent-tracking-android` and is waiting for a pull request into `main`.
4. ~~Claims in HACKATHON.md~~ Resolved 2 Nov (step 18): voice and two-stage box confirmation are now built. Remaining caveats for the write-up: two-stage adds little over the verifier, Kiswahili voice is unconfirmed, and Muse Spark Open has not run against a real host (a partner key would close this).

## What's next

| Priority | Task | Done when |
| --- | --- | --- |
| 1 | Install the Android app on a real phone and count a slide over Wi-Fi (photos from the datasets on screen are fine without a microscope) | A slide captured and reported from the phone |
| 2 | Real panning video for tracking (a phone clip of a slide). The synthetic-pan demo clip is done (step 17) | Real clip tracked; duplicates checked against step 17 |
| 3 | Improve UDOM parasite F1 (0.44 on the larger check half) | F1 on the `check` half clearly above 0.44 |
| Done | ~~Final test-set run~~ (2 Nov, step 15) | Ablation table in EVALUATION.md filled |
| Done | ~~Muse Spark agent~~, ~~SAM tracking~~, ~~phone capture app~~, ~~native Android app~~, ~~localised quality flags~~, ~~audit repeatability~~, ~~train/test split~~, ~~Figma restyle~~ | 30 Oct-2 Nov |

## Known risks

- **Tanzanian accuracy:** the UDOM gap is the main technical risk to the evaluation story.
- **Schedule:** we are about 1.5 days behind. The agent and the capture app are both unbuilt, and the feature freeze is Mon 2 Nov.
- **API cost:** about $5 spent. A final hybrid test run on 4,596 UDOM tiles costs about $11.50; a sam3 ablation on NIH 4K fields costs much more, so sample it.
