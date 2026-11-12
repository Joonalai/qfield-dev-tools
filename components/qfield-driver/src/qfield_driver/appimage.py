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

import json
import logging
import shutil
import subprocess
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from pathlib import Path

LOGGER = logging.getLogger(__name__)

RELEASES = "https://github.com/opengisch/QField/releases"
LATEST_API = "https://api.github.com/repos/opengisch/QField/releases/latest"
LATEST = "latest"


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
    directory = cache_dir / f"qfield-{version}"
    app_run = directory / "squashfs-root/AppRun"
    if app_run.exists():
        return app_run
    directory.mkdir(parents=True, exist_ok=True)
    name = f"qfield-v{version}-linux-x64.AppImage"
    image = directory / name
    partial = directory / f"{name}.part"
    LOGGER.info("Downloading %s", name)
    with (
        urlopen(  # noqa: S310 fixed https URL
            f"{RELEASES}/download/v{version}/{name}", timeout=60
        ) as response,
        partial.open("wb") as out,
    ):
        shutil.copyfileobj(response, out)
    partial.rename(image)
    image.chmod(0o755)
    # Extracting avoids FUSE, which containers and CI runners often lack.
    subprocess.run(  # noqa: S603 the AppImage we downloaded
        [str(image), "--appimage-extract"],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    image.unlink()
    return app_run
