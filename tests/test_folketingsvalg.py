import dataclasses
import time
from datetime import date
from pathlib import Path

import pytest
from conftest import (
    BOM,
    PARTIES_XML,
    ROOT,
    dt,
    entry,
    feed_xml,
    kreds_entry,
    make_ref,
    overview_xml,
)

from dkvalg import ElectionType, FeedError, PlaceType, Status
from dkvalg.adapters.folketingsvalg import (
    FeedRef,
    parse_overview,
    parse_place,
    unreported_place,
)

REF = make_ref("20", last_changed=dt("2026-03-24T21:00:00"))


# --- parse_overview ------------------------------------------------------------


def test_parse_overview_reads_name_date_type_and_all_107_feeds(
    fixture_dir: Path,
) -> None:
    overview = parse_overview((fixture_dir / "valgdag.xml").read_bytes())

    assert overview.name == "Folketingsvalg tirsdag 24. marts 2026"
    assert overview.election_date == date.fromisoformat("2026-03-24")
    assert overview.election_type is ElectionType.FOLKETINGSVALG
    counts = {t: 0 for t in PlaceType}
    for feed in overview.feeds:
        counts[feed.place_type] += 1
    assert counts == {
        PlaceType.COUNTRY: 1,
        PlaceType.TALLY: 1,
        PlaceType.LANDSDEL: 3,
        PlaceType.STORKREDS: 10,
        PlaceType.OPSTILLINGSKREDS: 92,
    }
    assert len(overview.feeds) == 107


def test_parse_overview_maps_ids_parents_and_file_names(fixture_dir: Path) -> None:
    overview = parse_overview((fixture_dir / "valgdag.xml").read_bytes())
    by_key = {(f.place_type, f.place_id): f for f in overview.feeds}

    hovedstaden = by_key[(PlaceType.LANDSDEL, "7")]
    assert hovedstaden.name == "Hovedstaden"
    assert hovedstaden.parent_id == "0"
    assert hovedstaden.file_name == "valgdag_7.xml"
    assert hovedstaden.last_changed == dt("2026-03-25T00:12:26")
    assert by_key[(PlaceType.STORKREDS, "10")].parent_id == "7"
    assert by_key[(PlaceType.OPSTILLINGSKREDS, "20")].parent_id == "10"
    assert by_key[(PlaceType.OPSTILLINGSKREDS, "20")].name == "1.Østerbro"
    country = by_key[(PlaceType.COUNTRY, "0")]
    assert (country.parent_id, country.file_name) == (None, "valgdag_0.xml")
    tally = by_key[(PlaceType.TALLY, "999")]
    assert (tally.parent_id, tally.file_name) == (None, "valgdag_999.xml")


def test_parse_overview_synthetic_place_type_rules() -> None:
    xml = overview_xml(
        [
            entry("Land", "Hele landet", "valgdag_0.xml", land_id="0"),
            entry("Land", "Optalling", "valgdag_999.xml"),
            entry("Landsdel", "L", "valgdag_7.xml", landsdel_id="7", land_id="0"),
            entry(
                "Storkreds", "S", "valgdag_10.xml", storkreds_id="10", landsdel_id="7"
            ),
            kreds_entry("20", "K"),
        ]
    )

    feeds = parse_overview(xml).feeds

    assert [(f.place_type, f.place_id, f.parent_id) for f in feeds] == [
        (PlaceType.COUNTRY, "0", None),
        (PlaceType.TALLY, "999", None),
        (PlaceType.LANDSDEL, "7", "0"),
        (PlaceType.STORKREDS, "10", "7"),
        (PlaceType.OPSTILLINGSKREDS, "20", "10"),
    ]


def test_parse_overview_landsdel_without_land_id_gets_parent_zero() -> None:
    xml = overview_xml([entry("Landsdel", "L", "valgdag_7.xml", landsdel_id="7")])

    assert parse_overview(xml).feeds[0].parent_id == "0"


def test_parse_overview_ignores_afstemningsomraader_entries() -> None:
    xml = overview_xml(
        [
            kreds_entry("20", "K"),
            "<Afstemningsomraader><Afstemningsomraade filnavn='x/valgdag_5.xml'>a"
            "</Afstemningsomraade></Afstemningsomraader>",
        ]
    )

    assert [f.place_id for f in parse_overview(xml).feeds] == ["20"]


def test_parse_overview_without_a_timestamp_gives_none() -> None:
    xml = overview_xml([kreds_entry("20", "K", senest=None, iso=None)])

    assert parse_overview(xml).feeds[0].last_changed is None


@pytest.mark.parametrize(
    ("senest", "iso"),
    [
        ("01-01-0001 00:00:00", None),
        ("01-01-0001 00:00:00", ""),
        (None, "0001-01-01T00:00:00"),
        ("24-03-2026 22:00:00", "0001-01-01T00:00:00"),
        ("", None),
        (None, "0001-01-01 00:00:00"),
    ],
)
def test_parse_overview_never_reported_timestamp_in_any_spelling_is_none(
    senest: str | None, iso: str | None
) -> None:
    xml = overview_xml([kreds_entry("20", "K", senest=senest, iso=iso)])

    assert parse_overview(xml).feeds[0].last_changed is None


