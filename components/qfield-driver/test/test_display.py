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


import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.qfield_app

START_AND_WAIT = """
import sys, time
from qfield_driver.display import start_xvfb
process, _ = start_xvfb(320, 240, die_with_parent=True)
print(process.pid, flush=True)
time.sleep(60)
"""


def test_xvfb_dies_with_the_process_that_started_it() -> None:
    parent = subprocess.Popen(  # noqa: S603 this Python with a fixed script
        [sys.executable, "-c", START_AND_WAIT], stdout=subprocess.PIPE, text=True
    )
    assert parent.stdout is not None
    xvfb = Path(f"/proc/{parent.stdout.readline().strip()}")
    assert xvfb.exists()

    parent.kill()
    parent.wait()
    deadline = time.monotonic() + 10
    while xvfb.exists() and time.monotonic() < deadline:
        time.sleep(0.1)

    assert not xvfb.exists()
