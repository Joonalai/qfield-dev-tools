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

"""MCP server that starts real QField apps and lets an agent look and tap."""

from __future__ import annotations

import atexit
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from qfield_driver import actions
from qfield_driver.app import QFieldApp
from qfield_fetch import appimage

DEFAULT_VERSION = "4.2.9"
MAX_ITEMS = 400

INSTRUCTIONS = """\
Drives stock QField apps on private displays with isolated profiles.
Start with start_device, then item_tree to see what is on screen. Taps and
typing are real input events. eval_js runs a JS function body inside QField,
see the eval_js description for the names it sees. Coordinates for tap_map and
set_position are in the project CRS. Never ask for screenshots of camera views.
"""

server = MCPServer("qfield", instructions=INSTRUCTIONS)
devices: dict[str, QFieldApp] = {}
_work_dir = Path(tempfile.mkdtemp(prefix="qfield-mcp-"))


def _device(name: str) -> QFieldApp:
    try:
        return devices[name]
    except KeyError:
        msg = f"No device {name!r}, running: {sorted(devices)}"
        raise ValueError(msg) from None


@atexit.register
def _stop_all() -> None:
    for app in devices.values():
        app.close()
    devices.clear()
    shutil.rmtree(_work_dir, ignore_errors=True)


@server.tool()
def start_device(  # noqa: PLR0913
    *,
    name: str = "device",
    version: str = DEFAULT_VERSION,
    plugin_dir: str | None = None,
    project: str | None = None,
    grant_project_plugin: bool = False,
    settings: dict[str, Any] | None = None,
) -> str:
    """Start a QField with its own profile and display.

    :param version: QField release, `latest` for the newest
    :param plugin_dir: Plugin to load with its root reachable as `plugin`
    :param project: Project file to open after start
    :param grant_project_plugin: Answer the project plugin permission prompt
    :param settings: QSettings written before start, `{"myplugin/key": 1}`
    """
    if name in devices:
        msg = f"Device {name!r} is already running"
        raise ValueError(msg)
    app_run = appimage(version)
    app = QFieldApp(app_run, _work_dir / name, settings=settings)
    app.__enter__()
    devices[name] = app
    if plugin_dir:
        app.host_plugin(Path(plugin_dir).expanduser().resolve() / "main.qml")
    if project:
        actions.open_project(
            app,
            Path(project).expanduser().resolve(),
            grant_plugin=grant_project_plugin,
        )
    app.mark_log()
    return f"{name} running QField {version}, log at {app.log}"


@server.tool()
def stop_device(name: str = "device") -> str:
    """Stop a QField and remove it from the running devices."""
    _device(name).close()
    del devices[name]
    return f"{name} stopped"


@server.tool()
def list_devices() -> list[str]:
    """Names of the running devices."""
    return sorted(devices)


@server.tool()
def eval_js(code: str, device: str = "device") -> Any:  # noqa: ANN401
    """Run a JS function body in QField and return its JSON result.

    The body sees `iface`, `find` (iface.findItemByObjectName), `findItem`
    (search by objectName in the scene, popups and the hosted plugin), `search`,
    `walk`, `walkAll`, `scene`, `state` (kept between calls), `plugin`,
    `qgisProject`, `layerObserver`, `pluginManager`, `settings`,
    `platformUtilities`, `messageLogModel`, `featureHistory`, `flatLayerTree`,
    `trackingModel`, `LayerUtils`, `GeometryUtils`, `FeatureUtils`,
    `StringUtils` and `Theme`. Use `return` to get a value back.
    """
    return _device(device).eval(code)


ITEM_TREE_JS = """
const lines = [];
const root = __ROOT__;
const visit = (item, depth) => {
  if (!item || lines.length >= __MAX__ || depth > __DEPTH__) return;
  if (__VISIBLE_ONLY__ && item.visible === false) return;
  const type = String(item).split('(')[0];
  const parts = [type];
  if (item.objectName) parts.push('#' + item.objectName);
  const text = typeof item.text === 'string' && item.text;
  if (text) parts.push(JSON.stringify(text.slice(0, 60)));
  if (item.iconSource) parts.push('icon=' + String(item.iconSource).split('/').pop());
  if (typeof item.mapToGlobal === 'function' && item.width > 0 && item.height > 0) {
    const p = item.mapToGlobal(0, 0);
    parts.push('@' + Math.round(p.x) + ',' + Math.round(p.y)
      + ' ' + Math.round(item.width) + 'x' + Math.round(item.height));
  }
  if (item.objectName || text || !__NAMED_ONLY__) {
    lines.push('  '.repeat(depth) + parts.join(' '));
  }
  const kids = item.children || [];
  for (let i = 0; i < kids.length; i++) visit(kids[i], depth + 1);
  const content = item.contentItem;
  if (content && kids.indexOf(content) === -1) visit(content, depth + 1);
};
visit(root, 0);
if (lines.length >= __MAX__) lines.push('... truncated, narrow with root');
return lines.join('\\n');
"""


