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
import functools
import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from qfield_driver import actions
from qfield_driver.app import BINARY_ENV, QFieldApp, local_app
from qfield_fetch import appimage, default_cache_dir
from qfield_mcp.devices import Devices, clean_orphans

if TYPE_CHECKING:
    from collections.abc import Callable

    from qfield_driver.cloud.client import QFieldCloudClient
    from qfield_driver.cloud.stack import QFieldCloudStack

LOGGER = logging.getLogger(__name__)
DEFAULT_VERSION = "4.2.9"
MAX_ITEMS = 300
PORT_OFFSET_ENV = "QFIELDCLOUD_PORT_OFFSET"
NO_STACK = (
    "This server knows no local QFieldCloud. Start one with cloud_up, or use one"
    " that runs with cloud_attach, which is also needed after a server restart."
)

INSTRUCTIONS = """\
Drives stock QField apps on private displays with isolated profiles.
Start with start_device, then find_items or item_tree to see what is on screen.
Taps and typing are real input events, use wait_for after actions that animate
or load. eval_js runs a JS function body inside QField, see its description for
the names it sees. Coordinates for tap_map and set_position are in the project
CRS. Never ask for screenshots of camera views.
"""

server = MCPServer("qfield", instructions=INSTRUCTIONS)
# The local QFieldCloud that cloud_up started last, and logged in clients of it.
_stack: QFieldCloudStack | None = None
_clients: dict[tuple[str, str, str | None], QFieldCloudClient] = {}
devices = Devices()
atexit.register(devices.stop_all)


def tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Register a tool whose errors reach the agent with their message.

    MCP hides the message of anything but a ToolError.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as error:
            msg = f"{type(error).__name__}: {error}"
            raise ToolError(msg) from error

    server.tool()(wrapper)
    return wrapper


# Devices


def _app_run(version: str | None) -> Path:
    local = os.environ.get(BINARY_ENV) if version is None else None
    if not local:
        return appimage(version or DEFAULT_VERSION)
    try:
        return local_app(local)
    except FileNotFoundError as error:
        msg = (
            f"{error} (from ${BINARY_ENV} of the server's environment). "
            f"Pass `version` to run a release instead, or fix or unset ${BINARY_ENV}."
        )
        raise FileNotFoundError(msg) from error


@tool
def start_device(  # noqa: PLR0913
    *,
    name: str = "device",
    version: str | None = None,
    plugin_dir: str | None = None,
    project: str | None = None,
    grant_project_plugin: bool = False,
    settings: dict[str, Any] | None = None,
) -> str:
    """Start a QField with its own profile and display.

    :param version: QField release, `latest` for the newest. Without it the
        server's `$QFIELD_APP_BINARY` runs if set, else 4.2.9
    :param plugin_dir: Plugin to load with its root reachable as `plugin`
    :param project: Project file to open after start
    :param grant_project_plugin: Answer the project plugin permission prompt
    :param settings: QSettings written before start, `{"myplugin/key": 1}`
    """
    lock = devices.reserve(name)
    try:
        app_run = _app_run(version)
        app = QFieldApp(app_run, devices.work_dir / name, settings=settings)
        app.__enter__()
        try:
            devices.add(name, app)
            if plugin_dir:
                app.host_plugin(Path(plugin_dir).expanduser().resolve() / "main.qml")
            if project:
                actions.open_project(
                    app,
                    Path(project).expanduser().resolve(),
                    grant_plugin=grant_project_plugin,
                )
            app.mark_log()
        except Exception:
            app.close()
            raise
    except Exception:
        devices.forget(name)
        raise
    finally:
        lock.release()
    return f"{name} running {app_run}, log at {app.log}"


@tool
def stop_device(*, name: str = "device") -> str:
    """Stop a QField and remove it from the running devices."""
    devices.stop(name)
    return f"{name} stopped"


@tool
def list_devices() -> list[str]:
    """Names of the running devices."""
    return devices.names()


@tool
def reload_plugin(*, device: str = "device") -> str:
    """Load the hosted plugin again from its directory, edits included."""
    with devices.use(device) as app:
        app.reload_plugin()
    return "reloaded"


# Looking


