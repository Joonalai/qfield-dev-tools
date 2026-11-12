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
import socket
import threading
from functools import reduce

SEND_INTERVAL_S = 0.5
MINUTES = 60


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


def nmea(latitude: float, longitude: float, altitude: float = 10.0) -> bytes:
    """GGA and RMC sentences of a fix at a WGS84 position, timed now."""
    now = dt.datetime.now(dt.UTC)
    time = now.strftime("%H%M%S.00")
    date = now.strftime("%d%m%y")
    lat = _angle(latitude, 2, "N", "S")
    lon = _angle(longitude, 3, "E", "W")
    gga = f"GPGGA,{time},{lat},{lon},4,12,0.6,{altitude:.1f},M,18.0,M,,"
    rmc = f"GPRMC,{time},A,{lat},{lon},0.0,0.0,{date},,,R"
    gst = f"GPGST,{time},0.010,0.010,0.010,0.0,0.010,0.010,0.020"
    return _sentence(gga) + _sentence(rmc) + _sentence(gst)


class NmeaServer:
    """Streams a settable position to every connected client."""

    def __init__(self) -> None:
        self._position: tuple[float, float] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server = socket.create_server(("127.0.0.1", 0))
        self._server.settimeout(SEND_INTERVAL_S)
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def device_id(self) -> str:
        """QField's positioning device id for this receiver."""
        return f"tcp:127.0.0.1:{self._server.getsockname()[1]}"

    def set_position(self, latitude: float, longitude: float) -> None:
        with self._lock:
            self._position = (latitude, longitude)

    def clear_position(self) -> None:
        """Stop sending fixes, as a receiver losing the sky would."""
        with self._lock:
            self._position = None

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
                    position = self._position
                if position is None:
                    continue
                try:
                    client.sendall(nmea(*position))
                except OSError:
                    return

    def close(self) -> None:
        self._stop.set()
        self._server.close()
