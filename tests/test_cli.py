import io
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT, feed_xml, kreds_entry, overview_xml, write_directory

from dkvalg import ReplaySource, cli, load_election
from dkvalg.cli import main, run

STEP_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}  +(\d+)/(\d+)  (\S+) (.+)$"
)


def _run(
    argv: list[str] | None, sleeps: list[float] | None = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    waits = [] if sleeps is None else sleeps
    code = run(argv, out=out, err=err, sleep=waits.append)
    return code, out.getvalue(), err.getvalue()


def _step_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if STEP_LINE.match(line)]


# --- replay on the fixtures (A6, T6) -------------------------------------------


def test_replay_prints_one_line_per_step_ending_at_92_of_92(fixture_dir: Path) -> None:
    code, out, err = _run(["replay", str(fixture_dir), "--speed", "inf"])

    lines = _step_lines(out)
    assert code == 0
    assert err == ""
    assert len(lines) == 107
    assert STEP_LINE.match(lines[-1])
    assert "92/92" in lines[-1]


def test_replay_counted_column_rises_monotonically_to_92(fixture_dir: Path) -> None:
    _, out, _ = _run(["replay", str(fixture_dir), "--speed", "inf"])

    counted = []
    for line in _step_lines(out):
        match = STEP_LINE.match(line)
        assert match
        counted.append(int(match.group(1)))
        assert match.group(2) == "92"
    assert counted == sorted(counted)
    assert counted[0] <= 1
    assert counted[-1] == 92


def test_replay_step_lines_name_the_place_type_and_place(fixture_dir: Path) -> None:
    _, out, _ = _run(["replay", str(fixture_dir), "--speed", "inf"])

    assert any(" opstillingskreds 1.Østerbro" in line for line in _step_lines(out))
    assert any(" landsdel Hovedstaden" in line for line in _step_lines(out))
    assert _step_lines(out)[-1].endswith(
        ("country Hele landet", "tally Alle indberettede opstillingskredse")
    )


def test_replay_ends_with_the_national_table_and_uden_for_partier_last(
    fixture_dir: Path,
) -> None:
    _, out, _ = _run(["replay", str(fixture_dir), "--speed", "inf"])

    after_steps = out.splitlines()[107:]
    table = [line for line in after_steps if line.strip()]
    assert table[0].startswith("Hele landet:")
    rows = table[1:]
    assert len(rows) == 13
    assert rows[0].startswith("A  A. Socialdemokratiet")
    assert "21.9%" in rows[0]
    assert "779524" in rows[0]
    assert rows[0].rstrip().endswith("38")
    assert rows[-1].startswith("-  Uden for partier")
    assert "2420" in rows[-1]


def test_replay_never_calls_sleep_at_infinite_speed(fixture_dir: Path) -> None:
    waits: list[float] = []

    _run(["replay", str(fixture_dir), "--speed", "inf"], waits)

    assert waits == []


@pytest.mark.parametrize(
    "flag", ["--speed=inf", "--speed INF", "--speed Infinity", "--speed 1e400"]
)
def test_replay_accepts_the_spellings_of_infinity(fixture_dir: Path, flag: str) -> None:
    waits: list[float] = []

    code, _, err = _run(["replay", str(fixture_dir), *flag.split(" ")], waits)

    assert (code, err, waits) == (0, "", [])


def test_replay_default_speed_is_600_and_the_injected_sleep_is_used(
    fixture_dir: Path,
) -> None:
    waits: list[float] = []

    code, _, _ = _run(["replay", str(fixture_dir)], waits)

    assert code == 0
    assert waits
    expected: list[float] = []
    list(ReplaySource(load_election(fixture_dir), speed=600.0, sleep=expected.append))
    assert waits == expected


def test_replay_speed_argument_scales_the_waits(fixture_dir: Path) -> None:
    fast: list[float] = []
    slow: list[float] = []

    _run(["replay", str(fixture_dir), "--speed", "1200"], fast)
    _run(["replay", str(fixture_dir), "--speed", "600"], slow)

    assert [w * 2 for w in fast] == pytest.approx(slow)


def test_replay_last_speed_flag_wins(fixture_dir: Path) -> None:
    waits: list[float] = []

    code, _, _ = _run(
        ["replay", str(fixture_dir), "--speed", "5", "--speed", "inf"], waits
    )

    assert (code, waits) == (0, [])


def test_replay_twice_prints_the_same_output(fixture_dir: Path) -> None:
    argv = ["replay", str(fixture_dir), "--speed", "inf"]

    assert _run(argv) == _run(argv)


def test_replay_flushes_each_step_line(fixture_dir: Path) -> None:
    class Counting(io.StringIO):
        flushes = 0

        def flush(self) -> None:
            type(self).flushes += 1
            super().flush()

    out = Counting()

    run(["replay", str(fixture_dir), "--speed", "inf"], out=out, err=io.StringIO())

    assert Counting.flushes >= 107
    assert not out.closed


