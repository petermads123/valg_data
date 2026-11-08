"""Shared helpers for the dkvalg tests: fixture paths and small synthetic feeds.

The builders follow the real XML shape of DST's 2026 feeds, so a synthetic feed
exercises the same code path a downloaded one does. Datetimes are built only with
`datetime.fromisoformat`, as Ruff's DTZ rules require.
"""

import functools
import hashlib
import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from dkvalg.adapters.folketingsvalg import FeedRef
from dkvalg.errors import FeedError
from dkvalg.model import (
    Election,
    ElectionType,
    PartyResult,
    Place,
    PlaceType,
    Status,
)
from dkvalg.sources.capture import Recorder
from dkvalg.sources.directory import load_election
from dkvalg.sources.http_source import HttpResponse

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "folketingsvalg_2026"
EP_FIXTURES = ROOT / "tests" / "fixtures" / "ep_2024"
FA_2022_FIXTURES = ROOT / "tests" / "fixtures" / "folkeafstemning_2022"
FA_2015_FIXTURES = ROOT / "tests" / "fixtures" / "folkeafstemning_2015"
FA_2009_FIXTURES = ROOT / "tests" / "fixtures" / "folkeafstemning_2009"
BOM = b"\xef\xbb\xbf"
ELECTION_NAME = "Folketingsvalg tirsdag 24. marts 2026"
EP_ELECTION_NAME = "Europa-Parlamentsvalg søndag  9. juni 2024"  # note the double space
# The Folkeafstemning names, copied verbatim from each valgdag.xml.
FA_2022_NAME = "Folkeafstemning onsdag  1. juni 2022"  # double space
FA_2015_NAME = "Folkeafstemning torsdag 3. december 2015"  # single space
FA_2009_NAME = "Folkeafstemning søndag  7. juni 2009"  # double space
FA_ELECTION_NAME = FA_2022_NAME

PARTIES_XML = (
    '<Parti Id="5891" Bogstav="A" Navn="A. Socialdemokratiet" StemmerAntal="600" '
    'StemmerPct="60.0" />\n'
    '<Parti Id="5893" Bogstav="B" Navn="B. Radikale Venstre" StemmerAntal="390" '
    'StemmerPct="39.0" />\n'
    '<Parti Id="" Navn="Uden for partier" StemmerAntal="10" StemmerPct="1.0" />\n'
    "<IAltGyldigeStemmer>1000</IAltGyldigeStemmer>\n"
    "<BlankeStemmer>5</BlankeStemmer>\n"
    "<AndreUgyldigeStemmer>2</AndreUgyldigeStemmer>\n"
    "<IAltUgyldigeStemmer>7</IAltUgyldigeStemmer>\n"
    "<IAltAfgivneStemmer>1007</IAltAfgivneStemmer>\n"
)


def dt(text: str) -> datetime:
    """Build a naive datetime from ISO text."""
    return datetime.fromisoformat(text)


def feed_xml(
    *,
    status: str | None = "1",
    status_text: str = "Foreløbigt resultat",
    senest: str | None = "24-03-2026 22:00:00",
    iso: str | None = "2026-03-24T22:00:00",
    stemmer: str | None = PARTIES_XML,
    eligible: str | None = "1200",
    turnout: str | None = "83.9",
    bom: bool = True,
    root_tag: str = "Data",
) -> bytes:
    """Build one result feed in DST's shape; `None` omits the element or attribute."""
    kode = "" if status is None else f' Kode="{status}"'
    parts = [
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>',
        f"<{root_tag}>",
        f"<ValgNavn>{ELECTION_NAME}</ValgNavn>",
        "<ValgDato>24-03-2026</ValgDato>",
        '<Sted Id="20" Type="OpstKreds">1.Østerbro</Sted>',
    ]
    if senest is not None:
        parts.append(f"<SenestRettet>{senest}</SenestRettet>")
    if iso is not None:
        parts.append(f"<SenestRettetIso>{iso}</SenestRettetIso>")
    if status is not None or status_text:
        parts.append(f"<Status{kode}>{status_text}</Status>")
    if eligible is not None:
        parts.append(f"<Stemmeberettigede>{eligible}</Stemmeberettigede>")
    if turnout is not None:
        parts.append(f"<DeltagelsePct>{turnout}</DeltagelsePct>")
    if stemmer is not None:
        parts.append(f"<Stemmer>{stemmer}</Stemmer>")
    parts.append(f"</{root_tag}>")
    data = "\n".join(parts).encode("utf-8")
    return BOM + data if bom else data


