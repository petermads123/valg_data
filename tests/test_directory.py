import hashlib
from pathlib import Path

import pytest
from conftest import (
    dt,
    feed_xml,
    kreds_entry,
    overview_xml,
    write_directory,
)

from dkvalg import (
    CountingProgress,
    Election,
    ElectionType,
    FeedError,
    PlaceType,
    Status,
    load_election,
)
from dkvalg.adapters.folketingsvalg import parse_overview, unreported_place


def _digests(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
    }


# --- the real fixtures (A3, T3) -------------------------------------------------


def test_load_election_reads_name_date_and_type(election: Election) -> None:
    assert election.name == "Folketingsvalg tirsdag 24. marts 2026"
    assert election.election_date.isoformat() == "2026-03-24"
    assert election.election_type is ElectionType.FOLKETINGSVALG


def test_load_election_gives_107_places_with_the_expected_type_counts(
    election: Election,
) -> None:
    assert len(election.places) == 107
    assert {t: len(election.of_type(t)) for t in PlaceType} == {
        PlaceType.COUNTRY: 1,
        PlaceType.TALLY: 1,
        PlaceType.LANDSDEL: 3,
        PlaceType.STORKREDS: 10,
        PlaceType.OPSTILLINGSKREDS: 92,
    }


def test_load_election_places_follow_the_overview_order(
    election: Election, fixture_dir: Path
) -> None:
    overview = parse_overview((fixture_dir / "valgdag.xml").read_bytes())

    assert [(p.place_type, p.place_id) for p in election.places] == [
        (f.place_type, f.place_id) for f in overview.feeds
    ]
    assert [p.place_type for p in election.places[:3]] == [PlaceType.LANDSDEL] * 3
    assert [p.place_type for p in election.places[-2:]] == [
        PlaceType.COUNTRY,
        PlaceType.TALLY,
    ]


def test_load_election_hovedstaden_matches_its_file(election: Election) -> None:
    place = election.get(PlaceType.LANDSDEL, "7")

    assert place.name == "Hovedstaden"
    assert place.status is Status.PRELIMINARY
    assert place.eligible_voters == 1309177
    assert place.turnout_percent == 84.31
    assert (place.valid_votes, place.blank_votes) == (1091388, 9870)
    assert (place.other_invalid_votes, place.total_invalid_votes) == (2478, 12348)
    assert place.total_votes == 1103736
    social = place.parties[0]
    assert (social.name, social.votes, social.percent) == (
        "A. Socialdemokratiet",
        201493,
        18.5,
    )
    assert (social.seats, social.constituency_seats, social.supplementary_seats) == (
        10,
        10,
        0,
    )


def test_load_election_national_seats_sum_to_175(election: Election) -> None:
    country = election.get(PlaceType.COUNTRY, "0")

    assert sum(p.seats or 0 for p in country.parties) == 175
    assert sum(p.constituency_seats or 0 for p in country.parties) == 135
    assert sum(p.supplementary_seats or 0 for p in country.parties) == 40
    assert country.parties[0].seats == 38


def test_load_election_landsdele_seats_also_sum_to_175(election: Election) -> None:
    total = sum(
        p.seats or 0
        for land in election.of_type(PlaceType.LANDSDEL)
        for p in land.parties
    )

    assert total == 175


def test_load_election_opstillingskreds_and_tally_have_no_seats(
    election: Election,
) -> None:
    seatless = (
        *election.of_type(PlaceType.OPSTILLINGSKREDS),
        *election.of_type(PlaceType.TALLY),
    )

    assert len(seatless) == 93
    assert all(p.seats is None for place in seatless for p in place.parties)
    assert all(
        p.constituency_seats is None for place in seatless for p in place.parties
    )


def test_load_election_uden_for_partier_is_a_non_party_entry_where_dst_gives_it(
    election: Election,
) -> None:
    carrying = 0
    for place in election.places:
        outside = [p for p in place.parties if not p.is_party]
        assert len(outside) <= 1, place.name
        for entry in outside:
            assert (entry.name, entry.party_id) == ("Uden for partier", "")
            carrying += 1
        assert all(p.name != "Uden for partier" for p in place.parties if p.is_party)
    assert carrying >= 1
    assert [p.is_party for p in election.get(PlaceType.LANDSDEL, "7").parties][
        -1
    ] is False


def test_load_election_national_uden_for_partier_votes_come_from_the_file(
    election: Election,
) -> None:
    country = election.get(PlaceType.COUNTRY, "0")

    assert country.parties[-1].votes == 2420
    assert country.parties[-1].seats == 0


