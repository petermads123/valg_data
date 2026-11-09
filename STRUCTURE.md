# Structure

The map of this repo: every module, and every public class and function with its signature
and return type. Read it before opening source files. `/finish` rewrites it from the code once
per feature; `check_sync.py` fails when a Python file under `src/`, `tests/` or
`.claude/hooks/` is missing from it or named here without existing. Private names (`_x`) stay
out.

The package has two subpackages; once this file grows unwieldy, keep the tree and one line per
subpackage here and move per-subpackage detail into `.claude/rules/structure-<subpackage>.md`
with `paths: ["src/dkvalg/<subpackage>/**"]` so it loads only when Claude works there.

## Tree

```
src/                    everything installable; nothing outside it is packaged
  dkvalg/               the package: model, diff, adapters, sources (files, HTTP, captures) and the CLI
docs/                   reference documents (DST's XML-feeds PDF)
tests/                  pytest suite, one test_<module>.py per module
  fixtures/             unmodified real DST feeds used as test data (Folketingsvalg 2026, EP 2024, Folkeafstemning 2022, 2015 and 2009)
development/            the pipeline's state: one folder per feature branch (see its README)
.claude/
  skills/               /feature, /fix, /round, /finish
  agents/               the pipeline's agents, one file each
  workflows/            diagnose.js (a fix's diagnosis), round.js (one round), final.js (the whole-feature check)
  hooks/                session brief, git guard, Ruff on edit, state reader, sync checker, test selector
  rules/python.md       coding conventions, loaded for **/*.py
.github/workflows/      CI: the gate and check_sync
.vscode/                editor config (Ruff as formatter, format on save)
pyproject.toml          packaging, Ruff, mypy and pytest configuration
DEVELOPMENT.md          development-side open questions and things to fix later (see CLAUDE.md)
README.md               human setup guide, with the version
DEVLOG.md               one entry per version, newest first
CLAUDE.md               routing map for Claude
STRUCTURE.md            this file
```

## Package: `src/dkvalg/`

