"""Command line interface: `python -m dkvalg replay <dir> [--speed N]`."""

import argparse
import math
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import TextIO

from dkvalg.errors import FeedError
from dkvalg.model import Election, PlaceType
from dkvalg.sources.directory import load_election
from dkvalg.sources.replay import ReplaySource

_DEFAULT_SPEED = 600.0


def _speed(text: str) -> float:
    """Parse a positive speed; `inf` is allowed."""
    try:
        value = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid speed {text!r}") from error
    if math.isnan(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"speed must be positive, got {text!r}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    """Build the parser with its `replay` subcommand."""
    parser = argparse.ArgumentParser(prog="dkvalg", description="Danish election data.")
    commands = parser.add_subparsers(dest="command", title="commands")
    replay = commands.add_parser(
        "replay", help="replay a saved Folketingsvalg feed directory"
    )
    replay.add_argument(
        "directory", type=Path, help="directory laid out as DST serves it"
    )
    replay.add_argument(
        "--speed",
        type=_speed,
        default=_DEFAULT_SPEED,
        help="time compression, a positive number or inf (default: %(default)s)",
    )
    return parser


def _print_table(election: Election, out: TextIO) -> None:
    """Print the national result table, "Uden for partier" last."""
    countries = election.of_type(PlaceType.COUNTRY)
    for country in countries:
        out.write(f"\n{country.name}: {country.status_text or country.status.name}\n")
        ordered = [p for p in country.parties if p.is_party] + [
            p for p in country.parties if not p.is_party
        ]
        for party in ordered:
            seats = "-" if party.seats is None else str(party.seats)
            letter = party.letter or "-"
            out.write(
                f"{letter:<3}{party.name:<48}{party.percent:>6.1f}%"
                f"{party.votes:>11}{seats:>6}\n"
            )


def _replay(
    directory: Path,
    speed: float,
    out: TextIO,
    sleep: Callable[[float], None],
) -> None:
    """Load the directory, replay it, print each step and the final table."""
    election = load_election(directory)
    source = ReplaySource(election, speed=speed, sleep=sleep)
    final = source.initial()
    for step in source:
        final = step.election
        stamp = step.at.isoformat(sep=" ")
        progress = str(step.progress)
        out.write(
            f"{stamp}  {progress:>5}  {step.place.place_type.value} {step.place.name}\n"
        )
        out.flush()
    _print_table(final, out)


def run(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run the command line interface.

    Args:
        argv: Arguments after the program name; `sys.argv[1:]` when None.
        out: Where normal output goes; `sys.stdout` when None.
        err: Where errors go; `sys.stderr` when None.
        sleep: Called with the seconds to wait between replay steps.

    Returns:
        The exit code: 0 ok, 1 for a `FeedError`, 2 for bad arguments.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    parser = _build_parser()
    arguments = sys.argv[1:] if argv is None else list(argv)
    try:
        # argparse writes usage and errors to sys.stdout/sys.stderr and exits;
        # redirect them to the injected streams and turn the exit into a code.
        with redirect_stdout(out), redirect_stderr(err):
            args = parser.parse_args(arguments)
    except SystemExit as exit_request:
        return exit_request.code if isinstance(exit_request.code, int) else 2
    if args.command is None:
        parser.print_help(out)
        return 0
    try:
        _replay(args.directory, args.speed, out, sleep)
    except FeedError as error:
        err.write(f"error: {error}\n")
        return 1
    return 0


def main() -> None:
    """Run the command line interface and exit with its code."""
    raise SystemExit(run())


if __name__ == "__main__":
    main()
