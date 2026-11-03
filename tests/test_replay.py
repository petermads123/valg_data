import dataclasses
import math

import pytest
from conftest import dt, make_election, make_place

from dkvalg import (
    CountingProgress,
    Election,
    PlaceType,
    ReplaySource,
    ReplayStep,
    Status,
)
from dkvalg.model import Place

KREDS = PlaceType.OPSTILLINGSKREDS


def _timed(place_id: str, stamp: str, **kwargs: object) -> Place:
    return make_place(place_id, last_changed=dt(stamp), **kwargs)  # type: ignore[arg-type]  # forwarded as-is


def _recorded(election: Election, speed: float) -> tuple[list[ReplayStep], list[float]]:
    waits: list[float] = []
    steps = list(ReplaySource(election, speed=speed, sleep=waits.append))
    return steps, waits


def _no_sleep(_seconds: float) -> None:
    raise AssertionError("sleep must not be called")


# --- fixtures: A5 / T5 ------------------------------------------------------------


def test_replay_starts_at_zero_of_92_on_the_fixtures(election: Election) -> None:
    source = ReplaySource(election, speed=math.inf)

    assert source.initial().counting_progress() == CountingProgress(0, 92)


def test_replay_initial_turns_every_timed_place_into_its_placeholder(
    election: Election,
) -> None:
    initial = ReplaySource(election, speed=math.inf).initial()

    assert len(initial.places) == 107
    for before, after in zip(election.places, initial.places, strict=True):
        assert after == before.unreported()


def test_replay_yields_one_step_per_place_in_time_order_on_the_fixtures(
    election: Election,
) -> None:
    steps, waits = _recorded(election, math.inf)

    assert len(steps) == 107
    times = [step.at for step in steps]
    assert times == sorted(times)
    assert waits == []


def test_replay_ties_on_the_fixtures_keep_overview_order(election: Election) -> None:
    steps, _ = _recorded(election, math.inf)
    position = {id(p): i for i, p in enumerate(election.places)}

    for earlier, later in zip(steps, steps[1:], strict=False):
        if earlier.at == later.at:
            assert position[id(earlier.place)] < position[id(later.place)]


def test_replay_final_snapshot_equals_the_static_election_on_the_fixtures(
    election: Election,
) -> None:
    steps, _ = _recorded(election, math.inf)

    assert steps[-1].election == election
    assert steps[-1].progress == CountingProgress(92, 92)


def test_replay_progress_rises_monotonically_by_at_most_one_to_92(
    election: Election,
) -> None:
    steps, _ = _recorded(election, math.inf)

    counted = [step.progress.counted for step in steps]
    assert counted == sorted(counted)
    assert all(b - a in (0, 1) for a, b in zip(counted, counted[1:], strict=False))
    assert counted[-1] == 92
    assert all(step.progress.total == 92 for step in steps)


def test_replay_each_step_changes_exactly_the_revealed_place(
    election: Election,
) -> None:
    source = ReplaySource(election, speed=math.inf)
    previous = source.initial()

    for step in source:
        changed = [
            (a, b)
            for a, b in zip(previous.places, step.election.places, strict=True)
            if a != b
        ]
        assert [b for _, b in changed] == [step.place]
        assert step.at == step.place.last_changed
        previous = step.election


def test_replay_mid_sequence_snapshots_hold_exactly_the_revealed_places(
    election: Election,
) -> None:
    steps, _ = _recorded(election, math.inf)
    middle = steps[50]

    revealed = {(s.place.place_type, s.place.place_id) for s in steps[:51]}
    for place in middle.election.places:
        if (place.place_type, place.place_id) in revealed:
            assert place.has_result
            assert place.parties
        else:
            assert place.status is Status.NOT_AVAILABLE
            assert place.parties == ()


def test_replay_aggregates_appear_late_because_they_changed_last(
    election: Election,
) -> None:
    steps, _ = _recorded(election, math.inf)
    last_five = {(s.place.place_type) for s in steps[-5:]}

    assert PlaceType.COUNTRY in last_five
    assert PlaceType.TALLY in last_five


def test_replay_earlier_step_snapshots_are_not_changed_by_later_steps(
    election: Election,
) -> None:
    steps, _ = _recorded(election, math.inf)
    first_counted = steps[0].progress

    list(ReplaySource(election, speed=math.inf))

    assert steps[0].progress == first_counted
    assert steps[0].election.counting_progress().counted <= 1


