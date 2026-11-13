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

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from qfield_driver import actions
from qfield_driver.app import QFieldApp
from qfield_driver.cloud.client import QFieldCloudClient
from qfield_driver.cloud.stack import QFieldCloudStack

pytestmark = [pytest.mark.qfield_app, pytest.mark.qfieldcloud]

POINTS = "points"
SURVEYOR_A = "surveyor_a"
SURVEYOR_B = "surveyor_b"


@pytest.fixture
def cloud_project(
    project_file: Path,
    qfieldcloud_user: Callable[..., QFieldCloudClient],
    qfieldcloud_project: Callable[..., str],
) -> str:
    qfieldcloud_user(SURVEYOR_A)
    qfieldcloud_user(SURVEYOR_B)
    return qfieldcloud_project(
        project_file.parent, collaborators=(SURVEYOR_A, SURVEYOR_B)
    )


def test_stack_runs_the_resolved_release(
    qfieldcloud_stack: QFieldCloudStack, qfieldcloud_admin: QFieldCloudClient
) -> None:
    # Local builds report version `dev`, the checkout carries the release.
    described = subprocess.run(
        ["git", "describe", "--tags"],  # noqa: S607 git from PATH
        cwd=qfieldcloud_stack.source_dir,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert described == qfieldcloud_stack.ref
    status = qfieldcloud_admin.get("/status/")
    assert (status["database"], status["storage"]) == ("ok", "ok")


def test_edit_travels_from_one_device_to_another(
    cloud_project: str,
    qfieldcloud_device: Callable[..., QFieldApp],
    qfieldcloud_admin: QFieldCloudClient,
) -> None:
    text = f"edited-{time.time_ns()}"
    device_a = qfieldcloud_device(cloud_project, SURVEYOR_A)

    actions.edit_in_form(device_a, POINTS, "fid = 1", "text_field", text)
    pushed = actions.push(device_a, cloud_project)

    assert pushed == 1
    deltas = qfieldcloud_admin.wait_for_deltas(cloud_project, pushed)
    assert [delta["status"] for delta in deltas] == ["STATUS_APPLIED"]

    device_b = qfieldcloud_device(cloud_project, SURVEYOR_B)
    rows = actions.features(device_b, POINTS, ["text_field"], "fid = 1")
    assert rows == [{"text_field": text}]


def test_synchronize_reports_the_deltas(
    cloud_project: str, qfieldcloud_device: Callable[..., QFieldApp]
) -> None:
    device = qfieldcloud_device(cloud_project, SURVEYOR_A)
    actions.edit_in_form(device, POINTS, "fid = 1", "text_field", "synced")

    result = actions.synchronize(device, cloud_project)

    assert result == {"deltas": 1, "delta_status": "applied"}
