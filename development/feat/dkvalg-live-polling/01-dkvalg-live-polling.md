# dkvalg: live polling, recording and capture replay

<!-- claude-plan step=2 status=active -->

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
