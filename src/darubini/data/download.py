"""Resumable, checksum-verified dataset downloads."""

from __future__ import annotations

import hashlib
import logging
import shutil

# subprocess runs only a fixed `git clone` command (see download()).
import subprocess  # nosec B404
import zipfile
from pathlib import Path

import httpx
from tqdm import tqdm

from darubini.data.registry import DatasetSpec

log = logging.getLogger(__name__)
CHUNK = 1 << 20


class DownloadError(RuntimeError):
    """A download failed verification or could not complete."""


def md5sum(path: Path) -> str:
    """MD5 of a file, used only to match the checksum published by the data provider."""
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def fetch_http(url: str, dest: Path, client: httpx.Client | None = None) -> Path:
    """Stream ``url`` to ``dest``, resuming a partial ``.part`` file if one exists."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    own = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0))
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


def download(spec: DatasetSpec, raw_dir: Path, keep_archive: bool = False) -> Path | None:
    """Fetch one dataset into ``raw_dir/<id>``. Returns the folder, or None for manual sets."""
    target = raw_dir / spec.id
    marker = target / ".complete"
    if marker.exists():
        log.info("%s already downloaded", spec.id)
        return target

    if spec.kind == "manual":
        log.warning("%s needs a manual step:\n  %s", spec.id, spec.instructions)
        return None

    if spec.kind == "git":
        git = shutil.which("git")
        if git is None:
            raise DownloadError("git is not installed")
        if target.exists():
            shutil.rmtree(target)
        # Fixed argv with an absolute git path; the URL comes from the reviewed manifest.
        subprocess.run(  # noqa: S603  # nosec B603
            [git, "clone", "--depth", "1", str(spec.url), str(target)], check=True
        )
        marker.touch()
        return target

    if spec.url is None or spec.filename is None:  # the manifest schema already enforces this
        raise DownloadError(f"{spec.id}: http dataset needs url and filename")
    archive = raw_dir / "_archives" / spec.filename
    if not archive.exists():
        fetch_http(spec.url, archive)
    if spec.md5:
        actual = md5sum(archive)
        if actual != spec.md5:
            raise DownloadError(f"{spec.id}: checksum mismatch (expected {spec.md5}, got {actual})")
    if zipfile.is_zipfile(archive):
        extract(archive, target)
        if not keep_archive:
            archive.unlink()
    else:
        target.mkdir(parents=True, exist_ok=True)
        shutil.move(str(archive), target / spec.filename)
    marker.touch()
    return target