def test_replay_works_from_a_directory_with_spaces_and_unicode(
    fixture_copy: Path, tmp_path: Path
) -> None:
    moved = tmp_path / "valg æøå 2026"
    fixture_copy.rename(moved)

    code, out, _ = _run(["replay", str(moved), "--speed", "inf"])

    assert code == 0
    assert len(_step_lines(out)) == 107


# --- errors (A6, A7) ---------------------------------------------------------------


def _ep_directory(tmp_path: Path, fixture_dir: Path) -> Path:
    target = tmp_path / "ep"
    shutil.copytree(fixture_dir, target)
    overview = target / "valgdag.xml"
    overview.write_bytes(
        overview.read_bytes().replace(
            b"Folketingsvalg tirsdag 24. marts 2026", b"Europa-Parlamentsvalg 2024"
        )
    )
    return target


def _malformed(tmp_path: Path, fixture_dir: Path) -> Path:
    del fixture_dir
    return write_directory(tmp_path / "bad", b"<Data><broken")


def _missing_feed(tmp_path: Path, fixture_dir: Path) -> Path:
    del fixture_dir
    return write_directory(tmp_path / "gap", overview_xml([kreds_entry("20", "K")]))


def _empty(tmp_path: Path, fixture_dir: Path) -> Path:
    del fixture_dir
    target = tmp_path / "empty"
    target.mkdir()
    return target


def _nowhere(tmp_path: Path, fixture_dir: Path) -> Path:
    del fixture_dir
    return tmp_path / "nowhere"


def _a_file(tmp_path: Path, fixture_dir: Path) -> Path:
    del fixture_dir
    target = tmp_path / "plain.txt"
    target.write_text("x")
    return target


def _no_feeds(tmp_path: Path, fixture_dir: Path) -> Path:
    del fixture_dir
    return write_directory(tmp_path / "none", overview_xml([]))


@pytest.mark.parametrize(
    ("make", "needle"),
    [
        (_empty, "valgdag.xml"),
        (_nowhere, "valgdag.xml"),
        (_a_file, ""),
        (_ep_directory, "Europa-Parlamentsvalg"),
        (_malformed, "valgdag.xml"),
        (_missing_feed, "valgdag_20.xml"),
        (_no_feeds, "no result feeds"),
    ],
)
def test_replay_a_bad_directory_returns_1_with_the_error_on_stderr_only(
    tmp_path: Path, fixture_dir: Path, make: object, needle: str
) -> None:
    directory = make(tmp_path, fixture_dir)  # type: ignore[operator]  # the helpers above share a signature

    code, out, err = _run(["replay", str(directory), "--speed", "inf"])

    assert code == 1
    assert out == ""
    assert err.startswith("error: ")
    assert needle in err
    assert err.count("\n") == 1


def test_replay_a_malformed_feed_midway_prints_nothing_on_stdout(
    fixture_copy: Path,
) -> None:
    (fixture_copy / "valgdag_20.xml").write_bytes(b"<Data>")

    code, out, err = _run(["replay", str(fixture_copy), "--speed", "inf"])

    assert (code, out) == (1, "")
    assert "valgdag_20.xml" in err


@pytest.mark.parametrize("speed", ["0", "-1", "-inf", "nan", "abc", "", "1,5"])
def test_replay_a_bad_speed_returns_2_with_the_message_on_err(
    fixture_dir: Path, speed: str
) -> None:
    waits: list[float] = []

    code, out, err = _run(["replay", str(fixture_dir), "--speed", speed], waits)

    assert code == 2
    assert out == ""
    assert "--speed" in err
    assert "speed" in err.lower()
    assert waits == []


def test_replay_a_bad_speed_message_names_the_value(fixture_dir: Path) -> None:
    _, _, err = _run(["replay", str(fixture_dir), "--speed", "abc"])

    assert "abc" in err


def test_replay_speed_without_a_value_returns_2(fixture_dir: Path) -> None:
    code, out, err = _run(["replay", str(fixture_dir), "--speed"])

    assert (code, out) == (2, "")
    assert "expected one argument" in err


@pytest.mark.parametrize(
    "argv",
    [
        ["bogus"],
        ["replay"],
        ["replay", "dir", "extra"],
        ["replay", "dir", "--nope"],
        ["--speed", "5"],
    ],
)
def test_run_bad_argument_shapes_return_2_with_usage_on_err(argv: list[str]) -> None:
    code, out, err = _run(argv)

    assert code == 2
    assert out == ""
    assert "usage: dkvalg" in err


# --- no subcommand, help, never raises -----------------------------------------------


def test_run_without_arguments_prints_usage_to_out_and_returns_0() -> None:
    code, out, err = _run([])

    assert code == 0
    assert "usage: dkvalg" in out
    assert "replay" in out
    assert err == ""


@pytest.mark.parametrize(
    "argv", [["-h"], ["--help"], ["replay", "-h"], ["replay", "--help"]]
)
def test_run_help_returns_0_with_the_text_on_out(argv: list[str]) -> None:
    code, out, err = _run(argv)

    assert (code, err) == (0, "")
    assert "usage: dkvalg" in out


