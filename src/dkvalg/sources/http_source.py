"""Poll DST's election feeds over HTTPS into `Election` snapshots."""

import http.client
import importlib.metadata
import math
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Final, Protocol
from urllib.parse import urlsplit

from dkvalg.adapters.registry import parse_any_overview
from dkvalg.errors import FeedError, FetchError
from dkvalg.model import Election, Place
from dkvalg.sources.capture import Recorder, check_feed_name
from dkvalg.sources.directory import build_election

DEFAULT_INTERVAL: Final[float] = 60.0
MIN_INTERVAL: Final[float] = 15.0
MAX_BACKOFF: Final[float] = 300.0

_OVERVIEW_NAME = "valgdag.xml"
_MAX_BODY = 10_000_000
_REPOSITORY = "https://github.com/petermads123/valg_data"
_DST_FOLDER = "https://www.dst.dk/valg/{election_id}/xml/"
_ID_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """One HTTP response.

    Attributes:
        status: The HTTP status code.
        headers: The response headers, names lower-case.
        body: The response body.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    """What `HttpSource` needs from HTTP: one GET that returns every status."""

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        """GET `url`; a 304 and any other status are returned, not raised.

        Args:
            url: The address to fetch.
            headers: Request headers to send.
            timeout: Seconds to wait for the server.

        Returns:
            The response.

        Raises:
            FetchError: If the request fails before a response arrives.
        """
        ...


def _read_body(
    stream: IO[bytes], url: str, status: int, headers: Mapping[str, str]
) -> bytes:
    """Read a response body under the size cap and check it against Content-Length.

    `http.client` returns a short read without raising when the server closes the
    connection early and the caller asked for a limited number of bytes, so the
    declared length is compared here. A 204 or 304 carries no body whatever the
    header says.
    """
    body = stream.read(_MAX_BODY + 1)
    if len(body) > _MAX_BODY:
        raise FetchError(f"{url}: response body is over {_MAX_BODY} bytes")
    declared = headers.get("content-length", "").strip()
    if (
        status not in (204, 304)
        and declared.isascii()
        and declared.isdigit()
        and len(body) != int(declared)
    ):
        raise FetchError(
            f"{url}: body is {len(body)} bytes, Content-Length said {declared}"
        )
    return body


def urllib_transport(
    url: str, headers: Mapping[str, str], timeout: float
) -> HttpResponse:
    """Fetch a URL with `urllib.request`; the default `Transport`.

    Args:
        url: The address to fetch.
        headers: Request headers to send.
        timeout: Seconds to wait for the server.

    Returns:
        The response; a 304 or a 5xx is returned like a 200.

    Raises:
        FetchError: If the connection fails, times out, the body is truncated or
            is over 10 MB; the message names the URL.
    """
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = int(response.status)
                received = {k.lower(): v for k, v in response.headers.items()}
                body = _read_body(response, url, status, received)
        except urllib.error.HTTPError as error:
            with error:
                status = error.code
                received = {k.lower(): v for k, v in error.headers.items()}
                body = _read_body(error, url, status, received)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        raise FetchError(f"{url}: {error}") from error
    return HttpResponse(status=status, headers=received, body=body)


def user_agent() -> str:
    """Return the User-Agent this library sends.

    Returns:
        `dkvalg/<installed version> (+https://github.com/petermads123/valg_data)`;
        the version reads `unknown` when the package metadata is not installed.
    """
    try:
        version = importlib.metadata.version("dkvalg")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return f"dkvalg/{version} (+{_REPOSITORY})"


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=UTC)


def overview_url(location: str) -> str:
    """Turn a location into the URL of an election's `valgdag.xml`.

    Args:
        location: A DST election id such as `Valg2546527`, the URL of the folder
            holding `valgdag.xml`, or the URL of `valgdag.xml` itself.

    Returns:
        The overview URL.

    Raises:
        ValueError: If `location` is none of these, its scheme is not http or
            https, or it carries credentials, a bad port, a query, a fragment, a
            non-ASCII character, whitespace or a control character; the message
            names the value. A trailing slash after `valgdag.xml`, and any case of
            that name, is normalised to `valgdag.xml`.
    """
    message = f"location must be an election id or an http(s) URL, got {location!r}"
    if not location.isascii() or any(
        character.isspace() or not character.isprintable() for character in location
    ):
        raise ValueError(message)
    if all(character in _ID_CHARACTERS for character in location) and location:
        return _DST_FOLDER.format(election_id=location) + _OVERVIEW_NAME
    parts = urlsplit(location)
    try:
        port_ok = parts.port is None or parts.port > 0
    except ValueError:
        port_ok = False
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or "@" in parts.netloc
        or not port_ok
        or parts.query
        or parts.fragment
    ):
        raise ValueError(message)
    folder = location.rstrip("/")
    last = folder.rsplit("/", 1)[-1]
    if last.lower() == _OVERVIEW_NAME and parts.path.rstrip("/") != "":
        return folder[: -len(last)] + _OVERVIEW_NAME
    return folder + "/" + _OVERVIEW_NAME


@dataclass(frozen=True, slots=True)
class FetchResult:
    """One successful fetch.

    Attributes:
        election: The election as of this fetch.
        changed: The places that differ from the previous fetch's election; every
            reported place on the first fetch.
        fetched_at: The source's clock when the fetch started.
    """

    election: Election
    changed: tuple[Place, ...]
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class _Held:
    """A result feed the source has accepted."""

    last_changed: datetime
    body: bytes
    etag: str | None
    last_modified: str | None


def _validators(response: HttpResponse) -> tuple[str | None, str | None]:
    """Pick the ETag and Last-Modified validators out of a response; empty is None."""
    etag = response.headers.get("etag") or None
    last_modified = response.headers.get("last-modified") or None
    return etag, last_modified


class HttpSource:
    """A blocking source that polls DST over HTTP.

    It keeps the accepted body of the overview and of every reported feed, with
    their validators, and builds each `Election` from those bodies with
    `build_election`, so it agrees with `load_election` on the same files. A fetch
    is atomic: it builds its result, writes the capture, and only then commits its
    state, so any failure leaves the last good election in place. Calls are
    serialised by a lock, so it may be driven from a thread.
    """

    def __init__(
        self,
        location: str,
        *,
        transport: Transport = urllib_transport,
        recorder: Recorder | None = None,
        timeout: float = 20.0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Prepare a source; nothing is fetched yet.

        Args:
            location: An election id, a folder URL or a `valgdag.xml` URL.
            transport: How to GET; replace it to test without a network.
            recorder: Where to write every 200 body a fetch receives, or None.
            timeout: Seconds to wait for the server on each request.
            clock: Returns the current timezone-aware time.

        Raises:
            ValueError: If `location` is not usable or `timeout` is not finite
                and positive.
        """
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(f"timeout must be finite and positive, got {timeout}")
        self._overview_url = overview_url(location)
        self._folder_url = self._overview_url[: -len(_OVERVIEW_NAME)]
        self._transport = transport
        self._recorder = recorder
        self._timeout = timeout
        self._clock = clock
        self._lock = threading.Lock()
        self._election: Election | None = None
        self._overview_body: bytes | None = None
        self._overview_validators: tuple[str | None, str | None] = (None, None)
        self._held: dict[str, _Held] = {}

    @property
    def election(self) -> Election | None:
        """The last good election, or None before the first successful fetch."""
        return self._election

    @property
    def clock(self) -> Callable[[], datetime]:
        """The clock this source stamps fetches with."""
        return self._clock

    def _get(self, url: str, validators: tuple[str | None, str | None]) -> HttpResponse:
        """GET one URL, conditionally; only 200 and 304 are returned."""
        headers = {"User-Agent": user_agent(), "Accept": "text/xml"}
        etag, last_modified = validators
        if etag is not None:
            headers["If-None-Match"] = etag
        if last_modified is not None:
            headers["If-Modified-Since"] = last_modified
        response = self._transport(url, headers, self._timeout)
        if response.status not in (200, 304):
            raise FetchError(f"{url}: HTTP status {response.status}")
        return response

    def fetch(self) -> FetchResult:
        """Fetch the overview and whichever feeds it says are newer.

        The first fetch holds nothing and requests everything. Later ones send the
        previous `ETag` and `Last-Modified` and request only feeds whose overview
        timestamp moved. A 304, or a 200 whose body is byte-identical to the held
        one, counts as no change.

        Returns:
            The election, the places that changed and the fetch time.

        Raises:
            FetchError: On a network error, a timeout, an oversize body or an
                HTTP status other than 200 and 304.
            FeedError: If a body is malformed or not a supported election type, a listed
                feed name is unsafe, or the capture cannot be written. The last
                good election and the held bodies are left untouched.
        """
        with self._lock:
            return self._fetch(self._clock())

    def _fetch_at(self, fetched_at: datetime) -> FetchResult:
        """Fetch with a time the caller already read, so a cycle reads the clock once."""
        with self._lock:
            return self._fetch(fetched_at)

    def _fetch(self, fetched_at: datetime) -> FetchResult:
        """Do one fetch stamped `fetched_at`; the caller holds the lock."""
        held_overview = self._overview_body
        held_election = self._election
        response = self._get(self._overview_url, self._overview_validators)
        if response.status == 304:
            if held_election is None:
                raise FetchError(f"{self._overview_url}: 304 with nothing held")
            return FetchResult(held_election, (), fetched_at)
        overview_body = response.body
        received: dict[str, bytes] = {_OVERVIEW_NAME: overview_body}
        validators = _validators(response)
        if held_election is not None and overview_body == held_overview:
            if self._recorder is not None:
                self._recorder.record(fetched_at, received)
            self._overview_validators = validators
            return FetchResult(held_election, (), fetched_at)

        overview = parse_any_overview(overview_body)
        for ref in overview.feeds:
            check_feed_name(ref.file_name)
        accepted: dict[str, _Held] = {}
        for ref in overview.feeds:
            if ref.last_changed is None:
                continue
            name = ref.file_name
            held = self._held.get(name)
            if held is not None and held.last_changed == ref.last_changed:
                accepted[name] = held
                continue
            feed = self._get_feed(self._folder_url + name, held)
            if feed.status == 304:
                if held is None:
                    raise FetchError(
                        f"{self._folder_url + name}: 304 with nothing held"
                    )
                accepted[name] = replace(held, last_changed=ref.last_changed)
                continue
            received[name] = feed.body
            etag, last_modified = _validators(feed)
            if held is not None and feed.body == held.body:
                accepted[name] = replace(
                    held,
                    last_changed=ref.last_changed,
                    etag=etag,
                    last_modified=last_modified,
                )
            else:
                accepted[name] = _Held(ref.last_changed, feed.body, etag, last_modified)

        election = build_election(overview_body, lambda name: accepted[name].body)
        changed = election.changed_since(held_election)
        if self._recorder is not None:
            self._recorder.record(fetched_at, received)
        self._election = election
        self._overview_body = overview_body
        self._overview_validators = validators
        self._held = accepted
        return FetchResult(election, changed, fetched_at)

    def _get_feed(self, url: str, held: _Held | None) -> HttpResponse:
        """GET a result feed, conditionally on what is held for it."""
        if held is None:
            return self._get(url, (None, None))
        return self._get(url, (held.etag, held.last_modified))


