# dkvalg: Folketingsvalg model, adapter and replay

<!-- claude-plan step=7 status=active -->

| Field | Value |
|---|---|
| Feature | `feat/dkvalg-folketingsvalg-replay` (the folder) |
| Round | 1 |
| Branch | `feat/dkvalg-folketingsvalg-replay` |
| Version | `major` — first real capability, new subpackage; step 9 adds `0.1.0 → 1.0.0` (minor, 0.2.0, was the alternative) |
| Started | 2026-11-03 |

## Progress

| # | Step | Skill | Runs | Status |
|---|---|---|---|---|
| 1 | Conceptualize | `/conceptualize` | with the user | done |
| 2 | Plan | `/plan` | with the user, unless the critique is clean | done |
| 3 | Implement | `/implement` | in `/build` | done |
| 4 | Verify | `/verify` | in `/build` | done |
| 5 | Test | `/test` | in `/build` | done |
| 6 | Concept check | `/concept-check` | in `/build` | done |
| 7 | Ship | `/ship` | in `/build` | in progress |
| 8 | Recommend | `/recommend` | with the user | pending |
| 9 | Pull request | `/create-pr` | with the user | pending |
| 10 | Review | `/watch-pr` | on the pull request | pending |

Statuses: `pending`, `in progress`, `done`.

## Builds on

Nothing — this is the first round.

---

## 1. Concept

### What this is

`dkvalg` is a dependency-free Python library that reads DST's Folketingsvalg XML feeds into one normalised model: an election made of places (land, landsdel, storkreds, opstillingskreds), each with party votes, percentages, seats, turnout and a counting status. It can replay a saved feed set through time at accelerated speed, through a library API and `python -m dkvalg replay <dir>`. Round 1 builds this on the real Folketingsvalg 24 March 2026 data. The library is meant for live elections (used from Home Assistant via a separate AppDaemon project); replay is the way to build and test it without one.

### Why it is worth building

The next election may be years away, so the pipeline has to be developed and tested against a real past one. A source that replays saved files is indistinguishable downstream from a live one, so the parser, model and later live polling, diff and HA mapping are all proven against the same real data.

### Inputs and outputs

In: a directory laid out as DST serves it (overview feeds `generel.xml` and `valgdag.xml`, and the result feeds they link to). Out: a normalised election snapshot, and from a replay a time-ordered sequence of snapshots. The CLI prints progress to stdout and errors to stderr.

### How it connects to the rest of the repo

Everything is new under `src/dkvalg/`, replacing the `valg_data` package and the hello-world placeholder. No existing module is reused. Nothing in the repo relates to AppDaemon or Home Assistant.

### Explicitly out of scope

- AppDaemon / Home Assistant: no wrapper, entities, `apps.yaml.example` or `valg_opdateret` event, now or in this repo. The library only provides a model and diff that a separate HA project can map.
- HttpSource (live polling), a live-capture recorder, `diff.py`: later rounds (live polling is planned as round 2).
- EP-valg and folkeafstemning (a yes/no shape): later rounds.
- Kommunal- and regionsvalg: DST publishes no feed for them.
- Fintaelling (`fintal.xml`, personal votes), afstemningsomraader, and national totals derived by summing lower levels.
- Network access in tests.

Assumptions: English identifiers and docstrings with Danish values kept as served; standard library only. Replay from saved files reveals each result feed at its `SenestRettet` (its last change), so landsdel, storkreds and national aggregates, last changed at the end, appear late: faithful intermediate aggregates need captures recorded while an election is live.

### Acceptance criteria

| # | The finished feature... |
|---|---|
| A1 | is the package `dkvalg`: `valg_data` and the hello-world placeholder with its test are gone, and `python -m dkvalg` runs. |
| A2 | ships real fixtures: `docs/` holds DST's XML-feeds PDF; `tests/fixtures/` holds the unmodified Folketingsvalg 24 March 2026 set (`generel.xml`, `valgdag.xml` and all 107 result feeds), with a README naming the source URLs and retrieval date. |
| A3 | parses the fixture set into a normalised election: name, date, type, and 107 places (hele landet, the preliminary "optalling" tally, 3 landsdele, 10 storkredse, 92 opstillingskredse), each with type, id, name, status, eligible voters, turnout %, valid, blank and invalid votes, and per-party votes, %, constituency seats and supplementary seats. Tested on values from the files, e.g. Hovedstaden: 1,309,177 eligible voters, Socialdemokratiet 201,493 votes and 10 seats. |
| A4 | reports counting progress from a snapshot: how many of the 92 opstillingskredse have a result, distinguishing "no result yet" (status 0 or timestamp `0001-01-01`) from a reported result. |
| A5 | provides a ReplaySource that reveals each result feed at its `SenestRettet` time, in order: nothing counted at the start, equal to the static parse at the end, only already-reported places mid-sequence; at speed N gaps shrink by N, tested with an injected clock and no real waiting. |
| A6 | provides `python -m dkvalg replay <dir> [--speed N]` that prints each place as it is revealed with running counted-of-92 progress, ends with the national result table and exits 0; an empty or non-election directory prints a readable error to stderr and exits non-zero. |
| A7 | handles real-feed quirks: a UTF-8 BOM parses; "Uden for partier" (empty `Id`) is kept as a distinct non-party entry; a status 9 feed becomes an explicit error state rather than a crash; a missing feed file raises an error naming it. |

### Open questions

None.

