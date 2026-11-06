import re
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from conftest import (
    EP_BASE_URL,
    FA_2009_FIXTURES,
    FA_2015_BASE_URL,
    FA_2015_FIXTURES,
    FA_2022_FIXTURES,
    NATIONAL,
    OVERVIEW,
    FakeClock,
    FakeTransport,
    ep_fixture_files,
    fa_fixture_files,
    feed_xml,
    fixture_files,
    kreds_entry,
    overview_xml,
    retime_overview,
    utc,
)

from dkvalg import (
    CaptureReplay,
    CaptureStep,
    ElectionType,
    FeedError,
    FetchResult,
    HttpSource,
    PlaceType,
    Recorder,
    load_election,
)
from dkvalg.sources.capture import check_feed_name, is_capture_directory
from dkvalg.sources.http_source import HttpResponse

INF = float("inf")
T1 = "2026-03-24T20:00:00+00:00"
T2 = "2026-03-24T20:01:00+00:00"
T3 = "2026-03-24T20:03:30+00:00"
# a capture name written with fullwidth digits: matches \d without re.ASCII
FULLWIDTH = "".join(
    chr(0xFF10 + int(c)) if c.isdigit() else c for c in "20260324T200000.000000Z"
)


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _overview(*ids: str, stamps: dict[str, str] | None = None) -> bytes:
    stamps = stamps or {}
    entries = []
    for place_id in ids:
        iso = stamps.get(place_id, "2026-03-24T22:00:00")
        entries.append(kreds_entry(place_id, f"K{place_id}", iso=iso, senest=None))
    return overview_xml(entries)


def _feed(votes: int = 1000, iso: str = "2026-03-24T22:00:00") -> bytes:
    stemmer = (
        f'<Parti Id="5891" Bogstav="A" Navn="A. Socialdemokratiet" '
        f'StemmerAntal="{votes}" StemmerPct="100.0" />\n'
        f"<IAltGyldigeStemmer>{votes}</IAltGyldigeStemmer>\n"
        "<BlankeStemmer>0</BlankeStemmer>\n"
        "<AndreUgyldigeStemmer>0</AndreUgyldigeStemmer>\n"
        "<IAltUgyldigeStemmer>0</IAltUgyldigeStemmer>\n"
        f"<IAltAfgivneStemmer>{votes}</IAltAfgivneStemmer>\n"
    )
    return feed_xml(stemmer=stemmer, iso=iso, senest=None)


def _first_capture(root: Path) -> Path:
    """A capture directory with one complete two-kreds election at T1."""
    recorder = Recorder(root)
    recorder.record(
        _at(T1),
        {
            OVERVIEW: _overview("20", "21"),
            "valgdag_20.xml": _feed(),
            "valgdag_21.xml": _feed(),
        },
    )
    return root


def _folders(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


# --- check_feed_name (T7) ---------------------------------------------------------


def test_check_feed_name_accepts_every_fixture_feed_name_except_the_overview() -> None:
    names = [name for name in fixture_files() if name != OVERVIEW]

    assert len(names) == 108
    assert [check_feed_name(name) for name in names] == names


@pytest.mark.parametrize(
    "name",
    [
        "x.xml",
        "A-b_9.xml",
        "valgdag_999.xml",
        "valgdag2.xml",
        "Valgdag_1.xml",
        "generel.xml",
    ],
)
def test_check_feed_name_returns_a_safe_name_unchanged(name: str) -> None:
    assert check_feed_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "../x.xml",
        "a/b.xml",
        "a\\b.xml",
        "C:x.xml",
        "a#b.xml",
        "a?b.xml",
        "x y.xml",
        "x.XML",
        "x.xml.bak",
        "x.xml\n",
        "\nx.xml",
        ".xml",
        "xml",
        "",
        " ",
        "é.xml",
        "ñ.xml",
        "x\x00.xml",
        "%2e%2e.xml",
        "valgdag.xml",
        "VALGDAG.xml",
        "Valgdag.xml",
        "valgdag.XML",
        "x.xml/",
    ],
)
def test_check_feed_name_rejects_unsafe_names_and_the_overview_in_any_case(
    name: str,
) -> None:
    with pytest.raises(FeedError, match="unsafe feed file name"):
        check_feed_name(name)


def test_check_feed_name_error_names_the_offending_value() -> None:
    with pytest.raises(FeedError, match=re.escape(repr("../x.xml"))):
        check_feed_name("../x.xml")


# --- Recorder (T7, A6) --------------------------------------------------------------


def test_record_writes_a_utc_named_folder_holding_the_given_files(
    tmp_path: Path,
) -> None:
    feeds = {OVERVIEW: b"<o/>", "valgdag_20.xml": b"<f/>"}

    folder = Recorder(tmp_path / "cap").record(_at(T1), feeds)

    assert folder == tmp_path / "cap" / "20260324T200000.000000Z"
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == feeds


