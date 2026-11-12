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

"""What a field user does, in terms of QField's own objects.

Every tap is a real pointer event at the item's position on screen. Item names
follow QField 4.2, recheck them on a version bump.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qfield_driver.app import QFieldApp

LOGGED_IN = 2
PROJECT_IDLE = 0
RENDER_S = 1.5
SETTLE_S = 1
# QField asks during the load, a granted plugin never asks.
PERMISSION_PROMPT_S = 10
FEATURE_FORM = "find('featureForm')"
# A form opened from a relation editor, in a popup of its own.
EMBEDDED_FORM = (
    "walk(scene(), i => String(i).startsWith('FeatureForm_') && i.visible"
    " && i.embeddedLevel > 0, 0)"
)
SAVE_ICON = "ic_check_white_24dp"
EDIT_ICON = "ic_edit_attributes"


def js(value: object) -> str:
    """Return a Python value as a JS literal."""
    return json.dumps(value)


# Finding and tapping items


def center_of(app: QFieldApp, item: str) -> tuple[float, float]:
    """Window position of the center of the item a JS expression gives."""
    x, y = app.eval(f"""
      const item = {item};
      const p = item.mapToGlobal(item.width / 2, item.height / 2);
      return [p.x, p.y];
    """)
    return x, y


def tap_item(app: QFieldApp, item: str, timeout: float = 15) -> None:
    """Tap the item a JS expression gives, once it exists and is visible."""
    app.wait(f"const item = {item}; return !!item && item.visible", timeout)
    app.click(*center_of(app, item))


def _matching(test: str, root: str | None) -> str:
    return f"walk({root or 'scene()'}, i => i.visible && ({test})(i), 0)"


def tap_matching(
    app: QFieldApp, test: str, root: str | None = None, timeout: float = 15
) -> None:
    """Tap the first visible item passing a JS test.

    :param root: JS expression of the item to search under, the window by default
    """
    item = _matching(test, root)
    app.wait(f"return !!{item}", timeout)
    app.click(*center_of(app, item))


def tap_text(app: QFieldApp, text: str, root: str | None = None) -> None:
    """Tap a visible control by its text."""
    # Button texts can carry a mnemonic marker, `&Yes`.
    tap_matching(app, f"i => String(i.text).replace('&', '') === {js(text)}", root)


def tap_text_containing(app: QFieldApp, text: str, root: str | None = None) -> None:
    tap_matching(app, f"i => String(i.text).indexOf({js(text)}) !== -1", root)


def tap_object(app: QFieldApp, object_name: str, root: str | None = None) -> None:
    """Tap a visible item by its object name."""
    tap_matching(app, f"i => i.objectName === {js(object_name)}", root)


def tap_icon(app: QFieldApp, icon: str, root: str | None = None) -> None:
    """Tap a visible button whose icon source contains `icon`."""
    tap_matching(app, f"i => String(i.iconSource).indexOf({js(icon)}) !== -1", root)


def item_by_name(object_name: str) -> str:
    """JS expression of the first item with an object name."""
    return f"findItem({js(object_name)})"


def wait_for_item(
    app: QFieldApp, object_name: str, condition: str = "true", timeout: float = 15
) -> None:
    """Wait until an item exists and a JS condition on `item` holds."""
    app.wait(
        f"const item = {item_by_name(object_name)};return !!item && !!({condition})",
        timeout,
    )


def is_visible(app: QFieldApp, object_name: str) -> bool:
    """Whether an item exists and shows, its ancestors included."""
    return bool(
        app.eval(f"""
      let item = {item_by_name(object_name)};
      if (!item) return false;
      for (let i = item; i; i = i.parent) if (!i.visible) return false;
      return true;
    """)
    )


def item_property(app: QFieldApp, object_name: str, name: str) -> Any:  # noqa: ANN401
    return app.eval(f"return {item_by_name(object_name)}[{js(name)}]")


def set_item_property(
    app: QFieldApp, object_name: str, name: str, value: object
) -> None:
    app.eval(f"{item_by_name(object_name)}[{js(name)}] = {js(value)};")


def type_into(
    app: QFieldApp, object_name: str, text: str, *, clear: bool = True
) -> None:
    """Tap a text field and type, as the on-screen keyboard would."""
    item = item_by_name(object_name)
    tap_item(app, item)
    app.wait(f"return {item}.activeFocus", 5)
    if clear:
        app.eval(f"{item}.selectAll();")
    app.type_text(text)


def expand_drawer(app: QFieldApp, object_name: str) -> None:
    """Open a collapsed tool button drawer by tapping its toggle."""
    drawer = item_by_name(object_name)
    if app.eval(f"return {drawer}.collapsed"):
        x, y = app.eval(f"""
          const item = {drawer};
          const p = item.mapToGlobal(item.size / 2, item.size / 2);
          return [p.x, p.y];
        """)
        app.click(x, y)
    app.wait(f"return !{drawer}.collapsed", 10)
    # The drawer grows in a 200 ms animation.
    time.sleep(0.5)


# Cloud


def login(app: QFieldApp, url: str, username: str, password: str) -> None:
    app.eval(f"""
      const c = find('cloudConnection');
      c.url = {js(url)}; c.username = {js(username)};
      c.login({js(password)});
    """)
    app.wait(f"return find('cloudConnection').status === {LOGGED_IN}", 40)


def download_project(app: QFieldApp, project_id: str) -> Path:
    """Package and download a cloud project, and return the local project file."""
    project = f"find('cloudProjectsModel').findProject({js(project_id)})"
    # A list reply mid-download rebuilds the model under the running transfers,
    # and QField refreshes on its own after a login.
    idle = "!find('cloudProjectsModel').isRefreshing"
    app.wait(f"return {idle}", 30)
    app.eval("find('cloudProjectsModel').refreshProjectsList();")
    app.wait(f"return {idle} && !!{project}", 30)
    app.eval(f"find('cloudProjectsModel').projectPackageAndDownload({js(project_id)})")
    app.wait(
        f"const p = {project};return p.localPath !== '' && p.status === {PROJECT_IDLE}",
        300,
        1,
    )
    local = Path(app.eval(f"return {project}.localPath"))
    packaged: list[Path] = []
    for root in (local, *app.home.rglob(f"*{project_id}*")):
        if root.is_dir():
            packaged.extend((*root.rglob("*_qfield.qgz"), *root.rglob("*_qfield.qgs")))
    packaged.sort()
    if not packaged:
        msg = f"No packaged project file for {project_id} under {local}"
        raise FileNotFoundError(msg)
    return packaged[0]


def push(app: QFieldApp, project_id: str) -> int:
    """Push the delta file, and return how many deltas it held."""
    count = int(app.eval("return layerObserver.deltaFileWrapper.count") or 0)
    app.eval(f"find('cloudProjectsModel').projectPush({js(project_id)}, false);")
    app.wait("return layerObserver.deltaFileWrapper.count === 0", 120, 1)
    return count


def synchronize(app: QFieldApp, project_id: str) -> None:
    """Push local edits and download the latest cloud state, as Synchronize does."""
    project = f"find('cloudProjectsModel').findProject({js(project_id)})"
    app.eval(f"find('cloudProjectsModel').projectPush({js(project_id)}, true);")
    app.wait(
        "return layerObserver.deltaFileWrapper.count === 0"
        f" && {project}.status === {PROJECT_IDLE}",
        300,
        1,
    )


# Projects


def open_project(
    app: QFieldApp, project_file: Path, *, grant_plugin: bool = False
) -> None:
    """Open a project, and grant its project plugin the permission a user would.

    :param grant_plugin: The project ships a plugin, answer QField's prompt if
        it asks. A permanently granted plugin loads without one.
    """
    if grant_plugin:
        app.eval("""
          state.permission = false;
          if (!state.permissionHooked) {
            pluginManager.pluginPermissionRequested.connect(
              () => { state.permission = true; });
            state.permissionHooked = true;
          }
        """)
    app.eval("const tour = find('mapCanvasTour'); if (tour) tour.blockGuide();")
    app.eval(f"""
      state.loaded = false;
      if (!state.loadHooked) {{
        iface.loadProjectEnded.connect(() => {{ state.loaded = true; }});
        state.loadHooked = true;
      }}
      iface.loadFile({js(str(project_file))});
    """)
    app.wait("return state.loaded && qgisProject.fileName !== ''", 60)
    # The loading overlay fades out after the load and swallows taps meanwhile.
    app.wait("const busy = findItem('busyOverlay'); return !busy || !busy.visible", 10)
    if grant_plugin:
        try:
            app.wait("return state.permission === true", PERMISSION_PROMPT_S)
        except TimeoutError:
            return
        tap_text(app, "Yes")


# Map


def frame_map(app: QFieldApp, x: float, y: float, half_size: float) -> None:
    """Show the map around a project CRS coordinate, as panning there would."""
    app.eval(f"""
      const a = GeometryUtils.point({x - half_size}, {y - half_size});
      const b = GeometryUtils.point({x + half_size}, {y + half_size});
      const rectangle = GeometryUtils.createRectangleFromPoints(a, b);
      find('mapCanvas').mapSettings.setExtent(rectangle, false);
    """)
    time.sleep(RENDER_S)


def map_to_screen(app: QFieldApp, x: float, y: float) -> tuple[float, float]:
    """Window position where a project CRS coordinate is drawn."""
    sx, sy = app.eval(f"""
      const mapSettings = find('mapCanvas').mapSettings;
      const local = mapSettings.coordinateToScreen(GeometryUtils.point({x}, {y}));
      const screen = find('mapCanvasContainer').mapToGlobal(local.x, local.y);
      return [screen.x, screen.y];
    """)
    return sx, sy


def tap_map(app: QFieldApp, x: float, y: float) -> None:
    """Tap the map at a project CRS coordinate."""
    app.click(*map_to_screen(app, x, y))


def long_press_map(app: QFieldApp, x: float, y: float) -> None:
    app.long_press(*map_to_screen(app, x, y))


def close_feature_list(app: QFieldApp) -> None:
    """Close the panel that a tap on features opened."""
    app.eval("find('featureForm').state = 'Hidden';")
    app.wait("return !find('featureForm').visible", 10)


def set_active_layer(app: QFieldApp, layer: str) -> None:
    app.eval(f"""
      find('dashBoard').activeLayer = qgisProject.mapLayersByName({js(layer)})[0];
    """)


def digitize_point(
    app: QFieldApp, layer: str, point: tuple[float, float], label: str, value: object
) -> None:
    """Add a point feature by tapping the map, then fill its form and save."""
    set_active_layer(app, layer)
    app.eval("iface.mainWindow().changeMode('digitize');")
    app.wait("return find('stateMachine').state === 'digitize'", 10)
    tap_map(app, *point)
    app.wait("return find('overlayFeatureFormDrawer').opened", 15)
    fill_and_confirm(app, "find('overlayFeatureFormDrawer').contentItem", label, value)
    app.wait("return !find('overlayFeatureFormDrawer').opened", 15)
    app.eval("iface.mainWindow().changeMode('browse');")


# Forms


def open_feature_form(
    app: QFieldApp, layer: str, expression: str, *, edit: bool = True
) -> None:
    """Open an existing feature's form in the feature list drawer."""
    app.eval(f"""
      const layer = qgisProject.mapLayersByName({js(layer)})[0];
      const form = find('featureForm');
      form.selection.focusedItem = -1;
      form.model.setFeatures(layer, {js(expression)});
      form.selection.focusedItem = 0;
      form.state = {js("FeatureFormEdit" if edit else "FeatureForm")};
    """)
    app.wait("return find('featureForm').visible", 10)


