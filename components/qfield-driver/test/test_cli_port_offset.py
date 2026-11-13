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

from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from qfield_driver.cloud import cli
from qfield_driver.cloud.stack import QFieldCloudStack

runner = CliRunner()


def _record(stacks: list[QFieldCloudStack]) -> Callable[[QFieldCloudStack], None]:
    def record(stack: QFieldCloudStack) -> None:
        stacks.append(stack)

    return record


def test_up_moves_the_stack_by_the_port_offset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "resolve_ref", lambda ref: ref)
    started: list[QFieldCloudStack] = []
    monkeypatch.setattr(cli.QFieldCloudStack, "up", _record(started))

    result = runner.invoke(
        cli.app,
        ["up", "--ref", "v1", "--cache-dir", str(tmp_path), "--port-offset", "10"],
    )

    assert result.output == "https://localhost:8553\n"
    assert started[0].project_name.endswith("_v1-10")


def test_port_offset_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "resolve_ref", lambda ref: ref)
    downed: list[QFieldCloudStack] = []
    monkeypatch.setattr(cli.QFieldCloudStack, "down", _record(downed))
    monkeypatch.setenv("QFIELDCLOUD_PORT_OFFSET", "20")

    runner.invoke(cli.app, ["down", "--ref", "v1", "--cache-dir", str(tmp_path)])

    assert downed[0].https_port == 8563
