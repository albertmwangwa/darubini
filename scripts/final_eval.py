"""The one-time final evaluation (protocol: docs/EVALUATION.md, "Final test protocol").

Stages, each resumable:

    python scripts/final_eval.py detect SET SEGMENTER [--workers 6] [--final-test]
    python scripts/final_eval.py agent [--final-test]     # Muse Spark agent + audit on NIH test slides
    python scripts/final_eval.py report [--final-test]    # all metrics -> docs/calibration/final_test.md

Every field's detections and quality-gate result are cached as JSON lines under
datasets/processed/final/, so each image is segmented once per segmenter and the
metrics never re-run a model.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from darubini.config import get_settings
from darubini.data.annotations import parse_nlm_thick
from darubini.data.fields import nlm_thick_fields, patient_split, udom_fields
from darubini.evaluation import match_centres
from darubini.pipeline import load_image
from darubini.quality import assess
from darubini.types import BoundingBox, Detection, ObjectClass

RAW = Path("datasets/raw")
OUT = Path("datasets/processed/final")
REPORT = Path("docs/calibration/final_test.md")
UNINFECTED = RAW / "nih-thick-uninfected" / "NIH-NLM-ThickBloodSmearsU"
SEED = 0
TEST_SETS = {"nih_test", "unin_test", "udom_test", "nm_aist", "nih_test_s60", "udom_test_s300"}


@dataclass(frozen=True)
class Item:
    """One image: its cache key, path, slide (patient or photo) and slide label."""

    key: str
    image: Path
    slide: str
    infected: bool


# ---------------------------------------------------------------- sets


def _labelled(fields: Iterable[object], infected: bool) -> list[Item]:
    return [Item(str(f.image), f.image, f.patient, infected) for f in fields]  # type: ignore[attr-defined]


def uninfected_fields(split_names: set[str]) -> list[tuple[Item, list[Detection]]]:
    """NIH uninfected patients in the given splits, with their WBC labels."""
    out = []
    for pdir in sorted((UNINFECTED / "Uninfected Patients").iterdir()):
        if not pdir.is_dir() or patient_split(pdir.name) not in split_names:
            continue
        for image in sorted((pdir / "tiled").glob("*.tiff")):
            gt = UNINFECTED / "Annotations" / pdir.name / f"{image.stem}.txt"
            truth = parse_nlm_thick(gt) if gt.is_file() else []
            out.append((Item(str(image), image, pdir.name, False), truth))
    return out


def unin_dev_patients() -> set[str]:
    """All uninfected val patients plus 16 tune patients (seed 0), as pre-registered."""
    names = sorted(p.name for p in (UNINFECTED / "Uninfected Patients").iterdir() if p.is_dir())
    val = [n for n in names if patient_split(n) == "val"]
    tune = [n for n in names if patient_split(n) == "tune"]
    return set(val) | set(random.Random(SEED).sample(tune, 16))


def nm_aist_items() -> list[Item]:
    root = RAW / "nm-aist-tz"
    out = []
    for folder, infected in (("Thick_Infected", True), ("Thick_Uninfected", False)):
        images = sorted((root / folder / folder).glob("*.jpg"))
        pick = sorted(random.Random(SEED).sample(images, min(400, len(images))))
        out += [Item(str(p), p, f"{folder}/{p.stem}", infected) for p in pick]
    return out


def items(name: str) -> list[Item]:
    nih = RAW / "nih-thick-pf-150"
    udom = RAW / "udom-tz-thick"
    if name == "nih_val":
        return _labelled(nlm_thick_fields(nih, "val"), True)
    if name == "nih_test":
        return _labelled(nlm_thick_fields(nih, "test"), True)
    if name == "nih_test_s60":
        return sorted(random.Random(SEED).sample(items("nih_test"), 60), key=lambda i: i.key)
    if name == "unin_dev":
        keep = unin_dev_patients()
        return [i for i, _ in uninfected_fields({"tune", "val"}) if i.slide in keep]
    if name == "unin_test":
        return [i for i, _ in uninfected_fields({"test"})]
    if name == "udom_test":
        return _labelled(udom_fields(udom, "test"), True)
    if name == "udom_test_s300":
        return sorted(random.Random(SEED).sample(items("udom_test"), 300), key=lambda i: i.key)
    if name == "nm_aist":
        return nm_aist_items()
    raise SystemExit(f"unknown set {name}")


def truths(name: str) -> dict[str, list[Detection]]:
    """Expert boxes by cache key (uninfected sets have WBC labels only)."""
    if name in ("unin_dev", "unin_test"):
        split = {"unin_dev": {"tune", "val"}, "unin_test": {"test"}}[name]
        return {i.key: t for i, t in uninfected_fields(split)}
    if name.startswith("nih"):
        split = "val" if name == "nih_val" else "test"
        return {
            str(f.image): list(f.truth) for f in nlm_thick_fields(RAW / "nih-thick-pf-150", split)
        }
    if name.startswith("udom"):
        return {str(f.image): list(f.truth) for f in udom_fields(RAW / "udom-tz-thick", "test")}
    return {}


# ---------------------------------------------------------------- detect

_SEGMENTER = None


def _init(segmenter: str) -> None:
    global _SEGMENTER
    from darubini.segmentation.base import get_segmenter

    _SEGMENTER = get_segmenter(get_settings().model_copy(update={"segmenter": segmenter}))


def _run(item: Item) -> dict[str, object]:
    image = load_image(item.image)
    quality = assess(image)
    dets = _SEGMENTER.segment(image)  # type: ignore[union-attr]
    return {
        "key": item.key,
        "slide": item.slide,
        "infected": item.infected,
        "usable": quality.usable,
        "flags": list(quality.flags),
        "dets": [
            [d.cls.value, d.box.x_min, d.box.y_min, d.box.x_max, d.box.y_max, round(d.score, 4)]
            for d in dets
        ],
    }


def cache_path(name: str, segmenter: str) -> Path:
    return OUT / f"{name}__{segmenter}.jsonl"


def load_cache(name: str, segmenter: str) -> dict[str, dict]:
    path = cache_path(name, segmenter)
    if not path.is_file():
        return {}
    return {r["key"]: r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def detect(name: str, segmenter: str, workers: int) -> None:
    todo = [i for i in items(name) if i.key not in load_cache(name, segmenter)]
    print(f"{name} / {segmenter}: {len(todo)} images to run", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (
        cache_path(name, segmenter).open("a", encoding="utf-8") as fh,
        ProcessPoolExecutor(workers, initializer=_init, initargs=(segmenter,)) as pool,
    ):
        for n, row in enumerate(pool.map(_run, todo, chunksize=2), 1):
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            if n % 25 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}", flush=True)


# ---------------------------------------------------------------- metrics


def dets_of(row: dict, cls: ObjectClass) -> list[Detection]:
    return [
        Detection(ObjectClass(c), BoundingBox(*box), s)
        for c, *box, s in row["dets"]
        if c == cls.value
    ]


def field_scores(name: str, segmenter: str) -> dict[str, dict[str, float]]:
    cache, truth = load_cache(name, segmenter), truths(name)
    out = {}
    for cls in (ObjectClass.PARASITE, ObjectClass.WBC):
        tp = fp = fn = 0
        errors = []
        for key, row in cache.items():
            t = [d for d in truth.get(key, []) if d.cls is cls]
            p = dets_of(row, cls)
            s = match_centres(p, t, cls)
            tp, fp, fn = tp + s.true_positives, fp + s.false_positives, fn + s.false_negatives
            errors.append(len(p) - len(t))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        e = np.asarray(errors, dtype=float)
        out[cls.value] = {
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "mae": float(np.abs(e).mean()),
            "bias": float(e.mean()),
            "labelled": tp + fn,
            "fields": len(cache),
        }
    return out


def per_slide(name: str, segmenter: str) -> dict[str, dict[str, float]]:
    """Usable-field totals per slide: predicted and expert parasites and WBC."""
    cache, truth = load_cache(name, segmenter), truths(name)
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for key, row in cache.items():
        s = out[row["slide"]]
        s["infected"] = float(row["infected"])
        s["fields"] += 1
        if not row["usable"]:
            continue
        s["usable"] += 1
        s["p"] += len(dets_of(row, ObjectClass.PARASITE))
        s["w"] += len(dets_of(row, ObjectClass.WBC))
        t = truth.get(key, [])
        s["tp_"] += sum(d.cls is ObjectClass.PARASITE for d in t)
        s["tw"] += sum(d.cls is ObjectClass.WBC for d in t)
    return out


def choose_threshold(pos: list[float], neg: list[float]) -> float:
    """Youden-optimal cut-off, midway between observed values; ties go to the lowest."""
    values = sorted(set(pos) | set(neg))
    cuts = (
        [v / 2 for v in values[:1]]
        + [(a + b) / 2 for a, b in itertools.pairwise(values)]
        + [values[-1] + 1]
    )
    best, best_j = cuts[0], -2.0
    for c in cuts:
        j = sum(v >= c for v in pos) / len(pos) + sum(v < c for v in neg) / len(neg) - 1
        if j > best_j + 1e-12:
            best, best_j = c, j
    return best


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n:.0%} ({lo:.0%}–{hi:.0%})" if n else "–"


def mean_per_field(s: dict[str, float]) -> float:
    return s["p"] / s["usable"] if s["usable"] else 0.0


def field_counts(name: str, segmenter: str, positive_only_labelled: bool) -> list[float]:
    cache, truth = load_cache(name, segmenter), truths(name)
    out = []
    for key, row in cache.items():
        if positive_only_labelled and not any(
            d.cls is ObjectClass.PARASITE for d in truth.get(key, [])
        ):
            continue
        out.append(float(len(dets_of(row, ObjectClass.PARASITE))))
    return out


def report() -> str:
    lines = [
        "# Final test results",
        "",
        "Generated by `scripts/final_eval.py report` under the protocol fixed in "
        "[EVALUATION.md](../EVALUATION.md#final-test-protocol-fixed-2-nov-2026-before-any-test-data-was-scored). "
        "Ranges are Wilson 95% intervals.",
        "",
    ]

    lines += ["## 1. Field level: detection and count agreement", ""]
    for name, label in (
        ("nih_test", "NIH test (24 patients)"),
        ("udom_test", "UDOM test (180 photos)"),
        ("nih_test_s60", "NIH test, 60-field sample"),
        ("udom_test_s300", "UDOM test, 300-tile sample"),
    ):
        segs = ["sam3"] if name.endswith(("s60", "s300")) else ["baseline", "verified", "hybrid"]
        segs = [s for s in segs if cache_path(name, s).is_file()]
        if not segs:
            continue
        lines += [
            f"### {label}",
            "",
            "| Segmenter | Class | Fields | Labelled | Precision | Recall | F1 | Count MAE | Count bias |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for seg in segs:
            for cls, m in field_scores(name, seg).items():
                lines.append(
                    f"| {seg} | {cls} | {m['fields']} | {m['labelled']} | {m['precision']:.2f} | {m['recall']:.2f} | "
                    f"{m['f1']:.2f} | {m['mae']:.1f} | {m['bias']:+.1f} |"
                )
        lines.append("")

    lines += [
        "## 2. Slide density (24 infected NIH test patients, usable fields)",
        "",
        "| Segmenter | Median predicted/expert | Within ±25% | Within 2× | Pearson r (log10 density) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for seg in ("verified", "hybrid"):
        if not cache_path("nih_test", seg).is_file():
            continue
        slides = per_slide("nih_test", seg)
        ratios, logs = [], []
        for s in slides.values():
            if s["w"] and s["tw"] and s["tp_"]:
                pred, true = 8000 * s["p"] / s["w"], 8000 * s["tp_"] / s["tw"]
                ratios.append(pred / true)
                logs.append((math.log10(max(pred, 1)), math.log10(true)))
        r = np.asarray(ratios)
        n = len(r)
        corr = float(np.corrcoef(*zip(*logs, strict=False))[0, 1]) if n > 2 else float("nan")
        lines.append(
            f"| {seg} | {np.median(r):.2f} | {rate(int(((r >= 0.75) & (r <= 1.25)).sum()), n)} | "
            f"{rate(int(((r >= 0.5) & (r <= 2)).sum()), n)} | {corr:.2f} |"
        )
    lines.append("")

    lines += [
        "## 3. Slide call: infected against uninfected (31 NIH test slides)",
        "",
        "| Segmenter | Rule | Threshold (from development slides) | Sensitivity | Specificity |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for seg in ("verified", "hybrid"):
        need = [("nih_val", seg), ("unin_dev", seg), ("nih_test", seg), ("unin_test", seg)]
        if not all(cache_path(*n).is_file() for n in need):
            continue
        dev_pos = [mean_per_field(s) for s in per_slide("nih_val", seg).values()]
        dev_neg = [mean_per_field(s) for s in per_slide("unin_dev", seg).values()]
        t = choose_threshold(dev_pos, dev_neg)
        pos = [mean_per_field(s) for s in per_slide("nih_test", seg).values()]
        neg = [mean_per_field(s) for s in per_slide("unin_test", seg).values()]
        for rule, cut in (("any parasite", 1e-9), ("mean parasites per field ≥ T", t)):
            tp, tn = sum(v >= cut for v in pos), sum(v < cut for v in neg)
            lines.append(
                f"| {seg} | {rule} | {'–' if rule == 'any parasite' else f'{t:.2f}'} | {rate(tp, len(pos))} | {rate(tn, len(neg))} |"
            )
    lines.append("")

    lines += [
        "## 4. Image call on NM-AIST (Tanzania, 400 infected + 400 uninfected thick-film images)",
        "",
        "| Segmenter | Threshold k (from development fields) | Sensitivity | Specificity |",
        "| --- | ---: | --- | --- |",
    ]
    for seg in ("verified", "hybrid"):
        need = [("nih_val", seg), ("unin_dev", seg), ("nm_aist", seg)]
        if not all(cache_path(*n).is_file() for n in need):
            continue
        k = choose_threshold(
            field_counts("nih_val", seg, True), field_counts("unin_dev", seg, False)
        )
        cache = load_cache("nm_aist", seg)
        pos = [len(dets_of(r, ObjectClass.PARASITE)) for r in cache.values() if r["infected"]]
        neg = [len(dets_of(r, ObjectClass.PARASITE)) for r in cache.values() if not r["infected"]]
        lines.append(
            f"| {seg} | {k:.1f} | {rate(sum(v >= k for v in pos), len(pos))} | {rate(sum(v < k for v in neg), len(neg))} |"
        )
    lines.append("")

    agent = OUT / "agent_nih_test.jsonl"
    if agent.is_file():
        rows = [json.loads(x) for x in agent.read_text(encoding="utf-8").splitlines()]
        lines += ["## 5. Muse Spark on the 31 NIH test slides (hybrid)", ""]
        lines += agent_section(rows)
    return "\n".join(lines) + "\n"


def agent_section(rows: list[dict]) -> list[str]:
    infected = [r for r in rows if r["infected"]]
    clean = [r for r in rows if not r["infected"]]
    over = [r for r in infected if r.get("ratio") and r["ratio"] >= 1.5]
    fine = [r for r in infected if r.get("ratio") and r["ratio"] < 1.5]
    out = ["| Measure | Result |", "| --- | --- |"]
    out.append(
        f"| Agent finished by itself (not the fallback) | {rate(sum(r['finished_by_agent'] for r in rows), len(rows))} |"
    )
    out.append(
        f"| Fields excluded by the agent | {sum(r['excluded'] for r in rows)} of {sum(r['examined'] for r in rows)} examined |"
    )
    ar = np.asarray([r["agent_ratio"] for r in infected if r.get("agent_ratio")])
    if len(ar):
        out.append(
            f"| Agent density, median predicted/expert (infected) | {np.median(ar):.2f}; within ±25%: "
            f"{rate(int(((ar >= 0.75) & (ar <= 1.25)).sum()), len(ar))} |"
        )
    for label, key in (("agent run", "agent_flag"), ("audit alone", "audit_flag")):
        out.append(
            f"| Flag ({label}) on slides over-counted ≥1.5× | {rate(sum(bool(r.get(key)) for r in over), len(over))} |"
        )
        out.append(
            f"| Flag ({label}) on infected slides counted within 1.5× | {rate(sum(bool(r.get(key)) for r in fine), len(fine))} |"
        )
        out.append(
            f"| Flag ({label}) on uninfected slides (sent for review) | {rate(sum(bool(r.get(key)) for r in clean), len(clean))} |"
        )
    return [*out, ""]


# ---------------------------------------------------------------- agent


def run_agent() -> None:
    from darubini.agent import CapturedField, CountingAgent, SlideSession
    from darubini.audit import MuseAuditor
    from darubini.meta.client import MetaModelClient
    from darubini.meta.reviewer import MuseReviewer
    from darubini.pipeline import Pipeline
    from darubini.segmentation.base import get_segmenter
    from darubini.types import FieldResult
    from darubini.video import resize_to

    s = get_settings()
    client = MetaModelClient.from_settings(s)
    model = s.meta_reasoning_model
    pipeline = Pipeline(get_segmenter(s.model_copy(update={"segmenter": "verified"})))
    out = OUT / "agent_nih_test.jsonl"
    done = (
        {json.loads(x)["slide"] for x in out.read_text(encoding="utf-8").splitlines()}
        if out.is_file()
        else set()
    )
    caches = {
        "nih_test": load_cache("nih_test", "hybrid"),
        "unin_test": load_cache("unin_test", "hybrid"),
    }
    for name, cache in caches.items():
        slides: dict[str, list[dict]] = defaultdict(list)
        for row in cache.values():
            slides[row["slide"]].append(row)
        truth = truths(name)
        for slide, rows in sorted(slides.items()):
            if slide in done:
                continue
            rows.sort(key=lambda r: r["key"])
            fields = []
            tp_ = tw = 0
            for r in rows:
                if not r["usable"]:
                    continue
                image = load_image(Path(r["key"]))
                result = FieldResult(field_id=Path(r["key"]).name, quality_flags=list(r["flags"]))
                result.detections = dets_of(r, ObjectClass.PARASITE) + dets_of(r, ObjectClass.WBC)
                captured = CapturedField.from_image(image, result)
                captured.image = resize_to(image, 1024)
                fields.append((result.field_id, captured))
                t = truth.get(r["key"], [])
                tp_ += sum(d.cls is ObjectClass.PARASITE for d in t)
                tw += sum(d.cls is ObjectClass.WBC for d in t)
            crops = [c for _, f in fields for c in f.crops]
            audit = MuseAuditor(client, model).audit(crops) if crops else None
            session = SlideSession(
                pipeline,
                fields,
                reviewer=MuseReviewer(client, model),
                auditor=MuseAuditor(client, model),
            )
            res = CountingAgent(client, model).run(session, "en")
            p_all = sum(
                sum(d.cls is ObjectClass.PARASITE for d in f.result.detections) for _, f in fields
            )
            w_all = sum(
                sum(d.cls is ObjectClass.WBC for d in f.result.detections) for _, f in fields
            )
            true_density = 8000 * tp_ / tw if tw and tp_ else None
            row = {
                "slide": slide,
                "infected": name == "nih_test",
                "examined": res.count.fields_examined,
                "excluded": len(res.excluded),
                "finished_by_agent": res.finished_by_agent,
                "agent_density": res.count.density_per_ul,
                "agent_flag": bool(res.audit and res.audit.flagged),
                "audit_flag": bool(audit and audit.flagged),
                "audit_share": audit.confirmed_share if audit else None,
                "ratio": (8000 * p_all / w_all) / true_density if true_density and w_all else None,
                "agent_ratio": (res.count.density_per_ul / true_density)
                if true_density and res.count.density_per_ul
                else None,
                "tool_calls": len(res.steps),
            }
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            print(
                slide,
                {k: row[k] for k in ("examined", "excluded", "agent_flag", "audit_flag", "ratio")},
                flush=True,
            )


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("set")
    d.add_argument("segmenter", choices=["baseline", "verified", "hybrid", "sam3"])
    d.add_argument("--workers", type=int, default=6)
    for p in (d, sub.add_parser("agent"), sub.add_parser("report")):
        p.add_argument(
            "--final-test", action="store_true", help="confirm scoring the frozen test sets"
        )
    args = ap.parse_args()
    if not args.final_test and (args.cmd != "detect" or args.set in TEST_SETS):
        print("error: this touches the frozen test sets; pass --final-test to confirm")
        return 2
    if args.cmd == "detect":
        detect(args.set, args.segmenter, args.workers)
    elif args.cmd == "agent":
        run_agent()
    else:
        text = report()
        REPORT.write_text(text, encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
