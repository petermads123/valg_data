"""Folkeafstemning (referendum): the adapter, and referenda across the stack (A1 to A6; T1 to T6)."""

import io
import re
import shutil
from pathlib import Path

import pytest
from conftest import (
    BOM,
    ELECTION_NAME,
    FA_2009_BASE_URL,
    FA_2009_NAME,
    FA_2015_NAME,
    FA_2022_BASE_URL,
    FA_2022_NAME,
    NATIONAL,
    FakeClock,
    FakeTransport,
    dt,
    entry,
    feed_xml,
    kreds_entry,
    make_ref,
    overview_xml,
    write_directory,
)

from dkvalg import (
    CaptureReplay,
    Election,
    ElectionType,
    FeedError,
    HttpSource,
    PlaceType,
    Recorder,
    ReplaySource,
    Status,
    load_election,
    poll,
)
from dkvalg.adapters import (
    europaparlamentsvalg,
    folkeafstemning,
    folketingsvalg,
    registry,
)
from dkvalg.adapters.dst_feed import parse_place
from dkvalg.adapters.folkeafstemning import parse_overview, unreported_place
from dkvalg.cli import run
from dkvalg.sources.directory import build_election

LOCATION_2022 = "Valg1962294"
LOCATION_2009 = "Valg1191213"

ANSWERS_XML = (
    '<Parti Id="434284" Bogstav="JA" Navn="JA" StemmerAntal="600" StemmerPct="60.0" />\n'
    '<Parti Id="434285" Bogstav="NEJ" Navn="NEJ" StemmerAntal="400" StemmerPct="40.0" />\n'
    "<IAltGyldigeStemmer>1000</IAltGyldigeStemmer>\n"
    "<BlankeStemmer>5</BlankeStemmer>\n"
    "<AndreUgyldigeStemmer>2</AndreUgyldigeStemmer>\n"
    "<IAltUgyldigeStemmer>7</IAltUgyldigeStemmer>\n"
    "<IAltAfgivneStemmer>1007</IAltAfgivneStemmer>\n"
)


def _answer(party_id: str, letter: str, votes: int) -> str:
    return (
        f'<Parti Id="{party_id}" Bogstav="{letter}" Navn="{letter}" '
        f'StemmerAntal="{votes}" StemmerPct="{votes / 10}" />\n'
    )


def _fa_overview(
    *entries: str,
    name: str | None = FA_2022_NAME,
    election_date: str | None = "01-06-2022",
    bom: bool = True,
) -> bytes:
    """A synthetic Folkeafstemning overview (one opstillingskreds by default)."""
    return overview_xml(
        list(entries) or [kreds_entry("20", "K")],
        name=name,
        election_date=election_date,
        bom=bom,
    )


def _fa_feed(
    *,
    status: str | None = "1",
    status_text: str = "Foreløbigt resultat",
    stemmer: str | None = ANSWERS_XML,
    eligible: str | None = "1200",
    turnout: str | None = "83.9",
    bom: bool = True,
) -> bytes:
    """A synthetic result feed under the Folkeafstemning name."""
    body = feed_xml(
        status=status,
        status_text=status_text,
        stemmer=stemmer,
        eligible=eligible,
        turnout=turnout,
        bom=bom,
    )
    return body.replace(ELECTION_NAME.encode(), FA_2022_NAME.encode())


def _inject_doctype(body: bytes) -> bytes:
    start = body.index(b"?>") + 2
    return body[:start] + b'\n<!DOCTYPE Data [<!ENTITY x "y">]>' + body[start:]


# --- A1 / T1 / T2: the three real sets through load_election ----------------------------

# fixture, name, date, opstillingskredse, places, eligible, turnout, blank, JA, JA %, NEJ, NEJ %, leader
REAL = [
    (
        "fa_2022",
        FA_2022_NAME,
        "2022-06-01",
        92,
        107,
        4_260_944,
        65.76,
        32_807,
        (1_848_738, 66.9),
        (914_829, 33.1),
        "JA",
    ),
    (
        "fa_2015",
        FA_2015_NAME,
        "2015-12-03",
        92,
        107,
        4_153_150,
        71.98,
        48_151,
        (1_377_538, 46.9),
        (1_556_582, 53.1),
        "NEJ",
    ),
    (
        "fa_2009",
        FA_2009_NAME,
        "2009-06-07",
        94,
        109,
        4_114_395,
        58.26,
        204_712,
        (1_858_008, 85.3),
        (317_711, 14.6),
        "JA",
    ),
]
REAL_IDS = [row[0] for row in REAL]


@pytest.mark.parametrize("row", REAL, ids=REAL_IDS)
def test_load_election_referendum_is_a_referendum_with_the_real_name_and_date(
    request: pytest.FixtureRequest, row: tuple[object, ...]
) -> None:
    election: Election = request.getfixturevalue(str(row[0]))

    assert election.election_type is ElectionType.FOLKEAFSTEMNING
    assert election.name == row[1]
    assert election.election_date.isoformat() == row[2]