@tool
def eval_js(code: str, *, device: str = "device") -> Any:  # noqa: ANN401
    """Run a JS function body in QField and return its JSON result.

    The body sees `iface`, `find` (iface.findItemByObjectName), `findItem`
    (search by objectName in the scene, popups and the hosted plugin), `search`,
    `walk`, `walkAll`, `scene`, `state` (kept between calls), `plugin`,
    `qgisProject`, `layerObserver`, `pluginManager`, `settings`,
    `platformUtilities`, `messageLogModel`, `featureHistory`, `flatLayerTree`,
    `trackingModel`, `LayerUtils`, `GeometryUtils`, `FeatureUtils`,
    `StringUtils` and `Theme`. Use `return` to get a value back.

    QML exposes less of the QGIS API than PyQGIS. `qgisProject.mapLayers()` and
    `QgsFields.at()` do not exist, use
    `qgisProject.mapLayersByName('points')[0].fields.names` instead.
    """
    with devices.use(device) as app:
        return app.eval(code)


# Shared by item_tree and find_items, `describe` gives one line for an item.
ITEMS_JS = """
const clickable = i => typeof i.clicked === 'function'
  || typeof i.pressAndHold === 'function';
const textOf = i => typeof i.text === 'string' && i.text;
const describe = i => {
  const parts = [String(i).split('(')[0]];
  if (i.objectName) parts.push('#' + i.objectName);
  const text = textOf(i);
  if (text) parts.push(JSON.stringify(text.slice(0, 60)));
  if (i.iconSource) parts.push('icon=' + String(i.iconSource).split('/').pop());
  if (clickable(i)) parts.push('[clickable]');
  if (typeof i.mapToGlobal === 'function' && i.width > 0 && i.height > 0) {
    const p = i.mapToGlobal(0, 0);
    parts.push('@' + Math.round(p.x) + ',' + Math.round(p.y)
      + ' ' + Math.round(i.width) + 'x' + Math.round(i.height));
  }
  return parts.join(' ');
};
const lines = [];
const visit = (item, depth, keep, indent) => {
  if (!item || lines.length >= __MAX__ || depth > __DEPTH__) return;
  if (__VISIBLE_ONLY__ && item.visible === false) return;
  if (keep(item)) lines.push((indent ? '  '.repeat(depth) : '') + describe(item));
  const kids = item.children || [];
  for (let i = 0; i < kids.length; i++) visit(kids[i], depth + 1, keep, indent);
  const content = item.contentItem;
  if (content && kids.indexOf(content) === -1) visit(content, depth + 1, keep, indent);
};
"""


def _items_code(  # noqa: PLR0913
    root: str | None,
    keep: str,
    *,
    indent: bool,
    max_items: int,
    max_depth: int,
    visible_only: bool,
    result: str = "lines.join('\\n')",
) -> str:
    start = f"findItem({json.dumps(root)})" if root else "scene()"
    return (
        ITEMS_JS.replace("__MAX__", str(max_items))
        .replace("__DEPTH__", str(max_depth))
        .replace("__VISIBLE_ONLY__", json.dumps(visible_only))
        + f"""
const root = {start};
if (!root) throw new Error('No item ' + {json.dumps(root)});
visit(root, 0, {keep}, {json.dumps(indent)});
if (lines.length >= {max_items}) lines.push('... more, narrow with root or a query');
return {result};
"""
    )


@tool
def item_tree(  # noqa: PLR0913
    *,
    device: str = "device",
    root: str | None = None,
    max_depth: int = 40,
    max_items: int = MAX_ITEMS,
    visible_only: bool = True,
    named_only: bool = True,
    clickable_only: bool = False,
) -> str:
    """List items on screen as an indented tree.

    Each line has type, #objectName, text, icon, [clickable], @x,y window
    position and size. Positions are tap targets.

    :param root: objectName of the item to start from, the whole window by default
    :param named_only: Only list items with an objectName or text
    :param clickable_only: Only list items that react to taps
    """
    conditions = []
    if named_only:
        conditions.append("(i.objectName || textOf(i))")
    if clickable_only:
        conditions.append("clickable(i)")
    keep = f"i => {' && '.join(conditions) or 'true'}"
    code = _items_code(
        root,
        keep,
        indent=True,
        max_items=max_items,
        max_depth=max_depth,
        visible_only=visible_only,
    )
    with devices.use(device) as app:
        return app.eval(code) or ""


