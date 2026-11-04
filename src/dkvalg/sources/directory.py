"""Read a directory laid out as DST serves it into an `Election`."""

from collections.abc import Callable
from pathlib import Path

from dkvalg.adapters.dst_feed import parse_place, unreported_place
from dkvalg.adapters.registry import parse_any_overview
from dkvalg.errors import FeedError
from dkvalg.model import Election, Place

_OVERVIEW_NAME = "valgdag.xml"


def _read(path: Path) -> bytes:
    """Read a feed file, or raise `FeedError` naming it."""
    try:
        return path.read_bytes()
    except FileNotFoundError as error:
        raise FeedError(f"feed file not found: {path}") from error
    except OSError as error:
        raise FeedError(f"cannot read feed file {path}: {error}") from error


def build_election(overview_xml: bytes, read_feed: Callable[[str], bytes]) -> Election:
    """Assemble an `Election` from an overview and a way to read its feeds.

    Args:
        overview_xml: The bytes of `valgdag.xml`.
        read_feed: Called with a feed's file name, returns its bytes. Called only
            for feeds the overview lists as reported; its exceptions propagate.

    Returns:
        The election, with its places in overview order. A feed the overview
        lists as never reported becomes a placeholder place.

    Raises:
        FeedError: If the overview or a feed is malformed or not a supported election type.
    """
    overview = parse_any_overview(overview_xml)
    places: list[Place] = []
    for ref in overview.feeds:
        if ref.last_changed is None:
            places.append(unreported_place(ref))
        else:
            places.append(parse_place(read_feed(ref.file_name), ref))
    return Election(
        name=overview.name,
        election_type=overview.election_type,
        election_date=overview.election_date,
        places=tuple(places),
    )


def load_election(directory: Path) -> Election:
    """Read `valgdag.xml` and every reported feed it lists.

    A feed the overview lists as never reported is not read; it becomes a
    placeholder place.

    Args:
        directory: A directory holding `valgdag.xml` and the result feeds it lists,
            named as in the URLs' last segments.

    Returns:
        The election, with its places in overview order.

    Raises:
        FeedError: If `valgdag.xml` or a listed feed is missing or unreadable,
            or any feed is malformed or not a supported election type.
    """
    return build_election(
        _read(directory / _OVERVIEW_NAME), lambda name: _read(directory / name)
    )


def main() -> None:
    """Showcase this module's functionality."""
    directory = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "folketingsvalg_2026"
    )
    if not directory.is_dir():
        print(f"fixtures not found at {directory}; run from a repository checkout")
        return

    election = load_election(directory)

    progress = election.counting_progress()
    print(f"{election.name}: {len(election.places)} places, counted {progress}")

    # A directory without valgdag.xml is a FeedError naming the missing file.
    empty = directory / "no-such-directory"
    try:
        load_election(empty)
    except FeedError as error:
        print(f"error: {error}")


if __name__ == "__main__":
    main()
