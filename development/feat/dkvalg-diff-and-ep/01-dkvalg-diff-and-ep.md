# dkvalg: EP-valg adapter and snapshot diff

<!-- claude-plan step=6 status=active -->

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
| 2 | Plan | `/plan` | with the user, unless the critique is clean | done |
| 3 | Implement | `/implement` | in `/build` | done |
| 4 | Verify | `/verify` | in `/build` | done |
| 5 | Test | `/test` | in `/build` | done |
| 6 | Concept check | `/concept-check` | in `/build` | in progress |
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

`diff_elections` does not build on `Election.changed_since` (section 1 names it as the place-level starting point) on purpose: `changed_since` skips places without a `last_changed`, so it cannot see a place falling back to a status without a result, and diff compares every matched place instead. `changed_since` stays the cheap "which places moved" list for `HttpSource`.

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
| `tests/test_europaparlamentsvalg.py`, `test_registry.py`, `test_dst_feed.py`, `test_diff.py` | new | (step 5); `test_dst_feed.py` covers `election_name` and `parse_overview_for`, while `test_folketingsvalg.py` stays the suite for the shared parsing behaviour through the Folketingsvalg adapter |
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
| `@dataclass(frozen=True, slots=True) class PlaceCounted`: `place: Place` | `diff` | A place whose earlier status was `NOT_AVAILABLE` (a placeholder) and that has a result now | A5, A6 |
| `@dataclass(frozen=True, slots=True) class PartyResultChanged`: `place: Place`, `before: PartyResult \| None`, `after: PartyResult`; properties `votes_delta -> int \| None`, `seats_delta -> int \| None` | `diff` | A party's result at a place that had a result in both snapshots changed (votes, percent or any seat figure), or the party is new there (`before` is `None`); the deltas are `None` when `before` is `None`, and `seats_delta` is also `None` when either side has no seat figure | A5, A6 |
| `@dataclass(frozen=True, slots=True) class LeaderChanged`: `place: Place`, `before: PartyResult \| None`, `after: PartyResult` | `diff` | The leader at a place is a different party, or the place now has a leader and had none | A5, A6 |
| `@dataclass(frozen=True, slots=True) class StatusChanged`: `place: Place`, `before: Status`, `after: Status` | `diff` | A place's status changed, other than from `NOT_AVAILABLE` to a status with a result (that is a `PlaceCounted`) | A5, A6 |
| `@dataclass(frozen=True, slots=True) class ProgressChanged`: `before: CountingProgress`, `after: CountingProgress` | `diff` | The counted-of-total opstillingskredse changed | A5, A6 |
| `type Change = PlaceCounted \| PartyResultChanged \| LeaderChanged \| StatusChanged \| ProgressChanged` | `diff` | The union of the five | A5 |
| `diff_elections(previous: Election \| None, current: Election) -> tuple[Change, ...]` | `diff` | The typed changes from `previous` to `current` (see Behaviour); `ValueError` naming both if the two differ in `election_type` or `election_date` | A5 to A7 |
| `main() -> None` | `adapters.dst_feed`, `adapters.europaparlamentsvalg`, `adapters.registry`, `diff` | Showcases (the Folketingsvalg adapter keeps its own) | A9 |

`dkvalg/__init__.py` additionally re-exports `diff_elections`, `Change`, `PlaceCounted`, `PartyResultChanged`, `LeaderChanged`, `StatusChanged` and `ProgressChanged`; the registry, `dst_feed` and the adapters stay in their modules. `run` and every other round 1 and 2 signature are unchanged.

Behaviour the signatures do not carry:

- **`diff_elections`.** `previous=None` behaves as if every place of `current` were present and unreported. Places are matched on `(place_type, place_id)`; a place only in `current` is compared with its own `unreported()` form, a place only in `previous` is ignored. For each place of `current`, in order: (1) `PlaceCounted` if the earlier place's status is `NOT_AVAILABLE` and it has a result now (a 0 to 1 transition); otherwise `StatusChanged` if the status differs, so 1 to 9, 1 to 11, 10 to 11, 9 to 1 and 0 to 9 are status changes and none of them is a count; (2) if it had a result in both snapshots, a `PartyResultChanged` for each party of `current`, in feed order, whose `votes`, `percent`, `seats`, `constituency_seats` or `supplementary_seats` differ from the same `party_id` in `previous` or which is absent there; a party that vanished is ignored; (3) `LeaderChanged(place, before, after)` if `current`'s leader exists and `previous`'s leader is `None` or a different `party_id`. After all places, one `ProgressChanged` if `counting_progress()` differs (the previous progress of `None` being 0 of the current total). Equal elections give `()`. Neither input is modified.
- **Leader.** The earlier leader is `None` whenever the earlier place carried no figures (status 0, 9 or 10), so a place that recovers from 9 or 10 reports its leader with `before` `None`. The leader is the `is_party` party with the most `votes`; on a tie the earlier in feed order; `None` if the place has no result or no party. A change of votes or percent alone never changes the leader's identity, so it is a `PartyResultChanged` only.
- **Adapter choice.** `election_name` runs the same hardened parse as the adapters, so a DOCTYPE in an overview is refused before the name is read. Matching is `startswith` and case-sensitive, as for Folketingsvalg today, so `ValgNavn` `Europa-Parlamentsvalg søndag  9. juni 2024` (double space) matches and `Europaparlamentsvalg` would be refused with the supported types listed.
- **CLI `--diff`.** On `poll` and `replay`, after each step's (or poll's) place lines and only when the flag is given, one line per *notable* change between the previous snapshot (`ReplaySource.initial()`, the previous `CaptureStep` or `PollCycle` election, `None` first) and the current one, using the same timestamp as the place lines. Notable: `LeaderChanged` at `COUNTRY`, `LANDSDEL` and `STORKREDS` places (not at opstillingskredse, not at the tally); `PartyResultChanged` with a non-zero `seats_delta`, or whose seats go from none to a figure (printed `<letter> - -> <after>`; DST may publish seats only once they are allocated); `StatusChanged`; `ProgressChanged`. Formats: `<time>  leader <place type> <name>: <before letter or -> -> <after letter>`; `<time>  seats <place type> <name>: <party letter> <before> -> <after>`; `<time>  status <place type> <name>: <before.name> -> <after.name>`; `<time>  progress <before> -> <after>`. Without the flag nothing changes. A poll cycle that failed prints no diff lines.

### Implementation guide

1. `model.py`: the EP member and `Place.leader`.
2. Create `adapters/dst_feed.py` by moving the shared code out of `folketingsvalg.py` (everything except the type check), add `election_name` and `parse_overview_for`; make `folketingsvalg.py` the thin wrapper with `__all__`. **Run the whole existing suite: it must be green unchanged** before anything else.
3. `adapters/europaparlamentsvalg.py`, `adapters/registry.py`; switch `directory.build_election` and `HttpSource` to `parse_any_overview`; retarget the two tests named in A9 to a folkeafstemning overview (they are the only existing tests edited) and run the suite green again.
4. Fixtures: download `generel.xml`, `valgdag.xml` and every `filnavn` of `https://www.dst.dk/valg/Valg2546524/xml/valgdag.xml` unmodified into `tests/fixtures/ep_2024/` (109 files; `fintal.xml` is not part of it) with a `SHA256SUMS` and a `README.md` (source URLs, retrieval date). If the network refuses, fall back to the identical set the planner downloaded on 2026-11-04 into `/tmp/claude-0/-home-user-valg-data/d285c151-1f0b-5ebe-b617-d9e05602daaa/scratchpad/ep2024/` (copy everything except `fintal.xml`; check that it holds `generel.xml`, `valgdag.xml` and exactly the 107 `filnavn` files of the overview, unmodified, BOM intact; record the retrieval date 2026-11-04 in the README); halt only if both the network and that copy are unavailable.
5. `diff.py` with its showcase.
6. CLI `--diff` for `poll`, plain `replay` and capture `replay`.
7. `__init__` re-exports, README (EP and `--diff`), `STRUCTURE.md`, showcases for the new modules.

### Test intents

