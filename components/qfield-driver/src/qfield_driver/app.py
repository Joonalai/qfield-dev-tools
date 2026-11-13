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

"""Real QField under Xvfb with an isolated profile, driven by a test app plugin."""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Self

from qfield_driver.bridge import Bridge
from qfield_driver.display import (
    Pointer,
    kill_with_parent,
    start_xvfb,
    terminate,
)
from qfield_driver.positioning import NmeaServer

LOGGER = logging.getLogger(__name__)

DRIVER_NAME = "qfield_driver"
DRIVER_SOURCE = Path(__file__).parent / "driver" / DRIVER_NAME
PLUGINS_DIR = "Documents/QField Documents/QField/plugins"
SCREEN_SIZE = (1280, 800)
BINARY_ENV = "QFIELD_APP_BINARY"
START_TIMEOUT_S = 90
POLL_S = 0.02
# QField opens the host's webcam for a photo, so hide every camera from it.
NO_CAMERAS = (
    'for d in /dev/video*; do [ -e "$d" ] || continue; '
    'mount --bind /dev/null "$d" || exit 3; done; exec "$@"'
)
UNSHARE_HINT = (
    "\nHiding the cameras needs unprivileged user namespaces, which AppArmor"
    " may restrict (sysctl kernel.apparmor_restrict_unprivileged_userns=0)."
)
# Views that show the host camera, never grab them.
CAMERA_VIEWS = "/Camera|QRCodeReader|CodeReader/"
DROPPED_ENV = (
    "WAYLAND_DISPLAY",
    "QT_QPA_PLATFORM",
    "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR",
    "QGIS_PREFIX_PATH",
    "QT_PLUGIN_PATH",
    "PYTHONPATH",
)


class DriverError(RuntimeError):
    """Code sent to QField threw, or QField went away."""


def local_app(path: str | Path) -> Path:
    """Return a QField of your own to run: an AppRun, an AppImage or a build."""
    app_run = Path(path).expanduser().resolve()
    if not app_run.is_file() or not os.access(app_run, os.X_OK):
        msg = f"Not an executable QField: {app_run}"
        raise FileNotFoundError(msg)
    return app_run


def settings_key(main_qml: Path) -> str:
    """Return a plugin's key in `QField.conf`."""
    return str(main_qml).replace("/", "_").replace(" ", "%20")


def install_app_plugin(home: Path, source: Path, uuid: str) -> Path:
    """Copy an app plugin into a profile, and return its `main.qml`."""
    target = home / PLUGINS_DIR / uuid
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target / "main.qml"


def _plugin_settings(main_qml: Path, uuid: str) -> str:
    key = settings_key(main_qml)
    return (
        f"plugins\\{key}\\userEnabled=true\n"
        f"plugins\\{key}\\permissionGranted=true\n"
        f"plugins\\{key}\\uuid={uuid}\n"
    )


def _ini_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        # Quoted, or QSettings reads commas as a list and eats backslashes.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return str(value)


def seed_profile(
    home: Path,
    endpoint: str,
    app_plugins: dict[str, Path] | None = None,
    settings: dict[str, object] | None = None,
) -> None:
    """Install the driver and app plugins, and write QField settings.

    Telemetry is turned off as well.

    :param settings: QSettings keys such as `myplugin/interval`, a key without
        a group goes under `General`
    """
    driver = install_app_plugin(home, DRIVER_SOURCE, DRIVER_NAME)
    driver.write_text(driver.read_text().replace("__ENDPOINT__", endpoint))
    plugins = _plugin_settings(driver, DRIVER_NAME)
    for uuid, source in (app_plugins or {}).items():
        plugins += _plugin_settings(install_app_plugin(home, source, uuid), uuid)
    groups: dict[str, list[str]] = {
        "General": ["enableInfoCollection=false"],
        "QField": ["showMapCanvasGuide=false"],
        "qfield": plugins.splitlines(),
    }
    for key, value in (settings or {}).items():
        group, _, name = key.rpartition("/") if "/" in key else ("General", "", key)
        group, _, rest = group.partition("/")
        name = f"{rest}\\{name}" if rest else name
        groups.setdefault(group, []).append(f"{name}={_ini_value(value)}")
    conf = home / ".config/OPENGIS.ch/QField.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(
        "\n".join(
            f"[{group}]\n" + "\n".join(lines) + "\n" for group, lines in groups.items()
        )
    )