@pytest.mark.parametrize("row", REAL, ids=REAL_IDS)
def test_load_election_referendum_has_the_places_by_type_and_counts_all_districts(
    request: pytest.FixtureRequest, row: tuple[object, ...]
) -> None:
    election: Election = request.getfixturevalue(str(row[0]))
    kreds = row[3]

    counts = {t: len(election.of_type(t)) for t in PlaceType}
    progress = election.counting_progress()

    assert counts == {
        PlaceType.COUNTRY: 1,
        PlaceType.TALLY: 1,
        PlaceType.LANDSDEL: 3,
        PlaceType.STORKREDS: 10,
        PlaceType.OPSTILLINGSKREDS: kreds,
    }
    assert len(election.places) == row[4]
    assert (progress.counted, progress.total) == (kreds, kreds)
    assert str(progress) == f"{kreds}/{kreds}"


@pytest.mark.parametrize("row", REAL, ids=REAL_IDS)
def test_load_election_referendum_national_figures_match_the_files(
    request: pytest.FixtureRequest, row: tuple[object, ...]
) -> None:
    election: Election = request.getfixturevalue(str(row[0]))
    country = election.get(PlaceType.COUNTRY, "0")

    ja, nej = country.parties

    assert country.status is Status.PRELIMINARY
    assert country.eligible_voters == row[5]
    assert country.turnout_percent == row[6]
    assert country.blank_votes == row[7]
    assert (ja.letter, ja.votes, ja.percent) == ("JA", *row[8])  # type: ignore[misc]  # row is a tuple of tuples
    assert (nej.letter, nej.votes, nej.percent) == ("NEJ", *row[9])  # type: ignore[misc]  # row is a tuple of tuples


@pytest.mark.parametrize("row", REAL, ids=REAL_IDS)
def test_referendum_national_leader_is_the_winning_answer(
    request: pytest.FixtureRequest, row: tuple[object, ...]
) -> None:
    election: Election = request.getfixturevalue(str(row[0]))

    leader = election.get(PlaceType.COUNTRY, "0").leader

    assert leader is not None
    assert leader.letter == row[10]


@pytest.mark.parametrize("fixture_name", REAL_IDS)
def test_referendum_answers_are_parties_with_no_seats_and_no_outside_party_entry(
    request: pytest.FixtureRequest, fixture_name: str
) -> None:
    election: Election = request.getfixturevalue(fixture_name)

    answers = [p for place in election.places for p in place.parties]

    assert {p.letter for p in answers} == {"JA", "NEJ"}
    assert {(p.party_id, p.letter) for p in answers} == {
        ("434284", "JA"),
        ("434285", "NEJ"),
    }
    assert all(p.is_party for p in answers)
    assert {
        (p.seats, p.constituency_seats, p.supplementary_seats) for p in answers
    } == {(None, None, None)}
    assert all(
        [p.letter for p in place.parties] == ["JA", "NEJ"]
        for place in election.places
        if place.has_result
    )


def test_referendum_2009_dangling_parents_are_kept_as_served(
    fa_2009: Election,
) -> None:
    greenland = fa_2009.get(PlaceType.OPSTILLINGSKREDS, "841466")
    faroe = fa_2009.get(PlaceType.OPSTILLINGSKREDS, "841467")
    storkreds_ids = {p.place_id for p in fa_2009.of_type(PlaceType.STORKREDS)}

    others = [
        p
        for p in fa_2009.of_type(PlaceType.OPSTILLINGSKREDS)
        if p.place_id not in {"841466", "841467"}
    ]

    assert (greenland.name, greenland.parent_id) == ("Grønland", "841466")
    assert (faroe.name, faroe.parent_id) == ("Færøerne", "841467")
    assert {"841466", "841467"}.isdisjoint(storkreds_ids)
    assert len(others) == 92
    assert {p.parent_id for p in others} <= storkreds_ids


def test_referendum_2009_feeds_carry_no_iso_timestamp_and_parse_from_the_dst_form(
    fa_2009_dir: Path, fa_2009: Election
) -> None:
    assert all(
        b"SenestRettetIso" not in p.read_bytes() for p in fa_2009_dir.glob("*.xml")
    )
    assert all(p.last_changed is not None for p in fa_2009.places)
    assert fa_2009.get(PlaceType.COUNTRY, "0").last_changed == dt("2009-06-08T10:22:56")


def test_referendum_2009_place_names_come_from_the_overview_not_the_feed(
    fa_2009_dir: Path, fa_2009: Election
) -> None:
    feed_text = (fa_2009_dir / "valgdag_0.xml").read_text(encoding="utf-8-sig")

    assert ">Hele riget<" in feed_text
    assert fa_2009.get(PlaceType.COUNTRY, "0").name == "Hele landet"


def test_referendum_names_keep_or_lack_the_double_space_as_served() -> None:
    assert "onsdag  1." in FA_2022_NAME
    assert "søndag  7." in FA_2009_NAME
    assert "torsdag 3." in FA_2015_NAME
    assert "  " not in FA_2015_NAME


def test_load_election_referendum_is_idempotent_and_pure(fa_2015_dir: Path) -> None:
    before = {p.name: p.read_bytes() for p in fa_2015_dir.glob("*.xml")}

    first = load_election(fa_2015_dir)
    second = load_election(fa_2015_dir)

    assert first == second
    assert before == {p.name: p.read_bytes() for p in fa_2015_dir.glob("*.xml")}


