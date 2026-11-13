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

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from qfield_fetch import (
    Entry,
    FetchError,
    Kind,
    appimage,
    entries,
    entry_path,
    qfield_source,
    qfieldcloud_source,
    remove,
)

if TYPE_CHECKING:
    from pathlib import Path

    from github_stub import Repository

pytest_plugins = ["github_stub"]
pytestmark = pytest.mark.usefixtures("github")


def test_appimage_is_extracted_once_by_parallel_callers(
    cache_dir: Path, extractions: Path
) -> None:
    with ThreadPoolExecutor(4) as pool:
        app_runs = set(pool.map(lambda _: appimage("4.2.9"), range(4)))

    assert app_runs == {cache_dir / "appimage/4.2.9/AppRun"}
    assert extractions.read_text() == "x\n"
    assert sorted(path.name for path in (cache_dir / "appimage").iterdir()) == [
        ".4.2.9.lock",
        "4.2.9",
    ]


@pytest.mark.parametrize("version", ["v4.2.9", "latest"])
def test_appimage_versions_resolve_to_the_release(
    version: str, cache_dir: Path
) -> None:
    assert appimage(version) == cache_dir / "appimage/4.2.9/AppRun"


def test_appimage_not_matching_its_digest_is_refused(
    github_root: Path, extractions: Path
) -> None:
    release = github_root / "opengisch/QField/releases/download/v4.2.9"
    (release / "qfield-v4.2.9-linux-x64.AppImage").write_text("#!/bin/sh\n")

    with pytest.raises(FetchError, match="SHA-256"):
        appimage("4.2.9")

    assert entries() == []
    assert extractions.read_text() == ""


def test_missing_appimage_leaves_no_entry(cache_dir: Path) -> None:
    with pytest.raises(FetchError, match=r"4\.3\.0"):
        appimage("4.3.0")

    assert entries() == []
    assert [path.name for path in (cache_dir / "appimage").iterdir()] == [".4.3.0.lock"]


def test_qfield_source_clones_only_the_version(
    cache_dir: Path, github: dict[str, Repository]
) -> None:
    checkout = qfield_source("4.2.9")

    assert checkout == cache_dir / "source/v4.2.9"
    assert (checkout / "VERSION").read_text() == "4.2.9"
    assert github["QField"].git("rev-list", "--count", "HEAD", cwd=checkout) == "1"


def test_moved_branch_is_cloned_again_on_update(
    github: dict[str, Repository],
) -> None:
    checkout = qfield_source("master")
    github["QField"].commit("moved")
    github["QField"].push()

    assert (qfield_source("master") / "VERSION").read_text() == "next"
    assert (qfield_source("master", update=True) / "VERSION").read_text() == "moved"
    assert checkout == qfield_source("master")


def test_qfieldcloud_source_clones_the_latest_release(cache_dir: Path) -> None:
    checkout = qfieldcloud_source("latest")

    assert checkout == cache_dir / "qfieldcloud/v4.2.9"
    assert (checkout / "VERSION").read_text() == "4.2.9"


def test_unknown_ref_raises_and_leaves_no_entry() -> None:
    with pytest.raises(FetchError, match="nope"):
        qfield_source("nope")

    assert entries() == []


@pytest.mark.parametrize("ref", ["../x", "/etc", "-x", "a/../../b", ""])
def test_refs_cannot_leave_the_cache(ref: str) -> None:
    with pytest.raises(ValueError, match="Not a"):
        qfield_source(ref)
    with pytest.raises(ValueError, match="Not a"):
        appimage(ref)


def test_leftovers_of_killed_fetches_are_removed(cache_dir: Path) -> None:
    leftover = cache_dir / "source/.v4.2.9-killed"
    leftover.mkdir(parents=True)

    qfield_source("4.2.9")

    assert not leftover.exists()


def test_entries_are_listed_and_removed(cache_dir: Path) -> None:
    appimage("4.2.9")
    qfield_source("4.2.9")
    qfieldcloud_source("v4.2.9")

    assert entries() == [
        Entry(Kind.APPIMAGE, "4.2.9", cache_dir / "appimage/4.2.9"),
        Entry(Kind.SOURCE, "v4.2.9", cache_dir / "source/v4.2.9"),
        Entry(Kind.QFIELDCLOUD, "v4.2.9", cache_dir / "qfieldcloud/v4.2.9"),
    ]
    assert entry_path(Kind.SOURCE, "v4.2.9") == cache_dir / "source/v4.2.9"
    assert remove(Kind.SOURCE, "v4.2.9")
    assert not remove(Kind.SOURCE, "v4.2.9")
    assert [entry.kind for entry in entries()] == [Kind.APPIMAGE, Kind.QFIELDCLOUD]
