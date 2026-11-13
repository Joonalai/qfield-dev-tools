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

from pathlib import Path

import pytest
from typer.testing import CliRunner

from qfield_fetch.cli import app

pytest_plugins = ["github_stub"]
pytestmark = pytest.mark.usefixtures("github")

runner = CliRunner()


def test_fetched_paths_are_printed(cache_dir: Path) -> None:
    result = runner.invoke(app, ["source", "4.2.9"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == str(cache_dir / "source/v4.2.9")


def test_cache_dir_option_wins_over_the_env(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["appimage", "4.2.9", "--cache-dir", str(tmp_path / "other")]
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == str(tmp_path / "other/appimage/4.2.9/AppRun")


def test_entries_are_listed_and_removed(cache_dir: Path) -> None:
    runner.invoke(app, ["qfieldcloud", "latest"])

    listed = runner.invoke(app, ["list"])
    removed = runner.invoke(app, ["remove", "qfieldcloud", "v4.2.9"])
    missing = runner.invoke(app, ["remove", "qfieldcloud", "v4.2.9"])

    assert listed.stdout == f"qfieldcloud\tv4.2.9\t{cache_dir / 'qfieldcloud/v4.2.9'}\n"
    assert removed.exit_code == 0
    assert missing.exit_code == 1
    assert "No qfieldcloud v4.2.9" in missing.stderr


def test_bad_refs_exit_with_the_reason(cache_dir: Path) -> None:
    result = runner.invoke(app, ["source", "../x"])

    assert result.exit_code == 1
    assert "Not a release or git ref: '../x'" in result.stderr
    assert not cache_dir.exists()
