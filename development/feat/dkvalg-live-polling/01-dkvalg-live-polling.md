# dkvalg: live polling, recording and capture replay

<!-- claude-plan step=8 status=active -->

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
| 3 | Implement | `/implement` | in `/build` | done |
| 4 | Verify | `/verify` | in `/build` | done |
| 5 | Test | `/test` | in `/build` | done |
| 6 | Concept check | `/concept-check` | in `/build` | done |
| 7 | Ship | `/ship` | in `/build` | done |
| 8 | Recommend | `/recommend` | with the user | in progress |
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
| `check_feed_name(name: str) -> str` | `sources.capture` | Returns `name` if it matches `^[A-Za-z0-9_-]+\.xml$` and is not `valgdag.xml`, else raises `FeedError` naming it; the one rule used by `HttpSource` before it builds a URL and by `Recorder` before it writes | A6 |
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

Built as planned, with these small additions (none touches an acceptance criterion):

- `CaptureReplay` raises its `FeedError`s (no captures, bad folder, incomplete first capture) when iteration starts, not in `__init__`, because the directory is read per iteration so a restart sees new folders; only `ValueError` for `speed` is raised at construction. Documented in its docstring.
- `_Held` (private) keeps, per feed, the overview timestamp it was fetched at, the body and the validators. On a feed 304 the held body is kept and its timestamp moved forward; on an identical 200 body the validators are refreshed. An identical-body 200 of the overview also refreshes the overview validators.
- The CLI prints changed places with the round 1 line format (`<time>  <counted/total>  <type> <name>`, two spaces, progress right-aligned) for `replay` on both kinds of directory and for `poll`, so all three share one helper.
- `overview_url` accepts an id made of letters, digits, `_` and `-`; an http(s) URL with a query or fragment is refused.
- Live sanity run (network reachable): `python -m dkvalg poll Valg2546527 --cycles 2 --interval 15` printed 107 lines for cycle 1 (counted 92/92) and none for cycle 2, exit 0. A separate probe of four consecutive fetches saw overview responses 200 (unconditional), 200, 304, 200 with both validators sent: DST answers 304 only some of the time, as the plan's Risks expected; noted in `DEVELOPMENT.md`.
- `DEVELOPMENT.md`: the two resolved entries deleted; added "A recorder failure fails the fetch" and "How often DST answers 304 to both validators".
- Existing suite: 696 passed unchanged. `ruff check .`, `ruff format --check .`, `mypy` clean; all showcases run.

Step 5 additions (production fixes the tests exposed; none changes an acceptance criterion or a public signature, details in section 5):

- **One clock read per poll cycle (refines the plan text).** The plan had `poll` stamp `at = source.clock()` and `fetch` read the clock again for `fetched_at`, so the printed time, the capture folder name and a scripted clock's consumption disagreed. Now `poll` reads `source.clock()` once and passes that time to a private `HttpSource._fetch_at`; `fetch()` still reads the clock once itself. `PollCycle.at` therefore equals `FetchResult.fetched_at` and the capture folder time on success and on failure. A1 to A7 are unaffected.
- `urllib_transport` compares the body length with `Content-Length` (except for 204 and 304), because `http.client` returns a short read without raising.
- `overview_url` also refuses credentials, a bad port, non-ASCII, whitespace and control characters, and normalises `valgdag.xml/` and any case of `valgdag.xml`.
- `check_feed_name` refuses `valgdag.xml` in any letter case; `Recorder.record` refuses a body that is not `bytes` and removes its `.tmp-*` folder after any exception, not only `OSError`.
- Empty `ETag`/`Last-Modified` are not sent back; `timeout`, `interval` and `max_cycles` refuse bools and `max_cycles` must be an `int`; the capture folder pattern matches ASCII digits only.

---

## 4. Verification log

> Written in step 4: the static half. Command output, not a summary of it.

| Check | Result |
|---|---|
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `59 files already formatted` |
| `mypy` | `Success: no issues found in 29 source files` |
| `pytest` | `696 passed in 6.47s` (round 1 suite unchanged, A9) |
| Plan completeness | every signature in the Public API table exists as written (see below) |
| `STRUCTURE.md` | in sync (see auditor note below) |
| `python -m dkvalg.<module>` | all seven showcases exit 0 and print readable output (see below) |

**Plan completeness.** Checked by `inspect.signature`, `dataclasses.fields` and `isinstance(..., property)` on the code as it stands, not by reading it:

| Row | Result |
|---|---|
| `FetchError(FeedError)` | present, MRO `FetchError, FeedError, Exception` |
| `Election.changed_since(self, previous: Election \| None) -> tuple[Place, ...]` | present as planned |
| `build_election(overview_xml: bytes, read_feed: Callable[[str], bytes]) -> Election` | present as planned |
| `DEFAULT_INTERVAL`, `MIN_INTERVAL`, `MAX_BACKOFF` | `Final[float]`, 60.0 / 15.0 / 300.0 |
| `HttpResponse` | frozen, slots; `status: int`, `headers: Mapping[str, str]`, `body: bytes` |
| `Transport(Protocol)` | `_is_protocol` true; `__call__(self, url, headers, timeout) -> HttpResponse` |
| `urllib_transport`, `user_agent`, `overview_url`, `utc_now` | signatures as planned |
| `FetchResult` | frozen, slots; `election`, `changed`, `fetched_at` |
| `HttpSource` | `__init__` keyword-only `transport=urllib_transport, recorder=None, timeout=20.0, clock=utc_now`; `election` and `clock` are properties; `fetch(self) -> FetchResult` |
| `PollCycle` | frozen, slots; `number, at, election, changed, error, wait` with the planned types |
| `poll` | keyword-only `interval=60.0, max_cycles=None, stop=None, sleep=time.sleep`, returns `Iterator[PollCycle]` |
| `Recorder` | `__init__(self, directory: Path)`, `record(self, fetched_at, feeds) -> Path` |
| `check_feed_name(name: str) -> str` | present as planned |
| `CaptureStep` | frozen, slots; `at, changed, election`; `progress` property returns `CountingProgress` |
| `CaptureReplay` | `__init__(self, directory, *, speed=1.0, sleep=time.sleep)`, `__iter__ -> Iterator[CaptureStep]` |
| `is_capture_directory(directory: Path) -> bool` | present as planned |
| `cli.run(...)` | new keyword-only `transport=urllib_transport, clock=utc_now` after `sleep` |
| `dkvalg/__init__` re-exports | `FetchError, HttpSource, FetchResult, PollCycle, poll, Recorder, CaptureReplay, CaptureStep` present; `Transport, HttpResponse, overview_url, user_agent, utc_now, the constants, build_election, is_capture_directory, check_feed_name, urllib_transport` are not at the top level |

No Missing rows. No Unplanned public names: the public names defined in `http_source` and `capture` are exactly the planned ones (plus `main`). Section 3's deviations (errors of `CaptureReplay` raised at iteration, private `_Held`, shared CLI line helper, `overview_url` id charset and query/fragment refusal) change no row of the Public API table, so section 2 needs no correction. The only plan-table edit made here is a typo in the `check_feed_name` row, whose Covers cell read `A6 | A6 |`.

**Structure auditor.** Its report claimed 11 places of drift; it had read the stale copy of `STRUCTURE.md` injected into the session. Checked against the file on disk: every claim is already satisfied (sections for `sources/http_source.py` and `sources/capture.py` with all planned names and constants, `FetchError`, `Election.changed_since`, `build_election`, the new `run` signature and exit codes 0/1/2/130, the extended `__init__` re-export list and the "stays in their modules" list, DOCTYPE prose for the adapter, package intro). Its finding of no code-versus-plan drift is confirmed by the introspection above. No edit to `STRUCTURE.md` was needed; the test files for the two new modules are deliberately not listed until step 5 creates them.

**Showcases.** `errors`, `model`, `adapters.folketingsvalg`, `sources.directory`, `sources.http_source`, `sources.capture`, `sources.replay`: exit 0, each preceded by the expected `RuntimeWarning`. `http_source` prints the overview URL, the user agent, `cycle 1: 107 places changed`, `cycle 2: 0 places changed`, `requests: 109, sleeps (seconds): [60.0]` and the interval-below-floor error; `capture` prints a capture directory with two steps (`107 changed, 92/92` then `0 changed, 92/92`), `sleeps (seconds): [2.0]` and the unsafe-name error. Both bind their inputs to named variables with the accepted-values comment. `python -m dkvalg` prints usage (`{replay,poll}`) with exit 0; `python -m dkvalg replay tests/fixtures/folketingsvalg_2026 --speed inf` prints the national table, exit 0.

---

## 5. Test log

> Written in step 5: the dynamic half.

Suite: 1301 passed (696 round 1 tests unchanged plus 605 new); `ruff check .`, `ruff format --check .`, `mypy` clean. No test touches the external network (fake transport, or a server bound to `127.0.0.1`). Existing test files only gained new cases and import names; no existing case was edited or removed.