def test_load_election_referendum_names_a_missing_feed(
    fa_2015_dir: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "fa"
    shutil.copytree(fa_2015_dir, copy)
    (copy / "valgdag_20.xml").unlink()

    with pytest.raises(FeedError, match=r"valgdag_20\.xml"):
        load_election(copy)


def test_build_election_referendum_equals_load_election_and_reads_in_overview_order(
    fa_2022_dir: Path, fa_2022: Election
) -> None:
    reads: list[str] = []

    def read(name: str) -> bytes:
        reads.append(name)
        return (fa_2022_dir / name).read_bytes()

    built = build_election((fa_2022_dir / "valgdag.xml").read_bytes(), read)

    assert built == fa_2022
    assert len(reads) == 107
    overview = parse_overview((fa_2022_dir / "valgdag.xml").read_bytes())
    assert reads == [f.file_name for f in overview.feeds]


def test_build_election_refuses_an_unsupported_name_before_reading_any_feed() -> None:
    xml = _fa_overview(name="Kommunalvalg 2025")

    with pytest.raises(FeedError, match="Kommunalvalg 2025"):
        build_election(xml, lambda name: pytest.fail(f"read {name}"))


@pytest.mark.parametrize("count", [94, 92, 1, 0])
def test_referendum_progress_total_comes_from_the_overview_not_a_constant(
    count: int,
) -> None:
    kreds = [kreds_entry(str(100 + i), f"K{i}") for i in range(count)]
    land = entry("Land", "Hele landet", "valgdag_0.xml", land_id="0")

    election = build_election(_fa_overview(land, *kreds), lambda _name: _fa_feed())

    progress = election.counting_progress()
    assert (progress.counted, progress.total) == (count, count)
    assert str(progress) == f"{count}/{count}"


def test_referendum_progress_counts_only_reported_districts_of_the_overview() -> None:
    kreds = [kreds_entry("20", "A"), kreds_entry("21", "B")]
    never = kreds_entry(
        "22", "C", senest="01-01-0001 00:00:00", iso="0001-01-01T00:00:00"
    )
    overview = _fa_overview(*kreds, never)

    election = build_election(overview, lambda _name: _fa_feed())

    progress = election.counting_progress()
    assert (progress.counted, progress.total) == (2, 3)


# --- A3 / T3: the adapter -------------------------------------------------------------


def test_adapter_parses_each_real_overview_as_a_referendum(
    fa_2022_dir: Path, fa_2015_dir: Path, fa_2009_dir: Path
) -> None:
    overviews = [
        parse_overview((d / "valgdag.xml").read_bytes())
        for d in (fa_2022_dir, fa_2015_dir, fa_2009_dir)
    ]

    assert [o.election_type for o in overviews] == [ElectionType.FOLKEAFSTEMNING] * 3
    assert [o.name for o in overviews] == [FA_2022_NAME, FA_2015_NAME, FA_2009_NAME]
    assert [len(o.feeds) for o in overviews] == [107, 107, 109]


@pytest.mark.parametrize(
    ("adapter_name", "prefix"),
    [
        ("folketingsvalg", "Folketingsvalg"),
        ("europaparlamentsvalg", "Europa-Parlamentsvalg"),
        ("folkeafstemning", "Folkeafstemning"),
    ],
)
@pytest.mark.parametrize(
    "directory_name", ["fixture_dir", "ep_fixture_dir", "fa_2022_dir"]
)
def test_each_adapter_accepts_only_its_own_overview_and_names_the_value_otherwise(
    request: pytest.FixtureRequest, adapter_name: str, prefix: str, directory_name: str
) -> None:
    adapters = {
        "folketingsvalg": folketingsvalg,
        "europaparlamentsvalg": europaparlamentsvalg,
        "folkeafstemning": folkeafstemning,
    }
    directory: Path = request.getfixturevalue(directory_name)
    xml = (directory / "valgdag.xml").read_bytes()
    own = {
        "fixture_dir": "folketingsvalg",
        "ep_fixture_dir": "europaparlamentsvalg",
        "fa_2022_dir": "folkeafstemning",
    }[directory_name]

    if own == adapter_name:
        assert adapters[adapter_name].parse_overview(xml).feeds
    else:
        with pytest.raises(FeedError, match=f"not a {prefix}, ValgNavn is '") as caught:
            adapters[adapter_name].parse_overview(xml)
        assert "valgdag.xml" in str(caught.value)


def test_adapter_reexports_the_shared_names_and_all_matches_the_ep_adapter() -> None:
    from dkvalg.adapters import dst_feed

    assert folkeafstemning.parse_place is dst_feed.parse_place
    assert folkeafstemning.FeedRef is dst_feed.FeedRef
    assert folkeafstemning.Overview is dst_feed.Overview
    assert folkeafstemning.unreported_place is dst_feed.unreported_place
    assert sorted(folkeafstemning.__all__) == sorted(europaparlamentsvalg.__all__)
    assert ElectionType("folkeafstemning") is ElectionType.FOLKEAFSTEMNING


@pytest.mark.parametrize(
    "name",
    [
        "Folkeafstemning",
        "Folkeafstemning onsdag  1. juni 2022",
        "Folkeafstemninger",  # a longer word is accepted: startswith, as for the others
    ],
)
def test_adapter_accepts_names_that_start_with_the_prefix(name: str) -> None:
    overview = parse_overview(_fa_overview(name=name))

    assert overview.election_type is ElectionType.FOLKEAFSTEMNING
    assert overview.name == name


@pytest.mark.parametrize(
    ("raw", "stripped"),
    [
        (f"  {FA_2022_NAME}\n", FA_2022_NAME),
        (f"\t{FA_2015_NAME} ", FA_2015_NAME),
        (f" Folkeafstemning x{chr(10)}", "Folkeafstemning x"),
    ],
)
def test_adapter_strips_outer_whitespace_and_keeps_interior_spaces(
    raw: str, stripped: str
) -> None:
    assert parse_overview(_fa_overview(name=raw)).name == stripped


@pytest.mark.parametrize(
    "name",
    [
        "folkeafstemning",
        "FOLKEAFSTEMNING",
        "x Folkeafstemning",
        "Folke afstemning",
        "Afstemning",
        "Kommunalvalg 2025",
        "Folketingsvalg",
    ],
)
def test_adapter_refuses_other_names_naming_the_value(name: str) -> None:
    with pytest.raises(FeedError) as caught:
        parse_overview(_fa_overview(name=name))

    assert (
        str(caught.value) == f"valgdag.xml: not a Folkeafstemning, ValgNavn is {name!r}"
    )


@pytest.mark.parametrize(
    "xml",
    [
        b"<Data><ValgDato>01-06-2022</ValgDato></Data>",
        b"<Data><ValgNavn/></Data>",
        b"<Data><ValgNavn>   </ValgNavn></Data>",
    ],
)
def test_adapter_and_registry_say_no_valgnavn_when_the_name_is_missing(
    xml: bytes,
) -> None:
    for parse in (parse_overview, registry.parse_any_overview):
        with pytest.raises(FeedError, match=r"valgdag\.xml: no ValgNavn"):
            parse(xml)


@pytest.mark.parametrize(
    "date_text", [None, "", "31-02-2022", "2022-06-01", "1-6-2022"]
)
def test_adapter_refuses_a_missing_or_bad_date_naming_it(date_text: str | None) -> None:
    with pytest.raises(FeedError, match="bad ValgDato"):
        parse_overview(_fa_overview(election_date=date_text))


def test_adapter_accepts_the_dst_date_form() -> None:
    assert parse_overview(_fa_overview()).election_date.isoformat() == "2022-06-01"


def test_adapter_refuses_an_overview_listing_no_feeds() -> None:
    xml = overview_xml([], name=FA_2022_NAME, election_date="01-06-2022")

    with pytest.raises(FeedError, match="lists no result feeds"):
        parse_overview(xml)


@pytest.mark.parametrize("bom", [True, False])
def test_overview_with_and_without_a_bom_parses_equal(bom: bool) -> None:
    xml = _fa_overview(bom=bom)

    assert xml.startswith(BOM) is bom
    assert parse_overview(xml) == parse_overview(_fa_overview(bom=not bom))


def test_overview_in_utf16_with_a_matching_declaration_parses_equal(
    fa_2022_dir: Path,
) -> None:
    text = (fa_2022_dir / "valgdag.xml").read_text(encoding="utf-8-sig")
    original = parse_overview((fa_2022_dir / "valgdag.xml").read_bytes())
    utf16 = text.replace('encoding="utf-8"', 'encoding="utf-16"').encode("utf-16")

    assert parse_overview(utf16) == original


def test_overview_in_utf16_under_a_utf8_declaration_is_a_feed_error_naming_the_file(
    fa_2022_dir: Path,
) -> None:
    text = (fa_2022_dir / "valgdag.xml").read_text(encoding="utf-8-sig")

    with pytest.raises(FeedError, match=r"valgdag\.xml: malformed XML"):
        parse_overview(text.encode("utf-16"))


@pytest.mark.parametrize("xml", [b"", b"<Data>", b"not xml", b"\xff\xfe\x00garbage"])
def test_adapter_malformed_xml_is_a_feed_error_naming_the_file(xml: bytes) -> None:
    with pytest.raises(FeedError, match=r"valgdag\.xml"):
        parse_overview(xml)


# --- overview entries: timestamps and parents -----------------------------------------


@pytest.mark.parametrize(
    ("senest", "iso", "expected"),
    [
        ("01-06-2022 21:30:00", None, dt("2022-06-01T21:30:00")),
        ("01-06-2022 21:30:00", "", dt("2022-06-01T21:30:00")),
        ("01-01-0001 00:00:00", None, None),
        (None, None, None),
        (None, "2022-06-01T21:30:00", dt("2022-06-01T21:30:00")),
    ],
)
def test_overview_without_an_iso_stamp_falls_back_to_the_dst_form(
    senest: str | None, iso: str | None, expected: object
) -> None:
    xml = _fa_overview(kreds_entry("20", "K", senest=senest, iso=iso))

    (feed,) = parse_overview(xml).feeds

    assert feed.last_changed == expected


@pytest.mark.parametrize(
    ("senest", "iso", "message"),
    [
        ("1-6-2022 21:30", None, "bad timestamp"),
        (None, "2022-06-01T21:30:00+02:00", "UTC offset"),
    ],
)
def test_overview_with_a_bad_timestamp_is_refused_naming_the_entry(
    senest: str | None, iso: str | None, message: str
) -> None:
    xml = _fa_overview(kreds_entry("20", "K", senest=senest, iso=iso))

    with pytest.raises(FeedError, match=message):
        parse_overview(xml)


def test_overview_opstillingskreds_without_a_storkreds_id_has_no_parent() -> None:
    xml = _fa_overview(
        entry("Opstillingskreds", "K", "valgdag_20.xml", opstillingskreds_id="20")
    )

    (feed,) = parse_overview(xml).feeds

    assert feed.parent_id is None


# --- A5 / T5: result feeds under a referendum -----------------------------------------


def test_status_zero_feed_in_dsts_example_shape_is_figure_free() -> None:
    xml = _fa_feed(
        status="0",
        status_text="Resultatet foreligger endnu ikke.",
        stemmer=None,
        eligible=None,
        turnout=None,
    )

    place = parse_place(xml, make_ref("20"))

    assert place.status is Status.NOT_AVAILABLE
    assert place.status_text == "Resultatet foreligger endnu ikke."
    assert place.parties == ()
    assert place.eligible_voters is None
    assert place.leader is None


def test_status_one_feed_with_only_the_two_answers_has_a_leader() -> None:
    place = parse_place(_fa_feed(), make_ref("20"))

    assert place.status is Status.PRELIMINARY
    assert [(p.letter, p.votes) for p in place.parties] == [("JA", 600), ("NEJ", 400)]
    assert place.leader is not None
    assert place.leader.letter == "JA"
    assert place.valid_votes == 1000
    assert place.blank_votes == 5


@pytest.mark.parametrize("status", ["0", "9", "10"])
def test_statuses_without_a_result_drop_the_answers_even_with_a_stemmer(
    status: str,
) -> None:
    place = parse_place(_fa_feed(status=status), make_ref("20"))

    assert place.parties == ()
    assert place.total_votes is None
    assert place.leader is None
    assert not place.has_result


@pytest.mark.parametrize("status", ["11", "12"])
def test_recount_statuses_with_a_result_keep_the_answers(status: str) -> None:
    place = parse_place(_fa_feed(status=status), make_ref("20"))

    assert place.has_result
    assert len(place.parties) == 2


@pytest.mark.parametrize("status", ["2", "abc", "", None])
def test_an_unknown_or_missing_status_code_is_a_feed_error(status: str | None) -> None:
    with pytest.raises(FeedError, match="unknown status code"):
        parse_place(_fa_feed(status=status), make_ref("20"))


def test_a_result_status_without_a_stemmer_is_refused_naming_the_feed() -> None:
    with pytest.raises(FeedError, match=r"valgdag_20\.xml: status 1 but no Stemmer"):
        parse_place(_fa_feed(stemmer=None), make_ref("20"))


@pytest.mark.parametrize(
    ("answers", "leader"),
    [
        ([], None),
        ([("1", "JA", 0)], None),
        ([("1", "JA", 5)], "JA"),
        ([("1", "JA", 100), ("2", "NEJ", 100)], "JA"),
        ([("1", "JA", 0), ("2", "NEJ", 0)], None),
        ([("1", "JA", 0), ("2", "NEJ", 1)], "NEJ"),
        ([("1", "JA", 5), ("2", "NEJ", 9), ("3", "BLANK", 7)], "NEJ"),
    ],
)
def test_the_number_of_answers_is_whatever_the_feed_lists_and_the_leader_follows(
    answers: list[tuple[str, str, int]], leader: str | None
) -> None:
    stemmer = (
        "".join(_answer(*a) for a in answers)
        + "<IAltGyldigeStemmer>1</IAltGyldigeStemmer>"
    )

    place = parse_place(_fa_feed(stemmer=stemmer), make_ref("20"))

    assert [p.letter for p in place.parties] == [a[1] for a in answers]
    assert (place.leader.letter if place.leader else None) == leader


def test_an_answer_without_an_id_is_refused_naming_the_feed_and_the_answer() -> None:
    stemmer = '<Parti Bogstav="JA" Navn="JA" StemmerAntal="1" StemmerPct="1.0" />'

    with pytest.raises(FeedError, match=r"valgdag_20\.xml: <Parti> 'JA' has no Id"):
        parse_place(_fa_feed(stemmer=stemmer), make_ref("20"))


def test_an_answer_with_an_empty_id_is_accepted_but_is_not_a_party_and_never_leads() -> (
    None
):
    stemmer = (
        '<Parti Id="" Bogstav="JA" Navn="JA" StemmerAntal="900" StemmerPct="90.0" />'
        + _answer("2", "NEJ", 10)
    )

    place = parse_place(_fa_feed(stemmer=stemmer), make_ref("20"))

    assert [p.is_party for p in place.parties] == [False, True]
    assert place.leader is not None
    assert place.leader.letter == "NEJ"


def test_an_answer_with_an_empty_letter_keeps_it_empty() -> None:
    stemmer = '<Parti Id="1" Bogstav="" Navn="x" StemmerAntal="1" StemmerPct="1.0" />'

    (answer,) = parse_place(_fa_feed(stemmer=stemmer), make_ref("20")).parties

    assert answer.letter == ""
    assert answer.is_party


@pytest.mark.parametrize("bad", ["nan", "inf", "1_000", "1e3", ""])
def test_a_non_numeric_answer_figure_is_refused(bad: str) -> None:
    stemmer = (
        f'<Parti Id="1" Bogstav="JA" Navn="JA" StemmerAntal="{bad}" StemmerPct="1.0" />'
    )

    with pytest.raises(FeedError, match="bad StemmerAntal"):
        parse_place(_fa_feed(stemmer=stemmer), make_ref("20"))


def test_a_never_reported_feed_becomes_a_placeholder_and_is_never_read() -> None:
    overview_bytes = _fa_overview(
        kreds_entry("20", "K", senest="01-01-0001 00:00:00", iso="0001-01-01T00:00:00"),
    )
    overview = parse_overview(overview_bytes)

    election = build_election(overview_bytes, lambda _name: pytest.fail("read"))

    assert overview.feeds[0].last_changed is None
    (place,) = election.places
    assert place == unreported_place(overview.feeds[0])
    assert place.status is Status.NOT_AVAILABLE
    assert election.election_type is ElectionType.FOLKEAFSTEMNING


def test_the_feed_timestamp_is_naive_local_time_and_falls_back_to_the_overview() -> (
    None
):
    ref = make_ref("20", last_changed=dt("2022-06-01T21:00:00"))
    no_stamp = (
        _fa_feed().replace(b"SenestRettetIso", b"X").replace(b"SenestRettet>", b"Y>")
    )

    own = parse_place(_fa_feed(), ref)
    fallback = parse_place(no_stamp, ref)

    assert own.last_changed == dt("2026-03-24T22:00:00")
    assert own.last_changed is not None
    assert own.last_changed.tzinfo is None
    assert fallback.last_changed == dt("2022-06-01T21:00:00")


def test_overview_with_a_doctype_is_refused_naming_the_file() -> None:
    with pytest.raises(FeedError, match=r"valgdag\.xml.*DOCTYPE"):
        parse_overview(_inject_doctype(_fa_overview(bom=False)))


def test_result_feed_with_a_doctype_is_refused_naming_the_feed() -> None:
    with pytest.raises(FeedError, match=r"valgdag_20\.xml.*DOCTYPE"):
        parse_place(_inject_doctype(_fa_feed(bom=False)), make_ref("20"))


def test_directory_with_an_entity_in_a_result_feed_is_refused_by_load_election(
    fa_2022_copy: Path,
) -> None:
    target = fa_2022_copy / "valgdag_20.xml"
    target.write_bytes(_inject_doctype(target.read_bytes().removeprefix(BOM)))

    with pytest.raises(FeedError, match=r"valgdag_20\.xml"):
        load_election(fa_2022_copy)


def test_synthetic_directory_loads_as_a_referendum(tmp_path: Path) -> None:
    directory = write_directory(
        tmp_path / "fa", _fa_overview(), {"valgdag_20.xml": _fa_feed()}
    )

    election = load_election(directory)

    assert election.election_type is ElectionType.FOLKEAFSTEMNING
    assert election.counting_progress().counted == 1


def test_the_showcases_run_and_show_the_referendum(
    capsys: pytest.CaptureFixture[str],
) -> None:
    folkeafstemning.main()
    adapter_out = capsys.readouterr().out
    registry.main()
    registry_out = capsys.readouterr().out

    assert "JA: 1848738 votes (66.9 %)" in adapter_out
    assert "NEJ: 914829 votes (33.1 %)" in adapter_out
    assert "Folkeafstemning" in registry_out
    assert "refused:" in registry_out
    assert (
        "(Folketingsvalg, Europa-Parlamentsvalg, Folkeafstemning), "
        "ValgNavn is 'Kommunalvalg 2025'" in registry_out
    )


# --- A4 / T4: referenda through HttpSource, Recorder, CaptureReplay, ReplaySource ------


def test_http_source_first_fetch_equals_load_election_for_2022(
    fa_transport: FakeTransport, fa_2022: Election
) -> None:
    source = HttpSource(LOCATION_2022, transport=fa_transport, clock=FakeClock())

    result = source.fetch()

    assert result.election == fa_2022
    assert result.election.election_type is ElectionType.FOLKEAFSTEMNING
    assert len(result.changed) == 107
    assert source.election == fa_2022
    assert all(r.url.startswith(FA_2022_BASE_URL) for r in fa_transport.requests)
    assert len(fa_transport.requests) == 108


def test_http_source_first_fetch_equals_load_election_for_2009_and_second_is_unchanged(
    fa_2009_transport: FakeTransport, fa_2009: Election
) -> None:
    source = HttpSource(LOCATION_2009, transport=fa_2009_transport, clock=FakeClock())

    first = source.fetch()
    second = source.fetch()

    assert first.election == fa_2009
    assert len(first.changed) == 109
    assert second.changed == ()
    assert second.election == fa_2009
    assert fa_2009_transport.requests[0].url.startswith(FA_2009_BASE_URL)
    assert first.election.counting_progress().total == 94


def test_http_source_refetches_only_the_touched_referendum_feed(
    fa_transport: FakeTransport,
) -> None:
    source = HttpSource(LOCATION_2022, transport=fa_transport, clock=FakeClock())
    source.fetch()
    fa_transport.touch([NATIONAL])

    result = source.fetch()
    requested = fa_transport.names[-2:]
    unchanged = source.fetch()

    assert [p.place_id for p in result.changed] == ["0"]
    assert requested == ["valgdag.xml", NATIONAL]
    assert unchanged.changed == ()


def test_http_source_overview_retime_without_new_figures_changes_nothing(
    fa_transport: FakeTransport,
) -> None:
    source = HttpSource(LOCATION_2022, transport=fa_transport, clock=FakeClock())
    first = source.fetch()
    fa_transport.retime_only([NATIONAL])

    result = source.fetch()

    assert result.changed == ()
    assert result.election == first.election


def test_http_source_a_referendum_feed_that_becomes_never_reported_is_a_placeholder(
    fa_transport: FakeTransport,
) -> None:
    source = HttpSource(LOCATION_2022, transport=fa_transport, clock=FakeClock())
    source.fetch()
    fa_transport.never_reported("valgdag_20.xml")

    result = source.fetch()

    placeholder = result.election.get(PlaceType.OPSTILLINGSKREDS, "20")
    assert placeholder.status is Status.NOT_AVAILABLE
    assert placeholder.parties == ()
    progress = result.election.counting_progress()
    assert (progress.counted, progress.total) == (91, 92)


def test_http_source_refuses_an_overview_that_becomes_a_kommunalvalg_and_keeps_its_state(
    fa_transport: FakeTransport,
) -> None:
    source = HttpSource(LOCATION_2022, transport=fa_transport, clock=FakeClock())
    first = source.fetch()
    fa_transport.publish(
        "valgdag.xml",
        fa_transport.files["valgdag.xml"].replace(b"Folkeafstemning", b"Kommunalvalg"),
    )
    before = len(fa_transport.requests)

    with pytest.raises(FeedError, match="Kommunalvalg"):
        source.fetch()

    assert source.election == first.election
    assert len(fa_transport.requests) == before + 1


def test_recorded_referendum_poll_replays_through_capture_replay_ending_equal(
    fa_transport: FakeTransport, tmp_path: Path
) -> None:
    capture = tmp_path / "cap"
    source = HttpSource(
        LOCATION_2022,
        transport=fa_transport,
        recorder=Recorder(capture),
        clock=FakeClock(),
    )
    list(poll(source, max_cycles=2, sleep=lambda _s: None))
    fa_transport.touch([NATIONAL, "valgdag_20.xml"])
    list(poll(source, max_cycles=1, sleep=lambda _s: None))

    steps = list(CaptureReplay(capture, speed=float("inf")))
    again = list(CaptureReplay(capture, speed=float("inf")))

    assert len(steps) == 2
    assert steps[-1].election == source.election
    assert steps[-1].election.election_type is ElectionType.FOLKEAFSTEMNING
    assert steps[0].election.counting_progress().counted == 92
    assert {p.place_id for p in steps[-1].changed} == {"0", "20"}
    assert [s.election for s in again] == [s.election for s in steps]


def test_replay_source_of_the_referendums_ends_equal_to_the_loaded_election(
    fa_2022: Election, fa_2009: Election
) -> None:
    for election, steps_expected, total in ((fa_2022, 107, 92), (fa_2009, 109, 94)):
        source = ReplaySource(election, speed=float("inf"))

        steps = list(source)

        assert source.initial().election_type is ElectionType.FOLKEAFSTEMNING
        assert source.initial().counting_progress().counted == 0
        assert len(steps) == steps_expected
        assert steps[-1].election == election
        assert (steps[-1].progress.counted, steps[-1].progress.total) == (total, total)


# --- A4 / T4: the CLI on referenda ----------------------------------------------------

STEP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}  +(\d+)/(\d+)  (\S+) (.+)$")