def edit_in_form(
    app: QFieldApp, layer: str, expression: str, label: str, value: object
) -> None:
    """Open a feature's real form, change one field and confirm.

    :param label: The field's name in the form, its alias when it has one
    """
    open_feature_form(app, layer, expression)
    fill_and_confirm(app, FEATURE_FORM, label, value)


def editor(form: str, label: str) -> str:
    """JS expression of a form field's editor loader."""
    return (
        f"walk({form}, i => i.objectName === {js('attributeEditorLoader' + label)}, 0)"
    )


def field_value(app: QFieldApp, label: str, form: str = FEATURE_FORM) -> Any:  # noqa: ANN401
    return app.eval(f"return {editor(form, label)}.item.parent.value")


def set_field(
    app: QFieldApp, label: str, value: object, form: str = FEATURE_FORM
) -> None:
    """Change a field through its editor widget, as the widget does on input."""
    app.wait(f"return !!{editor(form, label)}", 15)
    app.eval(f"{editor(form, label)}.item.valueChangeRequested({js(value)}, false);")


def fill_and_confirm(app: QFieldApp, root: str, label: str, value: object) -> None:
    """Change one field of the form under `root` and confirm the form."""
    set_field(app, label, value, root)
    confirm_form(app, root)


def confirm_form(app: QFieldApp, root: str = FEATURE_FORM) -> None:
    """Confirm the open feature form under `root`, as its save button does."""
    app.eval(f"""
      const isForm = i => typeof i.confirm === 'function'
        && typeof i.save === 'function';
      walk({root}, isForm, 0).confirm();
    """)


