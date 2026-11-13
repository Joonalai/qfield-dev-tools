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

from pytest_qfield_e2e.cloud import PORT_OFFSET_ENV, port_offset

pytest_plugins = ["pytester"]

CONFTEST = """
import pytest
from qfield_driver.cloud.stack import QFieldCloudStack

@pytest.fixture(scope="session")
def qfieldcloud_ref():
    return "v1"

@pytest.fixture(autouse=True, scope="session")
def _no_docker():
    QFieldCloudStack.up = lambda self: None
"""

TEST = """
def test_ports(qfieldcloud_stack):
    assert qfieldcloud_stack.https_port == 8543 + 7
    assert qfieldcloud_stack.postgres_port == 8432 + 7
    assert qfieldcloud_stack.project_name.endswith("_v1-7")
"""


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PORT_OFFSET_ENV, raising=False)


class IniConfig:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def getini(self, name: str) -> str:
        assert name == "qfieldcloud_port_offset"
        return self.value


def test_offset_defaults_to_zero() -> None:
    assert port_offset(IniConfig()) == 0  # type: ignore[arg-type]


def test_offset_comes_from_ini() -> None:
    assert port_offset(IniConfig("3")) == 3  # type: ignore[arg-type]


def test_env_wins_over_ini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PORT_OFFSET_ENV, "9")

    assert port_offset(IniConfig("3")) == 9  # type: ignore[arg-type]


def test_stack_fixture_applies_the_offset(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PORT_OFFSET_ENV, "7")
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(TEST)

    result = pytester.runpytest_subprocess(
        "-p", "no:pytest-qfield", "-p", "no:pytest_qgis", "-p", "no:pytest-qt"
    )

    result.assert_outcomes(passed=1)
