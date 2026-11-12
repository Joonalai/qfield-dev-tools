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

"""Pytest fixtures running a local QFieldCloud and devices synced with it."""

from __future__ import annotations

import os
import time
from contextlib import suppress
from typing import TYPE_CHECKING

import pytest

from qfield_driver import actions
from qfield_driver.cloud.stack import HOSTED, QFieldCloudStack, resolve_ref

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from qfield_driver.app import QFieldApp
    from qfield_driver.cloud.client import QFieldCloudClient

REF_ENV = "QFIELDCLOUD_REF"
DEFAULT_PASSWORD = "pytest-qfield-123"  # noqa: S105 disposable local test stack


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("qfieldcloud")
    group.addoption(
        "--qfieldcloud-ref",
        help=(
            "QFieldCloud release: `hosted` (what app.qfield.cloud runs, default),"
            f" `latest` or a tag. Env {REF_ENV}."
        ),
    )
    group.addoption(
        "--qfieldcloud-down",
        action="store_true",
        help="Remove the QFieldCloud stack and its data after the session.",
    )
    parser.addini("qfieldcloud_ref", "QFieldCloud release, see --qfieldcloud-ref.")
    parser.addini("qfieldcloud_https_port", "Host HTTPS port, 8543 by default.")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "qfieldcloud: test needs a local QFieldCloud stack, docker or podman"
    )


@pytest.fixture(scope="session")
def qfieldcloud_ref(pytestconfig: pytest.Config) -> str:
    """Return the QFieldCloud tag under test, resolved from `hosted` or `latest`."""
    ref = (
        pytestconfig.getoption("qfieldcloud_ref")
        or os.environ.get(REF_ENV)
        or pytestconfig.getini("qfieldcloud_ref")
        or HOSTED
    )
    return resolve_ref(str(ref))


@pytest.fixture(scope="session")
def qfieldcloud_stack(
    pytestconfig: pytest.Config, qfieldcloud_ref: str, qfield_app_cache_dir: Path
) -> Iterator[QFieldCloudStack]:
    """Start a local QFieldCloud, reused across sessions until removed.

    Override to change ports or pass extra `.env` values.
    """
    stack = QFieldCloudStack(qfieldcloud_ref, qfield_app_cache_dir)
    if port := pytestconfig.getini("qfieldcloud_https_port"):
        stack.https_port = int(port)
    stack.up()
    yield stack
    if pytestconfig.getoption("qfieldcloud_down"):
        stack.down()


@pytest.fixture(scope="session")
def qfieldcloud_admin(qfieldcloud_stack: QFieldCloudStack) -> QFieldCloudClient:
    from qfield_driver.cloud.client import QFieldCloudClient  # noqa: PLC0415

    return QFieldCloudClient(qfieldcloud_stack.url, *qfieldcloud_stack.admin)


@pytest.fixture(scope="session")
def qfieldcloud_user(
    qfieldcloud_stack: QFieldCloudStack,
) -> Callable[..., QFieldCloudClient]:
    """Create a plain user once per session, and return a client logged in as it.

    One cloud token is valid on one device at a time, so give each device a user.
    """
    from qfield_driver.cloud.client import QFieldCloudClient  # noqa: PLC0415

    def user(username: str, password: str = DEFAULT_PASSWORD) -> QFieldCloudClient:
        qfieldcloud_stack.ensure_user(username, password)
        return QFieldCloudClient(qfieldcloud_stack.url, username, password)

    return user


@pytest.fixture
def qfieldcloud_project(
    qfieldcloud_admin: QFieldCloudClient,
) -> Iterator[Callable[..., str]]:
    """Upload a project directory as a new cloud project and return its id.

    The project is packaged, and deleted after the test.

    :param collaborators: Usernames added as editors
    """
    created: list[str] = []

    def create(
        directory: Path, name: str | None = None, collaborators: tuple[str, ...] = ()
    ) -> str:
        project_id = qfieldcloud_admin.create_project(
            name or f"pytest_{time.time_ns()}"
        )
        created.append(project_id)
        for username in collaborators:
            qfieldcloud_admin.add_collaborator(project_id, username)
        qfieldcloud_admin.upload(project_id, directory)
        qfieldcloud_admin.package(project_id)
        return project_id

    yield create
    for project_id in created:
        with suppress(Exception):
            qfieldcloud_admin.delete_project(project_id)


@pytest.fixture
def qfieldcloud_device(
    qfield_app_factory: Callable[..., QFieldApp],
    qfieldcloud_stack: QFieldCloudStack,
) -> Callable[..., QFieldApp]:
    """Start a QField, log it in, and download and open a cloud project.

    :param grant_plugin: The project ships a project plugin to allow
    """

    def start(
        project_id: str,
        username: str,
        password: str = DEFAULT_PASSWORD,
        *,
        name: str | None = None,
        grant_plugin: bool = False,
    ) -> QFieldApp:
        app = qfield_app_factory(name or username)
        actions.login(app, qfieldcloud_stack.url, username, password)
        project_file = actions.download_project(app, project_id)
        actions.open_project(app, project_file, grant_plugin=grant_plugin)
        return app

    return start
