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

"""A private X server and real pointer and key input on it."""

from __future__ import annotations

import ctypes
import os
import select
import signal
import subprocess
import time

from Xlib import XK, X, display
from Xlib.ext import xtest

LEFT_BUTTON = 1
LATIN1_END = 0x100
UNICODE_KEYSYM = 0x01000000
KEY_NAMES = {
    " ": "space",
    ".": "period",
    ",": "comma",
    "-": "minus",
    "_": "underscore",
    ":": "colon",
    "/": "slash",
    "\n": "Return",
}
HOVER_S = 0.2
PRESS_S = 0.05
LONG_PRESS_S = 1.0
DRAG_STEPS = 10
TERMINATE_TIMEOUT_S = 10
XVFB_START_TIMEOUT_S = 30
PR_SET_PDEATHSIG = 1
# Loaded before forking, children only call into it.
_LIBC = ctypes.CDLL(None, use_errno=True)


class InputError(RuntimeError):
    """The X server could not deliver an input event."""


class DisplayError(RuntimeError):
    """Xvfb did not start."""


def kill_with_parent() -> None:
    """Have the kernel kill the calling child once its parent thread exits.

    Pass as `preexec_fn`. Only for children started from a thread that lives as
    long as they should, such as pytest's main thread.
    """
    _LIBC.prctl(PR_SET_PDEATHSIG, signal.SIGKILL)


def start_xvfb(
    width: int, height: int, *, die_with_parent: bool = False
) -> tuple[subprocess.Popen[bytes], int]:
    """Start a private X server, and return it with its display number."""
    read_end, write_end = os.pipe()
    with os.fdopen(read_end) as pipe:
        try:
            process = subprocess.Popen(  # noqa: S603 fixed Xvfb command
                [
                    *("Xvfb", "-displayfd", str(write_end), "-nolisten", "tcp"),
                    *("-screen", "0", f"{width}x{height}x24"),
                ],
                pass_fds=(write_end,),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                preexec_fn=kill_with_parent if die_with_parent else None,  # noqa: PLW1509 only calls prctl
            )
        finally:
            os.close(write_end)
        ready, _, _ = select.select([pipe], [], [], XVFB_START_TIMEOUT_S)
        line = pipe.readline() if ready else ""
    if not line.strip().isdigit():
        terminate(process)
        msg = f"Xvfb reported no display within {XVFB_START_TIMEOUT_S} s"
        raise DisplayError(msg)
    return process, int(line)


def terminate(process: subprocess.Popen[bytes]) -> None:
    """Stop one started process group, never anything found by name."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(TERMINATE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(TERMINATE_TIMEOUT_S)
    except ProcessLookupError:
        pass


class Pointer:
    """Real X pointer and key events, through the app's normal input path."""

    def __init__(self, display_number: int) -> None:
        self._display = display.Display(f":{display_number}")

    def _send(self, kind: int, **kwargs: int) -> None:
        xtest.fake_input(self._display, kind, **kwargs)
        self._display.sync()

    def move(self, x: int, y: int) -> None:
        self._send(X.MotionNotify, x=x, y=y)

    def click(self, x: int, y: int, hold: float = PRESS_S) -> None:
        self.move(x, y)
        time.sleep(HOVER_S)
        self._send(X.ButtonPress, detail=LEFT_BUTTON)
        time.sleep(hold)
        self._send(X.ButtonRelease, detail=LEFT_BUTTON)

    def long_press(self, x: int, y: int) -> None:
        self.click(x, y, LONG_PRESS_S)

    def drag(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        self.move(*start)
        time.sleep(HOVER_S)
        self._send(X.ButtonPress, detail=LEFT_BUTTON)
        for step in range(1, DRAG_STEPS + 1):
            x = start[0] + (end[0] - start[0]) * step // DRAG_STEPS
            y = start[1] + (end[1] - start[1]) * step // DRAG_STEPS
            self.move(x, y)
            time.sleep(PRESS_S)
        self._send(X.ButtonRelease, detail=LEFT_BUTTON)

    def type_text(self, text: str) -> None:
        for char in text:
            self.key(KEY_NAMES.get(char, char))

    def _spare_keycode(self, keysym: int) -> int:
        """Bind a keysym missing from the layout, `ä` on a US one, to a free key."""
        first = self._display.display.info.min_keycode
        last = self._display.display.info.max_keycode
        mapping = self._display.get_keyboard_mapping(first, last - first + 1)
        for offset in range(len(mapping) - 1, -1, -1):
            if not any(mapping[offset]):
                keycode = first + offset
                self._display.change_keyboard_mapping(keycode, [(keysym, keysym)])
                self._display.sync()
                time.sleep(PRESS_S)
                return keycode
        msg = f"No free key for keysym {keysym:#x}"
        raise InputError(msg)

    def key(self, name: str) -> None:
        """Press and release one key by its keysym name, `Return` or `a`."""
        keysym = XK.string_to_keysym(name)
        if not keysym and len(name) == 1:
            # Latin-1 keysyms equal their code points, others are offset.
            code = ord(name)
            keysym = code if code < LATIN1_END else UNICODE_KEYSYM + code
        keycode = self._display.keysym_to_keycode(keysym)
        if not keycode and keysym:
            keycode = self._spare_keycode(keysym)
        if not keycode:
            msg = f"No key for {name!r}"
            raise InputError(msg)
        shifted = self._display.keycode_to_keysym(keycode, 0) != keysym
        shift = self._display.keysym_to_keycode(XK.XK_Shift_L)
        if shifted:
            self._send(X.KeyPress, detail=shift)
        self._send(X.KeyPress, detail=keycode)
        time.sleep(PRESS_S)
        self._send(X.KeyRelease, detail=keycode)
        if shifted:
            self._send(X.KeyRelease, detail=shift)

    def close(self) -> None:
        self._display.close()
