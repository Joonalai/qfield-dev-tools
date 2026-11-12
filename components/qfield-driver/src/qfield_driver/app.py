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
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Self

from qfield_driver.bridge import Bridge
from qfield_driver.display import Pointer, start_xvfb, terminate
from qfield_driver.positioning import NmeaServer

LOGGER = logging.getLogger(__name__)

DRIVER_NAME = "qfield_driver"
DRIVER_SOURCE = Path(__file__).parent / "driver" / DRIVER_NAME
PLUGINS_DIR = "Documents/QField Documents/QField/plugins"
SCREEN_SIZE = (1280, 800)
START_TIMEOUT_S = 90
POLL_S = 0.02
# QField opens the host's webcam for a photo, so hide every camera from it.
NO_CAMERAS = (
    'for d in /dev/video*; do [ -e "$d" ] || continue; '
    'mount --bind /dev/null "$d" || exit 3; done; exec "$@"'
)
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


def seed_profile(
    home: Path, endpoint: str, app_plugins: dict[str, Path] | None = None
) -> None:
    """Install the driver and other app plugins, and turn telemetry off."""
    driver = install_app_plugin(home, DRIVER_SOURCE, DRIVER_NAME)
    driver.write_text(driver.read_text().replace("__ENDPOINT__", endpoint))
    plugins = _plugin_settings(driver, DRIVER_NAME)
    for uuid, source in (app_plugins or {}).items():
        plugins += _plugin_settings(install_app_plugin(home, source, uuid), uuid)
    conf = home / ".config/OPENGIS.ch/QField.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(
        "[General]\n"
        "enableInfoCollection=false\n\n"
        "[QField]\n"
        "showMapCanvasGuide=false\n\n"
        "[qfield]\n" + plugins
    )


class QFieldApp:
    """One QField process. Never touches the user's profile or other instances.

    :param app_plugins: App plugins to install and enable, by uuid
    """

    def __init__(
        self,
        app_run: Path,
        home: Path,
        *,
        app_plugins: dict[str, Path] | None = None,
        screen_size: tuple[int, int] = SCREEN_SIZE,
    ) -> None:
        self._app_run = app_run
        self.home = home
        self.log = home.parent / f"{home.name}.log"
        self._app_plugins = app_plugins
        self._screen_size = screen_size
        self._sequence = 0
        self._log_offset = 0
        self._bridge = Bridge()
        self._process: subprocess.Popen[bytes] | None = None
        self._xvfb: subprocess.Popen[bytes] | None = None
        self._pointer: Pointer | None = None
        self._gnss: NmeaServer | None = None

    def __enter__(self) -> Self:
        try:
            self._start()
        except BaseException:
            self.close()
            raise
        return self

    def _start(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        seed_profile(self.home, self._bridge.endpoint, self._app_plugins)
        self._xvfb, display_number = start_xvfb(*self._screen_size)
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
            )
        deadline = time.monotonic() + START_TIMEOUT_S
        while not self._bridge.polled.wait(0.5):
            if self._process.poll() is not None or time.monotonic() > deadline:
                tail = self.log_text()[-2000:]
                msg = f"QField or its driver did not start:\n{tail}"
                raise DriverError(msg)
        # Without a window manager nothing maximizes the window.
        width, height = self._screen_size
        self.eval(
            "const window = iface.mainWindow();"
            f"window.width = {width}; window.height = {height};"
        )

    def __exit__(self, *_exc: object) -> None:
        self.close()

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
        """Wait until the log holds `line` at least `count` times."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.log_text().count(line) >= count:
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

    def unhost_plugin(self) -> None:
        self.eval(
            "if (driver._pqfHosted) driver._pqfHosted.destroy();"
            "driver._pqfHosted = null;"
        )

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

    def screenshot(self, path: Path) -> Path:
        """Save a grab of the whole window."""
        self.eval(
            "state.saved = null; scene().grabToImage("
            f"result => state.saved = result.saveToFile({json.dumps(str(path))}));"
        )
        if not self.wait("return state.saved !== null && [state.saved]", 10)[0]:
            msg = f"Could not save a screenshot to {path}"
            raise DriverError(msg)
        return path
