"""Shared helpers for the dkvalg tests: fixture paths and small synthetic feeds.

The builders follow the real XML shape of DST's 2026 feeds, so a synthetic feed
exercises the same code path a downloaded one does. Datetimes are built only with
`datetime.fromisoformat`, as Ruff's DTZ rules require.
"""

import shutil
from datetime import date, datetime
from pathlib import Path

import pytest

from dkvalg.adapters.folketingsvalg import FeedRef
from dkvalg.model import (
    Election,
    ElectionType,
    PartyResult,
    Place,
    PlaceType,
    Status,
)
from dkvalg.sources.directory import load_election

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "folketingsvalg_2026"
BOM = b"\xef\xbb\xbf"
ELECTION_NAME = "Folketingsvalg tirsdag 24. marts 2026"

PARTIES_XML = (
    '<Parti Id="5891" Bogstav="A" Navn="A. Socialdemokratiet" StemmerAntal="600" '
    'StemmerPct="60.0" />\n'
    '<Parti Id="5893" Bogstav="B" Navn="B. Radikale Venstre" StemmerAntal="390" '
    'StemmerPct="39.0" />\n'
    '<Parti Id="" Navn="Uden for partier" StemmerAntal="10" StemmerPct="1.0" />\n'
    "<IAltGyldigeStemmer>1000</IAltGyldigeStemmer>\n"
    "<BlankeStemmer>5</BlankeStemmer>\n"
    "<AndreUgyldigeStemmer>2</AndreUgyldigeStemmer>\n"
    "<IAltUgyldigeStemmer>7</IAltUgyldigeStemmer>\n"
    "<IAltAfgivneStemmer>1007</IAltAfgivneStemmer>\n"
)


def dt(text: str) -> datetime:
    """Build a naive datetime from ISO text."""
    return datetime.fromisoformat(text)


def feed_xml(
    *,
    status: str | None = "1",
    status_text: str = "Foreløbigt resultat",
    senest: str | None = "24-03-2026 22:00:00",
    iso: str | None = "2026-03-24T22:00:00",
    stemmer: str | None = PARTIES_XML,
    eligible: str | None = "1200",
    turnout: str | None = "83.9",
    bom: bool = True,
    root_tag: str = "Data",
) -> bytes:
    """Build one result feed in DST's shape; `None` omits the element or attribute."""
    kode = "" if status is None else f' Kode="{status}"'
    parts = [
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>',
        f"<{root_tag}>",
        f"<ValgNavn>{ELECTION_NAME}</ValgNavn>",
        "<ValgDato>24-03-2026</ValgDato>",
        '<Sted Id="20" Type="OpstKreds">1.Østerbro</Sted>',
    ]
    if senest is not None:
        parts.append(f"<SenestRettet>{senest}</SenestRettet>")
    if iso is not None:
        parts.append(f"<SenestRettetIso>{iso}</SenestRettetIso>")
    if status is not None or status_text:
        parts.append(f"<Status{kode}>{status_text}</Status>")
    if eligible is not None:
        parts.append(f"<Stemmeberettigede>{eligible}</Stemmeberettigede>")
    if turnout is not None:
        parts.append(f"<DeltagelsePct>{turnout}</DeltagelsePct>")
    if stemmer is not None:
        parts.append(f"<Stemmer>{stemmer}</Stemmer>")
    parts.append(f"</{root_tag}>")
    data = "\n".join(parts).encode("utf-8")
    return BOM + data if bom else data


def entry(
    tag: str,
    name: str,
    file_name: str | None,
    *,
    senest: str | None = "24-03-2026 22:00:00",
    iso: str | None = "2026-03-24T22:00:00",
    **attributes: str,
) -> str:
    """Build one overview entry such as `<Opstillingskreds ...>name</...>`."""
    attrs = dict(attributes)
    if senest is not None:
        attrs["SenestRettet"] = senest
    if iso is not None:
        attrs["SenestRettetIso"] = iso
    if file_name is not None:
        attrs["filnavn"] = f"https://www.dst.dk/valg/x/xml/{file_name}"
    text = " ".join(f'{key}="{value}"' for key, value in attrs.items())
    return f"<{tag} {text}>{name}</{tag}>"