def entry(
    tag: str,
    name: str,
    file_name: str | None,
    *,
    senest: str | None = "24-03-2026 22:00:00",
    iso: str | None = "2026-03-24T22:00:00",
    **attributes: str,
) -> str:
    """Build one overview entry such as `<Opstillingskreds ...>name</...>`."""
    attrs = dict(attributes)
    if senest is not None:
        attrs["SenestRettet"] = senest
    if iso is not None:
        attrs["SenestRettetIso"] = iso
    if file_name is not None:
        attrs["filnavn"] = f"https://www.dst.dk/valg/x/xml/{file_name}"
    text = " ".join(f'{key}="{value}"' for key, value in attrs.items())
    return f"<{tag} {text}>{name}</{tag}>"


def overview_xml(
    entries: list[str],
    *,
    name: str | None = ELECTION_NAME,
    election_date: str | None = "24-03-2026",
    bom: bool = True,
) -> bytes:
    """Build a `valgdag.xml` around the given entries."""
    parts = ['<?xml version="1.0" encoding="utf-8" standalone="yes"?>', "<Data>"]
    if name is not None:
        parts.append(f"<ValgNavn>{name}</ValgNavn>")
    if election_date is not None:
        parts.append(f"<ValgDato>{election_date}</ValgDato>")
    parts.append("<Afstemningsomraader />")
    parts.extend(entries)
    parts.append("</Data>")
    data = "\n".join(parts).encode("utf-8")
    return BOM + data if bom else data


def kreds_entry(
    place_id: str,
    name: str,
    *,
    senest: str | None = "24-03-2026 22:00:00",
    iso: str | None = "2026-03-24T22:00:00",
) -> str:
    """An `Opstillingskreds` overview entry whose feed is `valgdag_<id>.xml`."""
    return entry(
        "Opstillingskreds",
        name,
        f"valgdag_{place_id}.xml",
        senest=senest,
        iso=iso,
        opstillingskreds_id=place_id,
        storkreds_id="10",
    )


def make_ref(
    place_id: str = "20",
    *,
    place_type: PlaceType = PlaceType.OPSTILLINGSKREDS,
    name: str = "1.Østerbro",
    parent_id: str | None = "10",
    last_changed: datetime | None = None,
    file_name: str | None = None,
) -> FeedRef:
    """Build a `FeedRef` with sensible defaults."""
    return FeedRef(
        place_type,
        place_id,
        name,
        parent_id,
        last_changed,
        file_name or f"valgdag_{place_id}.xml",
    )


def make_place(
    place_id: str = "20",
    *,
    place_type: PlaceType = PlaceType.OPSTILLINGSKREDS,
    name: str | None = None,
    status: Status = Status.PRELIMINARY,
    status_text: str = "Foreløbigt resultat",
    last_changed: datetime | None = None,
    parties: tuple[PartyResult, ...] | None = None,
) -> Place:
    """Build a `Place`; a place with a result gets one party and some figures."""
    if parties is None:
        parties = (PartyResult("5891", "A", "A. Socialdemokratiet", 600, 60.0),)
    reported = status.has_result
    return Place(
        place_type=place_type,
        place_id=place_id,
        name=name or f"Place {place_id}",
        parent_id="10",
        status=status,
        status_text=status_text,
        last_changed=last_changed,
        eligible_voters=1200 if reported else None,
        turnout_percent=83.9 if reported else None,
        valid_votes=1000 if reported else None,
        blank_votes=5 if reported else None,
        other_invalid_votes=2 if reported else None,
        total_invalid_votes=7 if reported else None,
        total_votes=1007 if reported else None,
        parties=parties if reported else (),
    )


