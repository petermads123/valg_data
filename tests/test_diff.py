"""`dkvalg.diff`: `diff_elections` and the five change kinds (A5, A6, A7; T5, T6, T7)."""

import copy
import dataclasses
import math
import typing
from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import (
    dt,
    make_answer,
    make_election,
    make_ep_election,
    make_fa_election,
    make_party,
    make_place,
)

from dkvalg import (
    Change,
    CountingProgress,
    Election,
    LeaderChanged,
    PartyResult,
    PartyResultChanged,
    Place,
    PlaceCounted,
    PlaceType,
    ProgressChanged,
    ReplaySource,
    Status,
    StatusChanged,
    diff_elections,
)

COUNTRY = PlaceType.COUNTRY
STORKREDS = PlaceType.STORKREDS
KREDS = PlaceType.OPSTILLINGSKREDS
KINDS = (
    PlaceCounted,
    PartyResultChanged,
    LeaderChanged,
    StatusChanged,
    ProgressChanged,
)


def _country(
    *parties: PartyResult, status: Status = Status.PRELIMINARY, place_id: str = "0"
) -> Place:
    return make_place(
        place_id,
        place_type=COUNTRY,
        name="Hele landet",
        status=status,
        parties=parties,
    )


def _kreds(
    place_id: str,
    *parties: PartyResult,
    status: Status = Status.PRELIMINARY,
) -> Place:
    return make_place(
        place_id, place_type=KREDS, status=status, parties=parties or None
    )


def _kinds(changes: tuple[Change, ...]) -> list[str]:
    return [type(change).__name__ for change in changes]


def _swap_party(
    election: Election,
    place_type: PlaceType,
    place_id: str,
    letter: str,
    **fields: object,
) -> Election:
    """A copy of `election` with one party's fields replaced at one place."""
    places = []
    for place in election.places:
        if (place.place_type, place.place_id) == (place_type, place_id):
            parties = tuple(
                replace(party, **fields) if party.letter == letter else party  # type: ignore[arg-type]  # forwarded as-is
                for party in place.parties
            )
            place = replace(place, parties=parties)
        places.append(place)
    return replace(election, places=tuple(places))


def _only(changes: tuple[Change, ...], kind: type) -> list[typing.Any]:
    return [c for c in changes if isinstance(c, kind)]


# --- the Change alias and the dataclasses ---------------------------------------------


def test_change_alias_is_the_union_of_the_five_kinds() -> None:
    assert set(typing.get_args(Change.__value__)) == set(KINDS)
    assert len(typing.get_args(Change.__value__)) == 5


@pytest.mark.parametrize("kind", KINDS)
def test_every_change_kind_is_a_frozen_slotted_dataclass(kind: type) -> None:
    assert dataclasses.is_dataclass(kind)
    assert kind.__dataclass_params__.frozen  # type: ignore[attr-defined]  # dataclass internals
    assert "__slots__" in vars(kind)


def test_change_instances_are_immutable_equal_by_value_and_hashable() -> None:
    place = _country(make_party("A", 10))
    first = PlaceCounted(place)

    with pytest.raises(dataclasses.FrozenInstanceError):
        first.place = place  # type: ignore[misc]  # proving it is frozen
    assert first == PlaceCounted(place)
    assert hash(first) == hash(PlaceCounted(place))
    assert ProgressChanged(CountingProgress(0, 2), CountingProgress(1, 2)) == (
        ProgressChanged(CountingProgress(0, 2), CountingProgress(1, 2))
    )


@pytest.mark.parametrize(
    ("before", "after", "votes", "seats"),
    [
        (None, make_party("A", 10, seats=3), None, None),
        (make_party("A", 10), make_party("A", 15, seats=3), 5, None),
        (make_party("A", 10, seats=3), make_party("A", 15), 5, None),
        (make_party("A", 10, seats=3), make_party("A", 8, seats=4), -2, 1),
        (make_party("A", 10, seats=3), make_party("A", 10, seats=2), 0, -1),
        (make_party("A", 10, seats=0), make_party("A", 12, seats=0), 2, 0),
        (make_party("A", 10), make_party("A", 10, constituency_seats=1), 0, None),
    ],
)
def test_party_result_changed_deltas(
    before: PartyResult | None,
    after: PartyResult,
    votes: int | None,
    seats: int | None,
) -> None:
    change = PartyResultChanged(_country(after), before, after)

    assert change.votes_delta == votes
    assert change.seats_delta == seats