def _cli(argv: list[str], **kwargs: object) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(argv, out=out, err=err, sleep=lambda _s: None, **kwargs)  # type: ignore[arg-type]  # forwarded as-is
    return code, out.getvalue(), err.getvalue()


def _ja_row(percent: float, votes: int) -> str:
    return f"{'JA':<4}{'JA':<48}{percent:>6.1f}%{votes:>11}{'-':>6}"


def _nej_row(percent: float, votes: int) -> str:
    return f"{'NEJ':<4}{'NEJ':<48}{percent:>6.1f}%{votes:>11}{'-':>6}"


def test_cli_replay_of_2022_prints_107_lines_ending_92_of_92_and_exact_table_rows(
    fa_2022_dir: Path,
) -> None:
    code, out, err = _cli(["replay", str(fa_2022_dir), "--speed", "inf"])

    lines = [line for line in out.splitlines() if STEP.match(line)]
    assert (code, err) == (0, "")
    assert len(lines) == 107
    assert "92/92" in lines[-1]
    rows = out.splitlines()
    assert _ja_row(66.9, 1_848_738) in rows
    assert _nej_row(33.1, 914_829) in rows
    assert "Hele landet: Foreløbigt resultat" in rows


def test_cli_replay_of_2022_table_separates_nej_from_its_name_and_shows_dashes(
    fa_2022_dir: Path,
) -> None:
    _, out, _ = _cli(["replay", str(fa_2022_dir), "--speed", "inf"])

    table = out.split("\n\n", 1)[1].splitlines()[1:]
    assert len(table) == 2
    assert table[0].startswith("JA  JA ")
    assert table[1].startswith("NEJ NEJ ")
    assert all(line.endswith("-") for line in table)


