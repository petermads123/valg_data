# dkvalg

Danish election data in one normalised model, built on the XML feeds DST (Danmarks Statistik)
publishes for the Folketingsvalg and the Europa-Parlamentsvalg. It reads a saved feed set and
replays it through time at accelerated speed, polls DST's live feeds over HTTP, and records what a poll receives so a
live night can be replayed later with its true timing. The pipeline is developed against a
real past election (24 March 2026) and the EP election of 9 June 2024. Standard library
only.

## Install as a dependency

```powershell
pip install git+https://github.com/petermads123/valg_data.git@main
```

Or in `dependencies` in `pyproject.toml`:

```toml
"dkvalg @ git+https://github.com/petermads123/valg_data.git@main"
```

## Usage

### Library

```python
from pathlib import Path

from dkvalg import PlaceType, ReplaySource, load_election

election = load_election(Path("tests/fixtures/folketingsvalg_2026"))
print(election.counting_progress())  # 92/92
hovedstaden = election.get(PlaceType.LANDSDEL, "7")
print(hovedstaden.eligible_voters, hovedstaden.parties[0].votes)

for step in ReplaySource(election, speed=600):  # waits between steps, 600 times faster
    print(step.at, step.progress, step.place.name)
```

`load_election` reads a directory laid out as DST serves it: `valgdag.xml` and the result
feeds it lists. `tests/fixtures/folketingsvalg_2026/` is such a directory (see its README
for the sources). A snapshot holds every place (country, the preliminary "optalling" tally,
landsdele, storkredse and opstillingskredse); a place with no result yet has status
`NOT_AVAILABLE`. A replay reveals each feed at its last-changed time, so landsdel, storkreds
and national figures appear late: DST publishes only the latest version of each feed.

### Europa-Parlamentsvalg

The election type is read from the overview's `ValgNavn`, so EP feeds load, replay, poll and
record exactly like Folketingsvalg ones (`election.election_type` says which). The EP feeds
carry no seat attributes, so every seat field is `None` and the national table shows `-`.
`tests/fixtures/ep_2024/` is the 9 June 2024 election.

```python
from pathlib import Path

from dkvalg import load_election

election = load_election(Path("tests/fixtures/ep_2024"))
print(
    election.election_type, election.counting_progress()
)  # europaparlamentsvalg 92/92
```

### Detecting changes

`diff_elections(previous, current)` compares two snapshots and returns typed changes, in a
stable order (places in overview order, then the progress change): `PlaceCounted`,
`PartyResultChanged` (with `votes_delta` and `seats_delta`), `LeaderChanged`, `StatusChanged`
and `ProgressChanged`. `previous` may be `None`. The library only detects; what to do about a
change, and any threshold, is the caller's.

```python
from pathlib import Path

from dkvalg import LeaderChanged, ReplaySource, diff_elections, load_election

source = ReplaySource(
    load_election(Path("tests/fixtures/folketingsvalg_2026")), speed=float("inf")
)
before = source.initial()
for step in source:
    for change in diff_elections(before, step.election):
        if isinstance(change, LeaderChanged):
            print(change.place.name, change.before, change.after.name)
    before = step.election
```

### Replay command

```powershell
python -m dkvalg replay tests/fixtures/folketingsvalg_2026 --speed 600
```

Prints one line per place as it is revealed, with a running counted-of-92 progress, and ends
with the national result table. `--speed` is a positive number (default 600) or `inf` for no
waiting. `--diff` adds a line after each step for every notable change: a new leader at the
country, a landsdel or a storkreds, a seat change (or seats appearing), a status change and
the counting progress. A directory that is not a Folketingsvalg or Europa-Parlamentsvalg feed
set prints `error: ...` to stderr and
exits 1. `python -m dkvalg` with no arguments prints usage.

### Live polling and recording

```python
from pathlib import Path

from dkvalg import HttpSource, Recorder, poll

source = HttpSource("Valg2546527", recorder=Recorder(Path("capture")))  # id or URL
for cycle in poll(source, interval=60):  # at least 15 seconds
    if cycle.error is not None:
        print("error:", cycle.error)  # the last good election is kept
    for place in cycle.changed:
        print(cycle.at, place.place_type.value, place.name)
```