# --- equality, purity, idempotency ----------------------------------------------------


def test_equal_elections_give_an_empty_tuple(election: Election) -> None:
    assert diff_elections(election, election) == ()
    assert diff_elections(election, copy.deepcopy(election)) == ()


def test_a_last_changed_only_difference_is_not_a_change(election: Election) -> None:
    shifted = replace(
        election,
        places=tuple(
            replace(p, last_changed=dt("2030-01-01T00:00:00")) for p in election.places
        ),
    )

    assert diff_elections(election, shifted) == ()


def test_none_against_an_all_placeholder_election_is_empty(election: Election) -> None:
    blank = replace(election, places=tuple(p.unreported() for p in election.places))

    assert diff_elections(None, blank) == ()
    assert diff_elections(blank, blank) == ()


def test_none_previous_equals_diffing_against_an_all_unreported_copy(
    election: Election,
) -> None:
    blank = replace(election, places=tuple(p.unreported() for p in election.places))

    from_none = diff_elections(None, election)

    assert from_none == diff_elections(blank, election)
    assert len(_only(from_none, PlaceCounted)) == 107
    assert from_none[-1] == ProgressChanged(
        CountingProgress(0, 92), CountingProgress(92, 92)
    )
    assert _kinds(from_none).count("ProgressChanged") == 1


def test_none_previous_on_ep_equals_the_all_unreported_copy(
    ep_election: Election,
) -> None:
    blank = replace(
        ep_election, places=tuple(p.unreported() for p in ep_election.places)
    )

    assert diff_elections(None, ep_election) == diff_elections(blank, ep_election)


def test_diff_elections_does_not_modify_its_inputs_and_is_idempotent(
    election: Election,
) -> None:
    earlier = replace(
        election,
        places=tuple(p.unreported() for p in election.places[:40])
        + election.places[40:],
    )
    earlier_copy, later_copy = copy.deepcopy(earlier), copy.deepcopy(election)

    first = diff_elections(earlier, election)
    second = diff_elections(earlier, election)

    assert first == second
    assert earlier == earlier_copy
    assert election == later_copy
    assert len(first) > 0


# --- election type and date mismatch --------------------------------------------------


def test_a_type_mismatch_raises_value_error_naming_both() -> None:
    fv = make_election(_kreds("20"))
    ep = make_ep_election(_kreds("20"))

    with pytest.raises(ValueError) as caught:
        diff_elections(fv, ep)

    message = str(caught.value)
    assert "folketingsvalg 2026-03-24" in message
    assert "europaparlamentsvalg 2024-06-09" in message


def test_a_date_mismatch_raises_value_error_naming_both() -> None:
    earlier = make_election(_kreds("20"))
    later = replace(earlier, election_date=earlier.election_date + timedelta(days=1))

    with pytest.raises(ValueError, match=r"2026-03-24.*2026-03-25"):
        diff_elections(earlier, later)


@pytest.mark.parametrize("current", [make_election(_kreds("20")), make_ep_election()])
def test_none_previous_never_raises_for_any_election_type(current: Election) -> None:
    diff_elections(None, current)


def test_a_name_difference_alone_is_not_a_mismatch() -> None:
    earlier = make_election(_kreds("20"))

    assert diff_elections(earlier, replace(earlier, name="Another name")) == ()


# --- status transitions: PlaceCounted only from status 0 ------------------------------