@server.tool()
def item_tree(
    *,
    device: str = "device",
    root: str | None = None,
    max_depth: int = 40,
    visible_only: bool = True,
    named_only: bool = True,
) -> str:
    """List items on screen as an indented tree.

    Each line has type, #objectName, text, icon, @x,y window position and size.
    Positions are tap targets.

    :param root: objectName of the item to start from, the whole window by default
    :param named_only: Only list items with an objectName or text
    """
    code = (
        ITEM_TREE_JS.replace(
            "__ROOT__", f"findItem({json.dumps(root)})" if root else "scene()"
        )
        .replace("__MAX__", str(MAX_ITEMS))
        .replace("__DEPTH__", str(max_depth))
        .replace("__VISIBLE_ONLY__", json.dumps(visible_only))
        .replace("__NAMED_ONLY__", json.dumps(named_only))
    )
    return _device(device).eval(code) or ""


@server.tool()
def tap(  # noqa: PLR0913
    *,
    device: str = "device",
    object_name: str | None = None,
    text: str | None = None,
    x: float | None = None,
    y: float | None = None,
    long_press: bool = False,
) -> str:
    """Tap an item by objectName or visible text, or a window position."""
    app = _device(device)
    if object_name:
        x, y = actions.center_of(app, actions.item_by_name(object_name))
    elif text:
        wanted = json.dumps(text)
        label = "typeof i.text === 'string' && i.visible && i.text.replace('&', '')"
        item = (
            f"(walk(scene(), i => {label} === {wanted}, 0)"
            f" || walk(scene(), i => {label} && i.text.includes({wanted}), 0))"
        )
        try:
            app.wait(f"return !!{item}", 5)
        except TimeoutError:
            msg = f"No visible item with text {text!r}"
            raise ValueError(msg) from None
        x, y = actions.center_of(app, item)
    if x is None or y is None:
        msg = "Give object_name, text, or x and y"
        raise ValueError(msg)
    if long_press:
        app.long_press(x, y)
    else:
        app.click(x, y)
    app.settle()
    return f"tapped at {round(x)},{round(y)}"


@server.tool()
def tap_map(
    x: float, y: float, *, device: str = "device", long_press: bool = False
) -> str:
    """Tap the map where a project CRS coordinate is drawn."""
    app = _device(device)
    sx, sy = actions.map_to_screen(app, x, y)
    if long_press:
        app.long_press(sx, sy)
    else:
        app.click(sx, sy)
    app.settle()
    return f"tapped map at window {round(sx)},{round(sy)}"


@server.tool()
def frame_map(
    x: float, y: float, half_size: float = 100, device: str = "device"
) -> str:
    """Show the map around a project CRS coordinate."""
    actions.frame_map(_device(device), x, y, half_size)
    return "framed"


@server.tool()
def type_text(text: str, device: str = "device") -> str:
    """Type into whatever has keyboard focus, tap a field first."""
    _device(device).type_text(text)
    return "typed"


@server.tool()
def key(name: str, device: str = "device") -> str:
    """Press one key by keysym name: Return, Escape, BackSpace, Tab."""
    _device(device).key(name)
    return f"pressed {name}"


CAMERA_OPEN_JS = """
const camera = /Camera|QRCodeReader|CodeReader/;
return walkAll(scene(), i => i.visible && camera.test(String(i)), 0).length > 0;
"""


@server.tool()
def screenshot(device: str = "device") -> Image:
    """Take a PNG of the whole window. Refused while a camera view is open."""
    app = _device(device)
    if app.eval(CAMERA_OPEN_JS):
        msg = "A camera view is open, close it before a screenshot"
        raise ValueError(msg)
    path = app.screenshot(app.home.parent / f"{device}-screenshot.png")
    data = path.read_bytes()
    path.unlink()
    return Image(data=data, format="png")


@server.tool()
def messages(
    device: str = "device", tag: str | None = None, last: int = 30
) -> list[str]:
    """Newest messages of QField's message log, what iface.logMessage writes."""
    return actions.log_messages(_device(device), tag)[:last]


@server.tool()
def log(device: str = "device") -> str:
    """QField's stdout and stderr since the previous call."""
    app = _device(device)
    lines = app.new_log_lines()
    app.mark_log()
    return "\n".join(lines[-200:])


@server.tool()
def open_project(
    path: str, *, device: str = "device", grant_project_plugin: bool = False
) -> str:
    """Open a project file."""
    actions.open_project(
        _device(device),
        Path(path).expanduser().resolve(),
        grant_plugin=grant_project_plugin,
    )
    return "opened"


@server.tool()
def set_position(x: float, y: float, device: str = "device") -> str:
    """Feed a GNSS fix at a project CRS coordinate through a fake receiver."""
    app = _device(device)
    app.set_position(x, y)
    app.wait_for_position(x, y)
    return "positioned"


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