@tool
def find_items(
    query: str,
    *,
    device: str = "device",
    clickable_only: bool = False,
    max_items: int = 50,
) -> str:
    """Find visible items whose objectName, text or icon contains `query`.

    Case is ignored, and items are listed one per line as in item_tree.
    """
    needle = json.dumps(query.lower())
    keep = (
        "i => [i.objectName, textOf(i), i.iconSource && String(i.iconSource)]"
        f".some(v => v && String(v).toLowerCase().includes({needle}))"
    )
    if clickable_only:
        keep += " && clickable(i)"
    code = _items_code(
        None, keep, indent=False, max_items=max_items, max_depth=60, visible_only=True
    )
    with devices.use(device) as app:
        return app.eval(code) or f"No visible item matches {query!r}"


@tool
def wait_for(
    *,
    device: str = "device",
    js: str | None = None,
    text: str | None = None,
    gone: bool = False,
    timeout: float = 10,
) -> str:
    """Wait until a JS function body returns something truthy, or text shows.

    With `text`, waits until an item with the text is visible.

    :param gone: Wait for the text to disappear instead
    """
    if text is not None:
        js = _items_code(
            None,
            f"i => textOf(i) && i.text.includes({json.dumps(text)})",
            indent=False,
            max_items=1,
            max_depth=60,
            visible_only=True,
            result="lines.length === 0" if gone else "lines.length > 0",
        )
    if js is None:
        msg = "Give js or text"
        raise ValueError(msg)
    with devices.use(device) as app:
        started = time.monotonic()
        try:
            result = app.wait(js, timeout)
        except TimeoutError:
            msg = f"Still not true after {timeout} s"
            raise ValueError(msg) from None
    return f"true after {time.monotonic() - started:.1f} s: {json.dumps(result)[:200]}"


@tool
def screenshot(
    *, device: str = "device", object_name: str | None = None, scale: float = 1
) -> Image:
    """Take a PNG of the window, or of one item. Refused while a camera is open.

    :param scale: Size factor, 0.5 gives a quarter of the pixels
    """
    with devices.use(device) as app:
        if app.camera_open():
            msg = "A camera view is open, close it before a screenshot"
            raise ValueError(msg)
        item = f"findItem({json.dumps(object_name)})" if object_name else "scene()"
        path = app.screenshot(
            app.home.parent / f"{device}-screenshot.png", item=item, scale=scale
        )
        data = path.read_bytes()
        path.unlink()
    return Image(data=data, format="png")


@tool
def messages(
    *, device: str = "device", tag: str | None = None, last: int = 30
) -> list[str]:
    """Newest messages of QField's message log, what iface.logMessage writes."""
    with devices.use(device) as app:
        return actions.log_messages(app, tag)[:last]


@tool
def log(*, device: str = "device") -> str:
    """QField's stdout and stderr since the previous call."""
    with devices.use(device) as app:
        lines = app.new_log_lines()
        app.mark_log()
    return "\n".join(lines[-200:])


# Input


@tool
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
    with devices.use(device) as app:
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


@tool
def tap_map(
    x: float, y: float, *, device: str = "device", long_press: bool = False
) -> str:
    """Tap the map where a project CRS coordinate is drawn."""
    with devices.use(device) as app:
        sx, sy = actions.map_to_screen(app, x, y)
        if long_press:
            app.long_press(sx, sy)
        else:
            app.click(sx, sy)
        app.settle()
    return f"tapped map at window {round(sx)},{round(sy)}"


@tool
def frame_map(
    x: float, y: float, *, half_size: float = 100, device: str = "device"
) -> str:
    """Show the map around a project CRS coordinate."""
    with devices.use(device) as app:
        actions.frame_map(app, x, y, half_size)
    return "framed"


@tool
def type_text(text: str, *, device: str = "device") -> str:
    """Type into whatever has keyboard focus, tap a field first."""
    with devices.use(device) as app:
        app.type_text(text)
    return "typed"


@tool
def key(name: str, *, device: str = "device") -> str:
    """Press one key by keysym name: Return, Escape, BackSpace, Tab."""
    with devices.use(device) as app:
        app.key(name)
    return f"pressed {name}"


# Projects and features


@tool
def open_project(
    path: str, *, device: str = "device", grant_project_plugin: bool = False
) -> str:
    """Open a project file."""
    with devices.use(device) as app:
        actions.open_project(
            app, Path(path).expanduser().resolve(), grant_plugin=grant_project_plugin
        )
    return "opened"


