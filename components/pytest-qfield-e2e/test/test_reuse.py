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

from pathlib import Path

import pytest

from pytest_qfield_e2e.cloud import worker_username
from qfield_driver import actions
from qfield_driver.app import BINARY_ENV, QFieldApp, local_app
from qfield_fetch import CACHE_ENV
from qfield_fetch.pytest_plugin import VERSION_ENV

pytest_plugins = ["pytester"]
pytestmark = pytest.mark.qfield_app

INNER_ARGS = ("-p", "no:pytest-qfield", "-p", "no:pytest_qgis", "-p", "no:pytest-qt")


@pytest.fixture
def inner_pytester(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    qfield_fetch_cache_dir: Path,
    qfield_app_version: str,
) -> pytest.Pytester:
    """Pytester whose runs use the outer QField, its HOME has no cache."""
    monkeypatch.setenv(CACHE_ENV, str(qfield_fetch_cache_dir))
    monkeypatch.setenv(VERSION_ENV, qfield_app_version)
    return pytester


def test_reset_clears_project_plugin_popups_and_state(
    qfield_app: QFieldApp, simple_plugin: Path, project_file: Path
) -> None:
    actions.open_project(qfield_app, project_file)
    qfield_app.host_plugin(simple_plugin / "main.qml")
    qfield_app.set_position(385000.0, 6672000.0)
    qfield_app.eval("""
      state.popup = Qt.createQmlObject(
        'import QtQuick.Controls; Popup { width: 100; height: 100 }',
        iface.mainWindow().contentItem);
      state.popup.open();
      state.loadHooked = true;
    """)
    qfield_app.wait("return state.popup.opened")

    qfield_app.reset()

    assert qfield_app.eval("""
      return [qgisProject.fileName, plugin === null, Object.keys(state),
              find('positionSource').active];
    """) == ["", True, ["loadHooked"], False]


def test_reload_plugin_loads_edited_imports(
    qfield_app: QFieldApp, tmp_path: Path
) -> None:
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "main.qml").write_text(
        'import QtQuick\nimport "answer.js" as Answer\n'
        "Item { property int answer: Answer.value() }\n"
    )
    (plugin / "answer.js").write_text("function value() { return 1; }\n")
    qfield_app.host_plugin(plugin / "main.qml")

    (plugin / "answer.js").write_text("function value() { return 2; }\n")
    qfield_app.reload_plugin()

    assert qfield_app.plugin_property("answer") == 2


def test_diagnose_saves_a_screenshot(qfield_app: QFieldApp, tmp_path: Path) -> None:
    report = qfield_app.diagnose(tmp_path, "device")

    assert "message log" in report
    assert (tmp_path / "device-failure.png").read_bytes().startswith(b"\x89PNG")


def test_failure_report_shows_the_device(inner_pytester: pytest.Pytester) -> None:
    inner_pytester.makepyfile("""
        def test_fails(qfield_app):
            assert qfield_app.eval("return 1") == 2
    """)

    result = inner_pytester.runpytest_subprocess(*INNER_ARGS)

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*QField device*", "*screenshot: *failure.png*"])


def test_reuse_hands_out_the_running_device_reset(
    inner_pytester: pytest.Pytester,
) -> None:
    inner_pytester.makepyfile("""
        def test_first(qfield_app):
            qfield_app.eval("state.left = 1")
            open("pid", "w").write(str(qfield_app.process_groups["qfield"]))

        def test_second(qfield_app):
            assert qfield_app.eval("return Object.keys(state)") == []
            assert open("pid").read() == str(qfield_app.process_groups["qfield"])
    """)

    result = inner_pytester.runpytest_subprocess(*INNER_ARGS, "--qfield-app-reuse")

    result.assert_outcomes(passed=2)


def test_worker_usernames(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert worker_username("alice") == "alice"
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    assert worker_username("alice") == "alice_gw1"
    assert worker_username("alice_gw1") == "alice_gw1"


def test_own_binary_is_used_instead_of_a_release(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "qfield"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setenv(BINARY_ENV, str(binary))
    pytester.makepyfile("""
        def test_binary(qfield_app_binary):
            print("binary", qfield_app_binary)
    """)

    result = pytester.runpytest_subprocess(*INNER_ARGS, "-s")

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([f"*binary {binary}"])


def test_own_binary_must_be_executable(tmp_path: Path) -> None:
    (tmp_path / "qfield").write_text("")

    with pytest.raises(FileNotFoundError, match="Not an executable QField"):
        local_app(tmp_path / "qfield")
