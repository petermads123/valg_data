# dkvalg

Danish election data in one normalised model, built on the XML feeds DST (Danmarks Statistik)
publishes for the Folketingsvalg, the Europa-Parlamentsvalg and Danish referenda (Folkeafstemning). It reads a saved feed set and
replays it through time at accelerated speed, polls DST's live feeds over HTTP, and records what a poll receives so a
live night can be replayed later with its true timing. The pipeline is developed against a
real past election (24 March 2026), the EP election of 9 June 2024 and the referenda of
2022, 2015 and 2009. Standard library only.

**Version:** 1.3.2

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

### Folkeafstemning (referenda)

A referendum is read the same way (`ValgNavn` starts with `Folkeafstemning`;
`election.election_type` is `folkeafstemning`). DST serves the two answers as party entries,
so for a referendum the entries of `Place.parties` are the answers, with letter `JA` or
`NEJ`, and every seat field is `None`. `Place.leader` is the winning answer, and `diff_elections`
reports a flip as a `LeaderChanged`. `tests/fixtures/folkeafstemning_2022/`, `_2015/` and `_2009/`
are the referenda of 1 June 2022, 3 December 2015 and 7 June 2009 (the 2009 set has 94
opstillingskredse).

```python
from pathlib import Path

from dkvalg import PlaceType, load_election

election = load_election(Path("tests/fixtures/folkeafstemning_2022"))
print(election.of_type(PlaceType.COUNTRY)[0].leader.letter)  # JA
```

### Detecting changes

`diff_elections(previous, current)` compares two snapshots and returns typed changes, in a
stable order (places in overview order, then the progress change): `PlaceCounted`,
`PartyResultChanged` (with `votes_delta` and `seats_delta`), `LeaderChanged`, `StatusChanged`
and `ProgressChanged`. `previous` may be `None`. The library only detects; what to do about a
change, and any threshold, is the caller's.

Things to know: DST calculates seats after a place is first counted, so live, a counted place
gains its seats in a later snapshot and that shows as a `PartyResultChanged` (and a `seats`
line under `--diff`); only a replay of finished files shows seats arriving together with the
count, where a first count gives `PlaceCounted` and `LeaderChanged` but no `PartyResultChanged`.
A place nobody has voted at has no leader, and a place that loses its leader (a status fall to
0, 9 or 10) gives only a `StatusChanged`. Two snapshots of different elections raise `ValueError`
(the CLI turns that into `error: ...` and exit 1).

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
python -m dkvalg replay tests/fixtures/folkeafstemning_2022 --speed inf --diff   # a referendum: the rows are JA and NEJ
```

Prints one line per place as it is revealed, with a running counted-of-total progress, and ends
with the national result table. `--speed` is a positive number (default 600) or `inf` for no
waiting. `--diff` adds a line after each step for every notable change: a new leader at the
country, a landsdel or a storkreds, a seat change (or seats appearing), a status change and
the counting progress. A directory that is not a Folketingsvalg, Europa-Parlamentsvalg or Folkeafstemning feed
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

This repo ships a Claude Code configuration under `.claude/`, plus `CLAUDE.md` (the routing
map, loaded every session) and `STRUCTURE.md` (every module and public signature, imported by
`CLAUDE.md`). The pipeline is the one from `petermads123/template`.

Ask for a feature in plain words, or `/feature <what to build>`; report a bug the same way,
or `/fix <symptom>`. Claude routes it and says which route in one line.

| Stage | Skill | What happens | Waits for you |
|---|---|---|---|
| Concept | `/feature` | The concept, the branch name and the version bump are agreed; repo scouts investigate in the background; `BRIEF.md` splits the work into rounds | the concept and the rounds |
| Diagnosis (a bug) | `/fix` | The symptom reproduced as a failing test, causes hunted from three angles, one root cause proven and criticised | the cause, the scope and the bump |
| Each round | `/round` | Conceptualize, plan, implement, verify with parallel reviewers, four test designers, write and run the tests, three concept checkers, merge into the feature branch | only a question the round cannot answer |
| Finish | `/finish` | Whole-feature check, extras, the version, `STRUCTURE.md`, `README.md` and `DEVLOG.md` written, the pull request opened | only a critical extra |

State lives under `development/<branch>/` (`BRIEF.md`, `brief.json`, one `r<n>-<slug>/`
folder per round) and is committed after every step, so a session can be closed and resumed.
`development/README.md` documents the JSON files; the older numbered `NN-*.md` plan files
there are the history of the previous pipeline.

Claude never merges on its own judgment or on an approval alone: a pull request reaches
`main` because you pressed the button or told Claude to merge it. Every version is recorded
in `DEVLOG.md`.

### Hooks and CI

- **Session start** — reports a feature in flight and the skill that resumes it.
- **Before any shell command** — refuses a `git commit` or `git push` that would land on `main`.
- **After every `.py` write** — Ruff formats and auto-fixes the file.
- **CI** (`.github/workflows/check.yml`) — on every pull request and push to `main`, runs the
  four checks above and `python .claude/hooks/check_sync.py`, which checks that the version,
  `README.md`, `DEVLOG.md` and `STRUCTURE.md` agree with each other and the code.

Hooks are read at session start, so a change under `.claude/hooks/` or to
`.claude/settings.json` needs a Claude Code restart, and the first session asks for
workspace trust. The hooks run the first of `python3` or `python` that actually starts, so
the Windows Store alias stub is skipped.

### Troubleshooting

`Activate.ps1 cannot be loaded because running scripts is disabled` — allow local scripts
for your user:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

`python` not found right after `winget install` — open a new terminal so PATH is reloaded.