def test_cli_replay_of_2009_ends_at_94_of_94(fa_2009_dir: Path) -> None:
    code, out, err = _cli(["replay", str(fa_2009_dir), "--speed", "inf"])

    lines = [line for line in out.splitlines() if STEP.match(line)]
    assert (code, err) == (0, "")
    assert len(lines) == 109
    assert "94/94" in lines[-1]
    assert _ja_row(85.3, 1_858_008) in out.splitlines()


def test_cli_replay_of_2015_table_has_nej_winning(fa_2015_dir: Path) -> None:
    _, out, _ = _cli(["replay", str(fa_2015_dir), "--speed", "inf"])

    assert _ja_row(46.9, 1_377_538) in out.splitlines()
    assert _nej_row(53.1, 1_556_582) in out.splitlines()


def test_cli_poll_on_a_referendum_fake_transport_prints_its_lines(
    fa_transport: FakeTransport,
) -> None:
    code, out, err = _cli(
        ["poll", LOCATION_2022, "--cycles", "1"],
        transport=fa_transport,
        clock=FakeClock(),
    )

    lines = out.splitlines()
    assert (code, err) == (0, "")
    assert len(lines) == 107
    assert lines[0].startswith("2026-03-24 20:00:00+00:00")
    assert "country Hele landet" in out
    assert "92/92" in lines[0]