def test_record_does_not_create_the_directory_until_the_first_record(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "a" / "b" / "cap"

    recorder = Recorder(directory)

    assert not directory.exists()
    recorder.record(_at(T1), {OVERVIEW: b"x"})
    assert directory.is_dir()


@pytest.mark.parametrize(
    ("when", "name"),
    [
        ("2026-03-24T22:00:00.5+02:00", "20260324T200000.500000Z"),
        ("2026-03-24T20:00:00+00:00", "20260324T200000.000000Z"),
        ("2026-03-24T20:00:00.000001+00:00", "20260324T200000.000001Z"),
        ("2026-03-24T23:59:59.999999+00:00", "20260324T235959.999999Z"),
        ("2026-03-25T01:30:00+05:30", "20260324T200000.000000Z"),
        ("2026-12-31T23:00:00-05:00", "20270101T040000.000000Z"),
    ],
)
def test_record_names_the_folder_after_the_utc_time(
    tmp_path: Path, when: str, name: str
) -> None:
    folder = Recorder(tmp_path).record(_at(when), {OVERVIEW: b"x"})

    assert folder.name == name


def test_record_refuses_a_naive_time_and_writes_nothing(tmp_path: Path) -> None:
    naive = datetime.fromisoformat("2026-03-24T20:00:00")

    with pytest.raises(ValueError, match="timezone-aware"):
        Recorder(tmp_path / "cap").record(naive, {OVERVIEW: b"x"})

    assert not (tmp_path / "cap").exists()


def test_record_refuses_no_feeds_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no feeds"):
        Recorder(tmp_path / "cap").record(_at(T1), {})

    assert not (tmp_path / "cap").exists()


def test_record_with_a_naive_time_and_no_feeds_reports_the_time_first(
    tmp_path: Path,
) -> None:
    naive = datetime.fromisoformat("2026-03-24T20:00:00")

    with pytest.raises(ValueError, match="timezone-aware"):
        Recorder(tmp_path).record(naive, {})


@pytest.mark.parametrize(
    "name",
    [
        "../x.xml",
        "a/b.xml",
        "a\\b.xml",
        "C:x.xml",
        "x.XML",
        "x.xml.bak",
        "x.xml\n",
        ".xml",
        "",
        "é.xml",
        "VALGDAG.xml",
        "Valgdag.xml",
        "valgdag.XML",
    ],
)
def test_record_refuses_an_unsafe_name_and_creates_no_folder(
    tmp_path: Path, name: str
) -> None:
    directory = tmp_path / "cap"

    with pytest.raises(FeedError, match="unsafe feed file name"):
        Recorder(directory).record(_at(T1), {"good.xml": b"x", name: b"y"})

    assert not directory.exists()
    assert not (tmp_path / "x.xml").exists()


def test_record_accepts_an_overview_only_capture(tmp_path: Path) -> None:
    folder = Recorder(tmp_path).record(_at(T1), {OVERVIEW: b"<o/>"})

    assert [p.name for p in folder.iterdir()] == [OVERVIEW]


def test_record_writes_an_empty_body_as_a_zero_byte_file(tmp_path: Path) -> None:
    folder = Recorder(tmp_path).record(_at(T1), {"a.xml": b""})

    assert (folder / "a.xml").read_bytes() == b""


@pytest.mark.parametrize("body", ["text", 12, None, bytearray(b"x"), memoryview(b"x")])
def test_record_refuses_a_body_that_is_not_bytes_and_leaves_no_temporary_folder(
    tmp_path: Path, body: object
) -> None:
    directory = tmp_path / "cap"

    with pytest.raises(FeedError, match=r"a\.xml.*bytes"):
        Recorder(directory).record(_at(T1), {OVERVIEW: b"ok", "a.xml": body})  # type: ignore[dict-item]  # a deliberately wrong type

    assert not directory.exists() or _folders(directory) == []


def test_record_cleans_up_when_a_write_fails_midway_with_an_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "cap"
    real = Path.write_bytes
    calls = {"n": 0}

    def failing(self: Path, data: bytes) -> int:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing)

    with pytest.raises(FeedError, match="disk full"):
        Recorder(directory).record(
            _at(T1), {OVERVIEW: b"1", "a.xml": b"2", "b.xml": b"3"}
        )

    assert _folders(directory) == []


def test_record_cleans_up_when_a_write_fails_with_something_that_is_not_an_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "cap"
    real = Path.write_bytes

    def failing(self: Path, data: bytes) -> int:
        if self.name == "a.xml":
            raise RuntimeError("boom")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing)

    with pytest.raises(RuntimeError, match="boom"):
        Recorder(directory).record(_at(T1), {OVERVIEW: b"1", "a.xml": b"2"})

    assert _folders(directory) == []


