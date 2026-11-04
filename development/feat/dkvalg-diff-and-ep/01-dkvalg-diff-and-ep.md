# dkvalg: EP-valg adapter and snapshot diff

<!-- claude-plan step=2 status=active -->

| Field | Value |
|---|---|
| Feature | `feat/dkvalg-diff-and-ep` (the folder) |
| Round | 1 |
| Branch | `feat/dkvalg-diff-and-ep` |
| Version | `minor` — two additions to the existing library (a second election type through the same feed machinery, and a change-detection function); step 9 adds `1.1.0 → 1.2.0` (major, 2.0.0, was the alternative) |
| Started | 2026-11-04 |

## Progress

| # | Step | Skill | Runs | Status |
|---|---|---|---|---|
| 1 | Conceptualize | `/conceptualize` | with the user | done |
| 2 | Plan | `/plan` | with the user, unless the critique is clean | in progress |
| 3 | Implement | `/implement` | in `/build` | pending |
| 4 | Verify | `/verify` | in `/build` | pending |
| 5 | Test | `/test` | in `/build` | pending |
| 6 | Concept check | `/concept-check` | in `/build` | pending |
| 7 | Ship | `/ship` | in `/build` | pending |
| 8 | Recommend | `/recommend` | with the user | pending |
| 9 | Pull request | `/create-pr` | with the user | pending |
| 10 | Review | `/watch-pr` | on the pull request | pending |

Statuses: `pending`, `in progress`, `done`.

## Builds on