def test_load_election_tally_text_reports_92_of_92(election: Election) -> None:
    tally = election.get(PlaceType.TALLY, "999")

    assert tally.name == "Alle indberettede opstillingskredse"
    assert "92 af 92" in tally.status_text


def test_load_election_counts_92_of_92_on_the_fixtures(election: Election) -> None:

    assert election.counting_progress() == CountingProgress(92, 92)


def test_load_election_keeps_danish_place_names(election: Election) -> None:

    assert election.get(PlaceType.OPSTILLINGSKREDS, "20").name == "1.Østerbro"
    assert election.get(PlaceType.LANDSDEL, "8").name == "Sjælland-Syddanmark"


def test_load_election_every_place_has_the_feed_timestamp(
    election: Election, fixture_dir: Path
) -> None:
    overview = parse_overview((fixture_dir / "valgdag.xml").read_bytes())

    assert [p.last_changed for p in election.places] == [
        f.last_changed for f in overview.feeds
    ]
    assert all(p.last_changed is not None for p in election.places)


def test_load_election_twice_gives_equal_elections_and_leaves_files_alone(
    fixture_copy: Path,
) -> None:
    before = _digests(fixture_copy)

    first = load_election(fixture_copy)
    second = load_election(fixture_copy)

    assert first == second
    assert _digests(fixture_copy) == before


def test_load_election_works_from_a_directory_with_spaces_and_unicode(
    fixture_copy: Path, tmp_path: Path
) -> None:
    moved = tmp_path / "valg æøå 2026"
    fixture_copy.rename(moved)

    assert len(load_election(moved).places) == 107


# --- synthetic directories (A7) --------------------------------------------------


def test_load_election_does_not_read_a_feed_the_overview_lists_as_never_reported(
    tmp_path: Path,
) -> None:
    overview = overview_xml(
        [kreds_entry("20", "K", senest=None, iso="0001-01-01T00:00:00")]
    )
    directory = write_directory(tmp_path, overview)

    election = load_election(directory)

    ref = parse_overview(overview).feeds[0]
    assert election.places == (unreported_place(ref),)
    assert election.counting_progress() == CountingProgress(0, 1)


@pytest.mark.parametrize(
    ("senest", "iso"),
    [
        ("01-01-0001 00:00:00", None),
        (None, None),
        ("", ""),
        ("01-01-0001 00:00:00", "0001-01-01T00:00:00"),
    ],
)
def test_load_election_every_spelling_of_never_reported_becomes_a_placeholder(
    tmp_path: Path, senest: str | None, iso: str | None
) -> None:
    overview = overview_xml([kreds_entry("20", "K", senest=senest, iso=iso)])
    directory = write_directory(tmp_path, overview)

    place = load_election(directory).places[0]

    assert place.status is Status.NOT_AVAILABLE
    assert place.last_changed is None
    assert place.parties == ()


def test_load_election_all_never_reported_overview_is_zero_of_n(tmp_path: Path) -> None:
    overview = overview_xml(
        [kreds_entry(str(i), f"K{i}", senest=None, iso=None) for i in range(1, 4)]
    )

    election = load_election(write_directory(tmp_path, overview))

    assert election.counting_progress() == CountingProgress(0, 3)


def test_load_election_missing_listed_feed_names_the_file(fixture_copy: Path) -> None:
    (fixture_copy / "valgdag_20.xml").unlink()

    with pytest.raises(FeedError, match="valgdag_20.xml"):
        load_election(fixture_copy)


def test_load_election_a_missing_feed_in_a_synthetic_directory_names_the_file(
    tmp_path: Path,
) -> None:
    directory = write_directory(tmp_path, overview_xml([kreds_entry("20", "K")]))

    with pytest.raises(FeedError, match="not found") as caught:
        load_election(directory)

    assert "valgdag_20.xml" in str(caught.value)


def test_load_election_empty_directory_names_the_overview(tmp_path: Path) -> None:
    with pytest.raises(FeedError, match="valgdag.xml"):
        load_election(tmp_path)


def test_load_election_nonexistent_directory_names_the_overview(tmp_path: Path) -> None:
    with pytest.raises(FeedError, match="valgdag.xml"):
        load_election(tmp_path / "nowhere")


def test_load_election_a_directory_that_is_a_regular_file_is_a_feed_error(
    tmp_path: Path,
) -> None:
    not_a_directory = tmp_path / "plain.txt"
    not_a_directory.write_text("x")

    with pytest.raises(FeedError):
        load_election(not_a_directory)