def _show_tab_of(app: QFieldApp, label: str, form: str) -> None:
    """Tap the form tab holding a field, when it is not the current one."""
    index = app.eval(f"""
      const editor = {editor(form, label)};
      let swipe = editor.parent;
      while (swipe && !String(swipe).startsWith('SwipeView')) swipe = swipe.parent;
      if (!swipe) return -1;
      for (let i = 0; i < swipe.count; i++) {{
        let page = editor;
        while (page && page !== swipe.itemAt(i)) page = page.parent;
        if (page) return i === swipe.currentIndex ? -1 : i;
      }}
      return -1
    """)
    if index in (None, -1):
        return
    app.eval(f"""
      const tabs = walk({form}, i => i.objectName === 'tabRow', 0);
      tabs.positionViewAtIndex({index}, 1);  // ListView.Contain
    """)
    time.sleep(0.3)
    tap_object(app, f"tabRowdDelegate_{index}", form)
    time.sleep(0.5)


def scroll_to_field(app: QFieldApp, label: str, form: str = FEATURE_FORM) -> None:
    """Show a field's tab and scroll the form to it, as a swipe would."""
    app.wait(f"return !!{editor(form, label)}", 15)
    _show_tab_of(app, label, form)
    app.eval(f"""
      const editor = {editor(form, label)};
      let flick = editor.parent;
      while (flick && flick.contentY === undefined) flick = flick.parent;
      const y = editor.mapToItem(flick.contentItem, 0, 0).y - flick.height / 3;
      const bottom = Math.max(0, flick.contentHeight - flick.height);
      flick.contentY = Math.max(0, Math.min(y, bottom));
    """)
    time.sleep(0.3)


