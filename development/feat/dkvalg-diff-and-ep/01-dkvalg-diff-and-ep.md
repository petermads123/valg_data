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
