"""Parse DST's Europa-Parlamentsvalg overview and result feeds into the model.

A thin adapter over `dkvalg.adapters.dst_feed`: it adds the check that the overview
is a Europa-Parlamentsvalg and re-exports the shared names. The EP feeds carry no
seat attributes, so every seat field of the model is None. Bytes in, model out:
nothing here touches the disk.
"""

from pathlib import Path

from dkvalg.adapters.dst_feed import (
    FeedRef,
    Overview,
    parse_overview_for,
    parse_place,
    unreported_place,
)
from dkvalg.model import ElectionType

__all__ = [
    "FeedRef",
    "Overview",
    "main",
    "parse_overview",
    "parse_place",
    "unreported_place",
]


def parse_overview(xml: bytes) -> Overview:
    """Parse `valgdag.xml` of a Europa-Parlamentsvalg.

    Args:
        xml: The raw bytes of the overview feed.

    Returns:
        The election name, type and date and every result feed it lists.

    Raises:
        FeedError: If the XML is malformed, a required field is missing, the
            overview is not a Europa-Parlamentsvalg, or it lists no result feeds.
    """
    return parse_overview_for(
        xml, ElectionType.EUROPAPARLAMENTSVALG, "Europa-Parlamentsvalg"
    )


def main() -> None:
    """Showcase this module's functionality."""
    fixtures = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "ep_2024"
    if not fixtures.is_dir():
        print(f"fixtures not found at {fixtures}; run from a repository checkout")
        return
    overview_xml = (fixtures / "valgdag.xml").read_bytes()
    feed_name = "valgdag_0.xml"  # the country; try valgdag_7.xml for Hovedstaden

    overview = parse_overview(overview_xml)
    ref = next(feed for feed in overview.feeds if feed.file_name == feed_name)
    place = parse_place((fixtures / feed_name).read_bytes(), ref)

    print(f"{overview.name} ({overview.election_date}): {len(overview.feeds)} feeds")
    print(f"{place.name}: {place.eligible_voters} eligible, status {place.status.name}")
    leader = place.parties[0]
    print(f"{leader.name}: {leader.votes} votes, seats {leader.seats}")

    # A feed the overview lists as never reported becomes a placeholder.
    placeholder = unreported_place(ref)

    print(f"placeholder: {placeholder.status.name}, {placeholder.parties}")


if __name__ == "__main__":
    main()