| Intent | Test names (in `tests/test_http_source.py` unless a file is named) | Result |
|---|---|---|
| T1 first fetch equals `load_election`, all places changed, UA and timeout on every request | `test_first_fetch_equals_load_election_of_the_same_files`, `test_first_fetch_reports_every_reported_place_as_changed`, `test_first_fetch_requests_the_overview_then_each_listed_feed_once`, `test_first_fetch_sends_no_conditional_header_anywhere`, `test_every_request_carries_the_user_agent_accept_and_the_timeout[20.0/7.5]`, `test_the_default_timeout_is_twenty_seconds`, `test_fetch_reads_the_clock_once_per_call_and_reports_that_time` | pass |
| T2 second fetch: overview only, both validators; 304 and identical 200 with new ETag; recordings | `test_second_fetch_sends_only_the_overview_with_both_previous_validators`, `test_an_unchanged_overview_returns_the_same_election_and_no_changes[304/200-same-body-new-etag]`, `test_an_identical_200_without_any_validators_is_also_no_change`, `test_a_304_records_nothing_and_an_identical_200_records_only_the_overview`, `test_the_new_etag_of_an_identical_200_is_the_one_sent_next`, `test_only_the_validators_a_response_carried_are_sent_back` (9 header cases), `test_a_304_on_the_very_first_fetch_is_a_fetch_error`, `test_a_304_for_a_feed_nothing_is_held_for_is_a_fetch_error`, `test_any_status_but_200_and_304_is_a_fetch_error_naming_url_and_status` (16), `test_an_empty_200_overview_after_a_good_fetch_is_not_taken_as_unchanged` | pass |
| T3 only newer feeds requested; changed list exact; never to reported | `test_only_the_feeds_with_a_newer_timestamp_are_requested_conditionally`, `test_a_feed_request_uses_the_feeds_own_validators_not_the_overviews`, `test_the_changed_list_names_exactly_the_touched_places`, `test_the_changed_list_follows_the_election_order`, `test_a_third_fetch_after_a_change_requests_only_the_overview`, `test_a_feed_going_from_never_reported_to_reported_is_fetched_unconditionally`, `test_a_feed_going_back_to_never_reported_is_dropped_and_not_listed_as_changed`, `test_a_feed_removed_from_the_overview_leaves_the_election_and_is_not_requested`, `test_a_moved_timestamp_with_an_identical_feed_body_is_no_change[feed-304/feed-200-same-body]`, `test_an_overview_that_changed_without_newer_timestamps_requests_no_feed`, `test_a_shared_file_name_is_requested_per_listing_and_both_places_are_built` | pass |
| T4 interval and timeout validation; failures leave state; backoff 120/240/300/300/60; recorder failure; unsafe names; UA `unknown` | `test_poll_waits_120_240_300_300_then_60_after_a_success_then_120_again`, `test_poll_backoff_doubles_to_the_cap_or_the_interval_if_that_is_larger` (5 intervals), `test_poll_rejects_a_bad_interval_at_call_time_before_any_request` (9), `test_a_failure_on_the_second_of_three_feeds_changes_nothing_and_records_nothing` (6 failure kinds), `test_a_failing_overview_keeps_the_last_good_election_and_the_next_fetch_recovers` (6), `test_a_failing_feed_on_the_first_fetch_leaves_the_source_empty` (6), `test_a_doctype_feed_error_names_the_feed`, `test_a_recorder_that_fails_on_fetch_two_changes_nothing_and_fetch_three_records_the_full_set`, `test_a_disk_error_from_the_recorder_is_a_feed_error_and_state_is_kept`, `test_a_fetch_that_fails_midway_records_nothing_even_though_it_received_bodies`, `test_an_overview_listing_an_unsafe_name_is_refused_before_any_feed_request` (13), `test_an_unsafe_name_on_the_first_fetch_requests_only_the_overview`, `test_http_source_rejects_a_timeout_that_is_not_finite_and_positive` (8), `test_http_source_accepts_a_positive_finite_timeout`, `test_http_source_rejects_a_bad_location_naming_it`, `test_user_agent_reads_unknown_when_the_package_metadata_is_missing`, `test_user_agent_names_the_installed_version_and_the_repository`, `test_interval_constants_are_the_documented_seconds` | pass |
| T5 poll cycles, stop, max_cycles, no sleep after the last, call-time errors, `at` from `source.clock()` | `test_poll_stops_after_max_cycles_and_never_sleeps_after_the_last`, `test_poll_with_one_cycle_does_not_sleep_at_all`, `test_poll_stop_is_checked_after_each_cycle`, `test_poll_without_a_limit_runs_until_stop_says_so`, `test_poll_does_not_sleep_when_stop_and_max_cycles_hit_together`, `test_poll_rejects_a_max_cycles_that_is_not_an_integer_of_at_least_one` (7), `test_poll_accepts_the_floor_and_anything_above`, `test_poll_does_nothing_until_it_is_iterated`, `test_poll_cycle_numbers_start_at_one_and_count_up`, `test_a_successful_cycle_carries_the_election_changes_and_the_interval`, `test_a_failed_first_cycle_has_no_election_and_no_changes`, `test_a_later_failed_cycle_keeps_the_last_good_election`, `test_poll_reads_the_clock_once_per_cycle_and_stamps_the_cycle_with_it`, `test_each_recorded_cycles_at_is_the_name_of_its_capture_folder`, `test_a_cycles_at_is_the_fetch_time_the_recorder_received`, `test_poll_never_touches_the_network_or_the_real_sleep` | pass |
| T6 `urllib_transport` on loopback; `overview_url` | `test_urllib_transport_returns_200_with_lower_cased_header_names`, `..._sends_the_given_headers`, `..._returns_other_statuses_as_responses` (4), `..._does_not_flag_a_304_that_declares_a_content_length`, `..._rejects_a_body_shorter_than_its_content_length`, `..._rejects_a_short_error_body_too`, `..._accepts_a_body_of_exactly_the_cap`, `..._rejects_a_body_one_byte_over_the_cap` (200 and 500), `..._turns_a_refused_connection_into_a_fetch_error`, `..._turns_a_read_timeout_into_a_fetch_error`, `..._turns_a_dropped_connection_into_a_fetch_error`, `..._follows_a_redirect_to_the_same_server`, `..._does_not_follow_a_redirect_to_a_file_url`, `..._keeps_the_last_of_two_headers_with_the_same_name`, `..._rejects_a_url_http_client_refuses`; `test_overview_url_accepts_an_id_a_folder_or_the_file` (19), `test_overview_url_is_idempotent_on_its_own_output`, `test_overview_url_rejects_junk_credentials_and_control_characters` (27) | pass |
| T7 `Recorder`, `check_feed_name` (`tests/test_capture.py`) | `test_record_writes_a_utc_named_folder_holding_the_given_files`, `..._does_not_create_the_directory_until_the_first_record`, `test_record_names_the_folder_after_the_utc_time` (6), `..._refuses_a_naive_time_and_writes_nothing`, `..._refuses_no_feeds_and_writes_nothing`, `..._with_a_naive_time_and_no_feeds_reports_the_time_first`, `test_record_refuses_an_unsafe_name_and_creates_no_folder` (13), `..._refuses_a_body_that_is_not_bytes_and_leaves_no_temporary_folder` (5), `..._cleans_up_when_a_write_fails_midway_with_an_os_error`, `..._with_something_that_is_not_an_os_error`, `..._refuses_an_existing_folder_and_keeps_its_contents`, `..._replaces_a_leftover_temporary_folder_from_a_crash`, `..._with_a_regular_file_in_the_temporary_place_is_a_feed_error`, `..._into_a_directory_that_is_a_regular_file_is_a_feed_error`, `..._does_not_mutate_the_feeds_it_is_given`, `..._writes_an_empty_body_as_a_zero_byte_file`, `..._accepts_an_overview_only_capture`; `test_check_feed_name_accepts_every_fixture_feed_name_except_the_overview`, `..._returns_a_safe_name_unchanged`, `..._rejects_unsafe_names_and_the_overview_in_any_case` (24), `..._error_names_the_offending_value` | pass |
| T8 record then `CaptureReplay` (`tests/test_capture.py`) | `test_record_then_replay_gives_one_step_per_recorded_fetch`, `..._changed_lists_equal_the_live_changed_lists`, `..._an_earlier_step_shows_the_earlier_national_figures`, `..._the_last_step_equals_the_election_as_last_fetched`, `..._the_identical_body_capture_holds_only_the_overview`, `..._sleeps_are_the_fetch_gaps_divided_by_speed` (3), `..._restarting_gives_equal_steps`, `test_a_clock_with_an_offset_records_a_utc_folder_and_replays_utc`; plus `test_replay_*`: steps in time order, first step all changed, later step only differences, earlier figures, file replacement, overview-only capture, sleeps per speed (4), gaps from names not mtimes, order by name, sub-second gap, single capture, restart and added folder, two iterators, no modification, ignored entries (top level and inside a folder), invalid names (6), matching file, missing/file directory, no captures (2), incomplete first capture (3 + empty folder), error mid-iteration after earlier steps (missing feed, malformed, DOCTYPE), empty overview, bodies read per step, `test_capture_replay_rejects_a_speed_that_is_not_positive` (6), speed accepted (4), `reads_nothing_until_iterated` | pass |
| T9 CLI `poll`, capture `replay`, `is_capture_directory` (`tests/test_cli.py`, `tests/test_capture.py`) | `test_poll_prints_a_line_per_changed_place_for_the_first_cycle_only`, `..._lines_carry_the_fetch_time_progress_type_and_name`, `..._shows_only_the_places_that_changed_in_a_later_cycle`, `..._without_cycles_runs_until_interrupted` (130), `..._interval_is_the_wait_between_cycles` (3), `..._a_bad_interval_exits_2_with_the_reason_on_err` (10), `..._a_bad_cycle_count_exits_2` (5), `..._without_a_location_exits_2`, `..._a_bad_location_exits_2_with_error_on_err_and_touches_nothing` (6), `..._exits_1_when_the_last_cycle_failed_with_error_on_stderr_only`, `..._exits_0_when_an_early_cycle_failed_but_the_last_succeeded`, `..._exits_1_when_a_success_is_followed_by_a_failure`, `..._a_failed_cycle_prints_nothing_on_stdout`, `..._record_writes_one_capture_folder_per_poll_that_received_a_body`, `..._record_to_a_path_that_is_a_file_fails_every_cycle`, `..._what_it_records_replays_to_the_polled_election`, `test_python_dash_m_dkvalg_poll_a_bad_location_exits_2_without_a_network`, `test_replay_of_a_capture_directory_*` (4), `test_replay_of_a_plain_directory_is_unchanged_by_capture_support`, `test_replay_of_a_directory_with_both_an_overview_and_capture_folders_uses_the_plain_path`, broken or incomplete capture folders exit 1, a lone matching file takes the plain path; `test_is_capture_directory_*` (true, plain directory, overview beside captures, 6 false cases, lone file, file and missing path, invalid time still true) | pass |
| T10 DOCTYPE and entity refusal (`tests/test_folketingsvalg.py`) | `test_parse_overview_refuses_a_doctype_or_entity_in_every_encoding` and `test_parse_place_refuses_..._naming_the_feed` (7 shapes x 5 encodings each), `test_a_billion_laughs_payload_is_refused_quickly_in_both_parsers` (5), `test_a_utf_16_doctype_under_a_utf_8_declaration_is_still_a_feed_error`, `test_a_doctype_after_the_root_element_is_refused_either_way`, `test_a_doctype_in_a_valid_overview_is_refused_not_just_in_a_stub`, `..._valid_feed...`, `test_the_word_doctype_in_a_comment_cdata_text_pi_or_attribute_is_not_refused` (5), `test_a_utf_16_document_without_a_doctype_still_parses`, `test_a_utf_8_document_with_a_byte_order_mark_still_parses`, `test_every_fixture_feed_still_parses_after_the_hardening` (107 feeds), `test_malformed_input_is_reported_as_malformed_not_as_a_doctype_or_a_crash` (5), `test_the_refusal_keeps_its_cause_for_debugging`, `test_refusing_a_document_does_not_depend_on_what_the_ref_says`, `test_development_notes_no_longer_list_the_entries_this_round_resolved` (2); `test_build_election_refuses_a_doctype_in_the_overview_before_reading_any_feed` (`tests/test_directory.py`) | pass |
| T11 `changed_since`, `build_election` | `tests/test_model.py`: `test_changed_since_*` (18: None, placeholder excluded, equal, itself, changed figures, moved timestamp, new, never before, removed, back to never, order, same id other type, empty previous, empty election, duplicate in previous, idempotent and pure, tuple); `tests/test_directory.py`: `test_build_election_*` (equals `load_election`, reader asked once per reported feed in order, never-reported not asked, all-unreported reads nothing, reader exceptions propagate unchanged (3), malformed overview and feed named, idempotent, shared file name) | pass |
| T12 round 1 suite unchanged; fetch never concurrent | all 696 round 1 tests pass unchanged; `test_two_threads_calling_fetch_never_run_inside_the_transport_together` | pass |
| `FetchError`, package surface (`tests/test_errors.py`, `tests/test_package.py`) | `test_fetch_error_*` (6 incl. parametrised), `test_a_feed_error_handler_also_catches_a_fetch_error`, `test_a_plain_feed_error_is_not_a_fetch_error`; `test_dkvalg_re_exports_the_live_polling_api_from_its_module` (8, identity), `test_dkvalg_keeps_transport_pieces_and_helpers_out_of_the_top_level` (12), `test_the_helpers_stay_importable_from_their_own_modules` (12) | pass |

