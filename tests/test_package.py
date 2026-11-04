import importlib

import pytest

import dkvalg

PUBLIC = [
    "FeedError",
    "ElectionType",
    "PlaceType",
    "Status",
    "PartyResult",
    "Place",
    "CountingProgress",
    "Election",
    "load_election",
    "ReplaySource",
    "ReplayStep",
]


def test_import_dkvalg_works() -> None:
    assert importlib.import_module("dkvalg") is dkvalg


@pytest.mark.parametrize("name", PUBLIC)
def test_dkvalg_re_exports_the_public_api(name: str) -> None:
    assert hasattr(dkvalg, name)


@pytest.mark.parametrize(
    "name",
    [
        "run",
        "main",
        "parse_overview",
        "parse_place",
        "unreported_place",
        "FeedRef",
        "Overview",
    ],
)
def test_dkvalg_keeps_adapter_and_cli_internals_out_of_the_top_level(name: str) -> None:
    assert not hasattr(dkvalg, name)


@pytest.mark.parametrize(
    "name", ["valg_data", "valg_data.hello_world", "template_repo"]
)
def test_the_old_packages_are_not_importable(name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(name)


LIVE_PUBLIC = {
    "FetchError": "dkvalg.errors",
    "HttpSource": "dkvalg.sources.http_source",
    "FetchResult": "dkvalg.sources.http_source",
    "PollCycle": "dkvalg.sources.http_source",
    "poll": "dkvalg.sources.http_source",
    "Recorder": "dkvalg.sources.capture",
    "CaptureReplay": "dkvalg.sources.capture",
    "CaptureStep": "dkvalg.sources.capture",
}


@pytest.mark.parametrize(("name", "module"), sorted(LIVE_PUBLIC.items()))
def test_dkvalg_re_exports_the_live_polling_api_from_its_module(
    name: str, module: str
) -> None:
    assert getattr(dkvalg, name) is getattr(importlib.import_module(module), name)


@pytest.mark.parametrize(
    "name",
    [
        "Transport",
        "HttpResponse",
        "urllib_transport",
        "user_agent",
        "utc_now",
        "overview_url",
        "DEFAULT_INTERVAL",
        "MIN_INTERVAL",
        "MAX_BACKOFF",
        "build_election",
        "is_capture_directory",
        "check_feed_name",
    ],
)
def test_dkvalg_keeps_transport_pieces_and_helpers_out_of_the_top_level(
    name: str,
) -> None:
    assert not hasattr(dkvalg, name)


@pytest.mark.parametrize(
    ("name", "module"),
    [
        ("Transport", "dkvalg.sources.http_source"),
        ("HttpResponse", "dkvalg.sources.http_source"),
        ("urllib_transport", "dkvalg.sources.http_source"),
        ("user_agent", "dkvalg.sources.http_source"),
        ("utc_now", "dkvalg.sources.http_source"),
        ("overview_url", "dkvalg.sources.http_source"),
        ("DEFAULT_INTERVAL", "dkvalg.sources.http_source"),
        ("MIN_INTERVAL", "dkvalg.sources.http_source"),
        ("MAX_BACKOFF", "dkvalg.sources.http_source"),
        ("build_election", "dkvalg.sources.directory"),
        ("is_capture_directory", "dkvalg.sources.capture"),
        ("check_feed_name", "dkvalg.sources.capture"),
    ],
)
def test_the_helpers_stay_importable_from_their_own_modules(
    name: str, module: str
) -> None:
    assert hasattr(importlib.import_module(module), name)