Correction made in step 2 (2026-11-03): the concept said 106 result feeds and places; the overview lists 107 (the two national feeds are "Hele landet" and the seatless "Optalling" tally). A2 and A3 now say 107; nothing else in the concept changed.

---

## 2. Plan

> Written in step 2, accepted before step 3 starts — by the user, or by a clean critique
> (see `/plan`). Concrete enough that step 3 is transcription, not invention.

### Approach

Follow the layout the spec already chose, trimmed to what round 1 needs: a `dkvalg` package with a small immutable **model**, a Folketingsvalg **adapter** (bytes in, model out, no I/O), a **directory loader** that reads a DST-layout folder into an `Election`, a **ReplaySource** that turns an `Election` into a time-ordered series of snapshots, and a **CLI**. The replay takes an already-loaded `Election` rather than a path, so it is testable without files, and the loader is the only code that touches the disk. Immutable dataclasses with `tuple` fields make "final replay snapshot equals the static parse" a plain `==`. Datetimes are naive Danish local time exactly as DST publishes them (no `zoneinfo`, which would need a `tzdata` dependency on Windows); only differences between them are used.

Every place is always present in an `Election`: places with no result yet are placeholders (`Status.NOT_AVAILABLE`, no figures), which is how DST itself represents them and what makes "N of 92 counted" computable at every moment of a replay.

Rejected: (a) one flat `dkvalg.py` with functions and dicts, the smallest, but the spec's adapter-per-type and source-per-origin split would then be a refactor in round 2 and 3; (b) defining a `Source` protocol now, speculative until HttpSource exists in round 2 and its polling shape is known, so it is left out and noted under Risks.

Survey: the repo holds only the `valg_data` placeholder and its test, both deleted; nothing is reused. Findings from the real 2026 feeds that shaped this plan: the overview `valgdag.xml` lists 107 feeds (`Land` x2, `Landsdel` x3, `Storkreds` x10, `Opstillingskreds` x92) with `SenestRettetIso`; the two national feeds are `HeleLandet` (with seats) and `Optalling` (no seats, status text "92 af 92 opstillingskredse optalt"); opstillingskreds feeds carry no `Mandater` attributes; `Afstemningsomraader` is empty; opstillingskreds timestamps run 21:21:09 to 00:12:26 with ties (53 distinct for 92); a status 0 feed has no `Stemmer` and an `SenestRettet` of `01-01-0001 00:00:00`; older feeds have no `SenestRettetIso`.

### Modules

| Path | New or changed | Purpose |
|---|---|---|
| `src/valg_data/` (`__init__.py`, `hello_world.py`), `tests/test_hello_world.py` | deleted | Placeholder, replaced by `dkvalg` (A1) |
| `src/dkvalg/__init__.py` | new | Re-exports the public API |
| `src/dkvalg/errors.py` | new | `FeedError`, the one exception for bad input |
| `src/dkvalg/model.py` | new | Normalised, immutable election model (A3, A4) |
| `src/dkvalg/adapters/__init__.py` | new | Package marker for per-election-type adapters |
| `src/dkvalg/adapters/folketingsvalg.py` | new | Parses DST's Folketingsvalg overview and result feeds into the model (A3, A7) |
| `src/dkvalg/sources/__init__.py` | new | Package marker for sources |
| `src/dkvalg/sources/directory.py` | new | Reads a DST-layout directory into an `Election` (A3, A7) |
| `src/dkvalg/sources/replay.py` | new | `ReplaySource`: time-ordered, speed-scaled snapshots (A5) |
| `src/dkvalg/cli.py` | new | `replay` command, argument parsing, output (A6) |
| `src/dkvalg/__main__.py` | new | `python -m dkvalg` entry point (A1, A6) |
| `docs/XmlFeeds20260305.pdf` | new | DST's feed documentation (A2) |
| `tests/fixtures/folketingsvalg_2026/` | new | The 109 unmodified feed files and a README (A2) |
| `.gitattributes` | new or changed | `tests/fixtures/** -text` so no line-ending rewrite alters the unmodified fixtures (A2) |
| `tests/test_<module>.py` | new (step 5) | One per module, plus a shared fixture-directory helper in `tests/conftest.py` |
| `pyproject.toml`, `README.md`, `STRUCTURE.md` | changed | Package name `dkvalg`, usage section, structure map |

### Public API

All fields are keyword-or-positional in the order shown. Seat fields are `None` where DST gives none (opstillingskreds, tally).

