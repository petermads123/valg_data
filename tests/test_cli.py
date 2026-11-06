import io
import re
import runpy
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest
from conftest import (
    EP_ELECTION_NAME,
    LATER_ISO,
    NATIONAL,
    OVERVIEW,
    ROOT,
    FakeClock,
    FakeTransport,
    entry,
    feed_xml,
    fixture_files,
    kreds_entry,
    overview_xml,
    utc,
    write_directory,
)

from dkvalg import (
    CaptureReplay,
    Election,
    FetchError,
    HttpSource,
    PlaceType,
    Recorder,
    ReplaySource,
    cli,
    load_election,
)
from dkvalg.cli import main, run
from dkvalg.sources.http_source import HttpResponse

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
            b"Folketingsvalg tirsdag 24. marts 2026", b"Kommunalvalg 2025"
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
        (_ep_directory, "Kommunalvalg"),
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


# --- poll (A5, A7, T9) ----------------------------------------------------------------

POLL_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\+00:00  +(\d+)/(\d+)  (\S+) (.+)$"
)
THREE = [NATIONAL, "valgdag_20.xml", "valgdag_7.xml"]


def _poll(
    argv: list[str],
    transport: FakeTransport | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[int, str, str, list[float], FakeTransport]:
    transport = FakeTransport() if transport is None else transport
    out, err = io.StringIO(), io.StringIO()
    sleeps: list[float] = []

    def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if sleep is not None:
            sleep(seconds)

    code = run(
        argv,
        out=out,
        err=err,
        sleep=record_sleep,
        transport=transport,
        clock=FakeClock() if clock is None else clock,
    )
    return code, out.getvalue(), err.getvalue(), sleeps, transport


def _poll_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if POLL_LINE.match(line)]


def test_poll_prints_a_line_per_changed_place_for_the_first_cycle_only() -> None:
    code, out, err, sleeps, _ = _poll(["poll", "Valg2546527", "--cycles", "2"])

    assert (code, err) == (0, "")
    assert len(_poll_lines(out)) == 107
    assert len(out.splitlines()) == 107
    assert sleeps == [60.0]


def test_poll_lines_carry_the_fetch_time_progress_type_and_name() -> None:
    _, out, _, _, _ = _poll(["poll", "Valg2546527", "--cycles", "1"])

    match = POLL_LINE.match(out.splitlines()[0])
    assert match
    assert out.splitlines()[0].startswith("2026-03-24 20:00:00+00:00")
    assert {POLL_LINE.match(line).group(1) for line in out.splitlines()} == {"92"}  # type: ignore[union-attr]  # every line matches
    assert "landsdel Hovedstaden" in out
    assert "country Hele landet" in out


def test_poll_shows_only_the_places_that_changed_in_a_later_cycle() -> None:
    transport = FakeTransport()
    touched = {"done": False}

    def after_first_wait(_seconds: float) -> None:
        if not touched["done"]:
            touched["done"] = True
            transport.touch(THREE)

    code, out, _, _, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "2"], transport, sleep=after_first_wait
    )

    lines = out.splitlines()
    assert code == 0
    assert len(lines) == 107 + 3
    assert all(line.startswith("2026-03-24 20:01:00+00:00") for line in lines[107:])
    assert {line.split("  ")[-1] for line in lines[107:]} == {
        "landsdel Hovedstaden",
        "country Hele landet",
        "opstillingskreds 1.Østerbro",
    }


def test_poll_without_cycles_runs_until_interrupted() -> None:
    seen = {"n": 0}

    def interrupt_on_third(_seconds: float) -> None:
        seen["n"] += 1
        if seen["n"] == 3:
            raise KeyboardInterrupt

    code, out, err, sleeps, _ = _poll(["poll", "Valg2546527"], sleep=interrupt_on_third)

    assert code == 130
    assert "Traceback" not in err
    assert len(sleeps) == 3
    assert len(_poll_lines(out)) == 107  # the lines printed so far stay


@pytest.mark.parametrize(
    ("flag", "expected"), [("15", 15.0), ("90", 90.0), ("15.5", 15.5)]
)
def test_poll_interval_is_the_wait_between_cycles(flag: str, expected: float) -> None:
    _, _, _, sleeps, _ = _poll(
        ["poll", "Valg2546527", "--interval", flag, "--cycles", "2"]
    )

    assert sleeps == [expected]


def test_poll_default_interval_is_60_seconds() -> None:
    _, _, _, sleeps, _ = _poll(["poll", "Valg2546527", "--cycles", "2"])

    assert sleeps == [60.0]


def test_poll_one_cycle_never_sleeps() -> None:
    code, _, _, sleeps, _ = _poll(["poll", "Valg2546527", "--cycles", "1"])

    assert (code, sleeps) == (0, [])


@pytest.mark.parametrize(
    "interval", ["5", "14.9", "0", "-5", "nan", "inf", "-inf", "abc", "", "1e999"]
)
def test_poll_a_bad_interval_exits_2_with_the_reason_on_err(interval: str) -> None:
    code, out, err, _, transport = _poll(
        ["poll", "Valg2546527", "--interval", interval]
    )

    assert code == 2
    assert out == ""
    assert "interval" in err
    assert transport.requests == []


