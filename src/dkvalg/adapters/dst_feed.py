"""Parse DST's election overview and result feeds into the model.

The parsing every DST election type shares: the overview's feed list, the result
feeds, the hardening against DOCTYPE and entity declarations. The per-type
adapters (`folketingsvalg`, `europaparlamentsvalg`) add only the check that an
overview names their election type. Bytes in, model out: nothing here touches the
disk.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from xml.parsers import expat

from dkvalg.errors import FeedError
from dkvalg.model import (
    ElectionType,
    PartyResult,
    Place,
    PlaceType,
    Status,
)

_OVERVIEW_NAME = "valgdag.xml"
_NEVER = "0001-01-01"
_DST_TIMESTAMP = re.compile(r"^(\d{2})-(\d{2})-(\d{4}) (\d{2}:\d{2}:\d{2})$")
_DST_DATE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
_TALLY_FILE = re.compile(r"^valgdag_(.+)\.xml$")
_INTEGER = re.compile(r"[+-]?\d+", re.ASCII)
_DECIMAL = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)", re.ASCII)

# overview element tag -> (place type, attribute holding the id, parent attribute)
_OVERVIEW_PLACES: dict[str, tuple[PlaceType, str, str | None]] = {
    "Landsdel": (PlaceType.LANDSDEL, "landsdel_id", None),
    "Storkreds": (PlaceType.STORKREDS, "storkreds_id", "landsdel_id"),
    "Opstillingskreds": (
        PlaceType.OPSTILLINGSKREDS,
        "opstillingskreds_id",
        "storkreds_id",
    ),
}


@dataclass(frozen=True, slots=True)
class FeedRef:
    """One result feed as listed by the overview.

    Attributes:
        place_type: The level of the place the feed describes.
        place_id: DST's id for the place within its type.
        name: The place name from the overview.
        parent_id: Id of the enclosing place, or None.
        last_changed: The overview's timestamp for the feed, or None if never.
        file_name: The last path segment of the feed's URL.
    """

    place_type: PlaceType
    place_id: str
    name: str
    parent_id: str | None
    last_changed: datetime | None
    file_name: str


@dataclass(frozen=True, slots=True)
class Overview:
    """The parsed `valgdag.xml`.

    Attributes:
        name: The election name as served.
        election_type: The kind of election.
        election_date: The election day.
        feeds: Every result feed listed, in document order.
    """

    name: str
    election_type: ElectionType
    election_date: date
    feeds: tuple[FeedRef, ...]


class _DeclarationFoundError(Exception):
    """Raised from an expat handler when a DOCTYPE or entity declaration appears."""


def _refuse_declaration(*_args: object) -> None:
    """Expat handler: any DOCTYPE or entity declaration is refused."""
    raise _DeclarationFoundError


def _refuse_declarations(xml: bytes, source: str) -> None:
    """Raise `FeedError` if the document declares a DOCTYPE or an entity.

    Runs a throwaway expat pass that stops at the first such declaration, before
    `ElementTree` could expand anything. Expat decodes the document itself, so a
    UTF-16 document is checked as well as a UTF-8 one. A document expat cannot
    parse is left for `ElementTree` to report.
    """
    parser = expat.ParserCreate()
    handlers: dict[str, Callable[..., None]] = {
        "StartDoctypeDeclHandler": _refuse_declaration,
        "EntityDeclHandler": _refuse_declaration,
    }
    for attribute, handler in handlers.items():
        setattr(parser, attribute, handler)
    try:
        parser.Parse(xml, True)
    except _DeclarationFoundError as error:
        raise FeedError(
            f"{source}: contains a DOCTYPE or entity declaration"
        ) from error
    except expat.ExpatError:
        return


def _parse_xml(xml: bytes, source: str) -> ET.Element:
    """Parse bytes (BOM or not) into a root element, or raise `FeedError`.

    A document with a DOCTYPE or entity declaration is refused first.
    """
    _refuse_declarations(xml, source)
    try:
        return ET.fromstring(xml)
    except (ET.ParseError, ValueError) as error:
        raise FeedError(f"{source}: malformed XML: {error}") from error


def _timestamp(text: str | None, source: str) -> datetime | None:
    """Convert DST timestamp text (ISO or `dd-mm-yyyy hh:mm:ss`) to a datetime.

    Absent, empty and "never" (`0001-01-01`, in either spelling) give None. A
    timestamp carrying a UTC offset is refused: the model holds naive local time.
    """
    if text is None:
        return None
    text = text.strip()
    match = _DST_TIMESTAMP.match(text)
    if match:
        day, month, year, clock = match.groups()
        text = f"{year}-{month}-{day}T{clock}"
    if text == "" or text.startswith(_NEVER):
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError as error:
        raise FeedError(f"{source}: bad timestamp {text!r}") from error
    if stamp.tzinfo is not None:
        raise FeedError(f"{source}: timestamp {text!r} has a UTC offset")
    return stamp


def _date(text: str | None, source: str) -> date:
    """Convert DST's `dd-mm-yyyy` election date to a date."""
    match = _DST_DATE.match((text or "").strip())
    if not match:
        raise FeedError(f"{source}: bad ValgDato {text!r}")
    day, month, year = match.groups()
    try:
        return date.fromisoformat(f"{year}-{month}-{day}")
    except ValueError as error:
        raise FeedError(f"{source}: bad ValgDato {text!r}") from error