def make_election(*places: Place) -> Election:
    """Build an `Election` around the given places."""
    return Election(
        "Folketingsvalg tirsdag 24. marts 2026",
        ElectionType.FOLKETINGSVALG,
        date.fromisoformat("2026-03-24"),
        tuple(places),
    )


def make_party(
    letter: str,
    votes: int,
    *,
    percent: float | None = None,
    seats: int | None = None,
    constituency_seats: int | None = None,
    supplementary_seats: int | None = None,
    party_id: str | None = None,
) -> PartyResult:
    """Build a `PartyResult`; the id defaults to one derived from the letter.

    An empty `letter` with no `party_id` gives "Uden for partier" (id `""`).
    """
    if party_id is None:
        party_id = f"id-{letter}" if letter else ""
    return PartyResult(
        party_id,
        letter,
        f"{letter}. Party" if letter else "Uden for partier",
        votes,
        votes / 10 if percent is None else percent,
        seats,
        constituency_seats,
        supplementary_seats,
    )


def make_fa_election(*places: Place) -> Election:
    """Build a Folkeafstemning (referendum) `Election` around the given places."""
    return Election(
        FA_2022_NAME,
        ElectionType.FOLKEAFSTEMNING,
        date.fromisoformat("2022-06-01"),
        tuple(places),
    )


def make_answer(
    letter: str, votes: int, *, percent: float | None = None
) -> PartyResult:
    """Build a referendum answer (`JA`, `NEJ`) as a `PartyResult` without seats."""
    return PartyResult(
        f"id-{letter}",
        letter,
        letter,
        votes,
        votes / 10 if percent is None else percent,
    )


def make_ep_election(*places: Place) -> Election:
    """Build a Europa-Parlamentsvalg `Election` around the given places."""
    return Election(
        EP_ELECTION_NAME,
        ElectionType.EUROPAPARLAMENTSVALG,
        date.fromisoformat("2024-06-09"),
        tuple(places),
    )


def write_directory(
    directory: Path, overview: bytes, feeds: dict[str, bytes] | None = None
) -> Path:
    """Write `valgdag.xml` and feed files into `directory`, returning it."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "valgdag.xml").write_bytes(overview)
    for file_name, data in (feeds or {}).items():
        (directory / file_name).write_bytes(data)
    return directory


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    """The unmodified 2026 fixture directory (read-only: never write into it)."""
    assert FIXTURES.is_dir(), f"fixtures missing at {FIXTURES}"
    return FIXTURES


@pytest.fixture
def fixture_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the fixture directory that a test may damage."""
    target = tmp_path / "copy"
    shutil.copytree(FIXTURES, target)
    return target


@pytest.fixture(scope="session")
def election(fixture_dir: Path) -> Election:
    """The fixture set loaded once; immutable, so sharing it is safe."""
    return load_election(fixture_dir)


@pytest.fixture(scope="session")
def ep_fixture_dir() -> Path:
    """The unmodified 2024 Europa-Parlamentsvalg fixtures (read-only)."""
    assert EP_FIXTURES.is_dir(), f"fixtures missing at {EP_FIXTURES}"
    return EP_FIXTURES


