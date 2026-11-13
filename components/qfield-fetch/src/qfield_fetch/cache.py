# Copyright (C) 2026 qfield-dev-tools Contributors.
#
#
# This file is part of qfield-dev-tools.
#
# qfield-dev-tools is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# qfield-dev-tools is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qfield-dev-tools.  If not, see <https://www.gnu.org/licenses/>.

"""Downloads kept in one cache, each fetched once even by parallel processes.

An entry is complete once its directory exists. It is built in a temporary
directory next to it and renamed into place while holding a file lock.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

LOGGER = logging.getLogger(__name__)

CACHE_ENV = "QFIELD_FETCH_CACHE_DIR"
GITHUB = "https://github.com"
GITHUB_API = "https://api.github.com"
QFIELD = "opengisch/QField"
QFIELDCLOUD = "opengisch/QFieldCloud"
LATEST = "latest"
DOWNLOAD_CHUNK = 1 << 20
VERSION_PATTERN = re.compile(r"v?(\d+\.\d+\.\d+[A-Za-z0-9.-]*)")
# Refs name cache directories, so nothing that could leave the cache.
REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")


class FetchError(RuntimeError):
    """A download or clone failed."""


class Kind(StrEnum):
    APPIMAGE = "appimage"
    SOURCE = "source"
    QFIELDCLOUD = "qfieldcloud"


@dataclass(frozen=True)
class Entry:
    kind: Kind
    name: str
    path: Path


def default_cache_dir() -> Path:
    """Return `$QFIELD_FETCH_CACHE_DIR`, or `qfield-fetch` in the user cache."""
    configured = os.environ.get(CACHE_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "qfield-fetch"


def _github_api(path: str) -> dict[str, Any]:
    headers = {"Accept": "application/vnd.github+json"}
    # Anonymous calls are limited to 60 an hour, CI runners share that.
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{GITHUB_API}{path}", headers=headers)  # noqa: S310 GitHub API URL
    with urlopen(request, timeout=30) as response:  # noqa: S310 GitHub API URL
        return json.load(response)


def latest_release(repository: str) -> str:
    """Return the tag of the newest release, `v4.2.9` for example."""
    return str(_github_api(f"/repos/{repository}/releases/latest")["tag_name"])


def _asset_digest(version: str, name: str) -> str | None:
    """Return the SHA-256 GitHub lists for a release asset, if it lists one."""
    try:
        release = _github_api(f"/repos/{QFIELD}/releases/tags/v{version}")
    except OSError as error:
        LOGGER.warning("Not verifying %s, its release is unavailable: %s", name, error)
        return None
    for asset in release.get("assets", []):
        digest = str(asset.get("digest") or "")
        if asset.get("name") == name and digest.startswith("sha256:"):
            return digest.removeprefix("sha256:")
    LOGGER.warning("Not verifying %s, its release lists no digest", name)
    return None


def release_version(version: str) -> str:
    """Return the QField release `4.2.9` for `4.2.9`, `v4.2.9` or `latest`."""
    if version == LATEST:
        version = latest_release(QFIELD)
    match = VERSION_PATTERN.fullmatch(version)
    if not match:
        msg = f"Not a QField release version: {version!r}"
        raise ValueError(msg)
    return match[1]


def appimage(version: str, cache_dir: Path | None = None) -> Path:
    """Download and extract a QField release AppImage once, and return its `AppRun`.

    :param version: A release such as `4.2.9`, or `latest`
    """
    version = release_version(version)
    target = _entry_path(Kind.APPIMAGE, version, cache_dir)
    _ensure(target, partial(_install_appimage, version), update=False)
    return target / "AppRun"


def qfield_source(
    ref: str, cache_dir: Path | None = None, *, update: bool = False
) -> Path:
    """Clone QField at one ref only, and return the checkout.

    :param ref: A release such as `4.2.9`, `latest`, a tag or a branch
    :param update: Clone again, for a branch that moved
    """
    ref = _git_ref(ref, QFIELD)
    if match := VERSION_PATTERN.fullmatch(ref):
        ref = f"v{match[1]}"
    target = _entry_path(Kind.SOURCE, ref, cache_dir)
    return _ensure(target, partial(_clone, QFIELD, ref), update=update)


def qfieldcloud_source(
    ref: str, cache_dir: Path | None = None, *, update: bool = False
) -> Path:
    """Clone QFieldCloud at one ref only, and return the checkout.

    :param ref: A tag such as `v26.30`, `latest` or a branch
    :param update: Clone again, for a branch that moved
    """
    ref = _git_ref(ref, QFIELDCLOUD)
    target = _entry_path(Kind.QFIELDCLOUD, ref, cache_dir)
    return _ensure(target, partial(_clone, QFIELDCLOUD, ref), update=update)


def entries(cache_dir: Path | None = None) -> list[Entry]:
    root = cache_dir or default_cache_dir()
    return [
        Entry(kind, path.name, path)
        for kind in Kind
        for path in sorted((root / kind).glob("[!.]*"))
        if path.is_dir()
    ]


def entry_path(kind: Kind, name: str, cache_dir: Path | None = None) -> Path:
    """Return where an entry is kept, fetched or not.

    :param name: A release version or resolved ref, as `entries` names them
    """
    return _entry_path(Kind(kind), _checked_ref(name), cache_dir)


def remove(kind: Kind, name: str, cache_dir: Path | None = None) -> bool:
    """Remove one entry, and return whether it existed."""
    target = entry_path(kind, name, cache_dir)
    if not target.exists():
        return False
    with _locked(target):
        shutil.rmtree(target)
    return True


def _git_ref(ref: str, repository: str) -> str:
    if ref == LATEST:
        return latest_release(repository)
    return _checked_ref(ref)


def _checked_ref(ref: str) -> str:
    if not REF_PATTERN.fullmatch(ref) or ".." in ref:
        msg = f"Not a release or git ref: {ref!r}"
        raise ValueError(msg)
    return ref


def _entry_path(kind: Kind, name: str, cache_dir: Path | None) -> Path:
    return (cache_dir or default_cache_dir()) / kind / name.replace("/", "_")


@contextmanager
def _locked(target: Path) -> Iterator[None]:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.with_name(f".{target.name}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _ensure(target: Path, install: Callable[[Path], None], *, update: bool) -> Path:
    """Build the entry with `install` unless it exists, and return it."""
    if target.exists() and not update:
        return target
    with _locked(target):
        if target.exists() and not update:
            return target
        # Holding the lock, so these are left by killed processes.
        for leftover in target.parent.glob(f".{target.name}-*"):
            shutil.rmtree(leftover, ignore_errors=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{target.name}-", dir=target.parent
        ) as work_dir:
            work = Path(work_dir)
            install(work / "new")
            if target.exists():
                target.rename(work / "old")
            (work / "new").rename(target)
    return target


def _run(*args: str, cwd: Path | None = None) -> None:
    completed = subprocess.run(  # noqa: S603 fixed commands, refs are checked
        args, cwd=cwd, check=False, capture_output=True, text=True
    )
    if completed.returncode:
        msg = f"{' '.join(args)} failed:\n{completed.stderr[-3000:]}"
        raise FetchError(msg)


def _install_appimage(version: str, target: Path) -> None:
    name = f"qfield-v{version}-linux-x64.AppImage"
    image = target.parent / name
    LOGGER.info("Downloading %s", name)
    url = f"{GITHUB}/{QFIELD}/releases/download/v{version}/{name}"
    sha256 = hashlib.sha256()
    try:
        with (
            urlopen(url, timeout=60) as response,  # noqa: S310 GitHub release URL
            image.open("wb") as out,
        ):
            while chunk := response.read(DOWNLOAD_CHUNK):
                sha256.update(chunk)
                out.write(chunk)
    except OSError as error:
        msg = f"Downloading {url} failed: {error}"
        raise FetchError(msg) from error
    expected = _asset_digest(version, name)
    if expected and sha256.hexdigest() != expected:
        msg = f"{name} does not match the SHA-256 of its release"
        raise FetchError(msg)
    image.chmod(0o755)
    # Extracting avoids FUSE, which containers and CI runners often lack.
    _run(str(image), "--appimage-extract", cwd=target.parent)
    (target.parent / "squashfs-root").rename(target)


def _clone(repository: str, ref: str, target: Path) -> None:
    LOGGER.info("Cloning %s at %s", repository, ref)
    _run(
        *("git", "-c", "advice.detachedHead=false", "clone", "--quiet"),
        *("--depth=1", f"--branch={ref}"),
        f"{GITHUB}/{repository}.git",
        str(target),
    )
