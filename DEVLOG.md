# Devlog

One entry per version, newest first: what changed, then the files it touched. `/finish`
writes each entry in the commit that opens the pull request.

## 1.3.1 — 2026-11-09

Replaces the ten-step plan-file pipeline with the one from `petermads123/template` 0.2.0:
features are agreed in `/feature`, split into rounds that each run as the `round` workflow on
their own branch, bugs start in `/fix` with a diagnosis, and `/finish` writes the version,
`STRUCTURE.md`, `README.md` and `DEVLOG.md` and opens the pull request. A round runs only the
tests its change can affect (`select_tests.py`); CI runs the whole suite plus `check_sync.py`
on every pull request. The old skills, agents, `plan_state.py`, `stop_gate.py` and their tests
are gone; the numbered plan files under `development/feat/` stay as history. No package code
changed.

Files:
- `.claude/skills/` — `feature`, `fix`, `round`, `finish` (the fourteen old skills removed)
- `.claude/agents/` — the seventeen pipeline agents; `.claude/workflows/` — `diagnose.js`, `round.js`, `final.js`
- `.claude/hooks/` — `dev_state.py`, `session_brief.py`, `check_sync.py`, `select_tests.py`, `guard_git.py`, `lint_py.py` (`plan_state.py`, `stop_gate.py` removed)
- `.claude/settings.json`, `.claude/rules/python.md`, `.github/workflows/check.yml`
- `tests/test_dev_state.py`, `test_session_brief.py`, `test_check_sync.py`, `test_select_tests.py`, `test_guard_git.py` (`test_plan_state.py`, `test_stop_gate.py` removed)
- `development/README.md` (`development/TEMPLATE.md` removed)
- `CLAUDE.md`, `STRUCTURE.md`, `README.md`, `DEVLOG.md`, `DEVELOPMENT.md`, `pyproject.toml`

## 1.3.0 — 2026-11-06

Adds the Folkeafstemning (referendum) adapter: the answers `JA` and `NEJ` are carried as
seatless party results, `parse_any_overview` recognises the third election type, and the
national table of the CLI widens its letter column for the longer answers. Fixtures for the
referenda of 2022, 2015 and 2009 are added. Earlier versions (1.0.0 to 1.2.0) were recorded
in the plan files under `development/feat/`, not here.

Files:
- `src/dkvalg/adapters/folkeafstemning.py`, `registry.py`, `model.py`, `diff.py`, `cli.py`
- `tests/test_folkeafstemning.py`, `tests/fixtures/folkeafstemning_*/`
- `README.md`, `STRUCTURE.md`, `pyproject.toml`
