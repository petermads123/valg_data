# dkvalg: Folketingsvalg model, adapter and replay

<!-- claude-plan step=2 status=active -->

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
| A2 | ships real fixtures: `docs/` holds DST's XML-feeds PDF; `tests/fixtures/` holds the unmodified Folketingsvalg 24 March 2026 set (`generel.xml`, `valgdag.xml` and all 106 result feeds), with a README naming the source URLs and retrieval date. |
| A3 | parses the fixture set into a normalised election: name, date, type, and 106 places, each with type, id, name, status, eligible voters, turnout %, valid, blank and invalid votes, and per-party votes, %, constituency seats and supplementary seats. Tested on values from the files, e.g. Hovedstaden: 1,309,177 eligible voters, Socialdemokratiet 201,493 votes and 10 seats. |
| A4 | reports counting progress from a snapshot: how many of the 92 opstillingskredse have a result, distinguishing "no result yet" (status 0 or timestamp `0001-01-01`) from a reported result. |
| A5 | provides a ReplaySource that reveals each result feed at its `SenestRettet` time, in order: nothing counted at the start, equal to the static parse at the end, only already-reported places mid-sequence; at speed N gaps shrink by N, tested with an injected clock and no real waiting. |
| A6 | provides `python -m dkvalg replay <dir> [--speed N]` that prints each place as it is revealed with running counted-of-92 progress, ends with the national result table and exits 0; an empty or non-election directory prints a readable error to stderr and exits non-zero. |
| A7 | handles real-feed quirks: a UTF-8 BOM parses; "Uden for partier" (empty `Id`) is kept as a distinct non-party entry; a status 9 feed becomes an explicit error state rather than a crash; a missing feed file raises an error naming it. |

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
