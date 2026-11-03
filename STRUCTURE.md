# Structure

Map of everything in this repo. Loaded into context at the start of every session via the
`@STRUCTURE.md` import in `CLAUDE.md`, so it is what Claude uses to find things without
searching.

## Keeping this file current

Update it **in the same change** that causes any of the following:

- a module is added, deleted, renamed or moved
- a public function or class is added or removed
- a public signature changes (parameters, defaults, return type)
- a module's purpose changes

Private helpers (names starting with `_`) are intentionally left out. They are
implementation detail, and listing them is what makes a file like this rot.

The stop gate (`.claude/hooks/stop_gate.py`) cross-checks the module paths named here
against the `.py` files on disk and blocks on a mismatch. It only sees file-level drift —
signature drift is on you, or run the `structure-auditor` subagent.

That covers `src/`, `tests/` and `.claude/hooks/`. The hooks are documented here with full
signature tables, type-checked like the package (`[tool.mypy] files` names all three) and
importable from the suite (`[tool.pytest.ini_options] pythonpath` names `src` and
`.claude/hooks`, so a test imports a hook by module name the same way a sibling hook does
at runtime), so they are held to the same standard despite not being installable.

## Growth

While the package is flat, keep everything here. Once it has subpackages, keep the tree and
one line per subpackage in this file, and move per-subpackage detail into
`.claude/rules/structure-<subpackage>.md` with `paths: ["<subpackage>/**"]` so it loads only
when Claude works in that subpackage. Split rather than delete — there is no length limit
here, but everything in this file is in context every session.

## Tree

```
src/                    everything installable; nothing outside it is packaged
  dkvalg/               the package: model, adapters, sources and the CLI
docs/                   reference documents (DST's XML-feeds PDF)
tests/                  pytest suite, one test_<module>.py per module
  fixtures/             unmodified real DST feeds used as test data
development/            one folder per branch, one file per round: the pipeline's state
.claude/                Claude Code configuration: rules, skills, agents, hooks
.vscode/                editor config (Ruff as formatter, format on save)
pyproject.toml          packaging, Ruff, mypy and pytest configuration
DEVELOPMENT.md          development-side open questions and things to fix later (see CLAUDE.md)
README.md               human setup guide
CLAUDE.md               routing map for Claude
STRUCTURE.md            this file
```

## Package: `src/dkvalg/`

