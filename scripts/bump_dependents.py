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

# Adapted from https://github.com/nlsfi/pinta/blob/main/scripts/bump_dependents.py

"""Raise version requirements of components that depend on a released component.

Prints the names of the changed dependent components, one per line.
"""

import argparse
import re
import sys
import tomllib
from pathlib import Path

COMPONENTS_DIR = Path(__file__).parent.parent / "components"
KEY_PATTERN = re.compile(r"^([A-Za-z0-9_-]+)\s*=")
# A quoted requirement with optional extras, version specifiers and marker
REQUIREMENT_PATTERN = re.compile(
    r'"([A-Za-z0-9_.-]+)\s*(\[[^\]]*\])?(?:\s*[<>=!~][^";]*)?(\s*;[^"]*)?"'
)


def normalize(name: str) -> str:
    """Return the PEP 503 normalized package name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def package_name(component: str) -> str:
    """Return the normalized package name of a component."""
    with (COMPONENTS_DIR / component / "pyproject.toml").open("rb") as file:
        return normalize(tomllib.load(file)["project"]["name"])


def version_range(version: str) -> str:
    """Return a bound that allows the version and compatible later releases.

    Breaking changes only bump the minor version while the major version is zero.
    """
    major, minor = (int(part) for part in version.split(".")[:2])
    upper = f"{major + 1}" if major else f"0.{minor + 1}"
    return f">={version},<{upper}"


def bump_requirements(text: str, dependency: str, version: str) -> str:
    """Set the version range of the dependency in the project requirements."""

    def replace(match: re.Match[str]) -> str:
        name, extras, marker = match.group(1), match.group(2), match.group(3)
        if normalize(name) != dependency:
            return match.group(0)
        return f'"{name}{extras or ""}{version_range(version)}{marker or ""}"'

    table = key = ""
    lines = []
    for line in text.splitlines(keepends=True):
        if line.startswith("["):
            table, key = line.strip(), ""
        elif found := KEY_PATTERN.match(line):
            key = found.group(1)
        if (table, key) == ("[project]", "dependencies") or (
            table == "[project.optional-dependencies]" and key
        ):
            lines.append(REQUIREMENT_PATTERN.sub(replace, line))
        else:
            lines.append(line)
    return "".join(lines)


def main() -> None:
    """Bump the requirements and print the changed components."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", help="Released component directory name.")
    parser.add_argument("version", help="Released version.")
    args = parser.parse_args()

    dependency = package_name(args.component)
    for path in sorted(COMPONENTS_DIR.glob("*/pyproject.toml")):
        if path.parent.name == args.component:
            continue
        text = path.read_text()
        new_text = bump_requirements(text, dependency, args.version)
        if new_text != text:
            path.write_text(new_text)
            sys.stdout.write(f"{path.parent.name}\n")


if __name__ == "__main__":
    main()