Criteria coverage: A1 T1; A2 T2 and the second-fetch tests; A3 T3; A4 T1, T4 and the poll tests; A5 T5; A6 T8 and the end-to-end record-then-replay; A7 T9; A8 T10; A9 the unchanged 696-test suite plus T11.

**Production fixes the tests exposed** (each verified by running code first; against the pre-fix `src/` 43 of the new tests fail, so each fix has a test that catches its reverse):

| # | Defect | Fix | Tests |
|---|---|---|---|
| a | A body shorter than its `Content-Length` was accepted as a 200 (`http.client` `read(amt)` returns short without raising); a truncated feed would have been held as good. | `_read_body` compares the length with `Content-Length` and raises `FetchError` naming the URL; skipped for 204 and 304, whose declared length is not a body. | `test_urllib_transport_rejects_a_body_shorter_than_its_content_length`, `..._a_short_error_body_too`, `..._does_not_flag_a_304_that_declares_a_content_length` |
| b | Two clock reads per cycle: `PollCycle.at`, the capture folder name and `FetchResult.fetched_at` could disagree, a scripted clock was consumed twice, a constant clock made the second record collide. | One read: `poll` reads `source.clock()` and passes it to private `HttpSource._fetch_at`; `fetch()` reads once. Deviation recorded in section 3. | `test_poll_reads_the_clock_once_per_cycle_and_stamps_the_cycle_with_it`, `test_each_recorded_cycles_at_is_the_name_of_its_capture_folder`, `test_a_cycles_at_is_the_fetch_time_the_recorder_received` |
| c | `Recorder.record` left a `.tmp-*` folder behind on a non-`OSError` (a `str` body raised `TypeError`). | Bodies must be `bytes` (`FeedError` naming the file, before anything is created); any other exception also removes the temporary folder and propagates. | `test_record_refuses_a_body_that_is_not_bytes_and_leaves_no_temporary_folder`, `test_record_cleans_up_when_a_write_fails_with_something_that_is_not_an_os_error` |
| d | `overview_url` accepted credentials (which would appear in every `FetchError` message), control characters and whitespace, a trailing `valgdag.xml/` (giving `valgdag.xml/valgdag.xml`) and `VALGDAG.XML`. | Rejects userinfo, non-ASCII, whitespace and non-printable characters, an invalid or zero port and an empty host; normalises a trailing slash and any case of the file name to `valgdag.xml` (normalise, not reject, chosen as the smaller surprise). | `test_overview_url_accepts_an_id_a_folder_or_the_file`, `test_overview_url_rejects_junk_credentials_and_control_characters` |
| e | `check_feed_name` accepted `VALGDAG.xml`, which would overwrite the overview on a case-insensitive disk. | Compares `name.lower()`. | `test_check_feed_name_rejects_unsafe_names_and_the_overview_in_any_case`, `test_record_refuses_an_unsafe_name_and_creates_no_folder`, `test_an_overview_listing_an_unsafe_name_is_refused_before_any_feed_request` |
| f | An empty `ETag` or `Last-Modified` was sent back as an empty validator. | `_validators` turns an empty header into None. | `test_only_the_validators_a_response_carried_are_sent_back` |
| g | `timeout=True`, `interval=True`, `max_cycles=True` and `max_cycles=2.5` were accepted. | Bools refused for all three; `max_cycles` must be an `int` (`ValueError` naming the value). | `test_http_source_rejects_a_timeout_that_is_not_finite_and_positive`, `test_poll_rejects_a_bad_interval_at_call_time_before_any_request`, `test_poll_rejects_a_max_cycles_that_is_not_an_integer_of_at_least_one` |
| h | The capture-folder pattern used `\d`, which matches fullwidth digits, so such an entry counted as a capture. | The pattern is compiled with `re.ASCII`; such entries are ignored. | `test_is_capture_directory_false_without_a_capture_named_folder`, `test_replay_ignores_entries_that_are_not_capture_folders` |

