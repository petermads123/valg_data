import dataclasses
from datetime import date

import pytest
from conftest import dt, make_election, make_party, make_place

from dkvalg import (
    CountingProgress,
    Election,
    ElectionType,
    PartyResult,
    Place,
    PlaceType,
    Status,
)

KREDS = PlaceType.OPSTILLINGSKREDS


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (Status.NOT_AVAILABLE, False),
        (Status.PRELIMINARY, True),
        (Status.ERROR, False),
        (Status.RECOUNT_PENDING, False),
        (Status.RECOUNT_PRELIMINARY, True),
        (Status.RECOUNT_FINAL, True),
    ],
)
def test_status_has_result_is_true_only_for_codes_1_11_and_12(
    status: Status, expected: bool
) -> None:
    assert status.has_result is expected


@pytest.mark.parametrize("code", [0, 1, 9, 10, 11, 12])
def test_status_codes_match_dst(code: int) -> None:
    assert Status(code).value == code


@pytest.mark.parametrize("code", [-1, 2, 3, 13, 99])
def test_status_rejects_codes_dst_does_not_define(code: int) -> None:
    with pytest.raises(ValueError):
        Status(code)


@pytest.mark.parametrize(
    ("party_id", "expected"),
    [("", False), ("0", True), ("5891", True), (" ", True)],
)
def test_party_result_is_party_is_false_only_for_the_empty_id(
    party_id: str, expected: bool
) -> None:
    party = PartyResult(party_id, "", "x", 1, 0.1)

    assert party.is_party is expected


def test_party_result_seat_fields_default_to_none() -> None:
    party = PartyResult("5891", "A", "A. Socialdemokratiet", 10, 1.5)

    assert (party.seats, party.constituency_seats, party.supplementary_seats) == (
        None,
        None,
        None,
    )


def test_place_has_result_follows_status() -> None:
    assert make_place(status=Status.PRELIMINARY).has_result
    assert not make_place(status=Status.NOT_AVAILABLE).has_result
    assert not make_place(status=Status.RECOUNT_PENDING).has_result


def test_place_unreported_keeps_identity_and_drops_everything_else() -> None:
    place = make_place("20", name="1.Østerbro", last_changed=dt("2026-03-24T22:00:00"))

    blank = place.unreported()

    assert (blank.place_type, blank.place_id, blank.name, blank.parent_id) == (
        place.place_type,
        place.place_id,
        place.name,
        place.parent_id,
    )
    assert blank.status is Status.NOT_AVAILABLE
    assert blank.status_text == ""
    assert blank.last_changed is None
    assert blank.parties == ()
    assert blank.eligible_voters is None
    assert blank.valid_votes is None
    assert blank.total_votes is None


def test_place_unreported_is_idempotent_and_leaves_the_original_untouched() -> None:
    place = make_place(last_changed=dt("2026-03-24T22:00:00"))
    snapshot = dataclasses.replace(place)

    once = place.unreported()

    assert once.unreported() == once
    assert place == snapshot
    assert place.has_result


def test_place_is_immutable_and_slotted() -> None:
    place = make_place()

    with pytest.raises(dataclasses.FrozenInstanceError):
        place.name = "x"  # type: ignore[misc]  # frozen on purpose: that is the test
    with pytest.raises((AttributeError, TypeError)):
        place.extra = 1  # type: ignore[attr-defined]  # slots forbid new attributes


def test_model_objects_are_hashable() -> None:
    election = make_election(make_place("1"), make_place("2"))

    assert isinstance(hash(election), int)
    assert hash(election) == hash(make_election(make_place("1"), make_place("2")))


def test_election_get_returns_the_matching_place() -> None:
    first, second = make_place("20"), make_place("21")
    election = make_election(first, second)

    assert election.get(KREDS, "21") is second


def test_election_get_names_both_type_and_id_when_missing() -> None:
    election = make_election(make_place("20"))

    with pytest.raises(KeyError, match="landsdel.*999"):
        election.get(PlaceType.LANDSDEL, "999")