class QFieldApp:
    """One QField process. Never touches the user's profile or other instances.

    :param app_plugins: App plugins to install and enable, by uuid
    :param settings: QField settings written before the start, see `seed_profile`
    :param die_with_parent: Kill QField and Xvfb when the starting thread exits,
        for callers that may be killed without cleanup
    """

    def __init__(  # noqa: PLR0913 options are keyword-only
        self,
        app_run: Path,
        home: Path,
        *,
        app_plugins: dict[str, Path] | None = None,
        settings: dict[str, object] | None = None,
        screen_size: tuple[int, int] = SCREEN_SIZE,
        die_with_parent: bool = False,
    ) -> None:
        self._app_run = app_run
        self._die_with_parent = die_with_parent
        self.home = home
        self.log = home.parent / f"{home.name}.log"
        self._app_plugins = app_plugins
        self._settings = settings
        self._screen_size = screen_size
        self._sequence = 0
        self._log_offset = 0
        # Where this test's log starts on a reused app.
        self._log_start = 0
        self._bridge = Bridge()
        self._process: subprocess.Popen[bytes] | None = None
        self._xvfb: subprocess.Popen[bytes] | None = None
        self._pointer: Pointer | None = None
        self._gnss: NmeaServer | None = None
        self._eval_lock = threading.Lock()
        self._hosted: Path | None = None
        self._reload_copy: Path | None = None

    def __enter__(self) -> Self:
        try:
            self._start()
        except BaseException:
            self.close()
            raise
        return self

    def _start(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        seed_profile(
            self.home, self._bridge.endpoint, self._app_plugins, self._settings
        )
        self._xvfb, display_number = start_xvfb(
            *self._screen_size, die_with_parent=self._die_with_parent
        )
        self._pointer = Pointer(display_number)
        env = {
            name: value for name, value in os.environ.items() if name not in DROPPED_ENV
        }
        env.update(
            DISPLAY=f":{display_number}",
            HOME=str(self.home),
            XDG_CONFIG_HOME=str(self.home / ".config"),
            XDG_DATA_HOME=str(self.home / ".local/share"),
            XDG_CACHE_HOME=str(self.home / ".cache"),
            LIBGL_ALWAYS_SOFTWARE="1",
        )
        command = [str(self._app_run)]
        # Containers and CI runners have no cameras and often no user namespaces.
        if any(Path("/dev").glob("video*")):
            command = [
                *("unshare", "--map-root-user", "--mount"),
                *("sh", "-c", NO_CAMERAS, "qfield", *command),
            ]
        with self.log.open("w") as out:
            self._process = subprocess.Popen(  # noqa: S603 the AppImage we extracted
                command,
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                preexec_fn=kill_with_parent if self._die_with_parent else None,  # noqa: PLW1509 only calls prctl
            )
        deadline = time.monotonic() + START_TIMEOUT_S
        while not self._bridge.polled.wait(0.5):
            if self._process.poll() is not None or time.monotonic() > deadline:
                tail = self.log_text()[-2000:]
                msg = f"QField or its driver did not start:\n{tail}"
                if command[0] == "unshare" and "unshare:" in tail:
                    msg += UNSHARE_HINT
                raise DriverError(msg)
        # Without a window manager nothing maximizes the window.
        width, height = self._screen_size
        self.eval(
            "const window = iface.mainWindow();"
            f"window.width = {width}; window.height = {height};"
        )

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def process_groups(self) -> dict[str, int]:
        """Process group ids of QField and its Xvfb, both lead their group."""
        return {
            name: process.pid
            for name, process in (("qfield", self._process), ("xvfb", self._xvfb))
            if process is not None
        }

    def close(self) -> None:
        if self._process is not None:
            terminate(self._process)
            self._process = None
        if self._pointer is not None:
            self._pointer.close()
            self._pointer = None
        if self._xvfb is not None:
            terminate(self._xvfb)
            self._xvfb = None
        if self._gnss is not None:
            self._gnss.close()
            self._gnss = None
        self._bridge.close()
        if self._reload_copy is not None:
            shutil.rmtree(self._reload_copy, ignore_errors=True)
            self._reload_copy = None

    # Code

    def eval(self, code: str, timeout: float = 30) -> Any:  # noqa: ANN401
        """Run a JS function body in QField and return its JSON-decoded result.

        The body sees `iface`, `find` (iface.findItemByObjectName), `findItem`
        (scene search by objectName), `walk`, `walkAll`, `scene`, `state` (an
        object kept between calls), `plugin` (the hosted plugin root),
        `qgisProject`, `layerObserver`, `pluginManager`, `settings`,
        `platformUtilities`, `messageLogModel`, `featureHistory`,
        `flatLayerTree`, `trackingModel`, `LayerUtils`, `GeometryUtils`,
        `FeatureUtils`, `StringUtils` and `Theme`.
        """
        with self._eval_lock:
            self._sequence += 1
            command_id = self._sequence
            self._bridge.commands.put({"id": command_id, "code": code})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self._bridge.results.pop(command_id, None)
            if result is not None:
                if not result["ok"]:
                    msg = f"{result['value']}\ncode: {code}"
                    raise DriverError(msg)
                return result["value"]
            if self._process is not None and self._process.poll() is not None:
                msg = f"QField exited, see {self.log}"
                raise DriverError(msg)
            time.sleep(POLL_S)
        raise TimeoutError(code)

    def wait(self, code: str, timeout: float = 30, every: float = 0.2) -> Any:  # noqa: ANN401
        """Poll until `code` returns something truthy, and return it."""
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = self.eval(code)
            if last:
                return last
            time.sleep(every)
        msg = f"{code} -> {last!r}"
        raise TimeoutError(msg)

    def settle(self, seconds: float = 0.3) -> None:
        """Let animations and queued signals run."""
        time.sleep(seconds)

    # Log

    def log_text(self) -> str:
        return self.log.read_text(errors="replace")

    def mark_log(self) -> None:
        """Make `new_log_lines` start from here."""
        self._log_offset = len(self.log_text())

    def new_log_lines(self) -> list[str]:
        """Lines QField printed since the last `mark_log`."""
        return self.log_text()[self._log_offset :].splitlines()

    def wait_for_log(self, line: str, timeout: float = 30, count: int = 1) -> None:
        """Wait until the log holds `line` at least `count` times.

        Lines are counted since the last `reset`.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.log_text()[self._log_start :].count(line) >= count:
                return
            time.sleep(0.2)
        msg = f"{line!r} not in {self.log}"
        raise TimeoutError(msg)

    # Input

    @property
    def pointer(self) -> Pointer:
        if self._pointer is None:
            msg = "QField is not running"
            raise DriverError(msg)
        return self._pointer

    def click(self, x: float, y: float) -> None:
        """Click at a window position."""
        self.pointer.click(round(x), round(y))

    def long_press(self, x: float, y: float) -> None:
        self.pointer.long_press(round(x), round(y))

    def drag(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        self.pointer.drag(
            (round(start[0]), round(start[1])), (round(end[0]), round(end[1]))
        )

    def type_text(self, text: str) -> None:
        """Type into whatever has the keyboard focus."""
        self.pointer.type_text(text)

    def key(self, name: str) -> None:
        """Press one key by its keysym name, `Return` or `Escape`."""
        self.pointer.key(name)

    # Plugins

    def host_plugin(self, main_qml: Path) -> None:
        """Load a plugin through the driver, so tests reach its root as `plugin`.

        QField's own plugin manager creates plugins the same way, a component
        created without a parent, but it keeps no handle a test could reach.
        """
        self.eval(f"return driver._pqfHost({json.dumps(str(main_qml))})")
        self._hosted = main_qml

    def reload_plugin(self) -> None:
        """Host a fresh copy of the hosted plugin's directory.

        This way edits to any of its files load, as QML caches imported files by URL.
        """
        if self._hosted is None:
            msg = "No hosted plugin to reload"
            raise DriverError(msg)
        hosted = self._hosted
        previous = self._reload_copy
        copy = self.home.parent / f"{self.home.name}-reload-{time.time_ns()}"
        shutil.copytree(hosted.parent, copy)
        self.host_plugin(copy / hosted.name)
        self._hosted = hosted
        self._reload_copy = copy
        if previous is not None:
            shutil.rmtree(previous, ignore_errors=True)

    def unhost_plugin(self) -> None:
        self.eval(
            "if (driver._pqfHosted) driver._pqfHosted.destroy();"
            "driver._pqfHosted = null;"
        )
        self._hosted = None

    def plugin_property(self, name: str) -> Any:  # noqa: ANN401
        return self.eval(f"return plugin[{json.dumps(name)}]")

    # Positioning

    def set_position(self, x: float, y: float) -> None:
        """Feed a GNSS fix at a project CRS coordinate.

        The first call switches QField's positioning to a fake TCP receiver.
        """
        wgs84 = self.eval(f"""
          const p = GeometryUtils.reprojectPointToWgs84(
            GeometryUtils.point({x}, {y}),
            find('mapCanvas').mapSettings.destinationCrs);
          return [p.y, p.x];
        """)
        if self._gnss is None:
            self._gnss = NmeaServer()
            self._gnss.set_position(*wgs84)
        else:
            self._gnss.set_position(*wgs84)
        device = json.dumps(self._gnss.device_id)
        # lose_position deactivates the source.
        self.eval(f"""
          const source = find('positionSource');
          if (source.deviceId !== {device}) source.deviceId = {device};
          source.active = true;
        """)

    def wait_for_position(self, x: float, y: float, tolerance: float = 0.5) -> None:
        self.wait(f"""
          const p = find('positionSource').projectedPosition;
          return Math.abs(p.x - {x}) < {tolerance} && Math.abs(p.y - {y}) < {tolerance};
        """)

    def lose_position(self) -> None:
        """Stop the fake receiver sending fixes."""
        if self._gnss is not None:
            self._gnss.clear_position()
        self.eval("find('positionSource').active = false;")

    # Pictures

    def camera_open(self) -> bool:
        """Whether a view showing the camera is open."""
        return bool(
            self.eval(
                f"return walkAll(scene(), i => i.visible && {CAMERA_VIEWS}"
                ".test(String(i)), 0).length > 0"
            )
        )

    def screenshot(self, path: Path, item: str = "scene()", scale: float = 1) -> Path:
        """Save a grab of the whole window, or of the item a JS expression gives.

        :param scale: Size factor, below 1 for smaller files
        """
        self.eval(f"""
          const item = {item};
          state.saved = null;
          item.grabToImage(
            result => state.saved = result.saveToFile({json.dumps(str(path))}),
            Qt.size(Math.max(1, item.width * {scale}),
                    Math.max(1, item.height * {scale})));
        """)
        if not self.wait("return state.saved !== null && [state.saved]", 10)[0]:
            msg = f"Could not save a screenshot to {path}"
            raise DriverError(msg)
        return path

    # Reuse

    def reset(self) -> None:
        """Bring a running app back near its started state for another test.

        The plugin is unhosted, popups closed, project cleared, position lost,
        message log cleared and `state` emptied. Settings and app plugins stay.
        """
        # Commands of evals that timed out must not run in the next test.
        with self._eval_lock:
            while True:
                try:
                    self._bridge.commands.get_nowait()
                except queue.Empty:
                    break
            self._bridge.results.clear()
        self.unhost_plugin()
        if self._gnss is not None:
            self.lose_position()
        self.eval("""
          for (let n = 0; n < 20; n++) {
            const popup = search(iface.mainWindow(),
              i => i.opened === true && typeof i.close === 'function');
            if (!popup) break;
            popup.close();
          }
          if (find('stateMachine').state !== 'browse') {
            iface.mainWindow().changeMode('browse');
          }
          iface.clearProject();
          messageLogModel.clear();
          // Hooks keep using the same object, so keep their flags.
          for (const key of Object.keys(state)) {
            if (!key.endsWith('Hooked')) delete state[key];
          }
        """)
        self.settle()
        self.mark_log()
        self._log_start = self._log_offset

    # Diagnostics

    def diagnose(self, directory: Path, name: str) -> str:
        """Save a screenshot and describe the app's state, for a failure report."""
        lines = [f"log: {self.log}"]
        if not self.running:
            lines.append("QField is not running")
        else:
            lines += self._diagnose_live(directory, name)
        tail = self.log_text().splitlines()[-30:]
        return "\n".join([*lines, "log tail:", *tail])

    def _diagnose_live(self, directory: Path, name: str) -> list[str]:
        lines: list[str] = []
        try:
            messages = self.eval(
                """
                const rows = [];
                const model = messageLogModel;
                for (let r = 0; r < Math.min(model.rowCount(), 15); r++) {
                  const index = model.index(r, 0);
                  rows.push(model.data(index, 0x0101) + ': '
                    + model.data(index, 0x0100));
                }
                return rows;
                """,
                timeout=5,
            )
            lines += ["message log, newest first:", *messages]
            if self.camera_open():
                lines.append("no screenshot, a camera view is open")
            else:
                shot = self.screenshot(directory / f"{name}-failure.png")
                lines.append(f"screenshot: {shot}")
        except (DriverError, TimeoutError) as error:
            lines.append(f"driver did not answer: {error}")
        return lines