def test_parse_overview_falls_back_to_senestrettet_when_iso_is_empty() -> None:
    xml = overview_xml([kreds_entry("20", "K", senest="24-03-2026 22:00:00", iso="")])

    assert parse_overview(xml).feeds[0].last_changed == dt("2026-03-24T22:00:00")


def test_parse_overview_reads_the_dst_format_when_there_is_no_iso() -> None:
    xml = overview_xml([kreds_entry("20", "K", senest="25-03-2026 00:12:26", iso=None)])

    assert parse_overview(xml).feeds[0].last_changed == dt("2026-03-25T00:12:26")


def test_parse_overview_keeps_non_ascii_names() -> None:
    xml = overview_xml([kreds_entry("20", "  Æ Ø Å Østerbro  ")])

    assert parse_overview(xml).feeds[0].name == "Æ Ø Å Østerbro"


def test_parse_overview_bom_and_bomless_give_equal_results() -> None:
    with_bom = overview_xml([kreds_entry("20", "K")], bom=True)
    without = overview_xml([kreds_entry("20", "K")], bom=False)

    assert with_bom.startswith(BOM)
    assert parse_overview(with_bom) == parse_overview(without)


def test_parse_overview_is_idempotent_and_returns_immutable_objects() -> None:
    xml = overview_xml([kreds_entry("20", "K")])

    first, second = parse_overview(xml), parse_overview(xml)

    assert first == second
    assert isinstance(first.feeds, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.name = "x"  # type: ignore[misc]  # frozen on purpose: that is the test


@pytest.mark.parametrize(
    "name",
    [
        "Europa-Parlamentsvalg 2024",
        "folketingsvalg",
        "x Folketingsvalg",
        "Folkeafstemning",
    ],
)
def test_parse_overview_rejects_other_election_types_naming_the_value(
    name: str,
) -> None:
    xml = overview_xml([kreds_entry("20", "K")], name=name)

    with pytest.raises(FeedError, match="not a Folketingsvalg") as caught:
        parse_overview(xml)

    assert name in str(caught.value)


@pytest.mark.parametrize("name", [None, ""])
def test_parse_overview_rejects_a_missing_or_empty_election_name(
    name: str | None,
) -> None:
    xml = overview_xml([kreds_entry("20", "K")], name=name)

    with pytest.raises(FeedError, match="ValgNavn"):
        parse_overview(xml)


@pytest.mark.parametrize(
    "election_date",
    ["2026-03-24", "24-3-2026", "31-02-2026", "00-00-0000", "", None, "24-03-26"],
)
def test_parse_overview_rejects_a_bad_election_date(election_date: str | None) -> None:
    xml = overview_xml([kreds_entry("20", "K")], election_date=election_date)

    with pytest.raises(FeedError, match="ValgDato"):
        parse_overview(xml)


def test_parse_overview_with_no_result_feeds_is_an_error() -> None:
    xml = overview_xml([])

    with pytest.raises(FeedError, match="no result feeds"):
        parse_overview(xml)


@pytest.mark.parametrize(
    ("broken", "message"),
    [
        (entry("Land", "T", "weird.xml"), "tally id"),
        (entry("Land", "T", None), "no filnavn"),
        (entry("Landsdel", "L", "valgdag_7.xml"), "landsdel_id"),
        (entry("Storkreds", "S", "valgdag_10.xml", landsdel_id="7"), "storkreds_id"),
        (
            entry("Opstillingskreds", "K", "valgdag_20.xml", storkreds_id="10"),
            "opstillingskreds_id",
        ),
        (
            entry("Opstillingskreds", "K", "xml/", opstillingskreds_id="20"),
            "no filnavn",
        ),
    ],
)
def test_parse_overview_rejects_entries_that_cannot_be_identified(
    broken: str, message: str
) -> None:
    xml = overview_xml([broken])

    with pytest.raises(FeedError, match=message):
        parse_overview(xml)


def test_parse_overview_keeps_the_query_string_of_a_file_name() -> None:
    xml = overview_xml(
        [
            entry(
                "Opstillingskreds",
                "K",
                "valgdag_20.xml?v=1",
                opstillingskreds_id="20",
                storkreds_id="10",
            )
        ]
    )

    assert parse_overview(xml).feeds[0].file_name == "valgdag_20.xml?v=1"


def test_parse_overview_keeps_duplicate_entries_in_order() -> None:
    xml = overview_xml([kreds_entry("20", "first"), kreds_entry("20", "second")])

    assert [f.name for f in parse_overview(xml).feeds] == ["first", "second"]


def test_parse_overview_entry_without_a_parent_attribute_has_no_parent() -> None:
    xml = overview_xml(
        [entry("Opstillingskreds", "K", "valgdag_20.xml", opstillingskreds_id="20")]
    )

    assert parse_overview(xml).feeds[0].parent_id is None


@pytest.mark.parametrize(
    "xml", [b"", b"   ", BOM, b"not xml", b"<Data><ValgNavn>Folketingsvalg", b"<a></b>"]
)
def test_parse_overview_malformed_xml_raises_feed_error_naming_the_overview(
    xml: bytes,
) -> None:
    with pytest.raises(FeedError, match="valgdag.xml"):
        parse_overview(xml)


def test_parse_overview_truncated_real_overview_raises_feed_error(
    fixture_dir: Path,
) -> None:
    data = (fixture_dir / "valgdag.xml").read_bytes()

    with pytest.raises(FeedError, match="malformed"):
        parse_overview(data[: len(data) // 2])


def test_parse_overview_non_bytes_input_is_a_type_error_not_a_feed_error() -> None:
    """Documented limitation: the signature says bytes, so `None` is a caller bug."""
    with pytest.raises(TypeError):
        parse_overview(None)  # type: ignore[arg-type]  # pinning the wrong-type behaviour


def test_parse_overview_with_a_utc_offset_timestamp_is_a_feed_error() -> None:
    xml = overview_xml(
        [kreds_entry("20", "K", senest=None, iso="2026-03-24T22:00:00+01:00")]
    )

    with pytest.raises(FeedError, match="UTC offset"):
        parse_overview(xml)


@pytest.mark.parametrize(
    "stamp", ["yesterday", "2026-13-45T00:00:00", "24/03/2026 22:00"]
)
def test_parse_overview_unreadable_timestamp_names_the_value(stamp: str) -> None:
    xml = overview_xml([kreds_entry("20", "K", senest=None, iso=stamp)])

    with pytest.raises(FeedError, match="bad timestamp") as caught:
        parse_overview(xml)

    assert stamp in str(caught.value)


# --- unreported_place ----------------------------------------------------------


def test_unreported_place_is_a_figure_free_placeholder() -> None:
    place = unreported_place(REF)

    assert (place.place_type, place.place_id, place.name, place.parent_id) == (
        PlaceType.OPSTILLINGSKREDS,
        "20",
        "1.Østerbro",
        "10",
    )
    assert place.status is Status.NOT_AVAILABLE
    assert place.status_text == ""
    assert place.last_changed is None
    assert place.parties == ()
    assert not place.has_result


def test_unreported_place_equals_the_unreported_form_of_a_parsed_place() -> None:
    parsed = parse_place(feed_xml(), REF)

    assert unreported_place(REF) == parsed.unreported()


def test_unreported_place_does_not_change_its_ref() -> None:
    ref = make_ref("20", last_changed=dt("2026-03-24T21:00:00"))
    before = dataclasses.replace(ref)

    unreported_place(ref)

    assert ref == before


# --- parse_place: real files ---------------------------------------------------


def _fixture_ref(fixture_dir: Path, file_name: str) -> FeedRef:
    overview = parse_overview((fixture_dir / "valgdag.xml").read_bytes())
    return next(f for f in overview.feeds if f.file_name == file_name)


def test_parse_place_hovedstaden_matches_its_file_field_by_field(
    fixture_dir: Path,
) -> None:
    ref = _fixture_ref(fixture_dir, "valgdag_7.xml")

    place = parse_place((fixture_dir / "valgdag_7.xml").read_bytes(), ref)

    assert place.place_type is PlaceType.LANDSDEL
    assert (place.place_id, place.name, place.parent_id) == ("7", "Hovedstaden", "0")
    assert place.status is Status.PRELIMINARY
    assert place.status_text == "Foreløbigt resultat"
    assert place.last_changed == dt("2026-03-25T00:12:26")
    assert place.eligible_voters == 1309177
    assert place.turnout_percent == 84.31
    assert place.valid_votes == 1091388
    assert place.blank_votes == 9870
    assert place.other_invalid_votes == 2478
    assert place.total_invalid_votes == 12348
    assert place.total_votes == 1103736
    assert len(place.parties) == 13
    socialdemokratiet = place.parties[0]
    assert socialdemokratiet.party_id == "5891"
    assert socialdemokratiet.letter == "A"
    assert socialdemokratiet.name == "A. Socialdemokratiet"
    assert socialdemokratiet.votes == 201493
    assert socialdemokratiet.percent == 18.5
    assert socialdemokratiet.seats == 10
    assert socialdemokratiet.constituency_seats == 10
    assert socialdemokratiet.supplementary_seats == 0


def test_parse_place_keeps_uden_for_partier_last_and_not_a_party(
    fixture_dir: Path,
) -> None:
    ref = _fixture_ref(fixture_dir, "valgdag_7.xml")

    place = parse_place((fixture_dir / "valgdag_7.xml").read_bytes(), ref)

    last = place.parties[-1]
    assert (last.party_id, last.letter, last.name) == ("", "", "Uden for partier")
    assert last.votes == 2002
    assert not last.is_party
    assert all(p.is_party for p in place.parties[:-1])


def test_parse_place_opstillingskreds_has_no_seat_figures(fixture_dir: Path) -> None:
    ref = _fixture_ref(fixture_dir, "valgdag_20.xml")

    place = parse_place((fixture_dir / "valgdag_20.xml").read_bytes(), ref)

    assert place.eligible_voters == 57695
    assert place.parties[0].votes == 7286
    assert all(
        (p.seats, p.constituency_seats, p.supplementary_seats) == (None, None, None)
        for p in place.parties
    )


def test_parse_place_tally_feed_has_a_status_text_with_progress(
    fixture_dir: Path,
) -> None:
    ref = _fixture_ref(fixture_dir, "valgdag_999.xml")

    place = parse_place((fixture_dir / "valgdag_999.xml").read_bytes(), ref)

    assert place.place_type is PlaceType.TALLY
    assert "92 af 92" in place.status_text
    assert all(p.seats is None for p in place.parties)


def test_parse_place_every_fixture_feed_parses(fixture_dir: Path) -> None:
    overview = parse_overview((fixture_dir / "valgdag.xml").read_bytes())

    for ref in overview.feeds:
        place = parse_place((fixture_dir / ref.file_name).read_bytes(), ref)
        assert place.status is Status.PRELIMINARY
        assert place.last_changed == ref.last_changed
        assert place.parties


def test_parse_place_truncated_real_feed_raises_feed_error_naming_the_file(
    fixture_dir: Path,
) -> None:
    ref = _fixture_ref(fixture_dir, "valgdag_7.xml")
    data = (fixture_dir / "valgdag_7.xml").read_bytes()

    with pytest.raises(FeedError, match="valgdag_7.xml"):
        parse_place(data[: len(data) // 2], ref)


# --- parse_place: synthetic feeds ----------------------------------------------


def test_parse_place_bom_and_bomless_give_equal_places() -> None:
    assert parse_place(feed_xml(bom=True), REF) == parse_place(feed_xml(bom=False), REF)


def test_parse_place_takes_id_name_and_parent_from_the_ref() -> None:
    ref = make_ref("77", name="Ref Name", parent_id="5", last_changed=None)

    place = parse_place(feed_xml(), ref)

    assert (place.place_id, place.name, place.parent_id) == ("77", "Ref Name", "5")


def test_parse_place_status_zero_without_stemmer_gives_a_figure_free_place() -> None:
    xml = feed_xml(
        status="0",
        status_text="Resultat endnu ikke tilgængeligt",
        senest="01-01-0001 00:00:00",
        iso=None,
        stemmer=None,
        eligible=None,
        turnout=None,
    )

    place = parse_place(xml, REF)

    assert place.status is Status.NOT_AVAILABLE
    assert place.status_text == "Resultat endnu ikke tilgængeligt"
    assert place.parties == ()
    assert place.eligible_voters is None
    assert place.valid_votes is None
    assert not place.has_result


@pytest.mark.parametrize(
    ("code", "status"),
    [("0", Status.NOT_AVAILABLE), ("9", Status.ERROR), ("10", Status.RECOUNT_PENDING)],
)
def test_parse_place_statuses_without_a_result_drop_figures_even_with_a_stemmer(
    code: str, status: Status
) -> None:
    place = parse_place(feed_xml(status=code, status_text="Fejl"), REF)

    assert place.status is status
    assert place.status_text == "Fejl"
    assert place.parties == ()
    assert place.eligible_voters is None
    assert place.turnout_percent is None
    assert place.valid_votes is None
    assert not place.has_result


def test_parse_place_status_nine_is_an_error_state_not_a_crash() -> None:
    place = parse_place(feed_xml(status="9", stemmer=None, eligible=None), REF)

    assert place.status is Status.ERROR
    assert place.status_text == "Foreløbigt resultat"


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("1", Status.PRELIMINARY),
        ("11", Status.RECOUNT_PRELIMINARY),
        ("12", Status.RECOUNT_FINAL),
    ],
)
def test_parse_place_statuses_with_a_result_carry_figures(
    code: str, status: Status
) -> None:
    place = parse_place(feed_xml(status=code), REF)

    assert place.status is status
    assert place.has_result
    assert place.valid_votes == 1000
    assert len(place.parties) == 3


@pytest.mark.parametrize("code", ["1", "11", "12"])
def test_parse_place_a_result_status_without_stemmer_is_a_feed_error(code: str) -> None:
    with pytest.raises(FeedError, match="no Stemmer") as caught:
        parse_place(feed_xml(status=code, stemmer=None), REF)

    assert "valgdag_20.xml" in str(caught.value)


@pytest.mark.parametrize("code", ["2", "-1", "x", "", "1.0", "13", " "])
def test_parse_place_unknown_status_code_names_the_code_and_the_file(code: str) -> None:
    with pytest.raises(FeedError, match="unknown status code") as caught:
        parse_place(feed_xml(status=code), REF)

    assert repr(code) in str(caught.value)
    assert "valgdag_20.xml" in str(caught.value)


def test_parse_place_missing_status_code_attribute_is_a_feed_error() -> None:
    xml = feed_xml(status=None, status_text="Foreløbigt")

    with pytest.raises(FeedError, match="unknown status code"):
        parse_place(xml, REF)


def test_parse_place_missing_status_element_is_a_feed_error() -> None:
    xml = feed_xml(status=None, status_text="")

    with pytest.raises(FeedError, match="no Status element"):
        parse_place(xml, REF)


def test_parse_place_a_nested_status_element_is_not_found() -> None:
    xml = b"<Data><Wrap><Status Kode='1'>x</Status></Wrap></Data>"

    with pytest.raises(FeedError, match="no Status element"):
        parse_place(xml, REF)


def test_parse_place_feeding_it_an_overview_is_a_feed_error() -> None:
    xml = overview_xml([kreds_entry("20", "K")])

    with pytest.raises(FeedError):
        parse_place(xml, REF)


@pytest.mark.parametrize(
    "xml",
    [b"", b"   ", BOM, b"not xml", b"<Data><Status Kode='1'>", b"<Data>\xff</Data>"],
)
def test_parse_place_malformed_xml_raises_feed_error_naming_the_file(
    xml: bytes,
) -> None:
    with pytest.raises(FeedError, match="valgdag_20.xml"):
        parse_place(xml, REF)


@pytest.mark.parametrize(
    "bad",
    [
        "nan",
        "inf",
        "-inf",
        "Infinity",
        "1_000",
        "1,5",
        "21,9",
        "12abc",
        " ",
        "",
        "1e3",
        "٣",
    ],
)
def test_parse_place_a_party_percent_that_is_not_a_plain_number_is_a_feed_error(
    bad: str,
) -> None:
    stemmer = PARTIES_XML.replace('StemmerPct="60.0"', f'StemmerPct="{bad}"')

    with pytest.raises(FeedError, match="StemmerPct") as caught:
        parse_place(feed_xml(stemmer=stemmer), REF)

    assert "valgdag_20.xml" in str(caught.value)


@pytest.mark.parametrize(
    "bad", ["nan", "inf", "1_000", "1.5", "1,000", "12abc", " ", "", "0x10", "٣", "1e3"]
)
def test_parse_place_a_party_vote_count_that_is_not_an_integer_is_a_feed_error(
    bad: str,
) -> None:
    stemmer = PARTIES_XML.replace('StemmerAntal="600"', f'StemmerAntal="{bad}"')

    with pytest.raises(FeedError, match="StemmerAntal"):
        parse_place(feed_xml(stemmer=stemmer), REF)


@pytest.mark.parametrize("bad", ["1.309.177", "abc", "inf", "1_0", "12.5"])
def test_parse_place_bad_eligible_voters_names_the_value(bad: str) -> None:
    with pytest.raises(FeedError, match="Stemmeberettigede") as caught:
        parse_place(feed_xml(eligible=bad), REF)

    assert bad in str(caught.value)


@pytest.mark.parametrize("bad", ["nan", "inf", "83,9", "abc"])
def test_parse_place_bad_turnout_names_the_value(bad: str) -> None:
    with pytest.raises(FeedError, match="DeltagelsePct"):
        parse_place(feed_xml(turnout=bad), REF)


@pytest.mark.parametrize(
    "tag", ["IAltGyldigeStemmer", "BlankeStemmer", "IAltAfgivneStemmer"]
)
def test_parse_place_a_bad_total_names_the_element(tag: str) -> None:
    stemmer = PARTIES_XML.replace(f"<{tag}>", f"<{tag}>x")

    with pytest.raises(FeedError, match=tag):
        parse_place(feed_xml(stemmer=stemmer), REF)


def test_parse_place_party_without_a_vote_count_is_a_feed_error() -> None:
    stemmer = '<Parti Id="1" Navn="X" StemmerPct="1.0" />'

    with pytest.raises(FeedError, match="StemmerAntal"):
        parse_place(feed_xml(stemmer=stemmer), REF)


def test_parse_place_party_without_a_percent_is_a_feed_error() -> None:
    stemmer = '<Parti Id="1" Navn="X" StemmerAntal="5" />'

    with pytest.raises(FeedError, match="StemmerPct"):
        parse_place(feed_xml(stemmer=stemmer), REF)


def test_parse_place_party_without_an_id_attribute_is_a_feed_error() -> None:
    stemmer = '<Parti Navn="Anonymous" StemmerAntal="5" StemmerPct="1.0" />'

    with pytest.raises(FeedError, match="no Id") as caught:
        parse_place(feed_xml(stemmer=stemmer), REF)

    assert "Anonymous" in str(caught.value)
    assert "valgdag_20.xml" in str(caught.value)


def test_parse_place_empty_id_is_kept_as_a_non_party_in_its_original_position() -> None:
    stemmer = (
        '<Parti Id="" Navn="Uden for partier" StemmerAntal="3" StemmerPct="0.3" />'
        '<Parti Id="5891" Bogstav="A" Navn="A" StemmerAntal="5" StemmerPct="0.5" />'
    )

    place = parse_place(feed_xml(stemmer=stemmer), REF)

    assert [p.party_id for p in place.parties] == ["", "5891"]
    assert [p.is_party for p in place.parties] == [False, True]


def test_parse_place_party_without_a_letter_has_an_empty_letter() -> None:
    stemmer = '<Parti Id="1" Navn="X" StemmerAntal="5" StemmerPct="0.5" />'

    assert parse_place(feed_xml(stemmer=stemmer), REF).parties[0].letter == ""


def test_parse_place_seat_attributes_absent_are_none_and_zero_is_kept() -> None:
    stemmer = (
        '<Parti Id="1" Navn="X" StemmerAntal="5" StemmerPct="0.5" />'
        '<Parti Id="2" Navn="Y" Mandater="0" Kredsmandater="0" '
        'Tillaegsmandater="0" StemmerAntal="5" StemmerPct="0.5" />'
        '<Parti Id="3" Navn="Z" Mandater="4" StemmerAntal="5" StemmerPct="0.5" />'
    )

    absent, zeros, partial = parse_place(feed_xml(stemmer=stemmer), REF).parties

    assert (absent.seats, absent.constituency_seats, absent.supplementary_seats) == (
        None,
    ) * 3
    assert (zeros.seats, zeros.constituency_seats, zeros.supplementary_seats) == (
        0,
        0,
        0,
    )
    assert (partial.seats, partial.constituency_seats) == (4, None)


def test_parse_place_a_bad_seat_attribute_is_a_feed_error() -> None:
    stemmer = '<Parti Id="1" Navn="X" Mandater="" StemmerAntal="5" StemmerPct="0.5" />'

    with pytest.raises(FeedError, match="Mandater"):
        parse_place(feed_xml(stemmer=stemmer), REF)


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"eligible": None}, "eligible_voters"),
        ({"turnout": None}, "turnout_percent"),
    ],
)
def test_parse_place_missing_optional_header_elements_become_none(
    kwargs: dict[str, None], field: str
) -> None:
    place = parse_place(feed_xml(**kwargs), REF)  # type: ignore[arg-type]  # kwargs are None

    assert getattr(place, field) is None
    assert place.valid_votes == 1000