def overview_xml(
    entries: list[str],
    *,
    name: str | None = ELECTION_NAME,
    election_date: str | None = "24-03-2026",
    bom: bool = True,
) -> bytes:
    """Build a `valgdag.xml` around the given entries."""
    parts = ['<?xml version="1.0" encoding="utf-8" standalone="yes"?>', "<Data>"]
    if name is not None:
        parts.append(f"<ValgNavn>{name}</ValgNavn>")
    if election_date is not None:
        parts.append(f"<ValgDato>{election_date}</ValgDato>")
    parts.append("<Afstemningsomraader />")
    parts.extend(entries)
    parts.append("</Data>")
    data = "\n".join(parts).encode("utf-8")
    return BOM + data if bom else data


def kreds_entry(
    place_id: str,
    name: str,
    *,
    senest: str | None = "24-03-2026 22:00:00",
    iso: str | None = "2026-03-24T22:00:00",
) -> str:
    """An `Opstillingskreds` overview entry whose feed is `valgdag_<id>.xml`."""
    return entry(
        "Opstillingskreds",
        name,
        f"valgdag_{place_id}.xml",
        senest=senest,
        iso=iso,
        opstillingskreds_id=place_id,
        storkreds_id="10",
    )


def make_ref(
    place_id: str = "20",
    *,
    place_type: PlaceType = PlaceType.OPSTILLINGSKREDS,
    name: str = "1.Østerbro",
    parent_id: str | None = "10",
    last_changed: datetime | None = None,
    file_name: str | None = None,
) -> FeedRef:
    """Build a `FeedRef` with sensible defaults."""
    return FeedRef(
        place_type,
        place_id,
        name,
        parent_id,
        last_changed,
        file_name or f"valgdag_{place_id}.xml",
    )


def make_place(
    place_id: str = "20",
    *,
    place_type: PlaceType = PlaceType.OPSTILLINGSKREDS,
    name: str | None = None,
    status: Status = Status.PRELIMINARY,
    status_text: str = "Foreløbigt resultat",
    last_changed: datetime | None = None,
    parties: tuple[PartyResult, ...] | None = None,
) -> Place:
    """Build a `Place`; a place with a result gets one party and some figures."""
    if parties is None:
        parties = (PartyResult("5891", "A", "A. Socialdemokratiet", 600, 60.0),)
    reported = status.has_result
    return Place(
        place_type=place_type,
        place_id=place_id,
        name=name or f"Place {place_id}",
        parent_id="10",
        status=status,
        status_text=status_text,
        last_changed=last_changed,
        eligible_voters=1200 if reported else None,
        turnout_percent=83.9 if reported else None,
        valid_votes=1000 if reported else None,
        blank_votes=5 if reported else None,
        other_invalid_votes=2 if reported else None,
        total_invalid_votes=7 if reported else None,
        total_votes=1007 if reported else None,
        parties=parties if reported else (),
    )


def make_election(*places: Place) -> Election:
    """Build an `Election` around the given places."""
    return Election(
        "Folketingsvalg tirsdag 24. marts 2026",
        ElectionType.FOLKETINGSVALG,
        date.fromisoformat("2026-03-24"),
        tuple(places),
    )


def write_directory(
    directory: Path, overview: bytes, feeds: dict[str, bytes] | None = None
) -> Path:
    """Write `valgdag.xml` and feed files into `directory`, returning it."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "valgdag.xml").write_bytes(overview)
    for file_name, data in (feeds or {}).items():
        (directory / file_name).write_bytes(data)
    return directory


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    """The unmodified 2026 fixture directory (read-only: never write into it)."""
    assert FIXTURES.is_dir(), f"fixtures missing at {FIXTURES}"
    return FIXTURES


@pytest.fixture
def fixture_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the fixture directory that a test may damage."""
    target = tmp_path / "copy"
    shutil.copytree(FIXTURES, target)
    return target


@pytest.fixture(scope="session")
def election(fixture_dir: Path) -> Election:
    """The fixture set loaded once; immutable, so sharing it is safe."""
    return load_election(fixture_dir)
