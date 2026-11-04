# dkvalg: live polling, recording and capture replay

<!-- claude-plan step=3 status=active -->

| Field | Value |
|---|---|
| Feature | `feat/dkvalg-live-polling` (the folder) |
| Round | 1 |
| Branch | `feat/dkvalg-live-polling` |
| Version | `minor` — extends the existing sources and replay with live polling and recording; step 9 adds `1.0.0 → 1.1.0` (major, 2.0.0, was the alternative) |
| Started | 2026-11-04 |

## Progress

| # | Step | Skill | Runs | Status |
|---|---|---|---|---|
| 1 | Conceptualize | `/conceptualize` | with the user | done |
| 2 | Plan | `/plan` | with the user, unless the critique is clean | done |
| 3 | Implement | `/implement` | in `/build` | in progress |
| 4 | Verify | `/verify` | in `/build` | pending |
| 5 | Test | `/test` | in `/build` | pending |
| 6 | Concept check | `/concept-check` | in `/build` | pending |
| 7 | Ship | `/ship` | in `/build` | pending |
| 8 | Recommend | `/recommend` | with the user | pending |
| 9 | Pull request | `/create-pr` | with the user | pending |
| 10 | Review | `/watch-pr` | on the pull request | pending |

Statuses: `pending`, `in progress`, `done`.

## Builds on