| # | Must prove | Covers |
|---|---|---|
| T1 | The `ep_2024` directory holds the 109 XML files plus README and `SHA256SUMS`, every file matches its hash with its BOM intact; `load_election` of it is an EP election with 107 places (1/1/3/10/92 by type), 92 of 92 counted, every seat field `None`, 4,301,255 eligible, 58.23 % turnout, SF 426,367 votes at 17.4 %, correct parent ids; the fixtures README names `https://www.dst.dk/valg/Valg2546524/xml/` and the retrieval date | A1 |
| T2 | `parse_any_overview` gives each type from its own overview; the Folketingsvalg adapter refuses EP and the EP adapter refuses Folketingsvalg; folkeafstemning, kommunalvalg, a lower-case `folketingsvalg` and `x Folketingsvalg` are refused with the name and the supported types in the message; a name with leading or trailing whitespace is accepted once stripped, as the Folketingsvalg adapter does today; an absent or empty `ValgNavn` is refused with `valgdag.xml: no ValgNavn`; the double-space name is accepted; `load_election` of each fixture set reports its own type | A2 |
| T3 | EP through the stack: an `HttpSource` first fetch through a fake transport serving `ep_2024` equals `load_election`; a second fetch is unchanged; a recorded EP poll replays through `CaptureReplay` ending equal to the last fetch; `ReplaySource` of EP ends equal; the `replay` CLI on `ep_2024` prints 107 lines ending 92/92 and the table with `-` seats, exit 0; `poll` on an EP fake transport prints its lines | A3 |
| T4 | EP quirks: BOM and BOM-less overviews parse equal; a status 0 feed (built synthetically under the EP `ValgNavn` in the shape of DST's EP example: `Status Kode="0"`, no `Stemmer`, no `Stemmeberettigede`) is figure-free; a never-reported feed is a placeholder; an absent or empty party `Id` behaves as for Folketingsvalg; a DOCTYPE or entity in an EP overview or result feed is refused naming the file | A4 |
| T5 | `diff_elections`: equal elections give `()`; neither input is mutated; the order is deterministic; `None` previous equals diffing against an all-unreported copy; a place only in `current` and one only in `previous`; a mismatch in type or date is a `ValueError` naming both; every one of the five kinds can be produced (tests inspect the `Change` alias with `typing.get_args(Change.__value__)`, since `isinstance` does not accept a `type` alias) | A5 |
| T6 | Semantics on real data: a changed seat at the national place and at a storkreds in a modified copy of the 2026 election gives `PartyResultChanged` with before and after seats, votes and percent and the right deltas; a percent-only change counts; a new party has `before is None`; EP changes never carry a seat delta; `LeaderChanged` for an overtake, for the first leader of a newly counted place (`before is None`), tie rule, "Uden for partier" never leads, no leader change when only votes move; `StatusChanged` for 1 to 9, 1 to 11, 10 to 11, 9 to 1 and 0 to 9 (none of them a `PlaceCounted`) and not for 0 to 1, which is a `PlaceCounted`; `ProgressChanged` with both pairs; `Place.leader` on its own | A6 |
| T7 | Diffing each consecutive pair of `ReplaySource` snapshots of the 2026 election yields 107 `PlaceCounted` in total, ends the `ProgressChanged` chain at 92 of 92 and ends with the national leader Socialdemokratiet; the same for the EP election with SF as national leader | A7 |
| T8 | `--diff` prints exactly the notable lines in the stated formats on `replay` (plain and capture) and on `poll`, restricts leader lines to country, landsdel and storkreds, prints a seat line when seats first appear (none to a figure), and the output without the flag equals the output with the diff lines removed; a failed poll cycle prints no diff lines | A8 |
| T10 | `election_name` returns the stripped name and raises `FeedError` naming `valgdag.xml` for malformed XML, a DOCTYPE and an absent or empty `ValgNavn`; `parse_overview_for` refuses a name without the prefix with `not a <prefix>`, accepts the prefix after stripping, and parses exactly as the Folketingsvalg adapter did; `test_package` checks that the seven diff names are re-exported from `dkvalg` and that `parse_any_overview`, `election_name` and `parse_overview_for` stay out of the top level | A2, A5, A9 |
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

Plan-critic findings (verdict: accept with the changes below), 2026-11-04. The critic confirmed the leaders from the fixtures (FV 2026: A 779,524 vs F 413,465; EP 2024: F 426,367 vs A 381,494), the 107-count of A7, and that A9's "exactly two tests" is true.

1. **`PlaceCounted` swallowed recounts and recoveries (10 to 11, 9 to 1).** Applied: `PlaceCounted` only from `NOT_AVAILABLE`; every other status difference is a `StatusChanged`; the leader note says the earlier leader is `None` when the earlier place had no figures; T6 cases added. A7 is unaffected (replay only does 0 to 1).
2. **T2 contradicted `election_name` and today's Folketingsvalg behaviour (stripped names, empty name message).** Applied: T2 rewritten to accept stripped whitespace, refuse an empty name with `no ValgNavn`, and keep the supported-types message for the other refusals.
3. **Missing test intents.** Applied: `test_dst_feed.py` and a new T10 for `election_name` and `parse_overview_for`; README needles in T1; a synthetic status-0 case in T4; the diff re-exports and the kept-out names in T10; a note on inspecting the `type` alias.
4. **Section 1 says diff reuses `changed_since`, the plan does not call it.** Applied: one paragraph in the Approach saying why comparing every matched place is deliberate.
5. **`--diff` would never print seats first appearing (none to a figure).** Applied: notable, with a T8 case.
6. **Avoidable halt on the fixture download.** Applied: fall back to the identical set already downloaded; halt only if both are unavailable.

Accepted: clean critique, 2026-11-04 (all six findings applied in full, none rebutted, none a question for the user).

---

## 3. Implementation notes

> Written in step 3. Only deviations from the plan above, each with its reason. "Built as
> planned" is a complete and good entry. On a fix round, also the reproduction test's red
> run, pasted here before the fix was written — step 6 cites it.

Built as planned, with these details the plan left open:

- The two retargeted tests (`test_load_election_an_ep_overview_is_refused` in `test_directory.py`, the `_ep_directory` case in `test_cli.py`) keep their names and helper name; only the replaced `ValgNavn` (`Folkeafstemning 2022`) and the matched text (`Folkeafstemning`) changed. Step 5 may rename them.
- The `ep_2024` fixtures were downloaded afresh from `https://www.dst.dk/valg/Valg2546524/xml/` on 2026-11-04 (the network was available) rather than copied from the planner's set. 55 result feeds differ from the planner's copy only in the generated `SenestDato`/`SenestRettet` timestamp of when DST regenerated the feed; the content (figures, structure) is identical.
- `diff.py` has a private `_describe` for its showcase; the CLI's `--diff` formatting is the private `_diff_lines` in `cli.py`. Seat lines print when `after.seats` is not None and the earlier seat figure was `None` or differs (a `PartyResultChanged` with a new party counts as seats appearing).
- Docstrings of `directory.py` and `http_source.py` say "supported election type" instead of "Folketingsvalg"; no behaviour or signature change.

---

## 4. Verification log

> Written in step 4: the static half. Command output, not a summary of it.

| Check | Result |
|---|---|
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `67 files already formatted` |
| `mypy` | `Success: no issues found in 35 source files` |
| `pytest` (existing suite) | `1301 passed in 17.51s` |
| Plan completeness | every row of the Public API table checked with `inspect.signature`, dataclass fields and properties: exact match (below) |
| `STRUCTURE.md` | in sync after two edits from the auditor (below) |
| `python -m dkvalg.<module>` | errors, model, adapters.dst_feed, adapters.folketingsvalg, adapters.europaparlamentsvalg, adapters.registry, sources.directory, sources.http_source, sources.capture, sources.replay, diff: all exit 0 with meaningful output (only the expected `RuntimeWarning`) |
| CLI | `replay` on `folketingsvalg_2026` and `ep_2024`, with and without `--diff`: all exit 0; plain output 122 and 120 lines, `--diff` output 228 and 226 lines; the `--diff` output with its leader/seats/status/progress lines removed is identical to the plain output for both; plain output contains none of those lines; EP table shows `-` for every seat |

Plan completeness (all as planned, no Missing, Deviation or Unplanned):

- `model`: `ElectionType.EUROPAPARLAMENTSVALG == "europaparlamentsvalg"`; `Place.leader` is a property `(self) -> PartyResult | None`.
- `adapters.dst_feed`: `election_name(xml: bytes) -> str`, `parse_overview_for(xml, election_type: ElectionType, name_prefix: str) -> Overview`, `parse_place(xml, ref: FeedRef) -> Place`, `unreported_place(ref) -> Place`, frozen slotted `FeedRef`/`Overview` with the same fields, `main() -> None`.
- `adapters.folketingsvalg` and `adapters.europaparlamentsvalg`: `parse_overview(xml: bytes) -> Overview`; `__all__` is `FeedRef, Overview, main, parse_overview, parse_place, unreported_place`; `FeedRef`, `Overview`, `parse_place`, `unreported_place` are the same objects as in `dst_feed`.
- `adapters.registry`: `parse_any_overview(xml: bytes) -> Overview`, `main`.
- `diff`: five frozen slotted dataclasses with the planned fields; `votes_delta`/`seats_delta` properties `-> int | None`; `Change` is a `TypeAliasType` whose `__value__` is the five-member union; `diff_elections(previous: Election | None, current: Election) -> tuple[Change, ...]`; `main`.
- `dkvalg` top level re-exports exactly the 19 earlier names plus `diff_elections`, `Change`, `PlaceCounted`, `PartyResultChanged`, `LeaderChanged`, `StatusChanged`, `ProgressChanged`; `parse_any_overview`, `election_name`, `parse_overview_for` and `parse_overview` are not exported.
- No unplanned public names: the only public functions and classes defined in the new or changed adapter and diff modules are the planned ones.
- `git diff main -U0 -- tests` shows edits to existing tests only in `test_directory.py` and `test_cli.py` (the two A9 retargets, `Europa-Parlamentsvalg 2024` to `Folkeafstemning 2022`); everything else under `tests/` is the new `ep_2024` fixture set. `sha256sum -c SHA256SUMS` in `tests/fixtures/ep_2024` passes.

structure-auditor: both edits were genuine and applied: the `build_election` row in `STRUCTURE.md` now says `parse_any_overview` picks the adapter and unsupported types are a `FeedError`; the top-level paragraph names `parse_overview_for` among the adapter internals kept out of the package namespace. Its other findings were clean. Section 3 notes need no plan-table correction: they record details, not deviations.

---

## 5. Test log

> Written in step 5: the dynamic half.

| Intent | Test names | Result |
|---|---|---|
| T1 (ep_2024 files, hashes, BOM, `load_election` figures, README needles) | `test_fixtures.py`: `test_ep_fixture_directory_holds_109_xml_files_a_readme_and_a_manifest`, `test_every_feed_the_ep_overview_lists_is_present`, `test_the_ep_manifest_lists_exactly_the_xml_files`, `test_every_ep_file_matches_its_sha256_in_the_manifest`, `test_every_ep_xml_file_keeps_its_utf8_byte_order_mark`, `test_the_ep_readme_names_the_source_and_the_retrieval_date`; `test_europaparlamentsvalg.py`: `test_load_election_ep_is_an_ep_election_with_the_real_name`, `test_load_election_ep_has_the_107_places_by_type` (5 params), `test_load_election_ep_counts_92_of_92`, `test_load_election_ep_has_no_seat_figures_anywhere`, `test_load_election_ep_national_figures_match_the_file`, `test_load_election_ep_parent_ids_follow_the_hierarchy`; `test_directory.py`: EP cases | pass |
| T2 (`parse_any_overview`, adapter refusals, name matching, whitespace, empty name, double space) | `test_registry.py` (41 tests: accepted prefixes incl. whitespace, bare prefix, `Folketingsvalgxyz`; 8 refused names; `no ValgNavn`; malformed; DOCTYPE with and without BOM, UTF-16; bad date; no feeds); `test_europaparlamentsvalg.py`: `test_ep_adapter_refuses_a_folketingsvalg_overview`, `test_folketingsvalg_adapter_refuses_the_ep_overview`; `test_directory.py`: `test_load_election_refuses_unsupported_names_naming_them_and_the_supported_types` | pass |
| T3 (EP through HttpSource, Recorder + CaptureReplay, ReplaySource, CLI replay and poll) | `test_europaparlamentsvalg.py`: `test_http_source_*` (4), `test_recorded_ep_poll_replays_through_capture_replay_ending_equal`, `test_replay_source_of_ep_ends_equal_to_the_loaded_election`, `test_cli_replay_of_ep_prints_107_lines_ending_92_of_92`, `test_cli_replay_of_ep_table_shows_dashes_for_every_seat`, `test_cli_poll_on_an_ep_fake_transport_prints_its_lines`; `test_http_source.py`, `test_capture.py`: EP round-three cases | pass |
| T4 (EP quirks) | `test_europaparlamentsvalg.py`: `test_ep_overview_with_and_without_a_bom_parses_equal`, `test_ep_overview_keeps_the_double_space_in_the_name`, `test_ep_status_zero_feed_in_dsts_example_shape_is_figure_free`, `test_ep_never_reported_feed_becomes_a_placeholder`, `test_ep_empty_or_absent_party_id_behaves_as_for_folketingsvalg`, `test_ep_overview_with_a_doctype_is_refused_naming_the_file`, `test_ep_result_feed_with_a_doctype_is_refused_naming_the_file` | pass |
| T5 (`diff_elections`: equal, purity, order, None, only-in-one-side, mismatch, five kinds, alias) | `test_diff.py`: `test_equal_elections_give_an_empty_tuple`, `test_none_previous_equals_diffing_against_an_all_unreported_copy`, `test_diff_elections_does_not_modify_its_inputs_and_is_idempotent`, `test_a_type_mismatch_raises_value_error_naming_both`, `test_a_date_mismatch_raises_value_error_naming_both`, `test_a_place_only_in_current_*`, `test_a_place_only_in_previous_*`, `test_output_follows_currents_order_*`, `test_changes_are_ordered_by_place_then_kind_*`, `test_every_one_of_the_five_kinds_can_be_produced`, `test_change_alias_is_the_union_of_the_five_kinds` | pass |
| T6 (semantics on real data, leader rules, status transitions, progress, `Place.leader`) | `test_diff.py`: `test_a_national_seat_change_carries_seats_votes_and_percent_before_and_after`, `test_a_storkreds_seat_change_*`, `test_any_single_figure_change_*` (5), `test_a_new_party_has_before_none_*`, `test_status_transitions_give_the_documented_kinds` (13), `test_an_overtake_*`, `test_the_first_leader_of_a_newly_counted_place_*`, tie, reordered tie, Uden for partier, all-zero votes, `test_progress_*` (4), `test_ep_changes_never_carry_a_seat_delta`; `test_model.py`: ten `test_place_leader_*` cases | pass |
| T7 (replay consistency) | `test_diff.py`: `test_diffing_every_replay_step_gives_one_place_counted_per_place_and_the_leader[election-A]` and `[ep_election-F]` | pass |
| T8 (`--diff` formats, filter, flag-less equality, failed cycle) | `test_cli.py`: `test_replay_diff_on_a_synthetic_capture_prints_the_documented_lines_in_order`, `test_replay_output_without_the_flag_equals_the_diff_output_minus_the_diff_lines` (FV, EP), `test_replay_diff_leader_lines_are_only_country_landsdel_and_storkreds`, `test_replay_diff_of_a_recorded_capture_agrees_with_the_plain_replay`, `test_poll_diff_*` (7), `test_diff_misuse_exits_2_with_usage_on_err`, `test_replay_diff_of_a_capture_mixing_two_elections_exits_1_with_an_error`, `test_poll_diff_an_election_that_changes_type_mid_run_exits_1_with_an_error` | pass |
| T9 (existing tests unchanged, FV imports and messages) | the whole existing suite, 1301 tests, passes unchanged; `git diff main -U0 -- tests` removes only the two A9 retargets and import lines; `test_dst_feed.py::test_parse_overview_for_equals_the_folketingsvalg_adapter`, `test_adapter_modules_re_export_the_very_same_objects` | pass |
| T10 (`election_name`, `parse_overview_for`, re-exports, package names) | `test_dst_feed.py` (38 tests); `test_package.py`: `test_dkvalg_re_exports_the_diff_api_from_its_module` (7), `test_dkvalg_keeps_the_registry_and_adapter_helpers_out_of_the_top_level` (4), `test_election_type_exposes_the_ep_member_at_the_top_level` | pass |

Suite: `1596 passed` (1301 existing + 295 new: 44 `test_europaparlamentsvalg`, 41 `test_registry`, 38 `test_dst_feed`, 87 `test_diff`, 85 added across `test_model`, `test_directory`, `test_http_source`, `test_capture`, `test_fixtures`, `test_package`, `test_cli`). `ruff check .`, `ruff format --check .` and `mypy` clean.

Production fixes this step (each found by weighing the two designers' reports and run against the code):

- `Place.leader` (model.py): a party needs more than 0 votes to lead; a counted place where nobody has votes has no leader (C2). Reason: the first party of an all-zero place was reported as leader and would have produced a spurious `LeaderChanged` once real votes arrived. Docstring, `STRUCTURE.md`, README updated; tests `test_place_leader_is_none_when_nobody_has_votes_to_lead_with`, `test_an_all_zero_votes_place_has_no_leader_and_then_a_first_leader`.
- `cli._diff_lines` (cli.py): `diff_elections`' `ValueError` for two different elections is now raised as `FeedError`, so `replay --diff` and `poll --diff` print `error: <message>` and exit 1 instead of a traceback (C5). Tests `test_replay_diff_of_a_capture_mixing_two_elections_exits_1_with_an_error`, `test_poll_diff_an_election_that_changes_type_mid_run_exits_1_with_an_error`. `STRUCTURE.md` `run` row updated; no signature changed.
- `diff_elections` docstring and README document C1, C3 and C4 (below). No signature changed, so section 2's Public API table needs no edit.

Pinned behaviours (documented, not changed):

- C1: a place first counted with seats in the same snapshot gives `PlaceCounted` + `LeaderChanged` and no `PartyResultChanged` (`test_a_first_count_with_seats_gives_place_counted_and_leader_but_no_party_change`, `test_replay_diff_on_the_fixtures_prints_no_seats_or_status_lines`); an already-counted place whose seats go `None` to a figure prints `seats <type> <name>: <letter> - -> <n>` (`test_seats_arriving_after_the_count_are_a_party_result_change`, the synthetic capture test). DST computes seats after the first count, so live use reaches the none-to-figure path.
- C3: duplicate `party_id` in one place, last wins, a spurious change for the first duplicate (`test_duplicate_party_ids_in_one_place_are_a_documented_limitation`).
- C4: a lost leader (leader to none, or all votes gone) is never a `LeaderChanged` (`test_a_place_that_loses_its_leader_is_only_a_status_change`, `test_a_place_whose_votes_all_vanish_loses_its_leader_without_leader_changed`).
- C6: `startswith` matching accepts `Folketingsvalgxyz` and a bare prefix, as round 1 did (`test_parse_any_overview_accepts_names_that_start_with_a_supported_prefix`).
- `ProgressChanged` when the two totals differ (`test_progress_is_reported_when_the_totals_differ_between_snapshots`, `test_a_place_only_in_current_*`); poll prints aware UTC times and replay naive local time (`test_poll_uses_aware_utc_times_while_replay_prints_naive_local_time`); a tie reordered in the feed flips the leader (`test_reordering_a_tie_in_the_feed_flips_the_leader_pinned`).

Edge cases considered and deliberately skipped:

- Importing each module alone in a subprocess for import cycles (contract designer, item 10): the existing suite already imports every module and `python -m dkvalg.<module>` ran for all of them in step 4; a subprocess per module adds seconds for a risk already covered.
- A 100,000-character `ValgNavn` was tested only for "FeedError, no crash"; truncating the message is a style choice outside section 1.
- Wrong argument types to `diff_elections`, numeric overflow or float precision: the signatures are typed, `diff_elections` does arithmetic only as `int` subtraction, and percent comparison is exact equality of parsed figures (a deliberate choice, since DST rounds).
- Negative votes beyond `Place.leader` never leading: DST never emits them.
- A `load_election` of an EP directory using Folketingsvalg feed names (low priority in the input-space report): both types use the same file names, so it is the same code path.

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