A = make_party("A", 600)


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (Status.NOT_AVAILABLE, Status.PRELIMINARY, ["PlaceCounted", "LeaderChanged"]),
        (Status.NOT_AVAILABLE, Status.RECOUNT_FINAL, ["PlaceCounted", "LeaderChanged"]),
        (Status.NOT_AVAILABLE, Status.ERROR, ["StatusChanged"]),
        (Status.NOT_AVAILABLE, Status.RECOUNT_PENDING, ["StatusChanged"]),
        (Status.PRELIMINARY, Status.ERROR, ["StatusChanged"]),
        (Status.PRELIMINARY, Status.NOT_AVAILABLE, ["StatusChanged"]),
        (Status.PRELIMINARY, Status.RECOUNT_PENDING, ["StatusChanged"]),
        (Status.PRELIMINARY, Status.RECOUNT_PRELIMINARY, ["StatusChanged"]),
        (Status.RECOUNT_PRELIMINARY, Status.RECOUNT_FINAL, ["StatusChanged"]),
        (
            Status.RECOUNT_PENDING,
            Status.RECOUNT_PRELIMINARY,
            ["StatusChanged", "LeaderChanged"],
        ),
        (Status.ERROR, Status.PRELIMINARY, ["StatusChanged", "LeaderChanged"]),
        (Status.PRELIMINARY, Status.PRELIMINARY, []),
        (Status.ERROR, Status.ERROR, []),
    ],
)
def test_status_transitions_give_the_documented_kinds(
    before: Status, after: Status, expected: list[str]
) -> None:
    earlier = make_election(_country(A, status=before))
    later = make_election(_country(A, status=after))

    changes = diff_elections(earlier, later)

    assert _kinds(changes) == expected


def test_status_changed_carries_both_statuses_and_the_new_place() -> None:
    earlier = make_election(_country(A, status=Status.PRELIMINARY))
    later = make_election(_country(A, status=Status.ERROR))

    (change,) = diff_elections(earlier, later)

    assert change == StatusChanged(later.places[0], Status.PRELIMINARY, Status.ERROR)


@pytest.mark.parametrize(
    "status", [Status.NOT_AVAILABLE, Status.ERROR, Status.RECOUNT_PENDING]
)
def test_a_recovering_place_reports_its_leader_with_no_earlier_leader(
    status: Status,
) -> None:
    earlier = make_election(_country(A, status=status))
    later = make_election(_country(A))

    leader_changes = _only(diff_elections(earlier, later), LeaderChanged)

    assert [(c.before, c.after) for c in leader_changes] == [(None, A)]


def test_no_party_result_changed_is_ever_reported_across_a_status_gap() -> None:
    earlier = make_election(_country(A, status=Status.ERROR))
    later = make_election(_country(replace(A, votes=900), status=Status.PRELIMINARY))

    assert _only(diff_elections(earlier, later), PartyResultChanged) == []


def test_a_place_that_loses_its_leader_is_only_a_status_change() -> None:
    earlier = make_election(_country(A))
    later = make_election(_country(A, status=Status.RECOUNT_PENDING))

    changes = diff_elections(earlier, later)

    assert _kinds(changes) == ["StatusChanged"]


def test_a_place_whose_votes_all_vanish_loses_its_leader_without_leader_changed() -> (
    None
):
    earlier = make_election(_country(make_party("A", 600), make_party("B", 400)))
    later = make_election(_country(make_party("A", 0), make_party("B", 0)))

    changes = diff_elections(earlier, later)

    assert _only(changes, LeaderChanged) == []
    assert _kinds(changes) == ["PartyResultChanged", "PartyResultChanged"]


# --- PartyResultChanged ---------------------------------------------------------------


def test_a_national_seat_change_carries_seats_votes_and_percent_before_and_after(
    election: Election,
) -> None:
    before_party = election.get(COUNTRY, "0").parties[0]
    later = _swap_party(
        election,
        COUNTRY,
        "0",
        "A",
        seats=38 + 1,
        votes=779_524 + 100,
        percent=22.0,
    )

    (change,) = diff_elections(election, later)

    assert isinstance(change, PartyResultChanged)
    assert change.place == later.get(COUNTRY, "0")
    assert change.before == before_party
    assert (before_party.seats, change.after.seats) == (38, 39)
    assert (before_party.votes, change.after.votes) == (779_524, 779_624)
    assert (before_party.percent, change.after.percent) == (21.9, 22.0)
    assert (change.votes_delta, change.seats_delta) == (100, 1)


def test_a_storkreds_seat_change_is_reported_at_the_storkreds(
    election: Election,
) -> None:
    later = _swap_party(election, STORKREDS, "10", "A", seats=4, constituency_seats=4)

    (change,) = diff_elections(election, later)

    assert isinstance(change, PartyResultChanged)
    assert (change.place.place_type, change.place.place_id) == (STORKREDS, "10")
    assert change.seats_delta == 1
    assert change.votes_delta == 0
    assert change.after.constituency_seats == 4


