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

import pytest

from qfield_fetch import CACHE_ENV
from qfield_fetch.pytest_plugin import VERSION_ENV

pytest_plugins = ["pytester"]

INNER_ARGS = ("-p", "no:pytest-qfield", "-p", "no:pytest_qgis", "-p", "no:pytest-qt")

SHOW_CONFIG = """
from qfield_fetch.pytest_plugin import configured_version

def test_show(pytestconfig, qfield_fetch_cache_dir):
    print("version", configured_version(pytestconfig))
    print("cache", qfield_fetch_cache_dir)
"""


@pytest.fixture
def inner(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> pytest.Pytester:
    monkeypatch.delenv(VERSION_ENV, raising=False)
    monkeypatch.delenv(CACHE_ENV, raising=False)
    pytester.makepyfile(SHOW_CONFIG)
    pytester.makeini("[pytest]\nqfield_version = 4.2.9\nqfield_fetch_cache_dir = cache")
    return pytester


def test_ini_sets_version_and_cache_relative_to_rootdir(inner: pytest.Pytester) -> None:
    result = inner.runpytest(*INNER_ARGS, "-s")

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*version 4.2.9", f"cache {inner.path / 'cache'}"])


def test_option_and_env_win_over_the_ini(
    inner: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VERSION_ENV, "4.3.0")
    monkeypatch.setenv(CACHE_ENV, str(inner.path / "env-cache"))

    from_env = inner.runpytest(*INNER_ARGS, "-s")
    from_option = inner.runpytest(*INNER_ARGS, "-s", "--qfield-version", "master")

    from_env.stdout.fnmatch_lines(
        ["*version 4.3.0", f"cache {inner.path / 'env-cache'}"]
    )
    from_option.stdout.fnmatch_lines(["*version master"])