def test_replay_does_not_mutate_the_election(election: Election) -> None:
    before = dataclasses.replace(election)

    list(ReplaySource(election, speed=math.inf))

    assert election == before


def test_replay_twice_gives_equal_steps_and_equal_sleeps(election: Election) -> None:
    waits: list[float] = []
    source = ReplaySource(election, speed=600.0, sleep=waits.append)

    first = list(source)
    first_waits, waits[:] = list(waits), []
    second = list(source)

    assert first == second
    assert waits == first_waits
    assert source.initial() == source.initial()


# --- synthetic: ordering, sleeping ------------------------------------------------


def test_replay_ties_keep_overview_order_not_id_order() -> None:
    election = make_election(
        _timed("30", "2026-03-24T22:00:00"),
        _timed("10", "2026-03-24T22:00:00"),
        _timed("20", "2026-03-24T22:00:00"),
    )

    steps, waits = _recorded(election, 1.0)

    assert [s.place.place_id for s in steps] == ["30", "10", "20"]
    assert waits == []


def test_replay_reveals_an_earlier_timestamp_first_even_when_listed_later() -> None:
    election = make_election(
        _timed("C", "2026-03-24T22:10:00"),
        _timed("A", "2026-03-24T22:00:00"),
        _timed("B", "2026-03-24T22:00:00"),
    )

    steps, waits = _recorded(election, 1.0)

    assert [s.place.place_id for s in steps] == ["A", "B", "C"]
    assert waits == [600.0]


def test_replay_sleep_is_the_gap_divided_by_speed_and_skips_zero_gaps() -> None:
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"),
        _timed("2", "2026-03-24T21:00:30"),
        _timed("3", "2026-03-24T21:00:30"),
        _timed("4", "2026-03-24T21:01:30"),
    )

    _, waits = _recorded(election, 10.0)

    assert waits == [3.0, 6.0]


@pytest.mark.parametrize(("speed", "factor"), [(1.0, 1), (0.5, 2), (600.0, 1 / 600)])
def test_replay_total_waiting_is_the_time_span_over_speed(
    speed: float, factor: float
) -> None:
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"),
        _timed("2", "2026-03-24T21:10:00"),
        _timed("3", "2026-03-24T21:10:30"),
    )

    _, waits = _recorded(election, speed)

    assert sum(waits) == pytest.approx(630 * factor)


def test_replay_fractional_second_gaps_give_fractional_sleeps() -> None:
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"),
        _timed("2", "2026-03-24T21:00:00.500000"),
    )

    _, waits = _recorded(election, 1.0)

    assert waits == [0.5]


def test_replay_never_sleeps_before_the_first_step() -> None:
    election = make_election(_timed("1", "2026-03-24T21:00:00"))

    steps, waits = _recorded(election, 1.0)

    assert len(steps) == 1
    assert waits == []


def test_replay_infinite_speed_never_calls_sleep() -> None:
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"), _timed("2", "2026-03-25T21:00:00")
    )

    steps = list(ReplaySource(election, speed=math.inf, sleep=_no_sleep))

    assert len(steps) == 2


def test_replay_sleeps_lazily_just_before_each_step() -> None:
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"),
        _timed("2", "2026-03-24T21:01:00"),
        _timed("3", "2026-03-24T21:02:00"),
    )
    waits: list[float] = []
    iterator = iter(ReplaySource(election, speed=1.0, sleep=waits.append))

    assert waits == []
    next(iterator)
    assert len(waits) == 0
    next(iterator)
    assert len(waits) == 1
    next(iterator)
    assert len(waits) == 2


def test_replay_a_tiny_speed_hands_an_infinite_wait_to_the_injected_sleep() -> None:
    """Documented: the library does not clamp; a real `time.sleep(inf)` would raise."""
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"), _timed("2", "2026-03-24T21:00:01")
    )

    _, waits = _recorded(election, 5e-324)

    assert waits == [math.inf]


def test_replay_interleaved_iterators_do_not_share_state() -> None:
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"),
        _timed("2", "2026-03-24T21:01:00"),
        _timed("3", "2026-03-24T21:02:00"),
    )
    source = ReplaySource(election, speed=math.inf)
    one, two = iter(source), iter(source)

    first = [next(one), next(one)]
    other = [next(two)]
    rest = list(one)

    assert [s.place.place_id for s in first + rest] == ["1", "2", "3"]
    assert other[0] == first[0]
    assert [s.place.place_id for s in two] == ["2", "3"]


# --- synthetic: speed validation ---------------------------------------------------