def test_cli_poll_on_a_url_for_a_referendum_works_the_same_as_the_id(
    fa_transport: FakeTransport,
) -> None:
    code, out, _ = _cli(
        ["poll", FA_2022_BASE_URL, "--cycles", "1"],
        transport=fa_transport,
        clock=FakeClock(),
    )

    assert code == 0
    assert len(out.splitlines()) == 107


@pytest.mark.parametrize(
    ("speed", "code"),
    [("0", 2), ("-1", 2), ("nan", 2), ("inf", 0), ("1e-300", 0), ("1", 0)],
)
def test_cli_replay_of_a_referendum_validates_the_speed(
    fa_2009_dir: Path, speed: str, code: int
) -> None:
    slept: list[float] = []
    out, err = io.StringIO(), io.StringIO()

    result = run(
        ["replay", str(fa_2009_dir), "--speed", speed],
        out=out,
        err=err,
        sleep=slept.append,
    )

    assert result == code
    assert (err.getvalue() == "") is (code == 0)


@pytest.mark.parametrize(
    ("interval", "code"), [("14.99", 2), ("nan", 2), ("inf", 2), ("15", 0)]
)
def test_cli_poll_of_a_referendum_validates_the_interval(
    fa_transport: FakeTransport, interval: str, code: int
) -> None:
    result, _, _ = _cli(
        ["poll", LOCATION_2022, "--interval", interval, "--cycles", "1"],
        transport=fa_transport,
        clock=FakeClock(),
    )

    assert result == code


