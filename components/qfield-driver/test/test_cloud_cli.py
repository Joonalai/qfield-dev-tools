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
from typer.testing import CliRunner

from qfield_driver.cloud import cli

runner = CliRunner()


@pytest.fixture(autouse=True)
def _hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "hosted_ref", lambda: "v26.30")


def test_check_passes_when_the_pin_is_hosted() -> None:
    result = runner.invoke(cli.app, ["ref", "--check", "v26.30"])

    assert result.exit_code == 0
    assert "pinned v26.30, hosted v26.30" in result.output


def test_check_exits_1_on_drift() -> None:
    result = runner.invoke(cli.app, ["ref", "--check", "v26.29"])

    assert result.exit_code == 1
    assert "pinned v26.29, hosted v26.30" in result.output


def test_plain_ref_prints_the_resolved_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "resolve_ref", lambda ref: f"resolved-{ref}")

    result = runner.invoke(cli.app, ["ref", "--ref", "latest"])

    assert result.output == "resolved-latest\n"
