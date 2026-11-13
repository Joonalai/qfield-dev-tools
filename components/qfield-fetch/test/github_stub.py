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

"""A local stand-in for github.com, used as a pytest plugin."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from qfield_fetch import cache

APPIMAGE = "qfield-v4.2.9-linux-x64.AppImage"
# Extracts like an AppImage and counts its extractions.
FAKE_APPIMAGE = """#!/bin/sh
[ "$1" = --appimage-extract ] || exit 1
[ -z "$EXTRACTIONS" ] || echo x >> "$EXTRACTIONS"
mkdir -p squashfs-root
printf '#!/bin/sh\\n' > squashfs-root/AppRun
"""


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(  # noqa: S603 test repositories only
        ["git", "-c", "user.name=test", "-c", "user.email=test@localhost", *args],  # noqa: S607 git from PATH
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Repository:
    """A working repository pushing to a bare one served as a GitHub repository."""

    git = staticmethod(git)

    def __init__(self, work: Path, bare: Path) -> None:
        self.work = work
        work.mkdir(parents=True)
        git("init", "--quiet", "--initial-branch=master", cwd=work)
        self.commit("first")
        self.commit("4.2.9")
        git("tag", "v4.2.9", cwd=work)
        self.commit("next")
        bare.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--quiet", "--bare", str(work), str(bare), cwd=work)
        git("remote", "add", "origin", str(bare), cwd=work)

    def commit(self, content: str) -> None:
        (self.work / "VERSION").write_text(content)
        git("add", "VERSION", cwd=self.work)
        git("commit", "--quiet", "-m", content, cwd=self.work)

    def push(self) -> None:
        git("push", "--quiet", "origin", "master", cwd=self.work)


@pytest.fixture
def extractions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "extractions"
    path.touch()
    monkeypatch.setenv("EXTRACTIONS", str(path))
    return path


@pytest.fixture
def github_root(tmp_path: Path) -> Path:
    return tmp_path / "github"


@pytest.fixture
def github(
    tmp_path: Path, github_root: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Repository]:
    """Stand in for github.com with QField 4.2.9 and both repositories."""
    root = github_root
    monkeypatch.setattr(cache, "GITHUB", root.as_uri())
    monkeypatch.setattr(cache, "GITHUB_API", (root / "api").as_uri())
    release = root / "opengisch/QField/releases/download/v4.2.9"
    release.mkdir(parents=True)
    (release / APPIMAGE).write_text(FAKE_APPIMAGE)
    digest = hashlib.sha256(FAKE_APPIMAGE.encode()).hexdigest()
    asset = {"name": APPIMAGE, "digest": f"sha256:{digest}"}
    for repository in ("QField", "QFieldCloud"):
        releases = root / f"api/repos/opengisch/{repository}/releases"
        (releases / "tags").mkdir(parents=True)
        (releases / "latest").write_text(json.dumps({"tag_name": "v4.2.9"}))
        (releases / "tags/v4.2.9").write_text(json.dumps({"assets": [asset]}))
    return {
        name: Repository(tmp_path / "work" / name, root / f"opengisch/{name}.git")
        for name in ("QField", "QFieldCloud")
    }


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cache"
    monkeypatch.setenv(cache.CACHE_ENV, str(path))
    return path
