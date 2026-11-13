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

import itertools
import json
import logging
import os
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from qfield_driver.app import DriverError, QFieldApp
from qfield_driver.appimage import CACHE_ENV, default_cache_dir, ensure_appimage

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

LOGGER = logging.getLogger(__name__)
APPS_KEY = pytest.StashKey[list[tuple[str, QFieldApp, Path]]]()
DEFAULT_VERSION = "4.2.9"
VERSION_ENV = "QFIELD_APP_VERSION"


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
    group.addoption(
        "--qfield-app-reuse",
        action="store_true",
        help=(
            "Keep each device running between tests and reset it instead of"
            " restarting. Faster, but settings a test changes stay."
        ),
    )
    parser.addini(
        "qfield_app_reuse",
        "Reuse running devices, see --qfield-app-reuse.",
        type="bool",
        default=False,
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "qfield_app: test runs a real QField app, Linux and Xvfb only"
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Add each device's screenshot, message log and log tail to a failure."""
    report = yield
    if report.failed and call.when in ("setup", "call"):
        for name, app, directory in item.stash.get(APPS_KEY, []):
            report.sections.append(
                (f"QField {name}", app.diagnose(directory, f"{call.when}-{name}"))
            )
    return report


def cache_dir(config: pytest.Config) -> Path:
    """Where AppImages and QFieldCloud checkouts are kept."""
    configured = os.environ.get(CACHE_ENV) or config.getini("qfield_app_cache_dir")
    if configured:
        return config.rootpath / Path(configured).expanduser()
    return default_cache_dir()


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
    return cache_dir(pytestconfig)


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
def qfield_app_settings() -> dict[str, object]:
    """QField settings written to every profile before QField starts.

    Keys are QSettings keys, `myplugin/interval` for example. Override to set them.
    """
    return {}


class _Pool:
    """Running devices kept between tests, one per name."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.apps: dict[str, tuple[str, QFieldApp]] = {}
        self._homes = itertools.count()

    def get(self, name: str, key: str, start: Callable[[Path], QFieldApp]) -> QFieldApp:
        if name in self.apps:
            old_key, app = self.apps.pop(name)
            if old_key == key and app.running:
                try:
                    app.reset()
                except (DriverError, TimeoutError):
                    LOGGER.warning("Could not reset %s, starting it again", name)
                else:
                    self.apps[name] = (key, app)
                    return app
            app.close()
        app = start(self.directory / f"{name}-{next(self._homes)}")
        self.apps[name] = (key, app)
        return app

    def close(self) -> None:
        for _key, app in self.apps.values():
            app.close()
        self.apps.clear()


@pytest.fixture(scope="session")
def _qfield_app_pool(
    pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[_Pool | None]:
    reuse = pytestconfig.getoption("qfield_app_reuse") or pytestconfig.getini(
        "qfield_app_reuse"
    )
    if not reuse:
        yield None
        return
    pool = _Pool(tmp_path_factory.mktemp("qfield-devices"))
    yield pool
    pool.close()


@pytest.fixture
def qfield_app_factory(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    qfield_app_binary: Path,
    qfield_app_plugins: dict[str, Path],
    qfield_app_settings: dict[str, object],
    _qfield_app_pool: _Pool | None,
) -> Iterator[Callable[..., QFieldApp]]:
    """Start QField apps, each with its own profile and display.

    Call it with a device name, one profile directory per name. With
    `--qfield-app-reuse` a device started with the same plugins and settings
    in an earlier test is reset and handed out again.
    """
    started = request.node.stash.setdefault(APPS_KEY, [])
    with ExitStack() as stack:

        def start(
            name: str = "device",
            app_plugins: dict[str, Path] | None = None,
        ) -> QFieldApp:
            plugins = qfield_app_plugins if app_plugins is None else app_plugins

            def new(home: Path) -> QFieldApp:
                app = QFieldApp(
                    qfield_app_binary,
                    home,
                    app_plugins=plugins,
                    settings=qfield_app_settings,
                )
                return app.__enter__()

            if _qfield_app_pool is None:
                app = new(tmp_path / name)
                stack.callback(app.close)
            else:
                key = json.dumps(
                    [
                        sorted((name, str(path)) for name, path in plugins.items()),
                        qfield_app_settings,
                    ],
                    sort_keys=True,
                    default=str,
                )
                app = _qfield_app_pool.get(name, key, new)
            started.append((name, app, tmp_path))
            return app

        yield start


@pytest.fixture
def qfield_app(qfield_app_factory: Callable[..., QFieldApp]) -> QFieldApp:
    """Start a QField with an isolated profile."""
    return qfield_app_factory()