def test_election_get_does_not_match_the_same_id_under_another_type() -> None:
    election = make_election(make_place("20"))

    with pytest.raises(KeyError):
        election.get(PlaceType.STORKREDS, "20")


def test_election_get_does_not_coerce_an_integer_id() -> None:
    election = make_election(make_place("20"))

    with pytest.raises(KeyError):
        election.get(KREDS, 20)  # type: ignore[arg-type]  # ids are strings


def test_election_get_returns_the_first_of_two_places_with_the_same_key() -> None:
    first = make_place("20", name="first")
    election = make_election(first, make_place("20", name="second"))

    assert election.get(KREDS, "20") is first


def test_election_of_type_keeps_overview_order_and_may_be_empty() -> None:
    a, b = make_place("1"), make_place("2")
    country = make_place("0", place_type=PlaceType.COUNTRY)
    election = make_election(a, country, b)

    assert election.of_type(KREDS) == (a, b)
    assert election.of_type(PlaceType.COUNTRY) == (country,)
    assert election.of_type(PlaceType.LANDSDEL) == ()
    assert isinstance(election.of_type(KREDS), tuple)


@pytest.mark.parametrize(
    ("statuses", "counted"),
    [
        ([], 0),
        ([Status.NOT_AVAILABLE] * 3, 0),
        ([Status.PRELIMINARY], 1),
        ([Status.PRELIMINARY, Status.NOT_AVAILABLE], 1),
        ([Status.ERROR, Status.RECOUNT_PENDING, Status.NOT_AVAILABLE], 0),
        ([Status.RECOUNT_PRELIMINARY, Status.RECOUNT_FINAL, Status.PRELIMINARY], 3),
    ],
)
def test_counting_progress_counts_only_kredse_with_a_result(
    statuses: list[Status], counted: int
) -> None:
    places = [make_place(str(i), status=s) for i, s in enumerate(statuses)]

    progress = make_election(*places).counting_progress()

    assert progress == CountingProgress(counted, len(statuses))


def test_counting_progress_ignores_results_at_other_levels() -> None:
    election = make_election(
        make_place("0", place_type=PlaceType.COUNTRY),
        make_place("999", place_type=PlaceType.TALLY),
        make_place("7", place_type=PlaceType.LANDSDEL),
        make_place("10", place_type=PlaceType.STORKREDS),
        make_place("20", status=Status.NOT_AVAILABLE),
    )

    assert election.counting_progress() == CountingProgress(0, 1)


def test_counting_progress_of_an_election_without_places_is_zero_of_zero() -> None:
    assert make_election().counting_progress() == CountingProgress(0, 0)


@pytest.mark.parametrize(("counted", "total"), [(3, 92), (0, 0), (92, 92)])
def test_counting_progress_str_is_counted_slash_total(counted: int, total: int) -> None:
    assert str(CountingProgress(counted, total)) == f"{counted}/{total}"


def test_election_fields_are_kept_as_given() -> None:
    election = Election(
        "Folketingsvalg X",
        ElectionType.FOLKETINGSVALG,
        date.fromisoformat("2026-03-24"),
        (),
    )

    assert election.name == "Folketingsvalg X"
    assert election.election_type == "folketingsvalg"
    assert election.election_date == date.fromisoformat("2026-03-24")


def test_place_type_values_are_stable_strings() -> None:
    assert [p.value for p in PlaceType] == [
        "country",
        "tally",
        "landsdel",
        "storkreds",
        "opstillingskreds",
    ]


def test_places_compare_by_value() -> None:
    assert make_place("1") == make_place("1")
    assert make_place("1") != make_place("2")
    assert isinstance(make_place("1"), Place)


# --- Election.changed_since (A3, A6, T11) --------------------------------------

SEEN = dt("2026-03-24T22:00:00")
LATER = dt("2026-03-24T23:00:00")


def _reported(place_id: str, last_changed: object = SEEN, **kwargs: object) -> Place:
    return make_place(place_id, last_changed=last_changed, **kwargs)  # type: ignore[arg-type]  # test helper, kwargs forwarded


