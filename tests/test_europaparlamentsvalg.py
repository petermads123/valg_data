"""Europa-Parlamentsvalg: the adapter, and EP across the stack (A1, A3, A4; T1, T3, T4)."""

import io
import re
from pathlib import Path

import pytest
from conftest import (
    BOM,
    EP_BASE_URL,
    EP_ELECTION_NAME,
    NATIONAL,
    FakeClock,
    FakeTransport,
    dt,
    entry,
    feed_xml,
    kreds_entry,
    make_ref,
    overview_xml,
    utc,
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
from dkvalg.adapters import europaparlamentsvalg, folketingsvalg
from dkvalg.adapters.dst_feed import parse_place
from dkvalg.adapters.europaparlamentsvalg import parse_overview, unreported_place
from dkvalg.cli import run
from dkvalg.sources.directory import build_election

LOCATION = "Valg2546524"
EP_NAME_XML = EP_ELECTION_NAME  # the real name, double space included


def _ep_overview(*entries: str, **kwargs: object) -> bytes:
    return overview_xml(
        list(entries) or [kreds_entry("20", "K")],
        name=kwargs.pop("name", EP_NAME_XML),  # type: ignore[arg-type]  # forwarded as-is
        election_date=kwargs.pop("election_date", "09-06-2024"),  # type: ignore[arg-type]  # forwarded as-is
        **kwargs,  # type: ignore[arg-type]  # forwarded as-is
    )


def _ep_feed(**kwargs: object) -> bytes:
    """A synthetic result feed under the EP election name."""
    body = feed_xml(**kwargs)  # type: ignore[arg-type]  # forwarded as-is
    return body.replace(b"Folketingsvalg tirsdag 24. marts 2026", EP_NAME_XML.encode())


# --- A1 / T1: the real fixtures through load_election ---------------------------------


def test_load_election_ep_is_an_ep_election_with_the_real_name(
    ep_election: Election,
) -> None:
    assert ep_election.election_type is ElectionType.EUROPAPARLAMENTSVALG
    assert ep_election.name == EP_ELECTION_NAME
    assert ep_election.election_date.isoformat() == "2024-06-09"


@pytest.mark.parametrize(
    ("place_type", "count"),
    [
        (PlaceType.COUNTRY, 1),
        (PlaceType.TALLY, 1),
        (PlaceType.LANDSDEL, 3),
        (PlaceType.STORKREDS, 10),
        (PlaceType.OPSTILLINGSKREDS, 92),
    ],
)
def test_load_election_ep_has_the_107_places_by_type(
    ep_election: Election, place_type: PlaceType, count: int
) -> None:
    assert len(ep_election.of_type(place_type)) == count
    assert len(ep_election.places) == 107


def test_load_election_ep_counts_92_of_92(ep_election: Election) -> None:
    progress = ep_election.counting_progress()

    assert (progress.counted, progress.total) == (92, 92)


def test_load_election_ep_has_no_seat_figures_anywhere(ep_election: Election) -> None:
    seats = {
        (p.seats, p.constituency_seats, p.supplementary_seats)
        for place in ep_election.places
        for p in place.parties
    }

    assert seats == {(None, None, None)}
    assert sum(len(place.parties) for place in ep_election.places) > 1000


def test_load_election_ep_national_figures_match_the_file(
    ep_election: Election,
) -> None:
    country = ep_election.get(PlaceType.COUNTRY, "0")
    sf = next(p for p in country.parties if p.letter == "F")

    assert country.name == "Hele landet"
    assert country.eligible_voters == 4_301_255
    assert country.turnout_percent == 58.23
    assert (sf.votes, sf.percent) == (426_367, 17.4)
    assert country.status is Status.PRELIMINARY


def test_load_election_ep_parent_ids_follow_the_hierarchy(
    ep_election: Election,
) -> None:
    assert ep_election.get(PlaceType.COUNTRY, "0").parent_id is None
    assert ep_election.get(PlaceType.TALLY, "999").parent_id is None
    assert {p.parent_id for p in ep_election.of_type(PlaceType.LANDSDEL)} == {"0"}
    assert ep_election.get(PlaceType.STORKREDS, "10").parent_id == "7"
    assert ep_election.get(PlaceType.OPSTILLINGSKREDS, "20").parent_id == "10"
    storkreds_ids = {p.place_id for p in ep_election.of_type(PlaceType.STORKREDS)}
    assert {p.parent_id for p in ep_election.of_type(PlaceType.OPSTILLINGSKREDS)} <= (
        storkreds_ids
    )


def test_load_election_ep_is_idempotent_and_pure(ep_fixture_dir: Path) -> None:
    assert load_election(ep_fixture_dir) == load_election(ep_fixture_dir)


def test_ep_national_leader_is_sf_and_names_are_unicode_intact(
    ep_election: Election,
) -> None:
    leader = ep_election.get(PlaceType.COUNTRY, "0").leader

    assert leader is not None
    assert leader.letter == "F"
    assert any(p.letter == "Æ" for p in ep_election.get(PlaceType.COUNTRY, "0").parties)


def test_build_election_reads_ep_with_a_reader_over_the_files(
    ep_fixture_dir: Path, ep_election: Election
) -> None:
    built = build_election(
        (ep_fixture_dir / "valgdag.xml").read_bytes(),
        lambda name: (ep_fixture_dir / name).read_bytes(),
    )

    assert built == ep_election


def test_load_election_ep_with_a_folketingsvalg_name_is_a_folketingsvalg(
    ep_fixture_copy: Path,
) -> None:
    overview = (ep_fixture_copy / "valgdag.xml").read_bytes()
    renamed = overview.replace(EP_NAME_XML.encode(), b"Folketingsvalg 2024")
    (ep_fixture_copy / "valgdag.xml").write_bytes(renamed)

    election = load_election(ep_fixture_copy)

    assert election.election_type is ElectionType.FOLKETINGSVALG


# --- A2 at the adapter level ---------------------------------------------------------


def test_ep_adapter_parses_the_real_overview_as_ep(ep_fixture_dir: Path) -> None:
    overview = parse_overview((ep_fixture_dir / "valgdag.xml").read_bytes())

    assert overview.election_type is ElectionType.EUROPAPARLAMENTSVALG
    assert overview.name == EP_ELECTION_NAME
    assert len(overview.feeds) == 107


def test_ep_adapter_refuses_a_folketingsvalg_overview(fixture_dir: Path) -> None:
    with pytest.raises(FeedError, match="not a Europa-Parlamentsvalg"):
        parse_overview((fixture_dir / "valgdag.xml").read_bytes())


def test_folketingsvalg_adapter_refuses_the_ep_overview(ep_fixture_dir: Path) -> None:
    with pytest.raises(FeedError, match="not a Folketingsvalg"):
        folketingsvalg.parse_overview((ep_fixture_dir / "valgdag.xml").read_bytes())


def test_ep_adapter_bare_prefix_is_accepted_as_round_one_does() -> None:
    xml = _ep_overview(name="Europa-Parlamentsvalg")

    assert parse_overview(xml).election_type is ElectionType.EUROPAPARLAMENTSVALG


def test_ep_adapter_reexports_the_shared_names() -> None:
    from dkvalg.adapters import dst_feed

    assert europaparlamentsvalg.parse_place is dst_feed.parse_place
    assert europaparlamentsvalg.FeedRef is dst_feed.FeedRef
    assert europaparlamentsvalg.Overview is dst_feed.Overview
    assert europaparlamentsvalg.unreported_place is dst_feed.unreported_place
    assert sorted(europaparlamentsvalg.__all__) == sorted(
        [
            "FeedRef",
            "Overview",
            "main",
            "parse_overview",
            "parse_place",
            "unreported_place",
        ]
    )


# --- A4 / T4: EP quirks ----------------------------------------------------------------


def test_ep_overview_with_and_without_a_bom_parses_equal() -> None:
    with_bom = _ep_overview(bom=True)
    without = _ep_overview(bom=False)

    assert with_bom.startswith(BOM)
    assert not without.startswith(BOM)
    assert parse_overview(with_bom) == parse_overview(without)


def test_ep_overview_keeps_the_double_space_in_the_name() -> None:
    overview = parse_overview(_ep_overview())

    assert "søndag  9." in overview.name


def test_ep_overview_name_with_surrounding_whitespace_is_stripped() -> None:
    overview = parse_overview(_ep_overview(name=f"  {EP_NAME_XML}\n"))

    assert overview.name == EP_NAME_XML


def test_ep_status_zero_feed_in_dsts_example_shape_is_figure_free() -> None:
    xml = _ep_feed(
        status="0",
        status_text="Ingen resultat",
        stemmer=None,
        eligible=None,
        turnout=None,
    )

    place = parse_place(xml, make_ref("20"))

    assert place.status is Status.NOT_AVAILABLE
    assert place.parties == ()
    assert place.eligible_voters is None
    assert place.leader is None


def test_ep_status_zero_feed_with_a_stemmer_element_still_drops_the_figures() -> None:
    place = parse_place(_ep_feed(status="0"), make_ref("20"))

    assert place.parties == ()
    assert place.total_votes is None


def test_ep_never_reported_feed_becomes_a_placeholder() -> None:
    overview_bytes = _ep_overview(
        kreds_entry("20", "K", senest="01-01-0001 00:00:00", iso="0001-01-01T00:00:00"),
    )
    overview = parse_overview(overview_bytes)

    election = build_election(overview_bytes, lambda _name: pytest.fail("read"))

    assert overview.feeds[0].last_changed is None
    (place,) = election.places
    assert place == unreported_place(overview.feeds[0])
    assert place.status is Status.NOT_AVAILABLE


@pytest.mark.parametrize("party_id", ["", None])
def test_ep_empty_or_absent_party_id_behaves_as_for_folketingsvalg(
    party_id: str | None,
) -> None:
    attr = "" if party_id is None else f'Id="{party_id}" '
    stemmer = (
        f'<Parti {attr}Navn="Uden for partier" StemmerAntal="10" StemmerPct="1.0" />'
    )
    xml = _ep_feed(stemmer=stemmer)

    if party_id is None:
        with pytest.raises(FeedError, match="has no Id"):
            parse_place(xml, make_ref("20"))
    else:
        (party,) = parse_place(xml, make_ref("20")).parties
        assert party.party_id == ""
        assert not party.is_party


DOCTYPE = b'<!DOCTYPE Data [<!ENTITY x "y">]>'


def _inject_doctype(body: bytes) -> bytes:
    marker = b"?>"
    start = body.index(marker) + len(marker)
    return body[:start] + b"\n" + DOCTYPE + body[start:]


def test_ep_overview_with_a_doctype_is_refused_naming_the_file() -> None:
    xml = _inject_doctype(_ep_overview(bom=False))

    with pytest.raises(FeedError, match=r"valgdag\.xml.*DOCTYPE"):
        parse_overview(xml)


def test_ep_result_feed_with_a_doctype_is_refused_naming_the_file() -> None:
    xml = _inject_doctype(_ep_feed(bom=False))

    with pytest.raises(FeedError, match=r"valgdag_20\.xml.*DOCTYPE"):
        parse_place(xml, make_ref("20"))


def test_ep_directory_with_a_doctype_result_feed_is_refused_by_load_election(
    ep_fixture_copy: Path,
) -> None:
    target = ep_fixture_copy / "valgdag_20.xml"
    target.write_bytes(_inject_doctype(target.read_bytes().removeprefix(BOM)))

    with pytest.raises(FeedError, match=r"valgdag_20\.xml"):
        load_election(ep_fixture_copy)


def test_ep_directory_missing_a_listed_feed_is_a_feed_error_naming_it(
    ep_fixture_copy: Path,
) -> None:
    (ep_fixture_copy / "valgdag_20.xml").unlink()

    with pytest.raises(FeedError, match=r"valgdag_20\.xml"):
        load_election(ep_fixture_copy)


def test_ep_synthetic_directory_loads_as_ep(tmp_path: Path) -> None:
    directory = write_directory(
        tmp_path / "ep",
        _ep_overview(),
        {"valgdag_20.xml": _ep_feed()},
    )

    election = load_election(directory)

    assert election.election_type is ElectionType.EUROPAPARLAMENTSVALG
    assert election.counting_progress().counted == 1


# --- A3 / T3: EP through HttpSource, Recorder, CaptureReplay, ReplaySource ------------


def test_http_source_first_fetch_of_ep_equals_load_election(
    ep_transport: FakeTransport, ep_election: Election
) -> None:
    source = HttpSource(LOCATION, transport=ep_transport, clock=FakeClock())

    result = source.fetch()

    assert result.election == ep_election
    assert result.election.election_type is ElectionType.EUROPAPARLAMENTSVALG
    assert len(result.changed) == 107
    assert source.election == ep_election


def test_http_source_second_fetch_of_ep_is_unchanged(
    ep_transport: FakeTransport,
) -> None:
    source = HttpSource(LOCATION, transport=ep_transport, clock=FakeClock())
    first = source.fetch()

    second = source.fetch()

    assert second.changed == ()
    assert second.election == first.election


def test_http_source_ep_requests_only_the_ep_election_folder(
    ep_transport: FakeTransport,
) -> None:
    HttpSource(LOCATION, transport=ep_transport, clock=FakeClock()).fetch()

    assert all(r.url.startswith(EP_BASE_URL) for r in ep_transport.requests)
    assert ep_transport.names[0] == "valgdag.xml"
    assert len(ep_transport.requests) == 108


def test_http_source_ep_refetches_only_the_touched_feed(
    ep_transport: FakeTransport,
) -> None:
    source = HttpSource(LOCATION, transport=ep_transport, clock=FakeClock())
    source.fetch()
    ep_transport.touch([NATIONAL])

    result = source.fetch()

    assert [p.place_id for p in result.changed] == ["0"]
    assert ep_transport.names[-2:] == ["valgdag.xml", NATIONAL]


def test_recorded_ep_poll_replays_through_capture_replay_ending_equal(
    ep_transport: FakeTransport, tmp_path: Path
) -> None:
    capture = tmp_path / "cap"
    source = HttpSource(
        LOCATION,
        transport=ep_transport,
        recorder=Recorder(capture),
        clock=FakeClock(),
    )
    cycles = list(poll(source, max_cycles=2, sleep=lambda _s: None))
    assert cycles[-1].election is not None
    ep_transport.touch([NATIONAL, "valgdag_20.xml"])
    cycles = list(poll(source, max_cycles=1, sleep=lambda _s: None))

    steps = list(CaptureReplay(capture, speed=float("inf")))

    assert len(steps) == 2
    assert steps[-1].election == source.election
    assert steps[-1].election.election_type is ElectionType.EUROPAPARLAMENTSVALG
    assert steps[0].election.counting_progress().counted == 92
    assert {p.place_id for p in steps[-1].changed} == {"0", "20"}


def test_replay_source_of_ep_ends_equal_to_the_loaded_election(
    ep_election: Election,
) -> None:
    source = ReplaySource(ep_election, speed=float("inf"))

    steps = list(source)

    assert source.initial().counting_progress().counted == 0
    assert source.initial().election_type is ElectionType.EUROPAPARLAMENTSVALG
    assert len(steps) == 107
    assert steps[-1].election == ep_election
    assert steps[-1].progress.counted == 92


# --- A3 / T3: the CLI on EP ----------------------------------------------------------

STEP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}  +(\d+)/(\d+)  (\S+) (.+)$")