def test_poll_a_bad_interval_message_names_the_value() -> None:
    _, _, err, _, _ = _poll(["poll", "Valg2546527", "--interval", "14.9"])

    assert "14.9" in err


@pytest.mark.parametrize("cycles", ["0", "-1", "1.5", "abc", ""])
def test_poll_a_bad_cycle_count_exits_2(cycles: str) -> None:
    code, out, err, _, transport = _poll(["poll", "Valg2546527", "--cycles", cycles])

    assert code == 2
    assert out == ""
    assert "cycle" in err
    assert transport.requests == []


def test_poll_without_a_location_exits_2() -> None:
    code, _, err, _, _ = _poll(["poll"])

    assert code == 2
    assert "location" in err


@pytest.mark.parametrize(
    "location",
    [
        "file:///x/valgdag.xml",
        "ftp://x/",
        "https://h/x?y=1",
        "https://u:p@h/x/",
        "Valg 1",
        "",
    ],
)
def test_poll_a_bad_location_exits_2_with_error_on_err_and_touches_nothing(
    location: str,
) -> None:
    code, out, err, _, transport = _poll(["poll", location])

    assert code == 2
    assert out == ""
    assert err.startswith("error: ")
    assert transport.requests == []


def test_poll_accepts_a_folder_url_and_a_file_url_location() -> None:
    for location in [
        "https://www.dst.dk/valg/Valg2546527/xml/",
        "https://www.dst.dk/valg/Valg2546527/xml/valgdag.xml",
    ]:
        code, out, _, _, _ = _poll(["poll", location, "--cycles", "1"])

        assert code == 0
        assert len(_poll_lines(out)) == 107


def test_poll_exits_1_when_the_last_cycle_failed_with_error_on_stderr_only() -> None:
    transport = FakeTransport()
    transport.script(OVERVIEW, FetchError("https://x/valgdag.xml: HTTP status 503"))

    code, out, err, sleeps, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "1"], transport
    )

    assert code == 1
    assert out == ""
    assert err == "error: https://x/valgdag.xml: HTTP status 503\n"
    assert sleeps == []


def test_poll_exits_0_when_an_early_cycle_failed_but_the_last_succeeded() -> None:
    transport = FakeTransport()
    transport.script(OVERVIEW, FetchError("boom"))

    code, out, err, sleeps, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "2"], transport
    )

    assert code == 0
    assert err.count("error: ") == 1
    assert len(_poll_lines(out)) == 107
    assert sleeps == [120.0]  # one failure backs off to twice the interval


def test_poll_exits_1_when_a_success_is_followed_by_a_failure() -> None:
    transport = FakeTransport()

    def fail_next(_seconds: float) -> None:
        transport.script(OVERVIEW, FetchError("down"))

    code, out, err, _, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "2"], transport, sleep=fail_next
    )

    assert code == 1
    assert len(_poll_lines(out)) == 107
    assert "error: down" in err


def test_poll_a_failed_cycle_prints_nothing_on_stdout() -> None:
    transport = FakeTransport()
    transport.script(OVERVIEW, FetchError("one"), FetchError("two"))

    _, out, err, sleeps, _ = _poll(["poll", "Valg2546527", "--cycles", "2"], transport)

    assert out == ""
    assert err.splitlines() == ["error: one", "error: two"]
    assert sleeps == [120.0]


def test_poll_a_malformed_overview_is_reported_and_the_loop_continues() -> None:
    transport = FakeTransport()
    transport.script(OVERVIEW, HttpResponse(200, {}, b"<Data><broken"))

    code, _, err, _, _ = _poll(["poll", "Valg2546527", "--cycles", "2"], transport)

    assert code == 0
    assert "malformed" in err


def test_poll_record_writes_one_capture_folder_per_poll_that_received_a_body(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    capture = tmp_path / "cap"

    def touch(_seconds: float) -> None:
        if len(list(capture.iterdir())) == 1:
            transport.touch(THREE)

    code, _, _, _, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "3", "--record", str(capture)],
        transport,
        sleep=touch,
    )

    folders = sorted(p.name for p in capture.iterdir())
    assert code == 0
    assert folders == [
        "20260324T200000.000000Z",
        "20260324T200100.000000Z",
    ]  # cycle 3 was a 304
    assert len(list((capture / folders[0]).iterdir())) == 108
    assert len(list((capture / folders[1]).iterdir())) == 4


def test_poll_record_creates_the_directory_with_its_parents(tmp_path: Path) -> None:
    capture = tmp_path / "a" / "b" / "cap"

    code, _, _, _, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "1", "--record", str(capture)]
    )

    assert code == 0
    assert capture.is_dir()


def test_poll_record_to_a_path_that_is_a_file_fails_every_cycle(tmp_path: Path) -> None:
    blocker = tmp_path / "cap"
    blocker.write_bytes(b"x")

    code, out, err, _, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "2", "--record", str(blocker)]
    )

    assert code == 1
    assert out == ""
    assert err.count("error: cannot write capture") == 2


