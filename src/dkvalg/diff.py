"""Compare two election snapshots and report what changed, as typed changes.

The library only detects: nothing here formats or delivers a notification.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime

from dkvalg.model import (
    CountingProgress,
    Election,
    ElectionType,
    PartyResult,
    Place,
    PlaceType,
    Status,
)


@dataclass(frozen=True, slots=True)
class PlaceCounted:
    """A place that had no figures at all (status 0) and has a result now.

    Attributes:
        place: The place as it is now.
    """

    place: Place


@dataclass(frozen=True, slots=True)
class PartyResultChanged:
    """A party's result changed at a place that had a result in both snapshots.

    Attributes:
        place: The place as it is now.
        before: The party's earlier result, or None if the party is new there.
        after: The party's result now.
    """

    place: Place
    before: PartyResult | None
    after: PartyResult

    @property
    def votes_delta(self) -> int | None:
        """Votes gained, or None when the party is new at the place."""
        if self.before is None:
            return None
        return self.after.votes - self.before.votes

    @property
    def seats_delta(self) -> int | None:
        """Seats gained, or None when the party is new or a side has no seat figure."""
        if self.before is None or self.before.seats is None or self.after.seats is None:
            return None
        return self.after.seats - self.before.seats


@dataclass(frozen=True, slots=True)
class LeaderChanged:
    """The party with most votes at a place is a different one.

    Attributes:
        place: The place as it is now.
        before: The earlier leader, or None if the place had none.
        after: The leader now.
    """

    place: Place
    before: PartyResult | None
    after: PartyResult


@dataclass(frozen=True, slots=True)
class StatusChanged:
    """A place's status changed, other than from "no figures" to a result.

    Attributes:
        place: The place as it is now.
        before: The earlier status.
        after: The status now.
    """

    place: Place
    before: Status
    after: Status


@dataclass(frozen=True, slots=True)
class ProgressChanged:
    """The counted-of-total opstillingskredse changed.

    Attributes:
        before: The earlier progress.
        after: The progress now.
    """

    before: CountingProgress
    after: CountingProgress


type Change = (
    PlaceCounted | PartyResultChanged | LeaderChanged | StatusChanged | ProgressChanged
)


def _figures_differ(before: PartyResult, after: PartyResult) -> bool:
    """Whether any figure of a party's result differs."""
    return (
        before.votes != after.votes
        or before.percent != after.percent
        or before.seats != after.seats
        or before.constituency_seats != after.constituency_seats
        or before.supplementary_seats != after.supplementary_seats
    )


def _place_changes(before: Place, after: Place) -> list[Change]:
    """The changes from one place to its later form, in the documented order."""
    changes: list[Change] = []
    if before.status == Status.NOT_AVAILABLE and after.has_result:
        changes.append(PlaceCounted(after))
    elif before.status != after.status:
        changes.append(StatusChanged(after, before.status, after.status))
    if before.has_result and after.has_result:
        earlier = {party.party_id: party for party in before.parties}
        for party in after.parties:
            was = earlier.get(party.party_id)
            if was is None or _figures_differ(was, party):
                changes.append(PartyResultChanged(after, was, party))
    leader = after.leader
    if leader is not None:
        was_leader = before.leader
        if was_leader is None or was_leader.party_id != leader.party_id:
            changes.append(LeaderChanged(after, was_leader, leader))
    return changes


def diff_elections(previous: Election | None, current: Election) -> tuple[Change, ...]:
    """Compare two snapshots of the same election.

    Places are matched on type and id and visited in `current`'s order. A place
    only in `current` is compared with its own unreported form; a place only in
    `previous` is ignored. Per place: `PlaceCounted` (earlier status 0, a result
    now) or else `StatusChanged`; then a `PartyResultChanged` per party of
    `current` whose figures differ or that is new (only where both snapshots hold
    a result); then `LeaderChanged`. Last comes one `ProgressChanged` if the
    counting progress differs.

    Args:
        previous: The earlier snapshot, or None for none (every place then counts
            as unreported).
        current: The later snapshot.

    Returns:
        The changes, empty for equal elections. Neither input is modified.

    Raises:
        ValueError: If the two differ in election type or election date.
    """
    if previous is not None and (
        previous.election_type != current.election_type
        or previous.election_date != current.election_date
    ):
        raise ValueError(
            f"cannot diff {previous.election_type.value} {previous.election_date} "
            f"against {current.election_type.value} {current.election_date}"
        )
    earlier = (
        {}
        if previous is None
        else {(p.place_type, p.place_id): p for p in previous.places}
    )
    changes: list[Change] = []
    for place in current.places:
        before = earlier.get((place.place_type, place.place_id), place.unreported())
        changes.extend(_place_changes(before, place))
    now = current.counting_progress()
    was = (
        CountingProgress(0, now.total)
        if previous is None
        else previous.counting_progress()
    )
    if was != now:
        changes.append(ProgressChanged(was, now))
    return tuple(changes)


def _describe(change: Change) -> str:
    """One short line for the showcase."""
    kind = type(change).__name__
    match change:
        case PartyResultChanged(place=place, after=after, votes_delta=delta):
            return f"{kind}: {place.name} {after.letter} votes {delta:+}"
        case LeaderChanged(place=place, before=before, after=after):
            old = "-" if before is None else before.letter
            return f"{kind}: {place.name} {old} -> {after.letter}"
        case ProgressChanged(before=before, after=after):
            return f"{kind}: {before} -> {after}"
        case _:
            return f"{kind}: {change.place.name}"


def main() -> None:
    """Showcase this module's functionality."""
    election_day = date.fromisoformat("2026-03-24")
    reported_at = datetime.fromisoformat("2026-03-24T21:21:09")
    social_democrats = PartyResult("5891", "A", "A. Socialdemokratiet", 7286, 14.6)
    liberals = PartyResult("5892", "V", "V. Venstre", 6900, 13.8)
    kreds = Place(
        PlaceType.OPSTILLINGSKREDS,
        "20",
        "1.Østerbro",
        "10",
        Status.PRELIMINARY,
        "Foreløbigt resultat",
        reported_at,
        parties=(social_democrats, liberals),
    )
    waiting = Election(
        "Folketingsvalg 2026",
        ElectionType.FOLKETINGSVALG,
        election_day,
        (kreds.unreported(),),
    )
    counted = replace(waiting, places=(kreds,))
    overtaken = replace(liberals, votes=7400, percent=14.9)
    recounted = replace(
        waiting, places=(replace(kreds, parties=(social_democrats, overtaken)),)
    )

    first = diff_elections(None, counted)
    second = diff_elections(counted, recounted)
    third = diff_elections(recounted, recounted)

    print("nothing -> first result:")
    for change in first:
        print(f"  {_describe(change)}")
    print("first result -> Venstre overtakes:")
    for change in second:
        print(f"  {_describe(change)}")
    print(f"unchanged: {third}")


if __name__ == "__main__":
    main()
