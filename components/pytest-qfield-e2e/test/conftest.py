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

import shutil
from pathlib import Path

import pytest

# Shares the QField test project with pytest-qfield
DATA = Path(__file__).parents[2] / "pytest-qfield" / "test" / "data"


@pytest.fixture
def project_file(tmp_path: Path) -> Path:
    """Copy the shared QField test project."""
    target = tmp_path / "project"
    shutil.copytree(DATA / "qfield_project", target)
    return target / "pytest-qfield-project_qfield.qgs"


@pytest.fixture
def simple_plugin() -> Path:
    return DATA / "simple_plugin"