def test_poll_without_record_writes_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    _poll(["poll", "Valg2546527", "--cycles", "1"])

    assert list(tmp_path.iterdir()) == []


def test_poll_what_it_records_replays_to_the_polled_election(tmp_path: Path) -> None:
    transport = FakeTransport()
    capture = tmp_path / "cap"
    touched = {"done": False}

    def touch(_seconds: float) -> None:
        if not touched["done"]:
            touched["done"] = True
            transport.touch(THREE)

    _poll(
        ["poll", "Valg2546527", "--cycles", "2", "--record", str(capture)],
        transport,
        sleep=touch,
    )

    steps = list(CaptureReplay(capture, speed=float("inf")))
    assert len(steps) == 2
    assert steps[-1].election == load_election(transport.write_to(tmp_path / "now"))


def test_poll_help_lists_its_options() -> None:
    code, out, _, _, _ = _poll(["poll", "--help"])

    assert code == 0
    for option in ("--interval", "--record", "--cycles", "location"):
        assert option in out


def test_the_top_level_help_names_both_subcommands() -> None:
    code, out, _ = _run(["--help"])

    assert code == 0
    assert "replay" in out
    assert "poll" in out


def test_python_dash_m_dkvalg_poll_a_bad_location_exits_2_without_a_network() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "dkvalg", "poll", "file:///x"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONPATH": str(ROOT / "src")},
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 2
    assert result.stderr.startswith("error: ")
    assert result.stdout == ""


# --- replay on a capture directory (A6, A7, T9) --------------------------------------


def _capture(tmp_path: Path) -> Path:
    """Record two polls: everything, then the national feed and two others."""
    transport = FakeTransport()
    capture = tmp_path / "cap"
    touched = {"done": False}

    def touch(_seconds: float) -> None:
        if not touched["done"]:
            touched["done"] = True
            transport.touch(THREE)

    _poll(
        ["poll", "Valg2546527", "--cycles", "2", "--record", str(capture)],
        transport,
        sleep=touch,
    )
    return capture


def test_replay_of_a_capture_directory_prints_the_changed_places_per_step_and_the_table(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)

    code, out, err = _run(["replay", str(capture), "--speed", "inf"])

    assert (code, err) == (0, "")
    lines = _poll_lines(
        out
    )  # capture times are timezone-aware UTC, so they print +00:00
    assert len(lines) == 107 + 3
    assert lines[0].startswith("2026-03-24 20:00:00+00:00")
    assert lines[-1].startswith("2026-03-24 20:01:00+00:00")
    assert "Uden for partier" in out


def test_replay_of_a_capture_directory_sleeps_the_fetch_gap_divided_by_speed(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)
    sleeps: list[float] = []

    code, _, _ = _run(["replay", str(capture), "--speed", "30"], sleeps)

    assert code == 0
    assert sleeps == [2.0]


def test_replay_of_a_capture_directory_ends_with_the_final_national_table(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)
    final = list(CaptureReplay(capture, speed=float("inf")))[-1].election
    country = final.of_type(cli.PlaceType.COUNTRY)[0]

    _, out, _ = _run(["replay", str(capture), "--speed", "inf"])

    assert f"{country.name}: " in out
    assert str(country.parties[0].votes) in out


def test_replay_of_a_plain_directory_is_unchanged_by_capture_support(
    fixture_dir: Path,
) -> None:
    code, out, _ = _run(["replay", str(fixture_dir), "--speed", "inf"])

    assert code == 0
    assert len(_step_lines(out)) == 107
    assert POLL_LINE.match(out.splitlines()[0]) is None  # the round 1 time format


def test_replay_of_a_directory_with_both_an_overview_and_capture_folders_uses_the_plain_path(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)
    for name, body in fixture_files().items():
        (capture / name).write_bytes(body)

    code, out, _ = _run(["replay", str(capture), "--speed", "inf"])

    assert code == 0
    assert len(_step_lines(out)) == 107


def test_replay_of_a_nonexistent_capture_style_directory_exits_1_with_error(
    tmp_path: Path,
) -> None:
    code, out, err = _run(["replay", str(tmp_path / "nowhere"), "--speed", "inf"])

    assert (code, out) == (1, "")
    assert err.startswith("error: ")


def test_replay_of_a_capture_with_a_broken_folder_exits_1_naming_the_folder(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)
    (capture / "20261301T000000.000000Z").mkdir()

    code, out, err = _run(["replay", str(capture), "--speed", "inf"])

    assert code == 1
    assert out == ""
    assert "20261301T000000.000000Z" in err


