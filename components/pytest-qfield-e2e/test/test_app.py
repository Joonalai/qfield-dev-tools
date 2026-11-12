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

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from qfield_driver import actions
from qfield_driver.app import DriverError, QFieldApp

pytestmark = pytest.mark.qfield_app

POINTS = "points"


def test_eval_returns_json_values(qfield_app: QFieldApp) -> None:
    assert qfield_app.eval("return 1 + 1") == 2
    assert qfield_app.eval("return 'a' + 'b'") == "ab"
    assert qfield_app.eval("return [1, {a: true}]") == [1, {"a": True}]
    assert qfield_app.eval("return undefined") is None
    assert qfield_app.eval("return typeof iface.mainWindow()") == "object"


def test_eval_errors_raise(qfield_app: QFieldApp) -> None:
    with pytest.raises(DriverError, match="boom"):
        qfield_app.eval("throw new Error('boom')")


def test_state_survives_between_calls(qfield_app: QFieldApp) -> None:
    qfield_app.eval("state.value = 42;")
    assert qfield_app.eval("return state.value") == 42


def test_open_project_and_read_features(
    qfield_app: QFieldApp, project_file: Path
) -> None:
    actions.open_project(qfield_app, project_file)

    assert qfield_app.eval("return qgisProject.fileName") == str(project_file)
    assert actions.feature_count(qfield_app, POINTS) > 0


def test_hosted_plugin_root_and_real_tap(
    qfield_app: QFieldApp, simple_plugin: Path, project_file: Path
) -> None:
    actions.open_project(qfield_app, project_file)
    qfield_app.host_plugin(simple_plugin / "main.qml")

    assert qfield_app.eval("return plugin.mainWindow === iface.mainWindow()")
    actions.tap_object(qfield_app, "pluginButton")

    actions.wait_for_message(qfield_app, "Plugin button clicked!")


def test_app_plugin_installs_for_real(
    qfield_app_factory: Callable[..., QFieldApp],
    simple_plugin: Path,
    project_file: Path,
) -> None:
    app = qfield_app_factory(app_plugins={"simple_plugin": simple_plugin})
    actions.wait_for_item(app, "pluginButton")

    actions.open_project(app, project_file)

    actions.wait_for_message(app, "Project load ended")


def test_fake_gnss_position(qfield_app: QFieldApp, project_file: Path) -> None:
    actions.open_project(qfield_app, project_file)
    x, y = 385000.0, 6672000.0

    qfield_app.set_position(x, y)

    qfield_app.wait_for_position(x, y)
    qfield_app.set_position(x + 10, y)
    qfield_app.wait_for_position(x + 10, y)
    qfield_app.lose_position()
    qfield_app.set_position(x, y)
    qfield_app.wait_for_position(x, y)


def test_typing_reaches_a_text_field(qfield_app: QFieldApp) -> None:
    qfield_app.eval("""
      state.field = Qt.createQmlObject(
        'import QtQuick.Controls; TextField { objectName: "typed"; width: 300 }',
        iface.mainWindow().contentItem);
    """)

    actions.type_into(qfield_app, "typed", "Hellö wörld 1.5")

    time.sleep(0.3)
    assert actions.item_property(qfield_app, "typed", "text") == "Hellö wörld 1.5"