def test_record_refuses_an_existing_folder_and_keeps_its_contents(
    tmp_path: Path,
) -> None:
    recorder = Recorder(tmp_path)
    first = recorder.record(_at(T1), {OVERVIEW: b"first"})

    with pytest.raises(FeedError, match="already exists"):
        recorder.record(_at(T1), {OVERVIEW: b"second", "a.xml": b"x"})

    assert [p.name for p in first.iterdir()] == [OVERVIEW]
    assert (first / OVERVIEW).read_bytes() == b"first"
    assert _folders(tmp_path) == [first.name]


def test_record_replaces_a_leftover_temporary_folder_from_a_crash(
    tmp_path: Path,
) -> None:
    stale = tmp_path / ".tmp-20260324T200000.000000Z"
    stale.mkdir()
    (stale / "old.xml").write_bytes(b"stale")

    folder = Recorder(tmp_path).record(_at(T1), {OVERVIEW: b"new"})

    assert [p.name for p in folder.iterdir()] == [OVERVIEW]
    assert _folders(tmp_path) == [folder.name]


def test_record_with_a_regular_file_in_the_temporary_place_is_a_feed_error(
    tmp_path: Path,
) -> None:
    (tmp_path / ".tmp-20260324T200000.000000Z").write_bytes(b"not a folder")

    with pytest.raises(FeedError, match="cannot write capture"):
        Recorder(tmp_path).record(_at(T1), {OVERVIEW: b"x"})


def test_record_into_a_directory_that_is_a_regular_file_is_a_feed_error(
    tmp_path: Path,
) -> None:
    target = tmp_path / "cap"
    target.write_bytes(b"in the way")

    with pytest.raises(FeedError, match="cannot write capture"):
        Recorder(target).record(_at(T1), {OVERVIEW: b"x"})

    assert target.read_bytes() == b"in the way"


def test_record_does_not_mutate_the_feeds_it_is_given(tmp_path: Path) -> None:
    feeds = {OVERVIEW: b"a", "x.xml": b"b"}

    Recorder(tmp_path).record(_at(T1), feeds)

    assert feeds == {OVERVIEW: b"a", "x.xml": b"b"}


def test_record_keeps_every_folder_when_times_differ(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path)

    recorder.record(_at(T2), {OVERVIEW: b"2"})
    recorder.record(_at(T1), {OVERVIEW: b"1"})

    assert _folders(tmp_path) == ["20260324T200000.000000Z", "20260324T200100.000000Z"]


# --- is_capture_directory (T9) ---------------------------------------------------


def test_is_capture_directory_true_for_a_directory_with_a_capture_folder(
    tmp_path: Path,
) -> None:
    assert is_capture_directory(_first_capture(tmp_path / "cap"))


def test_is_capture_directory_false_for_a_plain_feed_directory(
    fixture_dir: Path,
) -> None:
    assert not is_capture_directory(fixture_dir)


def test_is_capture_directory_false_when_a_capture_folder_sits_beside_an_overview(
    tmp_path: Path,
) -> None:
    directory = _first_capture(tmp_path / "cap")
    (directory / OVERVIEW).write_bytes(b"<o/>")

    assert not is_capture_directory(directory)


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [".tmp-20260324T200000.000000Z"],
        ["notes.txt", "__pycache__"],
        ["20260324T200000Z"],
        ["20260324T200000.000000z"],
        [FULLWIDTH],
    ],
)
def test_is_capture_directory_false_without_a_capture_named_folder(
    tmp_path: Path, entries: list[str]
) -> None:
    for entry in entries:
        (tmp_path / entry).mkdir()

    assert not is_capture_directory(tmp_path)


def test_is_capture_directory_false_when_the_only_match_is_a_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "20260324T200000.000000Z").write_bytes(b"x")

    assert not is_capture_directory(tmp_path)


def test_is_capture_directory_false_for_a_file_and_a_missing_path(
    tmp_path: Path,
) -> None:
    (tmp_path / "f").write_bytes(b"x")

    assert not is_capture_directory(tmp_path / "f")
    assert not is_capture_directory(tmp_path / "missing")


def test_is_capture_directory_true_even_when_the_folder_time_is_invalid(
    tmp_path: Path,
) -> None:
    (tmp_path / "20261301T000000.000000Z").mkdir()

    assert is_capture_directory(tmp_path)


# --- CaptureReplay: construction -----------------------------------------------------


@pytest.mark.parametrize("speed", [0, 0.0, -1, -0.5, float("nan"), -INF])
def test_capture_replay_rejects_a_speed_that_is_not_positive(
    tmp_path: Path, speed: float
) -> None:
    with pytest.raises(ValueError, match="speed"):
        CaptureReplay(tmp_path, speed=speed)


def test_capture_replay_speed_error_names_the_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="-3"):
        CaptureReplay(tmp_path, speed=-3)


@pytest.mark.parametrize("speed", [1, 0.001, 600.0, INF])
def test_capture_replay_accepts_a_positive_speed_and_infinity(
    tmp_path: Path, speed: float
) -> None:
    CaptureReplay(tmp_path, speed=speed)