def test_replay_of_a_capture_with_an_incomplete_first_folder_exits_1(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "cap"
    Recorder(capture).record(
        datetime.fromisoformat("2026-03-24T20:00:00+00:00"),
        {OVERVIEW: fixture_files()[OVERVIEW]},
    )

    code, out, err = _run(["replay", str(capture), "--speed", "inf"])

    assert code == 1
    assert out == ""
    assert "20260324T200000.000000Z" in err


def test_replay_of_a_directory_whose_only_capture_like_entry_is_a_file_takes_the_plain_path(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "odd"
    directory.mkdir()
    (directory / "20260324T200000.000000Z").write_bytes(b"x")

    code, _, err = _run(["replay", str(directory), "--speed", "inf"])

    assert code == 1
    assert "valgdag.xml" in err


def test_replay_of_a_capture_directory_shows_the_earlier_national_figures_first(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)
    first, second = list(CaptureReplay(capture, speed=float("inf")))
    before = first.election.of_type(cli.PlaceType.COUNTRY)[0]
    after = second.election.of_type(cli.PlaceType.COUNTRY)[0]

    assert before.valid_votes != after.valid_votes


# --- round 3: --diff (A8, T8) and EP on the CLI ----------------------------------------

DIFF_LINE = re.compile(r"^\S+ \S+  (leader|seats|status|progress) ")
LEADER_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\+00:00)?  leader (\S+) (.+): (\S+) -> (\S+)$"
)
PROGRESS_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\+00:00)?  progress \d+/\d+ -> \d+/\d+$"
)


def _diff_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if DIFF_LINE.match(line)]


def _without_diff_lines(text: str) -> str:
    return "".join(
        line for line in text.splitlines(keepends=True) if not DIFF_LINE.match(line)
    )


def _stemmer(
    a_votes: int, f_votes: int, a_seats: int | None = None, f_seats: int | None = None
) -> str:
    def party(party_id: str, letter: str, votes: int, seats: int | None) -> str:
        seat_attr = "" if seats is None else f' Mandater="{seats}"'
        return (
            f'<Parti Id="{party_id}" Bogstav="{letter}" Navn="{letter}. Parti"'
            f'{seat_attr} StemmerAntal="{votes}" StemmerPct="{votes / 10}" />\n'
        )

    total = a_votes + f_votes
    return (
        party("5891", "A", a_votes, a_seats)
        + party("5897", "F", f_votes, f_seats)
        + f"<IAltGyldigeStemmer>{total}</IAltGyldigeStemmer>\n"
        "<BlankeStemmer>0</BlankeStemmer>\n"
        "<AndreUgyldigeStemmer>0</AndreUgyldigeStemmer>\n"
        "<IAltUgyldigeStemmer>0</IAltUgyldigeStemmer>\n"
        f"<IAltAfgivneStemmer>{total}</IAltAfgivneStemmer>\n"
    )


def _synthetic_step(
    recorder: Recorder,
    at: str,
    stamp: str,
    country: tuple[int, int, int | None, int | None],
    kreds: tuple[int, int] | None,
    *,
    name: str | None = None,
) -> None:
    """Record one capture folder: a country and (unless `None`) a kreds, both stamped."""
    iso = f"2026-03-24T{stamp}"
    entries = [
        entry(
            "Land", "Hele landet", "valgdag_0.xml", land_id="0", iso=iso, senest=None
        ),
        kreds_entry("20", "Østerbro", iso=iso, senest=None),
    ]
    feeds = {
        "valgdag_0.xml": feed_xml(stemmer=_stemmer(*country), iso=iso, senest=None),
        "valgdag_20.xml": (
            feed_xml(
                status="9",
                status_text="Fejl",
                stemmer=None,
                eligible=None,
                turnout=None,
                iso=iso,
                senest=None,
            )
            if kreds is None
            else feed_xml(stemmer=_stemmer(*kreds), iso=iso, senest=None)
        ),
    }
    overview = (
        overview_xml(entries) if name is None else overview_xml(entries, name=name)
    )
    recorder.record(utc(f"2026-03-24T{at}"), {OVERVIEW: overview, **feeds})


def _synthetic_capture(root: Path) -> Path:
    """Three polls: a first count, seats appearing, then seats moving with a status fall."""
    recorder = Recorder(root)
    _synthetic_step(recorder, "20:00:00", "22:00:00", (600, 400, None, None), (60, 40))
    _synthetic_step(recorder, "20:01:00", "22:05:00", (600, 400, 3, 2), (60, 40))
    _synthetic_step(recorder, "20:02:00", "22:10:00", (600, 700, 4, 1), None)
    return root


def test_replay_diff_on_a_synthetic_capture_prints_the_documented_lines_in_order(
    tmp_path: Path,
) -> None:
    capture = _synthetic_capture(tmp_path / "cap")

    code, out, err = _run(["replay", str(capture), "--speed", "inf", "--diff"])

    assert (code, err) == (0, "")
    assert _diff_lines(out) == [
        "2026-03-24 20:00:00+00:00  leader country Hele landet: - -> A",
        "2026-03-24 20:00:00+00:00  progress 0/1 -> 1/1",
        "2026-03-24 20:01:00+00:00  seats country Hele landet: A - -> 3",
        "2026-03-24 20:01:00+00:00  seats country Hele landet: F - -> 2",
        "2026-03-24 20:02:00+00:00  seats country Hele landet: A 3 -> 4",
        "2026-03-24 20:02:00+00:00  seats country Hele landet: F 2 -> 1",
        "2026-03-24 20:02:00+00:00  leader country Hele landet: A -> F",
        "2026-03-24 20:02:00+00:00  status opstillingskreds Østerbro: PRELIMINARY -> ERROR",
        "2026-03-24 20:02:00+00:00  progress 1/1 -> 0/1",
    ]


