# Implementation Plan

**Goal: first prize, Indie Developer track ($150,000).** Building period: **Tue 27 Oct to Wed 4 Nov 2026**. Submission closes **Thu 5 Nov, 05:00 EAT** (4 Nov, 9:00 PM ET) on the Cerebral Valley portal. All times below are East Africa Time: ET + 7 hours until US clocks change on Sun 1 Nov, ET + 8 hours after.

Two rules shape everything below (see [`HACKATHON.md`](HACKATHON.md)):

- **New work only.** Only what is built from 27 Oct counts, and it must be easy to identify. Pre-event scaffolding ends at commit `9c8d6b4`.
- **No medical advice, no simple image analysers.** Darubini is a counting instrument with an agentic workflow, never a diagnosis tool.

## 1. Build to the scoring rubric

The participant guide scores four criteria 0 to 10 each; the Official Rules weight them 30/25/20/25. Every task below serves at least one.

| Criterion | Rules weight | What the judges look for | How Darubini scores |
| --- | --- | --- | --- |
| **Impact** | 30% | Real-world potential, who benefits, whether people would use it | Malaria kills about 610,000 people a year; Tanzania ranks fourth for deaths. A phone-plus-microscope tool for labs that already exist, tested on Tanzanian slides, reporting in Kiswahili |
| **Use of Meta AI tooling** | 25% | Creative use beyond basic integration, unexpected capabilities | SAM 3.1 noun-phrase segmentation **and** box-prompt confirmation of detector candidates; SAM 3.1 video tracking to avoid double counts; Muse Spark as a tool-calling counting agent; Muse Voice Transcribe for hands-free Kiswahili control; open weights for offline reports |
| **Demo** | 25% | Working, impressive, holds up live; video quality | Live run on a real microscope: masks appear over parasites, the count climbs, the stopping rule fires, the report prints in Kiswahili |
| **Technical depth and execution** | 20% | Sound engineering, refinement, craft | Strict typing, coverage gate, security scans, photo- and patient-level splits, ablation tables, a model card |

## 2. What the Meta Model API actually offers (from Meta's cookbook)

| Capability | How it is called | Darubini use |
| --- | --- | --- |
| Muse Spark `muse-spark-1.3` | OpenAI-compatible chat at `https://api.meta.ai/v1`, key in `MODEL_API_KEY`; tool calling, structured output, vision input, prompt caching | Counting agent, field quality review, bilingual reports |
| SAM 3.1 `sam-3.1` | Responses API, streamed; `input_text` is **either** one noun phrase **or** object prompts (boxes and points per object), never both; decode with `meta_sam_parser` | Noun-phrase pass per field; box prompts to confirm each baseline candidate; video tracking with `propagation_direction` |
| Muse Voice Transcribe | Voice API (cookbook section 06) | "Next field", spoken notes in Kiswahili |
| Muse Glimmer, Muse Spark Open | Open weights through Baseten, Modal or Fireworks (use `meta-models/muse-spark-open-1026` on Baseten) | Offline report drafting |

The earlier idea of "exemplar" prompts (show a few parasites, find the rest) is **not** supported: object prompts segment the objects they name. The two-stage design replaces it.

## 3. Before the building period (today, Mon 26 Oct)

| Task | Done when |
| --- | --- |
| Claim the US$150 Meta Model API credits (form in the guide; a card must be on the account) and set a spend-limit alert on the Billing page | Credits visible on Billing |
| Request Modal (first 1,000 people), Baseten (2,000) and Fireworks credits | Forms submitted |
| Join Discord; post in #intros; ask in #questions whether disclosed pre-event scaffolding is acceptable for the Indie track | Answer recorded in `HACKATHON.md` |
| Watch the kickoff, **19:00 EAT** | Any rule changes noted |
| Book a microscope and stained slides (UDSM or Muhimbili lab) for **Mon 2 Nov**, plus a backup slot; buy a phone eyepiece adapter | Confirmed in writing |

No product code is written today, so the building-period boundary stays clean.

## 4. Day by day