def test_capture_replay_reads_nothing_until_it_is_iterated(tmp_path: Path) -> None:
    replay = CaptureReplay(tmp_path / "does-not-exist-yet")

    with pytest.raises(FeedError):
        list(replay)


# --- CaptureReplay: steps (T8, A6) -----------------------------------------------------


def _three_step_capture(root: Path) -> Path:
    recorder = Recorder(root)
    recorder.record(
        _at(T1),
        {
            OVERVIEW: _overview("20", "21"),
            "valgdag_20.xml": _feed(1000),
            "valgdag_21.xml": _feed(500),
        },
    )
    new = "2026-03-24T22:30:00"
    recorder.record(
        _at(T2),
        {
            OVERVIEW: _overview("20", "21", stamps={"20": new}),
            "valgdag_20.xml": _feed(1100, iso=new),
        },
    )
    recorder.record(_at(T3), {OVERVIEW: _overview("20", "21", stamps={"20": new})})
    return root


def test_replay_yields_one_step_per_folder_in_fetch_time_order(tmp_path: Path) -> None:
    steps = list(CaptureReplay(_three_step_capture(tmp_path / "c"), speed=INF))

    assert [s.at for s in steps] == [_at(T1), _at(T2), _at(T3)]
    assert all(isinstance(s, CaptureStep) for s in steps)
    assert all(s.at.utcoffset() is not None for s in steps)


def test_replay_first_step_changes_every_reported_place(tmp_path: Path) -> None:
    first, *_ = CaptureReplay(_three_step_capture(tmp_path / "c"), speed=INF)

    assert first.changed == first.election.places
    assert len(first.changed) == 2


def test_replay_later_step_changes_only_the_places_that_differ(tmp_path: Path) -> None:
    _, second, third = CaptureReplay(_three_step_capture(tmp_path / "c"), speed=INF)

    assert [p.place_id for p in second.changed] == ["20"]
    assert second.election.get(PlaceType.OPSTILLINGSKREDS, "20").valid_votes == 1100
    assert second.election.get(PlaceType.OPSTILLINGSKREDS, "21").valid_votes == 500
    assert third.changed == ()
    assert third.election == second.election


def test_replay_an_earlier_step_shows_the_earlier_figures(tmp_path: Path) -> None:
    first, second, _ = CaptureReplay(_three_step_capture(tmp_path / "c"), speed=INF)

    assert first.election.get(PlaceType.OPSTILLINGSKREDS, "20").valid_votes == 1000
    assert second.election.get(PlaceType.OPSTILLINGSKREDS, "20").valid_votes == 1100


def test_replay_step_progress_counts_the_snapshots_reported_kredse(
    tmp_path: Path,
) -> None:
    first, *_ = CaptureReplay(_three_step_capture(tmp_path / "c"), speed=INF)

    assert str(first.progress) == "2/2"


def test_replay_a_later_folders_file_replaces_the_earlier_one(tmp_path: Path) -> None:
    steps = list(CaptureReplay(_three_step_capture(tmp_path / "c"), speed=INF))

    assert steps[2].election.get(PlaceType.OPSTILLINGSKREDS, "20").valid_votes == 1100


def test_replay_an_overview_only_capture_with_unchanged_timestamps_changes_nothing(
    tmp_path: Path,
) -> None:
    directory = _first_capture(tmp_path / "c")
    Recorder(directory).record(_at(T2), {OVERVIEW: _overview("20", "21")})

    first, second = CaptureReplay(directory, speed=INF)

    assert second.changed == ()
    assert second.election == first.election


@pytest.mark.parametrize(
    ("speed", "expected"),
    [(1.0, [60.0, 150.0]), (60.0, [1.0, 2.5]), (0.5, [120.0, 300.0]), (INF, [])],
)
def test_replay_sleeps_the_gap_between_fetch_times_divided_by_speed(
    tmp_path: Path, speed: float, expected: list[float]
) -> None:
    waits: list[float] = []

    list(
        CaptureReplay(
            _three_step_capture(tmp_path / "c"), speed=speed, sleep=waits.append
        )
    )

    assert waits == expected


def test_replay_gaps_come_from_the_folder_names_not_the_file_times(
    tmp_path: Path,
) -> None:
    directory = _three_step_capture(tmp_path / "c")
    waits: list[float] = []

    # touching a folder changes its mtime, not its name
    (directory / "20260324T200000.000000Z" / "valgdag_20.xml").touch()

    list(CaptureReplay(directory, speed=2.0, sleep=waits.append))

    assert waits == [30.0, 75.0]


