"""dkvalg: Danish election data in one normalised model, with replay of saved feeds."""

from .errors import FeedError
from .model import (
    CountingProgress,
    Election,
    ElectionType,
    PartyResult,
    Place,
    PlaceType,
    Status,
)
from .sources.directory import load_election
from .sources.replay import ReplaySource, ReplayStep