def choose_option(
    app: QFieldApp, label: str, option: str, form: str = FEATURE_FORM
) -> None:
    """Pick an option of a combobox field from its real popup."""
    scroll_to_field(app, label, form)
    tap_object(app, "relationComboBox", editor(form, label))
    tap_text(app, option)


def toggle_switch(app: QFieldApp, label: str, form: str = FEATURE_FORM) -> None:
    """Flip a checkbox field's switch."""
    scroll_to_field(app, label, form)
    tap_matching(
        app,
        "i => typeof i.checked === 'boolean' && typeof i.toggle === 'function'",
        editor(form, label),
    )


def tick_item(app: QFieldApp, label: str, item: str, form: str = FEATURE_FORM) -> None:
    """Tick one entry of a checklist field."""
    scroll_to_field(app, label, form)
    tap_text(app, item, editor(form, label))


def search_and_tick(
    app: QFieldApp, label: str, search: str, item: str, form: str = FEATURE_FORM
) -> None:
    """Type into a checklist field's search bar and tick the match."""
    scroll_to_field(app, label, form)
    field = editor(form, label)
    before = app.eval(f"return JSON.stringify({field}.item.parent.value)")
    tap_object(app, "valueRelationSearchBar", field)
    app.type_text(search)
    # The list filters after the last key, a tap before that hits a moving row.
    time.sleep(SETTLE_S)
    tap_text(app, item, field)
    app.wait(f"return JSON.stringify({field}.item.parent.value) !== {js(before)}", 10)


def attach_photo(app: QFieldApp, label: str, form: str = FEATURE_FORM) -> str:
    """Take a photo with the real camera button, and return the stored path.

    There is no camera under test, so the camera hands back a grab of the map.
    """
    picture = app.home / f"capture-{time.monotonic_ns()}.jpg"
    app.eval(
        "find('mapCanvasContainer').grabToImage("
        f"r => r.saveToFile({js(str(picture))}));"
    )
    deadline = time.monotonic() + 10
    while not picture.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    time.sleep(0.5)
    scroll_to_field(app, label, form)
    field = editor(form, label)
    tap_icon(app, "ic_camera_photo", field)
    camera = (
        f"walk({field}.item, i => i.item && i.active"
        " && typeof i.item.finished === 'function', 0)"
    )
    app.wait(f"return !!{camera}", 15)
    app.eval(f"{camera}.item.finished({js(str(picture))});")
    app.wait(f"return !{camera}", 15)
    return str(app.eval(f"return String({field}.item.parent.value)") or "")


