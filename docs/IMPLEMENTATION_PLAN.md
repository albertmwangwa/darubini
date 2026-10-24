# Implementation Plan

**Goal: first prize, Indie Developer track ($150,000).** Build period: Mon 26 Oct to Wed 4 Nov 2026. Submission closes **Thu 5 Nov, 05:00 EAT** (4 Nov, 9:00 PM ET) on the Cerebral Valley portal. All times below are East Africa Time.

## 1. Build to the scoring rubric

The official rules score projects on four criteria. Every task in this plan serves at least one of them.

| Criterion | Weight | What the judges look for | How Darubini scores |
| --- | --- | --- | --- |
| **Impact** | 30% | Real-world potential, who benefits, how much it matters, could people use it | Malaria kills about 610,000 people a year; Tanzania ranks fourth for deaths. A phone-plus-microscope tool for existing labs, tested on Tanzanian slides, with a Kiswahili report |
| **Use of Meta AI tooling** | 25% | Creative use, beyond basic integration, unexpected capabilities | SAM 3 text **and** exemplar prompts adapted per slide; SAM 3 video tracking to avoid double counts; Muse Spark as a tool-calling counting agent and QC second reader; open weights for offline Kiswahili |
| **Demo** | 25% | Working, impressive, holds up live, video quality | Live run on a real microscope: masks appear over parasites, the count climbs, the stopping rule fires, the report prints in Kiswahili |
| **Technical depth and execution** | 20% | Sound engineering, refinement, craft | Strict typing, 80%+ coverage gate, security scans, patient-level splits, ablation tables, a model card |

## 2. Before kickoff (Sat 24 to Mon 26 Oct, morning)

| Task | Done when |
| --- | --- |
| Repo, CI, counting engine, baseline, API, CLI | CI green on `main` (done) |
| Run `make data` on the local machine | Core datasets in `datasets/raw/` with `.complete` markers |
| Verify the NLM annotation parser on real files | `parse_nlm_thick` returns sensible boxes on 5 sample images; fix the layout if needed |
| Baseline numbers | Baseline segmenter count MAE on UDOM Tanzania recorded in `docs/EVALUATION.md` |
| Book a microscope | A UDSM or Muhimbili lab contact agrees to 2 hours on **Mon 2 Nov** and a backup slot; buy a phone eyepiece adapter |
| Collect stained slides | Ask the lab for anonymised positive and negative Giemsa thick films for the demo |

## 3. Day by day

| Day | Date | Focus | Output | Gate |
| --- | --- | --- | --- | --- |
| 1 | Mon 26 Oct | Kickoff, API access | Claim credits; wire `ApiRoutes` and payload mappers in `meta/client.py`; run SAM 3 on 10 fields; assess Glimmer and other announced tools | First SAM 3 masks on a real smear |
| 2 | Tue 27 Oct | SAM 3 at scale | Batch runner with caching (each image is sent once); prompt variants ("malaria parasite", "ring-form trophozoite", "small purple dot") | Detection F1 on NLM validation patients |
| 3 | Wed 28 Oct | Exemplar prompting | Per-slide adaptation: 3 to 5 confirmed parasites as visual exemplars; compare with text-only | Exemplars beat text-only on F1 |
| 4 | Thu 29 Oct | Tanzanian evaluation | Count MAE, bias and *r* on UDOM Tanzania; slide sensitivity and specificity on NM-AIST and NLM uninfected | Tables in `docs/EVALUATION.md` |
| 5 | Fri 30 Oct | Muse Spark agent | Tool-calling loop: `assess_field`, `segment_field`, `get_count`; QC review; Kiswahili and English narrative | Agent finishes a full slide unattended |
| 6 | Sat 31 Oct | Live capture app | Phone web app: camera capture, mask overlay, running count, "next field" prompt, report screen | Works on a phone over 3G-class speed |
| 7 | Sun 1 Nov | Video tracking and polish | SAM 3 tracking across a panning eyepiece video to de-duplicate parasites; error states; offline fallback to baseline | Tracking demo clip recorded |
| 8 | Mon 2 Nov | **Live lab session + feature freeze** | Real microscope run with a microscopist's manual count alongside; record B-roll | Side-by-side count captured; **no new features after today** |
| 9 | Tue 3 Nov | Video and write-up | 3-minute video; README results; model card limits; submission text | Video exported; repo tagged `v1.0.0` |
| 10 | Wed 4 Nov | Submit | Final checks, submit by **18:00 EAT** (11 hours of buffer) | Submission confirmed on the portal |

## 4. Meta tooling: going past a basic call

1. **Concept segmentation with domain prompts.** Treat prompt wording as a hyperparameter and report its effect.
2. **Exemplar adaptation.** The microscopist taps 3 to 5 parasites; SAM 3 uses them as visual exemplars for the rest of the slide. Stain colour varies between labs; this adapts to it without any retraining.
3. **Video tracking.** Pan the slide on video and let SAM 3 track instances, so one parasite seen in two frames counts once.
4. **Muse Spark as an agent, not a chatbot.** It calls deterministic tools, decides when the counting rule is met, flags disagreement between SAM 3 and the baseline, and writes the bilingual report. It never invents a number.
5. **Open weights for the edge.** A small open-weights model drafts Kiswahili reports offline, for clinics with unreliable internet.

## 5. Demo plan

**Live (finals):** phone on eyepiece, run a positive slide; masks appear; the count climbs; the stopping rule fires at 200 WBC; the Kiswahili report prints. Then a negative slide shows the negative rule. Have a pre-recorded fallback video ready in case the network fails.

**Video (3 minutes):**

| Time | Scene |
| --- | --- |
| 0:00–0:20 | A Dar es Salaam lab, a microscopist counting by hand; the malaria burden in one line |
| 0:20–1:40 | Live run: capture, quality gate rejecting a blurry field, SAM 3 masks, running count, Kiswahili report |
| 1:40–2:20 | Under the hood: exemplar adaptation, tracking, the Muse Spark agent's tool calls |
| 2:20–2:50 | Results on Tanzanian slides it never trained on, plus the ablation table |
| 2:50–3:00 | Microscopist confirms; "decision support, not replacement"; repo link |

## 6. Risks and fallbacks

| Risk | Likelihood | Fallback |
| --- | --- | --- |
| SAM 3 misses tiny parasites | Medium | Exemplar prompts; tile fields into crops; baseline candidates verified by SAM 3 |
| API quota (US$150 credits) runs out | Medium | Cache every response; run ablations on a fixed 300-image subset; partner credits for open weights |
| API routes differ from assumptions | High | Only `meta/client.py` changes; tests mock the transport |
| No microscope on demo day | Low | Booked backup slot; recorded session from Day 8 |
| Power or internet cut in Dar | Medium | UPS and mobile data; cloud dev box; video recorded by Day 9 |
| Over-claiming clinical performance | Low | Model card limits; language reviewed; microscopist in the loop |

## 7. Definition of done for submission

- [ ] CI green on `main`, tag `v1.0.0`
- [ ] `docs/EVALUATION.md` has real numbers, including the ablations
- [ ] Live demo URL works on a phone
- [ ] 3-minute video uploaded
- [ ] README states what Meta tools are used and how
- [ ] Model card lists limits and intended use
- [ ] Dataset citations in place