def _changed(element: ET.Element, source: str) -> datetime | None:
    """Read a `SenestRettetIso` / `SenestRettet` attribute pair from an overview entry."""
    iso = element.get("SenestRettetIso")
    return _timestamp(iso or element.get("SenestRettet"), source)


def _child_text(root: ET.Element, tag: str) -> str | None:
    """Return the stripped text of a direct child, or None if absent."""
    child = root.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _int(text: str | None, what: str, source: str) -> int:
    """Convert plain digits (optional sign) to int, else raise `FeedError`."""
    if text is None or not _INTEGER.fullmatch(text.strip()):
        raise FeedError(f"{source}: bad {what} {text!r}")
    return int(text)


def _float(text: str | None, what: str, source: str) -> float:
    """Convert a plain decimal (no `nan`, `inf`, `_` or exponent) to float."""
    if text is None or not _DECIMAL.fullmatch(text.strip()):
        raise FeedError(f"{source}: bad {what} {text!r}")
    return float(text)


def _optional_int(root: ET.Element, tag: str, source: str) -> int | None:
    """Read an integer child element, None when absent."""
    text = _child_text(root, tag)
    return None if text is None else _int(text, tag, source)


def _optional_attr_int(element: ET.Element, name: str, source: str) -> int | None:
    """Read an integer attribute, None when absent."""
    text = element.get(name)
    return None if text is None else _int(text, name, source)


def _feed_ref(element: ET.Element) -> FeedRef:
    """Build a `FeedRef` from one overview entry."""
    tag = element.tag
    url = element.get("filnavn", "")
    file_name = url.rsplit("/", 1)[-1]
    name = (element.text or "").strip()
    source = f"{_OVERVIEW_NAME} <{tag}> {name!r}"
    if not file_name:
        raise FeedError(f"{source}: no filnavn")
    changed = _changed(element, source)
    if tag == "Land":
        land_id = element.get("land_id")
        if land_id is not None:
            return FeedRef(PlaceType.COUNTRY, land_id, name, None, changed, file_name)
        match = _TALLY_FILE.match(file_name)
        if not match:
            raise FeedError(f"{source}: cannot read a tally id from {file_name!r}")
        return FeedRef(PlaceType.TALLY, match.group(1), name, None, changed, file_name)
    place_type, id_attr, parent_attr = _OVERVIEW_PLACES[tag]
    place_id = element.get(id_attr)
    if place_id is None:
        raise FeedError(f"{source}: missing {id_attr}")
    if tag == "Landsdel":
        parent_id: str | None = element.get("land_id", "0")
    else:
        parent_id = element.get(parent_attr or "")
    return FeedRef(place_type, place_id, name, parent_id, changed, file_name)


def election_name(xml: bytes) -> str:
    """Read the election name from an overview.

    Args:
        xml: The raw bytes of `valgdag.xml`.

    Returns:
        The stripped `ValgNavn`.

    Raises:
        FeedError: If the XML is malformed or declares a DOCTYPE or entity, or
            `ValgNavn` is absent or empty.
    """
    root = _parse_xml(xml, _OVERVIEW_NAME)
    name = _child_text(root, "ValgNavn")
    if not name:
        raise FeedError(f"{_OVERVIEW_NAME}: no ValgNavn")
    return name


def parse_overview_for(
    xml: bytes, election_type: ElectionType, name_prefix: str
) -> Overview:
    """Parse `valgdag.xml` as one election type.

    Args:
        xml: The raw bytes of the overview feed.
        election_type: The type stamped on the result.
        name_prefix: What `ValgNavn` must start with, case-sensitively.

    Returns:
        The election name, type and date and every result feed it lists.

    Raises:
        FeedError: If the XML is malformed, a required field is missing, the
            name does not start with `name_prefix`, or no result feeds are listed.
    """
    root = _parse_xml(xml, _OVERVIEW_NAME)
    name = _child_text(root, "ValgNavn")
    if not name:
        raise FeedError(f"{_OVERVIEW_NAME}: no ValgNavn")
    if not name.startswith(name_prefix):
        raise FeedError(f"{_OVERVIEW_NAME}: not a {name_prefix}, ValgNavn is {name!r}")
    election_date = _date(_child_text(root, "ValgDato"), _OVERVIEW_NAME)
    tags = {*_OVERVIEW_PLACES, "Land"}
    feeds = tuple(_feed_ref(element) for element in root.iter() if element.tag in tags)
    if not feeds:
        raise FeedError(f"{_OVERVIEW_NAME}: lists no result feeds")
    return Overview(name, election_type, election_date, feeds)