def test_seat_changes_at_two_places_are_reported_in_the_elections_place_order(
    election: Election,
) -> None:
    later = _swap_party(election, STORKREDS, "10", "A", seats=4)
    later = _swap_party(later, COUNTRY, "0", "A", seats=39)

    changes = diff_elections(election, later)

    order = [later.places.index(c.place) for c in changes]  # type: ignore[union-attr]  # only place-carrying kinds here
    assert order == sorted(order)
    assert len(order) == 2
    assert {c.place.place_type for c in changes} == {COUNTRY, STORKREDS}  # type: ignore[union-attr]  # only place-carrying kinds here


@pytest.mark.parametrize(
    ("letter", "fields"),
    [
        ("F", {"percent": 17.5}),
        ("F", {"votes": 101}),
        ("A", {"seats": 1}),
        ("A", {"constituency_seats": 1}),
        ("A", {"supplementary_seats": 1}),
    ],
)
def test_any_single_figure_change_is_one_party_result_changed_and_no_leader_change(
    letter: str, fields: dict[str, object]
) -> None:
    earlier = make_election(
        _country(
            make_party("A", 1000, seats=0, constituency_seats=0, supplementary_seats=0),
            make_party("F", 100, percent=17.4),
        )
    )
    later = _swap_party(earlier, COUNTRY, "0", letter, **fields)

    changes = diff_elections(earlier, later)

    assert _kinds(changes) == ["PartyResultChanged"]


def test_a_percent_only_change_has_a_zero_votes_delta() -> None:
    earlier = make_election(_country(make_party("F", 100, percent=17.4)))
    later = make_election(_country(make_party("F", 100, percent=17.5)))

    (change,) = diff_elections(earlier, later)

    assert isinstance(change, PartyResultChanged)
    assert change.votes_delta == 0
    assert change.seats_delta is None


@pytest.mark.parametrize(("was", "now"), [(None, 3), (3, None)])
def test_seats_going_between_none_and_a_figure_is_a_change_with_no_seats_delta(
    was: int | None, now: int | None
) -> None:
    earlier = make_election(_country(make_party("A", 100, seats=was)))
    later = make_election(_country(make_party("A", 100, seats=now)))

    (change,) = diff_elections(earlier, later)

    assert isinstance(change, PartyResultChanged)
    assert change.seats_delta is None
    assert (change.before.seats, change.after.seats) == (was, now)  # type: ignore[union-attr]  # before is set


def test_a_new_party_has_before_none_and_no_deltas() -> None:
    earlier = make_election(_country(make_party("A", 600)))
    later = make_election(_country(make_party("A", 600), make_party("B", 100, seats=2)))

    (change,) = diff_elections(earlier, later)

    assert isinstance(change, PartyResultChanged)
    assert change.before is None
    assert change.after.letter == "B"
    assert change.votes_delta is None
    assert change.seats_delta is None


def test_a_vanished_party_is_ignored() -> None:
    earlier = make_election(_country(make_party("A", 600), make_party("B", 100)))
    later = make_election(_country(make_party("A", 600)))

    assert diff_elections(earlier, later) == ()


def test_changed_parties_come_in_the_current_feed_order() -> None:
    earlier = make_election(
        _country(make_party("A", 100), make_party("B", 90), make_party("C", 80))
    )
    later = make_election(
        _country(make_party("C", 85), make_party("A", 100), make_party("B", 95))
    )

    changes = _only(diff_elections(earlier, later), PartyResultChanged)

    assert [c.after.letter for c in changes] == ["C", "B"]


def test_uden_for_partier_changes_are_party_result_changes_but_never_a_leader() -> None:
    earlier = make_election(_country(make_party("A", 100), make_party("", 10)))
    later = make_election(_country(make_party("A", 100), make_party("", 900)))

    changes = diff_elections(earlier, later)

    assert _kinds(changes) == ["PartyResultChanged"]


def test_duplicate_party_ids_in_one_place_are_a_documented_limitation() -> None:
    # DST ids are unique within a place; with duplicates the last one wins, so the
    # first duplicate is compared with the wrong earlier party. Pinned, not endorsed.
    twin = (make_party("A", 10, party_id="1"), make_party("B", 20, party_id="1"))
    election = make_election(_country(*twin))

    changes = diff_elections(election, copy.deepcopy(election))

    assert _kinds(changes) == ["PartyResultChanged"]
    assert changes[0].after.letter == "A"  # type: ignore[union-attr]  # PartyResultChanged