@pytest.mark.parametrize(
    ("tag", "field"),
    [
        ("IAltGyldigeStemmer", "valid_votes"),
        ("BlankeStemmer", "blank_votes"),
        ("AndreUgyldigeStemmer", "other_invalid_votes"),
        ("IAltUgyldigeStemmer", "total_invalid_votes"),
        ("IAltAfgivneStemmer", "total_votes"),
    ],
)
def test_parse_place_each_missing_total_becomes_none_and_the_rest_parse(
    tag: str, field: str
) -> None:
    stemmer = "\n".join(
        line for line in PARTIES_XML.splitlines() if not line.startswith(f"<{tag}>")
    )

    place = parse_place(feed_xml(stemmer=stemmer), REF)

    assert getattr(place, field) is None
    assert len(place.parties) == 3


def test_parse_place_keeps_unicode_names_and_strips_status_text() -> None:
    stemmer = '<Parti Id="1" Bogstav="Æ" Navn="Æ Ø Å Dansk Folkeparti" StemmerAntal="5" StemmerPct="0.5" />'
    xml = feed_xml(stemmer=stemmer, status_text="\n  Foreløbigt resultat  \n")

    place = parse_place(xml, make_ref(name="1. Østerbro"))

    assert place.name == "1. Østerbro"
    assert place.parties[0].name == "Æ Ø Å Dansk Folkeparti"
    assert place.parties[0].letter == "Æ"
    assert place.status_text == "Foreløbigt resultat"


