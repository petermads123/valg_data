"""Command line interface: `python -m dkvalg replay` and `python -m dkvalg poll`."""

import argparse
import math
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import TextIO

from dkvalg.diff import (
    LeaderChanged,
    PartyResultChanged,
    ProgressChanged,
    StatusChanged,
    diff_elections,
)
from dkvalg.errors import FeedError
from dkvalg.model import CountingProgress, Election, Place, PlaceType
from dkvalg.sources.capture import CaptureReplay, Recorder, is_capture_directory
from dkvalg.sources.directory import load_election
from dkvalg.sources.http_source import (
    DEFAULT_INTERVAL,
    MIN_INTERVAL,
    HttpSource,
    Transport,
    overview_url,
    poll,
    urllib_transport,
    utc_now,
)
from dkvalg.sources.replay import ReplaySource

_DEFAULT_SPEED = 600.0
_LEADER_LEVELS = frozenset({PlaceType.COUNTRY, PlaceType.LANDSDEL, PlaceType.STORKREDS})
_DIFF_HELP = "also print leader, seat and status changes and the counting progress"


def _speed(text: str) -> float:
    """Parse a positive speed; `inf` is allowed."""
    try:
        value = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid speed {text!r}") from error
    if math.isnan(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"speed must be positive, got {text!r}")
    return value


def _interval(text: str) -> float:
    """Parse a poll interval: finite and at least `MIN_INTERVAL`."""
    try:
        value = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid interval {text!r}") from error
    if not math.isfinite(value) or value < MIN_INTERVAL:
        raise argparse.ArgumentTypeError(
            f"interval must be finite and at least {MIN_INTERVAL:g} seconds, "
            f"got {text!r}"
        )
    return value