# --- LeaderChanged --------------------------------------------------------------------


def test_an_overtake_names_the_old_and_the_new_leader() -> None:
    earlier = make_election(_country(make_party("A", 600), make_party("F", 400)))
    later = make_election(_country(make_party("A", 600), make_party("F", 700)))

    changes = diff_elections(earlier, later)

    (leader,) = _only(changes, LeaderChanged)
    assert (leader.before.letter, leader.after.letter) == ("A", "F")
    assert _kinds(changes) == ["PartyResultChanged", "LeaderChanged"]


def test_the_first_leader_of_a_newly_counted_place_has_no_old_one() -> None:
    earlier = make_election(_country(A, status=Status.NOT_AVAILABLE))
    later = make_election(_country(A))

    changes = diff_elections(earlier, later)

    assert changes == (
        PlaceCounted(later.places[0]),
        LeaderChanged(later.places[0], None, A),
    )


def test_votes_moving_without_an_overtake_is_no_leader_change() -> None:
    earlier = make_election(_country(make_party("A", 600), make_party("F", 400)))
    later = make_election(_country(make_party("A", 650), make_party("F", 450)))

    assert _only(diff_elections(earlier, later), LeaderChanged) == []


def test_a_tie_keeps_the_earlier_party_in_feed_order() -> None:
    earlier = make_election(_country(make_party("A", 500), make_party("F", 400)))
    later = make_election(_country(make_party("A", 500), make_party("F", 500)))

    assert _only(diff_elections(earlier, later), LeaderChanged) == []


def test_reordering_a_tie_in_the_feed_flips_the_leader_pinned() -> None:
    # The tie rule reads feed order, so a pure reordering of tied parties is a change.
    earlier = make_election(_country(make_party("A", 500), make_party("F", 500)))
    later = make_election(_country(make_party("F", 500), make_party("A", 500)))

    (leader,) = _only(diff_elections(earlier, later), LeaderChanged)

    assert (leader.before.letter, leader.after.letter) == ("A", "F")


def test_uden_for_partier_with_the_most_votes_never_leads() -> None:
    earlier = make_election(_country(make_party("", 900), make_party("A", 100)))
    later = make_election(_country(make_party("", 950), make_party("A", 100)))

    assert diff_elections(None, earlier)[0] == PlaceCounted(earlier.places[0])
    assert earlier.places[0].leader == make_party("A", 100)
    assert _only(diff_elections(earlier, later), LeaderChanged) == []


def test_a_place_with_only_uden_for_partier_has_no_leader_to_report() -> None:
    election = make_election(_country(make_party("", 900)))

    assert _kinds(diff_elections(None, election)) == ["PlaceCounted"]


def test_an_all_zero_votes_place_has_no_leader_and_then_a_first_leader() -> None:
    zero = make_election(_country(make_party("A", 0), make_party("B", 0)))
    voted = make_election(_country(make_party("A", 0), make_party("B", 5)))

    first = diff_elections(None, zero)
    second = diff_elections(zero, voted)

    assert _kinds(first) == ["PlaceCounted"]
    assert _kinds(second) == ["PartyResultChanged", "LeaderChanged"]
    leader = _only(second, LeaderChanged)[0]
    assert (leader.before, leader.after.letter) == (None, "B")


def test_a_leader_losing_a_place_to_a_vanished_party_gives_a_normal_leader_change() -> (
    None
):
    earlier = make_election(_country(make_party("A", 600), make_party("B", 700)))
    later = make_election(_country(make_party("A", 600)))

    (leader,) = _only(diff_elections(earlier, later), LeaderChanged)

    assert (leader.before.letter, leader.after.letter) == ("B", "A")


# --- first count with seats, seats arriving later (decision C1) -----------------------


def test_a_first_count_with_seats_gives_place_counted_and_leader_but_no_party_change() -> (
    None
):
    seated = _country(make_party("A", 600, seats=3), make_party("B", 400, seats=2))
    earlier = make_election(replace(seated, status=Status.NOT_AVAILABLE).unreported())
    later = make_election(seated)

    changes = diff_elections(earlier, later)

    assert _kinds(changes) == ["PlaceCounted", "LeaderChanged"]