def test_replay_diff_places_the_diff_lines_after_each_steps_place_lines(
    tmp_path: Path,
) -> None:
    capture = _synthetic_capture(tmp_path / "cap")

    _, out, _ = _run(["replay", str(capture), "--speed", "inf", "--diff"])

    lines = out.splitlines()
    first_diff = next(i for i, line in enumerate(lines) if DIFF_LINE.match(line))
    assert [bool(DIFF_LINE.match(line)) for line in lines[:first_diff]] == [
        False
    ] * first_diff
    assert first_diff == 2  # the first step's two place lines come first


def test_replay_diff_without_the_flag_prints_none_of_those_lines(
    tmp_path: Path,
) -> None:
    capture = _synthetic_capture(tmp_path / "cap")

    _, out, _ = _run(["replay", str(capture), "--speed", "inf"])

    assert _diff_lines(out) == []


def test_replay_diff_a_votes_only_change_prints_no_line(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path / "cap")
    _synthetic_step(recorder, "20:00:00", "22:00:00", (600, 400, 3, 2), (60, 40))
    _synthetic_step(recorder, "20:01:00", "22:05:00", (650, 450, 3, 2), (60, 40))

    _, out, _ = _run(["replay", str(tmp_path / "cap"), "--speed", "inf", "--diff"])

    assert [line.split("  ", 1)[1] for line in _diff_lines(out)] == [
        "leader country Hele landet: - -> A",
        "progress 0/1 -> 1/1",
    ]


def test_replay_diff_a_dash_stands_for_an_empty_letter(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path / "cap")
    iso = "2026-03-24T22:00:00"
    stemmer = (
        '<Parti Id="5891" Navn="Uden bogstav" StemmerAntal="9" StemmerPct="9.0" />\n'
        "<IAltGyldigeStemmer>9</IAltGyldigeStemmer>\n"
    )
    recorder.record(
        utc("2026-03-24T20:00:00"),
        {
            OVERVIEW: overview_xml(
                [
                    entry(
                        "Land",
                        "Hele landet",
                        "valgdag_0.xml",
                        land_id="0",
                        iso=iso,
                        senest=None,
                    )
                ]
            ),
            "valgdag_0.xml": feed_xml(stemmer=stemmer, iso=iso, senest=None),
        },
    )

    _, out, _ = _run(["replay", str(tmp_path / "cap"), "--speed", "inf", "--diff"])

    assert _diff_lines(out)[0].endswith("leader country Hele landet: - -> -")


@pytest.mark.parametrize("flag_after", [True, False])
def test_diff_flag_is_accepted_before_or_after_the_positional(
    fixture_dir: Path, flag_after: bool
) -> None:
    argv = ["replay", str(fixture_dir), "--speed", "inf"]
    argv = [*argv, "--diff"] if flag_after else ["replay", "--diff", *argv[1:]]

    code, out, err = _run(argv)

    assert (code, err) == (0, "")
    assert _diff_lines(out)


@pytest.mark.parametrize(
    "argv",
    [
        ["--diff", "replay", "x"],
        ["replay", "x", "--diff=1"],
        ["poll", "Valg1", "--diff=1"],
    ],
)
def test_diff_misuse_exits_2_with_usage_on_err(argv: list[str]) -> None:
    code, out, err = _run(argv)

    assert code == 2
    assert out == ""
    assert "usage:" in err


def test_replay_and_poll_help_list_the_diff_option() -> None:
    for command in ("replay", "poll"):
        code, out, _ = _run([command, "--help"])

        assert code == 0
        assert "--diff" in out


# --- --diff on the real fixtures --------------------------------------------------------


@pytest.mark.parametrize("fixture_name", ["fixture_dir", "ep_fixture_dir"])
def test_replay_output_without_the_flag_equals_the_diff_output_minus_the_diff_lines(
    request: pytest.FixtureRequest, fixture_name: str
) -> None:
    directory: Path = request.getfixturevalue(fixture_name)
    _, plain, _ = _run(["replay", str(directory), "--speed", "inf"])

    code, with_diff, err = _run(["replay", str(directory), "--speed", "inf", "--diff"])

    assert (code, err) == (0, "")
    assert _without_diff_lines(with_diff) == plain
    assert _diff_lines(plain) == []
    assert len(_diff_lines(with_diff)) > 100