def test_parse_place_negative_counts_are_accepted_as_served() -> None:
    """Documented: the adapter does not validate ranges, only that text is a number."""
    stemmer = '<Parti Id="1" Navn="X" StemmerAntal="-5" StemmerPct="-0.5" />'

    party = parse_place(feed_xml(stemmer=stemmer), REF).parties[0]

    assert (party.votes, party.percent) == (-5, -0.5)


def test_parse_place_plain_decimals_and_integers_are_accepted() -> None:
    stemmer = (
        '<Parti Id="1" Navn="X" StemmerAntal="+5" StemmerPct=".5" />'
        '<Parti Id="2" Navn="Y" StemmerAntal="007" StemmerPct="10" />'
        '<Parti Id="3" Navn="Z" StemmerAntal="1" StemmerPct="10." />'
    )

    x, y, z = parse_place(feed_xml(stemmer=stemmer), REF).parties

    assert (x.votes, x.percent) == (5, 0.5)
    assert (y.votes, y.percent) == (7, 10.0)
    assert z.percent == 10.0


# --- parse_place: timestamps ---------------------------------------------------


def test_parse_place_uses_the_iso_timestamp_when_present() -> None:
    xml = feed_xml(senest="24-03-2026 10:00:00", iso="2026-03-24T22:00:00")

    assert parse_place(xml, REF).last_changed == dt("2026-03-24T22:00:00")