@pytest.fixture
def ep_fixture_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the EP fixture directory that a test may damage."""
    target = tmp_path / "ep_copy"
    shutil.copytree(EP_FIXTURES, target)
    return target


@pytest.fixture(scope="session")
def ep_election(ep_fixture_dir: Path) -> Election:
    """The EP fixture set loaded once; immutable, so sharing it is safe."""
    return load_election(ep_fixture_dir)


@pytest.fixture(scope="session")
def fa_2022_dir() -> Path:
    """The unmodified 2022 Folkeafstemning fixtures (read-only)."""
    assert FA_2022_FIXTURES.is_dir(), f"fixtures missing at {FA_2022_FIXTURES}"
    return FA_2022_FIXTURES


@pytest.fixture(scope="session")
def fa_2015_dir() -> Path:
    """The unmodified 2015 Folkeafstemning fixtures (read-only)."""
    assert FA_2015_FIXTURES.is_dir(), f"fixtures missing at {FA_2015_FIXTURES}"
    return FA_2015_FIXTURES


@pytest.fixture(scope="session")
def fa_2009_dir() -> Path:
    """The unmodified 2009 Folkeafstemning fixtures (read-only)."""
    assert FA_2009_FIXTURES.is_dir(), f"fixtures missing at {FA_2009_FIXTURES}"
    return FA_2009_FIXTURES


@pytest.fixture
def fa_2022_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the 2022 referendum directory a test may damage."""
    target = tmp_path / "fa_copy"
    shutil.copytree(FA_2022_FIXTURES, target)
    return target


@pytest.fixture(scope="session")
def fa_2022(fa_2022_dir: Path) -> Election:
    """The 2022 referendum loaded once; immutable, so sharing it is safe."""
    return load_election(fa_2022_dir)


@pytest.fixture(scope="session")
def fa_2015(fa_2015_dir: Path) -> Election:
    """The 2015 referendum loaded once."""
    return load_election(fa_2015_dir)


@pytest.fixture(scope="session")
def fa_2009(fa_2009_dir: Path) -> Election:
    """The 2009 referendum (94 opstillingskredse) loaded once."""
    return load_election(fa_2009_dir)


# --- live polling helpers: a fake transport, a fake clock, feed mutations -------

BASE_URL = "https://www.dst.dk/valg/Valg2546527/xml/"
EP_BASE_URL = "https://www.dst.dk/valg/Valg2546524/xml/"
FA_2022_BASE_URL = "https://www.dst.dk/valg/Valg1962294/xml/"
FA_2015_BASE_URL = "https://www.dst.dk/valg/Valg1664255/xml/"
FA_2009_BASE_URL = "https://www.dst.dk/valg/Valg1191213/xml/"
OVERVIEW = "valgdag.xml"
NATIONAL = "valgdag_0.xml"
LATER_ISO = "2026-03-25T01:00:00"  # after every timestamp in the 2026 fixtures


@functools.cache
def _fixture_bytes() -> tuple[tuple[str, bytes], ...]:
    """Every fixture XML file as (name, bytes), read once per session."""
    return tuple((p.name, p.read_bytes()) for p in sorted(FIXTURES.glob("*.xml")))


def fixture_files() -> dict[str, bytes]:
    """A fresh dict of the 109 fixture files by name, free to mutate."""
    return dict(_fixture_bytes())


def ep_fixture_files() -> dict[str, bytes]:
    """A fresh dict of the 109 EP fixture files by name, free to mutate."""
    return {p.name: p.read_bytes() for p in sorted(EP_FIXTURES.glob("*.xml"))}


def fa_fixture_files(directory: Path = FA_2022_FIXTURES) -> dict[str, bytes]:
    """A fresh dict of a referendum set's XML files by name (2022 by default)."""
    return {p.name: p.read_bytes() for p in sorted(directory.glob("*.xml"))}


def dst_stamp(iso: str) -> str:
    """Spell an ISO timestamp the way DST's `SenestRettet` does."""
    return datetime.fromisoformat(iso).strftime("%d-%m-%Y %H:%M:%S")


def retime_feed(body: bytes, iso: str) -> bytes:
    """Rewrite a result feed's own `SenestRettet` and `SenestRettetIso`."""
    text = body.decode("utf-8")
    text = re.sub(
        r"<SenestRettetIso>[^<]*</SenestRettetIso>",
        f"<SenestRettetIso>{iso}</SenestRettetIso>",
        text,
        count=1,
    )
    text = re.sub(
        r"<SenestRettet>[^<]*</SenestRettet>",
        f"<SenestRettet>{dst_stamp(iso)}</SenestRettet>",
        text,
        count=1,
    )
    return text.encode("utf-8")


