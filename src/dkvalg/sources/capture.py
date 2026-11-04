"""Record the feeds a poll receives and replay the recording with its true timing."""

import math
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dkvalg.errors import FeedError
from dkvalg.model import CountingProgress, Election, Place
from dkvalg.sources.directory import build_election

_OVERVIEW_NAME = "valgdag.xml"
_FEED_NAME = re.compile(r"[A-Za-z0-9_-]+\.xml")
_CAPTURE_NAME = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})\.(\d{6})Z")
_TEMP_PREFIX = ".tmp-"


def check_feed_name(name: str) -> str:
    """Check that a feed file name is safe to put in a URL and on the disk.

    Args:
        name: A file name taken from an overview's feed list.

    Returns:
        `name`, unchanged, when it is letters, digits, `_` and `-` followed by
        `.xml` and is not `valgdag.xml`.

    Raises:
        FeedError: If `name` is anything else; the message names it.
    """
    if _FEED_NAME.fullmatch(name) is None or name == _OVERVIEW_NAME:
        raise FeedError(f"unsafe feed file name {name!r}")
    return name


def _folder_name(fetched_at: datetime) -> str:
    """Name a capture folder for a timezone-aware time, in UTC."""
    return fetched_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def _folder_time(name: str, path: Path) -> datetime:
    """Parse a capture folder name into its UTC time, or raise `FeedError`."""
    match = _CAPTURE_NAME.fullmatch(name)
    if match is None:
        raise FeedError(f"{path}: not a capture folder name")
    year, month, day, hour, minute, second, micro = match.groups()
    text = f"{year}-{month}-{day}T{hour}:{minute}:{second}.{micro}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as error:
        raise FeedError(f"{path}: capture folder name is not a valid time") from error


class Recorder:
    """Writes each poll's received feed bodies into a capture directory.

    A capture is one subfolder per poll, named by the UTC fetch time and holding
    the feeds under their DST file names. A folder is written under a temporary
    name and renamed when complete, so a folder is either whole or absent.
    """

    def __init__(self, directory: Path) -> None:
        """Prepare a recorder.

        Args:
            directory: The capture directory; created, with parents, on the
                first `record`.
        """
        self._directory = directory

    def record(self, fetched_at: datetime, feeds: Mapping[str, bytes]) -> Path:
        """Write one capture folder.

        Args:
            fetched_at: When the poll fetched the feeds; timezone-aware.
            feeds: File name to body. `valgdag.xml` is allowed; every other name
                must pass `check_feed_name`.

        Returns:
            The folder written.

        Raises:
            ValueError: If `fetched_at` is naive or `feeds` is empty.
            FeedError: If a file name is unsafe, the target folder already exists
                or the disk refuses a write.
        """
        if fetched_at.tzinfo is None:
            raise ValueError(f"fetched_at must be timezone-aware, got {fetched_at}")
        if not feeds:
            raise ValueError("no feeds to record")
        for name in feeds:
            if name != _OVERVIEW_NAME:
                check_feed_name(name)
        folder_name = _folder_name(fetched_at)
        final = self._directory / folder_name
        temporary = self._directory / f"{_TEMP_PREFIX}{folder_name}"
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            if final.exists():
                raise FeedError(f"capture folder already exists: {final}")
            if temporary.exists():
                shutil.rmtree(temporary)
            temporary.mkdir()
            for name, body in feeds.items():
                (temporary / name).write_bytes(body)
            temporary.rename(final)
        except OSError as error:
            shutil.rmtree(temporary, ignore_errors=True)
            raise FeedError(f"cannot write capture {final}: {error}") from error
        return final


@dataclass(frozen=True, slots=True)
class CaptureStep:
    """One recorded poll replayed.

    Attributes:
        at: The recorded fetch time, timezone-aware UTC.
        changed: The places that differ from the previous step's election; every
            reported place on the first step.
        election: The snapshot after this poll.
    """

    at: datetime
    changed: tuple[Place, ...]
    election: Election

    @property
    def progress(self) -> CountingProgress:
        """Counting progress of the snapshot after this poll."""
        return self.election.counting_progress()


def _capture_folders(directory: Path) -> list[tuple[datetime, Path]]:
    """List the capture folders in time order, ignoring everything else."""
    try:
        entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
    except OSError as error:
        raise FeedError(
            f"cannot read capture directory {directory}: {error}"
        ) from error
    folders: list[tuple[datetime, Path]] = []
    for entry in entries:
        if _CAPTURE_NAME.fullmatch(entry.name) is None:
            continue
        if not entry.is_dir():
            raise FeedError(f"{entry}: capture entry is not a directory")
        folders.append((_folder_time(entry.name, entry), entry))
    return folders


def _read_folder(folder: Path) -> dict[str, bytes]:
    """Read the feed files of one capture folder; other files are ignored."""
    bodies: dict[str, bytes] = {}
    try:
        for entry in sorted(folder.iterdir(), key=lambda item: item.name):
            valid = entry.name == _OVERVIEW_NAME or (
                _FEED_NAME.fullmatch(entry.name) is not None
            )
            if valid and entry.is_file():
                bodies[entry.name] = entry.read_bytes()
    except OSError as error:
        raise FeedError(f"cannot read capture {folder}: {error}") from error
    return bodies


