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

"""Stock QField release AppImages, downloaded and extracted once."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)
CACHE_ENV = "QFIELD_APP_CACHE_DIR"


def default_cache_dir() -> Path:
    """Where AppImages and QFieldCloud checkouts are kept outside pytest."""
    configured = os.environ.get(CACHE_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".cache" / "qfield-driver"


RELEASES = "https://github.com/opengisch/QField/releases"
LATEST_API = "https://api.github.com/repos/opengisch/QField/releases/latest"
LATEST = "latest"
# The version becomes part of cache paths
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+[A-Za-z0-9.-]*")


def latest_version() -> str:
    """Version of the newest QField release, `4.2.9` for tag `v4.2.9`."""
    request = Request(LATEST_API, headers={"Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 fixed https URL
        return str(json.load(response)["tag_name"]).removeprefix("v")


def ensure_appimage(version: str, cache_dir: Path) -> Path:
    """Fetch and extract a release AppImage once, and return its `AppRun`.

    :param version: A release such as `4.2.9`, or `latest`
    """
    if version == LATEST:
        version = latest_version()
    if not VERSION_PATTERN.fullmatch(version):
        msg = f"Not a QField release version: {version!r}"
        raise ValueError(msg)
    directory = cache_dir / f"qfield-{version}"
    root = directory / "squashfs-root"
    app_run = root / "AppRun"
    if app_run.exists():
        return app_run
    directory.mkdir(parents=True, exist_ok=True)
    # xdist workers and MCP calls may fetch the same release at once.
    with (directory / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not app_run.exists():
            _install(version, directory, root)
    return app_run


def _install(version: str, directory: Path, root: Path) -> None:
    name = f"qfield-v{version}-linux-x64.AppImage"
    LOGGER.info("Downloading %s", name)
    with tempfile.TemporaryDirectory(dir=directory) as work_dir:
        work = Path(work_dir)
        image = work / name
        with (
            urlopen(  # noqa: S310 fixed https URL
                f"{RELEASES}/download/v{version}/{name}", timeout=60
            ) as response,
            image.open("wb") as out,
        ):
            shutil.copyfileobj(response, out)
        image.chmod(0o755)
        # Extracting avoids FUSE, which containers and CI runners often lack.
        subprocess.run(  # noqa: S603 the AppImage we downloaded
            [str(image), "--appimage-extract"],
            cwd=work,
            check=True,
            capture_output=True,
        )
        # Only a complete extraction is renamed in place, drop an interrupted one.
        shutil.rmtree(root, ignore_errors=True)
        (work / "squashfs-root").rename(root)