def bump_votes(body: bytes) -> bytes:
    """Add one to the feed's `IAltGyldigeStemmer`, so its figures differ."""
    text = body.decode("utf-8")
    text = re.sub(
        r"<IAltGyldigeStemmer>(\d+)</IAltGyldigeStemmer>",
        lambda m: f"<IAltGyldigeStemmer>{int(m.group(1)) + 1}</IAltGyldigeStemmer>",
        text,
        count=1,
    )
    return text.encode("utf-8")


def retime_overview(
    overview: bytes, file_name: str, iso: str, senest: str = ""
) -> bytes:
    """Rewrite the two timestamp attributes of the overview entry for `file_name`.

    `senest` overrides the `SenestRettet` spelling (used for "never" in DST's form).
    """
    lines = overview.decode("utf-8").split("\n")
    marker = f'/{file_name}"'
    hits = 0
    for index, line in enumerate(lines):
        if marker in line and "SenestRettetIso=" in line:
            line = re.sub(r'SenestRettetIso="[^"]*"', f'SenestRettetIso="{iso}"', line)
            line = re.sub(
                r'SenestRettet="[^"]*"',
                f'SenestRettet="{senest or dst_stamp(iso)}"',
                line,
            )
            lines[index] = line
            hits += 1
    assert hits >= 1, f"no overview entry for {file_name}"
    return "\n".join(lines).encode("utf-8")


@dataclass(frozen=True)
class Request:
    """One request a `FakeTransport` saw."""

    url: str
    name: str
    headers: Mapping[str, str]
    timeout: float

    @property
    def conditional(self) -> bool:
        """Whether the request carried a validator."""
        return "If-None-Match" in self.headers or "If-Modified-Since" in self.headers