No docstring or STRUCTURE.md row was left stale: both were updated with the fixes. No public signature changed, so section 2's Public API table needs no edit.

**Pinned behaviours** (documented, tested, not changed):

- A naive injected clock with a recorder raises `ValueError` out of `fetch` and out of `poll` (a programming error, loud, state untouched): `test_a_naive_clock_with_a_recorder_is_a_loud_value_error_not_a_feed_error`, `test_poll_lets_a_naive_clock_with_a_recorder_raise_a_value_error`.
- A stuck (constant) clock with a recorder fails the second fetch that receives a body with `FeedError("already exists")` and never overwrites the first capture: `test_a_stuck_clock_with_a_recorder_never_overwrites_an_earlier_capture`.
- `changed_since` never reports a place that goes back to never-reported or disappears (its docstring says so): `test_changed_since_does_not_report_a_place_that_disappeared`, `..._went_back_to_never_reported`; the same through `HttpSource`: `test_a_feed_going_back_to_never_reported_is_dropped_and_not_listed_as_changed`.
- A duplicate file name in one overview is requested once per listing on a first fetch: `test_a_shared_file_name_is_requested_per_listing_and_both_places_are_built`.
- `replay` on a directory whose only capture-like entry is a file takes the plain path and fails with a `valgdag.xml` `FeedError`: `test_replay_of_a_directory_whose_only_capture_like_entry_is_a_file_takes_the_plain_path`.
- `HttpResponse` header names are expected lower-case; a mixed-case `ETag` key from a custom transport is not seen (the `mixed-case-names-ignored` case).
- Any token of letters, digits, `_` and `-` is accepted as an election id (`junk`, `-`, `_`, `1`), `HTTPS://H/x/` keeps its scheme case, and `generel.xml` passes `check_feed_name`.
- A doctype after the root element is refused as "malformed XML" (expat fails before the handler), a truncated DOCTYPE says "DOCTYPE"; both are `FeedError`s.
- Capture steps print timezone-aware UTC times (`+00:00`) while plain-directory `replay` prints naive local time: the two kinds of time the plan's Risks already named.
- A redirect to the same server is followed; a redirect to a `file://` URL is not (the response comes back as a 302 or a `FetchError`, never the file).

