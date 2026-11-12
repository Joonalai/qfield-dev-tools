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

"""Pytest fixtures starting real QField apps."""

from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from qfield_driver.app import QFieldApp
from qfield_driver.appimage import ensure_appimage

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

DEFAULT_VERSION = "4.2.9"
VERSION_ENV = "QFIELD_APP_VERSION"
CACHE_ENV = "QFIELD_APP_CACHE_DIR"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("qfield-app")
    group.addoption(
        "--qfield-app-version",
        help=f"QField release to run, `latest` for the newest. Env {VERSION_ENV}.",
    )
    parser.addini(
        "qfield_app_version",
        f"QField release to run, `latest` for the newest. Default {DEFAULT_VERSION}.",
    )
    parser.addini("qfield_app_cache_dir", "Where QField AppImages are kept.")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "qfield_app: test runs a real QField app, Linux and Xvfb only"
    )


@pytest.fixture(scope="session")
def qfield_app_version(pytestconfig: pytest.Config) -> str:
    """Return the QField release under test."""
    return str(
        pytestconfig.getoption("qfield_app_version")
        or os.environ.get(VERSION_ENV)
        or pytestconfig.getini("qfield_app_version")
        or DEFAULT_VERSION
    )


@pytest.fixture(scope="session")
def qfield_app_cache_dir(pytestconfig: pytest.Config) -> Path:
    configured = os.environ.get(CACHE_ENV) or pytestconfig.getini(
        "qfield_app_cache_dir"
    )
    if configured:
        return pytestconfig.rootpath / Path(configured).expanduser()
    return Path.home() / ".cache" / "pytest-qfield-e2e"


@pytest.fixture(scope="session")
def qfield_app_binary(qfield_app_version: str, qfield_app_cache_dir: Path) -> Path:
    """`AppRun` of the extracted QField AppImage."""
    return ensure_appimage(qfield_app_version, qfield_app_cache_dir)


@pytest.fixture
def qfield_app_plugins() -> dict[str, Path]:
    """App plugins to install in every started QField, by uuid.

    Override to install the plugin under test as a real app plugin.
    """
    return {}


@pytest.fixture
def qfield_app_factory(
    tmp_path: Path,
    qfield_app_binary: Path,
    qfield_app_plugins: dict[str, Path],
) -> Iterator[Callable[..., QFieldApp]]:
    """Start QField apps, each with its own profile and display.

    Call it with a device name, one profile directory per name.
    """
    with ExitStack() as stack:

        def start(
            name: str = "device",
            app_plugins: dict[str, Path] | None = None,
        ) -> QFieldApp:
            plugins = qfield_app_plugins if app_plugins is None else app_plugins
            app = QFieldApp(qfield_app_binary, tmp_path / name, app_plugins=plugins)
            return stack.enter_context(app)

        yield start


@pytest.fixture
def qfield_app(qfield_app_factory: Callable[..., QFieldApp]) -> QFieldApp:
    """Start a QField with an isolated profile."""
    return qfield_app_factory()