def test_parse_place_falls_back_to_senestrettet_without_the_iso_element() -> None:
    xml = feed_xml(senest="24-03-2026 23:59:12", iso=None)

    assert parse_place(xml, REF).last_changed == dt("2026-03-24T23:59:12")


def test_parse_place_an_empty_iso_element_falls_back_to_senestrettet() -> None:
    xml = feed_xml(senest="24-03-2026 22:00:00", iso="")

    assert parse_place(xml, REF).last_changed == dt("2026-03-24T22:00:00")


def test_parse_place_a_feed_without_any_timestamp_takes_the_refs() -> None:
    xml = feed_xml(senest=None, iso=None)

    assert parse_place(xml, REF).last_changed == REF.last_changed


@pytest.mark.parametrize(
    "senest",
    ["01-01-0001 00:00:00", "0001-01-01T00:00:00", "0001-01-01 00:00:00", ""],
)
def test_parse_place_a_never_timestamp_falls_back_to_the_refs(senest: str) -> None:
    xml = feed_xml(status="0", senest=senest, iso=None, stemmer=None)

    assert parse_place(xml, REF).last_changed == REF.last_changed


def test_parse_place_a_never_iso_timestamp_falls_back_to_the_refs() -> None:
    xml = feed_xml(senest="24-03-2026 22:00:00", iso="0001-01-01T00:00:00")

    assert parse_place(xml, REF).last_changed == REF.last_changed