Edge cases considered and deliberately skipped, with reasons:

- `chmod`-based read-only directory tests: the sandbox runs as root, so they would prove nothing; a regular file used as a directory and a monkeypatched `Path.write_bytes` cover the same failure branches.
- `CaptureReplay(speed=True)` and a speed so small that `gap / speed` overflows to `inf`: both are the caller's explicit choice (a bool is 1.0; `sleep(inf)` is the injected sleep's problem), nothing in the concept decides otherwise.
- A recorded `fetched_at` of year 1 or past 9999 after UTC conversion: `astimezone` overflows with an `OverflowError`; unreachable with a real clock.
- Asyncio or multi-process use, and concurrent reads of `source.election` while a fetch is committing: out of scope (concept); the lock tests prove fetches do not interleave.
- `urllib_transport` URL-scheme validation: `overview_url` already guards the scheme and a hostile CRLF URL is refused by `http.client` (one test).
- Gzip or chunked-encoding bodies and `Content-Length` disagreeing for HEAD: DST is read with plain GET and no `Accept-Encoding`; chunked bodies are length-checked by `http.client` itself.
- Contradicting `Content-Length` headers (two values, or a negative one): `http.client` and the plain-digit check ignore anything that is not a single non-negative integer; no real server sends them.
- Real DST network behaviour: verified once manually in step 3 (section 3), never in tests.