def start_editing(app: QFieldApp, form: str = FEATURE_FORM) -> None:
    """Tap the edit button of a feature form opened from the map."""
    tap_icon(app, EDIT_ICON, form)
    app.wait(f"return {form}.state === 'FeatureFormEdit'", 15)


def save_form(app: QFieldApp, form: str = FEATURE_FORM) -> None:
    """Tap the check button of an open feature form in edit mode."""
    tap_icon(app, SAVE_ICON, form)
    app.wait(f"return {form}.state !== 'FeatureFormEdit'", 15)


def open_related(app: QFieldApp, relation_label: str, card_text: str) -> None:
    """Open a child feature's form from a relation editor of the open form."""
    scroll_to_field(app, relation_label)
    tap_text_containing(app, card_text, editor(FEATURE_FORM, relation_label))
    app.wait(f"return !!{EMBEDDED_FORM}", 15)


def save_embedded_form(app: QFieldApp) -> None:
    """Tap the check button of the form a relation editor opened."""
    tap_icon(app, SAVE_ICON, EMBEDDED_FORM)
    app.wait(f"return !{EMBEDDED_FORM}", 15)


# Layers


def _iterator(expression: str) -> str:
    if not expression:
        return "LayerUtils.createFeatureIterator(layer)"
    return f"LayerUtils.createFeatureIteratorFromExpression(layer, {js(expression)})"


def features(
    app: QFieldApp, layer: str, fields: list[str], expression: str = ""
) -> list[dict[str, Any]]:
    """Attribute values of a layer's features, read through QField's own layer."""
    return app.eval(f"""
      const layer = qgisProject.mapLayersByName({js(layer)})[0];
      const it = {_iterator(expression)};
      const rows = [];
      while (it.hasNext()) {{
        const f = it.next();
        const row = {{}};
        for (const name of {js(fields)}) row[name] = f.attribute(name);
        rows.push(row);
      }}
      it.close();
      return rows;
    """)


def feature_count(app: QFieldApp, layer: str, expression: str = "") -> int:
    return int(
        app.eval(f"""
      const layer = qgisProject.mapLayersByName({js(layer)})[0];
      const it = {_iterator(expression)};
      let n = 0;
      while (it.hasNext()) {{ it.next(); n++; }}
      it.close();
      return n;
    """)
    )


def log_messages(app: QFieldApp, tag: str | None = None) -> list[str]:
    """Messages in QField's message log, the ones `iface.logMessage` writes."""
    return app.eval(f"""
      const rows = [];
      const model = messageLogModel;
      for (let r = 0; r < model.rowCount(); r++) {{
        const index = model.index(r, 0);
        const tag = model.data(index, 0x0101);
        if ({js(tag)} !== null && tag !== {js(tag)}) continue;
        rows.push(String(model.data(index, 0x0100)));
      }}
      return rows;
    """)


def wait_for_message(
    app: QFieldApp, text: str, tag: str | None = None, timeout: float = 15
) -> None:
    """Wait until QField's message log holds a message containing `text`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(text in message for message in log_messages(app, tag)):
            return
        time.sleep(0.2)
    msg = f"{text!r} not in {log_messages(app, tag)}"
    raise TimeoutError(msg)


def wait_for_text(app: QFieldApp, text: str, timeout: float = 5) -> None:
    """Wait until visible text containing `text` shows, a toast for example."""
    app.wait(
        "return walkAll(scene(), i => i.visible && typeof i.text === 'string'"
        f" && i.text.indexOf({js(text)}) !== -1, 0).length > 0",
        timeout,
        0.05,
    )


def close_feature_form(app: QFieldApp) -> None:
    """Hide the feature list and form without saving, as the back gesture does."""
    close_feature_list(app)


def highlighted_wkt(app: QFieldApp) -> str | None:
    """WKT of what the geometry highlighter shows, None when it shows nothing."""
    return app.eval("""
      const g = find('geometryHighlighter').geometryWrapper.qgsGeometry;
      const wkt = g ? String(g.asWkt(0)) : '';
      return wkt === '' ? null : wkt;
    """)


# Editing


def _layer(layer: str) -> str:
    return f"qgisProject.mapLayersByName({js(layer)})[0]"


def geometries(app: QFieldApp, layer: str, expression: str = "") -> list[str]:
    """WKT of a layer's feature geometries, at most three decimals."""
    return app.eval(f"""
      const layer = {_layer(layer)};
      const it = {_iterator(expression)};
      const out = [];
      while (it.hasNext()) out.push(String(it.next().geometry.asWkt(3)));
      it.close();
      return out;
    """)


