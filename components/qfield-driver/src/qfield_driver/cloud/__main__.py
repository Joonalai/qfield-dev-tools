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

"""Manage the local QFieldCloud: up, down, prune or ref."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from qfield_driver.appimage import default_cache_dir
from qfield_driver.cloud.stack import (
    HOSTED,
    QFieldCloudStack,
    down_stale,
    resolve_ref,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m qfield_driver.cloud")
    parser.add_argument("command", choices=("up", "down", "prune", "ref"))
    parser.add_argument("--ref", default=HOSTED, help="hosted, latest or a tag")
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    ref = resolve_ref(args.ref)
    stack = QFieldCloudStack(ref, args.cache_dir)
    if args.command == "ref":
        print(ref)  # noqa: T201
    elif args.command == "up":
        stack.up()
        print(stack.url)  # noqa: T201
    elif args.command == "down":
        stack.down()
    else:
        for removed in down_stale(args.cache_dir, keep=ref):
            print(f"removed {removed}")  # noqa: T201


if __name__ == "__main__":
    main()