Reads DST's Folketingsvalg XML feeds into one normalised, immutable model and replays a
saved feed set through time. Standard library only. Subpackages: `adapters/` (bytes in,
model out, one module per election type) and `sources/` (where an `Election` comes from: a
directory, or a time-scaled replay of one). Every `main()` is a showcase and runs standalone
with `python -m dkvalg.<module>` (`cli`'s is the entry point); the ones that read fixtures
locate them by a repo-relative path and say so outside a checkout.

### `src/dkvalg/__init__.py`

Re-exports the public API: `FeedError`, `ElectionType`, `PlaceType`, `Status`,
`PartyResult`, `Place`, `CountingProgress`, `Election`, `load_election`, `ReplaySource`,
`ReplayStep`. Adapter internals (`parse_*`, `unreported_place`, `FeedRef`, `Overview`) and
the CLI (`run`, `main`) stay in their modules.

### `src/dkvalg/errors.py`

| Signature | Description |
|---|---|
| `class FeedError(Exception)` | A feed is missing, unreadable, malformed, or of an unsupported election type; the message names the file or value. |
| `main() -> None` | Showcase. |

### `src/dkvalg/model.py`

Normalised, immutable election model. Seat fields are `None` where DST gives none.

| Signature | Description |
|---|---|
| `class ElectionType(StrEnum)` | `FOLKETINGSVALG = "folketingsvalg"`. |
| `class PlaceType(StrEnum)` | `COUNTRY`, `TALLY` (DST's seatless preliminary "optalling" total), `LANDSDEL`, `STORKREDS`, `OPSTILLINGSKREDS`. |
| `class Status(IntEnum)` | DST status code: `NOT_AVAILABLE` 0, `PRELIMINARY` 1, `ERROR` 9, `RECOUNT_PENDING` 10, `RECOUNT_PRELIMINARY` 11, `RECOUNT_FINAL` 12; property `has_result` (true for 1, 11, 12). |
| `@dataclass(frozen=True, slots=True) class PartyResult` | `party_id: str`, `letter: str`, `name: str`, `votes: int`, `percent: float`, `seats: int \| None = None`, `constituency_seats: int \| None = None`, `supplementary_seats: int \| None = None`; property `is_party` (false for "Uden for partier", `party_id == ""`). |
| `@dataclass(frozen=True, slots=True) class Place` | `place_type`, `place_id`, `name`, `parent_id`, `status`, `status_text`, `last_changed`, then optional `eligible_voters`, `turnout_percent`, `valid_votes`, `blank_votes`, `other_invalid_votes`, `total_invalid_votes`, `total_votes` and `parties: tuple[PartyResult, ...] = ()`; property `has_result`; `unreported() -> Place` gives the placeholder form. |
| `@dataclass(frozen=True, slots=True) class CountingProgress` | `counted: int`, `total: int`; `str` gives `"counted/total"`. |
| `@dataclass(frozen=True, slots=True) class Election` | `name`, `election_type`, `election_date`, `places`; `get(place_type, place_id) -> Place` (`KeyError` naming both), `of_type(place_type) -> tuple[Place, ...]`, `counting_progress() -> CountingProgress` (opstillingskredse with a result). |
| `main() -> None` | Showcase. |

### `src/dkvalg/adapters/__init__.py`

Package marker for per-election-type adapters.

### `src/dkvalg/adapters/folketingsvalg.py`

Parses DST's Folketingsvalg feeds; no I/O. Timestamps are naive Danish local time as
served (a UTC offset is refused; "never" in either spelling is None); a BOM is accepted;
figures must be plain numbers (no `nan`, `inf`, `1_000`).

| Signature | Description |
|---|---|
| `@dataclass(frozen=True, slots=True) class FeedRef` | `place_type`, `place_id`, `name`, `parent_id`, `last_changed: datetime \| None`, `file_name`: one feed as listed by the overview. |
| `@dataclass(frozen=True, slots=True) class Overview` | `name`, `election_type`, `election_date`, `feeds: tuple[FeedRef, ...]`. |
| `parse_overview(xml: bytes) -> Overview` | Parse `valgdag.xml`; `FeedError` when malformed, not a Folketingsvalg, or listing no feeds. |
| `parse_place(xml: bytes, ref: FeedRef) -> Place` | Parse one result feed; status 0, 9 and others without a result give a figure-free place; `FeedError` on malformed XML, an unknown status code, a result status without `Stemmer`, a `Parti` without `Id`, or a non-numeric figure. |
| `unreported_place(ref: FeedRef) -> Place` | Placeholder for a feed the overview lists as never reported. |
| `main() -> None` | Showcase. |

### `src/dkvalg/sources/__init__.py`

Package marker for sources.

### `src/dkvalg/sources/directory.py`

| Signature | Description |
|---|---|
| `load_election(directory: Path) -> Election` | Read `valgdag.xml` and every reported feed it lists from a DST-layout directory; `FeedError` naming a missing file. |
| `main() -> None` | Showcase. |

### `src/dkvalg/sources/replay.py`

| Signature | Description |
|---|---|
| `@dataclass(frozen=True, slots=True) class ReplayStep` | `at: datetime`, `place: Place`, `election: Election`; property `progress`. One reveal. |
| `class ReplaySource` | `__init__(self, election: Election, *, speed: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> None` (`ValueError` unless `speed` is positive and not NaN; `inf` never waits); `initial(self) -> Election`; `__iter__(self) -> Iterator[ReplayStep]` reveals each place at its `last_changed`, ties in overview order. |
| `main() -> None` | Showcase. |

### `src/dkvalg/cli.py`

| Signature | Description |
|---|---|
| `run(argv: Sequence[str] \| None = None, *, out: TextIO \| None = None, err: TextIO \| None = None, sleep: Callable[[float], None] = time.sleep) -> int` | `replay <dir> [--speed N]`; returns 0 ok, 1 on `FeedError` (`error: <message>` on `err`), 2 on bad arguments; no subcommand prints help and returns 0. |
| `main() -> None` | `raise SystemExit(run())`. |

### `src/dkvalg/__main__.py`

Entry point for `python -m dkvalg`; calls `cli.main()`.

## Documents and fixtures

### `docs/XmlFeeds20260305.pdf`

DST's documentation of its election XML feeds (status codes, element meanings), from
https://dst.dk/Valg/XmlFeeds20260305.pdf.

### `tests/fixtures/folketingsvalg_2026/`

The unmodified Folketingsvalg 24 March 2026 feeds retrieved 2026-11-03 from
`https://www.dst.dk/valg/Valg2546527/xml/`: `generel.xml`, `valgdag.xml` and the 107 result
feeds it lists (109 XML files, BOM intact), plus `README.md` (sources, retrieval date) and
`SHA256SUMS` (hash of every XML file at download time). `.gitattributes` marks the
directory `-text` so checkouts never rewrite line endings.

## Tests: `tests/`

Tests for the `dkvalg` package: one `test_<module>.py` per module, plus `conftest.py` for
the shared helpers. No test touches the network; datetimes are built only with
`datetime.fromisoformat`.

### `tests/conftest.py`

Shared helpers, not tests: `FIXTURES`/`ROOT` paths, the `fixture_dir` (read-only), `fixture_copy`
(a throwaway copy a test may damage) and session-wide `election` (the fixtures loaded once)
fixtures, and small builders for synthetic feeds in DST's real XML shape: `feed_xml`,
`overview_xml`, `entry`, `kreds_entry`, `make_ref`, `make_place`, `make_election`,
`write_directory` and `dt`.

### `tests/test_errors.py`

Covers `FeedError`: message kept, not a `ValueError`/`KeyError`/`OSError`, cause preserved.

### `tests/test_model.py`

Covers `dkvalg.model`: `Status.has_result` per code, `PartyResult.is_party`, `Place.unreported`
(identity kept, figures dropped, idempotent, pure), immutability and hashing, `Election.get` /
`of_type` / `counting_progress` boundaries, `CountingProgress.__str__` (T4, T8).

### `tests/test_package.py`

Covers the package surface: `import dkvalg`, the re-exported names, adapter and CLI names kept
out of the top level, and `valg_data`/`template_repo` not importable (T1, A1).

### `tests/test_folketingsvalg.py`

Covers `dkvalg.adapters.folketingsvalg`: `parse_overview`, `parse_place` and `unreported_place`
against the real fixtures (Hovedstaden field by field) and synthetic feeds: BOM, "never"
timestamps in every spelling, empty `SenestRettetIso`, status codes, missing and non-numeric
figures (`nan`, `inf`, `1_000`), a party without `Id`, malformed XML, non-Folketingsvalg
overviews (T3, T7, A3, A7).

### `tests/test_directory.py`

Covers `dkvalg.sources.directory.load_election`: the 107-place fixture election (type counts,
seats summing to 175, no seats below storkreds, "Uden for partier"), placeholders for never
reported feeds, missing/empty/malformed files and unreadable paths all as `FeedError`
naming the file, purity and idempotency (T3, T7, T8, A3, A7).

### `tests/test_replay.py`

Covers `dkvalg.sources.replay`: start at 0/92, order with ties in overview order, mid-sequence
snapshots, final snapshot equal to the static election (also with untimed, status 0 and 9
places), sleeps as gaps divided by speed with an injected clock, `inf` never sleeping, speed
validation, restart and interleaved iterators, purity (T5, T8, A5).

### `tests/test_cli.py`

Covers `dkvalg.cli` and `dkvalg.__main__`: `run` on the fixtures (one line per step, rising
counted/total, national table), errors on stderr with exit 1, bad arguments with exit 2, usage
and help with exit 0, stream handling, and `main` / `python -m dkvalg` through `runpy` and a
subprocess with `PYTHONPATH=src`, independent of the editable install (T1, T6, A1, A6).

### `tests/test_fixtures.py`

Verifies the fixture directory: 109 XML files plus README and `SHA256SUMS`, every feed the
overview lists present, every file matching its SHA-256 with its BOM intact, the PDF in `docs/`,
the README's source URLs and date, and `.gitattributes` (T2, A2).

All tests live here and nowhere else — `testpaths = ["tests"]` in `pyproject.toml` means
`pytest` collects nothing outside this directory, and the stop gate blocks on a test file
found anywhere else.

### `tests/test_guard_git.py`

Covers `.claude/hooks/guard_git.py` — every public function plus `main` end to end against a
throwaway repository, over both Bash and PowerShell command forms — and is the regression
suite for the quoting defect its parser was rebuilt to fix. One test asserts a documented
miss rather than a fix: `sudo -u me git push` is allowed, because only options are skipped
after a wrapper and never a bare word.

### `tests/test_plan_state.py`

Covers `.claude/hooks/plan_state.py`: every public function, the `Plan` properties either
side of `GATE_FROM_STEP`, and the git helpers against a throwaway repository.

### `tests/test_stop_gate.py`

Covers `.claude/hooks/stop_gate.py`: every public function and `main`'s paths through the
gate. `gate_failures`, `enforce` and `main` are driven through a monkeypatched `venv_tool`,
`capture` and checks rather than real executables: running them for real would invoke Ruff,
mypy and `pytest` from inside `pytest`, and stub executables would need a shell script on
POSIX and an `.exe` on Windows.


## Plans: `development/`

One folder per branch, one numbered file per round inside it, created at the close of step
1 from `TEMPLATE.md` and carried through all ten steps:

```
development/
  TEMPLATE.md                     copied for each new round; never itself active
  feat/csv-export/                the folder is the branch name, so it nests one level
    01-csv-export.md              round 1, shipped
    02-streaming-writer.md        round 2, opened from round 1's recommendation R2
```

Each file holds the concept and acceptance criteria, the plan, the verification and test
logs, the concept-check audit, the recommendations and the pull request, plus a `Halted`
section if the build stopped to ask. A fix round's section 1 also carries a **Defect**
block — reproduction, root cause, class, blast radius, scope — filled from the `/fix`
diagnosis; its presence is what tells the later steps the round is a fix. Every round
of a feature shares one branch and one pull request; a later round's **Builds on** section
names what the earlier rounds delivered, and its step 6 re-checks their acceptance criteria
as a regression pass.

The first line after the title is the workflow's state and is read by the hooks:

```
<!-- claude-plan step=3 status=active -->
```

`step` is 1 to 10; `status` is `active`, `done`, `parked` or `template`. Exactly one file
across the whole repo should be `active` — opening a round stands its predecessor down to
`done`, and step 9 marks the newest round `done` in the commit that opens the pull request,
so `main` never carries a live marker. Every step commits and pushes the file with what it
produced: plan files are the record of why the code looks the way it is, the state any
session resumes from, and what `/create-pr` builds the pull request body from.

## Claude configuration: `.claude/`

| Path | Role |
|---|---|
| `settings.json` | Registers the four hooks; pre-approves ruff/mypy/pytest, `python -m`, and the git commands the pipeline uses (read-only ones plus add, commit, push, fetch, checkout, switch, merge, mv) so an unattended build never stalls on a prompt — `guard_git.py` is what keeps that safe |
| — | Every skill pins `model` and `effort` in its frontmatter; the table in `CLAUDE.md` says which and why |
| `skills/build/` | `/build` — steps 3 to 7 as one unattended block, with `models.md` holding the per-step model and effort table and its rationale: a subagent per step on its pinned model, the step's readers (`structure-auditor`, `test-designer`) run by the orchestrator and handed over in the brief, work-in-progress commits, commit and push after each, halting rules, trace relay, resume from the marker or an interrupted run |
| `rules/python.md` | Coding conventions, auto-loaded for `**/*.py` |
| `skills/repo-setup/` | `/repo-setup` — one-time setup of a repo made from this template; carries `main_protect.solo.json` and `main_protect.collab.json` |
| `skills/feature/` | `/feature` — starts or resumes the pipeline |
| `skills/fix/` | `/fix` — starts the pipeline from a defect: reproduces, finds the root cause, sizes the class, has the diagnosis criticised, decides whether it is a bug at all, then hands to `/conceptualize` as a fix round |
| `skills/conceptualize/` | `/conceptualize` — step 1, agree the concept, name the branch and choose the version bump |
| `skills/plan/` | `/plan` — step 2, design it; waits for the user only when the critic leaves something open |
| `skills/implement/` | `/implement` — step 3, write the code (inside `/build`) |
| `skills/verify/` | `/verify` — step 4, static verification |
| `skills/test/` | `/test` — step 5, edge-case suite |
| `skills/concept-check/` | `/concept-check` — step 6, audit against the concept |
| `skills/ship/` | `/ship` — step 7, close the round: whole-tree gates and diff review (inside `/build`) |
| `skills/recommend/` | `/recommend` — step 8: critical follow-ups only, usually none, decided with the user; lesser ideas noted in `DEVELOPMENT.md`; with nothing critical it hands on to `/create-pr` |
| `skills/create-pr/` | `/create-pr` — step 9, write the version bump, pull request ready for review |
| `skills/watch-pr/` | `/watch-pr` — step 10, hourly review watch until merge or close |
| `skills/small-change/` | `/small-change` — cosmetic edits, outside the pipeline |
| `agents/diagnosis-critic.md` | Subagent that tries to falsify a defect diagnosis before step 1 agrees a fix on it — re-runs the reproduction, traces the cause independently, checks the class (feeds `/fix`); may run code from a scratch directory but never writes to the tree; pinned to `opus` |
| `agents/plan-critic.md` | Read-only subagent that reads a plan against its concept and the repo before it is accepted (feeds step 2; a clean verdict starts the build without the user); pinned to `opus` |
| `agents/test-designer.md` | Read-only subagent that finds edge cases; run twice at step 5 with the `input-space` and `contract` briefs |
| `agents/brainstormer.md` | Read-only subagent that proposes at most three follow-ups through one lens — `user`, `maintainer`, `integrator` or `defect-class` — or none; step 8 runs only `defect-class`, on a fix round, and the others run when the user asks what to build next |
| `agents/structure-auditor.md` | Read-only subagent that reconciles this file (feeds steps 4 and 6) |

### `.claude/hooks/plan_state.py`

Shared by the other hooks: parses the `claude-plan` marker out of the plan files and
answers which plan is active, plus the small git helpers the hooks need. Importable by its
siblings because Python puts a script's own directory on `sys.path`. Stdlib only.

| Signature | Description |
|---|---|
| `Plan` | Frozen dataclass: `path`, `step`, `status`, `title`, `branch`, `feature` (the folder relative to `development/`, so the branch name with its `/`; empty for `TEMPLATE.md`), `round_number`, plus `step_name` and `gated` properties. |
| `parse(path: Path) -> Plan \| None` | Parse one plan file, or None if it has no valid marker. |
| `all_plans(project_dir: Path) -> list[Plan]` | Every parseable plan in every feature folder, most recently modified first. |
| `active_plan(project_dir: Path) -> Plan \| None` | The plan the pipeline is working through. |
| `feature_rounds(project_dir: Path, feature: str) -> list[Plan]` | One feature's rounds, oldest first; `feature` is the folder relative to `development/`, as on `Plan.feature`. |
| `git_lines(project_dir: Path, args: list[str]) -> list[str]` | Run git, return output lines. |
| `current_branch(project_dir: Path) -> str` | The checked-out branch, or `""`. |
| `main() -> None` | Showcase: prints the plans found, the active one and its sibling rounds. |

`GATE_FROM_STEP = 8` is the step at which the stop gate starts blocking: steps 3 to 7 are
the build, which carries its own gates and must be able to halt on a red tree.
`PLAN_DIR = development` is the directory it scans; `Plan.feature` is a folder path relative
to it, so a branch-named folder such as `feat/csv-export` comes back with its `/`.

### `.claude/hooks/session_brief.py`

`SessionStart` hook. Injects the active plan's step into a new session's context, the skill
that resumes it (`/build` for steps 3 to 7), plus what any earlier rounds of the same
feature delivered, so work resumes without the user having to re-explain it. Silent when
no plan is active — including while a pull request is open, since step 9 closes the plan.
Stdlib only.

| Signature | Description |
|---|---|
| `brief(project_dir: Path, plan: Plan) -> str` | Describe one active plan's state. |
| `main() -> None` | Entry point: emit the brief as session context. |

### `.claude/hooks/guard_git.py`

`PreToolUse` hook on `Bash` and `PowerShell`. Refuses a `git commit` or `git push` that
would land on `main`. Reads the command the way a shell does — `shlex` resolves quoting, so a `;` or `|`
inside a commit message stays part of the message — then splits it on the real separators
into one invocation per segment. The grouping delimiters `(`, `)`, `{` and `}` split too, so
a command hidden inside `(git commit -m "x")` is seen rather than left with `(` sitting
where its name should be.

Each segment is judged against the branch that will be checked out when it runs. Only `&&`
guarantees its left side succeeded, so a branch switch carries forward across a run of
separators that is `&&` and newlines, and across nothing else: `git checkout -b feat/x &&
git commit` is allowed from `main`, and so is the same pair with the `&&` ending the line,
while `;`, `|`, `||`, `&`, a bare newline or a mixed run such as `; &&` is refused. A switch
that may not have taken effect here is distrusted the same way: one made inside a subshell
that has since closed, or aimed elsewhere by a global `-C`, `--git-dir` or `--work-tree`,
leaves the branch as it was. What still cannot be read is refused when it names `commit` or
`push` — matched on word boundaries, so `committee` is not a commit — while `main` is
checked out, and allowed anywhere else.

Within a segment it finds the command name where a shell would, after the prefix of
variable assignments and redirections, so `GIT_EDITOR=true git commit` and
`>log git commit` are seen. Backticks around a substitution are stripped, the executable is
matched without regard to case, and a short list of wrapper programs — `sudo`, `env`,
`time`, `nohup`, `doas` — is stepped over. That list is deliberately incomplete: a wrapper
nobody listed is a miss, which is safe, while scanning a segment for any `git` token would
refuse `echo git commit`, which is the failure this module treats as worse. Only options are
skipped after a wrapper, never a bare word, so an option that takes a value hides what
follows it.

A push's destination is read with the same care. The arguments are walked rather than
filtered, so an option that takes a value — `-o`, `--push-option`, `--repo`,
`--receive-pack`, `--exec` — does not leave its value standing where the remote should be,
and `git push -o ci.skip origin` is seen as the bare push it is. Every ref is then reduced
to the branch it names: a leading `+` dropped, the destination half of a `src:dst` pair
taken, `refs/heads/` stripped, backticks removed and `@` read as `HEAD`. Switch targets go
through the same reduction, so `git checkout refs/heads/main` is a switch to `main`.

A branch switch whose target only the running shell can resolve — `git checkout -`,
`@{-1}` — leaves the branch *unknown* rather than unchanged, and a `commit` or `push` that
meets an unknown branch is refused with a message saying so rather than the one about
`main`. Stdlib only.

| Signature | Description |
|---|---|
| `Segment` | Frozen dataclass: `tokens` and the `separator` that preceded them — one of `SEPARATORS`, a newline, or a grouping delimiter (`""` for the first). |
| `segments(command: str) -> list[Segment] \| None` | Split a command into invocations, or None if it cannot be read. |
| `git_subcommand(tokens: tuple[str, ...]) -> tuple[str, tuple[str, ...]]` | Identify the git subcommand and its arguments. |
| `push_targets_main(args: tuple[str, ...], branch: str) -> bool` | Whether a push would update `main`. |
| `switch_target(subcommand: str, args: tuple[str, ...]) -> str` | The branch a `checkout`/`switch` moves to, `""` when it moves none, or the sentinel `UNRESOLVED` (`"?"`) for a target only the running shell can resolve — `-` and `@{-1}`. |
| `violation(command: str, branch: str) -> str` | The reason to refuse, or `""` to allow. |
| `main() -> None` | Entry point: allow or refuse the command. |

### `.claude/hooks/lint_py.py`

`PostToolUse` hook. Runs `ruff format` and `ruff check --fix` on any `.py` file Claude
writes or edits, and reports unfixable issues back via exit code 2. Stdlib only.

| Signature | Description |
|---|---|
| `find_ruff(project_dir: Path) -> Path \| None` | Locate Ruff in the project venv. |
| `run(ruff: Path, args: list[str]) -> CompletedProcess[str]` | Run Ruff, capturing output. |
| `target_file(payload: dict[str, object], project_dir: Path) -> Path \| None` | Extract the edited `.py` file from the hook payload. |
| `main() -> None` | Entry point: format, fix, report. |

### `.claude/hooks/stop_gate.py`

`Stop` hook. Reads the active plan's step to decide how strict to be: advisory through step
7, blocking from step 8 and whenever no plan is active, and only when a Python file changed
in the tree or on the branch. When it blocks it runs ruff, mypy
and pytest, cross-checks `STRUCTURE.md` against the modules on disk, reports any test file
sitting outside `tests/` where `pytest` would silently never collect it, and reports any
package directory under `src/` missing its `__init__.py`. Bypass with
`.claude/.skip-gate`. Stdlib only.

| Signature | Description |
|---|---|
| `venv_tool(project_dir: Path, name: str) -> Path \| None` | Locate a tool in the project venv. |
| `capture(cmd: list[str], cwd: Path, timeout: int) -> CompletedProcess[str]` | Run a command, capturing output. |
| `changed_python_files(project_dir: Path) -> set[str]` | Python files changed in the tree or on this branch. |
| `tracked_python_files(project_dir: Path) -> set[str]` | All non-ignored Python files. |
| `structure_problems(project_dir: Path) -> list[str]` | File-level drift between this file and disk. |
| `stray_test_files(project_dir: Path) -> list[str]` | Test files outside `tests/`, which pytest never collects. |
| `missing_init_files(project_dir: Path) -> list[str]` | Package directories under `src/` with no `__init__.py`. |
| `gate_failures(project_dir: Path) -> list[str]` | Run the verification set, collect failures. |
| `advisory_notes(project_dir: Path, plan: Plan, changed: set[str]) -> list[str]` | Non-blocking observations for the steps below the gate. |
| `notice(message: str) -> None` | Show the user a message without blocking. |
| `block(reason: str) -> None` | Emit the block decision and exit. |
| `enforce(project_dir: Path) -> None` | Run the verification set and block on failure. |
| `main() -> None` | Entry point: decide whether the turn may end. |
