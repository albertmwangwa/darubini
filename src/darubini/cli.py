"""Command-line interface: ``darubini download | datasets | analyse | serve``."""

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
    from darubini.data.download import download
    from darubini.data.registry import load_manifest

    manifest = load_manifest(args.manifest)
    specs = [manifest.get(i) for i in args.only] if args.only else manifest.up_to_tier(args.tier)
    manual: list[str] = []
    for spec in specs:
        if download(spec, args.raw_dir, keep_archive=args.keep_archives) is None:
            manual.append(spec.id)
    if manual:
        print(f"\nManual steps still needed for: {', '.join(manual)} (see datasets/README.md)")
    return 0


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
    dl.set_defaults(func=_cmd_download)

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