@dataclass(frozen=True, slots=True)
class PollCycle:
    """One cycle of the poll loop.

    Attributes:
        number: 1 for the first cycle, counting up.
        at: The source's clock at the start of the cycle: one read, which is also
            the fetch time and the name of the capture folder.
        election: The last good election; None before the first success.
        changed: The places that changed in this cycle; empty after an error.
        error: The failure of this cycle, or None.
        wait: The seconds slept before the next cycle.
    """

    number: int
    at: datetime
    election: Election | None
    changed: tuple[Place, ...]
    error: FeedError | None
    wait: float


def _cycles(
    source: HttpSource,
    interval: float,
    max_cycles: int | None,
    stop: Callable[[], bool] | None,
    sleep: Callable[[float], None],
) -> Iterator[PollCycle]:
    """Run the loop `poll` validated."""
    previous_wait = interval
    number = 0
    while True:
        number += 1
        at = source.clock()
        try:
            result = source._fetch_at(at)
        except FeedError as error:
            wait = min(previous_wait * 2, max(MAX_BACKOFF, interval))
            cycle = PollCycle(number, at, source.election, (), error, wait)
        else:
            wait = interval
            cycle = PollCycle(number, at, result.election, result.changed, None, wait)
        previous_wait = wait
        yield cycle
        if (stop is not None and stop()) or (
            max_cycles is not None and number >= max_cycles
        ):
            return
        sleep(wait)


