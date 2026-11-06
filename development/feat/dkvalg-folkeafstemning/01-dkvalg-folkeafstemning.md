# dkvalg: Folkeafstemning (referendum) adapter

<!-- claude-plan step=9 status=done -->

| Field | Value |
|---|---|
| Feature | `feat/dkvalg-folkeafstemning` (the folder) |
| Round | 1 |
| Branch | `feat/dkvalg-folkeafstemning` |
| Version | `minor` — a third election type through the same machinery, no new model type; step 9 adds `1.2.0 → 1.3.0` (patch would undersell a new election type) |
| Started | 2026-11-06 |

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
| 8 | Recommend | `/recommend` | with the user | done |
| 9 | Pull request | `/create-pr` | with the user | done |
| 10 | Review | `/watch-pr` | on the pull request | pending |

Statuses: `pending`, `in progress`, `done`.

## Builds on

Nothing on this branch: this is its first round. It builds on what `main` holds from `development/feat/dkvalg-folketingsvalg-replay/` (PR #2), `development/feat/dkvalg-live-polling/` (PR #3) and `development/feat/dkvalg-diff-and-ep/` (PR #4), version 1.2.0: the model, `adapters/dst_feed.py` with the Folketingsvalg and Europa-Parlamentsvalg adapters and the registry, `load_election`/`build_election`, `HttpSource`, `poll`, `Recorder`, `ReplaySource`, `CaptureReplay`, `diff_elections` and the CLI. This round must not break them, except the tests named in A7.

---

## 1. Concept

### What this is

`dkvalg` reads Danish referenda (**Folkeafstemning**) as well as Folketingsvalg and Europa-Parlamentsvalg elections. `ElectionType` gets a referendum member, the election type is recognised from the overview's `ValgNavn` (DST writes `Folkeafstemning ...`), and everything that handles the other two types handles referenda: `load_election`, `HttpSource`, `poll`, `Recorder`, `ReplaySource`, `CaptureReplay`, `diff_elections` and the CLI (`replay`, `poll`, `--diff`). It is general-purpose: any referendum DST publishes in this format, not one election.

Inspection of the four referenda DST publishes (2009, 2014, 2015 and 2022, checked 2026-11-06) settles the design. **Referenda are encoded exactly like party elections.** The two answers are `Parti` entries (DST's `generel.xml` lists them as "opstillede partier": id 434284 letter `JA` and id 434285 letter `NEJ`), with `StemmerAntal` and `StemmerPct`, in the same result feeds, with the same eligible voters, turnout, valid, blank and invalid votes, the same status codes, and the same place hierarchy: hele landet, the preliminary "optalling" tally, 3 landsdele, 10 storkredse and the opstillingskredse (92 in 2014, 2015 and 2022, **94 in 2009**, where two of the 94 are Grønland and Færøerne, whose overview entries name a storkreds id that no storkreds has). There are no seat attributes, and no "Uden for partier". The existing parser already reads all four sets unchanged apart from the name check.

So the model is **reused, not extended**: the answers are carried as the place's `PartyResult` entries (letter `JA` or `NEJ`), seat fields are `None`, `Place.leader` is the winning answer, and `diff_elections` reports a flip of the winning answer as a `LeaderChanged` and moves in the share as `PartyResultChanged`. As in round 3, a thin adapter per election type sits on `adapters/dst_feed.py` and the registry picks it.

### Why it is worth building

Referenda are the third kind of election DST publishes in this feed format, and the spec asked for them from the start. Because the format is the same, supporting them is cheap and exercises the "one model, adapter per type" design a third time; the next referendum (a Danish referendum on an EU or constitutional question can be called at short notice) then needs no new code. The four real sets also give the first test data with an answer other than the expected one (2015: NEJ won).

### Inputs and outputs

The same inputs as today (a directory, an election id or URL, a capture directory) producing `Election`s whose type says referendum. In the replay and poll tables the rows are the answers (letter `JA` or `NEJ`, the name, percent, votes, `-` for seats). The model gets no new type; the docs say plainly that for a referendum the entries of `Place.parties` are the answers.

### How it connects to the rest of the repo

Reuses `adapters/dst_feed.py` (shared parsing), `adapters/registry.py` (adapter choice), the model, `build_election`/`load_election`, `HttpSource`, `poll`, the recorder and capture replay, `ReplaySource`, `diff_elections` and the CLI. New: a thin adapter module and a referendum `ElectionType` member; the registry's refusal message lists a third supported type. Nothing else changes in behaviour.

### Explicitly out of scope

- AppDaemon / Home Assistant: nothing, now or in this repo.
- Kommunal- and regionsvalg (DST publishes no feed), fintaelling feeds, personal votes, afstemningsomraader, finding the current election id.
- Computing anything DST does not publish (a referendum has no seats; "approval thresholds" such as the 30 % rule for constitutional referenda are not computed).
- A dedicated answer type or renaming `PartyResult`/`is_party` (noted in `DEVELOPMENT.md`; the model is documented as carrying answers for referenda).
- Committing the 2014 referendum's feeds: it has the same shape as 2015 and 2022 and was checked in the survey; three full sets prove the generality.

Assumptions (stated, not asked): the referendum is recognised by the `ValgNavn` prefix `Folkeafstemning` (case-sensitive, like the other two, and DST writes a double space after some weekdays, as for EP: 2022 and 2009 have one, 2015 has none); the answers are whichever `Parti` entries a feed lists, so a future referendum with more than two options would still parse; the "leader" of a place is the answer with the most votes under the existing rule (ties to the earlier entry, nobody leads on zero votes); the number of opstillingskredse comes from the overview (94 in 2009), never from a constant; the fixtures are the real 2022, 2015 and 2009 sets (unmodified, 109 XML files for 2022 and 2015 and 111 for 2009, no `fintal.xml`).

### Acceptance criteria

| # | The finished feature... |
|---|---|
| A1 | ships complete real fixture sets for the referenda of 1 June 2022, 3 December 2015 and 7 June 2009 (`tests/fixtures/folkeafstemning_2022`, `_2015`, `_2009`: `generel.xml`, `valgdag.xml` and every result feed, unmodified: 109 XML files for 2022 and 2015 and 111 for 2009, whose overview lists 109 result feeds, with a README naming the source URLs and retrieval date and a SHA-256 manifest), and `load_election` on each returns a referendum election with the right figures: 2022 has 107 places (1 country, 1 tally, 3 landsdele, 10 storkredse, 92 opstillingskredse), 92 of 92 counted, 4,260,944 eligible voters, turnout 65.76 %, JA 1,848,738 votes (66.9 %), NEJ 914,829 (33.1 %), 32,807 blank; 2015 has JA 1,377,538 and NEJ 1,556,582 (53.1 %); 2009 has 109 places with **94** opstillingskredse, 94 of 94 counted, JA 1,858,008 (85.3 %) and 4,114,395 eligible voters; every seat field is `None`. |
| A2 | carries the answers in the existing model with no new type, so that `Place.leader` is the winning answer (JA in 2022 and 2009, NEJ in 2015, at the national place), `is_party` is true for both answers, there is no "Uden for partier", and the counted-of-total progress uses the number of opstillingskredse the overview lists (94 in 2009). |
| A3 | chooses the adapter from `ValgNavn`: a Folkeafstemning overview parses into the referendum type with its own thin adapter, the Folketingsvalg and Europa-Parlamentsvalg adapters on their own still refuse it and the referendum adapter refuses them, and any other name (for example `Kommunalvalg`) is refused with a `FeedError` naming the value and all three supported types. |
| A4 | works for referenda across the stack: a first `HttpSource` fetch through a fake transport serving a referendum set equals `load_election` of it; a recorded poll replays through `CaptureReplay` ending equal to the last fetch; `ReplaySource` replays it; `python -m dkvalg replay tests/fixtures/folkeafstemning_2022 --speed inf` prints 107 place lines ending at 92/92 and a national table whose rows are `JA` and `NEJ` with `-` seats, exit 0; the 2009 set ends at 94/94; and `poll` on a fake transport serving a referendum prints its lines. |
| A5 | handles the referendum feed quirks the other types handle: the double space in `ValgNavn` (2022 and 2009; 2015 has a single space), a UTF-8 BOM, a status 0 feed in DST's own example shape (`FA-valgdagStatus0`: no `Stemmer`, "Resultatet foreligger endnu ikke."), a status 1 feed with only the two answers (`FA-valgdagStatus1`), a never-reported feed, an answer without an `Id` refused as before, and DOCTYPE or entity declarations refused with a `FeedError` naming the file. |
| A6 | makes `diff_elections` and `--diff` correct for referenda: diffing a snapshot where JA leads against one where NEJ leads gives a `LeaderChanged` from JA to NEJ, moves in votes or percent give a `PartyResultChanged` with `seats_delta` `None`, a place newly counted gives `PlaceCounted` with the answer that leads it; diffing every consecutive `ReplaySource` snapshot of each of the three sets gives one `PlaceCounted` per reported place (109 places in 2009 minus the unreported: all reported, so 109, and 107 in 2015 and 2022) and ends with the national leader JA, NEJ and JA respectively; and `--diff` prints leader lines at country, landsdel and storkreds with the letters `JA` and `NEJ`. |
| A7 | leaves the earlier rounds untouched: every existing test passes unchanged except those that asserted a Folkeafstemning overview is refused, which are retargeted to a `Kommunalvalg` overview (still unsupported): the `_ep_directory` helper and its case in the bad-directory replay test in `test_cli.py`, `test_load_election_an_ep_overview_is_refused` in `test_directory.py`, the unsupported-election case in `test_http_source.py`, the `"Folkeafstemning 2022"` row of the refused names in `test_registry.py`, and the registry showcase's example; and the two tests that pin `ElectionType`'s exact members (`test_election_type_has_exactly_the_folketingsvalg_and_ep_members` in `test_model.py` and `test_election_type_exposes_the_ep_member_at_the_top_level` in `test_package.py`), which gain `FOLKEAFSTEMNING`; `test_folketingsvalg.py`'s check that the Folketingsvalg adapter alone refuses `Folkeafstemning` stays as it is. |

### Open questions

None.

Corrections made in step 2 (2026-11-06), after the plan-critic checked section 1 against the data and the tests; none changes what the round delivers: (1) the 2009 set is 111 XML files (109 result feeds), not 109; (2) two of 2009's 94 opstillingskredse are Grønland and Færøerne with a dangling parent id, kept as served; (3) only 2022 and 2009 have the double space in `ValgNavn`; (4) A7's list of retargeted tests gains the two `ElectionType` member-set tests and loses the DOCTYPE stub case in `test_registry.py`, which asserts a refusal that still fires.

---

## 2. Plan

> Written in step 2, accepted before step 3 starts — by the user, or by a clean critique
> (see `/plan`). Concrete enough that step 3 is transcription, not invention.

### Approach

**Reuse everything, add one thin adapter.** The survey (four real referenda, plus DST's own `FA-valgdagStatus0/1` examples) shows the shared parser in `adapters/dst_feed.py` already reads referendum feeds unchanged, so the work is the same shape as round 3's EP adapter and smaller: a `FOLKEAFSTEMNING` member of `ElectionType`, a thin `adapters/folkeafstemning.py` (its `parse_overview` is `parse_overview_for(xml, ElectionType.FOLKEAFSTEMNING, "Folkeafstemning")`, plus the same re-exports), and one more entry in the registry, whose refusal message then lists three supported types. `build_election`, `HttpSource`, `CaptureReplay`, `ReplaySource`, `diff_elections` and the CLI already go through the registry or the model and need no change, except one real catch found in the survey: the CLI's national table pads the answer letter to 3 characters, so `NEJ` (3 letters) would run into its name (`NEJNEJ ...`). The table now uses a letter column of `max(3, longest printed letter + 1)`, which leaves every party-election table byte-for-byte as it was (their letters are one character) and gives referenda `JA ` and `NEJ ` columns.

Rejected: (a) a dedicated `Answer` type or renaming `PartyResult`: DST's own feeds model answers as `Parti` entries, and diff, `Place.leader`, the recorder, the replays and the tables would all need parallel code for no gain (noted in `DEVELOPMENT.md`); (b) one generic adapter accepting any `ValgNavn`: it would accept a kommunalvalg and break A3's refusal, and loses the registry's explicit list of supported types; (c) shipping all four referenda fixtures: 2014 has the same shape as 2015 and 2022 and adds 0.5 MB, so three sets (the latest, a NEJ result, and the older 94-district structure) prove the generality.

Survey: nothing in `src/` hard-codes 92 districts (the progress total comes from the overview), `PartyResult.is_party` is true for any non-empty `Id`, `Place.leader` and the diff rules apply to answers as they stand, and `cli._print_table` is the only place formatting depends on letter width. The tests that assert a Folkeafstemning overview is refused are, by grep: `tests/test_cli.py` (the `_ep_directory` helper, which still builds a `Folkeafstemning 2022` overview, and its case `(_ep_directory, "Folkeafstemning")` in the bad-directory replay test), `tests/test_directory.py::test_load_election_an_ep_overview_is_refused`, `tests/test_http_source.py` (the case turning the overview into an unsupported election, `Folkeafstemning`), and `tests/test_registry.py` (the refused-names row `"Folkeafstemning 2022"`; the DOCTYPE stub case at line 136 still passes and stays); two further tests pin `ElectionType`'s exact members and gain the new one (`test_model.py::test_election_type_has_exactly_the_folketingsvalg_and_ep_members`, `test_package.py::test_election_type_exposes_the_ep_member_at_the_top_level`); `tests/test_folketingsvalg.py` parametrises `"Folkeafstemning"` against the Folketingsvalg adapter alone, which stays correct. The registry's showcase also uses `Folkeafstemning 2022` as its refused example.

### Modules

| Path | New or changed | Purpose |
|---|---|---|
| `src/dkvalg/model.py` | changed | `ElectionType.FOLKEAFSTEMNING`; docstrings say that for a referendum `Place.parties` holds the answers (A2) |
| `src/dkvalg/adapters/folkeafstemning.py` | new | Thin adapter: `parse_overview` for Folkeafstemning plus the shared re-exports (A3) |
| `src/dkvalg/adapters/dst_feed.py` | changed | Docstring and showcase comments name the third adapter and member (A3) |
| `src/dkvalg/adapters/registry.py` | changed | The third prefix; the refusal message lists three types; the showcase's refused example becomes `Kommunalvalg` (A3, A7) |
| `src/dkvalg/cli.py` | changed | Letter column width in the national table (A4); no other change |
| `src/dkvalg/diff.py` | changed | Docstrings only: a party may be a referendum answer (A6) |
| `tests/fixtures/folkeafstemning_2022/`, `_2015/`, `_2009/` | new | Three complete real sets, 109 unmodified XML files each, `README.md`, `SHA256SUMS` (A1) |
| `tests/test_folkeafstemning.py` | new | The referendum adapter and the referendum through the stack (step 5) |
| `tests/conftest.py` | changed | Fixture paths and election fixtures for the three sets, a transport for them (step 5) |
| `tests/test_registry.py`, `test_directory.py`, `test_http_source.py`, `test_cli.py` | changed | The retargeted tests named in A7, plus new cases |
| `tests/test_model.py`, `test_diff.py`, `test_capture.py`, `test_fixtures.py`, `test_package.py`, `test_dst_feed.py` | changed | New cases only |
| `README.md`, `STRUCTURE.md`, `DEVELOPMENT.md` | changed | Referenda in usage and structure; the answers-as-parties note is already added |
| `pyproject.toml` | untouched | Step 9 writes the version |

### Public API

Existing signatures not listed here do not change. `parse_any_overview` keeps its signature; only its refusal message gains a third type.

| Signature | Module | Purpose | Covers |
|---|---|---|---|
| `ElectionType.FOLKEAFSTEMNING = "folkeafstemning"` | `model` | The referendum member of the `StrEnum` | A1, A3 |
| `parse_overview(xml: bytes) -> Overview` | `adapters.folkeafstemning` | `parse_overview_for(xml, ElectionType.FOLKEAFSTEMNING, "Folkeafstemning")`; `FeedError` when malformed, not a Folkeafstemning, or listing no feeds | A1, A3 |
| `FeedRef`, `Overview`, `parse_place`, `unreported_place` (re-exported through `__all__`) | `adapters.folkeafstemning` | The same shared objects as in `dst_feed` | A3 |
| `main() -> None` | `adapters.folkeafstemning` | Showcase (reads `tests/fixtures/folkeafstemning_2022` by a repo-relative path) | A1 |

Behaviour the signatures do not carry:

- **Registry.** `_PREFIXES` gains `"Folkeafstemning"`; the message is `valgdag.xml: not a supported election (Folketingsvalg, Europa-Parlamentsvalg, Folkeafstemning), ValgNavn is '<name>'`. Matching stays `startswith`, case-sensitive; the double space after the weekday is part of the name and is matched by the prefix alone.
- **Answers.** Entries of `Place.parties` are the answers, in feed order (`JA` then `NEJ`); `PartyResult.letter` is `JA` or `NEJ`, `party_id` is DST's id (434284, 434285), `seats` are `None`. `Place.leader` is the answer with the most votes. Nothing else in the model changes.
- **CLI table.** The letter column is `max(3, longest letter in the printed rows + 1)` characters wide, so one-letter party tables are unchanged and `JA`/`NEJ` tables read `JA  <name> ...` / `NEJ <name> ...`. The `--diff` lines already print the letter after `->` without padding.
- **Fixtures.** `tests/fixtures/folkeafstemning_2022` (Valg1962294), `_2015` (Valg1664255) and `_2009` (Valg1191213), each downloaded from `https://www.dst.dk/valg/<id>/xml/` (`generel.xml`, `valgdag.xml` and every `filnavn` of the overview; no `fintal.xml`), kept unmodified with their BOM, with a README (source URLs, retrieval date, what the set is) and a `SHA256SUMS`. If the network refuses, fall back to the identical sets the planner downloaded on 2026-11-06 into `/tmp/claude-0/-home-user-valg-data/d285c151-1f0b-5ebe-b617-d9e05602daaa/scratchpad/fa2022/`, `fa2015/` and `fa2009/` (check each holds `generel.xml`, `valgdag.xml` and exactly the overview's `filnavn` files; 2009 lists 94 opstillingskredse and 109 result feeds, so 111 XML files, among them `valgdag_999.xml`, `valgdag_841466.xml` and `valgdag_841467.xml`); halt only if both are unavailable.

### Implementation guide

1. `model.py`: the member and the docstrings; update the two `ElectionType` member-set tests (they must gain `FOLKEAFSTEMNING`). Run the whole existing suite: green.
2. `adapters/folkeafstemning.py` and the registry entry; update the showcase's refused example; retarget the tests named in A7 to a `Kommunalvalg` overview (the only existing tests edited); run the suite green.
3. Fixtures: the three sets, `SHA256SUMS` and `README.md` each; confirm `load_election` on each (a quick probe) before going on.
4. `cli._print_table` letter width; confirm the existing CLI tests and the plain replay output of both party fixtures are unchanged.
5. `diff.py` docstrings; README (referenda in the usage and structure), `STRUCTURE.md`, the new showcase.

### Test intents

| # | Must prove | Covers |
|---|---|---|
| T1 | Each of the three fixture directories holds the 109 XML files plus README and `SHA256SUMS`, every hash verifies with the BOM intact and the README names `https://www.dst.dk/valg/<id>/xml/` and the retrieval date; `load_election` of each gives the referendum type and the figures in A1 (2022: 107 places by type 1/1/3/10/92, 92/92, 4,260,944 eligible, 65.76 %, JA 1,848,738 at 66.9 %, NEJ 914,829 at 33.1 %, 32,807 blank; 2015: NEJ 1,556,582 at 53.1 %; 2009: 94 opstillingskredse, 94/94, JA 1,858,008 at 85.3 %, 4,114,395 eligible), all seat fields `None`; the 2009 set holds 111 XML files; its two oddities are pinned as served: `get(OPSTILLINGSKREDS, "841466")` (Grønland) and `"841467"` (Færøerne) have the parent ids `"841466"` and `"841467"`, which are no storkreds, and the other 92 opstillingskreds parents are storkreds ids; the 2009 feeds carry no `SenestRettetIso` and parse from the `dd-mm-yyyy` form alone, with `last_changed` set on every place; the place names come from the overview (the 2009 country feed's own name differs) | A1 |
| T2 | `Place.leader` at the national place is JA (2022, 2009) and NEJ (2015); both answers are `is_party`; there is no "Uden for partier"; the 2009 progress total is 94 | A2 |
| T3 | The registry gives the referendum type for each overview; the referendum adapter refuses Folketingsvalg and EP overviews and the other two adapters refuse a Folkeafstemning one; `Kommunalvalg`, lower-case `folkeafstemning` and `x Folkeafstemning` are refused with the name and all three supported types in the message; the double-space name is accepted; the registry showcase runs | A3 |
| T4 | A referendum through the stack: `HttpSource` first fetch through a fake transport equals `load_election` (2022 and 2009), a second fetch is unchanged; a recorded poll replays through `CaptureReplay` ending equal to the last fetch; `ReplaySource` ends equal; the CLI `replay` on 2022 prints 107 place lines ending 92/92 and a table with rows `JA` and `NEJ`, `-` seats, `NEJ` separated from its name, and on 2009 ends at 94/94; `poll` on a fake transport prints its lines; the table rows are pinned exactly instead of against old output: for 2026 the `A  A. Socialdemokratiet` row and the `-  Uden for partier` row, for EP one row, built with `f"{letter:<3}{name:<48}{percent:>6.1f}%{votes:>11}{seats:>6}"`; for 2022 `f"{'JA':<4}{'JA':<48}{66.9:>6.1f}%{1848738:>11}{'-':>6}"` and the NEJ equivalent; tests that mutate a served set (`touch`, `retime_only`, `never_reported`, the record-then-replay round trip) run on 2022 or 2015, because `retime_overview` needs `SenestRettetIso`, which the 2009 and 2014 feeds do not have; 2009 is used for first-fetch equality, `ReplaySource`, the CLI 94/94 and the diff counts | A4 |
| T5 | Quirks under a Folkeafstemning name (the name constants in `conftest.py` are copied verbatim from each `valgdag.xml`: 2022 and 2009 have the double space, 2015 a single space): BOM and BOM-less overviews, the double space, DST's own status 0 example shape (synthetic: `Status Kode="0"`, no `Stemmer`) and a status 1 feed with only the two answers, a never-reported feed, an answer without `Id` refused naming the feed, a DOCTYPE or entity in the overview and in a result feed refused naming the file | A5 |
| T6 | `diff_elections` on referenda: a JA lead against a NEJ lead gives `LeaderChanged(JA to NEJ)`; vote or percent moves give `PartyResultChanged` with `seats_delta` `None`; a newly counted place gives `PlaceCounted` and a first `LeaderChanged` with the leading answer; consecutive `ReplaySource` snapshots of each set give one `PlaceCounted` per reported place (109, 107, 107) and end with the national leader JA, NEJ, JA; `--diff` on `replay` of 2015 prints leader lines at country, landsdel and storkreds with letters `JA` and `NEJ` | A6 |
| T7 | Every existing test passes unchanged except the retargeted ones (the helper and case in `test_cli.py`, the test in `test_directory.py`, the case in `test_http_source.py`, the `"Folkeafstemning 2022"` row in `test_registry.py`), which now use `Kommunalvalg`, and the two `ElectionType` member-set tests, which gain `FOLKEAFSTEMNING`; `git diff main -U0 -- tests` removes only those lines; `test_folketingsvalg.py` is untouched | A7 |

### Risks

- **A future referendum could differ from the four checked.** The adapter takes whatever `Parti` entries a feed lists, so more than two options still parse; a structural change would be an adapter bug to fix in `dst_feed`, and if it needs a model change beyond the member, **halt**.
- **The 2009 hierarchy.** Two of its 94 opstillingskredse (Grønland, Færøerne) name a storkreds id that no storkreds has. Parent ids are kept as served; the build must **not** normalise or drop them, and must not "fix" the parser to demand a parent; round 3's EP test that checks parents against storkreds ids is not copied for 2009. If something downstream breaks on the dangling parent (nothing uses parents today), **halt**.
- **2009 and 2014 have no `SenestRettetIso`.** The parser already falls back to `SenestRettet`; the conftest mutation helpers do not, so they are not used on 2009 (see T4); extending `retime_overview` is not part of this round.
- **Retargeting tests.** If the build finds an existing test, beyond the ones named, that asserts a Folkeafstemning overview is refused and cannot pass, it is the same class and is retargeted to `Kommunalvalg` and recorded; if one asserts something else about referenda that is genuinely undecided, **halt**.
- **Table width.** The one place output formatting changes; the guard is the existing CLI tests and the byte-identical party tables in T4. If the width rule disturbs an existing table, fix the rule, not the test.
- **Fixture size.** About 1.4 MB for three sets; accepted.
- **"Party" naming.** `PartyResult` and `is_party` read oddly for answers; documented and noted in `DEVELOPMENT.md`, a deliberate non-change.

### Critique

Plan-critic findings (verdict: back to step 1 for two factual corrections to section 1; everything else accepted), 2026-11-06. The critic verified every A1 and A6 figure and the table-width rule against the data.

1. **Two `ElectionType` member-set tests are not in A7's list.** Applied: A7, T7 and guide step 1 now include them (they gain `FOLKEAFSTEMNING`); recorded as a section 1 correction.
2. **2009 is 111 XML files, not 109.** Applied: A1, the assumptions, T1 and the fixture fallback say 109 for 2022 and 2015 and 111 for 2009; recorded as a section 1 correction.
3. **2009's Grønland and Færøerne have a dangling parent id.** Applied: kept as served, pinned in T1, a Risk says not to normalise it; section 1 mentions it.
4. **2009 (and 2014) have no `SenestRettetIso`, which breaks the conftest mutation helpers.** Applied: mutation tests run on 2022 or 2015, 2009 is used for the rest, T1 pins the `dd-mm-yyyy` parse, and a Risk records it.
5. **"Byte-identical to before" cannot be tested.** Applied: T4 pins exact rows built from the format string instead.
6. **Not every referendum name has the double space.** Applied: 2015 has a single space; the name constants are copied verbatim, and A5 and the assumptions say which sets have the quirk.
7. **`dst_feed.py` missing from the Modules table.** Applied: row added.
8. **The DOCTYPE stub case in `test_registry.py` needs no retargeting.** Applied: dropped from A7 and the survey; it stays as a stronger test.

The verdict was "back to step 1" because findings 1 and 2 correct section 1 (a file count and a test list); the user confirmed those corrections and the plan.

Accepted: by the user, 2026-11-06

---

## 3. Implementation notes

> Written in step 3. Only deviations from the plan above, each with its reason. "Built as
> planned" is a complete and good entry. On a fix round, also the reproduction test's red
> run, pasted here before the fix was written — step 6 cites it.

Built as planned, with these small notes (none touches section 1):

- Fixtures were downloaded fresh from DST on 2026-11-06 (the network was available) and are
  byte-identical to the planner's copies; retrieval date 2026-11-06.
- The `"Folkeafstemning 2022"` row of the refused names in `test_registry.py` was deleted
  rather than retargeted: the list already holds `"Kommunalvalg 2025"`, so a retargeted row
  would duplicate it. The two ElectionType member-set tests keep their names.
- `cli._print_table` computes the letter width per national place from its printed rows;
  party-election output is byte-identical to before (checked for 2026 and EP 2024).
- The registry showcase gained a Folkeafstemning name (the real 2022 one) next to the
  `Kommunalvalg 2025` refused example.

---

## 4. Verification log

> Written in step 4: the static half. Command output, not a summary of it.

| Check | Result |
|---|---|
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `76 files already formatted` |
| `mypy` | `Success: no issues found in 40 source files` |
| `pytest` | `1595 passed in 20.88s` |
| Plan completeness | every Public API row exists as written: `ElectionType.FOLKEAFSTEMNING == "folkeafstemning"` (third member); `folkeafstemning.parse_overview(xml: bytes) -> Overview`; `__all__` = FeedRef, Overview, main, parse_overview, parse_place, unreported_place (same list as the EP adapter); the four shared names are the same objects as in `dst_feed`; registry refusal message lists Folketingsvalg, Europa-Parlamentsvalg, Folkeafstemning. No unplanned public names (module-level extras are only imports) |
| `STRUCTURE.md` | in sync (auditor: no drift); applied nit 1 ("EP, referenda"); skipped nit 2 (duplicates the ElectionType row and the answers note); README replay example for `folkeafstemning_2022` added (nit 3) |
| `python -m dkvalg.<module>` | errors, model, diff, adapters.dst_feed, adapters.folketingsvalg, adapters.europaparlamentsvalg, adapters.folkeafstemning, adapters.registry, sources.directory, sources.http_source, sources.capture, sources.replay: all exit 0 with output (only the expected runpy RuntimeWarning); folkeafstemning prints `Folkeafstemning onsdag  1. juni 2022 (2022-06-01): 107 feeds`, `JA: 1848738 votes (66.9 %)`, `NEJ: 914829 votes (33.1 %)`; registry prints three accepted types and `refused: ... (Folketingsvalg, Europa-Parlamentsvalg, Folkeafstemning), ValgNavn is 'Kommunalvalg 2025'` |
| `python -m dkvalg` / `replay ... --speed inf` | help exit 0; folketingsvalg_2026 122 lines, ep_2024 120, folkeafstemning_2022 111 (ends `92/92`, rows `JA  JA ... 66.9% 1848738 -`, `NEJ NEJ ... 33.1% 914829 -`), 2015 111, 2009 113 (ends `94/94`); all exit 0, empty stderr; 2015 with `--diff` exit 0, 216 lines, leader lines such as `storkreds Bornholms Storkreds: - -> NEJ` |
| Party tables unchanged | `replay` of folketingsvalg_2026 and ep_2024 compared with the same command run on `git archive main src`: byte-identical (`cmp`) |
| Fixtures | `sha256sum -c`: 0 failures in each of the three; XML counts 109 / 109 / 111 (2022 / 2015 / 2009) |
| 2009 dangling parents | `get(OPSTILLINGSKREDS, "841466").parent_id == "841466"`, `"841467"` likewise; progress `94/94` |
| `git diff main -U0 -- tests` | removed lines only: test_cli (`Folkeafstemning 2022` in the helper, the `_ep_directory` case), test_directory (name in helper, `match="Folkeafstemning"`), test_http_source (name in the case, `match`), test_registry (the `"Folkeafstemning 2022"` row), plus the one-line changes in test_model and test_package (member sets gain FOLKEAFSTEMNING). Exactly A7's list; the deleted-not-retargeted registry row is sound because `"Kommunalvalg 2025"` already exists in that list |

Section 3 notes judged: none needs a plan correction (the registry row deletion is covered above; the per-place letter width is computed from printed rows and verified byte-identical).

---

## 5. Test log

> Written in step 5: the dynamic half.

Result: `ruff check .`, `ruff format --check .` and `mypy` clean; `pytest` 1824 passed (1595 before this step; the new tests are `tests/test_folkeafstemning.py`, 145 cases, plus additions to the ten other files). The tests found no bug in `src/`: nothing in `src/` changed in this step.

| Intent | Test names (file: group) | Result |
|---|---|---|
| T1 | `test_fixtures.py`: `test_fa_fixture_directory_holds_its_xml_files_a_readme_and_a_manifest`, `test_every_feed_a_fa_overview_lists_is_present_and_nothing_else_but_two_overviews`, `test_every_fa_file_matches_its_sha256_and_keeps_its_bom`, `test_the_fa_readme_names_the_source_and_the_retrieval_date`, `test_no_fa_xml_file_had_its_line_endings_rewritten`, `test_the_2009_set_lists_the_oddly_numbered_feeds_the_plan_names` (109/109/111 files, hashes, BOM, README needles). `test_folkeafstemning.py`: `test_load_election_referendum_is_a_referendum_with_the_real_name_and_date`, `..._has_the_places_by_type_and_counts_all_districts`, `..._national_figures_match_the_files`, `test_referendum_answers_are_parties_with_no_seats_and_no_outside_party_entry`, `test_referendum_2009_dangling_parents_are_kept_as_served`, `test_referendum_2009_feeds_carry_no_iso_timestamp_and_parse_from_the_dst_form`, `test_referendum_2009_place_names_come_from_the_overview_not_the_feed`, `test_referendum_names_keep_or_lack_the_double_space_as_served`, idempotency, a missing feed named, `build_election` equal and in overview order. `test_directory.py`: round 4 group | pass |
| T2 | `test_folkeafstemning.py::test_referendum_national_leader_is_the_winning_answer` (JA, NEJ, JA), the answers test above (both `is_party`, no "Uden for partier"), the progress tests (`94/94`; total from the overview for 94, 92, 1 and 0 districts; 2 of 3 with a never-reported one). `test_model.py`: `test_a_referendum_place_leader_*`, `test_referendum_answers_are_parties_keyed_on_the_id_not_the_letter` | pass |
| T3 | `test_registry.py`: real overviews, accepted names, exact three-type refusal message, registry equal to the adapter. `test_folkeafstemning.py`: the 3 by 3 adapter matrix, name boundaries and whitespace, missing name, bad or missing date, no feeds, BOM, UTF-16, re-exports and `__all__`, `test_the_showcases_run_and_show_the_referendum`. `test_dst_feed.py`: round 4 group. `test_package.py`, `test_model.py`: the member | pass |
| T4 | `test_folkeafstemning.py`: `HttpSource` first fetch equal for 2022 and 2009, unchanged second fetch, touched and retimed feeds, never reported, Kommunalvalg refused with state kept, recorded poll through `CaptureReplay`, `ReplaySource` for 2022 and 2009, the CLI on all three sets with exact rows, `poll`, speed and interval boundaries, the letter-column tests. `test_http_source.py`, `test_capture.py`, `test_cli.py`: round 4 groups (exact 2026 and EP rows, the capture round trip on 2015) | pass |
| T5 | `test_folkeafstemning.py`: status 0 in DST's example shape, status 1 with the two answers, statuses 9, 10, 11 and 12, unknown or missing status code, answers 0 to 3, ties and zero votes, an answer without an `Id` or with an empty one, bad figures, a never-reported feed, DOCTYPE and entity in the overview, a result feed and a directory | pass |
| T6 | `test_diff.py`: flip JA to NEJ with deltas, tie, percent-only move, first count, type mismatch, replay chain for the three sets (109, 107, 107 counted; final leaders JA, NEJ, JA). `test_cli.py`: `--diff` on the three sets, flag-less equality, `poll --diff`, a referendum changing type mid-run | pass |
| T7 | `git diff main -U0 -- tests` removes only the lines of A7's list (and the import lines that gained a name); `test_folketingsvalg.py` is untouched | pass |

Designer cases merged (`contract` C1 to C15, `input-space` I1 to I20), applied or rebutted:

- Applied: C1 (3 by 3 matrix), C2 (exact refusal message, in `test_registry.py`), C3 (prefix matches), C4 (exact rows; see the wrong expectation below), C5 (`--diff` leader levels, no seat lines), C6 (replay chain, the expected count also compared with `has_result`), C7 (flip, tie, first count), C8 (type mismatch `ValueError` and the mid-run CLI error), C9 (record then replay on 2015, repeatable), C10, C11, C12 (in `test_model.py` and `test_folkeafstemning.py`), C13 (re-exports and `__all__`), C14 (purity and a missing feed named), C15 (both showcases). I1 to I5 (letter width per country, boundaries 1 to 5 letters, the longest letter and not the first row, the dash counts as one character, status 0 header only), I6 to I10, I11 (UTF-16 with a matching declaration equal, under a UTF-8 declaration a `FeedError` naming the file), I12, I13 to I15, I16 (progress totals from the overview), I17 (the timestamp fallback; `1-6-2022 21:30` and an offset refused), I18 (a missing storkreds id gives `None`), I19 (speeds `0`, `-1`, `nan` exit 2, `inf` and `1e-300` exit 0), I20 (one interval parametrisation).
- Applied with a note: C4's expectation of a `-  Uden for partier` row with `-` seats is wrong for 2026: DST gives that entry `Mandater="0"`, so the row ends in `0`. The test builds the row from the model (`outside.seats == 0` is asserted) and the EP row keeps `-`. A wrong expectation in the plan's T4 wording and in the designer's case, not a code bug.
- Dropped, with reason: I6's `Folkeafstemning` preceded by a BOM inside the text (a stray character is just another non-matching name, covered by `x Folkeafstemning`); I12 (a hostile `<!ENTITY` variant) duplicates the DOCTYPE-plus-entity injection already used; contradictions 1 and 4 to 5 (cosmetic showcase comment, docstring wording of `is_party`, the `parse_place` docstring) are wording notes with no behaviour to test; contradiction 2 (`Folkeafstemninger` accepted) is pinned in `test_folkeafstemning.py` and `test_registry.py` (`Folkeafstemningxyz`); contradiction 3 (a wide letter shifts all rows rather than truncating) is pinned by the width tests; the `_print_table` docstring says "longest letter", the width is per country: only observable with two countries, which a real feed never has, and pinned in `test_table_width_is_computed_per_country`; the A6 wording for 2009 is garbled in section 1, the tests assert 109 `PlaceCounted` and 94/94 separately (no amendment needed: the counts are right).

Edge cases considered and deliberately skipped, with reasons:

- Mutation tests (touch, retime, never-reported, record-then-replay) on 2009: its feeds have no `SenestRettetIso`, which the conftest helpers need (plan T4); 2022 and 2015 carry them.
- Table rows for `--speed` below a positive float's range other than `1e-300`: covered by the validator's own tests in round 2.
- A referendum with more than two answers through the CLI: the table width is tested with 5-letter letters, and the parser with three answers; a real feed with more is not available.
- Network-level behaviour (redirects, truncation, size caps): round 2's loopback tests, nothing referendum-specific.
- An EP `Uden for partier` row assertion in the new CLI test: the round 3 tests already pin the EP table.

---

## 6. Concept check

> Written in step 6, against section 1 — not against section 2. The question is whether
> the thing built is the thing agreed, not whether it matches the plan.

| # | Criterion | Met | Evidence |
|---|---|---|---|
| A1 | Three complete real fixture sets, `load_election` figures right | yes | `load_election` on each (run in this step): 2022 type `folkeafstemning`, 107 places (COUNTRY 1, TALLY 1, LANDSDEL 3, STORKREDS 10, OPSTILLINGSKREDS 92), 92/92, 4,260,944 eligible, turnout 65.76, blank 32,807, JA 1,848,738 (66.9), NEJ 914,829 (33.1); 2015 JA 1,377,538, NEJ 1,556,582 (53.1); 2009 109 places with 94 opstillingskredse, 94/94, JA 1,858,008 (85.3), 4,114,395 eligible. No `Parti` of any place has a seat figure (checked over every place of every set). `git diff main --stat` shows `tests/fixtures/folkeafstemning_{2022,2015,2009}/` added; the verification log records 109/109/111 XML files and `sha256sum -c` clean; README and SHA256SUMS present |
| A2 | Answers in the existing model, leader, `is_party`, progress | yes | No new model type: `git diff main --stat` has only the `ElectionType` member and docstrings in `model.py`. National `leader.letter`: 2022 JA, 2015 NEJ, 2009 JA; both answers `is_party` True; the national parties are exactly JA and NEJ (no "Uden for partier"); 2009 progress `94/94` from the overview. Tests: `test_referendum_national_leader_is_the_winning_answer`, `test_referendum_answers_are_parties_with_no_seats_and_no_outside_party_entry` |
| A3 | Adapter chosen from `ValgNavn`, refusals | yes | `parse_any_overview` on the 2022 overview gives `folkeafstemning`; `folketingsvalg.parse_overview` and `europaparlamentsvalg.parse_overview` refuse it (`not a Folketingsvalg, ValgNavn is 'Folkeafstemning onsdag  1. juni 2022'`, likewise EP); `folkeafstemning.parse_overview` refuses the 2026 and EP 2024 overviews; a `Kommunalvalg` name gives `valgdag.xml: not a supported election (Folketingsvalg, Europa-Parlamentsvalg, Folkeafstemning), ValgNavn is 'Kommunalvalg onsdag  1. juni 2022'`. Thin adapter `src/dkvalg/adapters/folkeafstemning.py` (77 lines with showcase) |
| A4 | Works across the stack | yes | `python -m dkvalg replay tests/fixtures/folkeafstemning_2022 --speed inf`: exit 0, empty stderr, 111 lines, 107 place lines ending `92/92`, table rows `JA  JA ... 66.9%  1848738  -` and `NEJ NEJ ... 33.1%  914829  -`; 2015 the same shape (NEJ 53.1 %); 2009 ends `94/94` (113 lines). `HttpSource` first fetch equal to `load_election`, `CaptureReplay` ending equal to the last fetch, `ReplaySource`, and `poll` on a fake transport are covered by `tests/test_folkeafstemning.py` (145 cases) and `test_capture.py` / `test_http_source.py` / `test_cli.py` round 4 groups, all in the 1824 passed run of this step. The CLI width fix is the only `src/cli.py` change (13 lines) |
| A5 | Feed quirks | yes | Double space (2022, 2009) and single space (2015) pinned by `test_referendum_names_keep_or_lack_the_double_space_as_served`; BOM, status 0 in DST's shape, status 1 with two answers, never reported, an answer without `Id`, DOCTYPE and entity in overview, result feed and directory: `test_folkeafstemning.py` groups listed in section 5 T5, all green (1824 passed). The hardening is the shared `dst_feed` code, unchanged by this round (`dst_feed.py` diff is docstring and comments, 5 lines) |
| A6 | `diff_elections` and `--diff` correct | yes | Run here: chaining `diff_elections` over every consecutive `ReplaySource` snapshot gives `PlaceCounted` 107 / 107 / 109 and final national leader JA / NEJ / JA for 2022 / 2015 / 2009. `replay tests/fixtures/folkeafstemning_2015 --speed inf --diff` prints e.g. `leader storkreds Bornholms Storkreds: - -> NEJ` and `... Nordsjællands Storkreds: - -> JA`. Flip, percent-only move and seats_delta `None`: `test_diff.py` round 4 group. `diff.py` change is docstrings only (7 lines) |
| A7 | Earlier rounds untouched | yes | `git diff main -U0 -- tests` removals (non-fixture): `test_cli.py` (import line gaining a name, `Folkeafstemning 2022` in the `_ep_directory` helper, the `(_ep_directory, "Folkeafstemning")` case), `test_directory.py` (helper name, `match="Folkeafstemning"`), `test_http_source.py` (case name, `match`), `test_registry.py` (the `"Folkeafstemning 2022"` row, an import line), `test_model.py` / `test_package.py` / `test_diff.py` / `test_dst_feed.py` / `test_fixtures.py` (import lines gaining names, the member-set assertions gaining `FOLKEAFSTEMNING`); `test_folketingsvalg.py` has no diff. This is A7's list plus import-line widening. `pytest`: 1824 passed; `ruff check .` clean; `mypy`: no issues in 41 files. Party tables unchanged: `replay` of folketingsvalg_2026 still prints `A  A. Socialdemokratiet ... 38`; step 4 compared 2026 and EP output byte-for-byte with `main` |

Drift found, and what was done about it:

- **Step 5's test-expectation correction (2026 "Uden for partier" row ends in `0`, not `-`).** Checked and not a conflict: A4 concerns referendum tables (`JA`/`NEJ` rows with `-` seats) and the letter column width; A7 says earlier tests pass unchanged. DST gives that 2026 entry `Mandater="0"`, so the real output is `-  Uden for partier  0.1%  2420  0`, and the new test builds its expectation from the model (`seats == 0`). Neither criterion says anything about that row. No halt.
- **Scope.** No AppDaemon or Home Assistant text in `src/` or the README (grep). `pyproject.toml` untouched, no new dependencies. `src/dkvalg/__init__.py` has no diff: no unplanned public names (the only new public names are `ElectionType.FOLKEAFSTEMNING`, `adapters.folkeafstemning.parse_overview` and `main`). README section "Folkeafstemning (referenda)" says that the entries of `Place.parties` are the answers, names the three fixture sets and the 94-district 2009 oddity; `DEVELOPMENT.md` records the `PartyResult` naming note. Nothing from the out-of-scope list was built (no fintal, no thresholds, no answer type, no 2014 fixtures).
- **STRUCTURE.md.** The auditor found two wording-only stale spots, both fixed: `### tests/test_registry.py` ("the supported types" instead of "both supported types") and `### tests/test_dst_feed.py` ("each adapter re-exports" instead of "both adapters re-export"). Nothing else drifted.
- **Showcase.** `python -m dkvalg.adapters.folkeafstemning` and the registry showcase were run in step 4 and read as worked examples (name, call, `JA: 1848738 votes (66.9 %)`).
- No code was wrong; nothing sent back to step 3.

### Earlier rounds still hold

Not applicable: this is the first round of the branch. Earlier PRs (#2 to #4) are on `main`; their suites pass unchanged except A7's list.

---

## 7. Ship log

| Field | Value |
|---|---|
| Commits | 11 before this one, oldest first: `b521a73` Concept; `f156ec1` Plan draft; `a760eac` Plan: apply plan-critic findings; `4228200` Plan accepted by the user; `7e466ad` WIP step 3 (type, adapter, registry, retargeted tests); `84dac8d` WIP step 3 (three fixture sets); `ef5d931` Implement; `39bce22` Verify; `c130652` WIP step 5; `9be3764` Test; `768f720` Concept check; then `Ship: dkvalg Folkeafstemning (referendum) adapter` (this step). Every step 1 to 6 left a commit. |
| Gates on the whole tree | `ruff check .` clean; `ruff format --check .` 77 files formatted; `mypy` no issues in 41 source files; `pytest` 1824 passed in 21.99s |
| Review | `git diff main...HEAD --name-only`: only the planned files (src: model, dst_feed, registry, cli, diff, new adapter; the tests named in the plan; README, STRUCTURE, DEVELOPMENT; the plan file; 335 fixture files under `tests/fixtures/folkeafstemning_{2022,2015,2009}/`). No scratch paths, debug output, secrets or AppDaemon/HA text; `pyproject.toml` untouched |
| Pushed to | `origin/feat/dkvalg-folkeafstemning` |

---

## 8. Recommendations

> Written in step 8. Only follow-ups that are critical and belong to this work, which most
> rounds do not have: replace the table with `None.` when there are none. Lesser ideas are
> one-line notes in `DEVELOPMENT.md`, not rows here. Not bugs in what this round built —
> those go back through `/build` before the pull request. A critical defect outside what
> section 1 promised, such as a class member it put out of scope, is a recommendation here,
> and its round opens through `/fix`.

None.

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
