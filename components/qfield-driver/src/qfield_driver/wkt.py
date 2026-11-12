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

"""Plain geometry math on WKT, QField does not expose length or interpolate to QML."""

from __future__ import annotations

import itertools
import math
import re

NUMBER = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"


def coordinates(wkt: str) -> list[tuple[float, float]]:
    """XY of every vertex, Z and M dropped."""
    body = wkt[wkt.index("(") :]
    points = []
    for chunk in body.replace("(", "").replace(")", "").split(","):
        numbers = [float(number) for number in re.findall(NUMBER, chunk)]
        points.append((numbers[0], numbers[1]))
    return points


def length(wkt: str) -> float:
    return sum(
        math.dist(start, end) for start, end in itertools.pairwise(coordinates(wkt))
    )


def interpolate(wkt: str, distance: float) -> tuple[float, float]:
    """Point at a distance along a line, the end when past it."""
    points = coordinates(wkt)
    for start, end in itertools.pairwise(points):
        segment = math.dist(start, end)
        if distance <= segment:
            ratio = distance / segment if segment else 0
            return (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
        distance -= segment
    return points[-1]