class CaptureReplay:
    """Replays a capture directory: one snapshot per recorded poll.

    Folders are replayed in name (fetch-time) order. Files accumulate, a later
    folder's file replacing an earlier one's, and each step is built from the
    accumulated files exactly as `load_election` builds an election from a
    directory. The first folder must hold the overview and every reported feed.
    """

    def __init__(
        self,
        directory: Path,
        *,
        speed: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Prepare a replay.

        Args:
            directory: A capture directory written by `Recorder`.
            speed: Time compression: gaps between fetch times shrink by this
                factor. `math.inf` means no waiting.
            sleep: Called with the seconds to wait before a step.

        Raises:
            ValueError: If `speed` is not positive or is NaN.
        """
        if math.isnan(speed) or speed <= 0:
            raise ValueError(f"speed must be positive, got {speed}")
        self._directory = directory
        self._speed = speed
        self._sleep = sleep

    def __iter__(self) -> Iterator[CaptureStep]:
        """Yield one `CaptureStep` per capture folder, in fetch-time order.

        Sleeps `gap_seconds / speed` before every step after the first, only when
        that is above zero. The directory is read when iteration starts and the
        bodies one step at a time; iterating again restarts.

        Yields:
            The steps in time order.

        Raises:
            FeedError: If the directory cannot be read or holds no captures, a
                capture-like entry is not a directory or not a valid UTC time, or
                a folder leaves the election incomplete or malformed.
        """
        folders = _capture_folders(self._directory)
        if not folders:
            raise FeedError(f"no captures in {self._directory}")
        files: dict[str, bytes] = {}
        previous: Election | None = None
        previous_at: datetime | None = None
        for at, folder in folders:
            if previous_at is not None and not math.isinf(self._speed):
                delay = (at - previous_at).total_seconds() / self._speed
                if delay > 0:
                    self._sleep(delay)
            files.update(_read_folder(folder))
            election = _assemble(files, folder)
            yield CaptureStep(
                at=at, changed=election.changed_since(previous), election=election
            )
            previous = election
            previous_at = at


def _assemble(files: Mapping[str, bytes], folder: Path) -> Election:
    """Build an election from accumulated files, naming `folder` on a gap."""
    if _OVERVIEW_NAME not in files:
        raise FeedError(f"{folder}: no {_OVERVIEW_NAME} in this or an earlier capture")

    def read_feed(name: str) -> bytes:
        if name not in files:
            raise FeedError(f"{folder}: feed {name} is in no capture up to here")
        return files[name]

    return build_election(files[_OVERVIEW_NAME], read_feed)


def is_capture_directory(directory: Path) -> bool:
    """Tell a capture directory from a plain feed directory.

    Args:
        directory: A directory.

    Returns:
        True if it has no `valgdag.xml` and at least one subfolder named like a
        capture (`YYYYMMDDTHHMMSS.ffffffZ`); False otherwise, also when the
        directory cannot be read.
    """
    try:
        if (directory / _OVERVIEW_NAME).exists():
            return False
        return any(
            _CAPTURE_NAME.fullmatch(entry.name) is not None and entry.is_dir()
            for entry in directory.iterdir()
        )
    except OSError:
        return False


def main() -> None:
    """Showcase this module's functionality."""
    fixtures = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "folketingsvalg_2026"
    )
    if not fixtures.is_dir():
        print(f"fixtures not found at {fixtures}; run from a repository checkout")
        return
    first_poll = datetime.fromisoformat("2026-03-24T20:30:00+00:00")
    second_poll = datetime.fromisoformat("2026-03-24T20:32:00+00:00")
    overview = (fixtures / _OVERVIEW_NAME).read_bytes()
    first_feeds = {path.name: path.read_bytes() for path in fixtures.glob("*.xml")}
    second_feeds = {_OVERVIEW_NAME: overview}  # an unchanged overview: nothing new
    speed = 60.0  # 60.0 turns a two minute gap into 2 seconds; math.inf never waits
    waits: list[float] = []

    with tempfile.TemporaryDirectory() as scratch:
        directory = Path(scratch) / "capture"
        recorder = Recorder(directory)
        recorder.record(first_poll, first_feeds)
        recorder.record(second_poll, second_feeds)
        is_capture = is_capture_directory(directory)
        replay = CaptureReplay(directory, speed=speed, sleep=waits.append)
        steps = list(replay)

    print(f"capture directory: {is_capture}")
    for step in steps:
        print(f"{step.at.isoformat()}: {len(step.changed)} changed, {step.progress}")
    print(f"sleeps (seconds): {waits}")

    # A feed name that could escape the capture directory is refused.
    name = "../outside.xml"
    try:
        check_feed_name(name)
    except FeedError as error:
        print(f"error: {error}")


if __name__ == "__main__":
    main()