def _cycles(text: str) -> int:
    """Parse a cycle count: an integer of at least 1."""
    try:
        value = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid cycle count {text!r}") from error
    if value < 1:
        raise argparse.ArgumentTypeError(f"cycles must be at least 1, got {text!r}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    """Build the parser with its `replay` and `poll` subcommands."""
    parser = argparse.ArgumentParser(prog="dkvalg", description="Danish election data.")
    commands = parser.add_subparsers(dest="command", title="commands")
    replay = commands.add_parser(
        "replay", help="replay a saved feed directory or a capture directory"
    )
    replay.add_argument(
        "directory",
        type=Path,
        help="directory laid out as DST serves it, or a capture directory",
    )
    replay.add_argument(
        "--speed",
        type=_speed,
        default=_DEFAULT_SPEED,
        help="time compression, a positive number or inf (default: %(default)s)",
    )
    replay.add_argument("--diff", action="store_true", help=_DIFF_HELP)
    live = commands.add_parser(
        "poll", help="poll DST's live feeds and print the places that change"
    )
    live.add_argument(
        "location",
        help="election id (Valg2546527), or the URL of its folder or valgdag.xml",
    )
    live.add_argument(
        "--interval",
        type=_interval,
        default=DEFAULT_INTERVAL,
        help=f"seconds between polls, at least {MIN_INTERVAL:g} (default: %(default)s)",
    )
    live.add_argument(
        "--record", type=Path, metavar="DIR", help="save every received feed in DIR"
    )
    live.add_argument(
        "--cycles", type=_cycles, help="stop after this many polls (default: no limit)"
    )
    live.add_argument("--diff", action="store_true", help=_DIFF_HELP)
    return parser


def _print_table(election: Election, out: TextIO) -> None:
    """Print the national result table, "Uden for partier" last.

    The letter column is as wide as the longest letter plus one, at least 3, so
    the answers `JA` and `NEJ` of a referendum do not run into their names.
    """
    countries = election.of_type(PlaceType.COUNTRY)
    for country in countries:
        out.write(f"\n{country.name}: {country.status_text or country.status.name}\n")
        ordered = [p for p in country.parties if p.is_party] + [
            p for p in country.parties if not p.is_party
        ]
        letters = [party.letter or "-" for party in ordered]
        width = max([3, *(len(letter) + 1 for letter in letters)])
        for party, letter in zip(ordered, letters, strict=True):
            seats = "-" if party.seats is None else str(party.seats)
            out.write(
                f"{letter:<{width}}{party.name:<48}{party.percent:>6.1f}%"
                f"{party.votes:>11}{seats:>6}\n"
            )


def _place_line(at: datetime, progress: CountingProgress, place: Place) -> str:
    """Format one changed place: time, counting progress, type and name."""
    stamp = at.isoformat(sep=" ")
    counted = str(progress)
    return f"{stamp}  {counted:>5}  {place.place_type.value} {place.name}\n"


def _diff_lines(at: datetime, previous: Election | None, current: Election) -> str:
    """Format the notable changes between two snapshots, one line each.

    Notable: a leader change at a country, landsdel or storkreds; a seat change,
    including seats appearing; a status change; the counting progress.
    """
    stamp = at.isoformat(sep=" ")
    lines: list[str] = []
    try:
        changes = diff_elections(previous, current)
    except ValueError as error:
        raise FeedError(str(error)) from error
    for change in changes:
        match change:
            case LeaderChanged(place=place, before=before, after=after):
                if place.place_type in _LEADER_LEVELS:
                    old = "-" if before is None else before.letter or "-"
                    new = after.letter or "-"
                    lines.append(
                        f"{stamp}  leader {place.place_type.value} {place.name}: "
                        f"{old} -> {new}"
                    )
            case PartyResultChanged(place=place, before=before, after=after):
                was = None if before is None else before.seats
                if after.seats is not None and (was is None or after.seats != was):
                    old_seats = "-" if was is None else str(was)
                    lines.append(
                        f"{stamp}  seats {place.place_type.value} {place.name}: "
                        f"{after.letter or '-'} {old_seats} -> {after.seats}"
                    )
            case StatusChanged(place=place, before=before, after=after):
                lines.append(
                    f"{stamp}  status {place.place_type.value} {place.name}: "
                    f"{before.name} -> {after.name}"
                )
            case ProgressChanged(before=before, after=after):
                lines.append(f"{stamp}  progress {before} -> {after}")
    return "".join(f"{line}\n" for line in lines)


def _replay(
    directory: Path,
    speed: float,
    out: TextIO,
    sleep: Callable[[float], None],
    show_diff: bool,
) -> None:
    """Load the directory, replay it, print each step and the final table."""
    if is_capture_directory(directory):
        _replay_capture(directory, speed, out, sleep, show_diff)
        return
    election = load_election(directory)
    source = ReplaySource(election, speed=speed, sleep=sleep)
    final = source.initial()
    for step in source:
        previous, final = final, step.election
        out.write(_place_line(step.at, step.progress, step.place))
        if show_diff:
            out.write(_diff_lines(step.at, previous, final))
        out.flush()
    _print_table(final, out)


def _replay_capture(
    directory: Path,
    speed: float,
    out: TextIO,
    sleep: Callable[[float], None],
    show_diff: bool,
) -> None:
    """Replay a capture directory: a line per changed place, then the table."""
    final: Election | None = None
    for step in CaptureReplay(directory, speed=speed, sleep=sleep):
        previous, final = final, step.election
        for place in step.changed:
            out.write(_place_line(step.at, step.progress, place))
        if show_diff:
            out.write(_diff_lines(step.at, previous, final))
        out.flush()
    if final is not None:
        _print_table(final, out)


def _poll(
    args: argparse.Namespace,
    out: TextIO,
    err: TextIO,
    sleep: Callable[[float], None],
    transport: Transport,
    clock: Callable[[], datetime],
) -> int:
    """Poll until the cycle limit or Ctrl-C; the exit code of the loop."""
    try:
        overview_url(args.location)
    except ValueError as error:
        err.write(f"error: {error}\n")
        return 2
    recorder = None if args.record is None else Recorder(args.record)
    source = HttpSource(
        args.location, transport=transport, recorder=recorder, clock=clock
    )
    failed = False
    previous: Election | None = None
    try:
        for cycle in poll(
            source, interval=args.interval, max_cycles=args.cycles, sleep=sleep
        ):
            failed = cycle.error is not None
            if cycle.error is not None:
                err.write(f"error: {cycle.error}\n")
                err.flush()
                continue
            if cycle.election is not None:
                progress = cycle.election.counting_progress()
                for place in cycle.changed:
                    out.write(_place_line(cycle.at, progress, place))
                if args.diff:
                    out.write(_diff_lines(cycle.at, previous, cycle.election))
                previous = cycle.election
            out.flush()
    except KeyboardInterrupt:
        return 130
    return 1 if failed else 0


def run(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
    sleep: Callable[[float], None] = time.sleep,
    transport: Transport = urllib_transport,
    clock: Callable[[], datetime] = utc_now,
) -> int:
    """Run the command line interface.

    Args:
        argv: Arguments after the program name; `sys.argv[1:]` when None.
        out: Where normal output goes; `sys.stdout` when None.
        err: Where errors go; `sys.stderr` when None.
        sleep: Called with the seconds to wait between replay steps or polls.
        transport: How `poll` fetches; replace it to run without a network.
        clock: The timezone-aware clock `poll` stamps its polls with.

    Returns:
        The exit code: 0 ok, 1 for a `FeedError` (or a `poll` whose last cycle
        failed), 2 for bad arguments or a bad location, 130 for Ctrl-C in `poll`.
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
        if args.command == "poll":
            return _poll(args, out, err, sleep, transport, clock)
        _replay(args.directory, args.speed, out, sleep, args.diff)
    except FeedError as error:
        err.write(f"error: {error}\n")
        return 1
    return 0


def main() -> None:
    """Run the command line interface and exit with its code."""
    raise SystemExit(run())


if __name__ == "__main__":
    main()