def poll(
    source: HttpSource,
    *,
    interval: float = DEFAULT_INTERVAL,
    max_cycles: int | None = None,
    stop: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[PollCycle]:
    """Poll a source in a loop, one `PollCycle` per fetch.

    After a failed fetch the wait doubles each time up to 5 minutes (or the
    interval, if that is longer) and returns to `interval` after a success. The
    last good election is kept. Nothing sleeps after the last cycle.

    Args:
        source: The source to fetch from; each cycle is stamped with its clock.
        interval: Seconds between cycles, finite and at least `MIN_INTERVAL`.
        max_cycles: Stop after this many cycles; None for no limit.
        stop: Checked after each cycle; the loop ends when it returns true.
        sleep: Called with the seconds to wait between cycles.

    Returns:
        An iterator over the cycles.

    Raises:
        ValueError: At call time, if `interval` is not finite and at least
            `MIN_INTERVAL`, or `max_cycles` is below 1.
    """
    if (
        isinstance(interval, bool)
        or not math.isfinite(interval)
        or interval < MIN_INTERVAL
    ):
        raise ValueError(
            f"interval must be finite and at least {MIN_INTERVAL} seconds, "
            f"got {interval}"
        )
    if max_cycles is not None and (
        isinstance(max_cycles, bool)
        or not isinstance(max_cycles, int)
        or max_cycles < 1
    ):
        raise ValueError(
            f"max_cycles must be an integer of at least 1, got {max_cycles}"
        )
    return _cycles(source, interval, max_cycles, stop, sleep)


class _DirectoryTransport:
    """A fake transport serving a fixture directory; used by the showcase."""

    def __init__(self, directory: Path) -> None:
        """Serve the files in `directory`; ETags are the body sizes."""
        self._directory = directory
        self.requests: list[str] = []

    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        timeout: float,  # noqa: ARG002 - signature fixed by the Transport protocol
    ) -> HttpResponse:
        """Answer 200, or 304 when `If-None-Match` matches, or 404."""
        name = url.rsplit("/", 1)[-1]
        self.requests.append(name)
        path = self._directory / name
        if not path.is_file():
            return HttpResponse(404, {}, b"")
        body = path.read_bytes()
        etag = f'"{len(body)}"'
        if headers.get("If-None-Match") == etag:
            return HttpResponse(304, {"etag": etag}, b"")
        return HttpResponse(200, {"etag": etag}, body)


def main() -> None:
    """Showcase this module's functionality."""
    directory = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "folketingsvalg_2026"
    )
    if not directory.is_dir():
        print(f"fixtures not found at {directory}; run from a repository checkout")
        return
    location = "Valg2546527"  # an id, a folder URL or a valgdag.xml URL
    max_cycles = 2
    interval = 60.0  # at least 15.0
    transport = _DirectoryTransport(directory)
    waits: list[float] = []

    source = HttpSource(location, transport=transport)
    cycles = list(
        poll(source, interval=interval, max_cycles=max_cycles, sleep=waits.append)
    )

    print(f"overview url: {overview_url(location)}")
    print(f"user agent: {user_agent()}")
    for cycle in cycles:
        print(f"cycle {cycle.number}: {len(cycle.changed)} places changed")
    print(f"requests: {len(transport.requests)}, sleeps (seconds): {waits}")

    # An interval below the floor is refused before anything is fetched.
    interval = 5.0
    try:
        poll(source, interval=interval)
    except ValueError as error:
        print(f"error: {error}")


if __name__ == "__main__":
    main()
