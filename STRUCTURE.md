# Structure

Map of everything in this repo. Loaded into context at the start of every session via the
`@STRUCTURE.md` import in `CLAUDE.md`, so it is what Claude uses to find things without
searching.

## Keeping this file current

Update it **in the same change** that causes any of the following:

- a module is added, deleted, renamed or moved
- a public function or class is added or removed
- a public signature changes (parameters, defaults, return type)
- a module's purpose changes

Private helpers (names starting with `_`) are intentionally left out. They are
implementation detail, and listing them is what makes a file like this rot.

The stop gate (`.claude/hooks/stop_gate.py`) cross-checks the module paths named here
against the `.py` files on disk and blocks on a mismatch. It only sees file-level drift —
signature drift is on you, or run the `structure-auditor` subagent.

That covers `src/`, `tests/` and `.claude/hooks/`. The hooks are documented here with full
signature tables, type-checked like the package (`[tool.mypy] files` names all three) and
importable from the suite (`[tool.pytest.ini_options] pythonpath` names `src` and
`.claude/hooks`, so a test imports a hook by module name the same way a sibling hook does
at runtime), so they are held to the same standard despite not being installable.

## Growth

While the package is flat, keep everything here. Once it has subpackages, keep the tree and
one line per subpackage in this file, and move per-subpackage detail into
`.claude/rules/structure-<subpackage>.md` with `paths: ["<subpackage>/**"]` so it loads only
when Claude works in that subpackage. Split rather than delete — there is no length limit
here, but everything in this file is in context every session.

## Tree

