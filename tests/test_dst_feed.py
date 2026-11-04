"""`dkvalg.adapters.dst_feed`: `election_name`, `parse_overview_for` and the re-exports (T10)."""

from pathlib import Path

import pytest
from conftest import BOM, ELECTION_NAME, EP_ELECTION_NAME, kreds_entry, overview_xml

from dkvalg import ElectionType, FeedError
from dkvalg.adapters import dst_feed, europaparlamentsvalg, folketingsvalg
from dkvalg.adapters.dst_feed import election_name, parse_overview_for

FV = ElectionType.FOLKETINGSVALG
EP = ElectionType.EUROPAPARLAMENTSVALG


def _overview(name: str | None, **kwargs: object) -> bytes:
    return overview_xml([kreds_entry("20", "K")], name=name, **kwargs)  # type: ignore[arg-type]  # forwarded as-is


# --- election_name ---------------------------------------------------------------------


def test_election_name_returns_the_name_of_each_real_overview(
    fixture_dir: Path, ep_fixture_dir: Path
) -> None:
    assert election_name((fixture_dir / "valgdag.xml").read_bytes()) == ELECTION_NAME
    assert (
        election_name((ep_fixture_dir / "valgdag.xml").read_bytes()) == EP_ELECTION_NAME
    )


@pytest.mark.parametrize("bom", [True, False])
def test_election_name_is_stripped_and_bom_independent(bom: bool) -> None:
    xml = _overview(f"\n  {ELECTION_NAME}  \t", bom=bom)

    assert election_name(xml) == ELECTION_NAME


def test_election_name_keeps_inner_double_spaces() -> None:
    assert election_name(_overview("Europa-Parlamentsvalg søndag  9. juni 2024")) == (
        "Europa-Parlamentsvalg søndag  9. juni 2024"
    )


@pytest.mark.parametrize(
    "xml",
    [
        b"<Data/>",
        b"<Data><ValgNavn/></Data>",
        b"<Data><ValgNavn></ValgNavn></Data>",
        b"<Data><ValgNavn> \n </ValgNavn></Data>",
        b"<Data><Inner><ValgNavn>Folketingsvalg</ValgNavn></Inner></Data>",
    ],
)
def test_election_name_absent_or_empty_raises_no_valgnavn(xml: bytes) -> None:
    with pytest.raises(FeedError, match=r"valgdag\.xml: no ValgNavn"):
        election_name(xml)


@pytest.mark.parametrize("xml", [b"", b"<Data>", b"\xff\xfe\xfd", b"<a></b>"])
def test_election_name_malformed_xml_raises_naming_the_file(xml: bytes) -> None:
    with pytest.raises(FeedError, match=r"valgdag\.xml: malformed XML"):
        election_name(xml)


@pytest.mark.parametrize(
    "xml",
    [
        b'<!DOCTYPE d [<!ENTITY e "x">]><Data><ValgNavn>Folketingsvalg</ValgNavn></Data>',
        BOM + b"<!DOCTYPE d><Data><ValgNavn>Folketingsvalg</ValgNavn></Data>",
    ],
)
def test_election_name_refuses_a_doctype_naming_the_file(xml: bytes) -> None:
    with pytest.raises(FeedError, match=r"valgdag\.xml: contains a DOCTYPE"):
        election_name(xml)


def test_election_name_is_pure_and_idempotent() -> None:
    xml = _overview(ELECTION_NAME)
    snapshot = bytes(xml)

    assert election_name(xml) == election_name(xml)
    assert xml == snapshot


# --- parse_overview_for ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "election_type", "prefix"),
    [
        (ELECTION_NAME, FV, "Folketingsvalg"),
        (EP_ELECTION_NAME, EP, "Europa-Parlamentsvalg"),
        ("  Folketingsvalg 2026 ", FV, "Folketingsvalg"),
    ],
)
def test_parse_overview_for_stamps_the_given_type_when_the_prefix_matches(
    name: str, election_type: ElectionType, prefix: str
) -> None:
    overview = parse_overview_for(_overview(name), election_type, prefix)

    assert overview.election_type is election_type
    assert overview.name == name.strip()


@pytest.mark.parametrize(
    ("name", "election_type", "prefix"),
    [
        (EP_ELECTION_NAME, FV, "Folketingsvalg"),
        (ELECTION_NAME, EP, "Europa-Parlamentsvalg"),
        ("folketingsvalg", FV, "Folketingsvalg"),
        ("x Folketingsvalg", FV, "Folketingsvalg"),
    ],
)
def test_parse_overview_for_refuses_a_name_without_the_prefix(
    name: str, election_type: ElectionType, prefix: str
) -> None:
    with pytest.raises(FeedError) as caught:
        parse_overview_for(_overview(name), election_type, prefix)

    message = str(caught.value)
    assert f"not a {prefix}" in message
    assert repr(name.strip()) in message
    assert message.startswith("valgdag.xml")


def test_parse_overview_for_an_empty_name_says_no_valgnavn() -> None:
    with pytest.raises(FeedError, match="no ValgNavn"):
        parse_overview_for(_overview(None), FV, "Folketingsvalg")


def test_parse_overview_for_equals_the_folketingsvalg_adapter(
    fixture_dir: Path,
) -> None:
    xml = (fixture_dir / "valgdag.xml").read_bytes()

    assert parse_overview_for(xml, FV, "Folketingsvalg") == (
        folketingsvalg.parse_overview(xml)
    )


def test_parse_overview_for_malformed_and_declared_documents_are_refused() -> None:
    with pytest.raises(FeedError, match="malformed XML"):
        parse_overview_for(b"<Data>", FV, "Folketingsvalg")
    with pytest.raises(FeedError, match="DOCTYPE"):
        parse_overview_for(b"<!DOCTYPE d><Data/>", FV, "Folketingsvalg")


def test_parse_overview_for_an_empty_prefix_accepts_any_name() -> None:
    overview = parse_overview_for(_overview("Whatever"), EP, "")

    assert overview.election_type is EP


# --- re-exports ------------------------------------------------------------------------


@pytest.mark.parametrize("module", [folketingsvalg, europaparlamentsvalg])
@pytest.mark.parametrize(
    "name", ["FeedRef", "Overview", "parse_place", "unreported_place"]
)
def test_adapter_modules_re_export_the_very_same_objects(
    module: object, name: str
) -> None:
    assert getattr(module, name) is getattr(dst_feed, name)


@pytest.mark.parametrize("module", [folketingsvalg, europaparlamentsvalg])
def test_adapter_modules_declare_their_public_names_in_all(module: object) -> None:
    assert sorted(module.__all__) == [  # type: ignore[attr-defined]  # modules have __all__
        "FeedRef",
        "Overview",
        "main",
        "parse_overview",
        "parse_place",
        "unreported_place",
    ]


def test_the_two_adapters_have_their_own_parse_overview() -> None:
    assert folketingsvalg.parse_overview is not europaparlamentsvalg.parse_overview
