"""Command-line interface for downloading data, checking it, and running Darubini."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from darubini.config import get_settings
from darubini.segmentation.base import SEGMENTERS
from darubini.types import ObjectClass

if TYPE_CHECKING:
    from darubini.counting import SlideCount


def _cmd_datasets(args: argparse.Namespace) -> int:
    from darubini.data.registry import load_manifest

    manifest = load_manifest(args.manifest)
    for d in manifest.datasets:
        size = f"{d.size_bytes / 1e9:.2f} GB" if d.size_bytes else "?"
        print(f"{d.id:22} {d.tier:9} {d.kind:7} {size:>9}  {d.country:11} {d.title}")
    return 0


def _cmd_download(args: argparse.Namespace) -> int:
    from darubini.data.download import DownloadError, LicenceNotAcceptedError, check_space, download
    from darubini.data.registry import load_manifest

    manifest = load_manifest(args.manifest)
    specs = [manifest.get(i) for i in args.only] if args.only else manifest.up_to_tier(args.tier)
    if not args.skip_space_check:
        try:
            check_space(specs, args.raw_dir)
        except DownloadError as exc:
            print(f"error: {exc}. Free up space or pass --skip-space-check.")
            return 2
    done: list[str] = []
    manual: list[str] = []
    licence: list[str] = []
    failed: list[str] = []
    for spec in specs:
        try:
            result = download(
                spec,
                args.raw_dir,
                keep_archive=args.keep_archives,
                accept_licences=args.accept_licences,
            )
        except LicenceNotAcceptedError as exc:
            licence.append(spec.id)
            print(f"skipped: {exc}")
            continue
        except DownloadError as exc:
            failed.append(spec.id)
            print(f"failed: {exc}")
            continue
        (done if result is not None else manual).append(spec.id)
    print("\nSummary")
    for label, ids in (
        ("ready", done),
        ("manual step needed", manual),
        ("licence not accepted", licence),
        ("failed", failed),
    ):
        if ids:
            print(f"  {label:22} {', '.join(ids)}")
    print("Run `darubini verify` to see every dataset's status; details in datasets/README.md.")
    return 1 if failed else 0


def _cmd_links(args: argparse.Namespace) -> int:
    from darubini.data.download import check_link
    from darubini.data.registry import load_manifest

    broken = 0
    for spec in load_manifest(args.manifest).datasets:
        ok, detail = check_link(spec)
        broken += not ok
        print(f"{'ok ' if ok else 'BAD'} {spec.id:22} {detail}")
    return 1 if broken else 0


def _cmd_splits(args: argparse.Namespace) -> int:
    from darubini.data.fields import (
        held_out_split,
        nlm_thick_fields,
        patient_split,
        split_table,
        udom_fields,
    )

    def table(dataset: str, root: Path) -> list[tuple[str, str, int]]:
        if dataset.startswith("udom"):
            return split_table(udom_fields(root), held_out_split)
        return split_table(nlm_thick_fields(root), patient_split)

    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    for dataset in ("nih-thick-pf-150", "udom-tz-thick"):
        root = args.raw_dir / dataset
        if not root.is_dir():
            print(f"skip {dataset}: {root} not found")
            continue
        rows = table(dataset, root)
        lines = ["group,split,fields", *(f"{g},{s},{n}" for g, s, n in rows)]
        (args.out / f"{dataset}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        totals: dict[str, tuple[int, int]] = {}
        for _, s, n in rows:
            groups, fields = totals.get(s, (0, 0))
            totals[s] = (groups + 1, fields + n)
        summary = ", ".join(f"{s} {g} groups / {f} fields" for s, (g, f) in sorted(totals.items()))
        print(f"{dataset}: {summary}")
        written += 1
    return 0 if written else 2


def _cmd_profile(args: argparse.Namespace) -> int:
    from darubini.data.profile import profile, render
    from darubini.data.registry import load_manifest

    profiles = [
        profile(spec.id, args.raw_dir / spec.id)
        for spec in load_manifest(args.manifest).datasets
        if (args.raw_dir / spec.id).is_dir()
    ]
    text = render(profiles)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    for p in profiles:
        print(
            f"{p.dataset_id:22} {p.files:>7,} files  {p.images:>7,} images  {p.annotation_format}"
        )
    print(f"\nFull profile written to {args.out}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from darubini.data.download import status
    from darubini.data.registry import load_manifest

    manifest = load_manifest(args.manifest)
    missing_core = False
    print(f"{'dataset':22} {'tier':9} {'status':8} {'files':>7}")
    for spec in manifest.datasets:
        state, n = status(spec, args.raw_dir)
        print(f"{spec.id:22} {spec.tier:9} {state:8} {n:>7}")
        if spec.tier == "core" and state != "ready":
            missing_core = True
    if missing_core:
        print("\nCore datasets are not all ready: run `darubini download --tier core`.")
    return 1 if missing_core else 0


def _cmd_calibrate(args: argparse.Namespace) -> int:
    from dataclasses import replace

    from darubini.calibration import render, suggest_min_sharpness, survey
    from darubini.data.registry import load_manifest
    from darubini.quality import QualityThresholds

    thresholds = QualityThresholds()
    if args.min_sharpness is not None:
        thresholds = replace(thresholds, min_sharpness=args.min_sharpness)
    surveys = []
    for spec in load_manifest(args.manifest).datasets:
        root = args.raw_dir / spec.id
        if not spec.smear or "thick" not in spec.smear or not root.is_dir():
            continue
        if args.only and spec.id not in args.only:
            continue
        s = survey(spec.id, root, args.sample, thresholds, seed=args.seed)
        if s.n:
            surveys.append(s)
            print(f"{spec.id:22} {s.n:>5} fields  blocked {s.reject_rate():6.1%}")
    if not surveys:
        print("error: no thick-film datasets found; run `darubini download --tier core`.")
        return 2
    suggested = suggest_min_sharpness(surveys, args.max_reject)
    limit = f"<= {args.max_reject:.0%} blocked per dataset"
    print(f"\nSuggested min_sharpness ({limit}): {suggested:g}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(surveys, thresholds), encoding="utf-8")
    print(f"Report written to {args.out}")
    return 0


def _cmd_sweep(args: argparse.Namespace) -> int:
    import random

    from darubini.data.fields import nlm_thick_fields
    from darubini.meta.client import MetaApiError, MetaModelClient
    from darubini.sweep import (
        USD_PER_REQUEST,
        Variant,
        matcher_for,
        render,
        requests_for,
        run_sweep,
        score_run,
    )
    from darubini.types import ObjectClass

    root = args.raw_dir / args.dataset
    fields = nlm_thick_fields(root, split=args.split) if root.is_dir() else []
    if not fields:
        print(f"error: no labelled fields for {args.dataset} ({args.split} split)")
        return 2
    rng = random.Random(args.seed)  # noqa: S311  # nosec B311
    fields = rng.sample(fields, min(args.fields, len(fields)))
    tiles = [None if t == "full" else int(t) for t in args.tiles]
    variants = [
        Variant(c, cls, t)
        for prompts, cls in (
            (args.parasite_prompts, ObjectClass.PARASITE),
            (args.wbc_prompts, ObjectClass.WBC),
        )
        for c in prompts
        for t in tiles
    ]
    wbc_filter = Variant(args.exclude_in_wbc, ObjectClass.WBC) if args.exclude_in_wbc else None
    upper = requests_for(fields, variants, args.tile_overlap) + (len(fields) if wbc_filter else 0)
    cost = upper * USD_PER_REQUEST
    print(
        f"{len(fields)} fields x {len(variants)} variants: up to {upper} SAM requests "
        f"(US${cost:.2f} before cache hits)"
    )
    if cost > args.max_cost:
        print(f"error: above --max-cost {args.max_cost:.2f}; use fewer fields or variants")
        return 2
    settings = get_settings()
    try:
        client = MetaModelClient.from_settings(settings)
    except MetaApiError as exc:
        print(f"error: {exc}")
        return 2
    try:
        runs = run_sweep(
            fields,
            variants,
            client,
            settings.meta_segmentation_model,
            tile_overlap=args.tile_overlap,
            workers=args.workers,
            wbc_filter=wbc_filter,
        )
    finally:
        client.close()
    scores = [score_run(r, matcher_for(args.centres)) for r in runs]
    text = render(scores, args.dataset, args.split, len(fields), client.billed_requests, wbc_filter)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Report written to {args.out}; {client.billed_requests} requests sent.")
    return 0


def _cmd_train_verifier(args: argparse.Namespace) -> int:
    import random

    from darubini.benchmark import compare_on_fields, render_comparison
    from darubini.data.fields import LabelledField, nlm_thick_fields, udom_fields
    from darubini.segmentation.base import Segmenter
    from darubini.segmentation.baseline import BaselineSegmenter
    from darubini.segmentation.candidates import CandidateDetector
    from darubini.types import ObjectClass
    from darubini.verifier import (
        ParasiteVerifier,
        VerifiedSegmenter,
        build_training_set,
    )

    root = args.raw_dir / args.dataset
    if not root.is_dir():
        print(f"error: {root} not found")
        return 2
    rng = random.Random(args.seed)  # noqa: S311  # nosec B311

    def by_patient(fields: list[LabelledField], n: int) -> tuple[list[LabelledField], ...]:
        """Hold out 15% of patients for early stopping and the threshold; sample both."""
        patients = sorted({f.patient for f in fields})
        rng.shuffle(patients)
        held = set(patients[: max(1, len(patients) * 15 // 100)])
        train = [f for f in fields if f.patient not in held]
        valid = [f for f in fields if f.patient in held]
        train = rng.sample(train, min(n, len(train)))
        return train, rng.sample(valid, min(max(1, n // 5), len(valid)))

    train_fields, valid_fields = by_patient(nlm_thick_fields(root, split="tune"), args.fields)
    if not train_fields:
        print("error: no labelled tuning fields")
        return 2
    adapt_root = args.raw_dir / args.adapt_dataset if args.adapt_dataset else None
    adapt = udom_fields(adapt_root, split="adapt") if adapt_root and adapt_root.is_dir() else []
    adapt_train, adapt_valid = by_patient(adapt, len(adapt)) if adapt else ([], [])

    candidates = CandidateDetector()
    print(
        f"Building features: {len(train_fields)} + {len(adapt_train)} train, "
        f"{len(valid_fields)} + {len(adapt_valid)} valid fields"
    )
    train = build_training_set(train_fields, candidates)
    valid = build_training_set(valid_fields, candidates)
    if adapt:
        train = train + build_training_set(adapt_train, candidates).repeat(args.adapt_weight)
        valid = valid + build_training_set(adapt_valid, candidates).repeat(args.adapt_weight)
    print(
        f"{len(train.y)} train candidates ({train.y.mean():.1%} parasites), "
        f"{len(valid.y)} valid candidates"
    )
    model = ParasiteVerifier.fit(train, valid, seed=args.seed)
    model.save(args.out)
    print(f"Saved {args.out} (threshold {model.threshold:.2f})")

    segmenters: dict[str, Segmenter] = {
        "Stain blobs (old candidates)": BaselineSegmenter(),
        "Absorption candidates": candidates,
        "Candidates + verifier": VerifiedSegmenter(candidates, model, wbc=BaselineSegmenter()),
    }
    sets = [(f"`{args.dataset}`, val split", nlm_thick_fields(root, split="val"))]
    if adapt_root is not None and adapt:
        sets.append((f"`{args.adapt_dataset}`, dev check half", udom_fields(adapt_root, "check")))
    adapted = (
        f" plus {len(adapt_train)} tiles from the `adapt` half of the "
        f"`{args.adapt_dataset}` dev slice (weighted x{args.adapt_weight})"
        if adapt
        else ""
    )
    parts = [
        "# Parasite verifier\n\n"
        f"Generated by `darubini train-verifier`: trained on {len(train_fields)} tuning-split "
        f"fields of `{args.dataset}`{adapted}, using absorption candidates. Threshold "
        f"{model.threshold:.2f} chosen on held-out tuning patients and photos. Matching is by "
        "centres (`evaluation.match_centres`)."
    ]
    for title, fields in sets:
        fields = rng.sample(fields, min(args.eval_fields, len(fields)))
        scores = compare_on_fields(fields, segmenters, classes=(ObjectClass.PARASITE,))
        parts.append(render_comparison(scores, f"\n# {title}: {len(fields)} fields"))
    text = "\n".join(parts)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0


def _sam_requests_per_field(name: str, image: Path) -> int:
    """SAM requests one field costs with a segmenter (before cache hits)."""
    from PIL import Image

    from darubini.segmentation.sam import TUNED_TILE_SIZE, tile_grid

    if name == "hybrid":
        return 1
    if name == "sam3":
        with Image.open(image) as im:
            w, h = im.size
        return len(tile_grid(w, h, TUNED_TILE_SIZE, 128)) + 1
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    import random

    from darubini.benchmark import compare_on_fields, render_comparison
    from darubini.data.fields import nlm_thick_fields, udom_fields
    from darubini.meta.client import MetaApiError
    from darubini.segmentation.base import get_segmenter
    from darubini.sweep import USD_PER_REQUEST

    if args.split == "test" and not args.final_test:
        print("error: the test split is scored once, at the end; pass --final-test to confirm")
        return 2
    root = args.raw_dir / args.dataset
    if not root.is_dir():
        print(f"error: {root} not found")
        return 2
    if args.dataset.startswith("udom"):
        if args.split == "val":
            print("error: UDOM splits are 'check', 'adapt', 'dev' and 'test'")
            return 2
        fields = udom_fields(root, split=args.split)
    else:
        if args.split not in ("val", "test"):
            print("error: NLM splits are 'val' and 'test'")
            return 2
        fields = nlm_thick_fields(root, split=args.split)
    if not fields:
        print(f"error: no labelled fields for {args.dataset} ({args.split} split)")
        return 2
    rng = random.Random(args.seed)  # noqa: S311  # nosec B311
    if args.fields:
        fields = rng.sample(fields, min(args.fields, len(fields)))

    requests = sum(_sam_requests_per_field(n, f.image) for n in args.segmenters for f in fields)
    cost = requests * USD_PER_REQUEST
    print(
        f"{len(fields)} fields, {', '.join(args.segmenters)}: up to {requests} SAM requests "
        f"(US${cost:.2f} before cache hits)"
    )
    if cost > args.max_cost:
        print(f"error: above --max-cost {args.max_cost:.2f}; use --fields to sample fewer")
        return 2
    settings = get_settings()
    try:
        segmenters = {
            n: get_segmenter(settings.model_copy(update={"segmenter": n})) for n in args.segmenters
        }
    except (MetaApiError, FileNotFoundError) as exc:
        print(f"error: {exc}")
        return 2
    scores = compare_on_fields(fields, segmenters)
    header = (
        f"# Evaluation: {args.dataset}, {args.split} split\n\n"
        f"Generated by `darubini evaluate` on {len(fields)} fields from "
        f"{len({f.patient for f in fields})} patients or photos. Matching is by centres "
        "(`evaluation.match_centres`); count errors are per field."
    )
    text = render_comparison(scores, header)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Report written to {args.out}")
    return 0


def _cmd_analyse(args: argparse.Namespace) -> int:
    from darubini.pipeline import Pipeline, load_image
    from darubini.segmentation.base import get_segmenter

    pipeline = Pipeline(segmenter=get_segmenter(get_settings()))
    images = ((p.name, load_image(p)) for p in args.images)
    fields, count, report = pipeline.analyse_slide(images, language=args.language)
    narrative = _narrate(count, report.facts, args.language, args.narrate)
    if args.json:
        out = {"slide": report.facts, "fields": len(fields), "narrative": narrative}
        print(json.dumps(out, indent=2))
    else:
        print(report.text)
        if narrative:
            print()
            print(narrative)
    return 0


def _narrate(count: SlideCount, facts: dict[str, Any], language: str, source: str) -> str | None:
    """Draft a narrative with Muse Spark or Muse Spark Open, or None.

    The narrative is dropped when it quotes a number the count did not produce.
    """
    from darubini.agent import _numbers_in, unsupported_numbers
    from darubini.meta.client import MetaApiError, MetaModelClient
    from darubini.meta.reviewer import MuseReviewer

    if source == "none":
        return None
    s = get_settings()
    try:
        if source == "open":
            if not s.open_weights_enabled:
                print("note: set OPEN_WEIGHTS_BASE_URL to draft with Muse Spark Open")
                return None
            key = s.open_weights_api_key.get_secret_value() if s.open_weights_api_key else "none"
            client = MetaModelClient(str(s.open_weights_base_url), key, timeout_s=180.0)
            model = s.open_weights_model
        else:
            client, model = MetaModelClient.from_settings(s), s.meta_reasoning_model
        text = MuseReviewer(client, model).draft_report(count, language)
    except MetaApiError as exc:
        print(f"note: narrative skipped ({exc})")
        return None
    bad = unsupported_numbers(text, _numbers_in(facts))
    if bad:
        print(f"note: narrative dropped; it quoted numbers the count did not produce: {bad}")
        return None
    return text.strip()


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")


def _expand_images(paths: Sequence[Path]) -> list[Path]:
    """Files as given; directories become their images, sorted by name (capture order)."""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(q for q in p.iterdir() if q.suffix.lower() in IMAGE_SUFFIXES))
        else:
            out.append(p)
    return out


def _cmd_agent(args: argparse.Namespace) -> int:
    from functools import partial

    from darubini.agent import CountingAgent, SlideSession
    from darubini.audit import MuseAuditor
    from darubini.meta.client import MetaApiError, MetaModelClient
    from darubini.meta.reviewer import MuseReviewer
    from darubini.pipeline import Pipeline, load_image
    from darubini.segmentation.base import get_segmenter

    images = _expand_images(args.images)
    if not images:
        print("error: no field images found")
        return 2
    settings = get_settings()
    if args.segmenter:
        settings = settings.model_copy(update={"segmenter": args.segmenter})
    try:
        client = MetaModelClient.from_settings(settings)
        segmenter = get_segmenter(settings)
    except (MetaApiError, FileNotFoundError) as exc:
        print(f"error: {exc}")
        return 2
    reviewer = None if args.no_review else MuseReviewer(client, settings.meta_reasoning_model)
    session = SlideSession(
        Pipeline(segmenter=segmenter),
        [(p.name, partial(load_image, p)) for p in images],
        reviewer=reviewer,
        auditor=None if args.no_audit else MuseAuditor(client, settings.meta_reasoning_model),
    )
    agent = CountingAgent(client, settings.meta_reasoning_model, max_turns=args.max_turns)
    result = agent.run(session, language=args.language)
    for step in result.steps:
        summary = {k: v for k, v in step.result.items() if k != "examined"}
        print(f"> {step.tool}({json.dumps(step.arguments, ensure_ascii=False)[:160]})")
        print(f"  {json.dumps(summary, ensure_ascii=False)[:240]}")
    print()
    print(result.text)
    for note in result.notes:
        print(f"note: {note}")
    print(f"finished by agent: {result.finished_by_agent}; tool calls: {len(result.steps)}")
    if args.transcript:
        args.transcript.parent.mkdir(parents=True, exist_ok=True)
        args.transcript.write_text(
            json.dumps(
                {
                    "steps": [vars(s) for s in result.steps],
                    "report": result.report.facts,
                    "narrative": result.narrative,
                    "excluded": result.excluded,
                    "audit": result.audit.facts() if result.audit else None,
                    "finished_by_agent": result.finished_by_agent,
                    "notes": result.notes,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Transcript written to {args.transcript}")
    return 0


def _cmd_track(args: argparse.Namespace) -> int:
    from darubini import video
    from darubini.meta.client import MetaApiError, MetaModelClient
    from darubini.pipeline import load_image
    from darubini.segmentation.base import get_segmenter
    from darubini.tracking import (
        SAM_MIN_BILLED_FRAMES,
        SamTracker,
        ShiftTracker,
        Tracker,
        count_clip,
        keyframe_indices,
        sam_cost_usd,
    )

    if args.synthetic:
        frames = video.synthetic_pan(load_image(args.source), frames=args.max_frames, eyepiece=True)
    else:
        frames = video.decode(args.source, max_frames=args.max_frames, max_side=args.max_side)
    if args.save_clip:
        args.save_clip.write_bytes(video.encode(frames))
        print(f"Clip written to {args.save_clip}")
    settings = get_settings()
    if args.segmenter:
        settings = settings.model_copy(update={"segmenter": args.segmenter})
    keys = keyframe_indices(len(frames), args.keyframe_every)
    tracker: Tracker
    try:
        segmenter = get_segmenter(settings)
        if args.tracker == "sam":
            # One request per keyframe with new objects, assuming at most 16 new ones.
            frames_billed = sum(max(len(frames) - k, SAM_MIN_BILLED_FRAMES) for k in keys[:-1])
            estimate = sam_cost_usd(frames_billed)
            print(
                f"{len(frames)} frames, {len(keys)} keyframes: about US${estimate:.2f} of SAM video"
            )
            if estimate > args.max_cost:
                print(f"error: above --max-cost {args.max_cost:.2f}")
                return 2
            tracker = SamTracker(
                MetaModelClient.from_settings(settings), settings.meta_segmentation_model
            )
        else:
            tracker = ShiftTracker()
        clip = count_clip(frames, segmenter, tracker, keyframe_every=args.keyframe_every)
    except (MetaApiError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    facts = {
        "frames": clip.frames,
        "keyframes": len(clip.keyframes),
        "tracker": tracker.name,
        "unique_parasites": clip.parasites,
        "unique_wbcs": clip.wbcs,
        "naive_parasites": clip.naive.get(ObjectClass.PARASITE, 0),
        "naive_wbcs": clip.naive.get(ObjectClass.WBC, 0),
    }
    if isinstance(tracker, SamTracker):
        facts["sam_frames_billed"] = tracker.frames_sent
        facts["sam_usd"] = round(sam_cost_usd(tracker.frames_sent), 3)
    print(json.dumps(facts, indent=2))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("darubini.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    p = argparse.ArgumentParser(prog="darubini", description="Malaria microscopy copilot")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    manifest_default = Path("datasets/manifest.yaml")

    ds = sub.add_parser("datasets", help="list known datasets")
    ds.add_argument("--manifest", type=Path, default=manifest_default)
    ds.set_defaults(func=_cmd_datasets)

    dl = sub.add_parser("download", help="download datasets into datasets/raw/")
    dl.add_argument("--manifest", type=Path, default=manifest_default)
    dl.add_argument("--tier", choices=["core", "extended", "large"], default="core")
    dl.add_argument("--only", nargs="+", metavar="ID", help="download only these dataset ids")
    dl.add_argument("--raw-dir", type=Path, default=Path("datasets/raw"))
    dl.add_argument("--keep-archives", action="store_true")
    dl.add_argument(
        "--accept-licences",
        action="store_true",
        help="confirm you have read and accepted licences for datasets that require it",
    )
    dl.add_argument("--skip-space-check", action="store_true")
    dl.set_defaults(func=_cmd_download)

    vf = sub.add_parser("verify", help="show which datasets are ready")
    vf.add_argument("--manifest", type=Path, default=manifest_default)
    vf.add_argument("--raw-dir", type=Path, default=Path("datasets/raw"))
    vf.set_defaults(func=_cmd_verify)

    pf = sub.add_parser("profile", help="summarise what each downloaded dataset contains")
    pf.add_argument("--manifest", type=Path, default=manifest_default)
    pf.add_argument("--raw-dir", type=Path, default=Path("datasets/raw"))
    pf.add_argument("--out", type=Path, default=Path("datasets/PROFILE.md"))
    pf.set_defaults(func=_cmd_profile)

    sp = sub.add_parser("splits", help="write the frozen train/test split lists")
    sp.add_argument("--raw-dir", type=Path, default=Path("datasets/raw"))
    sp.add_argument("--out", type=Path, default=Path("docs/splits"))
    sp.set_defaults(func=_cmd_splits)

    lk = sub.add_parser("links", help="check every dataset source is still reachable")
    lk.add_argument("--manifest", type=Path, default=manifest_default)
    lk.set_defaults(func=_cmd_links)

    cb = sub.add_parser("calibrate", help="measure the quality gate on real thick-film fields")
    cb.add_argument("--manifest", type=Path, default=manifest_default)
    cb.add_argument("--raw-dir", type=Path, default=Path("datasets/raw"))
    cb.add_argument("--only", nargs="+", metavar="ID", help="survey only these dataset ids")
    cb.add_argument("--sample", type=int, default=300, help="fields per dataset")
    cb.add_argument("--seed", type=int, default=0)
    cb.add_argument("--max-reject", type=float, default=0.01)
    cb.add_argument("--min-sharpness", type=float, help="threshold to evaluate (default: current)")
    cb.add_argument("--out", type=Path, default=Path("docs/calibration/quality.md"))
    cb.set_defaults(func=_cmd_calibrate)

    sw = sub.add_parser("sweep", help="score SAM 3 prompts and tile sizes on labelled fields")
    sw.add_argument("--dataset", default="nih-thick-pf-150", help="an NLM thick-smear dataset")
    sw.add_argument("--raw-dir", type=Path, default=Path("datasets/raw"))
    sw.add_argument("--split", choices=["tune", "val"], default="tune")
    sw.add_argument("--fields", type=int, default=10)
    sw.add_argument("--seed", type=int, default=0)
    sw.add_argument("--parasite-prompts", nargs="*", default=["malaria parasite"])
    sw.add_argument("--wbc-prompts", nargs="*", default=["white blood cell nucleus"])
    sw.add_argument(
        "--tiles", nargs="+", default=["full"], help="tile sizes in px, or 'full' for none"
    )
    sw.add_argument("--tile-overlap", type=int, default=128)
    sw.add_argument(
        "--exclude-in-wbc",
        metavar="PROMPT",
        help="drop parasites inside WBCs found by this whole-field prompt (e.g. 'cell')",
    )
    sw.add_argument("--workers", type=int, default=4)
    sw.add_argument(
        "--centres",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="match by box centres (NLM labels); --no-centres uses IoU >= 0.3",
    )
    sw.add_argument("--max-cost", type=float, default=5.0, help="refuse sweeps above this US$")
    sw.add_argument("--out", type=Path, default=Path("docs/calibration/sam_sweep.md"))
    sw.set_defaults(func=_cmd_sweep)

    tv = sub.add_parser("train-verifier", help="train the parasite verifier on NLM tuning fields")
    tv.add_argument("--dataset", default="nih-thick-pf-150")
    tv.add_argument("--raw-dir", type=Path, default=Path("datasets/raw"))
    tv.add_argument("--fields", type=int, default=300, help="training fields")
    tv.add_argument("--eval-fields", type=int, default=60, help="val-split fields to score")
    tv.add_argument("--seed", type=int, default=0)
    tv.add_argument(
        "--adapt-dataset",
        default="udom-tz-thick",
        help="also train on the 'adapt' half of this held-out dataset's dev slice ('' to skip)",
    )
    tv.add_argument("--adapt-weight", type=int, default=3, help="repeat adapt rows this often")
    tv.add_argument("--out", type=Path, default=Path("models/parasite_verifier.npz"))
    tv.add_argument("--report", type=Path, default=Path("docs/calibration/verifier.md"))
    tv.set_defaults(func=_cmd_train_verifier)

    ev = sub.add_parser("evaluate", help="score segmenters against labels on a held-out split")
    ev.add_argument("--dataset", default="udom-tz-thick")
    ev.add_argument("--raw-dir", type=Path, default=Path("datasets/raw"))
    ev.add_argument(
        "--split",
        choices=["val", "dev", "adapt", "check", "test"],
        default="check",
        help="NLM: val/test. UDOM: check (dev half the verifier never trains on), adapt, dev, test",
    )
    ev.add_argument("--segmenters", nargs="+", choices=SEGMENTERS, default=["baseline", "verified"])
    ev.add_argument("--fields", type=int, default=0, help="sample this many fields (0: all)")
    ev.add_argument("--seed", type=int, default=0)
    ev.add_argument("--max-cost", type=float, default=5.0, help="refuse runs above this US$")
    ev.add_argument("--final-test", action="store_true", help="allow scoring the test split")
    ev.add_argument("--out", type=Path, default=Path("docs/calibration/evaluation_dev.md"))
    ev.set_defaults(func=_cmd_evaluate)

    an = sub.add_parser("analyse", help="analyse field images of one slide")
    an.add_argument("images", nargs="+", type=Path)
    an.add_argument("--language", choices=["en", "sw"], default="en")
    an.add_argument("--json", action="store_true")
    an.add_argument(
        "--narrate",
        choices=["none", "muse", "open"],
        default="none",
        help="draft a narrative with Muse Spark (API) or Muse Spark Open (OPEN_WEIGHTS_BASE_URL)",
    )
    an.set_defaults(func=_cmd_analyse)

    ag = sub.add_parser("agent", help="count a slide with the Muse Spark agent")
    ag.add_argument("images", nargs="+", type=Path, help="field images or folders, in order")
    ag.add_argument("--language", choices=["en", "sw"], default="en")
    ag.add_argument("--segmenter", choices=SEGMENTERS, help="override DARUBINI_SEGMENTER")
    ag.add_argument("--no-review", action="store_true", help="no Muse Spark quality reviews")
    ag.add_argument("--no-audit", action="store_true", help="no Muse Spark parasite audit")
    ag.add_argument("--max-turns", type=int, default=40)
    ag.add_argument("--transcript", type=Path, help="write the tool-call trail as JSON")
    ag.set_defaults(func=_cmd_agent)

    tr = sub.add_parser("track", help="count each object once across a panning video")
    tr.add_argument("source", type=Path, help="a video, or an image with --synthetic")
    tr.add_argument("--synthetic", action="store_true", help="pan across a still field image")
    tr.add_argument("--tracker", choices=["sam", "shift"], default="sam")
    tr.add_argument("--segmenter", choices=SEGMENTERS, help="override DARUBINI_SEGMENTER")
    tr.add_argument("--keyframe-every", type=int, default=10)
    tr.add_argument("--max-frames", type=int, default=60)
    tr.add_argument("--max-side", type=int, default=1280)
    tr.add_argument("--max-cost", type=float, default=0.5)
    tr.add_argument("--save-clip", type=Path, help="also write the frames as MP4")
    tr.set_defaults(func=_cmd_track)

    sv = sub.add_parser("serve", help="run the HTTP API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(func=_cmd_serve)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``darubini`` command."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request otherwise
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    sys.exit(main())