def test_seats_arriving_after_the_count_are_a_party_result_change() -> None:
    counted = _country(make_party("A", 600), make_party("B", 400))
    seated = _country(make_party("A", 600, seats=3), make_party("B", 400, seats=2))

    changes = diff_elections(make_election(counted), make_election(seated))

    assert _kinds(changes) == ["PartyResultChanged", "PartyResultChanged"]
    assert [c.seats_delta for c in changes] == [None, None]  # type: ignore[union-attr]  # only PartyResultChanged here
    assert [c.after.seats for c in changes] == [3, 2]  # type: ignore[union-attr]  # only PartyResultChanged here


# --- places: matching, order, presence ------------------------------------------------


def test_places_are_matched_on_type_and_id_not_id_alone() -> None:
    country = _country(make_party("A", 600))
    tally = make_place(
        "0",
        place_type=PlaceType.TALLY,
        name="Optalling",
        parties=(make_party("A", 600),),
    )
    earlier = make_election(country, tally)
    later = make_election(country, replace(tally, parties=(make_party("A", 650),)))

    (change,) = diff_elections(earlier, later)

    assert isinstance(change, PartyResultChanged)
    assert change.place.place_type is PlaceType.TALLY


def test_a_place_only_in_current_is_compared_with_its_unreported_form() -> None:
    shared = _kreds("20")
    extra = _kreds("21")
    earlier = make_election(shared)
    later = make_election(shared, extra)

    changes = diff_elections(earlier, later)

    assert _kinds(changes) == ["PlaceCounted", "LeaderChanged", "ProgressChanged"]
    assert changes[0] == PlaceCounted(extra)
    assert changes[-1] == ProgressChanged(
        CountingProgress(1, 1), CountingProgress(2, 2)
    )


def test_a_place_only_in_previous_is_ignored_and_progress_uses_each_total() -> None:
    kept = _kreds("20")
    gone = _kreds("21")
    earlier = make_election(kept, gone)
    later = make_election(kept)

    changes = diff_elections(earlier, later)

    assert changes == (ProgressChanged(CountingProgress(2, 2), CountingProgress(1, 1)),)


def test_output_follows_currents_order_whatever_the_order_of_previous() -> None:
    first, second = _kreds("20"), _kreds("21")
    earlier = make_election(second.unreported(), first.unreported())
    later = make_election(first, second)

    changes = diff_elections(earlier, later)

    counted = [c.place.place_id for c in _only(changes, PlaceCounted)]
    assert counted == ["20", "21"]


def test_reordered_places_with_equal_content_give_no_changes() -> None:
    first, second = _kreds("20"), _kreds("21")

    assert (
        diff_elections(make_election(first, second), make_election(second, first)) == ()
    )


def test_changes_are_ordered_by_place_then_kind_with_progress_last_and_once() -> None:
    earlier = make_election(
        _country(make_party("A", 600), make_party("F", 400)),
        _kreds("20", status=Status.NOT_AVAILABLE),
        _kreds("21", status=Status.NOT_AVAILABLE),
    )
    later = make_election(
        _country(
            make_party("A", 600),
            make_party("F", 700),
            status=Status.RECOUNT_PRELIMINARY,
        ),
        _kreds("20"),
        _kreds("21"),
    )

    changes = diff_elections(earlier, later)

    assert _kinds(changes) == [
        "StatusChanged",
        "PartyResultChanged",
        "LeaderChanged",
        "PlaceCounted",
        "LeaderChanged",
        "PlaceCounted",
        "LeaderChanged",
        "ProgressChanged",
    ]
    places = [c.place.place_id for c in changes if not isinstance(c, ProgressChanged)]
    assert places == ["0"] * 3 + ["20"] * 2 + ["21"] * 2


# --- ProgressChanged ------------------------------------------------------------------


def test_progress_changed_carries_both_pairs_for_one_more_counted_place() -> None:
    kept = [_kreds(str(n)) for n in range(1, 92)]
    last = _kreds("92")
    earlier = make_election(*kept, last.unreported())
    later = make_election(*kept, last)

    changes = diff_elections(earlier, later)

    assert changes[-1] == ProgressChanged(
        CountingProgress(91, 92), CountingProgress(92, 92)
    )
    assert _kinds(changes).count("ProgressChanged") == 1


def test_progress_falling_is_a_progress_change_too() -> None:
    kept = _kreds("20")
    earlier = make_election(kept)
    later = make_election(kept.unreported())

    changes = diff_elections(earlier, later)

    assert _kinds(changes) == ["StatusChanged", "ProgressChanged"]
    assert changes[-1] == ProgressChanged(
        CountingProgress(1, 1), CountingProgress(0, 1)
    )