@pytest.mark.parametrize("speed", [0, 0.0, -0.0, -1, -1.5, -math.inf, math.nan])
def test_replay_rejects_a_speed_that_is_not_positive_naming_the_value(
    speed: float,
) -> None:
    with pytest.raises(ValueError, match="speed must be positive") as caught:
        ReplaySource(make_election(), speed=speed)

    assert str(speed) in str(caught.value)


@pytest.mark.parametrize("speed", [1e-300, 5e-324, 1, True, 600.0, math.inf])
def test_replay_accepts_every_positive_speed_including_infinity(
    speed: float,
) -> None:
    ReplaySource(make_election(), speed=speed)


def test_replay_default_speed_is_real_time() -> None:
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"), _timed("2", "2026-03-24T21:00:07")
    )
    waits: list[float] = []

    list(ReplaySource(election, sleep=waits.append))

    assert waits == [7.0]


def test_replay_a_non_numeric_speed_is_a_type_error_not_a_value_error() -> None:
    """Documented limitation: the signature says float, so a string is a caller bug."""
    with pytest.raises(TypeError):
        ReplaySource(make_election(), speed="fast")  # type: ignore[arg-type]  # wrong type on purpose


# --- synthetic: odd elections --------------------------------------------------------


def test_replay_of_an_election_without_places_has_no_steps() -> None:
    election = make_election()
    source = ReplaySource(election, speed=math.inf)

    assert list(source) == []
    assert source.initial() == election
    assert source.initial().counting_progress() == CountingProgress(0, 0)


def test_replay_of_untimed_places_has_no_steps_and_keeps_them_from_the_start() -> None:
    election = make_election(
        make_place("1", status=Status.NOT_AVAILABLE, status_text="Ikke klar"),
        make_place("2", status=Status.ERROR, status_text="Fejl"),
    )
    source = ReplaySource(election, speed=math.inf)

    assert list(source) == []
    assert source.initial() == election


def test_replay_final_snapshot_equals_the_election_with_untimed_and_error_places() -> (
    None
):
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"),
        make_place("2", status=Status.NOT_AVAILABLE, status_text="Ikke klar"),
        _timed("3", "2026-03-24T21:05:00", status=Status.ERROR, status_text="Fejl"),
        _timed(
            "4", "2026-03-24T21:06:00", status=Status.NOT_AVAILABLE, status_text="x"
        ),
    )

    steps, _ = _recorded(election, math.inf)

    assert len(steps) == 3
    assert steps[-1].election == election
    assert (
        ReplaySource(election, speed=math.inf).initial().places[1] == election.places[1]
    )


def test_replay_a_timed_error_place_loses_its_status_text_until_it_is_revealed() -> (
    None
):
    """Documented: every timed place starts as the blank placeholder, status 9 included."""
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"),
        _timed("3", "2026-03-24T21:05:00", status=Status.ERROR, status_text="Fejl"),
    )
    source = ReplaySource(election, speed=math.inf)
    steps = list(source)

    assert source.initial().places[1].status_text == ""
    assert steps[0].election.places[1].status_text == ""
    assert steps[1].election.places[1].status_text == "Fejl"


def test_replay_an_untimed_place_with_a_result_counts_from_the_start() -> None:
    """Documented: only places with a `last_changed` are held back."""
    election = make_election(make_place("1"), _timed("2", "2026-03-24T21:00:00"))

    source = ReplaySource(election, speed=math.inf)

    assert source.initial().counting_progress() == CountingProgress(1, 2)


def test_replay_step_progress_matches_its_snapshot() -> None:
    election = make_election(
        _timed("1", "2026-03-24T21:00:00"), _timed("2", "2026-03-24T21:01:00")
    )

    steps, _ = _recorded(election, math.inf)

    assert [str(s.progress) for s in steps] == ["1/2", "2/2"]
    assert steps[0].progress == steps[0].election.counting_progress()


def test_replay_step_is_immutable() -> None:
    election = make_election(_timed("1", "2026-03-24T21:00:00"))
    step = next(iter(ReplaySource(election, speed=math.inf)))

    with pytest.raises(dataclasses.FrozenInstanceError):
        step.at = dt("2026-03-24T21:00:00")  # type: ignore[misc]  # frozen on purpose


def test_replay_initial_is_a_new_election_and_leaves_the_source_untouched() -> None:
    election = make_election(_timed("1", "2026-03-24T21:00:00"))
    source = ReplaySource(election, speed=math.inf)

    initial = source.initial()

    assert initial is not election
    assert election.places[0].has_result
    assert not initial.places[0].has_result
