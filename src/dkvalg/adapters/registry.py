"""Choose the adapter for an election overview from its name."""

from dkvalg.adapters import europaparlamentsvalg, folkeafstemning, folketingsvalg
from dkvalg.adapters.dst_feed import Overview, election_name
from dkvalg.errors import FeedError

_PREFIXES = {
    "Folketingsvalg": folketingsvalg.parse_overview,
    "Europa-Parlamentsvalg": europaparlamentsvalg.parse_overview,
    "Folkeafstemning": folkeafstemning.parse_overview,
}


def parse_any_overview(xml: bytes) -> Overview:
    """Parse `valgdag.xml` with the adapter of its election type.

    Args:
        xml: The raw bytes of the overview feed.

    Returns:
        The election name, type and date and every result feed it lists.

    Raises:
        FeedError: If the XML is malformed, `ValgNavn` is absent or names no
            supported election type, or the chosen adapter refuses the overview.
    """
    name = election_name(xml)
    for prefix, parse in _PREFIXES.items():
        if name.startswith(prefix):
            return parse(xml)
    supported = ", ".join(_PREFIXES)
    raise FeedError(
        f"valgdag.xml: not a supported election ({supported}), ValgNavn is {name!r}"
    )


def main() -> None:
    """Showcase this module's functionality."""
    names = (
        "Folketingsvalg tirsdag 24. marts 2026",
        "Europa-Parlamentsvalg søndag  9. juni 2024",
        "Folkeafstemning onsdag  1. juni 2022",
        "Kommunalvalg 2025",
    )
    template = (
        "<Valg><ValgNavn>{}</ValgNavn><ValgDato>09-06-2024</ValgDato>"
        '<Land land_id="0" filnavn="https://x/valgdag_0.xml">Hele landet</Land></Valg>'
    )

    for name in names:
        xml = template.format(name).encode()
        try:
            overview = parse_any_overview(xml)
        except FeedError as error:
            print(f"refused: {error}")
        else:
            print(f"{overview.election_type.value}: {overview.name}")


if __name__ == "__main__":
    main()