def test_parse_place_never_timestamp_without_a_ref_time_is_none() -> None:
    xml = feed_xml(status="0", senest="01-01-0001 00:00:00", iso=None, stemmer=None)

    assert parse_place(xml, make_ref(last_changed=None)).last_changed is None


def test_parse_place_a_timestamp_with_a_utc_offset_is_a_feed_error() -> None:
    xml = feed_xml(iso="2026-03-24T22:00:00+01:00")

    with pytest.raises(FeedError, match="UTC offset"):
        parse_place(xml, REF)


def test_parse_place_an_unreadable_timestamp_is_a_feed_error() -> None:
    with pytest.raises(FeedError, match="bad timestamp"):
        parse_place(feed_xml(senest="soon", iso=None), REF)


def test_parse_place_is_idempotent_and_leaves_the_ref_untouched() -> None:
    ref = make_ref(last_changed=dt("2026-03-24T21:00:00"))
    before = dataclasses.replace(ref)
    xml = feed_xml()

    assert parse_place(xml, ref) == parse_place(xml, ref)
    assert ref == before


def test_parse_place_non_bytes_input_is_a_type_error_not_a_feed_error() -> None:
    """Documented limitation: the signature says bytes, so `None` is a caller bug."""
    with pytest.raises(TypeError):
        parse_place(None, REF)  # type: ignore[arg-type]  # pinning the wrong-type behaviour