def test_changed_since_none_gives_every_place_with_a_last_changed() -> None:
    election = make_election(_reported("1"), _reported("2"))

    assert election.changed_since(None) == election.places


def test_changed_since_none_leaves_out_a_never_reported_placeholder() -> None:
    placeholder = make_place("3", status=Status.NOT_AVAILABLE)
    election = make_election(_reported("1"), placeholder, _reported("2"))

    assert election.changed_since(None) == (election.places[0], election.places[2])


def test_changed_since_an_equal_election_gives_nothing() -> None:
    election = make_election(_reported("1"), _reported("2"))
    same = make_election(_reported("1"), _reported("2"))

    assert election.changed_since(same) == ()


def test_changed_since_itself_gives_nothing() -> None:
    election = make_election(_reported("1"), _reported("2"))

    assert election.changed_since(election) == ()


def test_changed_since_names_a_place_whose_figures_changed() -> None:
    party = (PartyResult("5891", "A", "A. Socialdemokratiet", 700, 70.0),)
    before = make_election(_reported("1"), _reported("2"))
    after = make_election(_reported("1"), _reported("2", parties=party))

    assert after.changed_since(before) == (after.places[1],)


def test_changed_since_names_a_place_whose_timestamp_moved() -> None:
    before = make_election(_reported("1"), _reported("2"))
    after = make_election(_reported("1"), _reported("2", LATER))

    assert after.changed_since(before) == (after.places[1],)


def test_changed_since_names_a_place_that_was_not_in_the_earlier_election() -> None:
    before = make_election(_reported("1"))
    after = make_election(_reported("1"), _reported("2"))

    assert after.changed_since(before) == (after.places[1],)


def test_changed_since_names_a_place_that_was_never_reported_before() -> None:
    before = make_election(make_place("1", status=Status.NOT_AVAILABLE))
    after = make_election(_reported("1"))

    assert after.changed_since(before) == after.places


def test_changed_since_does_not_report_a_place_that_disappeared() -> None:
    before = make_election(_reported("1"), _reported("2"))
    after = make_election(_reported("1"))

    assert after.changed_since(before) == ()


def test_changed_since_does_not_report_a_place_that_went_back_to_never_reported() -> (
    None
):
    before = make_election(_reported("1"), _reported("2"))
    after = make_election(_reported("1"), make_place("2", status=Status.NOT_AVAILABLE))

    assert after.changed_since(before) == ()


def test_changed_since_follows_the_current_elections_order() -> None:
    before = make_election(_reported("1"), _reported("2"), _reported("3"))
    after = make_election(
        _reported("3", LATER), _reported("1", LATER), _reported("2", LATER)
    )

    assert [p.place_id for p in after.changed_since(before)] == ["3", "1", "2"]


def test_changed_since_the_same_id_with_another_type_counts_as_new() -> None:
    before = make_election(
        make_place("1", place_type=PlaceType.STORKREDS, last_changed=SEEN)
    )
    after = make_election(make_place("1", place_type=KREDS, last_changed=SEEN))

    assert after.changed_since(before) == after.places


def test_changed_since_against_an_empty_election_gives_every_reported_place() -> None:
    after = make_election(_reported("1"), _reported("2"))

    assert after.changed_since(make_election()) == after.places


def test_changed_since_on_an_empty_election_gives_nothing() -> None:
    assert make_election().changed_since(make_election(_reported("1"))) == ()
    assert make_election().changed_since(None) == ()


def test_changed_since_a_duplicate_in_the_earlier_election_counts_as_the_last_one() -> (
    None
):
    old = _reported("1", parties=(PartyResult("1", "A", "A", 1, 1.0),))
    new = _reported("1")
    before = make_election(old, new)
    after = make_election(new)

    assert after.changed_since(before) == ()