# --- T4: the national table's letter column, on synthetic countries --------------------


def _tables(tmp_path: Path, *countries: str) -> list[list[str]]:
    """Replay a directory of country feeds and return each printed table's rows."""
    entries = [
        entry("Land", f"Land {i}", f"valgdag_{i}.xml", land_id=str(i))
        for i in range(len(countries))
    ]
    feeds = {
        f"valgdag_{i}.xml": _fa_feed(stemmer=stemmer)
        for i, stemmer in enumerate(countries)
    }
    directory = write_directory(tmp_path / "d", _fa_overview(*entries), feeds)
    code, out, err = _cli(["replay", str(directory), "--speed", "inf"])
    assert (code, err) == (0, "")
    return [block.splitlines()[1:] for block in out.split("\n\n")[1:]]


def _party(letter: str, name: str = "N", votes: int = 10) -> str:
    return (
        f'<Parti Id="{letter or "x"}" Bogstav="{letter}" Navn="{name}" '
        f'StemmerAntal="{votes}" StemmerPct="1.0" />\n'
    )


@pytest.mark.parametrize(
    ("letter", "width"),
    [("A", 3), ("AB", 3), ("ABC", 4), ("ABCD", 5), ("ABCDE", 6)],
)
def test_table_letter_column_is_the_longest_letter_plus_one_and_at_least_three(
    tmp_path: Path, letter: str, width: int
) -> None:
    ((row,),) = _tables(tmp_path, _party(letter))

    assert row.startswith(f"{letter:<{width}}N")
    assert row[width] == "N"


