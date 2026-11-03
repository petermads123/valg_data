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