---

## 6. Concept check

> Written in step 6, against section 1 — not against section 2. The question is whether
> the thing built is the thing agreed, not whether it matches the plan.

| # | Criterion | Met | Evidence |
|---|---|---|---|
| A1 | First fetch equals `load_election` | yes | `test_first_fetch_equals_load_election_of_the_same_files` (1 passed), plus `..._reports_every_reported_place_as_changed`; live: first cycle of `python -m dkvalg poll Valg2546527 --cycles 2 --interval 15` printed 107 lines at 92/92. |
| A2 | Both validators; 304 or identical 200 means no feed requested, same election, no changes | yes | `test_second_fetch_sends_only_the_overview_with_both_previous_validators`, `test_an_unchanged_overview_returns_the_same_election_and_no_changes[304, 200-same-body-new-etag]`, `test_a_304_records_nothing_and_an_identical_200_records_only_the_overview` (all pass). Live: probe of 8 fetches sent `If-None-Match` and `If-Modified-Since` on every later request, got 3 x 304 and 4 x 200 (identical body, `changed` 0 each) for 7 conditional overview requests; the CLI run's cycle 2 was a 200 with an identical body and recorded a folder holding only `valgdag.xml`. No feed was requested after the first fetch (feed-200 count stayed 107). |
| A3 | Only newer feeds requested; changed list exact | yes | `test_only_the_feeds_with_a_newer_timestamp_are_requested_conditionally`, `test_the_changed_list_names_exactly_the_touched_places`, `..._follows_the_election_order`, `..._never_reported_to_reported_is_fetched_unconditionally` (pass). Fake-transport recording: after touching the national feed and two others, the second fetch recorded a folder of 4 files (overview plus 3 feeds) and replay printed exactly 3 changed places for it. |
| A4 | User-Agent, timeout, floor 15, back-off, atomic failure | yes | Live probe showed `User-Agent: dkvalg/1.0.0 (+https://github.com/petermads123/valg_data)` on the overview request. Tests: `test_every_request_carries_the_user_agent_accept_and_the_timeout` and `user_agent` (12 passed with the interval cases); `test_poll_waits_120_240_300_300_then_60_after_a_success_then_120_again` and the back-off cases (8 passed); the failure and recorder-failure cases (13 passed) leave election and held bodies unchanged. CLI `--interval 5` exits 2 naming the value. |
| A5 | Poll loop | yes | `test_poll_stops_after_max_cycles_and_never_sleeps_after_the_last`, `test_poll_never_touches_the_network_or_the_real_sleep`, `test_poll_reads_the_clock_once_per_cycle_and_stamps_the_cycle_with_it`, stop and cycle-field tests (pass). Live: 2 cycles under `--cycles 2` with a real 15 s sleep between them. |
| A6 | Recorder layout, capture replay, timing, last snapshot, earlier national figures | yes | Live: `--record` gave `20261104T070753.162603Z` (108 files: overview plus 107 feeds) and `20261104T070906.861541Z` (only `valgdag.xml`, the identical 200); `python -m dkvalg replay <dir> --speed inf` exit 0 printed the national table. Fake-transport run (scratchpad `fake_record.py`): 3 folders of 108, 4 and 1 files (the 304 recorded nothing), replay exit 0. Tests: `..._an_earlier_step_shows_the_earlier_national_figures`, `..._the_last_step_equals_the_election_as_last_fetched`, `..._the_identical_body_capture_holds_only_the_overview`, `..._sleeps_are_the_fetch_gaps_divided_by_speed`, restart (8 passed). |
| A7 | CLI `poll` and `replay`, exit codes | yes | `python -m dkvalg poll foo/bar` gives `error:` and exit 2; `--interval 5` exits 2; `replay /nonexistent` prints `error: feed file not found: .../valgdag.xml` and exits 1; `replay tests/fixtures/folketingsvalg_2026 --speed inf` unchanged from round 1; capture-directory replay exit 0 (above). 98 CLI tests passed (`poll`, `replay`, exit codes). |
| A8 | DOCTYPE and entity refusal; note deleted | yes | `-k doctype`: 93 passed (both parsers, five encodings, billion laughs, UTF-16, fixtures still parse via `test_every_fixture_feed_still_parses_after_the_hardening`); `grep 'Harden XML' DEVELOPMENT.md` finds nothing; `test_development_notes_no_longer_list_the_entries_this_round_resolved` passes. |
| A9 | Round 1 untouched | yes | Full suite 1301 passed. `git diff main -U0 -- tests` removes only four import lines (names added to existing `from` imports in `conftest.py`, `test_cli.py`, `test_errors.py`) and no `def test_` or decorator; round 1's 696 tests taken from `main` and run against the current `src/`: 693 passed, the other 3 (`test_fixtures` PDF and `.gitattributes`, `test_guard_git` settings) failed only because the copy sits outside the repo, and they pass in the repo. `src/dkvalg/sources/replay.py` has no diff against `main`. |