def test_table_width_follows_the_longest_letter_not_the_first_row(
    tmp_path: Path,
) -> None:
    ((first, second, third),) = _tables(
        tmp_path, _party("JA") + _party("NEJ") + _party("BLANK")
    )

    assert [line[6] for line in (first, second, third)] == ["N", "N", "N"]
    assert first.startswith("JA    N")
    assert third.startswith("BLANK N")


def test_table_dash_for_an_empty_letter_counts_as_one_character(tmp_path: Path) -> None:
    stemmer = (
        _party("NEJ")
        + '<Parti Id="" Navn="Uden for partier" StemmerAntal="1" StemmerPct="0.1" />'
    )

    ((nej, outside),) = _tables(tmp_path, stemmer)

    assert nej.startswith("NEJ N")
    assert outside.startswith("-   Uden for partier")


def test_table_width_is_computed_per_country(tmp_path: Path) -> None:
    first, second = _tables(
        tmp_path, _party("JA") + _party("NEJ"), _party("A") + _party("B")
    )

    assert [row[4] for row in first] == ["N", "N"]
    assert [row[3] for row in second] == ["N", "N"]
    assert first[0].startswith("JA  N")
    assert second[0].startswith("A  N")


def test_table_of_a_country_without_a_result_is_a_header_only(tmp_path: Path) -> None:
    entries = [entry("Land", "Hele landet", "valgdag_0.xml", land_id="0")]
    feed = _fa_feed(
        status="0",
        status_text="Resultatet foreligger endnu ikke.",
        stemmer=None,
        eligible=None,
        turnout=None,
    )
    directory = write_directory(
        tmp_path / "d", _fa_overview(*entries), {"valgdag_0.xml": feed}
    )

    code, out, err = _cli(["replay", str(directory), "--speed", "inf"])

    assert (code, err) == (0, "")
    assert out.endswith("\nHele landet: Resultatet foreligger endnu ikke.\n")