def test_run_with_no_argv_reads_sys_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["dkvalg"])

    code, out, _ = _run(None)

    assert code == 0
    assert "usage: dkvalg" in out


def test_run_with_injected_streams_writes_nothing_to_the_real_ones(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run(["bogus"])
    _run([])

    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")


def test_run_restores_sys_stdout_and_sys_stderr() -> None:
    before = (sys.stdout, sys.stderr)

    _run(["bogus"])
    _run(["replay", "nowhere"])

    assert (sys.stdout, sys.stderr) == before


def test_run_defaults_to_the_real_streams(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = run([])
    assert code == 0
    assert "usage: dkvalg" in capsys.readouterr().out

    code = run(["bogus"])
    assert code == 2
    assert "usage: dkvalg" in capsys.readouterr().err


def test_run_does_not_close_the_streams_it_is_given() -> None:
    out, err = io.StringIO(), io.StringIO()

    run([], out=out, err=err)

    assert not out.closed
    assert not err.closed


# --- table corners ----------------------------------------------------------------


def test_replay_of_an_all_unreported_overview_prints_no_steps_and_no_party_rows(
    tmp_path: Path,
) -> None:
    overview = overview_xml([kreds_entry("20", "K", senest=None, iso=None)])
    directory = write_directory(tmp_path, overview)

    code, out, err = _run(["replay", str(directory), "--speed", "inf"])

    assert (code, err) == (0, "")
    assert _step_lines(out) == []
    assert out.strip() == ""


def test_replay_prints_a_dash_for_a_letter_or_seat_the_feed_does_not_give(
    tmp_path: Path,
) -> None:
    overview = overview_xml(
        [
            '<Land SenestRettet="24-03-2026 22:00:00" SenestRettetIso="2026-03-24T22:00:00" '
            'land_id="0" filnavn="https://x/valgdag_0.xml">Hele landet</Land>'
        ]
    )
    directory = write_directory(tmp_path, overview, {"valgdag_0.xml": feed_xml()})

    code, out, _ = _run(["replay", str(directory), "--speed", "inf"])

    assert code == 0
    rows = [line for line in out.splitlines() if "%" in line]
    assert rows[0].startswith("A  A. Socialdemokratiet")
    assert rows[0].rstrip().endswith("-")
    assert rows[-1].startswith("-  Uden for partier")


def test_replay_with_a_partyless_country_prints_only_its_header(
    tmp_path: Path,
) -> None:
    overview = overview_xml(
        [
            '<Land SenestRettet="24-03-2026 22:00:00" SenestRettetIso="2026-03-24T22:00:00" '
            'land_id="0" filnavn="https://x/valgdag_0.xml">Hele landet</Land>'
        ]
    )
    feed = feed_xml(status="9", status_text="Fejl", stemmer=None)
    directory = write_directory(tmp_path, overview, {"valgdag_0.xml": feed})

    code, out, _ = _run(["replay", str(directory), "--speed", "inf"])

    assert code == 0
    assert out.strip().splitlines()[-1] == "Hele landet: Fejl"


def test_replay_to_an_ascii_stream_with_danish_names_raises_unicode_error() -> None:
    """Documented limitation: the caller supplies a stream that can encode the names."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="ascii")

    with pytest.raises(UnicodeEncodeError):
        run(
            [
                "replay",
                str(ROOT / "tests" / "fixtures" / "folketingsvalg_2026"),
                "--speed",
                "inf",
            ],
            out=out,
            err=io.StringIO(),
        )


# --- main and __main__ (A1, T1) -------------------------------------------------------


def test_main_exits_with_the_code_run_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["dkvalg"])

    with pytest.raises(SystemExit) as caught:
        main()

    assert caught.value.code == 0


def test_main_exits_with_2_for_bad_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["dkvalg", "bogus"])

    with pytest.raises(SystemExit) as caught:
        main()

    assert caught.value.code == 2


def test_module_run_as_main_prints_usage_and_exits_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["dkvalg"])

    with pytest.raises(SystemExit) as caught:
        runpy.run_module("dkvalg", run_name="__main__")

    assert caught.value.code == 0
    assert "usage: dkvalg" in capsys.readouterr().out


def test_python_dash_m_dkvalg_works_without_the_editable_install() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "dkvalg"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT / "src")},
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0
    assert "usage: dkvalg" in result.stdout
    assert result.stderr == ""


def test_python_dash_m_dkvalg_replay_a_missing_directory_exits_1_with_an_error() -> (
    None
):
    result = subprocess.run(
        [sys.executable, "-m", "dkvalg", "replay", "no-such-directory"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT / "src")},
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: ")


def test_python_dash_m_dkvalg_replay_runs_the_fixtures_end_to_end() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "dkvalg",
            "replay",
            "tests/fixtures/folketingsvalg_2026",
            "--speed",
            "inf",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"},
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0
    assert "92/92" in result.stdout
    assert "Uden for partier" in result.stdout


def test_cli_module_exposes_run_and_main() -> None:
    assert cli.run is run
    assert cli.main is main