class FakeTransport:
    """A `Transport` serving feeds from memory the way DST's servers behave.

    Every file has an ETag (a hash of its body) and a Last-Modified (a counter
    that moves when its body changes). A request whose `If-None-Match` matches, or
    that has no `If-None-Match` and whose `If-Modified-Since` matches, gets a 304.
    With `vary_etag` every response carries a fresh ETag, so an ETag never matches
    (DST's nodes do this) and only the body comparison can see "unchanged".
    Outcomes queued with `script` are served first, once each, per file name.
    """

    def __init__(
        self,
        files: Mapping[str, bytes] | None = None,
        *,
        vary_etag: bool = False,
        base_url: str = BASE_URL,
    ) -> None:
        """Serve `files` (the 2026 fixtures by default) under `base_url`."""
        self.files: dict[str, bytes] = fixture_files() if files is None else dict(files)
        self.vary_etag = vary_etag
        self.base_url = base_url
        self.requests: list[Request] = []
        self.responses: list[HttpResponse] = []
        self._revision: dict[str, int] = dict.fromkeys(self.files, 1)
        self._scripted: dict[str, list[HttpResponse | Exception]] = {}
        self._served = 0

    @property
    def names(self) -> list[str]:
        """The file names requested so far, in order."""
        return [request.name for request in self.requests]

    def publish(self, name: str, body: bytes) -> None:
        """Replace a file; its Last-Modified moves only if the body changed."""
        if self.files.get(name) != body:
            self._revision[name] = self._revision.get(name, 0) + 1
        self.files[name] = body

    def touch(
        self, names: Iterable[str], iso: str = LATER_ISO, *, bump: bool = True
    ) -> None:
        """Re-report feeds: new figures (if `bump`), new timestamps, in feed and overview."""
        for name in names:
            body = self.files[name]
            body = bump_votes(body) if bump else body
            self.publish(name, retime_feed(body, iso))
            self.publish(OVERVIEW, retime_overview(self.files[OVERVIEW], name, iso))

    def retime_only(self, names: Iterable[str], iso: str = LATER_ISO) -> None:
        """Move only the overview timestamps; the feed bodies stay byte-identical."""
        for name in names:
            self.publish(OVERVIEW, retime_overview(self.files[OVERVIEW], name, iso))

    def never_reported(self, name: str) -> None:
        """Make the overview list a feed as never reported."""
        self.publish(
            OVERVIEW,
            retime_overview(
                self.files[OVERVIEW], name, "0001-01-01T00:00:00", "01-01-0001 00:00:00"
            ),
        )

    def script(self, name: str, *outcomes: HttpResponse | Exception) -> None:
        """Queue outcomes for `name`: a response is returned, an exception raised."""
        self._scripted.setdefault(name, []).extend(outcomes)

    def write_to(self, directory: Path) -> Path:
        """Write the current files into a directory, for `load_election`."""
        directory.mkdir(parents=True, exist_ok=True)
        for name, body in self.files.items():
            (directory / name).write_bytes(body)
        return directory

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        """Answer one request, logging the request and the response."""
        response = self._answer(url, headers, timeout)
        self.responses.append(response)
        return response

    def _answer(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        """Decide the response to one request."""
        name = url.rsplit("/", 1)[-1]
        self.requests.append(Request(url, name, dict(headers), timeout))
        queue = self._scripted.get(name)
        if queue:
            outcome = queue.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        if not url.startswith(self.base_url) or name not in self.files:
            return HttpResponse(404, {}, b"")
        body = self.files[name]
        self._served += 1
        digest = hashlib.sha1(body).hexdigest()[:10]
        etag = f'"{digest}-{self._served}"' if self.vary_etag else f'"{digest}"'
        modified = f"Tue, 24 Mar 2026 20:{self._revision[name] % 60:02d}:00 GMT"
        validators = {"etag": etag, "last-modified": modified}
        if "If-None-Match" in headers:
            unchanged = headers["If-None-Match"] == etag
        else:
            unchanged = headers.get("If-Modified-Since") == modified
        if unchanged:
            return HttpResponse(304, validators, b"")
        return HttpResponse(200, validators, body)


class FakeClock:
    """A strictly advancing timezone-aware clock: one step per call."""

    def __init__(
        self, start: str = "2026-03-24T20:00:00+00:00", step: float = 60.0
    ) -> None:
        """Start at `start`, advancing `step` seconds per call."""
        self._next = datetime.fromisoformat(start)
        self._step = timedelta(seconds=step)
        self.calls = 0

    def __call__(self) -> datetime:
        """Return the next time."""
        self.calls += 1
        now = self._next
        self._next = now + self._step
        return now


class FlakyRecorder(Recorder):
    """A recorder that raises `FeedError` on the calls numbered in `fail_on`."""

    def __init__(self, directory: Path, fail_on: Iterable[int]) -> None:
        """Record into `directory`, failing on the numbered calls (1-based)."""
        super().__init__(directory)
        self.fail_on = set(fail_on)
        self.calls: list[tuple[datetime, dict[str, bytes]]] = []

    def record(self, fetched_at: datetime, feeds: Mapping[str, bytes]) -> Path:
        """Record, or fail on the configured calls."""
        self.calls.append((fetched_at, dict(feeds)))
        if len(self.calls) in self.fail_on:
            raise FeedError("disk full (simulated)")
        return super().record(fetched_at, feeds)


def utc(text: str) -> datetime:
    """A timezone-aware UTC datetime from ISO text without an offset."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.fixture
def transport() -> FakeTransport:
    """A fake DST serving the 2026 fixtures."""
    return FakeTransport()


@pytest.fixture
def ep_transport() -> FakeTransport:
    """A fake DST serving the 2024 EP fixtures under their own election id."""
    return FakeTransport(ep_fixture_files(), base_url=EP_BASE_URL)


@pytest.fixture
def fa_transport() -> FakeTransport:
    """A fake DST serving the 2022 referendum under its own election id."""
    return FakeTransport(fa_fixture_files(FA_2022_FIXTURES), base_url=FA_2022_BASE_URL)


@pytest.fixture
def fa_2009_transport() -> FakeTransport:
    """A fake DST serving the 2009 referendum (no `SenestRettetIso`)."""
    return FakeTransport(fa_fixture_files(FA_2009_FIXTURES), base_url=FA_2009_BASE_URL)