| Signature | Module | Purpose | Covers |
|---|---|---|---|
| `class FeedError(Exception)` | `errors` | A feed is missing, unreadable, malformed, or of an unsupported election type; the message names the file or value | A6, A7 |
| `class ElectionType(StrEnum)`: `FOLKETINGSVALG = "folketingsvalg"` | `model` | Which kind of election | A3 |
| `class PlaceType(StrEnum)`: `COUNTRY = "country"`, `TALLY = "tally"`, `LANDSDEL = "landsdel"`, `STORKREDS = "storkreds"`, `OPSTILLINGSKREDS = "opstillingskreds"` | `model` | Level of a result place; `TALLY` is DST's seatless preliminary "optalling" total | A3 |
| `class Status(IntEnum)`: `NOT_AVAILABLE = 0`, `PRELIMINARY = 1`, `ERROR = 9`, `RECOUNT_PENDING = 10`, `RECOUNT_PRELIMINARY = 11`, `RECOUNT_FINAL = 12`; property `has_result(self) -> bool` | `model` | DST status code; `has_result` is true for 1, 11, 12 | A4, A7 |
| `@dataclass(frozen=True, slots=True) class PartyResult`: `party_id: str`, `letter: str`, `name: str`, `votes: int`, `percent: float`, `seats: int \| None = None`, `constituency_seats: int \| None = None`, `supplementary_seats: int \| None = None`; property `is_party(self) -> bool` | `model` | One party's result in one place; `party_id == ""` is DST's "Uden for partier", `is_party` false for it | A3, A7 |
| `@dataclass(frozen=True, slots=True) class Place`: `place_type: PlaceType`, `place_id: str`, `name: str`, `parent_id: str \| None`, `status: Status`, `status_text: str`, `last_changed: datetime \| None`, `eligible_voters: int \| None = None`, `turnout_percent: float \| None = None`, `valid_votes: int \| None = None`, `blank_votes: int \| None = None`, `other_invalid_votes: int \| None = None`, `total_invalid_votes: int \| None = None`, `total_votes: int \| None = None`, `parties: tuple[PartyResult, ...] = ()`; property `has_result(self) -> bool`; method `unreported(self) -> Place` | `model` | One result place; `unreported()` returns the placeholder form (status 0, `status_text=""`, `last_changed=None`, no figures) keeping type, id, name and parent | A3, A4, A5, A7 |
| `@dataclass(frozen=True, slots=True) class CountingProgress`: `counted: int`, `total: int`; `__str__(self) -> str` | `model` | "counted of total" opstillingskredse; `str` gives `"{counted}/{total}"` | A4 |
| `@dataclass(frozen=True, slots=True) class Election`: `name: str`, `election_type: ElectionType`, `election_date: date`, `places: tuple[Place, ...]`; methods `get(self, place_type: PlaceType, place_id: str) -> Place` (raises `KeyError` naming both), `of_type(self, place_type: PlaceType) -> tuple[Place, ...]`, `counting_progress(self) -> CountingProgress` | `model` | A snapshot of an election in overview order; progress counts opstillingskredse with `has_result` | A3, A4 |
| `@dataclass(frozen=True, slots=True) class FeedRef`: `place_type: PlaceType`, `place_id: str`, `name: str`, `parent_id: str \| None`, `last_changed: datetime \| None`, `file_name: str` | `adapters.folketingsvalg` | One result feed as listed by the overview (`file_name` is the last path segment of its URL) | A3 |
| `@dataclass(frozen=True, slots=True) class Overview`: `name: str`, `election_type: ElectionType`, `election_date: date`, `feeds: tuple[FeedRef, ...]` | `adapters.folketingsvalg` | The parsed `valgdag.xml` | A3 |
| `parse_overview(xml: bytes) -> Overview` | `adapters.folketingsvalg` | Parse `valgdag.xml`; raises `FeedError` when malformed or not a Folketingsvalg | A3, A7 |
| `parse_place(xml: bytes, ref: FeedRef) -> Place` | `adapters.folketingsvalg` | Parse one result feed; id and parent come from `ref`; status 0 and 9 give a `Place` without figures, never a crash; raises `FeedError` when malformed | A3, A7 |
| `unreported_place(ref: FeedRef) -> Place` | `adapters.folketingsvalg` | Placeholder `Place` for a feed the overview lists as never reported | A4, A5 |
| `load_election(directory: Path) -> Election` | `sources.directory` | Read `valgdag.xml` and every reported feed it lists from a DST-layout directory; raises `FeedError` naming a missing file | A3, A6, A7 |
| `@dataclass(frozen=True, slots=True) class ReplayStep`: `at: datetime`, `place: Place`, `election: Election`; property `progress(self) -> CountingProgress` | `sources.replay` | One reveal: the place that appeared, the feed time, and the snapshot after it | A5, A6 |
| `class ReplaySource`: `__init__(self, election: Election, *, speed: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> None`; `initial(self) -> Election`; `__iter__(self) -> Iterator[ReplayStep]` | `sources.replay` | Replays `election`. `ValueError` naming the value if `speed` is not positive or is NaN (`math.inf` means no waiting) | A5 |
| `run(argv: Sequence[str] \| None = None, *, out: TextIO \| None = None, err: TextIO \| None = None, sleep: Callable[[float], None] = time.sleep) -> int` | `cli` | The CLI; returns the exit code (0 ok, 1 `FeedError`, 2 bad arguments) | A6 |
| `main() -> None` | `cli` | `raise SystemExit(run())` | A1, A6 |

`dkvalg.__main__` defines no API beyond importing `main` and running it under the guard; `dkvalg/__init__.py` re-exports every name above except `run`, `main`, `parse_*`, `unreported_place`, `FeedRef` and `Overview` (adapter internals stay in their module).