@tool
def set_position(x: float, y: float, *, device: str = "device") -> str:
    """Feed a GNSS fix at a project CRS coordinate through a fake receiver."""
    with devices.use(device) as app:
        app.set_position(x, y)
        app.wait_for_position(x, y)
    return "positioned"


@tool
def features(
    layer: str,
    fields: list[str],
    *,
    expression: str = "",
    device: str = "device",
) -> list[dict[str, Any]]:
    """Attribute values of a layer's features, filtered by a QGIS expression."""
    with devices.use(device) as app:
        return actions.features(app, layer, fields, expression)


@tool
def open_feature_form(
    layer: str, expression: str, *, device: str = "device", edit: bool = True
) -> str:
    """Open the form of the first feature matching a QGIS expression."""
    with devices.use(device) as app:
        actions.open_feature_form(app, layer, expression, edit=edit)
    return "form open"


@tool
def set_field(label: str, value: Any, *, device: str = "device") -> str:  # noqa: ANN401
    """Change a field of the open feature form through its editor widget.

    Works on the form of an existing feature and on the form of a feature that
    digitizing just added, whichever is open.

    :param label: The field's alias, its name when it has none
    """
    with devices.use(device) as app:
        actions.set_field(app, label, value, actions.current_form(app))
    return "set"


@tool
def save_form(*, device: str = "device") -> str:
    """Save the open feature form, a digitized feature's form too."""
    with devices.use(device) as app:
        actions.save_open_form(app)
    return "saved"


@tool
def close_feature_form(*, device: str = "device") -> str:
    """Close the feature form and list without saving."""
    with devices.use(device) as app:
        actions.close_feature_form(app)
    return "closed"


@tool
def delete_feature(layer: str, expression: str, *, device: str = "device") -> str:
    """Delete the first feature matching a QGIS expression, as a user would.

    Opens its form, taps the form menu, `Delete Feature` and `OK`.
    """
    with devices.use(device) as app:
        actions.delete_feature(app, layer, expression)
    return "deleted"


@tool
def set_active_layer(layer: str, *, device: str = "device") -> str:
    """Make a layer the one that digitizing adds features to."""
    with devices.use(device) as app:
        actions.set_active_layer(app, layer)
    return "active"


@tool
def digitize_point(  # noqa: PLR0913
    layer: str,
    x: float,
    y: float,
    label: str,
    value: Any,  # noqa: ANN401
    *,
    device: str = "device",
) -> str:
    """Add a point by tapping the map in digitize mode, fill one field and save.

    The point must be on screen, use frame_map first. To fill several fields,
    switch to digitize mode with eval_js, use tap_map, set_field and save_form.

    :param x: Project CRS coordinate
    :param label: The field to fill, its alias, its name when it has none
    """
    with devices.use(device) as app:
        actions.digitize_point(app, layer, (x, y), label, value)
    return "added"


@tool
def add_feature(
    layer: str,
    attributes: dict[str, Any],
    *,
    wkt: str | None = None,
    device: str = "device",
) -> str:
    """Add a feature and commit it, as plugin JS does, without any form.

    :param wkt: Geometry in the layer's CRS, `Point (385000 6672000)`
    :param attributes: Values by field name
    """
    with devices.use(device) as app:
        actions.add_feature(app, layer, wkt, attributes)
    return "added"


@tool
def change_geometry(
    layer: str, expression: str, wkt: str, *, device: str = "device"
) -> str:
    """Replace the geometry of the first feature matching an expression and save.

    :param wkt: New geometry in the layer's CRS
    """
    with devices.use(device) as app:
        actions.change_geometry(app, layer, expression, wkt)
    return "changed"


# QFieldCloud


@tool
def cloud_up(
    *,
    ref: str | None = None,
    port_offset: int | None = None,
    name: str | None = None,
) -> str:
    """Start a local QFieldCloud of a release and return its URL.

    The first start of a release builds images, which takes many minutes. To use
    a stack that already runs, see cloud_attach.

    :param ref: `hosted` (what app.qfield.cloud runs), `latest` or a tag. Without
        it the server's `$QFIELDCLOUD_SOURCE_DIR` checkout runs if set, else hosted
    :param port_offset: Move every port and the compose project up by this much,
        so stacks of parallel checkouts do not collide. Without it
        `$QFIELDCLOUD_PORT_OFFSET` or 0
    :param name: Compose project name instead of the one derived from the release
    """
    stack = _make_stack(ref, port_offset, name, None)
    if stack.runs_here() and not stack.env_file.exists():
        msg = (
            f"Compose project {stack.project_name} runs, but this server did not"
            " configure it, starting it again would recreate its containers with"
            " other ports. Use cloud_attach to work with it."
        )
        raise ValueError(msg)
    stack.up()
    return _use_stack(stack)