def test_replay_orders_by_name_not_by_creation_order(tmp_path: Path) -> None:
    root = tmp_path / "c"
    recorder = Recorder(root)
    overview = _overview("20")
    recorder.record(_at(T3), {OVERVIEW: overview, "valgdag_20.xml": _feed(3)})
    recorder.record(_at(T1), {OVERVIEW: overview, "valgdag_20.xml": _feed(1)})
    recorder.record(_at(T2), {OVERVIEW: overview, "valgdag_20.xml": _feed(2)})

    steps = list(CaptureReplay(root, speed=INF))

    assert [s.at for s in steps] == [_at(T1), _at(T2), _at(T3)]
    place = [
        s.election.get(PlaceType.OPSTILLINGSKREDS, "20").valid_votes for s in steps
    ]
    assert place == [1, 2, 3]


def test_replay_a_sub_second_gap_is_slept_exactly(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path / "c")
    overview = _overview("20")
    recorder.record(
        _at("2026-03-24T20:00:00.250000+00:00"),
        {OVERVIEW: overview, "valgdag_20.xml": _feed()},
    )
    recorder.record(_at("2026-03-24T20:00:00.750000+00:00"), {OVERVIEW: overview})
    waits: list[float] = []

    list(CaptureReplay(tmp_path / "c", speed=2.0, sleep=waits.append))

    assert waits == [0.25]


def test_replay_a_single_capture_never_sleeps(tmp_path: Path) -> None:
    waits: list[float] = []

    steps = list(CaptureReplay(_first_capture(tmp_path / "c"), sleep=waits.append))

    assert len(steps) == 1
    assert waits == []


def test_replay_restarts_and_gives_equal_steps_each_time(tmp_path: Path) -> None:
    replay = CaptureReplay(_three_step_capture(tmp_path / "c"), speed=INF)

    assert list(replay) == list(replay)


def test_replay_restart_sees_a_folder_added_in_between(tmp_path: Path) -> None:
    directory = _first_capture(tmp_path / "c")
    replay = CaptureReplay(directory, speed=INF)
    assert len(list(replay)) == 1

    Recorder(directory).record(_at(T2), {OVERVIEW: _overview("20", "21")})

    assert len(list(replay)) == 2


def test_replay_two_iterators_at_once_are_independent(tmp_path: Path) -> None:
    replay = CaptureReplay(_three_step_capture(tmp_path / "c"), speed=INF)

    one, two = iter(replay), iter(replay)
    a1, b1 = next(one), next(two)
    a2 = next(one)
    b2 = next(two)

    assert (a1, a2) == (b1, b2)


def test_replay_does_not_modify_the_capture_directory(tmp_path: Path) -> None:
    directory = _three_step_capture(tmp_path / "c")
    before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}

    list(CaptureReplay(directory, speed=INF))

    assert {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()} == before
    assert _folders(directory) == sorted(_folders(directory))


# --- CaptureReplay: what it ignores and what it refuses -------------------------------


def test_replay_ignores_entries_that_are_not_capture_folders(tmp_path: Path) -> None:
    directory = _three_step_capture(tmp_path / "c")
    (directory / ".tmp-20260324T200500.000000Z").mkdir()
    (directory / "notes.txt").write_bytes(b"hi")
    (directory / "20260324T200000Z").mkdir()
    (directory / "20260324T200000.000000z").mkdir()
    (directory / "__pycache__").mkdir()
    (directory / FULLWIDTH).mkdir()

    assert len(list(CaptureReplay(directory, speed=INF))) == 3


def test_replay_ignores_unrelated_files_inside_a_capture_folder(tmp_path: Path) -> None:
    directory = _three_step_capture(tmp_path / "c")
    folder = directory / "20260324T200100.000000Z"
    (folder / "readme.txt").write_bytes(b"x")
    (folder / "VALGDAG.xml").write_bytes(b"<junk")
    (folder / "bad name.xml").write_bytes(b"<junk")
    (folder / "sub.xml").mkdir()

    steps = list(CaptureReplay(directory, speed=INF))

    assert len(steps) == 3
    assert steps[1].election.get(PlaceType.OPSTILLINGSKREDS, "20").valid_votes == 1100


@pytest.mark.parametrize(
    "name",
    [
        "20261301T000000.000000Z",
        "20260230T000000.000000Z",
        "20260324T240000.000000Z",
        "20260324T236000.000000Z",
        "20260324T235960.000000Z",
        "00000000T000000.000000Z",
    ],
)
def test_replay_a_capture_name_that_is_not_a_valid_time_is_a_feed_error_naming_it(
    tmp_path: Path, name: str
) -> None:
    directory = _first_capture(tmp_path / "c")
    (directory / name).mkdir()

    with pytest.raises(FeedError, match=name):
        list(CaptureReplay(directory, speed=INF))


def test_replay_a_matching_name_that_is_a_file_is_a_feed_error(tmp_path: Path) -> None:
    directory = _first_capture(tmp_path / "c")
    (directory / "20260324T200500.000000Z").write_bytes(b"x")

    with pytest.raises(FeedError, match="20260324T200500.000000Z"):
        list(CaptureReplay(directory, speed=INF))