def test_changed_since_is_idempotent_and_changes_neither_election() -> None:
    before = make_election(_reported("1"), _reported("2"))
    after = make_election(_reported("1"), _reported("2", LATER))
    snapshot = (before.places, after.places)

    first = after.changed_since(before)
    second = after.changed_since(before)

    assert first == second
    assert (before.places, after.places) == snapshot


def test_changed_since_returns_a_tuple() -> None:
    election = make_election(_reported("1"))

    assert isinstance(election.changed_since(None), tuple)
    assert isinstance(election.changed_since(election), tuple)


# --- round 3: the EP member and Place.leader ---------------------------------------


def test_election_type_has_exactly_the_folketingsvalg_and_ep_members() -> None:
    assert {m.name: m.value for m in ElectionType} == {
        "FOLKETINGSVALG": "folketingsvalg",
        "EUROPAPARLAMENTSVALG": "europaparlamentsvalg",
        "FOLKEAFSTEMNING": "folkeafstemning",
    }
    assert ElectionType("europaparlamentsvalg") is ElectionType.EUROPAPARLAMENTSVALG
    assert ElectionType.EUROPAPARLAMENTSVALG == "europaparlamentsvalg"


def test_an_election_can_hold_the_ep_type() -> None:
    election = Election(
        "Europa-Parlamentsvalg",
        ElectionType.EUROPAPARLAMENTSVALG,
        date(2024, 6, 9),
        (),
    )

    assert election.election_type is ElectionType.EUROPAPARLAMENTSVALG
    assert election.counting_progress() == CountingProgress(0, 0)


def test_place_leader_is_the_party_with_the_most_votes() -> None:
    place = make_place(parties=(make_party("A", 100), make_party("F", 300)))

    assert place.leader == make_party("F", 300)


def test_place_leader_tie_goes_to_the_party_earlier_in_the_feed() -> None:
    place = make_place(parties=(make_party("F", 300), make_party("A", 300)))

    assert place.leader is not None
    assert place.leader.letter == "F"


def test_place_leader_never_counts_uden_for_partier() -> None:
    place = make_place(parties=(make_party("", 900), make_party("A", 100)))

    assert place.leader == make_party("A", 100)


@pytest.mark.parametrize(
    "parties",
    [
        (),
        (make_party("", 900),),
        (make_party("A", 0), make_party("F", 0)),
        (make_party("A", 0), make_party("", 50)),
    ],
    ids=["no parties", "only uden for partier", "all zero votes", "zero and non-party"],
)
def test_place_leader_is_none_when_nobody_has_votes_to_lead_with(
    parties: tuple[PartyResult, ...],
) -> None:
    assert make_place(parties=parties).leader is None


def test_place_leader_a_party_with_one_vote_leads_a_field_of_zeros() -> None:
    place = make_place(parties=(make_party("A", 0), make_party("F", 1)))

    assert place.leader is not None
    assert place.leader.letter == "F"


def test_place_leader_negative_votes_never_lead() -> None:
    place = make_place(parties=(make_party("A", -5), make_party("F", 2)))

    assert place.leader == make_party("F", 2)
    assert make_place(parties=(make_party("A", -5),)).leader is None


@pytest.mark.parametrize(
    "status", [Status.NOT_AVAILABLE, Status.ERROR, Status.RECOUNT_PENDING]
)
def test_place_leader_is_none_without_a_result_even_if_parties_are_present(
    status: Status,
) -> None:
    place = dataclasses.replace(
        make_place(), status=status, parties=(make_party("A", 9),)
    )

    assert place.leader is None


@pytest.mark.parametrize(
    "status",
    [Status.PRELIMINARY, Status.RECOUNT_PRELIMINARY, Status.RECOUNT_FINAL],
)
def test_place_leader_exists_for_every_status_with_a_result(status: Status) -> None:
    place = make_place(status=status, parties=(make_party("A", 9),))

    assert place.leader == make_party("A", 9)


def test_place_leader_is_stable_across_calls() -> None:
    place = make_place(parties=(make_party("A", 1), make_party("B", 2)))

    assert place.leader is place.leader