# --- DOCTYPE and entity hardening (A8, T10) -------------------------------------------

XML_DECL = '<?xml version="1.0" encoding="utf-8"?>'
ENTITY_DOC = XML_DECL + '<!DOCTYPE d [<!ENTITY a "b">]><Data>&a;</Data>'
HOSTILE_DOCUMENTS = {
    "internal-entity": ENTITY_DOC,
    "system-doctype-no-subset": XML_DECL + '<!DOCTYPE x SYSTEM "a.dtd"><Data/>',
    "bare-doctype": XML_DECL + "<!DOCTYPE x><Data/>",
    "parameter-entity": XML_DECL + '<!DOCTYPE x [<!ENTITY % p "x">]><Data/>',
    "external-entity": XML_DECL
    + '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Data>&e;</Data>',
    "doctype-truncated-mid-declaration": '<!DOCTYPE x [<!ENTITY a "b',
    "doctype-without-xml-declaration": "<!DOCTYPE x><Data/>",
}
BILLION_LAUGHS = (
    XML_DECL
    + '<!DOCTYPE lolz [<!ENTITY lol "lol">'
    + "".join(
        f'<!ENTITY lol{n} "{f"&lol{n - 1};" * 10 if n > 2 else "&lol;" * 10}">'
        for n in range(2, 10)
    )
    + "]><Data>&lol9;</Data>"
)
ENCODINGS = ["utf-8", "utf-8-sig", "utf-16", "utf-16-le+bom", "utf-16-be+bom"]


def _encode(text: str, encoding: str) -> bytes:
    if encoding.startswith("utf-16"):
        text = text.replace('encoding="utf-8"', 'encoding="utf-16"')
    if encoding == "utf-16-le+bom":
        return b"\xff\xfe" + text.encode("utf-16-le")
    if encoding == "utf-16-be+bom":
        return b"\xfe\xff" + text.encode("utf-16-be")
    return text.encode(encoding)


def _both(xml: bytes, ref: FeedRef = REF) -> None:
    """Parse as an overview and as a result feed; the callers expect FeedError."""
    parse_overview(xml)
    parse_place(xml, ref)


@pytest.mark.parametrize("encoding", ENCODINGS)
@pytest.mark.parametrize("name", sorted(HOSTILE_DOCUMENTS))
def test_parse_overview_refuses_a_doctype_or_entity_in_every_encoding(
    name: str, encoding: str
) -> None:
    xml = _encode(HOSTILE_DOCUMENTS[name], encoding)

    with pytest.raises(FeedError, match=r"valgdag\.xml: contains a DOCTYPE or entity"):
        parse_overview(xml)


@pytest.mark.parametrize("encoding", ENCODINGS)
@pytest.mark.parametrize("name", sorted(HOSTILE_DOCUMENTS))
def test_parse_place_refuses_a_doctype_or_entity_in_every_encoding_naming_the_feed(
    name: str, encoding: str
) -> None:
    xml = _encode(HOSTILE_DOCUMENTS[name], encoding)

    with pytest.raises(
        FeedError, match=r"valgdag_20\.xml: contains a DOCTYPE or entity"
    ):
        parse_place(xml, REF)


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_a_billion_laughs_payload_is_refused_quickly_in_both_parsers(
    encoding: str,
) -> None:
    xml = _encode(BILLION_LAUGHS, encoding)
    started = time.monotonic()

    with pytest.raises(FeedError, match="DOCTYPE or entity"):
        parse_overview(xml)
    with pytest.raises(FeedError, match="DOCTYPE or entity"):
        parse_place(xml, REF)

    assert time.monotonic() - started < 2.0


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le+bom", "utf-16-be+bom"])
def test_a_utf_16_doctype_under_a_utf_8_declaration_is_still_a_feed_error(
    encoding: str,
) -> None:
    xml = ENTITY_DOC.encode("utf-16")
    if encoding != "utf-16":
        xml = (
            (b"\xff\xfe" + ENTITY_DOC.encode("utf-16-le"))
            if "le" in encoding
            else (b"\xfe\xff" + ENTITY_DOC.encode("utf-16-be"))
        )

    with pytest.raises(FeedError):
        parse_overview(xml)
    with pytest.raises(FeedError):
        parse_place(xml, REF)