Out of scope holds: grep for AppDaemon or Home Assistant finds only the plan files under `development/` (prose saying it is excluded), nothing in `src/`, `tests/`, `README.md`; no `diff.py`; the only adapter is `folketingsvalg.py`; no kommunal or fintal in `src/`; the only concurrency import is `threading.Lock` in `http_source.py:271` (no `Thread`, no asyncio); `pyproject.toml` has `dependencies = []`; no test reaches the external network (`urlopen` is monkeypatched in `test_http_source.py:1619`; the transport tests use a `127.0.0.1` server). Surface: the public names are the ones the concept asked for. Showcases for `http_source` and `capture` run without network. Gates: `ruff check`, `ruff format --check` (61 files), `mypy` (31 files) clean. Structure: auditor reported in sync; spot-checked the module list, all of which exist on disk.

Live measurement for the DEVELOPMENT.md note (2026-11-04, one run, 107 + 8 + 1 requests, 1 s apart in the probe): of 7 conditional overview requests carrying both validators, 3 were answered 304 and 4 a 200 with an identical body; the unconditional first request was 200. The CLI run's second cycle was also a 200. The byte comparison absorbed every one of them (no false change). This matches the plan's Risk, and the DEVELOPMENT.md entry already says so.

Drift found, and what was done about it: none against section 1. Observations that are not drift: (1) `replay <dir> | head` raises `BrokenPipeError` with a traceback, the same as round 1's code path; not a criterion and not changed. (2) Capture steps print timezone-aware UTC times while plain replay prints naive local time, already recorded in section 5 and in the plan's Risks. (3) Section 3's one-clock-read refinement of `poll` changes no criterion. No code was edited in this step.

### Earlier rounds still hold

First round on this branch; round 1 of the previous branch is merged and covered by A9.

| Round | # | Criterion | Still met | Evidence |
|---|---|---|---|---|
| 1 | A9 | Round 1 of the previous branch is untouched | yes | See the A9 row above. |

---

## 7. Ship log

| Field | Value |
|---|---|
| Commits | `0b65290` Concept; `cde1755` Plan (draft); `13f68b2` Plan (critic findings applied); `300fcbe` Implement; `92ebb83` Verify; `76be69c`, `cb3af6d`, `d646cdd` WIP step 5; `3d612f9` Test; `20f62b3` Concept check; then the final `Ship: dkvalg live polling, recording and capture replay` (this file's marker commit). Every step 1 to 6 left a commit. |
| Pushed to | `origin/feat/dkvalg-live-polling` |

Whole-tree gates at ship: `ruff check .` clean; `ruff format --check .` 61 files formatted; `mypy` 31 source files clean; `pytest` 1301 passed; showcases for `errors`, `model`, `adapters.folketingsvalg`, `sources.directory`, `sources.http_source`, `sources.capture`, `sources.replay`, `python -m dkvalg` and `python -m dkvalg replay tests/fixtures/folketingsvalg_2026 --speed inf` all exit 0. Diff review against `origin/main`: 21 files, all in `src/`, `tests/`, the plan file, `README.md`, `STRUCTURE.md`, `DEVELOPMENT.md`; no scratch files, secrets, committed capture or `.tmp-*` directories, AppDaemon or Home Assistant code; prints only in showcases and the CLI; `pyproject.toml` untouched (1.0.0); `STRUCTURE.md` lists both new modules and test files.

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
