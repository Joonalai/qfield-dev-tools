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
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from qfield_driver import actions
from qfield_driver.cloud.stack import (
    HOSTED,
    SOURCE_ENV,
    QFieldCloudStack,
    local_ref,
    resolve_ref,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

    from qfield_driver.app import QFieldApp
    from qfield_driver.cloud.client import QFieldCloudClient

REF_ENV = "QFIELDCLOUD_REF"
PORT_OFFSET_ENV = "QFIELDCLOUD_PORT_OFFSET"
WORKER_ENV = "PYTEST_XDIST_WORKER"
USED_STACK = pytest.StashKey[dict[str, Any]]()
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
    group.addoption(
        "--qfieldcloud-source-dir",
        help=f"QFieldCloud checkout of your own to run. Env {SOURCE_ENV}.",
    )
    parser.addini(
        "qfieldcloud_source_dir", "QFieldCloud checkout, relative to the rootdir."
    )
    parser.addini("qfieldcloud_https_port", "Host HTTPS port, 8543 by default.")
    parser.addini(
        "qfieldcloud_port_offset",
        "Move every stack port and the compose project by this offset."
        f" Env {PORT_OFFSET_ENV}.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "qfieldcloud: test needs a local QFieldCloud stack, docker or podman"
    )


def worker_username(username: str) -> str:
    """Return a username of this pytest-xdist worker, so workers never share a user.

    One cloud token is valid on one device, parallel tests would log each
    other out. Outside xdist names stay as they are.
    """
    worker = os.environ.get(WORKER_ENV)
    if not worker or username.endswith(f"_{worker}"):
        return username
    return f"{username}_{worker}"


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Remove the stack xdist workers used, once all of them are done."""
    config = session.config
    used = config.stash.get(USED_STACK, None)
    if used and config.getoption("qfieldcloud_down") and not os.environ.get(WORKER_ENV):
        QFieldCloudStack(
            used["ref"],
            Path(used["cache_dir"]),
            name=used["name"],
            source=Path(used["source"]) if used["source"] else None,
        ).down()


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: Any, error: object) -> None:  # noqa: ANN401, ARG001
    """Hear from xdist workers which stack they used."""
    output = getattr(node, "workeroutput", {})
    if "qfieldcloud_stack" in output:
        node.config.stash[USED_STACK] = output["qfieldcloud_stack"]


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(
    fixturedef: pytest.FixtureDef[Any], request: pytest.FixtureRequest
) -> Generator[None, Any, Any]:
    """Tell the xdist controller which stack a worker used, overrides included."""
    result = yield
    output = getattr(request.config, "workeroutput", None)
    if fixturedef.argname == "qfieldcloud_stack" and output is not None:
        output["qfieldcloud_stack"] = {
            "ref": result.ref,
            "cache_dir": str(result.cache_dir),
            "name": result.name,
            "source": str(result.source) if result.source else None,
        }
    return result


def local_source(config: pytest.Config) -> Path | None:
    """Return the configured QFieldCloud checkout of your own, if any."""
    if configured := config.getoption("qfieldcloud_source_dir") or os.environ.get(
        SOURCE_ENV
    ):
        return Path(configured)
    if configured := config.getini("qfieldcloud_source_dir"):
        return config.rootpath / configured
    return None


def port_offset(config: pytest.Config) -> int:
    """Return the configured offset of the stack's ports, 0 by default."""
    return int(
        os.environ.get(PORT_OFFSET_ENV) or config.getini("qfieldcloud_port_offset") or 0
    )


@pytest.fixture(scope="session")
def qfieldcloud_ref(pytestconfig: pytest.Config) -> str:
    """Return the QFieldCloud tag under test, resolved from `hosted` or `latest`.

    With a checkout of your own, `local-<directory>`.
    """
    if source := local_source(pytestconfig):
        return local_ref(source.expanduser().resolve())
    ref = (
        pytestconfig.getoption("qfieldcloud_ref")
        or os.environ.get(REF_ENV)
        or pytestconfig.getini("qfieldcloud_ref")
        or HOSTED
    )
    return resolve_ref(str(ref))


@pytest.fixture(scope="session")
def qfieldcloud_stack(
    pytestconfig: pytest.Config, qfieldcloud_ref: str, qfield_fetch_cache_dir: Path
) -> Iterator[QFieldCloudStack]:
    """Start a local QFieldCloud, reused across sessions until removed.

    Workers of pytest-xdist share it. Override to change ports or pass extra
    `.env` values.
    """
    if source := local_source(pytestconfig):
        stack = QFieldCloudStack.local(
            source, qfield_fetch_cache_dir, offset=port_offset(pytestconfig)
        )
    else:
        stack = QFieldCloudStack.with_offset(
            qfieldcloud_ref, qfield_fetch_cache_dir, port_offset(pytestconfig)
        )
    if port := pytestconfig.getini("qfieldcloud_https_port"):
        stack.https_port = int(port)
    stack.up()
    yield stack
    # Under xdist the controller removes it once every worker is done.
    if pytestconfig.getoption("qfieldcloud_down") and not os.environ.get(WORKER_ENV):
        stack.down()


@pytest.fixture(scope="session")
def qfieldcloud_admin(qfieldcloud_stack: QFieldCloudStack) -> QFieldCloudClient:
    from qfield_driver.cloud.client import QFieldCloudClient  # noqa: PLC0415

    username, password = qfieldcloud_stack.admin
    if worker_username(username) != username:
        # A login ends the user's other sessions, so each worker has its own.
        username = worker_username(username)
        qfieldcloud_stack.ensure_user(username, password, superuser=True)
    return QFieldCloudClient(
        qfieldcloud_stack.url,
        username,
        password,
        verify=qfieldcloud_stack.ca_certificate,
    )


@pytest.fixture(scope="session")
def qfieldcloud_user(
    qfieldcloud_stack: QFieldCloudStack,
) -> Callable[..., QFieldCloudClient]:
    """Create a plain user once per session, and return a client logged in as it.

    One cloud token is valid on one device at a time, so give each device a user.
    """
    from qfield_driver.cloud.client import QFieldCloudClient  # noqa: PLC0415

    def user(username: str, password: str = DEFAULT_PASSWORD) -> QFieldCloudClient:
        username = worker_username(username)
        qfieldcloud_stack.ensure_user(username, password)
        return QFieldCloudClient(
            qfieldcloud_stack.url,
            username,
            password,
            verify=qfieldcloud_stack.ca_certificate,
        )

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
            qfieldcloud_admin.add_collaborator(project_id, worker_username(username))
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
        username = worker_username(username)
        app = qfield_app_factory(name or username)
        actions.login(app, qfieldcloud_stack.url, username, password)
        project_file = actions.download_project(app, project_id)
        actions.open_project(app, project_file, grant_plugin=grant_plugin)
        return app

    return start