Live sessions are at 19:00 EAT; Meta office hours run in Discord #office-hours on weekdays at **17:00 to 18:00 EAT**, moving to **18:00 to 19:00 EAT** from Mon 2 Nov.

| Day | Date | Focus | Output | Gate |
| --- | --- | --- | --- | --- |
| 1 | Tue 27 Oct | Real API | `meta/client.py` on the OpenAI SDK + `meta_sam_parser`; SAM 3.1 noun-phrase run on 20 NLM fields; Agents 101 session | First real masks on a real smear |
| 2 | Wed 28 Oct | SAM 3.1 at scale | Cached batch runner; noun-phrase variants ("malaria parasite", "ring-form trophozoite", "white blood cell nucleus"); Agents 102 session | Detection F1 on NLM validation patients |
| 3 | Thu 29 Oct | Two-stage detection | Baseline proposes candidates, SAM 3.1 box prompts confirm each; compare with noun phrase alone | Two-stage beats either alone on F1 |
| 4 | Fri 30 Oct | Tanzanian evaluation | Count MAE, bias and *r* on UDOM (grouped by photo); slide sensitivity and specificity on NM-AIST and NLM uninfected; Fireworks session | Tables in `docs/EVALUATION.md` |
| 5 | Sat 31 Oct | Muse Spark agent + voice | Tool-calling loop (`assess_field`, `segment_field`, `get_count`), structured output; Muse Voice Transcribe for "next field" and Kiswahili notes | Agent finishes a full slide unattended |
| 6 | Sun 1 Nov | Phone capture app + tracking | Camera capture, mask overlay, running count, report screen; SAM 3.1 video tracking across a panning stream | Works on a phone over a 3G-class link |
| 7 | **Mon 2 Nov** | **Live lab session + feature freeze** | Real microscope run beside a microscopist's manual count; film B-roll | Side-by-side count captured; **no new features after today** |
| 8 | Tue 3 Nov | Video and write-up | 3-minute video; README results; model card; `HACKATHON.md` checklist | Video exported; last day for organiser questions |
| 9 | Wed 4 Nov | Submit | Final checks, submit by **18:00 EAT** (11 hours of buffer) | Submission confirmed |

## 5. Demo plan

**Live (finals):** phone on eyepiece, run a positive slide; masks appear; the count climbs; the stopping rule fires at 200 WBC; the Kiswahili report prints. Then a negative slide shows the negative rule. A pre-recorded fallback is ready in case the network fails.

**Video (3 minutes), showing only hackathon work:**

| Time | Scene |
| --- | --- |
| 0:00–0:20 | A Dar es Salaam lab, a microscopist counting by hand; the malaria burden in one line |
| 0:20–1:40 | Live run: voice "next field", a blurry field rejected, SAM 3.1 masks, the running count, the Kiswahili report |
| 1:40–2:20 | Under the hood: two-stage detection, video tracking, the Muse Spark agent's tool calls |
| 2:20–2:50 | Results on Tanzanian slides it never trained on, plus the ablation table |
| 2:50–3:00 | The microscopist confirms: "a counting instrument, not a diagnosis"; repo link |

## 6. Risks and fallbacks

| Risk | Likelihood | Fallback |
| --- | --- | --- |
| Judges read it as "medical advice" or a "simple image analyser" | Medium | Counting-instrument framing everywhere; no diagnosis wording; agentic workflow front and centre; ask organisers early |
| Pre-event scaffolding questioned | Medium | Commit boundary `9c8d6b4`, `HACKATHON.md`, demo shows only new work |
| SAM 3.1 misses tiny parasites | Medium | Tile fields into crops; two-stage box confirmation; noun-phrase ablations |
| US$150 credits run out | Medium | Cache every response; fixed 300-image ablation subset; spend-limit alert; partner credits for open weights |
| No microscope on demo day | Low | Backup slot; recorded session from day 7 |
| Power or internet cut in Dar | Medium | UPS and mobile data; cloud workspace; video recorded by day 8 |

## 7. Definition of done for submission

See the checklist in [`HACKATHON.md`](HACKATHON.md).
