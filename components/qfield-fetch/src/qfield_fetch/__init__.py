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

"""QField AppImages and QField and QFieldCloud sources, kept in one cache."""

from qfield_fetch.cache import (
    CACHE_ENV,
    LATEST,
    QFIELD,
    QFIELDCLOUD,
    Entry,
    FetchError,
    Kind,
    appimage,
    default_cache_dir,
    entries,
    entry_path,
    latest_release,
    qfield_source,
    qfieldcloud_source,
    release_version,
    remove,
)

__all__ = [
    "CACHE_ENV",
    "LATEST",
    "QFIELD",
    "QFIELDCLOUD",
    "Entry",
    "FetchError",
    "Kind",
    "appimage",
    "default_cache_dir",
    "entries",
    "entry_path",
    "latest_release",
    "qfield_source",
    "qfieldcloud_source",
    "release_version",
    "remove",
]