**XML to model** (from the 2026 feeds). Result feed `Data/`: `ValgNavn`, `ValgDato` (`dd-mm-yyyy`); `Status/@Kode` to `Status` and its text to `status_text`; `Stemmeberettigede` to `eligible_voters`; `DeltagelsePct` to `turnout_percent`; `Stemmer/IAltGyldigeStemmer` to `valid_votes`, `BlankeStemmer` to `blank_votes`, `AndreUgyldigeStemmer` to `other_invalid_votes`, `IAltUgyldigeStemmer` to `total_invalid_votes`, `IAltAfgivneStemmer` to `total_votes`. Each `Stemmer/Parti`: `Id` to `party_id` (empty for "Uden for partier"), `Bogstav` to `letter` (`""` when absent), `Navn` to `name`, `StemmerAntal` to `votes`, `StemmerPct` to `percent`, and **served, not derived**: `Mandater` to `seats`, `Kredsmandater` to `constituency_seats`, `Tillaegsmandater` to `supplementary_seats`, each `None` when the attribute is absent. Seat attributes are present on `HeleLandet`, `Landsdel` and `StorKreds` feeds and absent on `OpstKreds` and the `Optalling` tally. A status 0 feed has none of the figure elements. In the 2026 data Hovedstaden (landsdel 7) has `Mandater="10"`, `Kredsmandater="10"`, `Tillaegsmandater="0"` for Socialdemokratiet, so T3 asserts `seats == 10` and `constituency_seats == 10`, via `get(PlaceType.LANDSDEL, "7")`.

Behaviour the signatures do not carry:
- **Overview to places.** Place type comes from the overview element: `Land` with a `land_id` is `COUNTRY` (id `"0"`), `Land` without one is `TALLY` (id is the number in its file name, `valgdag_<id>.xml`, so `"999"` in 2026), `Landsdel`/`Storkreds`/`Opstillingskreds` map to their types with ids from `landsdel_id`/`storkreds_id`/`opstillingskreds_id`; parents are `storkreds_id` for an opstillingskreds, `landsdel_id` for a storkreds, `"0"` for a landsdel, `None` otherwise. `Afstemningsomraader` is ignored.
- **Reported or not.** A feed the overview lists with `0001-01-01` (or no timestamp) is not read from disk and becomes `unreported_place(ref)`, which returns exactly the placeholder fields `Place.unreported()` returns. `Place.last_changed` is the feed's own timestamp, falling back to the overview's `ref.last_changed` when the feed has none. All others are read; a missing file raises `FeedError` naming it.
- **Timestamps.** `SenestRettetIso` if present, else `SenestRettet` (`dd-mm-yyyy hh:mm:ss`, rewritten to ISO text for `datetime.fromisoformat`); `0001-01-01` means `None`. `ValgDato` is `dd-mm-yyyy`. **Election type** is read from `ValgNavn`: it must start with `Folketingsvalg`, otherwise `parse_overview` raises `FeedError` naming the value (an EP overview is `valgdag.xml` whose `ValgNavn` starts `Europa-Parlamentsvalg`). **Dates and times** are built only with `date.fromisoformat` / `datetime.fromisoformat` after rewriting the DST text to ISO; never `datetime(...)` or `strptime`, which Ruff's `DTZ` rules reject for naive values, in code, tests or showcases. An unknown `Status/@Kode` raises `FeedError` naming the code and the file.
- **Replay order.** The places with `last_changed` not `None`, stable-sorted by `last_changed` (ties keep overview order), one step each. `initial()` is the election with each place that has a `last_changed` replaced by `place.unreported()`; places without one are carried over unchanged (so a status 0 or 9 feed keeps its status text and the final snapshot equals the static election by construction); step *i* replaces that one place with its real self. `sleep(gap_seconds / speed)` is called before every step after the first, and only when `gap_seconds / speed > 0` (so never at `speed=inf`). Iterating twice restarts from the beginning.
- **CLI.** `run` builds an `argparse` parser whose messages go to the injected `out`/`err` and catches argparse's `SystemExit`, returning its code, so it never raises. No subcommand prints usage to `out` and returns 0 (that is what "`python -m dkvalg` runs" means in A1); a bad subcommand or `--speed` prints the argparse error to `err` and returns 2. `python -m dkvalg replay <dir> [--speed N]`, `--speed` a positive float, default 600, `inf` allowed. One line per step: feed time, `counted/total`, place type and name. Then a table of the `COUNTRY` place: party letter, name, percent, votes, seats, plus "Uden for partier" last. Errors go to stderr as `error: <message>`. A directory without `valgdag.xml`, or with a non-Folketingsvalg overview, is a `FeedError`.

### Implementation guide

1. Delete the whole `src/valg_data/` directory (including any untracked `__pycache__`, which would otherwise leave `import valg_data` working as a namespace package) and `tests/test_hello_world.py`; remove the stale `src/valg_data.egg-info` and re-run `pip install -e ".[dev]"` once the package is renamed; create the `src/dkvalg/` skeleton (`__init__.py` in the package and both subpackages); set `pyproject.toml` `name = "dkvalg"` and a matching description; update `README.md` and `STRUCTURE.md` references to the old name.
2. `errors.py` and `model.py` with showcases.
3. Fixtures: download `generel.xml`, `valgdag.xml` and every `filnavn` the overview lists from `https://www.dst.dk/valg/Valg2546527/xml/` into `tests/fixtures/folketingsvalg_2026/` unmodified, and the PDF into `docs/`; write a `SHA256SUMS` manifest of every downloaded file at download time and the fixtures README (source URLs, retrieval date 2026-11-03); add `.gitattributes`. Verify 109 XML files plus the README and manifest. If the network refuses, halt (see Risks).
4. `adapters/folketingsvalg.py`: `parse_overview`, `parse_place`, `unreported_place`, against the fixtures.
5. `sources/directory.py`: `load_election`.
6. `sources/replay.py`: `ReplayStep`, `ReplaySource`.
7. `cli.py` and `__main__.py`; `__init__.py` re-exports.
8. README usage section (library and `replay` command); `STRUCTURE.md` tree, package and test sections.

### Test intents

