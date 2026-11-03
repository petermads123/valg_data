"""Replay a saved election through time, revealing each feed when it last changed."""

import math
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import date, datetime

from dkvalg.model import (
    CountingProgress,
    Election,
    ElectionType,
    Place,
    PlaceType,
    Status,
)


@dataclass(frozen=True, slots=True)
class ReplayStep:
    """One reveal.

    Attributes:
        at: The feed time at which the place appeared.
        place: The place that appeared, with its real figures.
        election: The snapshot after the reveal.
    """

    at: datetime
    place: Place
    election: Election

    @property
    def progress(self) -> CountingProgress:
        """Counting progress of the snapshot after this reveal."""
        return self.election.counting_progress()


class ReplaySource:
    """Replays an election: each place appears at its `last_changed`, in order.

    Places that have a `last_changed` start as placeholders and are revealed one
    per step, stable-sorted by time (ties keep overview order). Places without a
    `last_changed` are present unchanged from the start, so the final snapshot
    equals the election given.
    """

    def __init__(
        self,
        election: Election,
        *,
        speed: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Prepare a replay.

        Args:
            election: The finished election to replay.
            speed: Time compression: gaps between steps shrink by this factor.
                `math.inf` means no waiting.
            sleep: Called with the seconds to wait before a step.

        Raises:
            ValueError: If `speed` is not positive or is NaN.
        """
        if math.isnan(speed) or speed <= 0:
            raise ValueError(f"speed must be positive, got {speed}")
        self._election = election
        self._speed = speed
        self._sleep = sleep

    def initial(self) -> Election:
        """Return the election as it stands before anything is revealed.

        Returns:
            The election with every place that has a `last_changed` replaced by
            its placeholder.
        """
        places = tuple(
            p.unreported() if p.last_changed is not None else p
            for p in self._election.places
        )
        return replace(self._election, places=places)

    def __iter__(self) -> Iterator[ReplayStep]:
        """Yield one `ReplayStep` per place with a `last_changed`.

        Sleeps `gap_seconds / speed` before every step after the first, only
        when that is above zero. Iterating again restarts from the beginning.

        Yields:
            The steps in time order.
        """
        current = list(self.initial().places)
        timed = sorted(
            (
                (p.last_changed, i)
                for i, p in enumerate(self._election.places)
                if p.last_changed is not None
            ),
            key=lambda pair: pair[0],
        )
        previous: datetime | None = None
        for at, index in timed:
            place = self._election.places[index]
            if previous is not None:
                delay = (at - previous).total_seconds() / self._speed
                if delay > 0:
                    self._sleep(delay)
            previous = at
            current[index] = place
            snapshot = replace(self._election, places=tuple(current))
            yield ReplayStep(at=at, place=place, election=snapshot)


def main() -> None:
    """Showcase this module's functionality."""
    kreds_a = Place(
        PlaceType.OPSTILLINGSKREDS,
        "20",
        "1.Østerbro",
        "10",
        Status.PRELIMINARY,
        "Foreløbigt resultat",
        datetime.fromisoformat("2026-03-24T21:30:00"),
    )
    kreds_b = replace(
        kreds_a,
        place_id="21",
        name="2.Sundbyvester",
        last_changed=datetime.fromisoformat("2026-03-24T22:00:00"),
    )
    election = Election(
        "Folketingsvalg 2026",
        ElectionType.FOLKETINGSVALG,
        date.fromisoformat("2026-03-24"),
        (kreds_a, kreds_b),
    )
    speed = 600.0  # 600.0 compresses 30 minutes to 3 seconds; math.inf never waits
    waits: list[float] = []

    source = ReplaySource(election, speed=speed, sleep=waits.append)
    start = source.initial().counting_progress()
    steps = list(source)

    print(f"before: {start}")
    for step in steps:
        print(f"{step.at}: {step.place.name} -> {step.progress}")
    print(f"sleeps (seconds): {waits}")


if __name__ == "__main__":
    main()