`HttpSource.fetch()` is a blocking call that returns the current `Election` and the places
that changed since the last fetch; `poll` is a loop around it that a caller can run from its
own thread and end with `stop` or `max_cycles`. Requests are conditional (`ETag` and
`Last-Modified`), carry a `dkvalg/<version>` User-Agent and a timeout, and back off after
errors. A recorder saves every received feed in a folder named by the UTC fetch time, so
the recording can be replayed with its true timing and shows the real intermediate national
and storkreds results:

```powershell
python -m dkvalg poll Valg2546527 --interval 60 --record capture
python -m dkvalg replay capture --speed 600
```

`poll` takes an election id or the URL of its folder or `valgdag.xml`, an optional
`--interval` (seconds, at least 15, default 60), `--record DIR` and `--cycles N` (stop after
N polls; default no limit) and `--diff` (as for `replay`). It prints one line per changed place per poll and reports
failures as `error: ...` on stderr (exit 1 if the last poll failed; exit 2 for a bad
interval, cycle count or location; exit 130 on Ctrl-C). `replay` accepts either a plain feed
directory or a capture directory. XML that declares a DOCTYPE or an entity is refused.

## Why `src/`

Everything installable lives under `src/`, so nothing else in the repo — `tests/`, `docs/`,
a stray script — can be picked up as a package by accident, and an import in a test resolves
against the installed package rather than against whatever happens to sit in the working
directory.

The trade-off: the repo root is not on `sys.path`, so `python -m dkvalg.<module>` only
works once you have run `pip install -e ".[dev]"`. `pytest` is unaffected — `pythonpath`
in `pyproject.toml` points it at `src`.

Avoid naming the package folder `lib`, `build`, `dist` or `sdist`: the `.gitignore`
inherited from GitHub's Python template ignores those, so the folder would be silently
untracked even under `src/`.

## Development

### Prerequisites

All installable from PowerShell — no website visits needed:

```powershell
winget install --id Git.Git --source winget
winget install --id Python.Python.3.13 --source winget
code --install-extension ms-python.python
code --install-extension charliermarsh.ruff
```

The Python version must satisfy `requires-python` in `pyproject.toml`. To install a
different one, replace the version in the package id, e.g. `Python.Python.3.14`.

`winget` does not update the PATH of the shell it ran in. Open a new terminal before
continuing, then check with `python --version`.

### Create the environment

From the repo root:

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\Activate.ps1
```

```powershell
python -m pip install --upgrade pip
```

```powershell
pip install -e ".[dev]"
```

The `[dev]` part installs Ruff, mypy and pytest. Without it you get the package only.

In VS Code the environment activates automatically in new terminals once the interpreter is
selected. If it is not picked up, use `CTRL + Shift + P` -> `Python: Select Interpreter` and
choose the one in `.venv`.

### Verify

All four must pass on a fresh clone:

```powershell
ruff check .
```

```powershell
ruff format --check .
```

```powershell
mypy
```

```powershell
pytest
```

### Editor

`.vscode/settings.json` is checked in, so format-on-save, import sorting and Ruff as the
Python formatter are already configured for this repo. Installing the Ruff extension (see
Prerequisites) is all that is required.

## Working with Claude Code

This repo ships a Claude Code configuration under `.claude/`, plus `CLAUDE.md` (a routing
map, loaded every session) and `STRUCTURE.md` (a map of what lives where, imported by
`CLAUDE.md`).

### The commands

These are the ones you would type. Everything else under `.claude/skills/` is a step the
pipeline opens by itself, and you rarely need to know it is there.

| Command | Use it for |
|---|---|
| `/feature <what to build>` | Anything new or changed that is not cosmetic: a module, a public function, a behaviour change. Opens the ten-step pipeline below at step 1. With no argument, reports where an in-flight feature got to. |
| `/fix <symptom>` | Something that exists behaves wrongly: wrong output, a crash, a guard that lets something through. Reproduces it, finds the root cause and sizes what else the cause breaks **before** the pipeline opens, then runs the same ten steps as a fix round. Sends you to `/feature` or `/small-change` instead if the diagnosis says it is not a bug. |
| `/small-change <what to change>` | Cosmetic edits with none of the pipeline: a local rename, a docstring reword, message text, plot styling, formatting. Refuses anything that adds or removes a file, changes a public signature, changes behaviour or needs a new test. |
| `/build` | Resume a build that halted to ask you something, once you have answered. |
| `/recommend` | Re-open step 8, if a session ended with a critical follow-up undecided. |
| `/create-pr` | Open the pull request for a finished branch, if you did not do it in the session that finished it. |
| `/watch-pr` | Resume watching an open pull request in a fresh session. |

You do not have to type any of them: describe the work in prose and Claude picks the route,
saying which and why in one line. The routing rules are in `CLAUDE.md`.

### The implementation pipeline

Anything that is not cosmetic goes through ten steps. You decide at most three times — the
concept, the plan, and any critical follow-up at step 8, which most rounds do not have —
plus a yes before step 9 publishes, and the build in between runs on its own. The state lives on
disk rather than in the conversation, and every step commits and pushes it, so a feature
survives closing the session and coming back tomorrow — one folder per branch, one numbered
file per round:

```
development/
  TEMPLATE.md
  feat/csv-export/
    01-csv-export.md          round 1, shipped
    02-streaming-writer.md    round 2, in flight