@tool
def cloud_attach(
    *,
    ref: str | None = None,
    port_offset: int | None = None,
    name: str | None = None,
    https_port: int | None = None,
) -> str:
    """Use a local QFieldCloud that already runs, without building or starting it.

    Give what cloud_up was given, or the compose project `name` and `https_port`
    of a stack some other run started, such as an e2e run's. Use it after the
    server restarted too, the stack keeps running meanwhile. The admin tools and
    cloud_login then use this stack.
    """
    stack = _make_stack(ref, port_offset, name, https_port)
    if not stack.is_up():
        msg = (
            f"No QFieldCloud answers at {stack.url} with the certificate of release"
            f" {stack.ref}. Check that `ref` is the release the stack runs from"
            " and its checkout exists, and check https_port and port_offset, or"
            " start it with cloud_up."
        )
        raise ValueError(msg)
    if not (stack.runs_here() and stack.publishes_url()):
        msg = (
            f"Something answers at {stack.url}, but the compose project"
            f" {stack.project_name} does not run it: its app is not running or"
            f" its nginx does not publish port {stack.https_port}. Check `name`."
        )
        raise ValueError(msg)
    return _use_stack(stack)


@tool
def cloud_status() -> str:
    """Show the local QFieldCloud the cloud tools use, its URL and if it answers."""
    if _stack is None:
        return f"None in use. {NO_STACK}"
    state = "up" if _stack.is_up() else "not answering"
    user, password = _stack.admin
    return (
        f"{_stack.url} {state}, release {_stack.ref}, compose project"
        f" {_stack.project_name}, admin {user} / {password}"
    )


def _make_stack(
    ref: str | None,
    port_offset: int | None,
    name: str | None,
    https_port: int | None,
) -> QFieldCloudStack:
    from qfield_driver.cloud.stack import (  # noqa: PLC0415
        HOSTED,
        SOURCE_ENV,
        QFieldCloudStack,
        resolve_ref,
    )

    if port_offset is None:
        port_offset = int(os.environ.get(PORT_OFFSET_ENV) or 0)
    extra: dict[str, Any] = {}
    if name:
        extra["name"] = name
    if https_port:
        extra["https_port"] = https_port
    source = os.environ.get(SOURCE_ENV) if ref is None else None
    if source:
        stack = QFieldCloudStack.local(Path(source), default_cache_dir(), port_offset)
        for key, value in extra.items():
            setattr(stack, key, value)
        return stack
    return QFieldCloudStack.with_offset(
        resolve_ref(ref or HOSTED), default_cache_dir(), port_offset, **extra
    )


def _use_stack(stack: QFieldCloudStack) -> str:
    global _stack  # noqa: PLW0603 the tools below talk to the stack used last
    _stack = stack
    _clients.clear()
    user, password = stack.admin
    return (
        f"{stack.url} release {stack.ref}, compose project {stack.project_name},"
        f" admin {user} / {password}"
    )


def _project_dir(directory: str) -> Path:
    path = Path(directory).expanduser().resolve()
    if not path.is_dir():
        msg = f"Not a project directory: {path}"
        raise FileNotFoundError(msg)
    return path


def _client(username: str | None, password: str | None) -> QFieldCloudClient:
    """Return a client of the local cloud, logged in as the admin by default.

    A login ends the same user's other sessions, so a device needs a user of
    its own, see cloud_user.
    """
    from qfield_driver.cloud.client import QFieldCloudClient  # noqa: PLC0415

    if _stack is None:
        msg = NO_STACK
        raise ValueError(msg)
    if username is None and password is None:
        username, password = _stack.admin
    elif username is None or password is None:
        msg = "Give username and password together"
        raise ValueError(msg)
    key = (_stack.url, username, password)
    if key not in _clients:
        _clients[key] = QFieldCloudClient(
            _stack.url, username, password, verify=_stack.ca_certificate
        )
    return _clients[key]