def add_feature(
    app: QFieldApp, layer: str, wkt: str | None, attributes: dict[str, object]
) -> None:
    """Add a feature and commit, the way plugin JS adds features.

    Triggers wired to the layer's `featureAdded` run as in the field.
    """
    geometry = f"GeometryUtils.createGeometryFromWkt({js(wkt)})" if wkt else "undefined"
    app.eval(f"""
      const layer = {_layer(layer)};
      layer.startEditing();
      const f = FeatureUtils.createFeature(layer, {geometry});
      const values = {js(attributes)};
      for (const name in values) f.setAttribute(name, values[name]);
      if (!LayerUtils.addFeature(layer, f)) {{
        layer.rollBack();
        throw new Error('addFeature failed');
      }}
      if (!layer.commitChanges()) {{
        const errors = layer.commitErrors ? layer.commitErrors().join('; ') : '';
        layer.rollBack();
        throw new Error('commit failed: ' + errors);
      }}
    """)
    time.sleep(0.3)


def change_geometry(app: QFieldApp, layer: str, expression: str, wkt: str) -> None:
    """Replace the geometry of the first matching feature and save.

    This is what QField's vertex editor does through its feature model.
    """
    app.eval(f"""
      const layer = {_layer(layer)};
      const it = {_iterator(expression)};
      const f = it.next(); it.close();
      const model = Qt.createQmlObject('import org.qfield; FeatureModel {{ }}', driver);
      model.project = qgisProject;
      model.currentLayer = layer;
      model.feature = f;
      const ok = model.changeGeometry(GeometryUtils.createGeometryFromWkt({js(wkt)}))
        && model.save();
      model.destroy();
      if (!ok) throw new Error('changeGeometry failed');
    """)
    time.sleep(0.3)


def import_js(app: QFieldApp, path: Path, name: str) -> None:
    """Import a JS module file, so tests call its functions as `state[name]`.

    `state[name].call('function', [args])` runs a function of the module.
    """
    url = js(Path(path).resolve().as_uri())
    app.eval(f"""
      state[{js(name)}] = Qt.createQmlObject(
        'import QtQuick; import ' + JSON.stringify({url}) + ' as M;'
        + 'QtObject {{ function call(n, a) {{ return M[n].apply(null, a); }} }}',
        driver, {js(name)});
    """)


def wait_visible(
    app: QFieldApp, object_name: str, *, shown: bool = True, timeout: float = 5
) -> None:
    """Wait until an item or popup shows or hides, its transitions done."""
    app.wait(
        f"const item = {item_by_name(object_name)};"
        f"return !!item && item.visible === {js(shown)}",
        timeout,
        0.05,
    )


def frame_and_tap(app: QFieldApp, x: float, y: float, half_size: float = 100) -> None:
    """Pan the map to a project CRS coordinate and tap it, as a user picking there."""
    frame_map(app, x, y, half_size)
    tap_map(app, x, y)
    time.sleep(0.5)


def evaluate_expression(
    app: QFieldApp, expression: str, layer: str | None = None
) -> Any:  # noqa: ANN401
    """Value of a QGIS expression in QField's project context, a layer's too.

    QField's evaluator hands values back as text, `1 + 2` gives `"3"`.
    """
    context_layer = f"evaluator.layer = {_layer(layer)};" if layer else ""
    return app.eval(f"""
      const evaluator = Qt.createQmlObject(
        'import org.qfield; ExpressionEvaluator {{}}', driver);
      evaluator.project = qgisProject;
      {context_layer}
      const value = evaluator.evaluate({js(expression)});
      evaluator.destroy();
      return value;
    """)


def scan_code(app: QFieldApp, text: str, timeout: float = 10) -> None:
    """Hand text to QField's open code reader, as a decoded QR code would."""
    app.wait("return find('codeReader').visible", timeout)
    app.eval(f"find('codeReader').accepted({js(text)});")
    time.sleep(0.3)
