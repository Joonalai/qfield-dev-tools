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
NEW_POINT = (385000.0, 6672000.0)


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


@pytest.fixture
def qfield_app_settings() -> dict[str, object]:
    return {"pytest/answer": 42, "pytest/text": 'a, "b" c:\\d'}


def test_settings_are_seeded(qfield_app: QFieldApp) -> None:
    assert qfield_app.eval("return Number(settings.value('pytest/answer', 0))") == 42
    assert qfield_app.eval("return settings.value('pytest/text', '')") == 'a, "b" c:\\d'


def test_first_run_intros_stay_closed(
    qfield_app_factory: Callable[..., QFieldApp],
) -> None:
    # A device of its own, a reused one may have opened the dashboard before.
    app = qfield_app_factory("intros")
    assert not app.eval("return settings.valueBool('/QField/showDashboardGuide', true)")

    app.eval("find('dashBoard').open();")
    actions.wait_visible(app, "dashBoard")
    time.sleep(1)

    assert not actions.is_visible(app, "dashboardTour")


def test_device_restarts_on_its_profile(
    qfield_app_factory: Callable[..., QFieldApp],
) -> None:
    qfield_app_factory("again").close()

    assert qfield_app_factory("again").eval("return 1") == 1


def test_screenshot_overwrites(qfield_app: QFieldApp, tmp_path: Path) -> None:
    path = tmp_path / "shot.png"
    path.write_bytes(b"stale")

    qfield_app.screenshot(path)

    assert path.read_bytes().startswith(b"\x89PNG")


def test_add_feature_and_change_geometry(
    qfield_app: QFieldApp, project_file: Path
) -> None:
    actions.open_project(qfield_app, project_file)
    before = actions.feature_count(qfield_app, POINTS)

    actions.add_feature(
        qfield_app, POINTS, "Point (385000 6672000)", {"text_field": "added"}
    )
    actions.change_geometry(
        qfield_app, POINTS, "text_field = 'added'", "Point (385010 6672000)"
    )

    assert actions.feature_count(qfield_app, POINTS) == before + 1
    assert actions.geometries(qfield_app, POINTS, "text_field = 'added'") == [
        "Point (385010 6672000)"
    ]


def test_digitize_point_adds_a_feature(
    qfield_app: QFieldApp, project_file: Path
) -> None:
    actions.open_project(qfield_app, project_file)
    before = actions.feature_count(qfield_app, POINTS)
    actions.frame_map(qfield_app, *NEW_POINT, 100)

    actions.digitize_point(qfield_app, POINTS, NEW_POINT, "text_field", "digitized")

    assert actions.feature_count(qfield_app, POINTS) == before + 1
    assert actions.feature_count(qfield_app, POINTS, "text_field = 'digitized'") == 1


def test_form_of_a_new_feature_is_found_and_saved(
    qfield_app: QFieldApp, project_file: Path
) -> None:
    actions.open_project(qfield_app, project_file)
    before = actions.feature_count(qfield_app, POINTS)
    actions.frame_map(qfield_app, *NEW_POINT, 100)
    actions.set_active_layer(qfield_app, POINTS)
    qfield_app.eval("iface.mainWindow().changeMode('digitize');")
    qfield_app.wait("return find('stateMachine').state === 'digitize'", 10)
    actions.tap_map(qfield_app, *NEW_POINT)
    qfield_app.wait("return find('overlayFeatureFormDrawer').opened", 15)

    assert actions.current_form(qfield_app) == actions.OVERLAY_FORM
    actions.set_field(
        qfield_app, "text_field", "overlay", actions.current_form(qfield_app)
    )
    actions.save_open_form(qfield_app)

    assert actions.feature_count(qfield_app, POINTS, "text_field = 'overlay'") == 1
    assert actions.feature_count(qfield_app, POINTS) == before + 1


def test_open_form_finds_the_form_of_an_existing_feature(
    qfield_app: QFieldApp, project_file: Path
) -> None:
    actions.open_project(qfield_app, project_file)
    actions.open_feature_form(qfield_app, POINTS, "text_field = 'test'")

    assert actions.current_form(qfield_app) == actions.FEATURE_FORM
    actions.set_field(
        qfield_app, "text_field", "edited", actions.current_form(qfield_app)
    )
    actions.save_open_form(qfield_app)

    assert actions.feature_count(qfield_app, POINTS, "text_field = 'edited'") == 1


def test_delete_feature_through_the_form_menu(
    qfield_app: QFieldApp, project_file: Path
) -> None:
    actions.open_project(qfield_app, project_file)
    before = actions.feature_count(qfield_app, POINTS)

    actions.delete_feature(qfield_app, POINTS, "text_field = 'test'")

    assert actions.feature_count(qfield_app, POINTS) == before - 1
    assert actions.feature_count(qfield_app, POINTS, "text_field = 'test'") == 0


def test_find_item_reaches_plugin_popups(qfield_app: QFieldApp, tmp_path: Path) -> None:
    plugin = tmp_path / "popup_plugin"
    plugin.mkdir()
    (plugin / "main.qml").write_text("""
import QtQuick
import QtQuick.Controls

Item {
  property int opened: 0
  Popup {
    objectName: "pluginPopup"
    parent: iface.mainWindow().contentItem
    contentItem: Button { objectName: "popupButton"; text: "Hit" }
  }
}
""")
    qfield_app.host_plugin(plugin / "main.qml")

    assert "pluginPopup" in qfield_app.eval("return String(findItem('pluginPopup'))")
    assert qfield_app.eval("return findItem('popupButton').text") == "Hit"


def test_evaluate_expression(qfield_app: QFieldApp, project_file: Path) -> None:
    actions.open_project(qfield_app, project_file)

    assert actions.evaluate_expression(qfield_app, "1 + 2") == "3"
    assert actions.evaluate_expression(qfield_app, "@layer_name", POINTS) == POINTS


def test_files_load_from_paths_with_url_characters(
    qfield_app: QFieldApp, tmp_path: Path
) -> None:
    directory = tmp_path / "a #1%"
    directory.mkdir()
    (directory / "main.qml").write_text(
        "import QtQuick\nItem { property int answer: 42 }\n"
    )
    (directory / "lib.mjs").write_text("export function twice(x) { return 2 * x; }\n")

    qfield_app.host_plugin(directory / "main.qml")
    actions.import_js(qfield_app, directory / "lib.mjs", "lib")

    assert qfield_app.plugin_property("answer") == 42
    assert qfield_app.eval("return state.lib.call('twice', [2])") == 4


def test_device_names_are_unique_within_a_test(
    qfield_app_factory: Callable[..., QFieldApp],
) -> None:
    qfield_app_factory("phone")

    with pytest.raises(ValueError, match="already running"):
        qfield_app_factory("phone")