def test_a_doctype_after_the_root_element_is_refused_either_way() -> None:
    xml = b"<Data/><!DOCTYPE x>"

    with pytest.raises(FeedError):
        parse_overview(xml)
    with pytest.raises(FeedError):
        parse_place(xml, REF)


def test_a_doctype_in_a_valid_overview_is_refused_not_just_in_a_stub() -> None:
    xml = overview_xml([kreds_entry("20", "K")], bom=False).replace(
        b"<Data>", b'<!DOCTYPE Data [<!ENTITY a "b">]><Data>', 1
    )

    with pytest.raises(FeedError, match="DOCTYPE"):
        parse_overview(xml)


def test_a_doctype_in_a_valid_feed_is_refused_not_just_in_a_stub() -> None:
    xml = feed_xml(bom=False).replace(b"<Data>", b"<!DOCTYPE Data><Data>", 1)

    with pytest.raises(FeedError, match="DOCTYPE"):
        parse_place(xml, REF)


_COMMENT = b'<!-- <!DOCTYPE x [<!ENTITY a "b">]> -->'
_CDATA = b'<Note><![CDATA[<!DOCTYPE x [<!ENTITY a "b">]>]]></Note>'
_TEXT = b"<Note>&lt;!DOCTYPE x&gt; &lt;!ENTITY a&gt;</Note>"
_PI = b"<?DOCTYPE x?>"
_ATTRIBUTE = b'<Note kind="DOCTYPE" what="ENTITY"/>'


@pytest.mark.parametrize(
    "insert",
    [_COMMENT, _CDATA, _TEXT, _PI, _ATTRIBUTE],
    ids=[
        "comment",
        "cdata",
        "escaped-text",
        "processing-instruction",
        "attribute-value",
    ],
)
def test_the_word_doctype_in_a_comment_cdata_text_pi_or_attribute_is_not_refused(
    insert: bytes,
) -> None:
    overview = overview_xml([kreds_entry("20", "K")], bom=False)
    feed = feed_xml(bom=False)

    parsed = parse_overview(overview.replace(b"<Data>", b"<Data>" + insert, 1))
    place = parse_place(feed.replace(b"<Data>", b"<Data>" + insert, 1), REF)

    assert [f.place_id for f in parsed.feeds] == ["20"]
    assert place.status is Status.PRELIMINARY


def test_a_utf_16_document_without_a_doctype_still_parses() -> None:
    text = overview_xml([kreds_entry("20", "K")], bom=False).decode("utf-8")
    text = text.replace('encoding="utf-8"', 'encoding="utf-16"')

    parsed = parse_overview(text.encode("utf-16"))

    assert [f.place_id for f in parsed.feeds] == ["20"]


def test_a_utf_8_document_with_a_byte_order_mark_still_parses() -> None:
    parsed = parse_overview(overview_xml([kreds_entry("20", "K")], bom=True))

    assert [f.place_id for f in parsed.feeds] == ["20"]


def test_every_fixture_feed_still_parses_after_the_hardening(fixture_dir: Path) -> None:
    overview = parse_overview((fixture_dir / "valgdag.xml").read_bytes())

    for ref in overview.feeds:
        parse_place((fixture_dir / ref.file_name).read_bytes(), ref)

    assert len(overview.feeds) == 107


@pytest.mark.parametrize(
    "xml",
    [b"", b"\x00\x00\x00\x00", XML_DECL.encode(), b"hello", b"<Data><unclosed"],
    ids=["empty", "nul-bytes", "declaration-only", "plain-text", "unclosed"],
)
def test_malformed_input_is_reported_as_malformed_not_as_a_doctype_or_a_crash(
    xml: bytes,
) -> None:
    with pytest.raises(FeedError, match="malformed XML") as overview_error:
        parse_overview(xml)
    with pytest.raises(FeedError, match="malformed XML") as place_error:
        parse_place(xml, REF)

    assert "DOCTYPE" not in str(overview_error.value)
    assert "DOCTYPE" not in str(place_error.value)


def test_the_refusal_keeps_its_cause_for_debugging() -> None:
    with pytest.raises(FeedError) as caught:
        parse_overview(ENTITY_DOC.encode())

    assert caught.value.__cause__ is not None


def test_refusing_a_document_does_not_depend_on_what_the_ref_says() -> None:
    other = make_ref("99", file_name="valgdag_99.xml")

    with pytest.raises(FeedError, match=r"valgdag_99\.xml"):
        parse_place(ENTITY_DOC.encode(), other)


@pytest.mark.parametrize(
    "heading",
    [
        "Harden XML parsing before live polling",
        "Faithful replay needs recorded live captures",
    ],
)
def test_development_notes_no_longer_list_the_entries_this_round_resolved(
    heading: str,
) -> None:
    notes = (ROOT / "DEVELOPMENT.md").read_text(encoding="utf-8")

    assert heading not in notes