@tool
def cloud_user(username: str, password: str, *, superuser: bool = False) -> str:
    """Create a user on the local QFieldCloud, or leave an existing one alone.

    Give each device a user of its own, a login ends the user's other sessions.
    """
    if _stack is None:
        msg = NO_STACK
        raise ValueError(msg)
    _stack.ensure_user(username, password, superuser=superuser)
    return f"user {username} ready"


@tool
def cloud_create_project(
    name: str,
    *,
    directory: str | None = None,
    collaborators: list[str] | None = None,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """Create a project on the local QFieldCloud and return its id.

    With `directory` the project's files go up and the project is packaged,
    which is what a device needs to download it.

    :param directory: A QField project directory to upload
    :param collaborators: Usernames added as editors, they must exist
    :param username: Owner of the project, the admin by default
    """
    client = _client(username, password)
    path = _project_dir(directory) if directory else None
    project_id = client.create_project(name)
    for collaborator in collaborators or []:
        client.add_collaborator(project_id, collaborator)
    if path:
        client.upload(project_id, path)
        client.package(project_id)
    return project_id


@tool
def cloud_add_collaborator(
    project_id: str,
    collaborator: str,
    *,
    role: str = "editor",
    username: str | None = None,
    password: str | None = None,
) -> str:
    """Give a user a role on a project of the local QFieldCloud.

    :param role: `reader`, `reporter`, `editor`, `manager` or `admin`
    :param username: A user who may manage the project, the admin by default
    """
    _client(username, password).add_collaborator(project_id, collaborator, role)
    return f"{collaborator} is {role}"


@tool
def cloud_upload(
    project_id: str,
    directory: str,
    *,
    package: bool = True,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """Upload a project directory to the local QFieldCloud, and package it.

    :param package: Run the package job devices download from
    """
    client = _client(username, password)
    path = _project_dir(directory)
    count = client.upload(project_id, path)
    if package:
        client.package(project_id)
    return f"uploaded {count} files" + (", packaged" if package else "")


@tool
def cloud_package(
    project_id: str, *, username: str | None = None, password: str | None = None
) -> str:
    """Run the package job of a project and wait for it to finish."""
    _client(username, password).package(project_id)
    return "packaged"


@tool
def cloud_deltas(
    project_id: str, *, username: str | None = None, password: str | None = None
) -> list[dict[str, Any]]:
    """Deltas a project received, with their status, such as `STATUS_APPLIED`."""
    return [
        {
            **{
                key: delta.get(key)
                for key in ("id", "status", "created_by", "created_at")
            },
            "message": (delta.get("last_feedback") or {}).get("msg"),
        }
        for delta in _client(username, password).deltas(project_id)
    ]


@tool
def cloud_login(
    url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    *,
    device: str = "device",
) -> str:
    """Log a device in to a QFieldCloud.

    :param url: Without it the stack of cloud_up or cloud_attach
    """
    if url is None:
        if _stack is None:
            raise ValueError(NO_STACK)
        url = _stack.url
    if username is None or password is None:
        msg = "Give username and password"
        raise ValueError(msg)
    with devices.use(device) as app:
        actions.login(app, url, username, password)
    return "logged in"


@tool
def cloud_download(
    project_id: str,
    *,
    device: str = "device",
    open_it: bool = True,
    grant_project_plugin: bool = False,
) -> str:
    """Download a cloud project the device's user can see, and open it.

    :param grant_project_plugin: Answer the project plugin permission prompt
        while opening
    """
    with devices.use(device) as app:
        path = actions.download_project(app, project_id)
        if open_it:
            actions.open_project(app, path, grant_plugin=grant_project_plugin)
    return str(path)


@tool
def cloud_synchronize(project_id: str, *, device: str = "device") -> str:
    """Push local edits and download the latest state, as Synchronize does."""
    with devices.use(device) as app:
        result = actions.synchronize(app, project_id)
    if not result["deltas"]:
        return "synchronized, no local changes to push"
    return (
        f"synchronized, deltas pushed: {result['deltas']},"
        f" status {result['delta_status']}"
    )


def main() -> None:
    stopped = clean_orphans()
    if stopped:
        LOGGER.warning("Stopped devices of a killed server: %s", stopped)
    server.run("stdio")


if __name__ == "__main__":
    main()
