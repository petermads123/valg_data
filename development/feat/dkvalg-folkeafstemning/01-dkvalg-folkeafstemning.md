# dkvalg: Folkeafstemning (referendum) adapter

<!-- claude-plan step=2 status=active -->

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

Nothing on this branch: this is its first round. It builds on what `main` holds from `development/feat/dkvalg-folketingsvalg-replay/` (PR #2), `development/feat/dkvalg-live-polling/` (PR #3) and `development/feat/dkvalg-diff-and-ep/` (PR #4), version 1.2.0: the model, `adapters/dst_feed.py` with the Folketingsvalg and Europa-Parlamentsvalg adapters and the registry, `load_election`/`build_election`, `HttpSource`, `poll`, `Recorder`, `ReplaySource`, `CaptureReplay`, `diff_elections` and the CLI. This round must not break them, except the tests named in A7.

---

## 1. Concept

### What this is

`dkvalg` reads Danish referenda (**Folkeafstemning**) as well as Folketingsvalg and Europa-Parlamentsvalg elections. `ElectionType` gets a referendum member, the election type is recognised from the overview's `ValgNavn` (DST writes `Folkeafstemning ...`), and everything that handles the other two types handles referenda: `load_election`, `HttpSource`, `poll`, `Recorder`, `ReplaySource`, `CaptureReplay`, `diff_elections` and the CLI (`replay`, `poll`, `--diff`). It is general-purpose: any referendum DST publishes in this format, not one election.

Inspection of the four referenda DST publishes (2009, 2014, 2015 and 2022, checked 2026-11-06) settles the design. **Referenda are encoded exactly like party elections.** The two answers are `Parti` entries (DST's `generel.xml` lists them as "opstillede partier": id 434284 letter `JA` and id 434285 letter `NEJ`), with `StemmerAntal` and `StemmerPct`, in the same result feeds, with the same eligible voters, turnout, valid, blank and invalid votes, the same status codes, and the same place hierarchy: hele landet, the preliminary "optalling" tally, 3 landsdele, 10 storkredse and the opstillingskredse (92 in 2014, 2015 and 2022, **94 in 2009**). There are no seat attributes, and no "Uden for partier". The existing parser already reads all four sets unchanged apart from the name check.

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

Assumptions (stated, not asked): the referendum is recognised by the `ValgNavn` prefix `Folkeafstemning` (case-sensitive, like the other two, and DST writes a double space after the weekday as for EP); the answers are whichever `Parti` entries a feed lists, so a future referendum with more than two options would still parse; the "leader" of a place is the answer with the most votes under the existing rule (ties to the earlier entry, nobody leads on zero votes); the number of opstillingskredse comes from the overview (94 in 2009), never from a constant; the fixtures are the real 2022, 2015 and 2009 sets (109 unmodified XML files each, no `fintal.xml`).

### Acceptance criteria

| # | The finished feature... |
|---|---|
| A1 | ships complete real fixture sets for the referenda of 1 June 2022, 3 December 2015 and 7 June 2009 (`tests/fixtures/folkeafstemning_2022`, `_2015`, `_2009`: `generel.xml`, `valgdag.xml` and every result feed, 109 unmodified XML files each, with a README naming the source URLs and retrieval date and a SHA-256 manifest), and `load_election` on each returns a referendum election with the right figures: 2022 has 107 places (1 country, 1 tally, 3 landsdele, 10 storkredse, 92 opstillingskredse), 92 of 92 counted, 4,260,944 eligible voters, turnout 65.76 %, JA 1,848,738 votes (66.9 %), NEJ 914,829 (33.1 %), 32,807 blank; 2015 has JA 1,377,538 and NEJ 1,556,582 (53.1 %); 2009 has 109 places with **94** opstillingskredse, 94 of 94 counted, JA 1,858,008 (85.3 %) and 4,114,395 eligible voters; every seat field is `None`. |
| A2 | carries the answers in the existing model with no new type, so that `Place.leader` is the winning answer (JA in 2022 and 2009, NEJ in 2015, at the national place), `is_party` is true for both answers, there is no "Uden for partier", and the counted-of-total progress uses the number of opstillingskredse the overview lists (94 in 2009). |
| A3 | chooses the adapter from `ValgNavn`: a Folkeafstemning overview parses into the referendum type with its own thin adapter, the Folketingsvalg and Europa-Parlamentsvalg adapters on their own still refuse it and the referendum adapter refuses them, and any other name (for example `Kommunalvalg`) is refused with a `FeedError` naming the value and all three supported types. |
| A4 | works for referenda across the stack: a first `HttpSource` fetch through a fake transport serving a referendum set equals `load_election` of it; a recorded poll replays through `CaptureReplay` ending equal to the last fetch; `ReplaySource` replays it; `python -m dkvalg replay tests/fixtures/folkeafstemning_2022 --speed inf` prints 107 place lines ending at 92/92 and a national table whose rows are `JA` and `NEJ` with `-` seats, exit 0; the 2009 set ends at 94/94; and `poll` on a fake transport serving a referendum prints its lines. |
| A5 | handles the referendum feed quirks the other types handle: the double space in `ValgNavn`, a UTF-8 BOM, a status 0 feed in DST's own example shape (`FA-valgdagStatus0`: no `Stemmer`, "Resultatet foreligger endnu ikke."), a status 1 feed with only the two answers (`FA-valgdagStatus1`), a never-reported feed, an answer without an `Id` refused as before, and DOCTYPE or entity declarations refused with a `FeedError` naming the file. |
| A6 | makes `diff_elections` and `--diff` correct for referenda: diffing a snapshot where JA leads against one where NEJ leads gives a `LeaderChanged` from JA to NEJ, moves in votes or percent give a `PartyResultChanged` with `seats_delta` `None`, a place newly counted gives `PlaceCounted` with the answer that leads it; diffing every consecutive `ReplaySource` snapshot of each of the three sets gives one `PlaceCounted` per reported place (109 places in 2009 minus the unreported: all reported, so 109, and 107 in 2015 and 2022) and ends with the national leader JA, NEJ and JA respectively; and `--diff` prints leader lines at country, landsdel and storkreds with the letters `JA` and `NEJ`. |
| A7 | leaves the earlier rounds untouched: every existing test passes unchanged except those that asserted a Folkeafstemning overview is refused, which are retargeted to a `Kommunalvalg` overview (still unsupported): the `_ep_directory` helper and its case in the bad-directory replay test in `test_cli.py`, `test_load_election_an_ep_overview_is_refused` in `test_directory.py`, the unsupported-election case in `test_http_source.py`, the refused-names rows and the stub case in `test_registry.py`, and the registry showcase's example; `test_folketingsvalg.py`'s check that the Folketingsvalg adapter alone refuses `Folkeafstemning` stays as it is. |

### Open questions

None.

---

## 2. Plan

> Written in step 2, accepted before step 3 starts — by the user, or by a clean critique
> (see `/plan`). Concrete enough that step 3 is transcription, not invention.

### Approach

**Reuse everything, add one thin adapter.** The survey (four real referenda, plus DST's own `FA-valgdagStatus0/1` examples) shows the shared parser in `adapters/dst_feed.py` already reads referendum feeds unchanged, so the work is the same shape as round 3's EP adapter and smaller: a `FOLKEAFSTEMNING` member of `ElectionType`, a thin `adapters/folkeafstemning.py` (its `parse_overview` is `parse_overview_for(xml, ElectionType.FOLKEAFSTEMNING, "Folkeafstemning")`, plus the same re-exports), and one more entry in the registry, whose refusal message then lists three supported types. `build_election`, `HttpSource`, `CaptureReplay`, `ReplaySource`, `diff_elections` and the CLI already go through the registry or the model and need no change, except one real catch found in the survey: the CLI's national table pads the answer letter to 3 characters, so `NEJ` (3 letters) would run into its name (`NEJNEJ ...`). The table now uses a letter column of `max(3, longest printed letter + 1)`, which leaves every party-election table byte-for-byte as it was (their letters are one character) and gives referenda `JA ` and `NEJ ` columns.

Rejected: (a) a dedicated `Answer` type or renaming `PartyResult`: DST's own feeds model answers as `Parti` entries, and diff, `Place.leader`, the recorder, the replays and the tables would all need parallel code for no gain (noted in `DEVELOPMENT.md`); (b) one generic adapter accepting any `ValgNavn`: it would accept a kommunalvalg and break A3's refusal, and loses the registry's explicit list of supported types; (c) shipping all four referenda fixtures: 2014 has the same shape as 2015 and 2022 and adds 0.5 MB, so three sets (the latest, a NEJ result, and the older 94-district structure) prove the generality.

Survey: nothing in `src/` hard-codes 92 districts (the progress total comes from the overview), `PartyResult.is_party` is true for any non-empty `Id`, `Place.leader` and the diff rules apply to answers as they stand, and `cli._print_table` is the only place formatting depends on letter width. The tests that assert a Folkeafstemning overview is refused are, by grep: `tests/test_cli.py` (the `_ep_directory` helper, which still builds a `Folkeafstemning 2022` overview, and its case `(_ep_directory, "Folkeafstemning")` in the bad-directory replay test), `tests/test_directory.py::test_load_election_an_ep_overview_is_refused`, `tests/test_http_source.py` (the case turning the overview into an unsupported election, `Folkeafstemning`), and `tests/test_registry.py` (the refused-names row `"Folkeafstemning 2022"` and a stub overview case); `tests/test_folketingsvalg.py` parametrises `"Folkeafstemning"` against the Folketingsvalg adapter alone, which stays correct. The registry's showcase also uses `Folkeafstemning 2022` as its refused example.

### Modules

| Path | New or changed | Purpose |
|---|---|---|
| `src/dkvalg/model.py` | changed | `ElectionType.FOLKEAFSTEMNING`; docstrings say that for a referendum `Place.parties` holds the answers (A2) |
| `src/dkvalg/adapters/folkeafstemning.py` | new | Thin adapter: `parse_overview` for Folkeafstemning plus the shared re-exports (A3) |
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
- **Fixtures.** `tests/fixtures/folkeafstemning_2022` (Valg1962294), `_2015` (Valg1664255) and `_2009` (Valg1191213), each downloaded from `https://www.dst.dk/valg/<id>/xml/` (`generel.xml`, `valgdag.xml` and every `filnavn` of the overview; no `fintal.xml`), kept unmodified with their BOM, with a README (source URLs, retrieval date, what the set is) and a `SHA256SUMS`. If the network refuses, fall back to the identical sets the planner downloaded on 2026-11-06 into `/tmp/claude-0/-home-user-valg-data/d285c151-1f0b-5ebe-b617-d9e05602daaa/scratchpad/fa2022/`, `fa2015/` and `fa2009/` (check each holds `generel.xml`, `valgdag.xml` and exactly the overview's `filnavn` files; 2009 lists 94 opstillingskredse, 109 result feeds in all); halt only if both are unavailable.

### Implementation guide

1. `model.py`: the member and the docstrings. Run the whole existing suite: green.
2. `adapters/folkeafstemning.py` and the registry entry; update the showcase's refused example; retarget the tests named in A7 to a `Kommunalvalg` overview (the only existing tests edited); run the suite green.
3. Fixtures: the three sets, `SHA256SUMS` and `README.md` each; confirm `load_election` on each (a quick probe) before going on.
4. `cli._print_table` letter width; confirm the existing CLI tests and the plain replay output of both party fixtures are unchanged.
5. `diff.py` docstrings; README (referenda in the usage and structure), `STRUCTURE.md`, the new showcase.

### Test intents

| # | Must prove | Covers |
|---|---|---|
| T1 | Each of the three fixture directories holds the 109 XML files plus README and `SHA256SUMS`, every hash verifies with the BOM intact and the README names `https://www.dst.dk/valg/<id>/xml/` and the retrieval date; `load_election` of each gives the referendum type and the figures in A1 (2022: 107 places by type 1/1/3/10/92, 92/92, 4,260,944 eligible, 65.76 %, JA 1,848,738 at 66.9 %, NEJ 914,829 at 33.1 %, 32,807 blank; 2015: NEJ 1,556,582 at 53.1 %; 2009: 94 opstillingskredse, 94/94, JA 1,858,008 at 85.3 %, 4,114,395 eligible), all seat fields `None` | A1 |
| T2 | `Place.leader` at the national place is JA (2022, 2009) and NEJ (2015); both answers are `is_party`; there is no "Uden for partier"; the 2009 progress total is 94 | A2 |
| T3 | The registry gives the referendum type for each overview; the referendum adapter refuses Folketingsvalg and EP overviews and the other two adapters refuse a Folkeafstemning one; `Kommunalvalg`, lower-case `folkeafstemning` and `x Folkeafstemning` are refused with the name and all three supported types in the message; the double-space name is accepted; the registry showcase runs | A3 |
| T4 | A referendum through the stack: `HttpSource` first fetch through a fake transport equals `load_election` (2022 and 2009), a second fetch is unchanged; a recorded poll replays through `CaptureReplay` ending equal to the last fetch; `ReplaySource` ends equal; the CLI `replay` on 2022 prints 107 place lines ending 92/92 and a table with rows `JA` and `NEJ`, `-` seats, `NEJ` separated from its name, and on 2009 ends at 94/94; `poll` on a fake transport prints its lines; the one-letter party tables of both party fixtures are byte-identical to before | A4 |
| T5 | Quirks under a Folkeafstemning name: BOM and BOM-less overviews, the double space, DST's own status 0 example shape (synthetic: `Status Kode="0"`, no `Stemmer`) and a status 1 feed with only the two answers, a never-reported feed, an answer without `Id` refused naming the feed, a DOCTYPE or entity in the overview and in a result feed refused naming the file | A5 |
| T6 | `diff_elections` on referenda: a JA lead against a NEJ lead gives `LeaderChanged(JA to NEJ)`; vote or percent moves give `PartyResultChanged` with `seats_delta` `None`; a newly counted place gives `PlaceCounted` and a first `LeaderChanged` with the leading answer; consecutive `ReplaySource` snapshots of each set give one `PlaceCounted` per reported place (109, 107, 107) and end with the national leader JA, NEJ, JA; `--diff` on `replay` of 2015 prints leader lines at country, landsdel and storkreds with letters `JA` and `NEJ` | A6 |
| T7 | Every existing test passes unchanged except the retargeted ones (the helper and case in `test_cli.py`, the test in `test_directory.py`, the case in `test_http_source.py`, the rows in `test_registry.py`), which now use `Kommunalvalg`; `git diff main -U0 -- tests` removes only those lines; `test_folketingsvalg.py` is untouched | A7 |

### Risks

- **A future referendum could differ from the four checked.** The adapter takes whatever `Parti` entries a feed lists, so more than two options still parse; a structural change would be an adapter bug to fix in `dst_feed`, and if it needs a model change beyond the member, **halt**.
- **Retargeting tests.** If the build finds an existing test, beyond the ones named, that asserts a Folkeafstemning overview is refused and cannot pass, it is the same class and is retargeted to `Kommunalvalg` and recorded; if one asserts something else about referenda that is genuinely undecided, **halt**.
- **Table width.** The one place output formatting changes; the guard is the existing CLI tests and the byte-identical party tables in T4. If the width rule disturbs an existing table, fix the rule, not the test.
- **Fixture size.** About 1.4 MB for three sets; accepted.
- **"Party" naming.** `PartyResult` and `is_party` read oddly for answers; documented and noted in `DEVELOPMENT.md`, a deliberate non-change.

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
