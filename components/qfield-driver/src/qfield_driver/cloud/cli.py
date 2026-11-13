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


"""The `qfield-driver-cloud` command, managing local QFieldCloud stacks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from qfield_driver.cloud.stack import (
    HOSTED,
    SOURCE_ENV,
    QFieldCloudStack,
    StackError,
    down_stale,
    resolve_ref,
)
from qfield_fetch import CACHE_ENV, default_cache_dir

app = typer.Typer(help="Manage local QFieldCloud stacks.", no_args_is_help=True)

Ref = Annotated[
    str,
    typer.Option(help="hosted (what app.qfield.cloud runs), latest or a tag."),
]
CacheDir = Annotated[
    Path | None,
    typer.Option(
        envvar=CACHE_ENV,
        help="qfield-fetch cache, ~/.cache/qfield-fetch by default.",
        show_default=False,
    ),
]

SourceDir = Annotated[
    Path | None,
    typer.Option(
        envvar=SOURCE_ENV,
        help="QFieldCloud checkout of your own, used instead of --ref.",
        show_default=False,
    ),
]

PortOffset = Annotated[
    int,
    typer.Option(
        min=0,
        envvar="QFIELDCLOUD_PORT_OFFSET",
        help="Move every port and the compose project by this offset.",
    ),
]


@app.callback()
def main() -> None:
    logging.basicConfig(level=logging.INFO)


def _cache_dir(cache_dir: Path | None) -> Path:
    return cache_dir.expanduser().resolve() if cache_dir else default_cache_dir()


def _stack(
    ref: str, cache_dir: Path | None, source_dir: Path | None, offset: int = 0
) -> QFieldCloudStack:
    if source_dir:
        return QFieldCloudStack.local(source_dir, _cache_dir(cache_dir), offset)
    return QFieldCloudStack.with_offset(resolve_ref(ref), _cache_dir(cache_dir), offset)


@app.command("ref")
def show_ref(ref: Ref = HOSTED) -> None:
    """Print the tag a ref resolves to."""
    typer.echo(resolve_ref(ref))


@app.command()
def up(
    ref: Ref = HOSTED,
    cache_dir: CacheDir = None,
    source_dir: SourceDir = None,
    port_offset: PortOffset = 0,
) -> None:
    """Build and start a stack, and print its URL."""
    stack = _stack(ref, cache_dir, source_dir, port_offset)
    try:
        stack.up()
    except StackError as error:
        typer.echo(error, err=True)
        raise typer.Exit(1) from error
    typer.echo(stack.url)


@app.command()
def down(
    ref: Ref = HOSTED,
    cache_dir: CacheDir = None,
    source_dir: SourceDir = None,
    port_offset: PortOffset = 0,
) -> None:
    """Remove a stack and its data volumes, keep its images."""
    _stack(ref, cache_dir, source_dir, port_offset).down()


@app.command()
def prune(ref: Ref = HOSTED, cache_dir: CacheDir = None) -> None:
    """Remove the stacks and checkouts of all other releases."""
    for removed in down_stale(_cache_dir(cache_dir), keep=resolve_ref(ref)):
        typer.echo(f"removed {removed}")
