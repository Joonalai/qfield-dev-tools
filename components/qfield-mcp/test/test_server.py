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

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from qfield_mcp import server


def call(tool: str, **arguments: Any) -> Any:  # noqa: ANN401
    return asyncio.run(server.server.call_tool(tool, arguments))


@pytest.fixture
def device() -> Iterator[str]:
    call("start_device", name="mcp")
    yield "mcp"
    if "mcp" in server.devices:
        call("stop_device", name="mcp")


@pytest.mark.qfield_app
def test_device_can_be_explored_and_driven(device: str) -> None:
    assert server.devices.keys() == {device}
    assert call("eval_js", code="return 1 + 1", device=device) is not None
    tree = str(call("item_tree", device=device))
    assert "#mapCanvas" in tree
    assert "tapped" in str(call("tap", device=device, x=10, y=10))
    image = call("screenshot", device=device)
    assert "image" in str(image).lower()
    call("stop_device", name=device)
    assert not server.devices
