"""`parse_any_overview`: the adapter chosen from `ValgNavn` (A2, T2)."""

from pathlib import Path

import pytest
from conftest import BOM, ELECTION_NAME, EP_ELECTION_NAME, kreds_entry, overview_xml

from dkvalg import ElectionType, FeedError
from dkvalg.adapters import europaparlamentsvalg, folketingsvalg
from dkvalg.adapters.registry import parse_any_overview

FV = ElectionType.FOLKETINGSVALG
EP = ElectionType.EUROPAPARLAMENTSVALG


def _overview(name: str | None, **kwargs: object) -> bytes:
    return overview_xml([kreds_entry("20", "K")], name=name, **kwargs)  # type: ignore[arg-type]  # forwarded as-is


def test_each_real_overview_gives_its_own_election_type(
    fixture_dir: Path, ep_fixture_dir: Path
) -> None:
    fv = parse_any_overview((fixture_dir / "valgdag.xml").read_bytes())
    ep = parse_any_overview((ep_fixture_dir / "valgdag.xml").read_bytes())

    assert (fv.election_type, ep.election_type) == (FV, EP)
    assert fv.name == ELECTION_NAME
    assert ep.name == EP_ELECTION_NAME
    assert len(fv.feeds) == len(ep.feeds) == 107


def test_parse_any_overview_equals_the_matching_adapter(
    fixture_dir: Path, ep_fixture_dir: Path
) -> None:
    fv_xml = (fixture_dir / "valgdag.xml").read_bytes()
    ep_xml = (ep_fixture_dir / "valgdag.xml").read_bytes()

    assert parse_any_overview(fv_xml) == folketingsvalg.parse_overview(fv_xml)
    assert parse_any_overview(ep_xml) == europaparlamentsvalg.parse_overview(ep_xml)


@pytest.mark.parametrize(
    ("name", "expected_type", "expected_name"),
    [
        (EP_ELECTION_NAME, EP, EP_ELECTION_NAME),
        (f"  {EP_ELECTION_NAME}\n", EP, EP_ELECTION_NAME),
        (f"\t{ELECTION_NAME} ", FV, ELECTION_NAME),
        ("Europa-Parlamentsvalg", EP, "Europa-Parlamentsvalg"),
        ("Folketingsvalg", FV, "Folketingsvalg"),
        # startswith, as round 1's adapter did: a longer word is accepted (pinned).
        ("Folketingsvalgxyz", FV, "Folketingsvalgxyz"),
        ("Europa-Parlamentsvalgfoo", EP, "Europa-Parlamentsvalgfoo"),
    ],
)
def test_parse_any_overview_accepts_names_that_start_with_a_supported_prefix(
    name: str, expected_type: ElectionType, expected_name: str
) -> None:
    overview = parse_any_overview(_overview(name))

    assert overview.election_type is expected_type
    assert overview.name == expected_name


@pytest.mark.parametrize(
    "name",
    [
        "Kommunalvalg 2025",
        "folketingsvalg 2026",
        "FOLKETINGSVALG 2026",
        "x Folketingsvalg",
        "Europaparlamentsvalg 2024",
        "europa-parlamentsvalg 2024",
        "Østrigsvalg æøå",
    ],
)
def test_parse_any_overview_refuses_other_names_naming_value_and_supported_types(
    name: str,
) -> None:
    with pytest.raises(FeedError) as caught:
        parse_any_overview(_overview(name))

    message = str(caught.value)
    assert message.startswith("valgdag.xml")
    assert repr(name) in message
    assert "Folketingsvalg" in message
    assert "Europa-Parlamentsvalg" in message


def test_parse_any_overview_a_very_long_name_is_a_feed_error_not_a_crash() -> None:
    with pytest.raises(FeedError, match="not a supported election"):
        parse_any_overview(_overview("Z" * 100_000))


@pytest.mark.parametrize(
    "xml",
    [
        b"<Data><ValgDato>09-06-2024</ValgDato></Data>",
        b"<Data><ValgNavn/></Data>",
        b"<Data><ValgNavn>   </ValgNavn></Data>",
        b"<Data><Wrap><ValgNavn>Folketingsvalg</ValgNavn></Wrap></Data>",
    ],
)
def test_parse_any_overview_without_a_name_says_no_valgnavn(xml: bytes) -> None:
    with pytest.raises(FeedError, match=r"valgdag\.xml: no ValgNavn"):
        parse_any_overview(xml)


@pytest.mark.parametrize(
    "xml",
    [b"", b"<Data>", b"\xff\xfe\x00garbage", b"not xml at all"],
)
def test_parse_any_overview_malformed_xml_is_a_feed_error_naming_the_file(
    xml: bytes,
) -> None:
    with pytest.raises(FeedError, match=r"valgdag\.xml"):
        parse_any_overview(xml)


@pytest.mark.parametrize("prefix", [b"", BOM])
@pytest.mark.parametrize(
    "declaration",
    [
        b'<!DOCTYPE Data [<!ENTITY x "y">]>',
        b'<!DOCTYPE Data SYSTEM "http://example.invalid/x.dtd">',
        b'<!DOCTYPE Data [<!ENTITY % p "q">]>',
    ],
)
def test_parse_any_overview_refuses_a_declaration_before_reading_the_name(
    prefix: bytes, declaration: bytes
) -> None:
    xml = (
        prefix
        + b"<?xml version='1.0'?>"
        + declaration
        + b"<Data><ValgNavn>Folkeafstemning</ValgNavn></Data>"
    )

    with pytest.raises(FeedError, match=r"valgdag\.xml: contains a DOCTYPE"):
        parse_any_overview(xml)


def test_parse_any_overview_refuses_a_utf16_document_with_a_doctype() -> None:
    xml = (
        '<?xml version="1.0" encoding="utf-16"?><!DOCTYPE Data [<!ENTITY x "y">]>'
        "<Data><ValgNavn>Folketingsvalg</ValgNavn></Data>"
    ).encode("utf-16")

    with pytest.raises(FeedError, match="DOCTYPE"):
        parse_any_overview(xml)


@pytest.mark.parametrize("name", [EP_ELECTION_NAME, ELECTION_NAME])
@pytest.mark.parametrize("date_text", ["31-02-2024", "2024-06-09", ""])
def test_parse_any_overview_a_good_name_with_a_bad_date_is_refused_naming_it(
    name: str, date_text: str
) -> None:
    with pytest.raises(FeedError, match="bad ValgDato"):
        parse_any_overview(_overview(name, election_date=date_text))


def test_parse_any_overview_a_good_name_with_no_feeds_is_refused() -> None:
    xml = overview_xml([], name=EP_ELECTION_NAME, election_date="09-06-2024")

    with pytest.raises(FeedError, match="lists no result feeds"):
        parse_any_overview(xml)


def test_parse_any_overview_is_idempotent(ep_fixture_dir: Path) -> None:
    xml = (ep_fixture_dir / "valgdag.xml").read_bytes()

    assert parse_any_overview(xml) == parse_any_overview(xml)
