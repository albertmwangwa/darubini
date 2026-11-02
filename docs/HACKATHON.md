# Hackathon submission notes

Darubini is entered in the **Indie Developer track** of the Meta Global AI Developer Hackathon. Building period: **27 Oct to 4 Nov 2026**. Submission deadline: **4 Nov, 9:00 PM ET (Thu 5 Nov, 05:00 East Africa Time)**.

## What was built before and during the event

The rules require that what we present was built during the event and that our original contributions are easy to identify. We draw the line at one commit.

| | Before the building period | During the building period |
| --- | --- | --- |
| **Boundary** | Up to and including commit [`9c8d6b4`](https://github.com/albertmwangwa/darubini/commit/9c8d6b4) (25 Oct 2026) | [Every commit after `9c8d6b4`](https://github.com/albertmwangwa/darubini/compare/9c8d6b4...main) |
| **Contents** | Repository scaffolding and CI; dataset manifest, downloader, profiler and annotation parsers; WHO-style counting engine; image quality checks; offline baseline detector; report templates; an API client written against guessed routes | Everything that uses Meta models: SAM 3.1 segmentation, two-stage box confirmation, video tracking, the Muse Spark counting agent, Muse Voice Transcribe control, evaluation results, the phone capture app and the demo |
| **Meta models called** | None | All Meta model usage |

The demo and video show only work from the second column. Pre-event pieces appear only as named infrastructure ("the counting engine we brought in"), never as hackathon work.

## How Darubini stays clear of the excluded project types

The participant guide excludes projects that use AI to give medical advice, and simple image analysers.

- **No medical advice.** Darubini is a counting instrument. It outputs counts, a density estimate computed by deterministic code, and image-quality flags. It never states a diagnosis, never recommends treatment, and every report says a qualified microscopist must confirm the result. The language model writes narrative around computed numbers and is instructed never to change them or advise.
- **Not a simple image analyser.** The core is an agentic workflow: field-by-field capture, a quality gate, two-stage detection, a WHO stopping rule that decides when enough fields have been counted, video tracking to avoid double counting, and an evaluation on held-out Tanzanian slides.
- **Problem statement.** *Push the Frontier*: give an ordinary laboratory microscope a new capability.

## Judging

Stage One is pass/fail on theme fit and real use of Meta models. Stage Two scores Impact, Use of Meta AI tooling, Technical depth and execution, and Demo, each 0 to 10 per the participant guide (the Official Rules weight them 30/25/20/25; we plan for both). The top five per track go to a live final.

## Submission checklist

- [ ] Repository public (it is)
- [ ] README states what was built during the event and links this page
- [ ] Three-minute demo video showing only hackathon work
- [ ] Live product link works on a phone
- [ ] Every Meta model used is named, with where it is called in code
- [ ] Dataset citations and licences in place
- [ ] Submitted on the Cerebral Valley portal before Thu 5 Nov, 05:00 EAT