```
src/                    everything installable; nothing outside it is packaged
  dkvalg/               the package: model, diff, adapters, sources (files, HTTP, captures) and the CLI
docs/                   reference documents (DST's XML-feeds PDF)
tests/                  pytest suite, one test_<module>.py per module
  fixtures/             unmodified real DST feeds used as test data (Folketingsvalg 2026, EP 2024, Folkeafstemning 2022, 2015 and 2009)
development/            one folder per branch, one file per round: the pipeline's state
.claude/                Claude Code configuration: rules, skills, agents, hooks
.vscode/                editor config (Ruff as formatter, format on save)
pyproject.toml          packaging, Ruff, mypy and pytest configuration
DEVELOPMENT.md          development-side open questions and things to fix later (see CLAUDE.md)
README.md               human setup guide
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

### `tests/test_errors.py`

Covers `FeedError` and `FetchError`: message kept, not a `ValueError`/`KeyError`/`OSError`, cause preserved; a `FetchError` is a `FeedError`, not the reverse.

### `tests/test_model.py`

Covers `dkvalg.model`: `Status.has_result` per code, `PartyResult.is_party`, `Place.unreported`
(identity kept, figures dropped, idempotent, pure), immutability and hashing, `Election.get` /
`of_type` / `counting_progress` boundaries, `CountingProgress.__str__` (T4, T8), and `Election.changed_since`: `None`, equal, changed, new, removed, back-to-never (not reported), order, type-aware identity, purity (T11).

Round 3 adds the EP `ElectionType` member and `Place.leader` (most votes, tie to the earlier party, "Uden for partier" and zero votes never lead, `None` without a result).

### `tests/test_package.py`

Covers the package surface: `import dkvalg`, the re-exported names, adapter and CLI names kept
out of the top level, and `valg_data`/`template_repo` not importable (T1, A1); the live-polling names re-exported and the transport pieces kept in their modules.

Round 3 adds the seven diff names re-exported and the registry and adapter helpers kept out.

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

### `tests/test_capture.py`

Covers `dkvalg.sources.capture`: `check_feed_name` (all 108 non-overview fixture names accepted,
unsafe names and any case of `valgdag.xml` refused), `Recorder` (UTC folder names, atomicity with no
`.tmp-*` left after OSError or other failures, existing folder, stale temporary folder, non-bytes bodies),
`is_capture_directory`, `CaptureReplay` (order by name, gaps divided by speed, ignored and refused
entries, incomplete first capture, errors mid-iteration, restart) and an end-to-end record-then-replay of
four fetches (full, partial with the national feed, identical 200, 304) checking steps, changed lists,
earlier national figures, last step equal to the source's election and sleeps (T7, T8, T9, A6).

Round 3 adds an EP record-then-replay round trip.

### `tests/test_europaparlamentsvalg.py`

Covers Europa-Parlamentsvalg across the stack (A1, A3, A4; T1, T3, T4): the real `ep_2024` fixtures through `load_election` (type, 107 places by type, 92/92, every seat field `None`, national figures, parent ids, SF leading), the EP adapter against the Folketingsvalg one, the quirks (BOM, double space, status 0 in DST's example shape, never reported, empty or absent `Id`, DOCTYPE in the overview and in a result feed), `HttpSource` through `FakeTransport`, a recorded poll replayed by `CaptureReplay`, `ReplaySource`, and the CLI `replay` and `poll` on EP (seats shown as `-`).

### `tests/test_registry.py`

Covers `parse_any_overview` (A2, T2): each real overview gives its own type, names accepted by prefix after stripping (a bare prefix and `Folketingsvalgxyz` pinned as accepted), other names refused naming the value and both supported types, absent or empty `ValgNavn`, malformed XML, a DOCTYPE refused before the name is read (BOM and UTF-16 too), a good name with a bad date or no feeds.

### `tests/test_dst_feed.py`

Covers `election_name`, `parse_overview_for` and the re-exports (T10): stripped names, `no ValgNavn` and malformed or hostile overviews naming `valgdag.xml`, the `not a <prefix>` refusal, equality with the Folketingsvalg adapter, and that both adapters re-export the same objects as `dst_feed` with the same `__all__`.

### `tests/test_diff.py`

Covers `diff_elections`, the five change kinds and `Place.leader` use in them (A5 to A7; T5 to T7): the `Change` alias via `typing.get_args(Change.__value__)`, frozen dataclasses and deltas, equal elections, `None` previous against an all-unreported copy, purity and idempotency, type and date mismatch, every status transition (`PlaceCounted` only from status 0), party-result changes on the real 2026 data (national and storkreds seats, percent only, seats `None` to a figure, new and vanished parties), leader rules (overtake, tie, reordered tie, "Uden for partier", all-zero votes, lost leader), a first count with seats giving no `PartyResultChanged`, place matching, ordering and progress, and the replay-consistency chain for 2026 (107 `PlaceCounted`, leader A) and EP 2024 (leader F).

### `tests/test_fixtures.py`

Verifies the fixture directory: 109 XML files plus README and `SHA256SUMS`, every feed the
overview lists present, every file matching its SHA-256 with its BOM intact, the PDF in `docs/`,
the README's source URLs and date, and `.gitattributes` (T2, A2).

All tests live here and nowhere else — `testpaths = ["tests"]` in `pyproject.toml` means
`pytest` collects nothing outside this directory, and the stop gate blocks on a test file
found anywhere else.

Round 3 adds the same checks for `tests/fixtures/ep_2024` (109 files, hashes, BOM, README needles).

### `tests/test_guard_git.py`

Covers `.claude/hooks/guard_git.py` — every public function plus `main` end to end against a
throwaway repository, over both Bash and PowerShell command forms — and is the regression
suite for the quoting defect its parser was rebuilt to fix. One test asserts a documented
miss rather than a fix: `sudo -u me git push` is allowed, because only options are skipped
after a wrapper and never a bare word.

### `tests/test_plan_state.py`

Covers `.claude/hooks/plan_state.py`: every public function, the `Plan` properties either
side of `GATE_FROM_STEP`, and the git helpers against a throwaway repository.

### `tests/test_stop_gate.py`

Covers `.claude/hooks/stop_gate.py`: every public function and `main`'s paths through the
gate. `gate_failures`, `enforce` and `main` are driven through a monkeypatched `venv_tool`,
`capture` and checks rather than real executables: running them for real would invoke Ruff,
mypy and `pytest` from inside `pytest`, and stub executables would need a shell script on
POSIX and an `.exe` on Windows.


## Plans: `development/`

One folder per branch, one numbered file per round inside it, created at the close of step
1 from `TEMPLATE.md` and carried through all ten steps:

```
development/
  TEMPLATE.md                     copied for each new round; never itself active
  feat/csv-export/                the folder is the branch name, so it nests one level
    01-csv-export.md              round 1, shipped
    02-streaming-writer.md        round 2, opened from round 1's recommendation R2