```

| Step | Command | Produces | Waits for |
|---|---|---|---|
| 1 | `/conceptualize` | The concept, agreed with you, numbered acceptance criteria, the branch and the version bump | you |
| 2 | `/plan` | Modules, full signatures, implementation guide, test intents | you, only if the plan critic leaves something open |
| 3 | `/build` → `/implement` | The production code | — |
| 4 | `/build` → `/verify` | ruff, mypy, and a check that the code matches the plan | — |
| 5 | `/build` → `/test` | The edge-case suite, and fixes for what it finds | — |
| 6 | `/build` → `/concept-check` | An audit against step 1, criterion by criterion | — |
| 7 | `/build` → `/ship` | The round closed, whole tree green | — |
| 8 | `/recommend` | Critical follow-ups only, usually none; lesser ideas noted in `DEVELOPMENT.md` | you, only if there is one |
| 9 | `/create-pr` | A full re-verification of the whole branch, the version bump written, then a pull request to `main` | you, before it publishes |
| 10 | `/watch-pr` | An hourly check of the open PR, acting on comments, until it merges or closes | — |

**Steps 3 to 7 run without you.** Once the plan is accepted, `/build` runs implement, verify,
test, concept-check and ship in order, each in its own subagent on the model that step
pins, committing and pushing after each. It halts for exactly two things: a finding that
would change the concept you agreed to, and a check that fails twice the same way after one
fix. A halt commits what exists, writes the question into the plan file, and waits; `/build`
resumes once you answer. While it runs you get a trace — a line or two per module, class,
function and test group as each step lands — so you can see what was built without reading
the diff.

Where the work genuinely diverges, more than one agent reads it: a diagnosis critic tries
to falsify the root cause before a fix is agreed, a plan critic reads the plan against the
concept before the build starts, two test designers with different briefs find the edge cases
at step 5, and on a fix round one more reader asks at step 8 where else the same cause
lives. The calling step merges what they find and stays the single voice.

Step 9 requests your review on the PR it opens. **Claude never merges on its own judgment,
and never on an approval alone** — a PR reaches `main` either because you pressed the button
or because you explicitly told Claude to. An approval says the change is wanted, not that it
should ship now. Once told, the instruction still waives nothing: it must not be stale
(anything pushed since means you would be merging code you have not seen), no conflict, and
every review thread resolved. Once a pull request has merged, by either route, Claude
deletes its branch as part of closing out, after confirming the head is on `main`.

Note that **GitHub lets nobody request a review from, or approve, their own pull request**.
In a solo repo, where Claude pushes under your token, every PR is authored by you — so the
review route is unavailable, step 9 assigns you instead, and the merge signal is an explicit
"merge it" from you. `CLAUDE.md` names the approver.

Start with `/feature <what to build>` — it opens step 1. Your confirmation of the concept
opens step 2 in the same turn. The plan opens the build on its own when the plan critic
leaves nothing open — every finding applied, none disputed — and waits for your acceptance
when it does. After the build, step 8 asks you only if it found something critical, and
step 9 asks before it publishes.

Each branch also moves the package version, `MAJOR.MINOR.PATCH` in `pyproject.toml`. The
bump is decided with the concept at step 1 — `patch` for a fix, `minor` for a change to
something that exists or a small addition, `major` for a large new feature, `none` when
nothing that ships changes — and written at step 9, counted from `main` as it stands then.
`CLAUDE.md` has the scale.

A bug starts with `/fix <symptom>` instead, and gets a diagnosis before step 1: the symptom
reproduced and its output quoted, the root cause as a file and line, the commit that
introduced it, the other inputs the same cause breaks, and who depends on the current
behaviour — read a second time by a critic whose job is to find a different cause. Only
then does step 1 open, and its first question is the one every fix has: this instance, or
the whole class? The rest of the pipeline is the same, with differences you will see in
the trace: the build writes the reproduction as a test and runs it red before fixing,
and halts if it is not red; the concept check has to show more than a green suite for
"nothing else changed"; and step 8 gets a reader asking where else the same cause lives
and what should have caught it. If the diagnosis finds that the code does what
was agreed and you want something different, `/fix` says so and hands over to `/feature`.

**You do not have to type the commands.** Describe the work in prose — "I want to add CSV
export", "rename that variable" — and Claude classifies it against the small-or-large test
before doing anything: a local rename with no signature or behaviour change is small, and
anything that adds a file, changes a public signature, changes behaviour or needs a test is
not — and a bug is a third thing, routed to `/fix` because the first question it raises is
whether it is a bug at all. It says which way it routed and why in one line, so a wrong
call costs you a sentence to correct, and asks only when the request is genuinely
borderline. When it is close, it routes up to the pipeline, because step 1 is a
conversation you can redirect — whereas a feature handled as a small change quietly skips
the concept, the tests and the audit.

A slash command still wins if you type one, and a question stays a question: asking how
something works gets an answer, not a pipeline.

Each step also picks its own model. Concept, planning and recommendations run on Opus
because they are judgment; implementation, verification, tests, the concept check and the
pull request run on Sonnet at max effort because the thinking has already been done and
written down. Steps 3 to 7 run as subagents for exactly this reason — a skill's model
override lasts the whole turn, so five steps chained in one turn would all run on the first
one's model. The one exception is the end of the build: `/build` opens `/recommend` in its
own turn, so step 8 and the `/create-pr` it hands on to run on the build's model.
`/small-change` runs on Opus too — deciding a change is small enough to skip the pipeline
is the one judgment made without the pipeline to catch it. `CLAUDE.md` has the table.

Step 9 is not a formality. It is the only point where the branch is verified as a whole:
step 7 checked one round at one moment, so on a multi-round branch nothing has yet proved
that round 2 left round 1 working. It re-runs the full suite, every module showcase and
every round's plan against a clean tree and a current `main`, and it marks the plan `done`
in the commit that opens the pull request — so the review lives on the pull request thread
and no commit ever exists just to tidy up afterwards.

Two things are worth knowing about the shape of it. **Step 6 audits against step 1, not
step 2**: a plan can drift from its concept a little at each step while passing every check
along the way, and this is where that gets caught. And **step 8 is deliberately small**:
it raises a follow-up only when leaving it undone would make what ships wrong or unsafe,
and most rounds have none. Lesser ideas become one-line notes in `DEVELOPMENT.md` rather
than questions for you. A recommendation you accept opens a new numbered file in
the same folder and goes back through steps 1 to 7 on the same branch, so one pull request
can carry several deliberate passes over one feature. Step 6 of a later round re-checks the
earlier rounds' acceptance criteria, so a follow-up cannot quietly regress what it builds on.

### Hooks

Four run automatically:

- **Session start** — reports the active plan and its step, so a new session picks up where
  the last one stopped. Silent when nothing is in flight.
- **Before any shell command** — refuses a `git commit` or `git push` that would land on
  `main`, including inside a `&&` chain.
- **After every `.py` write** — Ruff formats and auto-fixes the file; only unfixable issues
  come back.
- **Before a turn ends** — the stop gate. Through step 7 it only reports, because the build
  runs its own checks and has to be able to halt on a red tree; from step 8, and for any
  work with no plan file, it refuses to end a turn that changed Python while ruff, mypy or
  pytest fail or `STRUCTURE.md` is out of sync. Prose-only work is not gated. Create
  `.claude/.skip-gate` to bypass it.

Three caveats worth knowing:

- **Hooks are read at session start.** Editing anything under `.claude/hooks/` or
  `.claude/settings.json` needs a Claude Code restart. Skills and rules hot-reload.
- **The first session prompts for workspace trust**, because `.claude/settings.json`
  registers hooks. Accept it or the hooks stay inactive.
- The hooks call `python` from your PATH and only use the standard library; they locate
  `ruff`, `mypy` and `pytest` inside `.venv` themselves.

### Troubleshooting

`Activate.ps1 cannot be loaded because running scripts is disabled` — allow local scripts
for your user:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

`python` not found right after `winget install` — open a new terminal so PATH is reloaded.