@pytest.mark.parametrize(
    ("fixture_name", "letter"), [("fixture_dir", "A"), ("ep_fixture_dir", "F")]
)
def test_replay_diff_leader_lines_are_only_country_landsdel_and_storkreds(
    request: pytest.FixtureRequest, fixture_name: str, letter: str
) -> None:
    directory: Path = request.getfixturevalue(fixture_name)

    _, out, _ = _run(["replay", str(directory), "--speed", "inf", "--diff"])

    leaders = [m for line in _diff_lines(out) if (m := LEADER_LINE.match(line))]
    assert {m.group(2) for m in leaders} == {"country", "landsdel", "storkreds"}
    assert len(leaders) == 1 + 3 + 10
    assert f"leader country Hele landet: - -> {letter}" in out
    assert "leader opstillingskreds" not in out
    assert "leader tally" not in out


def test_replay_diff_ends_with_the_progress_line_92_of_92_before_the_table(
    fixture_dir: Path,
) -> None:
    _, out, _ = _run(["replay", str(fixture_dir), "--speed", "inf", "--diff"])

    progress = [line for line in out.splitlines() if " progress " in line]
    assert len(progress) == 92
    assert progress[0].endswith("progress 0/92 -> 1/92")
    assert progress[-1].endswith("progress 91/92 -> 92/92")
    assert all(PROGRESS_LINE.match(line) for line in progress)


def test_replay_diff_on_the_fixtures_prints_no_seats_or_status_lines(
    fixture_dir: Path,
) -> None:
    # In a replay of finished files seats arrive together with the count, which is
    # PlaceCounted + LeaderChanged and no PartyResultChanged: no seats line (pinned).
    _, out, _ = _run(["replay", str(fixture_dir), "--speed", "inf", "--diff"])

    assert "  seats " not in out
    assert "  status " not in out


def test_replay_diff_on_ep_prints_no_seats_lines_and_ends_with_sf_nationally(
    ep_fixture_dir: Path,
) -> None:
    _, out, _ = _run(["replay", str(ep_fixture_dir), "--speed", "inf", "--diff"])

    assert "  seats " not in out
    assert out.count("leader country") == 1
    assert "leader country Hele landet: - -> F" in out


def test_replay_diff_of_a_recorded_capture_agrees_with_the_plain_replay(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)
    _, plain, _ = _run(["replay", str(capture), "--speed", "inf"])

    code, with_diff, err = _run(["replay", str(capture), "--speed", "inf", "--diff"])

    assert (code, err) == (0, "")
    assert _without_diff_lines(with_diff) == plain
    progress = [line for line in with_diff.splitlines() if " progress " in line]
    assert progress == [
        "2026-03-24 20:00:00+00:00  progress 0/92 -> 92/92",
    ]
    assert "20:01:00+00:00  leader" not in with_diff


# --- --diff on poll ---------------------------------------------------------------------


def test_poll_diff_first_cycle_prints_progress_and_leaders_at_three_levels() -> None:
    code, out, err, _, _ = _poll(["poll", "Valg2546527", "--cycles", "1", "--diff"])

    diff = _diff_lines(out)
    assert (code, err) == (0, "")
    assert "2026-03-24 20:00:00+00:00  progress 0/92 -> 92/92" in diff
    leaders = [m for line in diff if (m := LEADER_LINE.match(line))]
    assert len(leaders) == 14
    assert {m.group(2) for m in leaders} == {"country", "landsdel", "storkreds"}
    assert all(line.startswith("2026-03-24 20:00:00+00:00") for line in diff)


def test_poll_diff_output_minus_the_diff_lines_equals_the_plain_poll_output() -> None:
    _, plain, _, _, _ = _poll(["poll", "Valg2546527", "--cycles", "2"])

    _, with_diff, _, _, _ = _poll(["poll", "Valg2546527", "--cycles", "2", "--diff"])

    assert _without_diff_lines(with_diff) == plain
    assert _diff_lines(plain) == []


def test_poll_diff_an_unchanged_cycle_prints_no_lines_at_all() -> None:
    _, out, _, _, _ = _poll(["poll", "Valg2546527", "--cycles", "2", "--diff"])

    assert "20:01:00" not in out


def test_poll_diff_prints_a_seat_change_from_a_later_cycle() -> None:
    transport = FakeTransport()
    seen = {"n": 0}

    def after_first_wait(_seconds: float) -> None:
        seen["n"] += 1
        if seen["n"] == 1:
            body = transport.files[NATIONAL].replace(
                b'Mandater="38"', b'Mandater="39"', 1
            )
            transport.publish(NATIONAL, body)
            transport.touch([NATIONAL], bump=False)

    _, out, _, _, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "2", "--diff"],
        transport,
        sleep=after_first_wait,
    )

    assert _diff_lines(out)[-1] == (
        "2026-03-24 20:01:00+00:00  seats country Hele landet: A 38 -> 39"
    )
    assert len([line for line in _diff_lines(out) if "20:01:00" in line]) == 1