def test_replay_a_nonexistent_directory_is_a_feed_error_at_iteration(
    tmp_path: Path,
) -> None:
    replay = CaptureReplay(tmp_path / "missing", speed=INF)

    with pytest.raises(FeedError, match="missing"):
        list(replay)


def test_replay_a_directory_that_is_a_file_is_a_feed_error(tmp_path: Path) -> None:
    (tmp_path / "f").write_bytes(b"x")

    with pytest.raises(FeedError, match="cannot read capture directory"):
        list(CaptureReplay(tmp_path / "f", speed=INF))


@pytest.mark.parametrize("extra", [[], [".tmp-20260324T200000.000000Z", "notes.txt"]])
def test_replay_a_directory_without_captures_is_a_feed_error(
    tmp_path: Path, extra: list[str]
) -> None:
    for name in extra:
        (tmp_path / name).mkdir()

    with pytest.raises(FeedError, match="no captures in"):
        list(CaptureReplay(tmp_path, speed=INF))


@pytest.mark.parametrize(
    "feeds",
    [
        pytest.param({OVERVIEW: _overview("20", "21")}, id="only-the-overview"),
        pytest.param(
            {OVERVIEW: _overview("20", "21"), "valgdag_20.xml": _feed()},
            id="all-but-one-feed",
        ),
        pytest.param(
            {"valgdag_20.xml": _feed(), "valgdag_21.xml": _feed()}, id="no-overview"
        ),
    ],
)
def test_replay_an_incomplete_first_capture_is_a_feed_error_naming_the_folder(
    tmp_path: Path, feeds: dict[str, bytes]
) -> None:
    root = tmp_path / "c"
    Recorder(root).record(_at(T1), feeds)

    steps: list[CaptureStep] = []
    with pytest.raises(FeedError, match="20260324T200000.000000Z"):
        for step in CaptureReplay(root, speed=INF):
            steps.append(step)

    assert steps == []


def test_replay_an_empty_first_folder_is_a_feed_error_naming_it(tmp_path: Path) -> None:
    root = tmp_path / "c"
    (root / "20260324T200000.000000Z").mkdir(parents=True)

    with pytest.raises(FeedError, match="20260324T200000.000000Z"):
        list(CaptureReplay(root, speed=INF))


def test_replay_a_feed_missing_from_every_capture_raises_after_the_earlier_steps(
    tmp_path: Path,
) -> None:
    directory = _first_capture(tmp_path / "c")
    Recorder(directory).record(_at(T2), {OVERVIEW: _overview("20", "21", "22")})
    steps: list[CaptureStep] = []

    with pytest.raises(FeedError, match=r"20260324T200100.*valgdag_22\.xml"):
        for step in CaptureReplay(directory, speed=INF):
            steps.append(step)

    assert len(steps) == 1


def test_replay_a_malformed_body_in_a_later_folder_raises_after_the_earlier_steps(
    tmp_path: Path,
) -> None:
    directory = _first_capture(tmp_path / "c")
    Recorder(directory).record(_at(T2), {"valgdag_20.xml": b"<Data><unclosed"})
    steps: list[CaptureStep] = []

    with pytest.raises(FeedError, match="malformed"):
        for step in CaptureReplay(directory, speed=INF):
            steps.append(step)

    assert len(steps) == 1


def test_replay_an_empty_recorded_overview_is_a_feed_error(tmp_path: Path) -> None:
    root = tmp_path / "c"
    Recorder(root).record(_at(T1), {OVERVIEW: b""})

    with pytest.raises(FeedError, match="malformed"):
        list(CaptureReplay(root, speed=INF))


def test_replay_a_doctype_in_a_recorded_feed_is_refused(tmp_path: Path) -> None:
    directory = _first_capture(tmp_path / "c")
    hostile = b'<!DOCTYPE d [<!ENTITY a "b">]><Data/>'
    Recorder(directory).record(_at(T2), {"valgdag_20.xml": hostile})

    with pytest.raises(FeedError, match="DOCTYPE"):
        list(CaptureReplay(directory, speed=INF))


def test_replay_reads_bodies_one_step_at_a_time(tmp_path: Path) -> None:
    directory = _three_step_capture(tmp_path / "c")
    iterator = iter(CaptureReplay(directory, speed=INF))
    next(iterator)

    shutil.rmtree(directory / "20260324T200100.000000Z")

    # the folder list was taken when iteration started, so the vanished folder
    # surfaces as a clean error rather than a skipped step
    with pytest.raises(FeedError, match="cannot read capture"):
        next(iterator)


# --- record then replay, end to end (T8, A6) ------------------------------------------