def unreported_place(ref: FeedRef) -> Place:
    """Build the placeholder for a feed the overview lists as never reported.

    Args:
        ref: The feed's overview entry.

    Returns:
        A figure-free place with status `NOT_AVAILABLE`.
    """
    return Place(
        place_type=ref.place_type,
        place_id=ref.place_id,
        name=ref.name,
        parent_id=ref.parent_id,
        status=Status.NOT_AVAILABLE,
        status_text="",
        last_changed=None,
    )


def _party(element: ET.Element, source: str) -> PartyResult:
    """Build a `PartyResult` from one `Parti` element."""
    party_id = element.get("Id")
    if party_id is None:
        raise FeedError(f"{source}: <Parti> {element.get('Navn')!r} has no Id")
    return PartyResult(
        party_id=party_id,
        letter=element.get("Bogstav", ""),
        name=element.get("Navn", ""),
        votes=_int(element.get("StemmerAntal"), "StemmerAntal", source),
        percent=_float(element.get("StemmerPct"), "StemmerPct", source),
        seats=_optional_attr_int(element, "Mandater", source),
        constituency_seats=_optional_attr_int(element, "Kredsmandater", source),
        supplementary_seats=_optional_attr_int(element, "Tillaegsmandater", source),
    )


def parse_place(xml: bytes, ref: FeedRef) -> Place:
    """Parse one result feed.

    Id, name and parent come from `ref`. A feed with status 0, 9 or 10 (a status
    that carries no result) yields a place without figures even if it holds a
    `Stemmer` element. A feed whose timestamp is absent, empty or "never" takes
    `ref.last_changed`.

    Args:
        xml: The raw bytes of the result feed.
        ref: The feed's overview entry.

    Returns:
        The place, with figures when the status carries a result.

    Raises:
        FeedError: If the XML is malformed, the status is missing or unknown, a
            status with a result has no `Stemmer`, a `Parti` has no `Id`, or a
            figure is not a plain number.
    """
    source = ref.file_name
    root = _parse_xml(xml, source)
    status_element = root.find("Status")
    if status_element is None:
        raise FeedError(f"{source}: no Status element")
    code = status_element.get("Kode")
    try:
        status = Status(int(code or ""))
    except ValueError as error:
        raise FeedError(f"{source}: unknown status code {code!r}") from error
    status_text = (status_element.text or "").strip()

    iso = _child_text(root, "SenestRettetIso")
    stamp = _timestamp(iso or _child_text(root, "SenestRettet"), source)
    last_changed = stamp if stamp is not None else ref.last_changed

    base = Place(
        place_type=ref.place_type,
        place_id=ref.place_id,
        name=ref.name,
        parent_id=ref.parent_id,
        status=status,
        status_text=status_text,
        last_changed=last_changed,
    )
    if not status.has_result:
        return base
    votes = root.find("Stemmer")
    if votes is None:
        raise FeedError(f"{source}: status {status.value} but no Stemmer element")
    turnout = _child_text(root, "DeltagelsePct")
    return Place(
        place_type=base.place_type,
        place_id=base.place_id,
        name=base.name,
        parent_id=base.parent_id,
        status=base.status,
        status_text=base.status_text,
        last_changed=base.last_changed,
        eligible_voters=_optional_int(root, "Stemmeberettigede", source),
        turnout_percent=None
        if turnout is None
        else _float(turnout, "DeltagelsePct", source),
        valid_votes=_optional_int(votes, "IAltGyldigeStemmer", source),
        blank_votes=_optional_int(votes, "BlankeStemmer", source),
        other_invalid_votes=_optional_int(votes, "AndreUgyldigeStemmer", source),
        total_invalid_votes=_optional_int(votes, "IAltUgyldigeStemmer", source),
        total_votes=_optional_int(votes, "IAltAfgivneStemmer", source),
        parties=tuple(_party(p, source) for p in votes.findall("Parti")),
    )


def main() -> None:
    """Showcase this module's functionality."""
    fixtures = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "folketingsvalg_2026"
    )
    if not fixtures.is_dir():
        print(f"fixtures not found at {fixtures}; run from a repository checkout")
        return
    overview_xml = (fixtures / "valgdag.xml").read_bytes()
    election_type = ElectionType.FOLKETINGSVALG  # FOLKETINGSVALG, EUROPAPARLAMENTSVALG
    name_prefix = "Folketingsvalg"  # "Folketingsvalg", "Europa-Parlamentsvalg"

    name = election_name(overview_xml)
    overview = parse_overview_for(overview_xml, election_type, name_prefix)

    print(f"{name}: {overview.election_type.value}, {len(overview.feeds)} feeds")

    # The wrong prefix is refused, naming the prefix and the name served.
    name_prefix = "Europa-Parlamentsvalg"
    try:
        parse_overview_for(overview_xml, election_type, name_prefix)
    except FeedError as error:
        print(f"refused: {error}")

    # A feed the overview lists as never reported becomes a placeholder.
    ref = overview.feeds[0]
    placeholder = unreported_place(ref)

    print(f"placeholder: {placeholder.status.name}, {placeholder.parties}")


if __name__ == "__main__":
    main()
