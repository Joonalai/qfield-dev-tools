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

"""A fake GNSS receiver QField reads NMEA from over TCP."""

from __future__ import annotations

import datetime as dt
import math
import socket
import threading
from enum import IntEnum
from functools import partial, reduce
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

SEND_INTERVAL_S = 0.5
MINUTES = 60
DEFAULT_HORIZONTAL_ACCURACY = 0.01
DEFAULT_VERTICAL_ACCURACY = 0.02


class FixQuality(IntEnum):
    """How a receiver computed a fix, the GGA quality indicator.

    Typical errors: GPS metres, DGPS below a metre, FLOAT_RTK decimetres and
    RTK centimetres. QField shows no position for NO_FIX.
    """

    NO_FIX = 0
    GPS = 1
    DGPS = 2
    PPS = 3
    RTK = 4
    FLOAT_RTK = 5
    ESTIMATED = 6
    MANUAL = 7
    SIMULATION = 8

    @property
    def is_valid(self) -> bool:
        """Whether QField accepts a fix of this quality."""
        return self is not FixQuality.NO_FIX


# QGIS takes the quality from the RMC mode unless GGA reports RTK.
_RMC_MODES = {
    FixQuality.GPS: "A",
    FixQuality.DGPS: "D",
    FixQuality.PPS: "P",
    FixQuality.RTK: "R",
    FixQuality.FLOAT_RTK: "F",
    FixQuality.ESTIMATED: "E",
    FixQuality.MANUAL: "M",
    FixQuality.SIMULATION: "S",
}


def _checksum(body: str) -> str:
    return f"{reduce(lambda acc, char: acc ^ ord(char), body, 0):02X}"


def _sentence(body: str) -> bytes:
    return f"${body}*{_checksum(body)}\r\n".encode()


def _angle(value: float, degree_digits: int, positive: str, negative: str) -> str:
    hemisphere = positive if value >= 0 else negative
    value = abs(value)
    degrees = int(value)
    minutes = (value - degrees) * MINUTES
    return f"{degrees:0{degree_digits}d}{minutes:010.7f},{hemisphere}"


def nmea(  # noqa: PLR0913
    latitude: float,
    longitude: float,
    altitude: float = 10.0,
    *,
    horizontal_accuracy: float = DEFAULT_HORIZONTAL_ACCURACY,
    vertical_accuracy: float = DEFAULT_VERTICAL_ACCURACY,
    fix_quality: FixQuality = FixQuality.RTK,
) -> bytes:
    """GGA, RMC and GST sentences of a fix at a WGS84 position, timed now.

    The accuracies are in metres. QField reads the horizontal one from the
    GST latitude and longitude errors and the vertical one from its altitude
    error.
    """
    fix_quality = FixQuality(fix_quality)
    now = dt.datetime.now(dt.UTC)
    time = now.strftime("%H%M%S.00")
    date = now.strftime("%d%m%y")
    lat = _angle(latitude, 2, "N", "S")
    lon = _angle(longitude, 3, "E", "W")
    status = "A" if fix_quality.is_valid else "V"
    mode = _RMC_MODES.get(fix_quality, "N")
    gga = (
        f"GPGGA,{time},{lat},{lon},{int(fix_quality)},12,0.6,{altitude:.1f},M,18.0,M,,"
    )
    rmc = f"GPRMC,{time},{status},{lat},{lon},0.0,0.0,{date},,,{mode}"
    h = f"{horizontal_accuracy:.3f}"
    gst = f"GPGST,{time},{h},{h},{h},0.0,{h},{h},{vertical_accuracy:.3f}"
    return _sentence(gga) + _sentence(rmc) + _sentence(gst)


class NmeaServer:
    """Streams a settable position to every connected client."""

    def __init__(self) -> None:
        self._fix: Callable[[], bytes] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server = socket.create_server(("127.0.0.1", 0))
        self._server.settimeout(SEND_INTERVAL_S)
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def device_id(self) -> str:
        """QField's positioning device id for this receiver."""
        return f"tcp:127.0.0.1:{self._server.getsockname()[1]}"

    def set_position(
        self,
        latitude: float,
        longitude: float,
        *,
        horizontal_accuracy: float = DEFAULT_HORIZONTAL_ACCURACY,
        vertical_accuracy: float = DEFAULT_VERTICAL_ACCURACY,
        fix_quality: FixQuality = FixQuality.RTK,
    ) -> None:
        """Send fixes at a WGS84 position, see :func:`nmea` for the rest."""
        for name, accuracy in (
            ("horizontal_accuracy", horizontal_accuracy),
            ("vertical_accuracy", vertical_accuracy),
        ):
            if not math.isfinite(accuracy) or accuracy < 0:
                msg = f"{name} must be a finite number of metres >= 0, not {accuracy}"
                raise ValueError(msg)
        fix = partial(
            nmea,
            latitude,
            longitude,
            horizontal_accuracy=horizontal_accuracy,
            vertical_accuracy=vertical_accuracy,
            fix_quality=FixQuality(fix_quality),
        )
        with self._lock:
            self._fix = fix

    def clear_position(self) -> None:
        """Stop sending fixes, as a receiver losing the sky would."""
        with self._lock:
            self._fix = None

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._stream, args=(client,), daemon=True).start()

    def _stream(self, client: socket.socket) -> None:
        with client:
            while not self._stop.wait(SEND_INTERVAL_S):
                with self._lock:
                    fix = self._fix
                if fix is None:
                    continue
                try:
                    client.sendall(fix())
                except OSError:
                    return

    def close(self) -> None:
        self._stop.set()
        self._server.close()