def _record_four_fetches(
    directory: Path,
) -> tuple[HttpSource, list[FetchResult], FakeTransport]:
    transport = FakeTransport()
    source = HttpSource(
        "Valg2546527",
        transport=transport,
        recorder=Recorder(directory),
        clock=FakeClock(T1, 60.0),
    )
    results = [source.fetch()]  # 1: everything
    transport.touch([NATIONAL, "valgdag_20.xml", "valgdag_7.xml"])
    results.append(source.fetch())  # 2: the national feed and two others
    body = transport.files[OVERVIEW]
    transport.script(
        OVERVIEW, HttpResponse(200, {"etag": '"other-node"'}, body)
    )  # 3: an identical body from another node
    results.append(source.fetch())
    transport.script(OVERVIEW, HttpResponse(304, {}, b""))  # 4: not modified
    results.append(source.fetch())
    return source, results, transport


def test_record_then_replay_gives_one_step_per_recorded_fetch(tmp_path: Path) -> None:
    directory = tmp_path / "cap"
    _, results, _ = _record_four_fetches(directory)

    steps = list(CaptureReplay(directory, speed=INF))

    assert len(_folders(directory)) == 3  # the 304 recorded nothing
    assert [s.at for s in steps] == [results[i].fetched_at for i in range(3)]
    assert [s.at for s in steps] == sorted(s.at for s in steps)