| # | Must prove | Covers |
|---|---|---|
| T1 | `import dkvalg` works, `valg_data` is not importable, and `python -m dkvalg` (run through `runpy.run_module("dkvalg", run_name="__main__")` or a subprocess with `PYTHONPATH=src`, so it does not depend on the install) prints usage to stdout and exits 0 | A1 |
| T2 | The fixture directory holds the 109 XML files (plus README and `SHA256SUMS`), every feed the overview lists is present, every file matches its SHA-256 in the manifest (BOM intact), the PDF exists and the fixtures README names URLs and date | A2 |
| T3 | `load_election` on the fixtures gives 107 places with the expected type counts, every A3 field of one place checked against its file (Hovedstaden: turnout, valid, blank, invalid and total votes, Socialdemokratiet votes, percent, seats 10, constituency seats 10, supplementary 0), national seats summing to 175, opstillingskreds seats `None`, tally with no seats, "Uden for partier" present and `is_party` false | A3 |
| T4 | `counting_progress` is 92/92 on the fixtures, 0/92 on an all-placeholder election, counts a status 1 place, ignores status 0, status 9, status 10 and never-reported places | A4 |
| T5 | `ReplaySource` starts at 0/92, yields one step per reported place in `last_changed` order with ties in overview order, mid-sequence snapshots hold exactly the revealed places as results and the rest as placeholders, the last snapshot `==` the static election, sleep durations are the gaps divided by speed (none for zero gaps or the first step), `inf` never sleeps, bad speeds raise `ValueError`, iterating twice gives the same steps, and an election holding a status 0 place with a non-empty status text and no timestamp (plus one with status 9) still replays to a final snapshot `==` the election | A5 |
| T6 | `run(["replay", dir, "--speed", "inf"])` prints one line per step, with the counted/total column rising monotonically to 92/92, then the national table, and returns 0; an empty directory, a directory with an EP overview, and a malformed overview return 1 with `error:` on stderr and nothing on stdout; bad speed returns 2 with the argparse message on `err`; no subcommand prints usage and returns 0 | A6 |
| T7 | BOM and BOM-less input parse; empty `Id` kept as non-party; status 0 feed (no `Stemmer`) gives a figure-free place; status 9 gives `Status.ERROR`, no crash; a feed missing from disk raises `FeedError` naming the file; truncated XML raises `FeedError`; feed without `SenestRettetIso` falls back to `SenestRettet`; an unknown status code raises `FeedError` naming the code and file | A7 |
| T8 | Purity and idempotency: `load_election` twice gives equal elections, no mutation of arguments, model objects are immutable | A3, A5 |

### Risks

- **Fixture download.** If dst.dk cannot be reached or a listed feed returns a non-200 during the build, **halt**: fabricated fixtures would break A2. (It worked on 2026-11-03.)
- **Line endings.** A checkout that rewrites XML line endings would make the fixtures no longer "unmodified"; `.gitattributes` prevents it, and T2 checks every file against `SHA256SUMS` so a violation shows up in tests.
- **Replay is only as late as `SenestRettet`.** National and landsdel aggregates appear at their last change; this is the assumption recorded in section 1, not a defect. Do not try to derive intermediate aggregates; that is out of scope.
- **Timestamp ties.** 92 opstillingskredse share 53 distinct timestamps; the stable overview-order tie-break keeps replay deterministic. If a test finds order matters elsewhere, it still holds because ties have gap 0.
- **Other election types.** An EP or folkeafstemning overview must fail clearly (`FeedError`), not half-parse; anything else about those types is out of scope. If the build finds the Folketingsvalg result format differs from what is described here in a way that changes a criterion, **halt**.
- **Showcases** locate the fixtures by a repo-relative path and say so when run outside a checkout.
- **No `Source` protocol yet.** Round 2 will add HttpSource and can introduce the shared protocol then, when its shape is known.

### Critique

Plan-critic findings (verdict: accept with the changes below), 2026-11-03. The critic had no shell and could not check the DST data itself; the data claims come from the planner's own inspection of the live feeds.

1. **Count correction changes the model (106 to 107 places, tally as a `TALLY` place).** Open, for the user: keep the seatless "Optalling" tally as a place in the model (107 places, as written) or only as a fixture file (107 feeds, 106 places). The planner recommends keeping it as a place: it is DST's own "N of 92 optalt" tally and costs one enum member.
2. **Final replay snapshot not `==` static for places with no timestamp.** Applied: `initial()` replaces only places with a `last_changed`; `last_changed` falls back to the overview's; `unreported_place` returns the same fields as `Place.unreported()`; new T5 case.
3. **No XML-to-field mapping, seat fields unclear.** Applied: mapping paragraph added, seats are served (`Mandater`), tally id rule stated, T3 asserts `seats == 10` and `constituency_seats == 10` for landsdel 7.
4. **No discriminator for non-Folketingsvalg.** Applied: `ValgNavn` must start `Folketingsvalg`; T6's EP overview is that file with `ValgNavn` changed.
5. **argparse exits and streams.** Applied: `run` routes argparse output to `out`/`err`, returns its exit code, no subcommand prints usage and returns 0; T1 and T6 updated.
6. **`has_result` excludes status 10.** Rebutted: DST documents status 10 as "fintaelling result not yet available", which carries no figures (fintaelling feeds are out of scope), so it is not a result; added to T4's "not counted" cases so the choice is tested.
7. **Unknown status code crashes.** Applied: raises `FeedError` naming code and file; T7 case added.
8. **Old package stays importable via `__pycache__` and egg-info.** Applied: step 1 deletes the whole directory and reinstalls; T1 does not depend on the install.
9. **"Byte-for-byte" unprovable offline.** Applied: `SHA256SUMS` manifest written at download time and checked by T2.
10. **Naive datetimes vs Ruff `DTZ`.** Applied: only `fromisoformat` is used, never `datetime(...)` or `strptime`.
11. **Sleep rule vs `inf`.** Applied: sleep only when `gap / speed > 0`.
12. **Missing test detail for A3 and A6.** Applied: T3 checks every A3 field on one place; T6 checks the counted/total column rises monotonically to 92/92.