def test_progress_is_reported_when_the_totals_differ_between_snapshots() -> None:
    one = _kreds("20")
    two = _kreds("21")
    earlier = make_election(one)
    later = make_election(one, two.unreported())

    changes = diff_elections(earlier, later)

    assert changes == (ProgressChanged(CountingProgress(1, 1), CountingProgress(1, 2)),)


def test_progress_counts_only_opstillingskredse() -> None:
    earlier = make_election(_country(A, status=Status.NOT_AVAILABLE).unreported())
    later = make_election(_country(A))

    assert _only(diff_elections(earlier, later), ProgressChanged) == []


# --- every kind can be produced -------------------------------------------------------


def test_every_one_of_the_five_kinds_can_be_produced() -> None:
    kreds_before = _kreds("20")
    kreds_after = replace(kreds_before, status=Status.NOT_AVAILABLE).unreported()
    earlier = make_election(
        _country(make_party("A", 600), make_party("F", 400)), kreds_after
    )
    later = make_election(
        _country(
            make_party("A", 600),
            make_party("F", 700),
            status=Status.RECOUNT_PRELIMINARY,
        ),
        kreds_before,
    )

    produced = {type(change) for change in diff_elections(earlier, later)}

    assert produced == set(typing.get_args(Change.__value__))


# --- T7: consistency with replay ------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture_name", "leader_letter"), [("election", "A"), ("ep_election", "F")]
)
def test_diffing_every_replay_step_gives_one_place_counted_per_place_and_the_leader(
    request: pytest.FixtureRequest, fixture_name: str, leader_letter: str
) -> None:
    full: Election = request.getfixturevalue(fixture_name)
    source = ReplaySource(full, speed=math.inf)
    previous = source.initial()
    changes: list[Change] = []
    for step in source:
        step_changes = diff_elections(previous, step.election)
        assert len(_only(step_changes, PlaceCounted)) == 1
        changes.extend(step_changes)
        previous = step.election

    progress = _only(tuple(changes), ProgressChanged)
    country_leaders = [
        c for c in _only(tuple(changes), LeaderChanged) if c.place.place_type is COUNTRY
    ]
    assert len(_only(tuple(changes), PlaceCounted)) == 107
    assert _only(tuple(changes), PartyResultChanged) == []
    assert _only(tuple(changes), StatusChanged) == []
    assert progress[0].before == CountingProgress(0, 92)
    assert progress[-1].after == CountingProgress(92, 92)
    assert len(progress) == 92
    assert all(
        a.after == b.before for a, b in zip(progress, progress[1:], strict=False)
    )
    assert [c.after.letter for c in country_leaders] == [leader_letter]
    assert country_leaders[0].before is None
    assert previous.get(COUNTRY, "0").leader is not None
    assert previous.get(COUNTRY, "0").leader.letter == leader_letter  # type: ignore[union-attr]  # asserted not None above


# --- EP never carries seats -----------------------------------------------------------


def test_ep_changes_never_carry_a_seat_delta(ep_election: Election) -> None:
    later = _swap_party(ep_election, COUNTRY, "0", "F", votes=426_467, percent=17.5)
    later = _swap_party(later, STORKREDS, "10", "A", votes=1)

    changes = diff_elections(ep_election, later)

    party_changes = _only(changes, PartyResultChanged)
    assert len(party_changes) == 2
    assert {c.seats_delta for c in party_changes} == {None}
    assert {c.votes_delta for c in party_changes} != {None}
    assert all(c.after.seats is None for c in party_changes)


def test_an_ep_overtake_is_a_leader_change_between_the_two_parties(
    ep_election: Election,
) -> None:
    later = _swap_party(ep_election, COUNTRY, "0", "A", votes=500_000)

    leader = _only(diff_elections(ep_election, later), LeaderChanged)

    assert [(c.before.letter, c.after.letter) for c in leader] == [("F", "A")]  # type: ignore[union-attr]  # before is set


# --- round 4: referenda (A6, T6) ------------------------------------------------------


def _fa_country(ja: int, nej: int, status: Status = Status.PRELIMINARY) -> Place:
    return make_place(
        "0",
        place_type=COUNTRY,
        name="Hele landet",
        status=status,
        parties=(make_answer("JA", ja), make_answer("NEJ", nej)),
    )


