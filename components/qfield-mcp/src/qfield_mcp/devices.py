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

"""Running devices of one server, and cleanup after servers that were killed."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import tempfile
import threading
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from qfield_driver.app import QFieldApp

PREFIX = "qfield-mcp-"
OWNER_FILE = "owner"
GROUPS_SUFFIX = ".groups.json"
# Names become file names in the work directory
NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _cmdline(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/cmdline").read_text(errors="replace")
    except OSError:
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def clean_orphans(temp_dir: Path | None = None) -> list[str]:
    """Stop devices of servers that died without cleanup.

    Their directories are removed. Return the stopped device names.

    A process group is only signalled while its leader still runs the
    command recorded at start, so a reused pid is left alone.
    """
    stopped: list[str] = []
    for work_dir in sorted(Path(temp_dir or tempfile.gettempdir()).glob(PREFIX + "*")):
        if not _own_directory(work_dir) or not _owner_died(work_dir):
            continue
        stopped.extend(
            groups_file.name.removesuffix(GROUPS_SUFFIX)
            for groups_file in work_dir.glob("*" + GROUPS_SUFFIX)
            if _stop_groups(groups_file)
        )
        shutil.rmtree(work_dir, ignore_errors=True)
    return stopped


def _own_directory(path: Path) -> bool:
    """Guard against directories other users planted in the shared temp dir."""
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()


def _owner_died(work_dir: Path) -> bool:
    try:
        owner = int((work_dir / OWNER_FILE).read_text())
    except (OSError, ValueError):
        return False
    return not _alive(owner)


def _stop_groups(groups_file: Path) -> bool:
    try:
        groups = json.loads(groups_file.read_text())
    except (OSError, ValueError):
        return False
    for pgid, cmdline in groups.items():
        if _cmdline(int(pgid)) == cmdline:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(int(pgid), signal.SIGKILL)
    return True


class Devices:
    """Devices by name, each used by one tool call at a time."""

    def __init__(self, temp_dir: Path | None = None) -> None:
        self.work_dir = Path(tempfile.mkdtemp(prefix=PREFIX, dir=temp_dir))
        (self.work_dir / OWNER_FILE).write_text(str(os.getpid()))
        self._apps: dict[str, QFieldApp] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._registry = threading.Lock()

    def names(self) -> list[str]:
        with self._registry:
            return sorted(self._apps)

    def reserve(self, name: str) -> threading.RLock:
        if not NAME_PATTERN.fullmatch(name):
            msg = f"Device name {name!r} must match {NAME_PATTERN.pattern}"
            raise ValueError(msg)
        with self._registry:
            if name in self._locks:
                msg = f"Device {name!r} is already running"
                raise ValueError(msg)
            lock = self._locks[name] = threading.RLock()
            lock.acquire()
            return lock

    def add(self, name: str, app: QFieldApp) -> None:
        """Register a started device and record its process groups."""
        groups = {str(pgid): _cmdline(pgid) for pgid in app.process_groups.values()}
        target = self.work_dir / f"{name}{GROUPS_SUFFIX}"
        partial = target.with_suffix(".tmp")
        partial.write_text(json.dumps(groups))
        partial.replace(target)
        with self._registry:
            self._apps[name] = app

    def forget(self, name: str) -> None:
        """Drop a device that failed to start or was stopped."""
        with self._registry:
            self._apps.pop(name, None)
            self._locks.pop(name, None)
        (self.work_dir / f"{name}{GROUPS_SUFFIX}").unlink(missing_ok=True)

    @contextmanager
    def use(self, name: str) -> Iterator[QFieldApp]:
        """Hold a device for one tool call."""
        with self._registry:
            lock = self._locks.get(name)
        if lock is None:
            msg = f"No device {name!r}, running: {self.names()}"
            raise ValueError(msg)
        with lock:
            with self._registry:
                # Stopped, and maybe started again, while this call waited.
                current = self._locks.get(name) is lock
                app = self._apps.get(name) if current else None
            if app is None:
                msg = f"Device {name!r} stopped or failed to start"
                raise ValueError(msg)
            yield app

    def stop(self, name: str) -> None:
        with self.use(name) as app:
            try:
                app.close()
            finally:
                self.forget(name)

    def stop_all(self) -> None:
        """Stop every device at exit, without waiting for calls in progress."""
        with self._registry:
            apps = list(self._apps.values())
            self._apps.clear()
            self._locks.clear()
        for app in apps:
            with suppress(Exception):
                app.close()
        shutil.rmtree(self.work_dir, ignore_errors=True)