Finding 1 decided by the user: the tally is a place (107 places). Finding 6 rebuttal accepted: status 10 is not counted.

Accepted: by the user, 2026-11-03

---

## 3. Implementation notes

> Written in step 3. Only deviations from the plan above, each with its reason. "Built as
> planned" is a complete and good entry. On a fix round, also the reproduction test's red
> run, pasted here before the fix was written — step 6 cites it.

Built as planned: every signature in the Public API table is as written. Fixtures verified
on 2026-11-03: all 109 files returned HTTP 200, all begin with the UTF-8 BOM, `SHA256SUMS`
lists them and verifies. Implementation choices the plan left open, none changing a
signature or criterion:

- `model.py` uses `from __future__ import annotations` so `Place.unreported() -> Place`
  needs no quotes on Python 3.13.
- `cli.run` parses with a plain `argparse.ArgumentParser` inside
  `contextlib.redirect_stdout`/`redirect_stderr` onto the injected `out`/`err` and turns
  argparse's `SystemExit` into the return code, instead of subclassing the parser.
- `parse_place` reads figures only when the status `has_result` (1, 11, 12); a status 0, 9
  or 10 feed gives a figure-free place even if it carried a `Stemmer` element.
- A landsdel's `parent_id` is its `land_id` attribute (`"0"` in the 2026 feeds), defaulting
  to `"0"`.
- Places keep overview document order: landsdele, storkredse, opstillingskredse, then the
  country and the tally (which come last in `valgdag.xml`).
- `Place.last_changed` for a feed whose own timestamp is `0001-01-01` falls back to the
  overview's, as for a missing one.

---

## 4. Verification log

> Written in step 4: the static half. Command output, not a summary of it.

| Check | Result |
|---|---|
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `47 files already formatted` |
| `mypy` | `Success: no issues found in 18 source files` |
| `pytest` (existing suite only; dkvalg tests arrive in step 5) | `307 passed in 6.57s` |
| Plan completeness | every signature in the Public API table exists as written; checked by introspection (`dataclasses.fields`, `inspect.signature`, enum members, `has_result` true for 1, 11, 12). No Missing, Deviation or Unplanned entries. `dkvalg.__init__` exports exactly `FeedError`, `ElectionType`, `PlaceType`, `Status`, `PartyResult`, `Place`, `CountingProgress`, `Election`, `load_election`, `ReplaySource`, `ReplayStep`, as planned |
| `STRUCTURE.md` | in sync: every module, signature and fixture/docs path checked by hand against the code and the auditor report; no edit needed |
| `python -m dkvalg.<module>` | `errors`, `model`, `adapters.folketingsvalg`, `sources.directory`, `sources.replay` each exit 0 with readable output (the expected `RuntimeWarning` for re-exported modules aside). `python -m dkvalg` prints usage, exit 0. `python -m dkvalg replay tests/fixtures/folketingsvalg_2026 --speed inf` exit 0: 107 steps ending `92/92 country Hele landet`, `92/92 tally Alle indberettede opstillingskredse`, then the national table (A Socialdemokratiet 21.9% 779524 votes 38 seats ... last row "Uden for partier" 2420 votes) |

Structure-auditor (step 4): its claim of stale `template_repo`/`hello_world` entries was
checked against the tree and is wrong (STRUCTURE.md already describes `dkvalg`); its
"no signature drift" and the step 5 test-entries notes hold. Nothing changed in code.
Housekeeping: removed the stale, git-ignored `src/valg_data.egg-info` the plan's step 1 names.

---

## 5. Test log

> Written in step 5: the dynamic half.

