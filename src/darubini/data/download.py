"""Resumable, checksum-verified dataset downloads.

Supported sources (``kind`` in the manifest):

- ``http``: one archive from a direct URL, resumable, MD5-checked when published.
- ``zenodo``: every file in a Zenodo record, each checked against Zenodo's MD5.
- ``git``: a shallow clone.
- ``kaggle``: a Kaggle dataset through the official ``kaggle`` CLI (needs an API token).
- ``manual``: printed instructions only.

Datasets whose licence must be accepted first are skipped unless the caller
passes ``accept_licences=True`` after the user has read and accepted it.
"""

from __future__ import annotations

import hashlib
import logging
import shutil

# subprocess runs only fixed `git clone` and `kaggle datasets download` commands.
import subprocess  # nosec B404
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
from tqdm import tqdm

from darubini.data.registry import DatasetSpec

log = logging.getLogger(__name__)
CHUNK = 1 << 20
ZENODO_API = "https://zenodo.org/api/records/{record}"
#: Archive plus extracted copy need roughly twice the archive size on disk.
SPACE_FACTOR = 2.1


class DownloadError(RuntimeError):
    """A download failed verification or could not complete."""


class LicenceNotAcceptedError(DownloadError):
    """The dataset's licence must be accepted before downloading."""


def md5sum(path: Path) -> str:
    """MD5 of a file, used only to match the checksum published by the data provider."""
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _client(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0)), True


def fetch_http(url: str, dest: Path, client: httpx.Client | None = None) -> Path:
    """Stream ``url`` to ``dest``, resuming a partial ``.part`` file if one exists."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    http, own = _client(client)
    try:
        with http.stream("GET", url, headers=headers) as r:
            if r.status_code == 416:  # already complete
                part.rename(dest)
                return dest
            r.raise_for_status()
            if offset and r.status_code != 206:
                offset = 0  # server ignored Range: restart
            total = int(r.headers.get("content-length", 0)) + offset
            mode = "ab" if offset else "wb"
            with (
                part.open(mode) as fh,
                tqdm(
                    total=total or None, initial=offset, unit="B", unit_scale=True, desc=dest.name
                ) as bar,
            ):
                for chunk in r.iter_bytes(CHUNK):
                    fh.write(chunk)
                    bar.update(len(chunk))
    except httpx.HTTPError as exc:
        raise DownloadError(f"download failed for {url}: {exc}") from exc
    finally:
        if own:
            http.close()
    part.rename(dest)
    return dest


def extract(archive: Path, target: Path) -> None:
    """Extract a zip archive, refusing entries that would escape ``target``."""
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            out = (target / member.filename).resolve()
            if not out.is_relative_to(root):
                raise DownloadError(f"unsafe path in archive: {member.filename}")
        zf.extractall(target)  # every member path validated above


@dataclass(frozen=True)
class RemoteFile:
    """One file listed by a Zenodo record."""

    name: str
    url: str
    size: int
    md5: str | None


def zenodo_files(record: str, client: httpx.Client | None = None) -> list[RemoteFile]:
    """List the files of a Zenodo record through its public API."""
    http, own = _client(client)
    try:
        r = http.get(ZENODO_API.format(record=record))
        r.raise_for_status()
        data: dict[str, Any] = r.json()
    except httpx.HTTPError as exc:
        raise DownloadError(f"could not list Zenodo record {record}: {exc}") from exc
    finally:
        if own:
            http.close()
    try:
        out = []
        for f in data["files"]:
            checksum = str(f.get("checksum", ""))
            out.append(
                RemoteFile(
                    name=str(f["key"]),
                    url=str(f["links"]["self"]),
                    size=int(f.get("size", 0)),
                    md5=checksum.split(":", 1)[1] if checksum.startswith("md5:") else None,
                )
            )
        return out
    except (KeyError, TypeError, ValueError) as exc:
        raise DownloadError(f"unexpected Zenodo response for {record}: {exc}") from exc


def _finish_archive(archive: Path, target: Path, md5: str | None, keep: bool, label: str) -> None:
    if md5:
        actual = md5sum(archive)
        if actual != md5:
            raise DownloadError(f"{label}: checksum mismatch (expected {md5}, got {actual})")
    if zipfile.is_zipfile(archive):
        extract(archive, target)
        if not keep:
            archive.unlink()
    else:
        target.mkdir(parents=True, exist_ok=True)
        shutil.move(str(archive), target / archive.name)


def _run(argv: list[str]) -> None:
    # Fixed argv with an absolute executable path; arguments come from the reviewed manifest.
    subprocess.run(argv, check=True)  # noqa: S603  # nosec B603


def download(
    spec: DatasetSpec,
    raw_dir: Path,
    keep_archive: bool = False,
    accept_licences: bool = False,
    client: httpx.Client | None = None,
) -> Path | None:
    """Fetch one dataset into ``raw_dir/<id>``. Returns the folder, or None if skipped."""
    target = raw_dir / spec.id
    marker = target / ".complete"
    if marker.exists():
        log.info("%s already downloaded", spec.id)
        return target

    if spec.kind == "manual":
        log.warning("%s needs a manual step:\n  %s", spec.id, spec.instructions)
        return None

    if spec.requires_licence_acceptance and not accept_licences:
        raise LicenceNotAcceptedError(
            f"{spec.id}: read and accept the licence at {spec.page}, "
            "then rerun with --accept-licences"
        )

    if spec.kind == "git":
        git = shutil.which("git")
        if git is None:
            raise DownloadError("git is not installed")
        if target.exists():
            shutil.rmtree(target)
        _run([git, "clone", "--depth", "1", str(spec.url), str(target)])

    elif spec.kind == "kaggle":
        kaggle = shutil.which("kaggle")
        if kaggle is None:
            raise DownloadError(
                f"{spec.id}: install the Kaggle CLI (pip install kaggle) and place your API "
                "token in ~/.kaggle/kaggle.json, or download it by hand: " + str(spec.instructions)
            )
        target.mkdir(parents=True, exist_ok=True)
        _run(
            [
                kaggle,
                "datasets",
                "download",
                "-d",
                str(spec.kaggle_slug),
                "-p",
                str(target),
                "--unzip",
            ]
        )

    elif spec.kind == "zenodo":
        files = zenodo_files(str(spec.zenodo_record), client)
        for f in files:
            dest = raw_dir / "_archives" / spec.id / f.name
            if not dest.exists():
                fetch_http(f.url, dest, client)
            _finish_archive(dest, target, f.md5, keep_archive, f"{spec.id}/{f.name}")

    else:  # http
        if spec.url is None or spec.filename is None:  # the schema already enforces this
            raise DownloadError(f"{spec.id}: http dataset needs url and filename")
        archive = raw_dir / "_archives" / spec.filename
        if not archive.exists():
            fetch_http(spec.url, archive, client)
        _finish_archive(archive, target, spec.md5, keep_archive, spec.id)

    target.mkdir(parents=True, exist_ok=True)
    marker.touch()
    return target


def space_needed(specs: list[DatasetSpec], raw_dir: Path) -> int:
    """Bytes of free space needed for the datasets not yet downloaded."""
    return int(
        sum(
            (s.size_bytes or 0) * SPACE_FACTOR
            for s in specs
            if s.kind != "manual" and not (raw_dir / s.id / ".complete").exists()
        )
    )


def check_space(specs: list[DatasetSpec], raw_dir: Path) -> None:
    """Raise if the disk holding ``raw_dir`` lacks room for these downloads."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    need = space_needed(specs, raw_dir)
    free = shutil.disk_usage(raw_dir).free
    if need > free:
        raise DownloadError(
            f"not enough disk space: need about {need / 1e9:.1f} GB, "
            f"{free / 1e9:.1f} GB free at {raw_dir}"
        )


