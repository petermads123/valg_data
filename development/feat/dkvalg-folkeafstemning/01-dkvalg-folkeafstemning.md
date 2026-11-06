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

One paragraph on the chosen approach, and one on what was rejected and why.

### Modules

| Path | New or changed | Purpose |
|---|---|---|

### Public API

> Every public class and function, with its full signature as it will be written.
> `Covers` links back to the acceptance criteria above.

| Signature | Module | Purpose | Covers |
|---|---|---|---|

### Implementation guide

Ordered. Each entry small enough to finish and check.

1.
2.

### Test intents

> High-level: what a test must prove, not how it is written. Step 5 turns each of these
> into concrete cases, including the edge cases.

| # | Must prove | Covers |
|---|---|---|
| T1 | | |

### Risks

What could make this harder than it looks, and what the build should do if it does —
including whether it should halt.

### Critique

> The `plan-critic`'s findings, each with what was done — applied, or rebutted in one
> sentence — then its verdict, and one line saying how the plan was accepted:
> `Accepted: clean critique, <date>` or `Accepted: by the user, <date>`.

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
