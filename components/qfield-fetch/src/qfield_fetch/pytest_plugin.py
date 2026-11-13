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

"""Pytest options that pytest-qfield and pytest-qfield-app share."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from qfield_fetch.cache import CACHE_ENV, default_cache_dir

VERSION_ENV = "QFIELD_VERSION"
VERSION_KEY = "qfield_version"
CACHE_KEY = "qfield_fetch_cache_dir"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("qfield-fetch")
    group.addoption(
        "--qfield-version",
        help=f"QField release or git ref to test against. Env {VERSION_ENV}.",
    )
    parser.addini(VERSION_KEY, "QField release or git ref to test against.")
    parser.addini(
        CACHE_KEY,
        f"qfield-fetch cache, relative to the rootdir. Env {CACHE_ENV}.",
    )


def configured_version(config: pytest.Config) -> str | None:
    """Return the QField version from the option, the env or the ini, in that order."""
    return (
        config.getoption(VERSION_KEY)
        or os.environ.get(VERSION_ENV)
        or config.getini(VERSION_KEY)
        or None
    )


def configured_cache_dir(config: pytest.Config) -> Path:
    """Return the cache from the env or the ini, or the user cache."""
    configured = config.getini(CACHE_KEY)
    if configured and not os.environ.get(CACHE_ENV):
        return config.rootpath / Path(configured).expanduser()
    return default_cache_dir()


@pytest.fixture(scope="session")
def qfield_fetch_cache_dir(pytestconfig: pytest.Config) -> Path:
    """Where qfield-fetch keeps AppImages and sources."""
    return configured_cache_dir(pytestconfig)