```

Each file holds the concept and acceptance criteria, the plan, the verification and test
logs, the concept-check audit, the recommendations and the pull request, plus a `Halted`
section if the build stopped to ask. A fix round's section 1 also carries a **Defect**
block — reproduction, root cause, class, blast radius, scope — filled from the `/fix`
diagnosis; its presence is what tells the later steps the round is a fix. Every round
of a feature shares one branch and one pull request; a later round's **Builds on** section
names what the earlier rounds delivered, and its step 6 re-checks their acceptance criteria
as a regression pass.

The first line after the title is the workflow's state and is read by the hooks:

```
<!-- claude-plan step=3 status=active -->
```

`step` is 1 to 10; `status` is `active`, `done`, `parked` or `template`. Exactly one file
across the whole repo should be `active` — opening a round stands its predecessor down to
`done`, and step 9 marks the newest round `done` in the commit that opens the pull request,
so `main` never carries a live marker. Every step commits and pushes the file with what it
produced: plan files are the record of why the code looks the way it is, the state any
session resumes from, and what `/create-pr` builds the pull request body from.

## Claude configuration: `.claude/`

| Path | Role |
|---|---|
| `settings.json` | Registers the four hooks; pre-approves ruff/mypy/pytest, `python -m`, and the git commands the pipeline uses (read-only ones plus add, commit, push, fetch, checkout, switch, merge, mv) so an unattended build never stalls on a prompt — `guard_git.py` is what keeps that safe |
| — | Every skill pins `model` and `effort` in its frontmatter; the table in `CLAUDE.md` says which and why |
| `skills/build/` | `/build` — steps 3 to 7 as one unattended block, with `models.md` holding the per-step model and effort table and its rationale: a subagent per step on its pinned model, the step's readers (`structure-auditor`, `test-designer`) run by the orchestrator and handed over in the brief, work-in-progress commits, commit and push after each, halting rules, trace relay, resume from the marker or an interrupted run |
| `rules/python.md` | Coding conventions, auto-loaded for `**/*.py` |
| `skills/repo-setup/` | `/repo-setup` — one-time setup of a repo made from this template; carries `main_protect.solo.json` and `main_protect.collab.json` |
| `skills/feature/` | `/feature` — starts or resumes the pipeline |
| `skills/fix/` | `/fix` — starts the pipeline from a defect: reproduces, finds the root cause, sizes the class, has the diagnosis criticised, decides whether it is a bug at all, then hands to `/conceptualize` as a fix round |
| `skills/conceptualize/` | `/conceptualize` — step 1, agree the concept, name the branch and choose the version bump |
| `skills/plan/` | `/plan` — step 2, design it; waits for the user only when the critic leaves something open |
| `skills/implement/` | `/implement` — step 3, write the code (inside `/build`) |
| `skills/verify/` | `/verify` — step 4, static verification |
| `skills/test/` | `/test` — step 5, edge-case suite |
| `skills/concept-check/` | `/concept-check` — step 6, audit against the concept |
| `skills/ship/` | `/ship` — step 7, close the round: whole-tree gates and diff review (inside `/build`) |
| `skills/recommend/` | `/recommend` — step 8: critical follow-ups only, usually none, decided with the user; lesser ideas noted in `DEVELOPMENT.md`; with nothing critical it hands on to `/create-pr` |
| `skills/create-pr/` | `/create-pr` — step 9, write the version bump, pull request ready for review |
| `skills/watch-pr/` | `/watch-pr` — step 10, hourly review watch until merge or close |
| `skills/small-change/` | `/small-change` — cosmetic edits, outside the pipeline |
| `agents/diagnosis-critic.md` | Subagent that tries to falsify a defect diagnosis before step 1 agrees a fix on it — re-runs the reproduction, traces the cause independently, checks the class (feeds `/fix`); may run code from a scratch directory but never writes to the tree; pinned to `opus` |
| `agents/plan-critic.md` | Read-only subagent that reads a plan against its concept and the repo before it is accepted (feeds step 2; a clean verdict starts the build without the user); pinned to `opus` |
| `agents/test-designer.md` | Read-only subagent that finds edge cases; run twice at step 5 with the `input-space` and `contract` briefs |
| `agents/brainstormer.md` | Read-only subagent that proposes at most three follow-ups through one lens — `user`, `maintainer`, `integrator` or `defect-class` — or none; step 8 runs only `defect-class`, on a fix round, and the others run when the user asks what to build next |
| `agents/structure-auditor.md` | Read-only subagent that reconciles this file (feeds steps 4 and 6) |

### `.claude/hooks/plan_state.py`

Shared by the other hooks: parses the `claude-plan` marker out of the plan files and
answers which plan is active, plus the small git helpers the hooks need. Importable by its
siblings because Python puts a script's own directory on `sys.path`. Stdlib only.

| Signature | Description |
|---|---|
| `Plan` | Frozen dataclass: `path`, `step`, `status`, `title`, `branch`, `feature` (the folder relative to `development/`, so the branch name with its `/`; empty for `TEMPLATE.md`), `round_number`, plus `step_name` and `gated` properties. |
| `parse(path: Path) -> Plan \| None` | Parse one plan file, or None if it has no valid marker. |
| `all_plans(project_dir: Path) -> list[Plan]` | Every parseable plan in every feature folder, most recently modified first. |
| `active_plan(project_dir: Path) -> Plan \| None` | The plan the pipeline is working through. |
| `feature_rounds(project_dir: Path, feature: str) -> list[Plan]` | One feature's rounds, oldest first; `feature` is the folder relative to `development/`, as on `Plan.feature`. |
| `git_lines(project_dir: Path, args: list[str]) -> list[str]` | Run git, return output lines. |
| `current_branch(project_dir: Path) -> str` | The checked-out branch, or `""`. |
| `main() -> None` | Showcase: prints the plans found, the active one and its sibling rounds. |

`GATE_FROM_STEP = 8` is the step at which the stop gate starts blocking: steps 3 to 7 are
the build, which carries its own gates and must be able to halt on a red tree.
`PLAN_DIR = development` is the directory it scans; `Plan.feature` is a folder path relative
to it, so a branch-named folder such as `feat/csv-export` comes back with its `/`.

### `.claude/hooks/session_brief.py`

`SessionStart` hook. Injects the active plan's step into a new session's context, the skill
that resumes it (`/build` for steps 3 to 7), plus what any earlier rounds of the same
feature delivered, so work resumes without the user having to re-explain it. Silent when
no plan is active — including while a pull request is open, since step 9 closes the plan.
Stdlib only.

| Signature | Description |
|---|---|
| `brief(project_dir: Path, plan: Plan) -> str` | Describe one active plan's state. |
| `main() -> None` | Entry point: emit the brief as session context. |

### `.claude/hooks/guard_git.py`

`PreToolUse` hook on `Bash` and `PowerShell`. Refuses a `git commit` or `git push` that
would land on `main`. Reads the command the way a shell does — `shlex` resolves quoting, so a `;` or `|`
inside a commit message stays part of the message — then splits it on the real separators
into one invocation per segment. The grouping delimiters `(`, `)`, `{` and `}` split too, so
a command hidden inside `(git commit -m "x")` is seen rather than left with `(` sitting
where its name should be.

Each segment is judged against the branch that will be checked out when it runs. Only `&&`
guarantees its left side succeeded, so a branch switch carries forward across a run of
separators that is `&&` and newlines, and across nothing else: `git checkout -b feat/x &&
git commit` is allowed from `main`, and so is the same pair with the `&&` ending the line,
while `;`, `|`, `||`, `&`, a bare newline or a mixed run such as `; &&` is refused. A switch
that may not have taken effect here is distrusted the same way: one made inside a subshell
that has since closed, or aimed elsewhere by a global `-C`, `--git-dir` or `--work-tree`,
leaves the branch as it was. What still cannot be read is refused when it names `commit` or
`push` — matched on word boundaries, so `committee` is not a commit — while `main` is
checked out, and allowed anywhere else.

Within a segment it finds the command name where a shell would, after the prefix of
variable assignments and redirections, so `GIT_EDITOR=true git commit` and
`>log git commit` are seen. Backticks around a substitution are stripped, the executable is
matched without regard to case, and a short list of wrapper programs — `sudo`, `env`,
`time`, `nohup`, `doas` — is stepped over. That list is deliberately incomplete: a wrapper
nobody listed is a miss, which is safe, while scanning a segment for any `git` token would
refuse `echo git commit`, which is the failure this module treats as worse. Only options are
skipped after a wrapper, never a bare word, so an option that takes a value hides what
follows it.

A push's destination is read with the same care. The arguments are walked rather than
filtered, so an option that takes a value — `-o`, `--push-option`, `--repo`,
`--receive-pack`, `--exec` — does not leave its value standing where the remote should be,
and `git push -o ci.skip origin` is seen as the bare push it is. Every ref is then reduced
to the branch it names: a leading `+` dropped, the destination half of a `src:dst` pair
taken, `refs/heads/` stripped, backticks removed and `@` read as `HEAD`. Switch targets go
through the same reduction, so `git checkout refs/heads/main` is a switch to `main`.

A branch switch whose target only the running shell can resolve — `git checkout -`,
`@{-1}` — leaves the branch *unknown* rather than unchanged, and a `commit` or `push` that
meets an unknown branch is refused with a message saying so rather than the one about
`main`. Stdlib only.

| Signature | Description |
|---|---|
| `Segment` | Frozen dataclass: `tokens` and the `separator` that preceded them — one of `SEPARATORS`, a newline, or a grouping delimiter (`""` for the first). |
| `segments(command: str) -> list[Segment] \| None` | Split a command into invocations, or None if it cannot be read. |
| `git_subcommand(tokens: tuple[str, ...]) -> tuple[str, tuple[str, ...]]` | Identify the git subcommand and its arguments. |
| `push_targets_main(args: tuple[str, ...], branch: str) -> bool` | Whether a push would update `main`. |
| `switch_target(subcommand: str, args: tuple[str, ...]) -> str` | The branch a `checkout`/`switch` moves to, `""` when it moves none, or the sentinel `UNRESOLVED` (`"?"`) for a target only the running shell can resolve — `-` and `@{-1}`. |
| `violation(command: str, branch: str) -> str` | The reason to refuse, or `""` to allow. |
| `main() -> None` | Entry point: allow or refuse the command. |

### `.claude/hooks/lint_py.py`

`PostToolUse` hook. Runs `ruff format` and `ruff check --fix` on any `.py` file Claude
writes or edits, and reports unfixable issues back via exit code 2. Stdlib only.

| Signature | Description |
|---|---|
| `find_ruff(project_dir: Path) -> Path \| None` | Locate Ruff in the project venv. |
| `run(ruff: Path, args: list[str]) -> CompletedProcess[str]` | Run Ruff, capturing output. |
| `target_file(payload: dict[str, object], project_dir: Path) -> Path \| None` | Extract the edited `.py` file from the hook payload. |
| `main() -> None` | Entry point: format, fix, report. |

### `.claude/hooks/stop_gate.py`

`Stop` hook. Reads the active plan's step to decide how strict to be: advisory through step
7, blocking from step 8 and whenever no plan is active, and only when a Python file changed
in the tree or on the branch. When it blocks it runs ruff, mypy
and pytest, cross-checks `STRUCTURE.md` against the modules on disk, reports any test file
sitting outside `tests/` where `pytest` would silently never collect it, and reports any
package directory under `src/` missing its `__init__.py`. Bypass with
`.claude/.skip-gate`. Stdlib only.

| Signature | Description |
|---|---|
| `venv_tool(project_dir: Path, name: str) -> Path \| None` | Locate a tool in the project venv. |
| `capture(cmd: list[str], cwd: Path, timeout: int) -> CompletedProcess[str]` | Run a command, capturing output. |
| `changed_python_files(project_dir: Path) -> set[str]` | Python files changed in the tree or on this branch. |
| `tracked_python_files(project_dir: Path) -> set[str]` | All non-ignored Python files. |
| `structure_problems(project_dir: Path) -> list[str]` | File-level drift between this file and disk. |
| `stray_test_files(project_dir: Path) -> list[str]` | Test files outside `tests/`, which pytest never collects. |
| `missing_init_files(project_dir: Path) -> list[str]` | Package directories under `src/` with no `__init__.py`. |
| `gate_failures(project_dir: Path) -> list[str]` | Run the verification set, collect failures. |
| `advisory_notes(project_dir: Path, plan: Plan, changed: set[str]) -> list[str]` | Non-blocking observations for the steps below the gate. |
| `notice(message: str) -> None` | Show the user a message without blocking. |
| `block(reason: str) -> None` | Emit the block decision and exit. |
| `enforce(project_dir: Path) -> None` | Run the verification set and block on failure. |
| `main() -> None` | Entry point: decide whether the turn may end. |