Status = Literal["ready", "partial", "missing", "manual"]


def status(spec: DatasetSpec, raw_dir: Path) -> tuple[Status, int]:
    """Report whether a dataset is ready, and how many files it holds."""
    target = raw_dir / spec.id
    if (target / ".complete").exists():
        return "ready", sum(1 for p in target.rglob("*") if p.is_file() and p.name != ".complete")
    if target.exists() and any(target.iterdir()):
        n = sum(1 for p in target.rglob("*") if p.is_file())
        return ("ready" if spec.kind == "manual" else "partial"), n
    return ("manual" if spec.kind == "manual" else "missing"), 0


def check_link(spec: DatasetSpec, client: httpx.Client | None = None) -> tuple[bool, str]:
    """Confirm a dataset's source is still reachable, without downloading it."""
    if spec.kind in ("manual", "kaggle"):
        return True, "not checked (manual or needs credentials)"
    url = ZENODO_API.format(record=spec.zenodo_record) if spec.kind == "zenodo" else str(spec.url)
    if spec.kind == "git":
        url = url.removesuffix(".git")
    http, own = _client(client)
    try:
        r = http.head(url)
        if r.status_code in (403, 405):  # some hosts refuse HEAD; ask for one byte instead
            r = http.get(url, headers={"Range": "bytes=0-0"})
        ok = r.status_code < 400
        return ok, f"HTTP {r.status_code}"
    except httpx.HTTPError as exc:
        return False, f"error: {exc}"
    finally:
        if own:
            http.close()
