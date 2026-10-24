"""Command-line interface for downloading data, checking it, and running Darubini."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from darubini.config import get_settings


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


def _cmd_analyse(args: argparse.Namespace) -> int:
    from darubini.pipeline import Pipeline, load_image
    from darubini.segmentation.base import get_segmenter

    pipeline = Pipeline(segmenter=get_segmenter(get_settings()))
    images = ((p.name, load_image(p)) for p in args.images)
    fields, _count, report = pipeline.analyse_slide(images, language=args.language)
    if args.json:
        print(json.dumps({"slide": report.facts, "fields": len(fields)}, indent=2))
    else:
        print(report.text)
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

    lk = sub.add_parser("links", help="check every dataset source is still reachable")
    lk.add_argument("--manifest", type=Path, default=manifest_default)
    lk.set_defaults(func=_cmd_links)

    an = sub.add_parser("analyse", help="analyse field images of one slide")
    an.add_argument("images", nargs="+", type=Path)
    an.add_argument("--language", choices=["en", "sw"], default="en")
    an.add_argument("--json", action="store_true")
    an.set_defaults(func=_cmd_analyse)

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
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    sys.exit(main())