Reads DST's Folketingsvalg, Europa-Parlamentsvalg and Folkeafstemning (referendum) XML feeds into one normalised, immutable
model, compares two snapshots (`diff`), polls them live over HTTP, records what a poll receives and replays a saved feed set or a recording through
time. Standard library only. Subpackages: `adapters/` (bytes in, model out: the shared `dst_feed`, a thin
module per election type and a `registry` choosing between them) and `sources/` (where an `Election` comes from: a directory, a time-scaled
replay of one, an HTTP poller, or a capture directory it recorded). Every `main()` is a showcase and runs standalone
with `python -m dkvalg.<module>` (`cli`'s is the entry point); the ones that read fixtures
locate them by a repo-relative path and say so outside a checkout.

### `src/dkvalg/__init__.py`

Re-exports the public API: `FeedError`, `ElectionType`, `PlaceType`, `Status`,
`PartyResult`, `Place`, `CountingProgress`, `Election`, `load_election`, `ReplaySource`,
`ReplayStep`, `FetchError`, `HttpSource`, `FetchResult`, `PollCycle`, `poll`, `Recorder`,
`CaptureReplay`, `CaptureStep`, `diff_elections`, `Change`, `PlaceCounted`,
`PartyResultChanged`, `LeaderChanged`, `StatusChanged`, `ProgressChanged`. Adapter internals
(`parse_*`, `parse_any_overview`, `parse_overview_for`, `election_name`, `unreported_place`, `FeedRef`, `Overview`), the transport pieces, `overview_url`, `user_agent`, `utc_now`, the interval
constants, `build_election`, `check_feed_name`, `is_capture_directory` and the CLI (`run`,
`main`) stay in their modules.

### `src/dkvalg/errors.py`

| Signature | Description |
|---|---|
| `class FeedError(Exception)` | A feed is missing, unreadable, malformed, or of an unsupported election type; the message names the file or value. |
| `class FetchError(FeedError)` | A request failed: network error, timeout, oversize body or an unexpected HTTP status; the message names the URL and the cause. |
| `main() -> None` | Showcase. |

### `src/dkvalg/model.py`

Normalised, immutable election model. Seat fields are `None` where DST gives none.

| Signature | Description |
|---|---|
| `class ElectionType(StrEnum)` | `FOLKETINGSVALG = "folketingsvalg"`, `EUROPAPARLAMENTSVALG = "europaparlamentsvalg"`, `FOLKEAFSTEMNING = "folkeafstemning"`. For a referendum the entries of `Place.parties` are the answers (letter `JA` or `NEJ`, no seats, no "Uden for partier"). |
| `class PlaceType(StrEnum)` | `COUNTRY`, `TALLY` (DST's seatless preliminary "optalling" total), `LANDSDEL`, `STORKREDS`, `OPSTILLINGSKREDS`. |
| `class Status(IntEnum)` | DST status code: `NOT_AVAILABLE` 0, `PRELIMINARY` 1, `ERROR` 9, `RECOUNT_PENDING` 10, `RECOUNT_PRELIMINARY` 11, `RECOUNT_FINAL` 12; property `has_result` (true for 1, 11, 12). |
| `@dataclass(frozen=True, slots=True) class PartyResult` | `party_id: str`, `letter: str`, `name: str`, `votes: int`, `percent: float`, `seats: int \| None = None`, `constituency_seats: int \| None = None`, `supplementary_seats: int \| None = None`; property `is_party` (false for "Uden for partier", `party_id == ""`). |
| `@dataclass(frozen=True, slots=True) class Place` | `place_type`, `place_id`, `name`, `parent_id`, `status`, `status_text`, `last_changed`, then optional `eligible_voters`, `turnout_percent`, `valid_votes`, `blank_votes`, `other_invalid_votes`, `total_invalid_votes`, `total_votes` and `parties: tuple[PartyResult, ...] = ()`; properties `has_result` and `leader -> PartyResult \| None` (the `is_party` party with most votes at a place with a result, ties to the earlier in the feed; `None` otherwise, and `None` when no party has more than 0 votes); `unreported() -> Place` gives the placeholder form. |
| `@dataclass(frozen=True, slots=True) class CountingProgress` | `counted: int`, `total: int`; `str` gives `"counted/total"`. |
| `@dataclass(frozen=True, slots=True) class Election` | `name`, `election_type`, `election_date`, `places`; `get(place_type, place_id) -> Place` (`KeyError` naming both), `of_type(place_type) -> tuple[Place, ...]`, `counting_progress() -> CountingProgress` (opstillingskredse with a result), `changed_since(previous: Election \| None) -> tuple[Place, ...]` (places with a `last_changed` that differ from, or are absent in, `previous`; all of them for `None`). |
| `main() -> None` | Showcase. |

### `src/dkvalg/adapters/__init__.py`

Package marker for per-election-type adapters.

### `src/dkvalg/adapters/dst_feed.py`

The election-type-independent parsing of DST's feeds, shared by the per-type adapters; no
I/O. Timestamps are naive Danish local time as served (a UTC offset is refused; "never" in
either spelling is None); a BOM is accepted; figures must be plain numbers (no `nan`, `inf`,
`1_000`). Both parsers refuse a document that declares a DOCTYPE or an entity (an `expat`
pre-scan, so UTF-16 is covered) with a `FeedError` naming the file, before `ElementTree`
expands anything. Seat attributes are optional, so a feed without them (EP, referenda) gives `None` seats.

| Signature | Description |
|---|---|
| `@dataclass(frozen=True, slots=True) class FeedRef` | `place_type`, `place_id`, `name`, `parent_id`, `last_changed: datetime \| None`, `file_name`: one feed as listed by the overview. |
| `@dataclass(frozen=True, slots=True) class Overview` | `name`, `election_type`, `election_date`, `feeds: tuple[FeedRef, ...]`. |
| `election_name(xml: bytes) -> str` | The stripped `ValgNavn` of an overview (hardened parse); `FeedError` for malformed XML, a DOCTYPE, or an absent or empty name (`valgdag.xml: no ValgNavn`). |
| `parse_overview_for(xml: bytes, election_type: ElectionType, name_prefix: str) -> Overview` | Parse `valgdag.xml` as `election_type` when `ValgNavn` starts with `name_prefix` (case-sensitive); otherwise `FeedError("valgdag.xml: not a <name_prefix>, ValgNavn is '<name>'")`; also `FeedError` when malformed, without a date, or listing no feeds. |
| `parse_place(xml: bytes, ref: FeedRef) -> Place` | Parse one result feed; status 0, 9 and others without a result give a figure-free place; `FeedError` on malformed XML, an unknown status code, a result status without `Stemmer`, a `Parti` without `Id`, or a non-numeric figure. |
| `unreported_place(ref: FeedRef) -> Place` | Placeholder for a feed the overview lists as never reported. |
| `main() -> None` | Showcase. |

### `src/dkvalg/adapters/folketingsvalg.py`

Thin adapter for Folketingsvalg feeds; re-exports `FeedRef`, `Overview`, `parse_place` and
`unreported_place` from `dst_feed` (`__all__`), so every existing import keeps working.

| Signature | Description |
|---|---|
| `parse_overview(xml: bytes) -> Overview` | `parse_overview_for(xml, ElectionType.FOLKETINGSVALG, "Folketingsvalg")`; `FeedError` when malformed, not a Folketingsvalg, or listing no feeds. |
| `main() -> None` | Showcase. |

### `src/dkvalg/adapters/europaparlamentsvalg.py`

Thin adapter for Europa-Parlamentsvalg feeds (same structure as Folketingsvalg, but no seat
attributes); re-exports the same four shared names.

| Signature | Description |
|---|---|
| `parse_overview(xml: bytes) -> Overview` | `parse_overview_for(xml, ElectionType.EUROPAPARLAMENTSVALG, "Europa-Parlamentsvalg")`. |
| `main() -> None` | Showcase (reads `tests/fixtures/ep_2024` by a repo-relative path). |

### `src/dkvalg/adapters/folkeafstemning.py`

Thin adapter for Folkeafstemning (referendum) feeds: the answers are `Parti` entries (`JA`,
`NEJ`), there are no seat attributes; re-exports the same four shared names.

| Signature | Description |
|---|---|
| `parse_overview(xml: bytes) -> Overview` | `parse_overview_for(xml, ElectionType.FOLKEAFSTEMNING, "Folkeafstemning")`; `FeedError` when malformed, not a Folkeafstemning, or listing no feeds. |
| `main() -> None` | Showcase (reads `tests/fixtures/folkeafstemning_2022` by a repo-relative path). |

### `src/dkvalg/adapters/registry.py`

| Signature | Description |
|---|---|
| `parse_any_overview(xml: bytes) -> Overview` | Read the name with `election_name` and call the matching adapter's `parse_overview`; any other name is `FeedError("valgdag.xml: not a supported election (Folketingsvalg, Europa-Parlamentsvalg, Folkeafstemning), ValgNavn is '<name>'")`. Used by `build_election` and `HttpSource`. |
| `main() -> None` | Showcase. |

### `src/dkvalg/sources/__init__.py`

Package marker for sources.

### `src/dkvalg/sources/directory.py`

| Signature | Description |
|---|---|
| `build_election(overview_xml: bytes, read_feed: Callable[[str], bytes]) -> Election` | `parse_any_overview` (which picks the adapter from `ValgNavn`), then `parse_place` of `read_feed(file_name)` for every reported feed and a placeholder for the rest; `FeedError` for an unsupported election type; the one assembly shared by `load_election`, `HttpSource` and `CaptureReplay`. |
| `load_election(directory: Path) -> Election` | Read `valgdag.xml` and every reported feed it lists from a DST-layout directory; `FeedError` naming a missing file. |
| `main() -> None` | Showcase. |

### `src/dkvalg/sources/replay.py`

| Signature | Description |
|---|---|
| `@dataclass(frozen=True, slots=True) class ReplayStep` | `at: datetime`, `place: Place`, `election: Election`; property `progress`. One reveal. |
| `class ReplaySource` | `__init__(self, election: Election, *, speed: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> None` (`ValueError` unless `speed` is positive and not NaN; `inf` never waits); `initial(self) -> Election`; `__iter__(self) -> Iterator[ReplayStep]` reveals each place at its `last_changed`, ties in overview order. |
| `main() -> None` | Showcase. |

### `src/dkvalg/sources/http_source.py`

Polls a live election over HTTP; standard library only. `HttpSource` holds the accepted
body of the overview and of each reported feed with its validators, requests only feeds
whose overview timestamp moved, treats a 304 or a byte-identical 200 as no change, and
builds each `Election` with `build_election`. A fetch is atomic: the recorder runs before
state is committed. `Place.last_changed` is naive Danish local time; fetch times are
timezone-aware UTC.

| Signature | Description |
|---|---|
| `DEFAULT_INTERVAL: Final[float] = 60.0`, `MIN_INTERVAL: Final[float] = 15.0`, `MAX_BACKOFF: Final[float] = 300.0` | Seconds. |
| `@dataclass(frozen=True, slots=True) class HttpResponse` | `status: int`, `headers: Mapping[str, str]` (names lower-case), `body: bytes`. |
| `class Transport(Protocol)` | `__call__(self, url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse`; returns every status, raises `FetchError` only when no response arrives. |
| `urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse` | Default `Transport` over `urllib.request`; `FetchError` for network errors, timeouts, a body shorter than its `Content-Length` (not checked for 204/304) and bodies over 10 MB. |
| `user_agent() -> str` | `dkvalg/<version> (+https://github.com/petermads123/valg_data)`; version `unknown` without package metadata. |
| `overview_url(location: str) -> str` | An election id, folder URL or `valgdag.xml` URL to the overview URL (a trailing slash and any letter case of `valgdag.xml` are normalised); `ValueError` for anything else, including credentials, a bad port, a query, a fragment, non-ASCII, whitespace or control characters. |
| `utc_now() -> datetime` | The default clock, timezone-aware UTC. |
| `@dataclass(frozen=True, slots=True) class FetchResult` | `election: Election`, `changed: tuple[Place, ...]`, `fetched_at: datetime`. |
| `class HttpSource` | `__init__(self, location: str, *, transport: Transport = urllib_transport, recorder: Recorder \| None = None, timeout: float = 20.0, clock: Callable[[], datetime] = utc_now) -> None` (`ValueError` for a bad location or a timeout that is not a finite positive number, a bool included); properties `election -> Election \| None` and `clock`; `fetch(self) -> FetchResult` (`FetchError`/`FeedError`, state untouched on failure; serialised by a lock). |
| `@dataclass(frozen=True, slots=True) class PollCycle` | `number: int`, `at: datetime`, `election: Election \| None`, `changed: tuple[Place, ...]`, `error: FeedError \| None`, `wait: float`. |
| `poll(source: HttpSource, *, interval: float = DEFAULT_INTERVAL, max_cycles: int \| None = None, stop: Callable[[], bool] \| None = None, sleep: Callable[[float], None] = time.sleep) -> Iterator[PollCycle]` | The poll loop; `ValueError` at call time for an interval that is not a finite number of at least 15 or a `max_cycles` that is not an integer of at least 1 (bools refused); backs off after errors (doubling to 5 minutes); reads `source.clock()` once per cycle, and that one time is both `PollCycle.at` and the fetch and capture time; never sleeps after the last cycle. |
| `main() -> None` | Showcase (an in-memory transport over the fixtures; no network). |

### `src/dkvalg/sources/capture.py`

Records what a poll receives and replays it. A capture directory holds one subfolder per
poll that received a body, named `YYYYMMDDTHHMMSS.ffffffZ` (UTC fetch time) and holding the
feeds under their DST file names; a folder is written as `.tmp-<name>` and renamed when
complete, and entries not named like a capture (ASCII digits only) are ignored.

| Signature | Description |
|---|---|
| `check_feed_name(name: str) -> str` | `name` if it is letters, digits, `_`, `-` plus `.xml` and not `valgdag.xml` in any letter case, else `FeedError`; the one allowlist `HttpSource` and `Recorder` share. |
| `class Recorder` | `__init__(self, directory: Path) -> None`; `record(self, fetched_at: datetime, feeds: Mapping[str, bytes]) -> Path` (`ValueError` for a naive time or no feeds; `FeedError` for an unsafe name, a body that is not `bytes`, an existing folder or an I/O failure; no `.tmp-*` folder survives any failure). |
| `@dataclass(frozen=True, slots=True) class CaptureStep` | `at: datetime`, `changed: tuple[Place, ...]`, `election: Election`; property `progress`. One recorded poll. |
| `class CaptureReplay` | `__init__(self, directory: Path, *, speed: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> None` (`ValueError` unless `speed` is positive and not NaN); `__iter__(self) -> Iterator[CaptureStep]` accumulates files folder by folder and sleeps `gap / speed`; `FeedError` (on iteration) for no captures, a bad folder or an incomplete first capture. |
| `is_capture_directory(directory: Path) -> bool` | No `valgdag.xml` and at least one capture-named subfolder. |
| `main() -> None` | Showcase (records and replays the fixtures in a temporary directory). |

### `src/dkvalg/diff.py`

Compares two snapshots; pure, deterministic, detects only (no formatting, no delivery). Places
are matched on type and id and visited in `current`'s order; per place `PlaceCounted` or
`StatusChanged`, then `PartyResultChanged` per party (only where both snapshots hold a
result), then `LeaderChanged`; one closing `ProgressChanged`. A place only in `previous` is
ignored; a place only in `current` is compared with its unreported form.

| Signature | Description |
|---|---|
| `@dataclass(frozen=True, slots=True) class PlaceCounted` | `place: Place`: the earlier status was `NOT_AVAILABLE` and there is a result now. |
| `@dataclass(frozen=True, slots=True) class PartyResultChanged` | `place`, `before: PartyResult \| None`, `after: PartyResult`; properties `votes_delta -> int \| None`, `seats_delta -> int \| None` (`None` when `before` is `None`, and for seats when either side has no seat figure). |
| `@dataclass(frozen=True, slots=True) class LeaderChanged` | `place`, `before: PartyResult \| None`, `after: PartyResult`. |
| `@dataclass(frozen=True, slots=True) class StatusChanged` | `place`, `before: Status`, `after: Status`; every status difference except `NOT_AVAILABLE` to a result. |
| `@dataclass(frozen=True, slots=True) class ProgressChanged` | `before: CountingProgress`, `after: CountingProgress`. |
| `type Change = PlaceCounted \| PartyResultChanged \| LeaderChanged \| StatusChanged \| ProgressChanged` | The union of the five. |
| `diff_elections(previous: Election \| None, current: Election) -> tuple[Change, ...]` | The typed changes from `previous` to `current` (`None` = every place unreported); `ValueError` naming both if the election type or date differs. |
| `main() -> None` | Showcase. |

### `src/dkvalg/cli.py`

| Signature | Description |
|---|---|
| `run(argv: Sequence[str] \| None = None, *, out: TextIO \| None = None, err: TextIO \| None = None, sleep: Callable[[float], None] = time.sleep, transport: Transport = urllib_transport, clock: Callable[[], datetime] = utc_now) -> int` | `replay <dir> [--speed N] [--diff]` (a plain feed directory or a capture directory) and `poll <id-or-url> [--interval N] [--record DIR] [--cycles N] [--diff]`; `--diff` adds, after each step's place lines, one line per notable change (leader at country, landsdel or storkreds; seats; status; progress), and without it the output is unchanged; the national table's letter column is `max(3, longest letter + 1)` wide, so the referendum answers `JA` and `NEJ` do not run into their names; returns 0 ok, 1 on `FeedError` (a `--diff` over two different elections included) or a `poll` whose last cycle failed (`error: <message>` on `err`), 2 on bad arguments or location, 130 on Ctrl-C in `poll`; no subcommand prints help and returns 0. |
| `main() -> None` | `raise SystemExit(run())`. |

### `src/dkvalg/__main__.py`

Entry point for `python -m dkvalg`; calls `cli.main()`.

## Documents and fixtures

### `docs/XmlFeeds20260305.pdf`

DST's documentation of its election XML feeds (status codes, element meanings), from
https://dst.dk/Valg/XmlFeeds20260305.pdf.

### `tests/fixtures/folketingsvalg_2026/`

The unmodified Folketingsvalg 24 March 2026 feeds retrieved 2026-11-03 from
`https://www.dst.dk/valg/Valg2546527/xml/`: `generel.xml`, `valgdag.xml` and the 107 result
feeds it lists (109 XML files, BOM intact), plus `README.md` (sources, retrieval date) and
`SHA256SUMS` (hash of every XML file at download time). `.gitattributes` marks the
directory `-text` so checkouts never rewrite line endings.

### `tests/fixtures/ep_2024/`

The unmodified Europa-Parlamentsvalg 9 June 2024 feeds retrieved 2026-11-04 from
`https://www.dst.dk/valg/Valg2546524/xml/`: `generel.xml`, `valgdag.xml` and the 107 result
feeds it lists (109 XML files, BOM intact, no seat attributes), plus `README.md` and
`SHA256SUMS`. `.gitattributes` marks it `-text` like the other fixture directory.

### `tests/fixtures/folkeafstemning_2022/`, `_2015/` and `_2009/`

The unmodified Folkeafstemning feeds retrieved 2026-11-06 from
`https://www.dst.dk/valg/Valg1962294/xml/` (1 June 2022), `.../Valg1664255/xml/` (3 December
2015) and `.../Valg1191213/xml/` (7 June 2009): `generel.xml`, `valgdag.xml` and every result
feed the overview lists (109 XML files each for 2022 and 2015, 111 for 2009, BOM intact, no
`fintal.xml`), each with a `README.md` and `SHA256SUMS`. The answers are `Parti` entries `JA`
and `NEJ` without seats. 2009 has 94 opstillingskredse; two (Grønland, Færøerne) name a parent
id that no storkreds has, kept as served, and its feeds carry no `SenestRettetIso`. 2015 has
a single space in `ValgNavn`, 2022 and 2009 a double one.

## Tests: `tests/`

Tests for the `dkvalg` package: one `test_<module>.py` per module, plus `conftest.py` for
the shared helpers. No test touches the network; datetimes are built only with
`datetime.fromisoformat`.

### `tests/conftest.py`

Shared helpers, not tests: the `FIXTURES`/`ROOT` paths and the `BOM`, `ELECTION_NAME` and `PARTIES_XML` constants (the byte-order mark, the 2026 election name and a three-party `<Stemmer>` body used by the synthetic builders), the `fixture_dir` (read-only), `fixture_copy`
(a throwaway copy a test may damage) and session-wide `election` (the fixtures loaded once)
fixtures, and small builders for synthetic feeds in DST's real XML shape: `feed_xml`,
`overview_xml`, `entry`, `kreds_entry`, `make_ref`, `make_place`, `make_election`,
`write_directory` and `dt`. For live polling it adds `FakeTransport` (a `Transport` serving the 2026
fixtures or an in-memory mapping with ETag/Last-Modified, 304 on a match, a `vary_etag` switch for
DST's different-ETag-per-request behaviour, scripted per-file outcomes and a request/response log;
its `touch`, `retime_only` and `never_reported` rewrite a feed body and the overview timestamps),
`Request`, `FakeClock` (strictly advancing, counts its calls), `FlakyRecorder` (a `Recorder` that
fails on chosen calls), the `transport` fixture, `fixture_files`, `retime_feed`, `bump_votes`,
`retime_overview`, `dst_stamp`, `utc` and the constants `BASE_URL`, `OVERVIEW`, `NATIONAL`, `LATER_ISO`. `FakeTransport` also offers `names`, `publish(name, body)`,
`script(name, *outcomes)` and `write_to(directory)`; `Request.conditional` says whether a
request carried a validator.

Round 3 adds `EP_FIXTURES`, `EP_ELECTION_NAME` (double space kept) and `EP_BASE_URL`, the fixtures `ep_fixture_dir` (read-only), `ep_fixture_copy` (damageable) and session-wide `ep_election`, the `ep_transport` fixture (a `FakeTransport` serving `ep_2024` under its own election id), `ep_fixture_files()`, and the builders `make_party(letter, votes, *, percent, seats, constituency_seats, supplementary_seats, party_id)` (an empty letter is "Uden for partier") and `make_ep_election(*places)`; `make_place` and `make_election` serve the diff tests.

Round 4 adds the three referendum fixture paths `FA_2022_FIXTURES`, `FA_2015_FIXTURES` and `FA_2009_FIXTURES`, the names `FA_2022_NAME`, `FA_2015_NAME` and `FA_2009_NAME` (copied verbatim from each `valgdag.xml`; `FA_ELECTION_NAME` is the 2022 one) and `FA_2022_BASE_URL`, `FA_2015_BASE_URL` and `FA_2009_BASE_URL`, the fixtures `fa_2022_dir`, `fa_2015_dir`, `fa_2009_dir` (read-only), `fa_2022_copy` (damageable), session-wide `fa_2022`, `fa_2015` and `fa_2009`, the `fa_transport` (2022) and `fa_2009_transport` fixtures (a `FakeTransport` under each set's own election id), `fa_fixture_files(directory=FA_2022_FIXTURES)`, and the builders `make_fa_election(*places)` and `make_answer(letter, votes, *, percent)` (a referendum answer as a seat-free `PartyResult`).

### `tests/test_errors.py`

Covers `FeedError` and `FetchError`: message kept, not a `ValueError`/`KeyError`/`OSError`, cause preserved; a `FetchError` is a `FeedError`, not the reverse.

### `tests/test_model.py`

Covers `dkvalg.model`: `Status.has_result` per code, `PartyResult.is_party`, `Place.unreported`
(identity kept, figures dropped, idempotent, pure), immutability and hashing, `Election.get` /
`of_type` / `counting_progress` boundaries, `CountingProgress.__str__` (T4, T8), and `Election.changed_since`: `None`, equal, changed, new, removed, back-to-never (not reported), order, type-aware identity, purity (T11).

Round 3 adds the EP `ElectionType` member and `Place.leader` (most votes, tie to the earlier party, "Uden for partier" and zero votes never lead, `None` without a result).

Round 4 adds the `FOLKEAFSTEMNING` member and referendum answers (leader, ties, zero votes, `is_party` keyed on the id).

### `tests/test_package.py`

Covers the package surface: `import dkvalg`, the re-exported names, adapter and CLI names kept
out of the top level, and `valg_data`/`template_repo` not importable (T1, A1); the live-polling names re-exported and the transport pieces kept in their modules.

Round 3 adds the seven diff names re-exported and the registry and adapter helpers kept out.

Round 4 adds the referendum member at the top level and the referendum adapter kept out.

### `tests/test_folketingsvalg.py`

Covers `dkvalg.adapters.folketingsvalg`: `parse_overview`, `parse_place` and `unreported_place`
against the real fixtures (Hovedstaden field by field) and synthetic feeds: BOM, "never"
timestamps in every spelling, empty `SenestRettetIso`, status codes, missing and non-numeric
figures (`nan`, `inf`, `1_000`), a party without `Id`, malformed XML, non-Folketingsvalg
overviews (T3, T7, A3, A7); the DOCTYPE/entity hardening (T10, A8): every hostile shape in UTF-8, UTF-8 with BOM and UTF-16, a billion-laughs payload refused quickly, a comment, CDATA, escaped text, processing instruction or attribute mentioning DOCTYPE accepted, every fixture still parsing, and `DEVELOPMENT.md` without the resolved entries.

### `tests/test_directory.py`

Covers `dkvalg.sources.directory.load_election`: the 107-place fixture election (type counts,
seats summing to 175, no seats below storkreds, "Uden for partier"), placeholders for never
reported feeds, missing/empty/malformed files and unreadable paths all as `FeedError`
naming the file, purity and idempotency (T3, T7, T8, A3, A7); and `build_election`: equal to `load_election`, the reader called only for reported feeds in overview order, its exceptions propagated, hostile overviews refused before any read (T11, A9).

Round 3 adds EP through `load_election` and `build_election` (adapter chosen from the overview name, unsupported names refused, a never-reported EP feed).

Round 4 adds the same for referenda (type and counts per set, adapter chosen for 2009, a referendum renamed to Kommunalvalg refused, a never-reported feed).

### `tests/test_replay.py`

Covers `dkvalg.sources.replay`: start at 0/92, order with ties in overview order, mid-sequence
snapshots, final snapshot equal to the static election (also with untimed, status 0 and 9
places), sleeps as gaps divided by speed with an injected clock, `inf` never sleeping, speed
validation, restart and interleaved iterators, purity (T5, T8, A5).

### `tests/test_cli.py`

Covers `dkvalg.cli` and `dkvalg.__main__`: `run` on the fixtures (one line per step, rising
counted/total, national table), errors on stderr with exit 1, bad arguments with exit 2, usage
and help with exit 0, stream handling, and `main` / `python -m dkvalg` through `runpy` and a
subprocess with `PYTHONPATH=src`, independent of the editable install (T1, T6, A1, A6); `poll` through
an injected transport, sleep and clock (lines, `--interval`, `--cycles`, `--record`, exit codes 0/1/2/130,
bad arguments, errors on stderr only) and `replay` on a capture directory against a plain one (T9, A7).

Round 3 adds `--diff` on `replay` (plain, capture, synthetic capture with exact line formats) and `poll` (failed cycles, seats appearing, EP), flag-less output equal to the diff output minus its lines, leader lines only at country, landsdel and storkreds, aware-UTC poll times against naive replay times, and a mixed-election run ending in `error:` and exit 1.

Round 4 pins the national table rows exactly (3-wide letter column for 2026 and EP, 4-wide `JA`/`NEJ` rows for referenda) and adds `--diff` on the three referenda (flag-less equality, leader lines at the three levels with `JA`/`NEJ`, no seat lines), a referendum `poll --diff`, a recorded referendum capture and a referendum that changes type mid-run ending in `error:` and exit 1.

### `tests/test_http_source.py`

Covers `dkvalg.sources.http_source` through `FakeTransport` and, for `urllib_transport`, a server bound
to `127.0.0.1`: the constants, `user_agent` (also without package metadata), `overview_url` (every
accepted and rejected shape), the loopback transport (headers lower-cased, 304/404/500 returned, refused
connection, timeout, dropped connection, truncated body, the 10 MB cap at its boundary, redirects),
`HttpSource` construction, the first fetch against `load_election`, validators per resource,
304 and identical-body 200s, changed-feed selection, never-reported transitions, unsafe feed names,
a failure at every stage leaving state and capture untouched, recorder and clock failures, two threads
fetching at once, and `poll` (backoff schedule, call-time validation, one clock read per cycle, stop and
`max_cycles`) (T1 to T6, T12, A1 to A5).

Round 3 adds EP through `HttpSource` (EP overview URL, first fetch equal to `load_election`, varying ETags, never reported and back, an overview that becomes an unsupported election).

Round 4 adds referenda (varying ETags, the 2009 set whole and unchanged, the overview URL, a poll cycle, a Kommunalvalg overview refused before any feed is requested).

### `tests/test_capture.py`

Covers `dkvalg.sources.capture`: `check_feed_name` (all 108 non-overview fixture names accepted,
unsafe names and any case of `valgdag.xml` refused), `Recorder` (UTC folder names, atomicity with no
`.tmp-*` left after OSError or other failures, existing folder, stale temporary folder, non-bytes bodies),
`is_capture_directory`, `CaptureReplay` (order by name, gaps divided by speed, ignored and refused
entries, incomplete first capture, errors mid-iteration, restart) and an end-to-end record-then-replay of
four fetches (full, partial with the national feed, identical 200, 304) checking steps, changed lists,
earlier national figures, last step equal to the source's election and sleeps (T7, T8, T9, A6).

Round 3 adds an EP record-then-replay round trip.

Round 4 adds the same round trip for the 2015 referendum (changed lists equal the live ones, repeatable replay, folder contents) and the all-feed-names allowlist check for the three referendum sets.

### `tests/test_europaparlamentsvalg.py`

Covers Europa-Parlamentsvalg across the stack (A1, A3, A4; T1, T3, T4): the real `ep_2024` fixtures through `load_election` (type, 107 places by type, 92/92, every seat field `None`, national figures, parent ids, SF leading), the EP adapter against the Folketingsvalg one, the quirks (BOM, double space, status 0 in DST's example shape, never reported, empty or absent `Id`, DOCTYPE in the overview and in a result feed), `HttpSource` through `FakeTransport`, a recorded poll replayed by `CaptureReplay`, `ReplaySource`, and the CLI `replay` and `poll` on EP (seats shown as `-`).

### `tests/test_registry.py`

Covers `parse_any_overview` (A2, T2): each real overview gives its own type, names accepted by prefix after stripping (a bare prefix and `Folketingsvalgxyz` pinned as accepted), other names refused naming the value and the supported types, absent or empty `ValgNavn`, malformed XML, a DOCTYPE refused before the name is read (BOM and UTF-16 too), a good name with a bad date or no feeds.

Round 4 adds the three real referendum overviews, referendum names accepted (double space kept, bare prefix, `Folkeafstemningxyz` pinned as accepted), other names refused with the exact three-type message, and the registry equal to the matching adapter.

### `tests/test_folkeafstemning.py`

Covers Folkeafstemning across the stack (A1 to A6; T1 to T6): the three real sets through `load_election` (type, name, date, places by type, 92/92 and 94/94 progress, the national figures, the winning answer, answers as seat-free parties with ids 434284 and 434285 and no "Uden for partier", the 2009 dangling parents of Grønland and Færøerne kept, no `SenestRettetIso` in 2009, overview names winning over feed names), `build_election` and the progress total taken from the overview (94, 92, 1, 0 districts), the adapter (the 3 by 3 refusal matrix, name boundaries, whitespace, bad or missing date, no feeds, BOM, UTF-16, the `SenestRettet` fallback, a missing storkreds id), `parse_place` shapes (status 0 in DST's example shape, status 1 with two answers, 0 to 3 answers, ties, all-zero votes, an answer without or with an empty `Id`, bad figures, a missing `Stemmer`), DOCTYPE and entity refusal naming the file, the showcases, `HttpSource` (equal to `load_election`, unchanged refetch, touched and retimed feeds, never reported, a Kommunalvalg overview refused with state kept), a recorded poll replayed by `CaptureReplay`, `ReplaySource`, and the CLI (`replay` on 2022, 2015 and 2009 with exact `JA`/`NEJ` table rows, `poll`, speed and interval boundaries, and the letter column width: per country, boundaries 1 to 5 letters, an empty letter, a country without a result).

### `tests/test_dst_feed.py`

Covers `election_name`, `parse_overview_for` and the re-exports (T10): stripped names, `no ValgNavn` and malformed or hostile overviews naming `valgdag.xml`, the `not a <prefix>` refusal, equality with the Folketingsvalg adapter, and that each adapter re-exports the same objects as `dst_feed` with the same `__all__`.

Round 4 adds `election_name` on the three referendum overviews, `parse_overview_for` with the referendum type, and the third adapter's re-exports.

### `tests/test_diff.py`

Covers `diff_elections`, the five change kinds and `Place.leader` use in them (A5 to A7; T5 to T7): the `Change` alias via `typing.get_args(Change.__value__)`, frozen dataclasses and deltas, equal elections, `None` previous against an all-unreported copy, purity and idempotency, type and date mismatch, every status transition (`PlaceCounted` only from status 0), party-result changes on the real 2026 data (national and storkreds seats, percent only, seats `None` to a figure, new and vanished parties), leader rules (overtake, tie, reordered tie, "Uden for partier", all-zero votes, lost leader), a first count with seats giving no `PartyResultChanged`, place matching, ordering and progress, and the replay-consistency chain for 2026 (107 `PlaceCounted`, leader A) and EP 2024 (leader F).

Round 4 adds referenda: `LeaderChanged` from JA to NEJ with votes deltas and `seats_delta` `None`, ties keeping the earlier answer, a percent-only move, a first count, the type-mismatch `ValueError`, and the replay-consistency chain for 2022, 2015 and 2009 (107, 107 and 109 `PlaceCounted`, final leaders JA, NEJ and JA).

### `tests/test_fixtures.py`

Verifies the fixture directory: 109 XML files plus README and `SHA256SUMS`, every feed the
overview lists present, every file matching its SHA-256 with its BOM intact, the PDF in `docs/`,
the README's source URLs and date, and `.gitattributes` (T2, A2).

All tests live here and nowhere else — `testpaths = ["tests"]` in `pyproject.toml` means
`pytest` collects nothing outside this directory; a test file anywhere else never runs.

Round 3 adds the same checks for `tests/fixtures/ep_2024` (109 files, hashes, BOM, README needles).

Round 4 adds them for the three referendum sets (109, 109 and 111 files, overview-listed feeds all present, hashes, BOM, line endings, README needles, the 2009 oddly numbered feeds, the `conftest` paths).

### Pipeline tests

| File | Covers |
|---|---|
| `tests/test_dev_state.py` | parsing, malformed files, active-brief choice, git helpers; its `write_brief`/`write_round` helpers are reused by other tests |
| `tests/test_session_brief.py` | the brief text and `main`'s output |
| `tests/test_check_sync.py` | every check, including the version raise against a throwaway repo |
| `tests/test_guard_git.py` | the guard, vendored with it |
| `tests/test_select_tests.py` | every selection rule on a throwaway repo (transitive and relative imports, re-exporting `__init__`, helpers, deletions, renames, cycles, unparseable files), `changed_files` and the CLI |

## Plans: `development/`

The pipeline's state, laid out in `development/README.md`. The numbered `NN-<slug>.md` files
under `development/feat/dkvalg-*/` are the record of the earlier ten-step pipeline: read-only
history, ignored by the hooks.

## Hooks: `.claude/hooks/`

Stdlib only; importable by each other and by the tests (`pythonpath` in `pyproject.toml`).

### `.claude/hooks/dev_state.py`

Reads `brief.json` and `round.json` leniently: a malformed file reads as None.

| Signature | Returns |
|---|---|
| `RoundEntry` | Frozen dataclass: `number`, `name`, `slug`, `branch`, `status`, `summary`; property `folder -> str` (`r<n>-<slug>`). |
| `Brief` | Frozen dataclass: `path`, `feature`, `title`, `branch`, `bump`, `status`, `summary`, `current_round`, `rounds: tuple[RoundEntry, ...]`, `pr`, `kind` (`feature` or `fix`); properties `folder -> Path`, `live -> bool`; `round_entry(number: int) -> RoundEntry \| None`. |
| `RoundState` | Frozen dataclass: `path`, `round`, `name`, `branch`, `status`, `step`, `steps: tuple[str, ...]`, `attempt`, `question`, `note`; property `step_name -> str`. |
| `read_brief(path: Path) -> Brief \| None` | One `brief.json`, or None if unusable. |
| `read_round(path: Path) -> RoundState \| None` | One `round.json`, or None if unusable. |
| `all_briefs(project_dir: Path) -> list[Brief]` | Every brief under `development/`, newest first. |
| `active_brief(project_dir: Path, branch: str = "") -> Brief \| None` | The live brief, preferring the checked-out feature or round branch. |
| `round_state(brief: Brief, number: int) -> RoundState \| None` | That round's `round.json`. |
| `read_diagnosis(path: Path) -> RoundState \| None` | A fix's diagnosis `state.json`, read as a `RoundState` with `round` 0 and the diagnosis steps. |
| `diagnosis_state(brief: Brief) -> RoundState \| None` | The feature's `diagnosis/state.json`, or None. |
| `git_lines(project_dir: Path, args: list[str]) -> list[str]` | Non-empty output lines of a git command, `[]` on failure. |
| `current_branch(project_dir: Path) -> str` | The checked-out branch, or `""`. |
| `main() -> None` | Prints the live feature and its current round. |

Constants: `DEV_DIR`, `DIAGNOSIS_DIR`, `KINDS`, `LIVE_STATUSES`, `FEATURE_STATUSES`,
`ROUND_STATUSES`, `STEP_STATUSES`, `ROUND_STEPS` (the nine step names), `DIAGNOSIS_STEPS` (the
four diagnosis steps).

### `.claude/hooks/session_brief.py`

`SessionStart` hook: injects the live feature's state and the skill that resumes it.

| Signature | Returns |
|---|---|
| `brief(project_dir: Path, feature: Brief) -> str` | The paragraph for the session's context. |
| `main() -> None` | Emits it as `additionalContext`, or nothing when no feature is live. |

### `.claude/hooks/check_sync.py`

Checks the documents agree with each other and with the code. Run by `/finish` and CI.

| Signature | Returns |
|---|---|
| `parse_version(text: str) -> tuple[int, int, int] \| None` | The version, or None if not exactly `X.Y.Z`. |
| `bumped(version: tuple[int, int, int], bump: str) -> tuple[int, int, int]` | The version raised by `major`/`minor`/`patch`; raises `ValueError` otherwise. |
| `project_version(pyproject_text: str) -> str` | `[project] version`, or `""`. |
| `version_problems(project_dir: Path) -> list[str]` | pyproject, README `**Version:**` and newest DEVLOG entry disagree; DEVLOG order. |
| `structure_problems(project_dir: Path) -> list[str]` | Python files missing from STRUCTURE.md, or named but absent. |
| `state_problems(project_dir: Path) -> list[str]` | Unparseable state files, unknown statuses. |
| `branch_brief(project_dir: Path, branch: str) -> Brief \| None` | The brief whose feature or round branch is `branch`. |
| `bump_problems(project_dir: Path, base: str) -> list[str]` | Version not raised above `base`'s by this branch's brief's bump (any raise without one). |
| `problems(project_dir: Path, base: str = "") -> list[str]` | All of the above. |
| `main() -> None` | CLI: `[--base REF] [--root DIR]`; prints problems, exits 1 if any. |

### `.claude/hooks/select_tests.py`

Picks the test files a change can affect, so a round runs those and CI runs the whole suite.
The changes are `git diff <base>...HEAD` plus uncommitted and untracked files. The full suite
(None) for `pyproject.toml`, a `conftest.py`, a non-test file under the test directory, a
re-exporting `__init__.py`, an unparseable `.py` file or a file it cannot place; otherwise
the changed test files, `test_<module>.py` (and `test_<pkg>_<module>.py`) of each changed
module, and every test file that depends on a changed module transitively, read with `ast`
(imports, `import_module("...")`, and strings naming a module or its path). Prose,
`development/` and `.claude/` outside `hooks/` select nothing; other configuration selects
the tests that name it. Module roots come from `pythonpath` and `testpaths`;
`[tool.select_tests] ignore` adds path prefixes that select nothing.

| Signature | Returns |
|---|---|
| `Selection` | Frozen dataclass: `tests: tuple[str, ...] \| None` (None = full suite), `reason`, `total`; `summary() -> str` (`selected 4 of 61: ...`, `full suite: ...`, `no tests apply: ...`). |
| `changed_files(project_dir: Path, base: str) -> list[str]` | Changed paths against `base...HEAD`, committed or not, sorted; renames as both paths. Raises `ValueError` when git fails. |
| `selection(project_dir: Path, changed: Iterable[str]) -> Selection` | The selection with its reason. |
| `select_tests(project_dir: Path, changed: Iterable[str]) -> list[str] \| None` | The test paths, `[]` when none applies, None for the full suite. |
| `main() -> None` | CLI: `[--base REF] [--root DIR]`; one test per line, `ALL`, or nothing on stdout, the reason on stderr; `ALL` when the changes cannot be listed. |

### `.claude/hooks/guard_git.py`

`PreToolUse` hook on `Bash` and `PowerShell`: refuses a `git commit` or `git push` that would
land on `main`, reading the command as a shell would (quoting, separators, subshells, branch
switches chained with `&&`). Vendored from `template_repo`.

| Signature | Returns |
|---|---|
| `Segment` | Frozen dataclass: `tokens`, `separator`. |
| `segments(command: str) -> list[Segment] \| None` | The command split into invocations, or None if unreadable. |
| `git_subcommand(tokens: tuple[str, ...]) -> tuple[str, tuple[str, ...]]` | The git subcommand and its arguments. |
| `push_targets_main(args: tuple[str, ...], branch: str) -> bool` | Whether a push would update `main`. |
| `switch_target(subcommand: str, args: tuple[str, ...]) -> str` | The branch a checkout/switch moves to, `""`, or `UNRESOLVED`. |
| `violation(command: str, branch: str) -> str` | The reason to refuse, or `""`. |
| `main() -> None` | Entry point: allow or refuse. |

### `.claude/hooks/lint_py.py`

`PostToolUse` hook: `ruff format` and `ruff check --fix` on an edited `.py` file.

| Signature | Returns |
|---|---|
| `find_ruff(project_dir: Path) -> Path \| None` | Ruff in the project venv. |
| `run(ruff: Path, args: list[str]) -> CompletedProcess[str]` | Ruff's result. |
| `target_file(payload: dict[str, object], project_dir: Path) -> Path \| None` | The edited `.py` file. |
| `main() -> None` | Format, fix, report. |

## Pipeline configuration: `.claude/`

| Path | Role |
|---|---|
| `skills/feature/` | `/feature`: Main Conceptualize (Opus medium), background `repo-scout`s, BRIEF, starts round 1 |
| `skills/fix/` | `/fix`: intake, runs `workflows/diagnose.js`, agrees cause, scope and bump with the user, then the rounds with `kind: "fix"` |
| `skills/round/` | `/round`: coordinates one round (Sonnet high), runs `workflows/round.js`, answers or escalates questions |
| `skills/finish/` | `/finish`: runs `workflows/final.js`, extras, `docs-writer`, version, pull request, then CI through to green |
| `workflows/diagnose.js` | A fix's four diagnosis steps; args `feature_dir`, `branch`, `symptom`, `start_step`, `answers`; returns `diagnosed` (with `is_bug` and the `defect`), `needs_input` or `failed` |
| `workflows/round.js` | The nine round steps (step 7 runs the tests `select_tests.py` picks against the feature branch, `--ff` plus the earlier failures in the fix loop); args `feature_dir`, `round_dir`, `round`, `feature_branch`, `round_branch`, `start_step`, `attempt`, `kind`, `answers` (`kind` `fix` adds the fix-round rules); returns `merged`, `needs_input` or `failed` |
| `workflows/final.js` | Read-only whole-feature check: test gate first (the selection against `origin/main`, not the full suite), then three independent concept checks and two extras scouts; returns `tests`, `checks`, `extras`, `missing` |
| `agents/reproducer.md`, `cause-hunter.md`, `root-cause-analyst.md`, `diagnosis-critic.md` | The diagnosis's four steps (`/fix`) |
| `agents/repo-scout.md` | Read-only investigation for `/feature`, one angle each |
| `agents/round-conceptualizer.md`, `round-planner.md` | Round steps 1 and 2 (Opus) |
| `agents/implementer.md` | Step 3, and fix mode for failing gates |
| `agents/verifier.md`, `code-reviewer.md` | Step 4 |
| `agents/test-designer.md`, `test-writer.md`, `test-runner.md` | Steps 5 to 7 |
| `agents/concept-checker.md` | Step 8 and the final check |
| `agents/round-closer.md` | Step 9: merge into the feature branch |
| `agents/extras-scout.md`, `docs-writer.md` | `/finish` |
| `rules/python.md` | Conventions for `**/*.py` |
| `settings.json` | Hooks and pre-approved commands |