Nothing on this branch: this is its first round. It builds on what `main` holds from `development/feat/dkvalg-folketingsvalg-replay/` (PR #2) and `development/feat/dkvalg-live-polling/` (PR #3), version 1.1.0: the model, the Folketingsvalg adapter, `load_election`/`build_election`, `HttpSource`, `poll`, `Recorder`, `ReplaySource`, `CaptureReplay`, `Election.changed_since` and the CLI. This round must not break them, except the two tests named in A9.

---

## 1. Concept

### What this is

Two additions to `dkvalg`, one for each of the library's remaining promises from the original spec.

**Europa-Parlamentsvalg.** `dkvalg` reads EP elections as well as Folketingsvalg ones into the same normalised model. `ElectionType` gets an EP member, the election type is recognised from the overview's `ValgNavn`, and `load_election`, `HttpSource`, `poll`, `ReplaySource`, `CaptureReplay`, `Recorder` and the CLI work for EP unchanged from the caller's side. Inspection of the real 9 June 2024 feeds (`Valg2546524`, 2026-11-04) shows the EP feeds have **the same structure as the Folketingsvalg feeds**: the same 107 places (hele landet, the "optalling" tally, 3 landsdele, 10 storkredse, 92 opstillingskredse), the same status codes and timestamps, and a `ValgNavn` of `Europa-Parlamentsvalg søndag  9. juni 2024` (note the double space). The one real difference is that **the EP feeds carry no seat attributes at all** (no `Mandater`, `Kredsmandater` or `Tillaegsmandater`), so every EP seat field is `None`. Each election type keeps its own adapter module, as the spec asked, because the formats are free to diverge.

**diff.** A function that compares two `Election` snapshots and returns typed changes, for a caller (the user's separate Home Assistant project) that wants to raise notifications. It goes beyond round 2's `Election.changed_since`, which only lists which places differ. The changes: a place becoming counted; a party's result at a place changing (votes, percent and, where DST gives seats, seats, so a seat shift is visible as a before and after); the leader (the party with most votes) at a place changing; a place's status changing; and counting progress changing. The library only detects; it formats and notifies nothing.

### Why it is worth building

A live night is a stream of snapshots, and "SF just overtook Socialdemokratiet nationally" or "the Hovedstaden storkreds gained a seat for Å" are the events a dashboard or notification wants, not 107 `Place` objects. EP elections recur every five years and have the same feed machinery, so supporting them now means the next one needs no new code. Both were in the original spec (`diff.py`, adapters per election type).

### Inputs and outputs

EP: the same inputs as today (a directory, an id or URL, a capture directory), producing `Election`s whose `election_type` says EP. diff: two `Election`s (the earlier may be `None`) in, a tuple of typed changes out, in a deterministic order (by place in overview order, then change kind, then party order). `diff(None, e)` behaves like a diff against `e` with every place unreported. The inputs are never modified.

### How it connects to the rest of the repo

Reuses the model, `Election.changed_since` (diff's place-level starting point), `parse_place` behaviour (seat attributes are already optional), `load_election` and `build_election`, `HttpSource`, `CaptureReplay` and the CLI. The place where the Folketingsvalg-only check lives today becomes a choice of adapter by election type. The CLI gains a `--diff` flag on `poll` and `replay`. `PollCycle` and `FetchResult` are not changed: the caller diffs consecutive elections itself.

### Explicitly out of scope

- AppDaemon / Home Assistant: nothing, now or in this repo; and no notification text, formatting or delivery.
- Threshold alerts ("progress passed 50 %"): the progress change carries before and after, so the caller decides its thresholds.
- Allocating EP seats (DST does not publish them in these feeds; computing them would be a separate feature), folkeafstemning, kommunal- and regionsvalg, fintaelling (`fintal.xml`) and personal votes, afstemningsomraader, finding the current election id.
- Changing `PollCycle`, `FetchResult` or any round 1 or 2 public signature.

Assumptions (stated, not asked): the election type comes from the overview's `ValgNavn` (it starts `Folketingsvalg` or `Europa-Parlamentsvalg`; anything else stays a `FeedError` naming the value and listing what is supported); the leader of a place is the party (not "Uden for partier") with the most votes, ties going to the earlier party in DST's order; a change in a party's percent alone counts as a result change, since DST rounds; `--diff` prints only the notable changes (leader, seat and status changes, progress), not every vote movement, so its output stays readable; EP fixtures are the real 2024 election, since DST's own example feeds (`EP-valgdagStatus0/1`) are older elections with the same shape.

### Acceptance criteria

| # | The finished feature... |
|---|---|
| A1 | ships a complete real EP fixture set in `tests/fixtures/ep_2024` (`generel.xml`, `valgdag.xml` and all 107 result feeds of 9 June 2024, unmodified, with a README naming the source URLs and retrieval date and a SHA-256 manifest), and `load_election` on it returns an election of the EP type with 107 places (1 country, 1 tally, 3 landsdele, 10 storkredse, 92 opstillingskredse), 92 of 92 opstillingskredse counted, every seat field `None`, and national figures matching the file (4,301,255 eligible voters, turnout 58.23 %, SF 426,367 votes at 17.4 %). |
| A2 | chooses the adapter from the overview's `ValgNavn`: a Folketingsvalg overview and an EP overview each parse into their own election type, the Folketingsvalg adapter on its own still refuses an EP overview, and anything else (for example a folkeafstemning) is refused with a `FeedError` naming the value and the supported types. |
| A3 | works for EP across the stack: a first `HttpSource` fetch through a fake transport serving `ep_2024` equals `load_election` of it; a `Recorder` run over EP replays through `CaptureReplay` ending equal to the last fetch; `ReplaySource` replays the EP election; and `python -m dkvalg replay tests/fixtures/ep_2024 --speed inf` prints 107 lines ending at 92/92 and the national table (seats shown as `-`) and exits 0. |
| A4 | handles the EP feed quirks the Folketingsvalg adapter handles: the double space in `ValgNavn`, a UTF-8 BOM, a status 0 feed (DST's own EP example shape), a never-reported feed, an empty or absent party `Id`, and DOCTYPE or entity declarations refused with a `FeedError` naming the file. |
| A5 | provides a diff function over two `Election`s that is pure (neither input modified), deterministic in its order, returns an empty tuple for equal elections, treats a `None` earlier election as all places unreported, and returns typed changes of five kinds: a place counted, a party result changed, a leader changed, a status changed, and counting progress changed. |
| A6 | reports the right changes on real data: between two Folketingsvalg 2026 snapshots that differ in a party's seats at the national place and in a storkreds, the party result change carries the seats (and votes and percent) before and after; for EP, which has no seats, no seat change is ever reported; the leader change names the old and new leader (the first leader of a place that becomes counted has no old one); a status change carries both statuses; and the progress change carries both counted-of-total pairs. |
| A7 | is consistent with replay: diffing every consecutive pair of snapshots of a `ReplaySource` replay of the 2026 election yields exactly one place-counted change per reported place (107) and ends with Socialdemokratiet as the national leader. |
| A8 | adds a `--diff` flag to `poll` and `replay` that prints one line per notable change (leader, seat and status changes, progress) after each step's place lines, and without the flag the output is byte-for-byte what it was before. |
| A9 | leaves rounds 1 and 2 untouched: every existing test passes unchanged except the two that asserted an EP overview is refused (`test_load_election_an_ep_overview_is_refused` and the EP case of the bad-directory replay test in `test_cli`), which are retargeted to a folkeafstemning overview, still unsupported; Folketingsvalg behaviour and output are unchanged. |

### Open questions

None.

---

## 2. Plan

> Written in step 2, accepted before step 3 starts — by the user, or by a clean critique
> (see `/plan`). Concrete enough that step 3 is transcription, not invention.

### Approach

**EP.** The probe in the survey settles the design: pushed through the existing Folketingsvalg code (with only the election name swapped in memory), the real EP 2024 set parses into exactly the model the concept describes (107 places, no seat data, national figures as in A1). So almost nothing in the adapter is Folketingsvalg-specific; the only election-type logic is the `ValgNavn` check and the `ElectionType` it stamps in `parse_overview`. The plan therefore **moves the shared parsing into a new `adapters/dst_feed.py`** and leaves two thin per-type adapters on top of it, `folketingsvalg` and `europaparlamentsvalg`, each providing the type's `parse_overview` and re-exporting the shared names, which keeps the spec's "one adapter per type" (formats may diverge later) without duplicating 300 lines, and keeps every existing import from `dkvalg.adapters.folketingsvalg` working. A small `adapters/registry.py` chooses the adapter from `ValgNavn` and is what `build_election` and `HttpSource` now call, so `load_election`, `HttpSource`, `poll`, `CaptureReplay`, `Recorder` and the CLI work for EP with no further change. `parse_place` stays shared and election-type-independent; if a future type's result feeds diverge, the registry is where a type-specific `parse_place` would be routed (not built now).

**diff.** One new module, `diff.py`, with five frozen dataclasses (one per kind of change), a `Change` union and one pure function, `diff_elections`. "Leader of a place" becomes a `Place.leader` property in the model so diff and the CLI share one definition. The function is named `diff_elections` rather than `diff` so that re-exporting it from the package cannot shadow the `dkvalg.diff` module. Detection is place by place, matched on place type and id, in the current election's order, with a single closing progress change.

Rejected: (a) copying the Folketingsvalg adapter into an EP module, which would duplicate the parser and let the two drift; (b) one adapter accepting both names (it would break A2 and the existing test that the Folketingsvalg adapter refuses an EP overview); (c) putting diff on `Election` as a method (a different file from where the spec put it, and it would grow the model with presentation-adjacent types); (d) a notification-ready formatter in `diff.py`, which the concept rules out (the library only detects).

Survey: `parse_place`, `unreported_place`, `FeedRef`, `Overview`, the hardening and all timestamp/number helpers live in `adapters/folketingsvalg.py` and nothing in them mentions the election type except lines 249 to 256. `directory.build_election` and `HttpSource` both import `parse_overview` from that module (the two places that must become type-aware); everything else, including `CaptureReplay`, goes through `build_election`. `Election.changed_since` is reused unchanged and diff does not call it. Existing tests import `FeedRef`, `Overview`, `parse_overview`, `parse_place`, `unreported_place` from `dkvalg.adapters.folketingsvalg` and use no private names, so a re-exporting wrapper keeps them valid; only two existing tests assert that an EP overview is refused (`test_load_election_an_ep_overview_is_refused` in `test_directory.py` and the EP case of the bad-directory replay test in `test_cli.py`) and A9 retargets exactly those.

### Modules

| Path | New or changed | Purpose |
|---|---|---|
| `src/dkvalg/model.py` | changed | `ElectionType.EUROPAPARLAMENTSVALG`; `Place.leader` (A1, A5, A6) |
| `src/dkvalg/adapters/dst_feed.py` | new | The election-type-independent DST feed parsing, moved out of the Folketingsvalg adapter (A1 to A4, A9) |
| `src/dkvalg/adapters/folketingsvalg.py` | changed | Thin: `parse_overview` for Folketingsvalg plus re-exports of the shared names (A2, A9) |
| `src/dkvalg/adapters/europaparlamentsvalg.py` | new | Thin: `parse_overview` for Europa-Parlamentsvalg plus the same re-exports (A1, A2, A4) |
| `src/dkvalg/adapters/registry.py` | new | `parse_any_overview`: choose the adapter from `ValgNavn` (A2, A3) |
| `src/dkvalg/sources/directory.py`, `sources/http_source.py` | changed | Call `parse_any_overview` instead of the Folketingsvalg `parse_overview`; no signature change (A3) |
| `src/dkvalg/diff.py` | new | Change kinds, `Change`, `diff_elections` (A5 to A7) |
| `src/dkvalg/cli.py` | changed | `--diff` on `poll` and `replay` (A8) |
| `src/dkvalg/__init__.py` | changed | Re-export the new public names |
| `tests/fixtures/ep_2024/` | new | The 109 unmodified real EP feeds, `README.md`, `SHA256SUMS` (A1) |
| `tests/conftest.py` | changed | EP fixture path and helpers |
| `tests/test_europaparlamentsvalg.py`, `test_registry.py`, `test_diff.py` | new | (step 5) |
| `tests/test_model.py`, `test_folketingsvalg.py`, `test_directory.py`, `test_http_source.py`, `test_capture.py`, `test_cli.py`, `test_fixtures.py`, `test_package.py` | changed | New cases; the two retargeted tests named in A9 are the only existing cases edited (step 3 retargets them, step 5 adds the rest) |
| `README.md`, `STRUCTURE.md`, `DEVELOPMENT.md` | changed | EP and `--diff` usage; structure map; the EP-seats note is already added |
| `pyproject.toml` | untouched | Step 9 writes the version |

### Public API

Existing signatures not listed here do not change. `FeedRef`, `Overview`, `parse_place` and `unreported_place` keep their signatures and are re-exported from `dkvalg.adapters.folketingsvalg` (as they were) and from `dkvalg.adapters.europaparlamentsvalg`; their definitions move to `dkvalg.adapters.dst_feed`.

| Signature | Module | Purpose | Covers |
|---|---|---|---|
| `ElectionType.EUROPAPARLAMENTSVALG = "europaparlamentsvalg"` | `model` | The EP member of the existing `StrEnum` | A1, A2 |
| `Place.leader` (property) `-> PartyResult \| None` | `model` | The party with the most votes at a place that has a result, "Uden for partier" never counted, ties to the party earlier in the feed; `None` without a result or a party | A5, A6 |
| `class FeedRef`, `class Overview` (fields as today) | `adapters.dst_feed` | Moved, unchanged | A9 |
| `election_name(xml: bytes) -> str` | `adapters.dst_feed` | The stripped `ValgNavn` of an overview (hardened parse); `FeedError` naming `valgdag.xml` when malformed or absent | A2 |
| `parse_overview_for(xml: bytes, election_type: ElectionType, name_prefix: str) -> Overview` | `adapters.dst_feed` | Parse `valgdag.xml` as `election_type` when `ValgNavn` starts with `name_prefix`; otherwise `FeedError("valgdag.xml: not a <name_prefix>, ValgNavn is <name>")`; otherwise exactly today's behaviour | A1, A2, A9 |
| `parse_place(xml: bytes, ref: FeedRef) -> Place`, `unreported_place(ref: FeedRef) -> Place` | `adapters.dst_feed` | Moved, unchanged | A4, A9 |
| `parse_overview(xml: bytes) -> Overview` | `adapters.folketingsvalg` | `parse_overview_for(xml, ElectionType.FOLKETINGSVALG, "Folketingsvalg")`; behaviour and messages unchanged | A2, A9 |
| `parse_overview(xml: bytes) -> Overview` | `adapters.europaparlamentsvalg` | `parse_overview_for(xml, ElectionType.EUROPAPARLAMENTSVALG, "Europa-Parlamentsvalg")` | A1, A2, A4 |
| `parse_any_overview(xml: bytes) -> Overview` | `adapters.registry` | Read the name with `election_name` and call the matching adapter's `parse_overview`; anything else raises `FeedError("valgdag.xml: not a supported election (Folketingsvalg, Europa-Parlamentsvalg), ValgNavn is <name>")` | A2, A3 |
| `@dataclass(frozen=True, slots=True) class PlaceCounted`: `place: Place` | `diff` | A place that has a result now and had none before | A5, A6 |
| `@dataclass(frozen=True, slots=True) class PartyResultChanged`: `place: Place`, `before: PartyResult \| None`, `after: PartyResult`; properties `votes_delta -> int \| None`, `seats_delta -> int \| None` | `diff` | A party's result at a place that had a result in both snapshots changed (votes, percent or any seat figure), or the party is new there (`before` is `None`); the deltas are `None` when `before` is `None`, and `seats_delta` is also `None` when either side has no seat figure | A5, A6 |
| `@dataclass(frozen=True, slots=True) class LeaderChanged`: `place: Place`, `before: PartyResult \| None`, `after: PartyResult` | `diff` | The leader at a place is a different party, or the place now has a leader and had none | A5, A6 |
| `@dataclass(frozen=True, slots=True) class StatusChanged`: `place: Place`, `before: Status`, `after: Status` | `diff` | A place's status changed in a way that is not a place being counted | A5, A6 |
| `@dataclass(frozen=True, slots=True) class ProgressChanged`: `before: CountingProgress`, `after: CountingProgress` | `diff` | The counted-of-total opstillingskredse changed | A5, A6 |
| `type Change = PlaceCounted \| PartyResultChanged \| LeaderChanged \| StatusChanged \| ProgressChanged` | `diff` | The union of the five | A5 |
| `diff_elections(previous: Election \| None, current: Election) -> tuple[Change, ...]` | `diff` | The typed changes from `previous` to `current` (see Behaviour); `ValueError` naming both if the two differ in `election_type` or `election_date` | A5 to A7 |
| `main() -> None` | `adapters.dst_feed`, `adapters.europaparlamentsvalg`, `adapters.registry`, `diff` | Showcases (the Folketingsvalg adapter keeps its own) | A9 |

`dkvalg/__init__.py` additionally re-exports `diff_elections`, `Change`, `PlaceCounted`, `PartyResultChanged`, `LeaderChanged`, `StatusChanged` and `ProgressChanged`; the registry, `dst_feed` and the adapters stay in their modules. `run` and every other round 1 and 2 signature are unchanged.

Behaviour the signatures do not carry:

- **`diff_elections`.** `previous=None` behaves as if every place of `current` were present and unreported. Places are matched on `(place_type, place_id)`; a place only in `current` is compared with its own `unreported()` form, a place only in `previous` is ignored. For each place of `current`, in order: (1) `PlaceCounted` if it has a result now and had none; otherwise `StatusChanged` if the status differs (so 0 to 1 is a count, not a status change, while 1 to 9, 1 to 11 and 0 to 9 are status changes); (2) if it had a result in both snapshots, a `PartyResultChanged` for each party of `current`, in feed order, whose `votes`, `percent`, `seats`, `constituency_seats` or `supplementary_seats` differ from the same `party_id` in `previous` or which is absent there; a party that vanished is ignored; (3) `LeaderChanged(place, before, after)` if `current`'s leader exists and `previous`'s leader is `None` or a different `party_id`. After all places, one `ProgressChanged` if `counting_progress()` differs (the previous progress of `None` being 0 of the current total). Equal elections give `()`. Neither input is modified.
- **Leader.** The `is_party` party with the most `votes`; on a tie the earlier in feed order; `None` if the place has no result or no party. A change of votes or percent alone never changes the leader's identity, so it is a `PartyResultChanged` only.
- **Adapter choice.** `election_name` runs the same hardened parse as the adapters, so a DOCTYPE in an overview is refused before the name is read. Matching is `startswith` and case-sensitive, as for Folketingsvalg today, so `ValgNavn` `Europa-Parlamentsvalg søndag  9. juni 2024` (double space) matches and `Europaparlamentsvalg` would be refused with the supported types listed.
- **CLI `--diff`.** On `poll` and `replay`, after each step's (or poll's) place lines and only when the flag is given, one line per *notable* change between the previous snapshot (`ReplaySource.initial()`, the previous `CaptureStep` or `PollCycle` election, `None` first) and the current one, using the same timestamp as the place lines. Notable: `LeaderChanged` at `COUNTRY`, `LANDSDEL` and `STORKREDS` places (not at opstillingskredse, not at the tally); `PartyResultChanged` with a non-zero `seats_delta`; `StatusChanged`; `ProgressChanged`. Formats: `<time>  leader <place type> <name>: <before letter or -> -> <after letter>`; `<time>  seats <place type> <name>: <party letter> <before> -> <after>`; `<time>  status <place type> <name>: <before.name> -> <after.name>`; `<time>  progress <before> -> <after>`. Without the flag nothing changes. A poll cycle that failed prints no diff lines.

### Implementation guide

1. `model.py`: the EP member and `Place.leader`.
2. Create `adapters/dst_feed.py` by moving the shared code out of `folketingsvalg.py` (everything except the type check), add `election_name` and `parse_overview_for`; make `folketingsvalg.py` the thin wrapper with `__all__`. **Run the whole existing suite: it must be green unchanged** before anything else.
3. `adapters/europaparlamentsvalg.py`, `adapters/registry.py`; switch `directory.build_election` and `HttpSource` to `parse_any_overview`; retarget the two tests named in A9 to a folkeafstemning overview (they are the only existing tests edited) and run the suite green again.
4. Fixtures: download `generel.xml`, `valgdag.xml` and every `filnavn` of `https://www.dst.dk/valg/Valg2546524/xml/valgdag.xml` unmodified into `tests/fixtures/ep_2024/` (109 files; `fintal.xml` is not part of it) with a `SHA256SUMS` and a `README.md` (source URLs, retrieval date). If the network refuses, halt.
5. `diff.py` with its showcase.
6. CLI `--diff` for `poll`, plain `replay` and capture `replay`.
7. `__init__` re-exports, README (EP and `--diff`), `STRUCTURE.md`, showcases for the new modules.

### Test intents

| # | Must prove | Covers |
|---|---|---|
| T1 | The `ep_2024` directory holds the 109 XML files plus README and `SHA256SUMS`, every file matches its hash with its BOM intact; `load_election` of it is an EP election with 107 places (1/1/3/10/92 by type), 92 of 92 counted, every seat field `None`, 4,301,255 eligible, 58.23 % turnout, SF 426,367 votes at 17.4 %, correct parent ids | A1 |
| T2 | `parse_any_overview` gives each type from its own overview; the Folketingsvalg adapter refuses EP and the EP adapter refuses Folketingsvalg; folkeafstemning, kommunalvalg, lower-case, a name with a leading space and an empty name are refused with the name and the supported types in the message; the double-space name is accepted; `load_election` of each fixture set reports its own type | A2 |
| T3 | EP through the stack: an `HttpSource` first fetch through a fake transport serving `ep_2024` equals `load_election`; a second fetch is unchanged; a recorded EP poll replays through `CaptureReplay` ending equal to the last fetch; `ReplaySource` of EP ends equal; the `replay` CLI on `ep_2024` prints 107 lines ending 92/92 and the table with `-` seats, exit 0; `poll` on an EP fake transport prints its lines | A3 |
| T4 | EP quirks: BOM and BOM-less overviews parse equal; a status 0 feed (DST's own EP example shape) is figure-free; a never-reported feed is a placeholder; an absent or empty party `Id` behaves as for Folketingsvalg; a DOCTYPE or entity in an EP overview or result feed is refused naming the file | A4 |
| T5 | `diff_elections`: equal elections give `()`; neither input is mutated; the order is deterministic; `None` previous equals diffing against an all-unreported copy; a place only in `current` and one only in `previous`; a mismatch in type or date is a `ValueError` naming both; every one of the five kinds can be produced | A5 |
| T6 | Semantics on real data: a changed seat at the national place and at a storkreds in a modified copy of the 2026 election gives `PartyResultChanged` with before and after seats, votes and percent and the right deltas; a percent-only change counts; a new party has `before is None`; EP changes never carry a seat delta; `LeaderChanged` for an overtake, for the first leader of a newly counted place (`before is None`), tie rule, "Uden for partier" never leads, no leader change when only votes move; `StatusChanged` for 1 to 9, 1 to 11, 0 to 9 and not for 0 to 1; `ProgressChanged` with both pairs; `Place.leader` on its own | A6 |
| T7 | Diffing each consecutive pair of `ReplaySource` snapshots of the 2026 election yields 107 `PlaceCounted` in total, ends the `ProgressChanged` chain at 92 of 92 and ends with the national leader Socialdemokratiet; the same for the EP election with SF as national leader | A7 |
| T8 | `--diff` prints exactly the notable lines in the stated formats on `replay` (plain and capture) and on `poll`, restricts leader lines to country, landsdel and storkreds, and the output without the flag equals the output with the diff lines removed; a failed poll cycle prints no diff lines | A8 |
| T9 | Every existing test passes unchanged except the two retargeted ones; `from dkvalg.adapters.folketingsvalg import FeedRef, Overview, parse_overview, parse_place, unreported_place` still works; Folketingsvalg messages unchanged | A9 |

### Risks

- **The adapter refactor can break round 1 and 2 behaviour.** The existing suite is the guard and runs green after step 2 of the guide before any EP code exists. If a failure other than the two retargeted tests appears, fix the code (not the test). If an existing test other than those two asserts that EP is refused, **halt**: A9 names exactly two.
- **The real EP data could surprise the shared parser.** It did not in the probe (all 107 feeds parse, no seats). If the build finds a feed the parser rejects, that is an adapter bug to fix in `dst_feed`; if it would need a change to the model beyond the EP member, **halt**.
- **Spelling of the election name.** DST writes `Europa-Parlamentsvalg`; a future spelling change is refused with a clear message rather than guessed at.
- **`diff` can be noisy.** The function reports everything; the CLI filters to the notable kinds. Thresholds are the caller's business (out of scope).
- **Module and function naming.** `diff_elections`, not `diff`, so that `dkvalg.diff` stays the module; `Change` uses the `type` statement (Python 3.12+, the project requires 3.13).
- **Time kinds.** Unchanged from round 2: `Place.last_changed` is naive Danish local time, fetch and capture times are timezone-aware UTC; `diff` compares neither.
- **Two election types, one parser.** If a later election type's result feeds differ, the registry is the place to route a type-specific `parse_place`; not built now.

### Critique

(Filled in after the plan-critic has read this plan.)

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
