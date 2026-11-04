"""Normalised, immutable model of an election and its result places."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import IntEnum, StrEnum


class ElectionType(StrEnum):
    """Which kind of election."""

    FOLKETINGSVALG = "folketingsvalg"
    EUROPAPARLAMENTSVALG = "europaparlamentsvalg"


class PlaceType(StrEnum):
    """Level of a result place.

    `TALLY` is DST's seatless preliminary "optalling" total.
    """

    COUNTRY = "country"
    TALLY = "tally"
    LANDSDEL = "landsdel"
    STORKREDS = "storkreds"
    OPSTILLINGSKREDS = "opstillingskreds"


class Status(IntEnum):
    """DST status code of a result feed."""

    NOT_AVAILABLE = 0
    PRELIMINARY = 1
    ERROR = 9
    RECOUNT_PENDING = 10
    RECOUNT_PRELIMINARY = 11
    RECOUNT_FINAL = 12

    @property
    def has_result(self) -> bool:
        """Whether this status carries a reported result (codes 1, 11 and 12)."""
        return self in (
            Status.PRELIMINARY,
            Status.RECOUNT_PRELIMINARY,
            Status.RECOUNT_FINAL,
        )


@dataclass(frozen=True, slots=True)
class PartyResult:
    """One party's result in one place.

    `party_id == ""` is DST's "Uden for partier" entry, which is not a party.

    Attributes:
        party_id: DST's party id, empty for "Uden for partier".
        letter: The party letter, empty when DST gives none.
        name: The party name as served.
        votes: Votes for the party.
        percent: Share of valid votes, as served.
        seats: Total seats, or None where DST gives none.
        constituency_seats: Constituency seats, or None where DST gives none.
        supplementary_seats: Supplementary seats, or None where DST gives none.
    """

    party_id: str
    letter: str
    name: str
    votes: int
    percent: float
    seats: int | None = None
    constituency_seats: int | None = None
    supplementary_seats: int | None = None

    @property
    def is_party(self) -> bool:
        """Whether this is a real party rather than "Uden for partier"."""
        return self.party_id != ""


@dataclass(frozen=True, slots=True)
class Place:
    """One result place.

    Attributes:
        place_type: The level of the place.
        place_id: DST's id for the place within its type.
        name: The place name as served.
        parent_id: Id of the enclosing place, or None.
        status: DST status code.
        status_text: DST's status text, empty for a placeholder.
        last_changed: Naive Danish local time the feed last changed, or None.
        eligible_voters: Eligible voters, or None without a result.
        turnout_percent: Turnout percentage, or None without a result.
        valid_votes: Valid votes, or None without a result.
        blank_votes: Blank votes, or None without a result.
        other_invalid_votes: Other invalid votes, or None without a result.
        total_invalid_votes: All invalid votes, or None without a result.
        total_votes: All votes cast, or None without a result.
        parties: Per-party results, empty without a result.
    """

    place_type: PlaceType
    place_id: str
    name: str
    parent_id: str | None
    status: Status
    status_text: str
    last_changed: datetime | None
    eligible_voters: int | None = None
    turnout_percent: float | None = None
    valid_votes: int | None = None
    blank_votes: int | None = None
    other_invalid_votes: int | None = None
    total_invalid_votes: int | None = None
    total_votes: int | None = None
    parties: tuple[PartyResult, ...] = ()

    @property
    def has_result(self) -> bool:
        """Whether this place has a reported result."""
        return self.status.has_result

    @property
    def leader(self) -> PartyResult | None:
        """The party with the most votes at this place.

        "Uden for partier" never leads; a tie goes to the party earlier in the
        feed. None when the place has no result or no party.
        """
        if not self.has_result:
            return None
        best: PartyResult | None = None
        for party in self.parties:
            if party.is_party and (best is None or party.votes > best.votes):
                best = party
        return best

    def unreported(self) -> Place:
        """Return the placeholder form of this place.

        Returns:
            A place with the same type, id, name and parent, status
            `NOT_AVAILABLE`, empty `status_text`, no timestamp and no figures.
        """
        return Place(
            place_type=self.place_type,
            place_id=self.place_id,
            name=self.name,
            parent_id=self.parent_id,
            status=Status.NOT_AVAILABLE,
            status_text="",
            last_changed=None,
        )


@dataclass(frozen=True, slots=True)
class CountingProgress:
    """How many opstillingskredse have a result.

    Attributes:
        counted: Opstillingskredse with a reported result.
        total: All opstillingskredse in the election.
    """

    counted: int
    total: int

    def __str__(self) -> str:
        """Format as `counted/total`."""
        return f"{self.counted}/{self.total}"


@dataclass(frozen=True, slots=True)
class Election:
    """A snapshot of an election, with its places in overview order.

    Attributes:
        name: The election name as served.
        election_type: The kind of election.
        election_date: The election day.
        places: Every result place, in overview order.
    """

    name: str
    election_type: ElectionType
    election_date: date
    places: tuple[Place, ...]

    def get(self, place_type: PlaceType, place_id: str) -> Place:
        """Look one place up.

        Args:
            place_type: The level of the place.
            place_id: DST's id for the place within its type.

        Returns:
            The matching place.

        Raises:
            KeyError: If there is no such place; the message names both values.
        """
        for place in self.places:
            if place.place_type == place_type and place.place_id == place_id:
                return place
        raise KeyError(f"no place of type {place_type.value!r} with id {place_id!r}")

    def of_type(self, place_type: PlaceType) -> tuple[Place, ...]:
        """Return every place of one level, in overview order.

        Args:
            place_type: The level to select.

        Returns:
            The matching places, possibly none.
        """
        return tuple(p for p in self.places if p.place_type == place_type)

    def counting_progress(self) -> CountingProgress:
        """Count the opstillingskredse that have a result.

        Returns:
            How many of the opstillingskredse have a reported result.
        """
        kredse = self.of_type(PlaceType.OPSTILLINGSKREDS)
        return CountingProgress(
            counted=sum(1 for p in kredse if p.has_result), total=len(kredse)
        )

    def changed_since(self, previous: Election | None) -> tuple[Place, ...]:
        """List the places that differ from an earlier snapshot.

        Args:
            previous: The earlier snapshot, or None for no earlier snapshot.

        Returns:
            The places of this election that have a `last_changed` and are not
            equal to the place with the same type and id in `previous` (or are
            absent from it), in this election's order. Every such place when
            `previous` is None.
        """
        if previous is None:
            return tuple(p for p in self.places if p.last_changed is not None)
        earlier = {(p.place_type, p.place_id): p for p in previous.places}
        return tuple(
            p
            for p in self.places
            if p.last_changed is not None
            and earlier.get((p.place_type, p.place_id)) != p
        )


def main() -> None:
    """Showcase this module's functionality."""
    election_day = date.fromisoformat("2026-03-24")
    reported_at = datetime.fromisoformat("2026-03-24T21:21:09")
    party = PartyResult("5891", "A", "A. Socialdemokratiet", 7286, 14.6)
    reported = Place(
        PlaceType.OPSTILLINGSKREDS,
        "20",
        "1.Østerbro",
        "10",
        Status.PRELIMINARY,
        "Foreløbigt resultat",
        reported_at,
        parties=(party,),
    )
    waiting = replace(reported, place_id="21", name="2.Sundbyvester").unreported()
    election = Election(
        "Folketingsvalg 2026",
        ElectionType.FOLKETINGSVALG,
        election_day,
        (reported, waiting),
    )

    progress = election.counting_progress()
    found = election.get(PlaceType.OPSTILLINGSKREDS, "20")

    print(f"counted: {progress}")
    print(f"{found.name}: {found.parties[0].name} {found.parties[0].votes} votes")
    print(f"placeholder status: {waiting.status.name}, has_result={waiting.has_result}")


if __name__ == "__main__":
    main()