Nothing on this branch: this is its first round. It builds on what `main` already holds from `development/feat/dkvalg-folketingsvalg-replay/` (PR #2, version 1.0.0): the model, the Folketingsvalg adapter, `load_election`, `ReplaySource` and the `replay` CLI. This round must not break them.

---

## 1. Concept

### What this is

Live data for `dkvalg`. An **HttpSource** polls DST's Folketingsvalg feeds over HTTPS and returns the same `Election` snapshots that `load_election` builds from files, so everything downstream is source-agnostic. It is polite (conditional requests, a minimum interval, a descriptive User-Agent, timeouts, back-off on errors) and has a blocking API a caller can use from a thread: fetch now and get the current `Election` plus a minimal list of which places changed, and a poll loop with an injectable clock, sleep and transport. A **recorder** can save every feed a poll receives, stamped with its fetch time, into a capture directory; **replay** can play a capture directory back with the true timing, which finally shows real intermediate national, landsdel and storkreds results (the limitation round 1 recorded). Because network input now arrives, the adapter also refuses XML that carries a DOCTYPE or entity declaration. The CLI gains `poll` and `replay` learns capture directories.

### Why it is worth building

Round 1 proved the model on a finished election; the point of the library is the next live one, and a live source is the missing half. Recording during that night is the only way to get a replayable record with real intermediate aggregates, so the recorder has to exist before the election, not after.

### Inputs and outputs

In: an election, given as its DST id (`Valg2546527`), or a URL to its `valgdag.xml` or to the folder holding it; a polling interval; optionally a capture directory. Out: `Election` snapshots (as in round 1) and, per poll, a list of the places that changed (type and id); on the CLI, one line per changed place per poll. A capture directory holds one subfolder per poll that received at least one feed body, named by the UTC fetch time and holding those feeds under their DST file names.

### How it connects to the rest of the repo

Reuses `adapters.folketingsvalg` (`parse_overview`, `parse_place`, `unreported_place`), the model, `sources.directory.load_election` (its result is the correctness reference for HttpSource) and `sources.replay.ReplaySource`; `cli` gains a subcommand. New code is a transport and polling module under `sources/`, plus capture writing and reading. Nothing in the library knows about AppDaemon or Home Assistant; the user's separate project calls it.

### Explicitly out of scope

- AppDaemon / Home Assistant: nothing, now or in this repo.
- Finding the current election's id automatically (scraping `xml.htm`): the id or URL is given. Noted in `DEVELOPMENT.md`.
- `diff.py` and any change detection beyond the per-poll list of changed places.
- EP-valg and folkeafstemning adapters, kommunal-/regionsvalg, fintaelling (`fintal.xml`).
- Threads, asyncio or scheduling inside the library: the caller supplies the thread and the loop's stop signal.
- Network access in tests: tests use a fake transport, or at most a server bound to `127.0.0.1`.

Assumptions (stated, not asked): standard library only (`urllib`, an HTTP client with no dependency); default interval 60 s with a floor of 15 s, because DST updates roughly every two minutes on election night; back-off doubles from the interval to a cap of 5 minutes and resets after a success; fetch times come from the caller's clock in UTC; a capture subfolder is only written for a poll that received at least one 200 body, and the first poll's subfolder therefore holds the overview and every result feed. DST's servers return different ETags for the same unchanged file (observed 2026-11-04: two GETs, two ETags, identical `Last-Modified`), so `Last-Modified` is the dependable validator and a 200 with an unchanged body is treated as "no change". A one-off manual `poll` against the still-served 2026 election is used as evidence at step 6; it is not part of the tests.

### Acceptance criteria

| # | The finished feature... |
|---|---|
| A1 | returns, on a first fetch through a fake transport serving the 2026 fixture set, an `Election` equal to `load_election` of the same files. |
| A2 | sends on later fetches a conditional request for the overview with both `If-None-Match` and `If-Modified-Since` taken from the previous response; a `304`, or a `200` whose body is byte-identical to the previous one, requests no result feed, returns the same `Election` and reports no changed places. |
| A3 | requests, when the overview shows some feeds with a newer `SenestRettet`, only those feeds; the new `Election` differs from the previous only in those places, and the changed list names exactly them by place type and id. |
| A4 | sends the User-Agent `dkvalg/<version> (+https://github.com/petermads123/valg_data)` and a per-request timeout; refuses an interval below 15 s with a `ValueError` naming the value; and on a failed poll (network error, HTTP 5xx, malformed XML) keeps the last good `Election`, reports the error, waits twice as long as before up to 5 minutes, and returns to the normal interval after a success, shown with a fake clock. |
| A5 | provides a poll loop that, per cycle, hands the caller the `Election`, the changed list and any error, stops when the caller says so or after a given number of cycles, and in tests neither sleeps nor touches the network. |
| A6 | records, when asked, every poll that received a 200 body into a UTC-time-named subfolder of the capture directory, and replays a capture directory with one snapshot per recorded poll in fetch-time order, gaps between fetch times scaled by the speed; in a recording where the national result changes between two polls, the earlier snapshot shows the earlier national figures; the last snapshot equals the election as last fetched. |
| A7 | runs `python -m dkvalg poll <id-or-url> [--interval N] [--record DIR] [--cycles N]`, printing one line per changed place per poll, and `python -m dkvalg replay <dir>` on either a plain feed directory (exactly as in round 1) or a capture directory; bad arguments exit 2 and feed or fetch errors exit 1 with `error:` on stderr. |
| A8 | refuses, in the overview and in any result feed, XML containing a DOCTYPE or entity declaration with a `FeedError` naming the file, before anything is expanded, while every 2026 fixture still parses; the `DEVELOPMENT.md` note "Harden XML parsing before live polling" is deleted. |
| A9 | leaves round 1's behaviour untouched: `load_election`, `ReplaySource` on a plain feed directory and their CLI output are as before, shown by the existing 696 tests passing unchanged. |

### Open questions

None.

---

## 2. Plan

> Written in step 2, accepted before step 3 starts — by the user, or by a clean critique
> (see `/plan`). Concrete enough that step 3 is transcription, not invention.

### Approach

Two new modules under `sources/` plus small changes to four existing ones. **`sources/http_source.py`** holds the transport, the URL rules, `HttpSource` and the poll loop; **`sources/capture.py`** holds the `Recorder`, the capture-directory reader and `CaptureReplay`. `load_election`'s assembly step is lifted into a public `build_election(overview_xml, read_feed)` so that three callers share one definition of "an `Election` from an overview and its feeds": `load_election` (files), `CaptureReplay` (accumulated captured bodies) and `HttpSource` (its held bodies), so the three agree by construction. `Election.changed_since` is the single definition of "what changed" and is used by `HttpSource` and `CaptureReplay` alike. The HTTP layer is a tiny `Transport` callable (`url, headers, timeout` in, `HttpResponse` out) so tests inject a fake and the default is `urllib`. `HttpSource.fetch` is one blocking call with all its state under a lock; `poll` is a generator the caller drives from its own thread. A fetch is **atomic**: it builds its result in locals, writes the capture, and only then commits its state, so any failure (network, parse, or the recorder) leaves the last good `Election` and the held bodies untouched and the next fetch simply tries again. The planner's call, made under the user's instruction not to wait, is that the integrity of the record wins over liveness: if the disk fails, fetches fail, and `poll` still hands the caller the last good `Election` with the error.

Rejected: (a) putting capture playback into `ReplaySource` (it reveals one place per step by `last_changed`; a capture step reveals many places at a fetch time, so one class would carry two time models) at the cost of one more class; (b) a general `Source` protocol shared by directory, replay, HTTP and capture, which would be speculative before the Home Assistant side shows which shape it wants; (c) an async or threaded poller inside the library, ruled out by the concept; (d) rejecting DOCTYPE by sniffing bytes, which a UTF-16 document slips past, in favour of an `expat` pre-scan with a handler on the doctype declaration. (`ET.XMLParser` exposes no `.parser` hook in this CPython, so the scan is a separate pass; checked on 2026-11-04: it refuses a billion-laughs payload and a UTF-16 DOCTYPE and passes all 109 fixtures.)

Survey: reused unchanged are the model, `parse_overview`/`parse_place`/`unreported_place`, `FeedRef`, `ReplayStep`/`ReplaySource` and the whole round 1 test suite. `FeedRef.file_name` is the last URL segment; a feed's URL is built as the overview's folder URL plus `file_name`, which holds for every DST election seen (all feeds sit next to `valgdag.xml`), and a `file_name` that is not a plain `*.xml` file name is refused (it would otherwise let a hostile overview write outside the capture directory).

### Modules

| Path | New or changed | Purpose |
|---|---|---|
| `src/dkvalg/errors.py` | changed | `FetchError(FeedError)` for network and HTTP failures |
| `src/dkvalg/model.py` | changed | `Election.changed_since` (A3, A6) |
| `src/dkvalg/adapters/folketingsvalg.py` | changed | Refuse DOCTYPE / entity declarations in `parse_overview` and `parse_place` (A8); no signature change |
| `src/dkvalg/sources/directory.py` | changed | Extract `build_election` from `load_election`; behaviour unchanged (A1, A6, A9) |
| `src/dkvalg/sources/http_source.py` | new | Transport, `overview_url`, `HttpSource`, `poll` (A1 to A5) |
| `src/dkvalg/sources/capture.py` | new | `Recorder`, `CaptureReplay`, `is_capture_directory` (A6) |
| `src/dkvalg/cli.py` | changed | `poll` subcommand; `replay` accepts a capture directory (A7) |
| `src/dkvalg/__init__.py` | changed | Re-export the new public names |
| `tests/conftest.py` | changed | A fake transport serving a directory, mutation helpers (step 5) |
| `tests/test_http_source.py`, `tests/test_capture.py` | new | (step 5) |
| `tests/test_model.py`, `test_folketingsvalg.py`, `test_directory.py`, `test_cli.py`, `test_errors.py`, `test_package.py` | changed | New cases only; existing cases untouched (step 5) |
| `DEVELOPMENT.md` | changed | Delete "Harden XML parsing before live polling" (A8) and "Faithful replay needs recorded live captures" (A6) |
| `README.md`, `STRUCTURE.md` | changed | Usage for `poll`, capture replay; structure map |
| `pyproject.toml` | untouched | Step 9 writes the version |

### Public API

Existing signatures not listed here do not change.

| Signature | Module | Purpose | Covers |
|---|---|---|---|
| `class FetchError(FeedError)` | `errors` | A request failed: network error, timeout, oversize body or an unexpected HTTP status; the message names the URL and the cause | A4, A7 |
| `Election.changed_since(self, previous: Election \| None) -> tuple[Place, ...]` | `model` | The places of this election that have a `last_changed` and are not equal to the place with the same type and id in `previous` (or are absent from it), in this election's order; every such place when `previous` is `None` | A1, A3, A6 |
| `build_election(overview_xml: bytes, read_feed: Callable[[str], bytes]) -> Election` | `sources.directory` | `parse_overview`, then `parse_place` of `read_feed(ref.file_name)` for every feed with a `last_changed` and `unreported_place` for the rest | A1, A6, A9 |
| `DEFAULT_INTERVAL: Final[float] = 60.0`, `MIN_INTERVAL: Final[float] = 15.0`, `MAX_BACKOFF: Final[float] = 300.0` | `sources.http_source` | Seconds | A4 |
| `@dataclass(frozen=True, slots=True) class HttpResponse`: `status: int`, `headers: Mapping[str, str]`, `body: bytes` | `sources.http_source` | One response; header names lower-case | A2 |
| `class Transport(Protocol)`: `__call__(self, url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse` | `sources.http_source` | What `HttpSource` needs from HTTP; a 304 and any other status are returned, not raised | A2, A4 |
| `urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse` | `sources.http_source` | The default `Transport`: `urllib.request`. `HTTPError` is caught first and returned as a response (its body read under the same cap); then `URLError`, `OSError` and `http.client.HTTPException` (which includes a truncated body) become `FetchError` naming the URL; a body over 10 MB is a `FetchError` | A4 |
| `user_agent() -> str` | `sources.http_source` | `dkvalg/<installed version> (+https://github.com/petermads123/valg_data)`; when the package metadata is not installed (`PackageNotFoundError`, as under `PYTHONPATH=src`) the version reads `unknown` | A4 |
| `overview_url(location: str) -> str` | `sources.http_source` | An id such as `Valg2546527`, a folder URL, or a URL ending `valgdag.xml` becomes the overview URL; `ValueError` naming the value for anything else, including schemes other than http and https | A7 |
| `utc_now() -> datetime` | `sources.http_source` | The default clock: timezone-aware UTC | A4, A5, A6 |
| `@dataclass(frozen=True, slots=True) class FetchResult`: `election: Election`, `changed: tuple[Place, ...]`, `fetched_at: datetime` | `sources.http_source` | One successful fetch | A1, A3 |
| `class HttpSource`: `__init__(self, location: str, *, transport: Transport = urllib_transport, recorder: Recorder \| None = None, timeout: float = 20.0, clock: Callable[[], datetime] = utc_now) -> None`; properties `election(self) -> Election \| None` and `clock(self) -> Callable[[], datetime]`; `fetch(self) -> FetchResult` | `sources.http_source` | Blocking source; `ValueError` for a bad `location` or a `timeout` that is not finite and positive; `fetch` raises `FetchError` or `FeedError` and leaves state and held bodies untouched; calls are serialised by a lock | A1 to A4 |
| `@dataclass(frozen=True, slots=True) class PollCycle`: `number: int`, `at: datetime`, `election: Election \| None`, `changed: tuple[Place, ...]`, `error: FeedError \| None`, `wait: float` | `sources.http_source` | One cycle of the loop; `election` is the last good one (`None` before the first success); `wait` is the seconds slept before the next cycle | A4, A5 |
| `poll(source: HttpSource, *, interval: float = DEFAULT_INTERVAL, max_cycles: int \| None = None, stop: Callable[[], bool] \| None = None, sleep: Callable[[float], None] = time.sleep) -> Iterator[PollCycle]` | `sources.http_source` | The poll loop, a plain function that validates and returns a private generator: `ValueError` at call time unless `interval` is finite and at least `MIN_INTERVAL`, and if `max_cycles < 1`; each cycle is stamped with `source.clock()` | A4, A5 |
| `class Recorder`: `__init__(self, directory: Path) -> None`; `record(self, fetched_at: datetime, feeds: Mapping[str, bytes]) -> Path` | `sources.capture` | Creates `directory` (parents included) on the first record and writes `directory/<UTC fetch time>/<file name>` for each feed, atomically (see Capture layout); `ValueError` for a naive `fetched_at` or no feeds; `FeedError` for an unsafe file name, a target folder that already exists, or an I/O failure |
| `check_feed_name(name: str) -> str` | `sources.capture` | Returns `name` if it matches `^[A-Za-z0-9_-]+\.xml$` and is not `valgdag.xml`, else raises `FeedError` naming it; the one rule used by `HttpSource` before it builds a URL and by `Recorder` before it writes | A6 | A6 |
| `@dataclass(frozen=True, slots=True) class CaptureStep`: `at: datetime`, `changed: tuple[Place, ...]`, `election: Election`; property `progress(self) -> CountingProgress` | `sources.capture` | One recorded poll replayed | A6, A7 |
| `class CaptureReplay`: `__init__(self, directory: Path, *, speed: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> None`; `__iter__(self) -> Iterator[CaptureStep]` | `sources.capture` | Replays a capture directory; `ValueError` unless `speed` is positive and not NaN (`inf` never waits); `FeedError` for a directory with no captures, a bad folder, or a first capture that is not a complete election | A6 |
| `is_capture_directory(directory: Path) -> bool` | `sources.capture` | True if the directory has no `valgdag.xml` and at least one subfolder named like a capture | A7 |
| `run(argv: Sequence[str] \| None = None, *, out: TextIO \| None = None, err: TextIO \| None = None, sleep: Callable[[float], None] = time.sleep, transport: Transport = urllib_transport, clock: Callable[[], datetime] = utc_now) -> int` | `cli` | As round 1, plus `poll` | A7 |

`dkvalg/__init__.py` additionally re-exports `FetchError`, `HttpSource`, `FetchResult`, `PollCycle`, `poll`, `Recorder`, `CaptureReplay` and `CaptureStep`; the transport pieces, `overview_url`, `user_agent`, `utc_now`, the constants, `build_election` and `is_capture_directory` stay in their modules.

Behaviour the signatures do not carry:

- **`HttpSource.fetch`.** The source holds, per file name, `(the overview's last_changed when it was fetched, the accepted body, ETag, Last-Modified)`, plus the last accepted overview body and its election. (1) GET the overview with `User-Agent`, `Accept: text/xml`, and `If-None-Match` / `If-Modified-Since` from the previous 200 when it carried `ETag` / `Last-Modified`. (2) A 304 returns the held election with `changed=()` and records nothing. A 200 whose body equals the held overview body also returns the held election with `changed=()`, but the received body is still recorded (`{"valgdag.xml": body}`), as the concept says every 200 body is. (3) Otherwise `parse_overview`; every `ref.file_name` goes through `check_feed_name` before any request. For each feed with a `last_changed`: if the held entry exists with the same overview `last_changed`, no request; else GET it with its own validators, where a 304 or an identical body keeps the held body and any other 200 replaces it. Feeds with no `last_changed` hold nothing. Held entries for feeds no longer listed are dropped. A 304 where nothing is held cannot happen (validators are only sent for held bodies) and is a `FetchError` if it does. (4) Build the new `Election` with `build_election(overview_body, held_bodies.__getitem__)` over the merged bodies, compute `changed = new.changed_since(old)`, call the recorder once with every 200 body received in this fetch, and **only then** commit the new state. The first fetch holds nothing and fetches everything. Any status other than 200 or 304 is a `FetchError` naming the status and URL; a parse error is the adapter's `FeedError`. A feed URL is the overview's folder plus `file_name`.
- **Why both validators.** DST's IIS nodes return different ETags for the same unchanged file (observed 2026-11-04), so an ETag from one node can miss on another and produce a 200; the byte comparison in step (2) is what keeps that from counting as a change.
- **`poll`.** Per cycle: stamp `at = source.clock()`, then `fetch()`; on success `wait = interval`; on `FeedError` the cycle carries `error`, the last good `election` and `changed=()`, and `wait = min(previous_wait * 2, max(MAX_BACKOFF, interval))` where `previous_wait` starts at `interval` (so 120, 240, 300, 300 at the default); the next success resets `wait` to `interval`. Yield the cycle; stop if `stop()` is true or `max_cycles` is reached; else `sleep(wait)`. Never sleeps after the last cycle.
- **Capture layout.** `directory/<YYYYMMDDTHHMMSS.ffffffZ>/<DST file name>`. A folder is written as `.tmp-<name>` and renamed once complete, after checking that the final name does not exist (a rename onto an empty directory would otherwise succeed silently), so a folder is either complete or absent and a leftover `.tmp-*` from a crash is never mistaken for a capture. `CaptureReplay` and `is_capture_directory` look only at entries whose names match `^\d{8}T\d{6}\.\d{6}Z$` and ignore everything else; a matching name that is not a valid UTC time, or a matching entry that is not a directory, is a `FeedError` naming it. `CaptureReplay` orders folders by name, accumulates files (a later folder's file replaces an earlier one's), and after each folder builds an `Election` with `build_election(overview_bytes, read_feed)`; the first folder must hold the overview and every reported feed. A step's `changed` is `election.changed_since(previous)` (all reported places on the first step). It sleeps `gap_seconds / speed` before each step after the first, only when above zero. Iterating again restarts; bodies are read per step, not up front.
- **Hardening.** `_parse_xml` first runs an `expat` parser with handlers on the doctype and entity declarations over the bytes, so a document declaring either raises `FeedError("... contains a DOCTYPE or entity declaration")` naming the file, before `ElementTree` parses it; an `ExpatError` in that pass is left for `ElementTree` to report as today.
- **CLI.** `poll <id-or-url> [--interval N] [--record DIR] [--cycles N]`: `--interval` is a finite float at least `MIN_INTERVAL` (argparse error, exit 2, otherwise; `nan` and `inf` included), default `DEFAULT_INTERVAL`; one line per changed place per cycle, `<at ISO> <counted/total> <place type> <name>`; a failed cycle prints `error: <message>` to `err` and the loop continues; the exit code is 1 if the last cycle failed or the location is rejected by a `FeedError`, 2 for a bad `location` or arguments, 130 on Ctrl-C, else 0. `replay <dir>` uses `CaptureReplay` when `is_capture_directory(dir)` and prints one line per changed place per step plus the final national table; otherwise it is exactly round 1.

### Implementation guide

1. `FetchError`; `Election.changed_since`; extract `build_election` and make `load_election` call it (round 1 tests unchanged and green).
2. XML hardening in `_parse_xml`; delete the two resolved `DEVELOPMENT.md` entries ("Harden XML parsing before live polling", "Faithful replay needs recorded live captures").
3. `sources/http_source.py`: constants, `HttpResponse`, `Transport`, `urllib_transport`, `user_agent`, `utc_now`, `overview_url`.
4. `Recorder` in `sources/capture.py`.
5. `HttpSource` and `FetchResult` (with the recorder call and the lock), then `PollCycle` and `poll`.
6. `CaptureStep`, `CaptureReplay`, `is_capture_directory`.
7. CLI: `poll`, capture-aware `replay`, the new `run` keywords.
8. `__init__` re-exports; README usage and `STRUCTURE.md`; showcases in the two new modules (fixtures served through an in-memory transport; no network). Add to `DEVELOPMENT.md` one note on the choice that a recorder failure fails the fetch (the alternative is to keep fetching and rewrite every held body at the next successful record) and, after the step 6 live check, one on how often DST answers 304 when both validators are sent.

### Test intents

| # | Must prove | Covers |
|---|---|---|
| T1 | A first `fetch` through a fake transport serving the 2026 fixtures returns an `Election` equal to `load_election` of the same directory, reports every reported place as changed, and sends `User-Agent` and a timeout on every request | A1, A4 |
| T2 | A second `fetch` sends only the overview request, with both validators; a 304 and a 200 with an unchanged body and a different ETag each return the same election and `changed == ()` and no result feed is requested; the 304 records nothing and the identical-body 200 records a folder holding only `valgdag.xml` | A2, A6 |
| T3 | After changing three feeds' bodies and their overview timestamps, only those three are requested, the new election differs from the old exactly there, and `changed` names exactly them; a feed going from never reported to reported is fetched | A3 |
| T4 | `interval < 15` is a `ValueError`; a failed poll (network error, 500, 404, malformed overview, malformed feed, a DOCTYPE feed) leaves the last good election, the recorder and held state untouched and produces `error` in the cycle; waits are 120, 240, 300, 300 then 60 after a success, with a fake sleep; a failure after some feeds were fetched changes nothing and the next fetch refetches them; a recorder that raises on fetch N leaves the election, validators and held bodies as before and fetch N+1 refetches and records the full set; an overview listing `C:x.xml`, `a#b.xml` or `valgdag.xml` as a feed raises `FeedError` and requests nothing; `timeout` of `nan`, `inf`, `0` and `-1` is a `ValueError`; `user_agent()` reads `unknown` when the metadata is missing (monkeypatched) | A4, A6 |
| T5 | `poll` yields numbered cycles with `election`, `changed`, `error`, `wait`; stops on `stop()` and on `max_cycles`; never sleeps after the last cycle; bad arguments (`interval` of `14.9`, `nan`, `inf`; `max_cycles` of `0`) raise at call time, before any iteration; each cycle's `at` comes from `source.clock()`; nothing sleeps or touches the network in tests | A5 |
| T6 | `urllib_transport` against a server bound to `127.0.0.1`: returns 200 with headers lower-cased, turns 304 and 500 into responses, turns refused connection, timeout, an oversize body and a body shorter than its `Content-Length` into `FetchError`; `overview_url` accepts an id, a folder URL, `.../valgdag.xml` and a localhost `http` URL, and rejects `file://`, `ftp://`, empty and junk with a `ValueError` naming the value | A4, A7 |
| T7 | `Recorder` writes the UTC-named folder with the given files, atomically (no partial folder after a failure), and refuses a naive time, no feeds, an unsafe file name (`../x.xml`, `a/b.xml`, no `.xml`) an existing folder and `C:x.xml`, and leaves no `.tmp-*` folder behind after a failure; `check_feed_name` accepts every real fixture name and rejects the unsafe ones | A6 |
| T8 | An `HttpSource` run over a scripted sequence of fake-transport states with a recorder, replayed with `CaptureReplay`: one step per recorded fetch in time order; an intermediate step shows the earlier national figures; the last step's election equals the last fetch's; sleeps are the gaps divided by speed, none at `inf`; bad speed is a `ValueError`; an empty directory and a first capture missing a feed are `FeedError`s; a leftover `.tmp-*` folder and other non-matching entries are ignored, while a matching name that is not a valid time, or a matching file, is a `FeedError`; restart gives the same steps; the identical-body capture gives a step with `changed == ()` | A6 |
| T9 | CLI `poll` with an injected transport, sleep and clock: prints the lines, honours `--cycles`, writes captures with `--record`, exits 2 for `--interval 5`, `--interval nan`, `--interval inf` or a bad location, 1 when the last cycle failed with `error:` on stderr; `replay` on a capture directory uses capture replay and on a plain directory is unchanged; `is_capture_directory` is true only for a capture directory | A7 |
| T10 | A feed or overview with a DOCTYPE, an entity declaration, a billion-laughs payload, an external entity, or a UTF-16 DOCTYPE raises `FeedError` naming the file in `parse_overview` and `parse_place`; all 109 fixtures still parse; `DEVELOPMENT.md` no longer has the "Harden XML parsing" heading | A8 |
| T11 | `Election.changed_since`: `None` gives every reported place; an equal election gives `()`; a changed, a new and a removed place; order follows the current election; `build_election` equals the old `load_election` on the fixtures and propagates `read_feed` errors | A3, A6, A9 |
| T12 | The whole round 1 suite passes unchanged; two threads calling `fetch` at once never run it concurrently | A9, A4 |

### Risks

- **The server's behaviour is only partly knowable offline.** The fake transport reproduces what was observed on 2026-11-04 (ETag and Last-Modified, 304 on a match, ETag varying between nodes). If the build finds `urllib` handles a header differently from that model, adapt the transport, not the criteria. A one-off live check against the still-served 2026 election is step 6 evidence and may be replaced by a loopback server if the network is blocked there; that is not a halt.
- **304s may be rare.** RFC 9110 has a server ignore `If-Modified-Since` when `If-None-Match` is present, and DST's per-node ETags make a mismatch likely, so a poll may often get the full overview as a 200. Correctness holds (the byte comparison catches it); only politeness suffers. The build keeps both validators as A2 requires; the step 6 live check records how often a 304 actually comes back, and whether to drop `If-None-Match` is a later decision noted in `DEVELOPMENT.md`, not a halt.
- **Feed URLs.** Built from the overview's folder plus `file_name`. If a real overview ever lists a feed in another folder or host it would fetch the wrong URL; this is accepted for now and noted if the build sees it in the fixtures (it does not).
- **Time zones.** `Place.last_changed` stays naive Danish local time; fetch times and capture folder names are timezone-aware UTC. `CaptureStep.at` and `ReplayStep.at` therefore differ in kind, and nothing compares across them. If the build finds code doing so, fix it there.
- **Capture size.** One folder per fetch with every 200 body, including identical ones (the concept). A busy night is tens of megabytes; accepted.
- **Hardening.** If the `expat` pre-scan rejects any real fixture, **halt**: that would mean real DST files carry a DOCTYPE and A8 needs a decision. (Checked: none of the 109 do.)
- **Changing `run`'s signature.** Adds two keyword-only parameters with defaults; existing callers are unaffected.
- **Version metadata.** `user_agent()` reads the installed version, which for an editable install is fixed at install time; tests compare against the same lookup, so a stale install cannot make them disagree.

### Critique

Plan-critic findings (verdict: accept with the changes below), 2026-11-04.

1. **Recorder failure left state committed.** Applied: the recorder runs before the state commit, so a failed capture fails the fetch and the next fetch refetches and records; test added to T4. The finding also raised a question for the user (keep data flowing on a disk failure instead); the planner decided for record integrity under the user's standing instruction not to wait, and records the alternative in `DEVELOPMENT.md`.
2. **Identical-body 200 not recorded.** Applied: it returns unchanged but records `{"valgdag.xml": body}`; T2 and T8 updated.
3. **`HttpSource` did not go through `build_election`.** Applied: it holds bodies and builds every election with `build_election`; a 304 with nothing held is a `FetchError`.
4. **`poll` validates lazily; NaN and inf slip through.** Applied: a plain function validating with `isfinite`, returning a private generator; same for `timeout` and the CLI interval; T4, T5, T9.
5. **Temporary folder and bad folder undefined.** Applied: `.tmp-<name>`, a name pattern, ignore non-matching entries, existence checked before rename, directory created on first record; T7 and T8.
6. **`user_agent()` without installed metadata.** Applied: version `unknown` on `PackageNotFoundError`; test in T4.
7. **Denylist file-name rule.** Applied: one allowlist `check_feed_name` shared by `HttpSource` and `Recorder`; T4 and T7.
8. **`urllib_transport` exceptions unnamed.** Applied: the order and the exception set are spelled out; truncated-body case in T6.
9. **Two clocks.** Applied: `poll` has no clock; it uses `source.clock()`, now a property.
10. **Second resolved `DEVELOPMENT.md` entry.** Applied: both entries are deleted in step 2 of the guide.
11. **If-None-Match defeats If-Modified-Since.** Applied as a Risk and a step 6 measurement; the validators stay as A2 requires.

Accepted: by delegation, 2026-11-04. The user said "continue, don't wait for my permission"; the critic marked finding 1 as containing a question for the user, which the planner resolved on that basis (see 1). The user can still interrupt or redirect.

---

## 3. Implementation notes

> Written in step 3. Only deviations from the plan above, each with its reason. "Built as
> planned" is a complete and good entry. On a fix round, also the reproduction test's red
> run, pasted here before the fix was written — step 6 cites it.

---

## 4. Verification log

> Written in step 4: the static half. Command output, not a summary of it.

| Check | Result |
|---|---|
| `ruff check .` | |
| `ruff format --check .` | |
| `mypy` | |
| Plan completeness | every signature in the Public API table exists as written |
| `STRUCTURE.md` | in sync |
| `python -m <package>.<module>` | |

---

## 5. Test log

> Written in step 5: the dynamic half.

| Intent | Test names | Result |
|---|---|---|

Edge cases considered and deliberately skipped, with reasons:

---

## 6. Concept check

> Written in step 6, against section 1 — not against section 2. The question is whether
> the thing built is the thing agreed, not whether it matches the plan.

| # | Criterion | Met | Evidence |
|---|---|---|---|
| A1 | | | |

Drift found, and what was done about it:

### Earlier rounds still hold

> Later rounds only. Re-check every acceptance criterion from every earlier round in this
> folder: this round changed code they depend on, and their tests passing is necessary but
> not sufficient — a criterion can be satisfied by tests that no longer describe what the
> feature does.

| Round | # | Criterion | Still met | Evidence |
|---|---|---|---|---|

---

## 7. Ship log

| Field | Value |
|---|---|
| Commits | |
| Pushed to | |

---

## 8. Recommendations

> Written in step 8. Only follow-ups that are critical and belong to this work, which most
> rounds do not have: replace the table with `None.` when there are none. Lesser ideas are
> one-line notes in `DEVELOPMENT.md`, not rows here. Not bugs in what this round built —
> those go back through `/build` before the pull request. A critical defect outside what
> section 1 promised, such as a class member it put out of scope, is a recommendation here,
> and its round opens through `/fix`.

| # | Recommendation | Why it is critical | Effort | Decision |
|---|---|---|---|---|
| R1 | | | | |

Decisions: `deferred`, `rejected`, or `next round` — a new numbered file in this folder,
taken back through steps 1 to 7 on the same branch.

---

## 9. Pull request

> Written in step 9, in the commit that opens the pull request — so the URL is not known
> yet and the pull request is found from the branch. The review itself is recorded on the
> pull request thread, not here: this file is `done` from step 9 on.

| Field | Value |
|---|---|
| URL | opened by step 9 — see the branch's pull request |
| Opened as | ready for review |

---

## Halted

> Only if the build stopped. Written by `/build`: the step, the reason verbatim from the
> step that halted, the question for the user — and, once answered, the answer and what
> changed because of it. Never deleted; it is the record of where the plan was thinner
> than the code needed.
