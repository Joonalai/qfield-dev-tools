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

"""The `qfield-fetch` command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from qfield_fetch import cache

if TYPE_CHECKING:
    from collections.abc import Callable

app = typer.Typer(
    help="Download QField AppImages and QField and QFieldCloud sources into one cache.",
    no_args_is_help=True,
)

CacheDir = Annotated[
    Path | None,
    typer.Option(
        envvar=cache.CACHE_ENV,
        help="Cache directory, ~/.cache/qfield-fetch by default.",
        show_default=False,
    ),
]
Update = Annotated[bool, typer.Option(help="Clone again, for a branch that moved.")]


def _echo_result(fetch: Callable[[], object]) -> None:
    try:
        typer.echo(fetch())
    except (ValueError, cache.FetchError) as error:
        typer.echo(error, err=True)
        raise typer.Exit(1) from error


def _resolved(cache_dir: Path | None) -> Path | None:
    return cache_dir.expanduser().resolve() if cache_dir else None


@app.command()
def appimage(
    version: Annotated[str, typer.Argument(help="A release such as 4.2.9, or latest.")],
    cache_dir: CacheDir = None,
) -> None:
    """Download and extract a QField AppImage, and print its AppRun."""
    _echo_result(lambda: cache.appimage(version, _resolved(cache_dir)))


@app.command()
def source(
    ref: Annotated[
        str, typer.Argument(help="A release such as 4.2.9, latest, a tag or a branch.")
    ],
    *,
    update: Update = False,
    cache_dir: CacheDir = None,
) -> None:
    """Clone QField at one ref only, and print the checkout."""
    _echo_result(lambda: cache.qfield_source(ref, _resolved(cache_dir), update=update))


@app.command()
def qfieldcloud(
    ref: Annotated[
        str, typer.Argument(help="A tag such as v26.30, latest or a branch.")
    ],
    *,
    update: Update = False,
    cache_dir: CacheDir = None,
) -> None:
    """Clone QFieldCloud at one ref only, and print the checkout."""
    _echo_result(
        lambda: cache.qfieldcloud_source(ref, _resolved(cache_dir), update=update)
    )


@app.command("list")
def list_entries(cache_dir: CacheDir = None) -> None:
    """List what the cache holds."""
    for entry in cache.entries(_resolved(cache_dir)):
        typer.echo(f"{entry.kind}\t{entry.name}\t{entry.path}")


@app.command()
def remove(
    kind: Annotated[cache.Kind, typer.Argument(help="What to remove.")],
    name: Annotated[str, typer.Argument(help="Name as `list` shows it.")],
    cache_dir: CacheDir = None,
) -> None:
    """Remove one entry from the cache."""
    try:
        removed = cache.remove(kind, name, _resolved(cache_dir))
    except ValueError as error:
        typer.echo(error, err=True)
        raise typer.Exit(1) from error
    if not removed:
        typer.echo(f"No {kind} {name}", err=True)
        raise typer.Exit(1)