def test_load_election_an_overview_that_is_a_directory_is_a_feed_error(
    tmp_path: Path,
) -> None:
    (tmp_path / "valgdag.xml").mkdir()

    with pytest.raises(FeedError, match="valgdag.xml"):
        load_election(tmp_path)


def test_load_election_an_empty_feed_file_is_a_feed_error_naming_it(
    tmp_path: Path,
) -> None:
    directory = write_directory(
        tmp_path, overview_xml([kreds_entry("20", "K")]), {"valgdag_20.xml": b""}
    )

    with pytest.raises(FeedError, match="valgdag_20.xml"):
        load_election(directory)


def test_load_election_a_truncated_feed_is_a_feed_error_not_a_parse_error(
    fixture_copy: Path,
) -> None:
    path = fixture_copy / "valgdag_20.xml"
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])

    with pytest.raises(FeedError, match="valgdag_20.xml"):
        load_election(fixture_copy)


def test_load_election_a_malformed_overview_is_a_feed_error(fixture_copy: Path) -> None:
    (fixture_copy / "valgdag.xml").write_bytes(b"<Data><broken")

    with pytest.raises(FeedError, match="valgdag.xml"):
        load_election(fixture_copy)


def test_load_election_an_ep_overview_is_refused(fixture_copy: Path) -> None:
    path = fixture_copy / "valgdag.xml"
    path.write_bytes(
        path.read_bytes().replace(
            b"Folketingsvalg tirsdag 24. marts 2026", b"Europa-Parlamentsvalg 2024"
        )
    )

    with pytest.raises(FeedError, match="Europa-Parlamentsvalg"):
        load_election(fixture_copy)


def test_load_election_an_overview_listing_no_feeds_is_refused(tmp_path: Path) -> None:
    directory = write_directory(tmp_path, overview_xml([]))

    with pytest.raises(FeedError, match="no result feeds"):
        load_election(directory)


def test_load_election_a_reported_feed_with_status_zero_is_kept_but_not_counted(
    tmp_path: Path,
) -> None:
    overview = overview_xml([kreds_entry("20", "K")])
    feed = feed_xml(status="0", status_text="Ikke klar", stemmer=None, eligible=None)
    directory = write_directory(tmp_path, overview, {"valgdag_20.xml": feed})

    election = load_election(directory)

    place = election.places[0]
    assert place.status is Status.NOT_AVAILABLE
    assert place.status_text == "Ikke klar"
    assert place.last_changed == dt("2026-03-24T22:00:00")
    assert election.counting_progress() == CountingProgress(0, 1)


def test_load_election_a_status_nine_feed_is_an_error_place_not_a_crash(
    tmp_path: Path,
) -> None:
    overview = overview_xml([kreds_entry("20", "K")])
    feed = feed_xml(status="9", status_text="Fejl i opgørelsen", stemmer=None)
    directory = write_directory(tmp_path, overview, {"valgdag_20.xml": feed})

    place = load_election(directory).places[0]

    assert place.status is Status.ERROR
    assert place.status_text == "Fejl i opgørelsen"
    assert not place.has_result


def test_load_election_the_feed_timestamp_beats_the_overview(tmp_path: Path) -> None:
    overview = overview_xml([kreds_entry("20", "K", iso="2026-03-24T21:00:00")])
    feed = feed_xml(iso="2026-03-24T23:00:00")
    directory = write_directory(tmp_path, overview, {"valgdag_20.xml": feed})

    assert load_election(directory).places[0].last_changed == dt("2026-03-24T23:00:00")


def test_load_election_a_feed_without_a_timestamp_takes_the_overviews(
    tmp_path: Path,
) -> None:
    overview = overview_xml([kreds_entry("20", "K", iso="2026-03-24T21:00:00")])
    feed = feed_xml(senest=None, iso=None)
    directory = write_directory(tmp_path, overview, {"valgdag_20.xml": feed})

    assert load_election(directory).places[0].last_changed == dt("2026-03-24T21:00:00")


def test_load_election_handles_a_bom_less_overview_and_feed(tmp_path: Path) -> None:
    overview = overview_xml([kreds_entry("20", "K")], bom=False)
    feed = feed_xml(bom=False)
    directory = write_directory(tmp_path, overview, {"valgdag_20.xml": feed})

    assert load_election(directory).counting_progress() == CountingProgress(1, 1)


def test_load_election_does_not_mutate_the_directory_it_reads(tmp_path: Path) -> None:
    overview = overview_xml([kreds_entry("20", "K")])
    directory = write_directory(tmp_path, overview, {"valgdag_20.xml": feed_xml()})
    before = _digests(directory)

    load_election(directory)

    assert _digests(directory) == before