def test_a_referendum_lead_flipping_from_ja_to_nej_is_a_leader_change_with_deltas() -> (
    None
):
    before = make_fa_election(_fa_country(600, 400))
    after = make_fa_election(_fa_country(400, 600))

    changes = diff_elections(before, after)

    (leader,) = _only(changes, LeaderChanged)
    assert (leader.before.letter, leader.after.letter) == ("JA", "NEJ")
    deltas = {
        c.after.letter: (c.votes_delta, c.seats_delta)
        for c in _only(changes, PartyResultChanged)
    }
    assert deltas == {"JA": (-200, None), "NEJ": (200, None)}


def test_a_referendum_tie_keeps_the_earlier_answer_and_reports_no_leader_change() -> (
    None
):
    before = make_fa_election(_fa_country(600, 400))
    after = make_fa_election(_fa_country(500, 500))

    assert _only(diff_elections(before, after), LeaderChanged) == []


def test_a_referendum_percent_only_move_is_a_party_result_change_without_seats() -> (
    None
):
    before = make_fa_election(_fa_country(600, 400))
    moved = _swap_party(before, COUNTRY, "0", "JA", percent=60.5)

    changes = diff_elections(before, moved)

    (change,) = _only(changes, PartyResultChanged)
    assert (change.votes_delta, change.seats_delta) == (0, None)
    assert change.after.percent == 60.5
    assert _only(changes, LeaderChanged) == []


def test_a_newly_counted_referendum_place_gives_place_counted_and_the_leading_answer() -> (
    None
):
    before = make_fa_election(_fa_country(0, 0, Status.NOT_AVAILABLE))
    after = make_fa_election(_fa_country(300, 700))

    changes = diff_elections(before, after)

    # a country does not move the districts-counted progress, so no ProgressChanged
    assert _kinds(changes) == ["PlaceCounted", "LeaderChanged"]
    (leader,) = _only(changes, LeaderChanged)
    assert leader.before is None
    assert leader.after.letter == "NEJ"
    assert _only(changes, PartyResultChanged) == []


def test_a_referendum_diffed_against_a_party_election_names_both_types() -> None:
    referendum = make_fa_election(_fa_country(600, 400))
    other = replace(referendum, election_type=make_ep_election().election_type)

    with pytest.raises(ValueError, match="folkeafstemning") as caught:
        diff_elections(referendum, other)

    assert "europaparlamentsvalg" in str(caught.value)


@pytest.mark.parametrize(
    ("fixture_name", "places", "kreds", "leader_letter"),
    [
        ("fa_2022", 107, 92, "JA"),
        ("fa_2015", 107, 92, "NEJ"),
        ("fa_2009", 109, 94, "JA"),
    ],
)
def test_diffing_every_referendum_replay_step_gives_one_place_counted_per_reported_place(
    request: pytest.FixtureRequest,
    fixture_name: str,
    places: int,
    kreds: int,
    leader_letter: str,
) -> None:
    full: Election = request.getfixturevalue(fixture_name)
    source = ReplaySource(full, speed=math.inf)
    previous = source.initial()
    changes: list[Change] = []
    for step in source:
        step_changes = diff_elections(previous, step.election)
        assert len(_only(step_changes, PlaceCounted)) == 1
        changes.extend(step_changes)
        previous = step.election

    progress = _only(tuple(changes), ProgressChanged)
    country_leaders = [
        c for c in _only(tuple(changes), LeaderChanged) if c.place.place_type is COUNTRY
    ]
    assert len(_only(tuple(changes), PlaceCounted)) == places
    assert places == sum(1 for p in full.places if p.has_result)
    assert _only(tuple(changes), PartyResultChanged) == []
    assert _only(tuple(changes), StatusChanged) == []
    assert progress[0].before == CountingProgress(0, kreds)
    assert progress[-1].after == CountingProgress(kreds, kreds)
    assert len(progress) == kreds
    assert [c.after.letter for c in country_leaders] == [leader_letter]
    assert previous == full
    assert previous.get(COUNTRY, "0").leader.letter == leader_letter  # type: ignore[union-attr]  # a result is present
    assert all(c.after.seats is None for c in _only(tuple(changes), LeaderChanged))