| Intent | Test names | Result |
|---|---|---|
| T1 (A1) | `test_package.py`: `test_import_dkvalg_works`, `test_the_old_packages_are_not_importable[valg_data, valg_data.hello_world, template_repo]`, `test_dkvalg_re_exports_the_public_api[*]`; `test_cli.py`: `test_module_run_as_main_prints_usage_and_exits_0` (runpy), `test_python_dash_m_dkvalg_works_without_the_editable_install` (subprocess, `PYTHONPATH=src`), `test_main_exits_with_the_code_run_returns` | pass |
| T2 (A2) | `test_fixtures.py`: 109 XML files plus README and `SHA256SUMS`, every listed feed present, every SHA-256 matches, BOM on every file, no CRLF drift, PDF present, README names URLs and date, `.gitattributes` | pass |
| T3 (A3) | `test_directory.py`: 107 places and type counts, overview order, Hovedstaden every field, national seats 175 (135 + 40), landsdele seats 175, opstillingskreds and tally seats `None`, "Uden for partier" non-party, tally text; `test_folketingsvalg.py`: `parse_place_hovedstaden_matches_its_file_field_by_field`, `parse_overview_*` | pass |
| T4 (A4) | `test_model.py`: `test_counting_progress_counts_only_kredse_with_a_result[6 cases incl. 9, 10, 0]`, `..._ignores_results_at_other_levels`, `..._zero_of_zero`, `..._str_is_counted_slash_total`; `test_directory.py`: `test_load_election_counts_92_of_92_on_the_fixtures`, all-never-reported 0/3, status 0 kept but not counted | pass |
| T5 (A5) | `test_replay.py`: 0/92 start, one step per place in time order, ties in overview order (fixtures and synthetic), mid-sequence snapshots, final `==` static (also with untimed status 0 and status 9 places), sleeps = gap / speed, no sleep for first step or zero gaps, `inf` never sleeps, bad speeds `ValueError`, twice and interleaved iteration | pass |
| T6 (A6) | `test_cli.py`: one line per step, counted/total monotonic to 92/92, national table with "Uden for partier" last, exit 0; empty, nonexistent, file, EP, malformed, missing-feed and no-feeds directories exit 1 with `error:` on stderr and empty stdout; bad speeds and argument shapes exit 2; no subcommand and help exit 0 | pass |
| T7 (A7) | `test_folketingsvalg.py`: BOM and BOM-less equal, empty `Id` kept as non-party, status 0 / 9 / 10 figure-free, missing file and truncated XML name the file (`test_directory.py`), `SenestRettetIso` fallback, unknown status code names code and file | pass |
| T8 | `test_directory.py`: `test_load_election_twice_gives_equal_elections_and_leaves_files_alone`, `..._does_not_mutate_the_directory_it_reads`; `test_replay.py`: `..._does_not_mutate_the_election`, immutability; `test_model.py`/`test_folketingsvalg.py`: frozen, idempotent, pure | pass |

Result: `ruff check .` clean, `ruff format --check .` clean, `mypy` no issues in 27 files,
`pytest` 696 passed (the 307 earlier tests plus 389 for dkvalg). The new tests were also run
against the pre-fix adapter: 26 of them fail there, so they pin the fixes below.

Bugs found by the two test-designers and verified by running code, then fixed in
`src/dkvalg/adapters/folketingsvalg.py` (no signature or acceptance criterion changed):

1. **DST's "never" timestamp `01-01-0001 00:00:00` was not recognised** (the `0001-01-01`
   check ran before the `dd-mm-yyyy` rewrite): a status 0 feed got `last_changed = year 1` and
   skipped the `ref.last_changed` fallback, and an overview entry carrying only that spelling
   made `load_election` read a file that does not exist. `_timestamp` now rewrites first, then
   checks, so every spelling is `None`.
2. **An empty `SenestRettetIso` blocked the `SenestRettet` fallback** (both in feeds and in the
   overview): an empty value is now treated as absent.
3. **A status 1/11/12 feed with no `<Stemmer>`** returned a place with `has_result` true and no
   figures, counted as reported: now `FeedError` ("status N but no Stemmer element").
4. **A `Parti` with no `Id` attribute silently became "Uden for partier"**: now `FeedError`
   naming the party and file; only an explicit empty `Id` is the non-party entry.
5. **`nan`, `inf`, `1_000`, `1e3`, non-ASCII digits passed `_int`/`_float`**: figures must now
   be plain ASCII integers or decimals, else `FeedError` naming the value and file (negative
   numbers remain accepted, the adapter does not validate ranges).
6. **An overview listing zero result feeds** gave an empty election and CLI exit 0: now
   `FeedError` ("lists no result feeds"), so such a directory exits 1 (A6/A7 spirit).
7. **A timestamp with a UTC offset** produced an aware datetime that would break sorting in the
   replay: now `FeedError`, keeping the model's naive-time invariant.
8. **`str` XML with an encoding declaration** raised `ValueError` on older parsers: `_parse_xml`
   now also maps `ValueError` to `FeedError` (Python 3.13 accepts such `str` input, so no test).

Docstrings of `parse_overview` and `parse_place` updated for 3, 4, 5, 6; `STRUCTURE.md`
descriptions updated to match.

Pinned as documented behaviour (tests assert it, nothing fixed):

- A non-bytes `xml` (`None`) raises `TypeError`, a non-numeric `speed` raises `TypeError`, and
  an ASCII-only `out` stream raises `UnicodeEncodeError` on Danish names: caller errors outside
  the typed contract; `run` does not catch encoding failures.
- `ReplaySource(speed=5e-324)` hands `inf` to the injected sleep (a real `time.sleep(inf)`
  would raise `OverflowError`).
- An untimed place that has a result is present from the start (`initial()` progress above
  0 for a hand-built election); a timed status 9 place loses its status text until revealed;
  `Election.get` returns the first of two places with the same key; negative counts are
  accepted as served; duplicate overview entries are kept in order; a feed `filnavn` keeps a
  query string in `file_name`; a landsdel without `land_id` gets parent `"0"`.

Edge cases considered and deliberately skipped, with reasons:

- `chmod 000` unreadable files: root bypasses permissions in this environment, and the
  `IsADirectoryError`/`NotADirectoryError` cases already cover the `OSError` branch.
- `load_election` given a `str` instead of a `Path`: type-contract violation, `TypeError`
  from `str / str`, low value.
- Mixed naive and aware datetimes in a hand-built `Election`: the adapter can no longer
  produce them (fix 7); the replay does not promise anything for hand-built ones.
- Entity-expansion attacks on `ElementTree`: relevant for live polling in round 2, not for
  local files here.