def test_poll_diff_a_failed_cycle_prints_no_diff_lines_and_the_next_diffs_against_the_last_good_one() -> (
    None
):
    transport = FakeTransport()
    steps = {"n": 0}

    def script(_seconds: float) -> None:
        steps["n"] += 1
        if steps["n"] == 1:
            transport.script(OVERVIEW, FetchError("down"))
        elif steps["n"] == 2:
            transport.touch(THREE)

    code, out, err, _, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "3", "--diff"], transport, sleep=script
    )

    stamps = {line.split("  ")[0] for line in _diff_lines(out)}
    assert (code, err) == (0, "error: down\n")
    assert stamps == {
        "2026-03-24 20:00:00+00:00"
    }  # nothing for the failed or later cycles
    assert "20:01:00" not in out
    assert any(
        line.startswith("2026-03-24 20:02:00+00:00") for line in out.splitlines()
    )


def test_poll_diff_a_first_cycle_failure_then_success_diffs_against_none() -> None:
    transport = FakeTransport()
    transport.script(OVERVIEW, FetchError("down"))

    _, out, err, _, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "2", "--diff"], transport
    )

    assert err == "error: down\n"
    assert "2026-03-24 20:01:00+00:00  progress 0/92 -> 92/92" in out


def test_poll_diff_ep_first_cycle_has_leader_f_and_no_seat_lines(
    ep_transport: FakeTransport,
) -> None:
    code, out, err, _, _ = _poll(
        ["poll", "Valg2546524", "--cycles", "1", "--diff"], ep_transport
    )

    assert (code, err) == (0, "")
    assert "leader country Hele landet: - -> F" in out
    assert "  seats " not in out
    assert "progress 0/92 -> 92/92" in out


def test_poll_uses_aware_utc_times_while_replay_prints_naive_local_time(
    fixture_dir: Path,
) -> None:
    _, polled, _, _, _ = _poll(["poll", "Valg2546527", "--cycles", "1", "--diff"])
    _, replayed, _ = _run(["replay", str(fixture_dir), "--speed", "inf", "--diff"])

    assert all(line.split("  ")[0].endswith("+00:00") for line in polled.splitlines())
    assert not any(
        "+00:00" in line.split("  ")[0] for line in replayed.splitlines()[:-20]
    )


# --- --diff with two elections in one run (decision C5) ---------------------------------


def _mixed_capture(root: Path) -> Path:
    recorder = Recorder(root)
    _synthetic_step(recorder, "20:00:00", "22:00:00", (600, 400, None, None), (60, 40))
    _synthetic_step(
        recorder,
        "20:01:00",
        "22:05:00",
        (600, 400, None, None),
        (60, 40),
        name=EP_ELECTION_NAME,
    )
    return root


def test_replay_diff_of_a_capture_mixing_two_elections_exits_1_with_an_error(
    tmp_path: Path,
) -> None:
    capture = _mixed_capture(tmp_path / "cap")

    code, out, err = _run(["replay", str(capture), "--speed", "inf", "--diff"])

    assert code == 1
    assert err.startswith("error: cannot diff folketingsvalg 2026-03-24 against ")
    assert "europaparlamentsvalg" in err
    assert "Traceback" not in err
    # the step's place lines print before its diff is attempted; no diff line follows
    assert not [line for line in _diff_lines(out) if "20:01:00" in line]


def test_replay_of_a_capture_mixing_two_elections_works_without_the_flag(
    tmp_path: Path,
) -> None:
    capture = _mixed_capture(tmp_path / "cap")

    code, _, err = _run(["replay", str(capture), "--speed", "inf"])

    assert (code, err) == (0, "")


def test_poll_diff_an_election_that_changes_type_mid_run_exits_1_with_an_error() -> (
    None
):
    transport = FakeTransport()

    def switch_election(_seconds: float) -> None:
        overview = transport.files[OVERVIEW].replace(
            b"Folketingsvalg tirsdag", b"Europa-Parlamentsvalg tirsdag"
        )
        transport.publish(OVERVIEW, overview)
        transport.touch([NATIONAL], LATER_ISO, bump=False)

    code, out, err, _, _ = _poll(
        ["poll", "Valg2546527", "--cycles", "2", "--diff"],
        transport,
        sleep=switch_election,
    )

    assert code == 1
    assert err.startswith("error: cannot diff folketingsvalg ")
    assert "Traceback" not in err
    assert not [line for line in _diff_lines(out) if "20:01:00" in line]


# --- round 4: referenda on the CLI (A4, A6; T4, T6) -------------------------------------


def _row(
    letter: str, width: int, name: str, percent: float, votes: int, seats: str
) -> str:
    return f"{letter:<{width}}{name:<48}{percent:>6.1f}%{votes:>11}{seats:>6}"


def test_party_election_table_rows_keep_their_three_wide_letter_column(
    fixture_dir: Path, election: Election
) -> None:
    _, out, _ = _run(["replay", str(fixture_dir), "--speed", "inf"])
    country = election.get(PlaceType.COUNTRY, "0")
    social = next(p for p in country.parties if p.letter == "A")
    outside = next(p for p in country.parties if not p.is_party)

    rows = out.splitlines()

    assert (
        _row("A", 3, social.name, social.percent, social.votes, str(social.seats))
        in rows
    )
    assert outside.seats == 0  # DST gives the outside-parties entry 0 seats in 2026
    assert (
        _row("-", 3, outside.name, outside.percent, outside.votes, str(outside.seats))
        in rows
    )
    assert [line for line in rows if line.startswith("A  A. Socialdemokratiet")]


