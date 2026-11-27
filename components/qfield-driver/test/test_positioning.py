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
import math
from functools import reduce

import pytest

from qfield_driver.positioning import FixQuality, NmeaServer, nmea


def _fields(sentences: bytes) -> dict[str, list[str]]:
    by_type = {}
    for line in sentences.decode().split("\r\n"):
        if not line:
            continue
        body, checksum = line.removeprefix("$").split("*")
        assert int(checksum, 16) == reduce(lambda acc, c: acc ^ ord(c), body, 0)
        fields = body.split(",")
        by_type[fields[0][2:]] = fields
    return by_type


def test_default_fix_is_fixed_rtk_at_one_centimetre() -> None:
    fields = _fields(nmea(60.0, 24.0))

    assert fields["GGA"][6] == "4"
    assert fields["RMC"][2] == "A"
    assert fields["RMC"][12] == "R"
    assert fields["GST"][6:9] == ["0.010", "0.010", "0.020"]


def test_accuracy_goes_to_gst_sigmas() -> None:
    gst = _fields(nmea(60.0, 24.0, horizontal_accuracy=4.5, vertical_accuracy=7.25))[
        "GST"
    ]

    lat_sigma, lon_sigma, alt_sigma = map(float, gst[6:9])
    # QGIS reads the horizontal accuracy as the quadratic mean of the
    # latitude and longitude errors.
    assert math.sqrt((lat_sigma**2 + lon_sigma**2) / 2) == 4.5
    assert alt_sigma == 7.25


@pytest.mark.parametrize(
    ("quality", "status", "mode"),
    [
        (FixQuality.GPS, "A", "A"),
        (FixQuality.DGPS, "A", "D"),
        (FixQuality.FLOAT_RTK, "A", "F"),
        (FixQuality.NO_FIX, "V", "N"),
    ],
)
def test_rmc_mode_follows_fix_quality(
    quality: FixQuality, status: str, mode: str
) -> None:
    """QGIS prefers the RMC mode to a GGA quality other than RTK."""
    fields = _fields(nmea(60.0, 24.0, fix_quality=quality))

    assert fields["GGA"][6] == str(int(quality))
    assert fields["RMC"][2] == status
    assert fields["RMC"][12] == mode


@pytest.mark.parametrize("accuracy", [-1.0, math.nan, math.inf])
def test_set_position_rejects_impossible_accuracy(accuracy: float) -> None:
    server = NmeaServer()
    try:
        with pytest.raises(ValueError, match="horizontal_accuracy"):
            server.set_position(60.0, 24.0, horizontal_accuracy=accuracy)
        with pytest.raises(ValueError, match="vertical_accuracy"):
            server.set_position(60.0, 24.0, vertical_accuracy=accuracy)
    finally:
        server.close()