- `ValgNavn` such as `Folketingsvalgs-X` passing the `startswith` check: the discriminator is
  the plan's rule; tightening it would be a concept change.
- Very long strings and extreme integers: no limits in the code, Python ints are unbounded.
- Real `time.sleep` pacing: needs real waiting; the injected clock covers the contract.

---

## 6. Concept check

> Written in step 6, against section 1 — not against section 2. The question is whether
> the thing built is the thing agreed, not whether it matches the plan.

| # | Criterion | Met | Evidence |
|---|---|---|---|
| A1 | Package is `dkvalg`; `valg_data` and hello-world gone; `python -m dkvalg` runs | Met | `git ls-files` has no `valg_data`/`hello_world` path; `src/` holds only `dkvalg`; `python -m dkvalg` prints usage, exit 0; `test_package.py` (`test_the_old_packages_are_not_importable[*]`) and `test_cli.py::test_python_dash_m_dkvalg_works_without_the_editable_install` pass; `dependencies = []` in `pyproject.toml` |
| A2 | Real fixtures and DST PDF, unmodified, README with URLs and date | Met | `docs/XmlFeeds20260305.pdf` exists; `tests/fixtures/folketingsvalg_2026/` has 109 `*.xml` plus `README.md` and `SHA256SUMS`; `sha256sum -c SHA256SUMS` reports 0 non-OK lines; README names `https://www.dst.dk/valg/Valg2546527/xml/` and retrieval date 2026-11-03; `test_fixtures.py` passes |
| A3 | Parses to a normalised election with 107 places and all fields | Met | Probe on the fixtures: name `Folketingsvalg tirsdag 24. marts 2026`, date 2026-03-24, type `folketingsvalg`, 107 places = 1 country, 1 tally, 3 landsdel, 10 storkreds, 92 opstillingskreds (Counter output). Hovedstaden (landsdel 7): eligible 1309177, turnout 84.31, valid 1091388, blank 9870, invalid 12348; Socialdemokratiet 201493 votes, 18.5 %, seats 10, constituency 10, supplementary 0; national seats sum 175; "Uden for partier" present with `is_party` false. `test_directory.py` and `test_folketingsvalg.py` (Hovedstaden field by field) pass |
| A4 | Counting progress, no result vs reported | Met | `counting_progress()` is `92/92` on the fixtures; `test_model.py::test_counting_progress_counts_only_kredse_with_a_result` (statuses 0, 1, 9, 10, 11, 12, never reported) and `test_directory.py` all-never-reported 0/3 pass. Note: status 10 and 9 are not counted, a choice step 2 recorded and the user accepted |
| A5 | ReplaySource reveals feeds at `SenestRettet`, in order, speed-scaled, injected clock | Met | `test_replay.py`: starts 0/92, ordered steps with ties in overview order, mid-sequence snapshots, final snapshot `==` static election, sleeps equal gap/speed, none at `inf`, bad speeds `ValueError`; all use an injected `sleep`, no real waiting (full suite 696 passed in 8.7 s) |
| A6 | `replay <dir> [--speed N]` prints each reveal with progress, ends with national table, exit 0; bad dir readable error and non-zero | Met | `python -m dkvalg replay tests/fixtures/folketingsvalg_2026 --speed inf`: 107 lines, e.g. `2026-03-24 21:21:09   1/92  opstillingskreds 3.Tønder`, ending `92/92 tally ...`, then the "Hele landet" table with "Uden for partier" last, rc 0. Empty directory: stderr `error: feed file not found: .../valgdag.xml`, rc 1. `test_cli.py` covers empty, EP, malformed and missing-feed directories (exit 1, empty stdout), bad speed (exit 2) |
| A7 | Real-feed quirks | Met | `test_folketingsvalg.py`: BOM and BOM-less parse equal, every fixture starts with a BOM (`test_fixtures.py`); empty `Id` kept as non-party (fixture probe `['Uden for partier']`); status 0, 9 and 10 give figure-free places (status 9 is `Status.ERROR`, no crash); `test_directory.py` missing feed raises `FeedError` naming the file; 58 selected quirk/CLI/replay tests pass |

Other checks. Out of scope: `grep -rliE 'appdaemon|home.?assistant|apps\.yaml|valg_opdateret'` matches only this plan file (where it is listed as out of scope), nothing in `src/`, `tests/`, README or docs; no `HttpSource`, `diff.py`, EP/FA adapter or fintael code (grep of `src`); no network imports (`urllib`, `requests`, `socket`, `http`, `urlopen`) in `src` or `tests`. Surface: public API is the one the concept implies (model, `load_election`, `ReplaySource`, CLI), nothing extra. Replay assumption as written: aggregates appear late, the last reveals are Hovedstaden, Københavns Storkreds, Hele landet and the tally at 00:12:26. Showcases: `python -m dkvalg.<module>` for errors, model, adapters.folketingsvalg, sources.directory, sources.replay exit 0. Structure: the auditor reported in sync; the only nit is that the `tests/conftest.py` entry omits the constants `BOM`, `ELECTION_NAME` and `PARTIES_XML`, which are not public API and need no entry. Gates: `ruff check .` clean, `mypy` no issues in 27 files, `pytest` 696 passed.

Drift found, and what was done about it: none. Everything in section 1 is built and nothing outside it. The step 5 fixes (nine adapter hardening changes, section 5) stay within the concept: they make A7 and A6 stricter and add no feature. No code was changed in this step.

### Earlier rounds still hold

First round; nothing to re-check.

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
