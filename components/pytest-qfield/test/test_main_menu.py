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
"""Plugins can add items to QField's main menu, ``mainMenu``.

The stand-in mirrors QField's items and icons, so a plugin can place its item
next to QField's own, found by icon since the labels are translated.
"""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from PyQt6.QtCore import QObject

    from pytest_qfield.qfieldbot import QFieldBot

PLUGIN_QML = """
import QtQuick
import QtQuick.Controls

Item {
    id: plugin

    property var menuItem: null

    function installMenuItem() {
        const menu = iface.findItemByObjectName("mainMenu");
        let settingsIndex = -1;
        for (let i = 0; i < menu.count && settingsIndex < 0; i++) {
            const item = menu.itemAt(i);
            if (item && item.icon && String(item.icon.source).indexOf("ic_tune_white_24dp") !== -1)
                settingsIndex = i;
        }
        const qfieldItem = menu.itemAt(settingsIndex);
        const item = menuItemComponent.createObject(menu.contentItem);
        item.font = qfieldItem.font;
        item.leftPadding = qfieldItem.leftPadding;
        item.icon.source = qfieldItem.icon.source;
        menu.insertItem(settingsIndex + 1, item);
        plugin.menuItem = item;
    }

    function removeMenuItem() {
        iface.findItemByObjectName("mainMenu").removeItem(plugin.menuItem);
        plugin.menuItem.destroy();
        plugin.menuItem = null;
    }

    function fail(kind) {
        if (kind === "error")
            throw new Error("broken");
        throw "plain text";
    }

    function add(a, b) {
        return {sum: a + b, list: [a, b]};
    }

    signal greeted(string name)
    property string lastGreeting: ""
    onGreeted: name => lastGreeting = name

    Component {
        id: menuItemComponent
        MenuItem {
            objectName: "pluginSettingsMenuItem"
            text: "Plugin settings"
            height: 48
        }
    }

    Connections {
        target: iface
        function onLoadProjectEnded() {
            plugin.installMenuItem();
        }
    }
}
"""


@pytest.fixture
def plugin(qfield_bot: "QFieldBot", tmp_path: "Path") -> "QFieldBot":
    qml_file = tmp_path / "menu_plugin.qml"
    qml_file.write_text(PLUGIN_QML)
    qfield_bot.show_window()
    qfield_bot.load_plugin(qml_file)
    return qfield_bot


def _items(qfield_bot: "QFieldBot", menu: "QObject") -> list["QObject"]:
    """Return the shown menu items in order, without separators and the undo row."""
    items = [
        qfield_bot.call_qml(menu, "itemAt", i) for i in range(menu.property("count"))
    ]
    return [item for item in items if item.property("text") and item.property("height")]


def _texts(qfield_bot: "QFieldBot", menu: "QObject") -> list[str]:
    return [item.property("text") for item in _items(qfield_bot, menu)]


def test_plugin_item_sits_under_qfield_settings(
    plugin: "QFieldBot", qfield_main_menu: "QObject"
) -> None:
    assert _texts(plugin, qfield_main_menu) == [
        "Plugin Manager",
        "Settings",
        "Plugin settings",
        "Message Log",
        "Lock Screen",
        "About QField",
    ]
    settings, plugin_item = _items(plugin, qfield_main_menu)[1:3]
    assert plugin_item.property("leftPadding") == settings.property("leftPadding")
    assert plugin_item.property("font") == settings.property("font")


def test_menu_items_are_visible_while_open(
    plugin: "QFieldBot", qfield_main_menu: "QObject"
) -> None:
    menu_item = plugin._get_plugin_root_object().property("menuItem")
    assert menu_item.property("visible") is False

    plugin.call_qml(qfield_main_menu, "open")
    plugin.qtbot.waitUntil(lambda: qfield_main_menu.property("opened"))

    assert menu_item.property("visible") is True


def test_plugin_removes_its_item(
    plugin: "QFieldBot", qfield_main_menu: "QObject"
) -> None:
    plugin.call_plugin("removeMenuItem")

    assert "Plugin settings" not in _texts(plugin, qfield_main_menu)


def test_call_plugin_returns_python_values(plugin: "QFieldBot") -> None:
    assert plugin.call_plugin("add", 1, 2) == {"sum": 3, "list": [1, 2]}


def test_call_plugin_emits_signals_once(plugin: "QFieldBot") -> None:
    greetings: list[str] = []
    plugin._get_plugin_root_object().greeted.connect(greetings.append)

    plugin.call_plugin("greeted", "QField")

    assert greetings == ["QField"]

    assert plugin._get_plugin_root_object().property("lastGreeting") == "QField"


def test_call_plugin_raises_for_unknown_names(plugin: "QFieldBot") -> None:
    with pytest.raises(AttributeError, match="missing"):
        plugin.call_plugin("missing")


@pytest.mark.parametrize(("kind", "message"), [("error", "broken"), ("text", "plain")])
def test_call_plugin_raises_when_the_function_throws(
    plugin: "QFieldBot", kind: str, message: str
) -> None:
    with pytest.raises(RuntimeError, match=message):
        plugin.call_plugin("fail", kind)