def _cli(argv: list[str], **kwargs: object) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(argv, out=out, err=err, sleep=lambda _s: None, **kwargs)  # type: ignore[arg-type]  # forwarded as-is
    return code, out.getvalue(), err.getvalue()


def test_cli_replay_of_ep_prints_107_lines_ending_92_of_92(
    ep_fixture_dir: Path,
) -> None:
    code, out, err = _cli(["replay", str(ep_fixture_dir), "--speed", "inf"])

    lines = [line for line in out.splitlines() if STEP.match(line)]
    assert (code, err) == (0, "")
    assert len(lines) == 107
    assert "92/92" in lines[-1]


def test_cli_replay_of_ep_table_shows_dashes_for_every_seat(
    ep_fixture_dir: Path,
) -> None:
    _, out, _ = _cli(["replay", str(ep_fixture_dir), "--speed", "inf"])

    table = out.split("\n\n", 1)[1]
    rows = [line for line in table.splitlines()[1:] if line.strip()]
    assert len(rows) >= 11
    assert all(line.rstrip().endswith("-") for line in rows)
    assert "F  F. SF - Socialistisk Folkeparti" in table
    assert "17.4%" in table
    assert "426367" in table


def test_cli_poll_on_an_ep_fake_transport_prints_its_lines(
    ep_transport: FakeTransport,
) -> None:
    code, out, err = _cli(
        ["poll", LOCATION, "--cycles", "1"],
        transport=ep_transport,
        clock=FakeClock(),
    )

    lines = out.splitlines()
    assert (code, err) == (0, "")
    assert len(lines) == 107
    assert lines[0].startswith("2026-03-24 20:00:00+00:00")
    assert "country Hele landet" in out
    assert "92/92" in lines[0]


def test_poll_accepts_an_ep_cycle_stamp_as_aware_utc(
    ep_transport: FakeTransport,
) -> None:
    source = HttpSource(
        LOCATION, transport=ep_transport, clock=lambda: utc("2024-06-10T01:00:00")
    )

    assert source.fetch().fetched_at == utc("2024-06-10T01:00:00")


def test_a_synthetic_ep_place_last_changed_stays_naive_local_time() -> None:
    place = parse_place(_ep_feed(), make_ref("20"))

    assert place.last_changed == dt("2026-03-24T22:00:00")
    assert place.last_changed is not None
    assert place.last_changed.tzinfo is None


def test_ep_overview_entry_helper_builds_a_land_entry() -> None:
    xml = _ep_overview(entry("Land", "Hele landet", "valgdag_0.xml", land_id="0"))

    (feed,) = parse_overview(xml).feeds

    assert (feed.place_type, feed.place_id) == (PlaceType.COUNTRY, "0")