def test_ep_table_rows_keep_their_three_wide_letter_column(
    ep_fixture_dir: Path, ep_election: Election
) -> None:
    _, out, _ = _run(["replay", str(ep_fixture_dir), "--speed", "inf"])
    sf = next(
        p for p in ep_election.get(PlaceType.COUNTRY, "0").parties if p.letter == "F"
    )

    assert _row("F", 3, sf.name, sf.percent, sf.votes, "-") in out.splitlines()


def test_referendum_replay_output_without_the_flag_equals_the_diff_output_minus_the_diff_lines(
    fa_2015_dir: Path,
) -> None:
    _, plain, _ = _run(["replay", str(fa_2015_dir), "--speed", "inf"])

    code, with_diff, err = _run(
        ["replay", str(fa_2015_dir), "--speed", "inf", "--diff"]
    )

    assert (code, err) == (0, "")
    assert _without_diff_lines(with_diff) == plain
    assert _diff_lines(plain) == []
    assert len(_diff_lines(with_diff)) > 100


@pytest.mark.parametrize(
    ("fixture_name", "final"),
    [("fa_2015_dir", "NEJ"), ("fa_2022_dir", "JA"), ("fa_2009_dir", "JA")],
)
def test_referendum_diff_leader_lines_are_only_country_landsdel_and_storkreds_with_ja_nej(
    request: pytest.FixtureRequest, fixture_name: str, final: str
) -> None:
    directory: Path = request.getfixturevalue(fixture_name)

    _, out, _ = _run(["replay", str(directory), "--speed", "inf", "--diff"])

    leaders = [m for line in _diff_lines(out) if (m := LEADER_LINE.match(line))]
    assert {m.group(2) for m in leaders} == {"country", "landsdel", "storkreds"}
    assert {m.group(5) for m in leaders} <= {"JA", "NEJ"}
    assert {m.group(4) for m in leaders} <= {"-", "JA", "NEJ"}
    assert f"leader country Hele landet: - -> {final}" in out
    assert "leader opstillingskreds" not in out
    assert "leader tally" not in out


def test_referendum_diff_prints_no_seat_lines_and_ends_with_the_progress_line(
    fa_2015_dir: Path,
) -> None:
    _, out, _ = _run(["replay", str(fa_2015_dir), "--speed", "inf", "--diff"])

    diff_lines = _diff_lines(out)
    assert not [line for line in diff_lines if "  seats " in line]
    assert not [line for line in diff_lines if "  status " in line]
    assert PROGRESS_LINE.match(diff_lines[-1]) is not None or "leader" in diff_lines[-1]
    assert any(line.endswith("progress 91/92 -> 92/92") for line in diff_lines)
    assert any("-> NEJ" in line for line in diff_lines)


def test_referendum_poll_diff_prints_a_leader_line_for_the_country(
    fa_transport: FakeTransport,
) -> None:
    code, out, err, _, _ = _poll(
        ["poll", "Valg1962294", "--cycles", "1", "--diff"], fa_transport
    )

    assert (code, err) == (0, "")
    assert "leader country Hele landet: - -> JA" in out
    assert not [line for line in _diff_lines(out) if "  seats " in line]


def test_replay_of_a_referendum_capture_prints_the_answers_in_the_table(
    fa_transport: FakeTransport, tmp_path: Path
) -> None:
    capture = tmp_path / "cap"
    source = HttpSource(
        "Valg1962294",
        transport=fa_transport,
        recorder=Recorder(capture),
        clock=FakeClock(),
    )
    source.fetch()

    code, out, err = _run(["replay", str(capture), "--speed", "inf", "--diff"])

    assert (code, err) == (0, "")
    assert _row("JA", 4, "JA", 66.9, 1_848_738, "-") in out.splitlines()
    assert "progress 0/92 -> 92/92" in out


def test_poll_diff_a_referendum_that_changes_type_mid_run_exits_1_with_an_error(
    fa_transport: FakeTransport,
) -> None:
    def switch_election(_seconds: float) -> None:
        overview = fa_transport.files[OVERVIEW].replace(
            b"Folkeafstemning onsdag", b"Europa-Parlamentsvalg onsdag"
        )
        fa_transport.publish(OVERVIEW, overview)
        fa_transport.touch([NATIONAL], "2022-06-02T01:00:00", bump=False)

    code, out, err, _, _ = _poll(
        ["poll", "Valg1962294", "--cycles", "2", "--diff"],
        fa_transport,
        sleep=switch_election,
    )

    assert code == 1
    assert err.startswith("error: cannot diff folkeafstemning ")
    assert "europaparlamentsvalg" in err
    assert "Traceback" not in err
    assert not [line for line in _diff_lines(out) if "20:01:00" in line]