def test_record_then_replay_changed_lists_equal_the_live_changed_lists(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "cap"
    _, results, _ = _record_four_fetches(directory)

    steps = list(CaptureReplay(directory, speed=INF))

    assert [s.changed for s in steps] == [r.changed for r in results[:3]]
    assert len(steps[0].changed) == 107
    assert len(steps[1].changed) == 3
    assert steps[2].changed == ()
    assert results[3].changed == ()


def test_record_then_replay_an_earlier_step_shows_the_earlier_national_figures(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "cap"
    _, results, _ = _record_four_fetches(directory)

    steps = list(CaptureReplay(directory, speed=INF))

    first = steps[0].election.get(PlaceType.COUNTRY, "0")
    second = steps[1].election.get(PlaceType.COUNTRY, "0")
    assert first == results[0].election.get(PlaceType.COUNTRY, "0")
    assert second == results[1].election.get(PlaceType.COUNTRY, "0")
    assert first.valid_votes is not None
    assert second.valid_votes == first.valid_votes + 1
    assert first != second


def test_record_then_replay_the_last_step_equals_the_election_as_last_fetched(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "cap"
    source, _, transport = _record_four_fetches(directory)

    steps = list(CaptureReplay(directory, speed=INF))

    assert steps[-1].election == source.election
    assert steps[-1].election == load_election(transport.write_to(tmp_path / "now"))


def test_record_then_replay_the_identical_body_capture_holds_only_the_overview(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "cap"
    _record_four_fetches(directory)

    folders = _folders(directory)

    assert len(list((directory / folders[0]).iterdir())) == 108
    assert sorted(p.name for p in (directory / folders[1]).iterdir()) == sorted(
        [OVERVIEW, NATIONAL, "valgdag_20.xml", "valgdag_7.xml"]
    )
    assert [p.name for p in (directory / folders[2]).iterdir()] == [OVERVIEW]


@pytest.mark.parametrize("speed", [60.0, 1.0, INF])
def test_record_then_replay_sleeps_are_the_fetch_gaps_divided_by_speed(
    tmp_path: Path, speed: float
) -> None:
    directory = tmp_path / "cap"
    _record_four_fetches(directory)  # fetch times are 60 s apart
    waits: list[float] = []

    list(CaptureReplay(directory, speed=speed, sleep=waits.append))

    assert waits == ([] if speed == INF else [60.0 / speed, 60.0 / speed])


def test_record_then_replay_restarting_gives_equal_steps(tmp_path: Path) -> None:
    directory = tmp_path / "cap"
    _record_four_fetches(directory)
    replay = CaptureReplay(directory, speed=INF)

    assert list(replay) == list(replay)


def test_a_clock_with_an_offset_records_a_utc_folder_and_replays_utc(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "cap"
    source = HttpSource(
        "Valg2546527",
        transport=FakeTransport(),
        recorder=Recorder(directory),
        clock=FakeClock("2026-03-24T22:00:00+02:00"),
    )
    source.fetch()

    (step,) = CaptureReplay(directory, speed=INF)

    assert _folders(directory) == ["20260324T200000.000000Z"]
    assert step.at == utc("2026-03-24T20:00:00")
    assert step.at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]  # aware


def test_replay_keeps_an_old_body_when_the_overview_claims_a_newer_one_nobody_captured(
    tmp_path: Path,
) -> None:
    files = fixture_files()
    root = tmp_path / "cap"
    recorder = Recorder(root)
    recorder.record(_at(T1), files)
    later = retime_overview(files[OVERVIEW], NATIONAL, "2026-03-25T03:00:00")
    recorder.record(_at(T2), {OVERVIEW: later})
    waits: list[float] = []

    steps = list(CaptureReplay(root, speed=2.0, sleep=waits.append))

    assert len(steps) == 2
    assert steps[1].changed == ()  # a place's figures come from its feed body
    assert waits == [30.0]


# --- round 3: Europa-Parlamentsvalg captures (A3, T3) ---------------------------------


def _record_ep(directory: Path) -> tuple[HttpSource, list[FetchResult]]:
    transport = FakeTransport(ep_fixture_files(), base_url=EP_BASE_URL)
    source = HttpSource(
        "Valg2546524",
        transport=transport,
        recorder=Recorder(directory),
        clock=FakeClock(T1, 60.0),
    )
    results = [source.fetch()]
    transport.touch([NATIONAL, "valgdag_20.xml"])
    results.append(source.fetch())
    return source, results


def test_ep_record_then_replay_ends_equal_to_the_last_fetch(tmp_path: Path) -> None:
    source, results = _record_ep(tmp_path / "cap")

    steps = list(CaptureReplay(tmp_path / "cap", speed=INF))

    assert len(steps) == 2
    assert steps[-1].election == source.election == results[-1].election
    assert steps[-1].election.election_type is ElectionType.EUROPAPARLAMENTSVALG


def test_ep_replay_step_changed_lists_equal_the_live_ones(tmp_path: Path) -> None:
    _, results = _record_ep(tmp_path / "cap")

    steps = list(CaptureReplay(tmp_path / "cap", speed=INF))

    assert [s.changed for s in steps] == [r.changed for r in results]
    assert len(steps[0].changed) == 107
    assert {p.place_id for p in steps[1].changed} == {"0", "20"}


def test_ep_replay_shows_the_earlier_national_figures_first(tmp_path: Path) -> None:
    _record_ep(tmp_path / "cap")

    first, last = list(CaptureReplay(tmp_path / "cap", speed=INF))

    national = (PlaceType.COUNTRY, "0")
    assert (
        first.election.get(*national).valid_votes
        != last.election.get(*national).valid_votes
    )


def test_an_ep_capture_folder_holds_the_ep_overview_with_the_double_space(
    tmp_path: Path,
) -> None:
    _record_ep(tmp_path / "cap")

    first_folder = sorted((tmp_path / "cap").iterdir())[0]

    assert (
        "søndag  9. juni 2024".encode() in (first_folder / "valgdag.xml").read_bytes()
    )
    assert len(list(first_folder.glob("*.xml"))) == 108
    assert is_capture_directory(tmp_path / "cap")


# --- round 4: Folkeafstemning captures (A4, T4; 2015, which has iso stamps) ---------------


def _record_fa(directory: Path) -> tuple[HttpSource, list[FetchResult]]:
    transport = FakeTransport(
        fa_fixture_files(FA_2015_FIXTURES), base_url=FA_2015_BASE_URL
    )
    source = HttpSource(
        "Valg1664255",
        transport=transport,
        recorder=Recorder(directory),
        clock=FakeClock(T1, 60.0),
    )
    results = [source.fetch()]
    transport.touch([NATIONAL, "valgdag_20.xml"])
    results.append(source.fetch())
    results.append(source.fetch())  # identical: nothing received that differs
    return source, results


def test_referendum_record_then_replay_ends_equal_to_the_last_fetch(
    tmp_path: Path,
) -> None:
    source, results = _record_fa(tmp_path / "cap")

    steps = list(CaptureReplay(tmp_path / "cap", speed=INF))

    assert len(steps) == 2
    assert steps[-1].election == source.election == results[-1].election
    assert steps[-1].election.election_type is ElectionType.FOLKEAFSTEMNING
    assert steps[-1].election.get(PlaceType.COUNTRY, "0").leader.letter == "NEJ"  # type: ignore[union-attr]  # a result is present


def test_referendum_replay_changed_lists_equal_the_live_ones_and_replay_is_repeatable(
    tmp_path: Path,
) -> None:
    _, results = _record_fa(tmp_path / "cap")

    steps = list(CaptureReplay(tmp_path / "cap", speed=INF))
    again = list(CaptureReplay(tmp_path / "cap", speed=INF))

    assert [s.changed for s in steps] == [r.changed for r in results[:2]]
    assert len(steps[0].changed) == 107
    assert {p.place_id for p in steps[1].changed} == {"0", "20"}
    assert [s.election for s in again] == [s.election for s in steps]


def test_a_referendum_capture_folder_holds_the_overview_and_every_feed_under_dst_names(
    tmp_path: Path,
) -> None:
    _record_fa(tmp_path / "cap")

    first_folder = sorted((tmp_path / "cap").iterdir())[0]

    assert b"torsdag 3. december 2015" in (first_folder / "valgdag.xml").read_bytes()
    assert len(list(first_folder.glob("*.xml"))) == 108
    assert is_capture_directory(tmp_path / "cap")


def test_check_feed_name_accepts_every_referendum_feed_name_except_the_overview() -> (
    None
):
    for directory in (FA_2015_FIXTURES, FA_2022_FIXTURES, FA_2009_FIXTURES):
        names = [n for n in fa_fixture_files(directory) if n != OVERVIEW]

        assert [check_feed_name(name) for name in names] == names
