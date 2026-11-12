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

"""Localhost server the driver plugin polls for code to run."""

from __future__ import annotations

import json
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class Bridge:
    """Hands commands to the driver and collects its results.

    Paths carry a random token, so other local processes cannot inject code.
    """

    def __init__(self) -> None:
        self.commands: queue.Queue[dict[str, Any]] = queue.Queue()
        self.results: dict[int, dict[str, Any]] = {}
        self.polled = threading.Event()
        self._token = secrets.token_urlsafe(16)
        bridge = self
        prefix = f"/{self._token}/"

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                pass

            def _reply(self, status: int, body: bytes = b"") -> None:
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path != f"{prefix}next":
                    self._reply(404)
                    return
                bridge.polled.set()
                try:
                    command = bridge.commands.get_nowait()
                except queue.Empty:
                    self._reply(200)
                    return
                self._reply(200, json.dumps(command).encode())

            def do_POST(self) -> None:
                if self.path != f"{prefix}result":
                    self._reply(404)
                    return
                length = int(self.headers["Content-Length"])
                result = json.loads(self.rfile.read(length))
                bridge.results[result["id"]] = result
                self._reply(200)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/{self._token}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
