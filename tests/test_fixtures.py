import hashlib
from pathlib import Path

import pytest
from conftest import ROOT

from dkvalg.adapters.folketingsvalg import parse_overview


def _manifest(fixture_dir: Path) -> dict[str, str]:
    entries = {}
    for line in (fixture_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        entries[name] = digest
    return entries


def test_fixture_directory_holds_109_xml_files_a_readme_and_a_manifest(
    fixture_dir: Path,
) -> None:
    xml = sorted(p.name for p in fixture_dir.glob("*.xml"))

    assert len(xml) == 109
    assert "generel.xml" in xml
    assert "valgdag.xml" in xml
    assert sorted(p.name for p in fixture_dir.iterdir() if p.suffix != ".xml") == [
        "README.md",
        "SHA256SUMS",
    ]


def test_every_feed_the_overview_lists_is_present(fixture_dir: Path) -> None:
    overview = parse_overview((fixture_dir / "valgdag.xml").read_bytes())

    missing = [
        f.file_name for f in overview.feeds if not (fixture_dir / f.file_name).is_file()
    ]

    assert missing == []
    assert len({f.file_name for f in overview.feeds}) == 107


def test_the_manifest_lists_exactly_the_xml_files(fixture_dir: Path) -> None:
    assert sorted(_manifest(fixture_dir)) == sorted(
        p.name for p in fixture_dir.glob("*.xml")
    )


def test_every_file_matches_its_sha256_in_the_manifest(fixture_dir: Path) -> None:
    mismatched = [
        name
        for name, digest in _manifest(fixture_dir).items()
        if hashlib.sha256((fixture_dir / name).read_bytes()).hexdigest() != digest
    ]

    assert mismatched == []


def test_every_xml_file_keeps_its_utf8_byte_order_mark(fixture_dir: Path) -> None:
    without = [
        p.name
        for p in fixture_dir.glob("*.xml")
        if not p.read_bytes().startswith(b"\xef\xbb\xbf")
    ]

    assert without == []


def test_no_xml_file_had_its_line_endings_rewritten(fixture_dir: Path) -> None:
    crlf = [p.name for p in fixture_dir.glob("*.xml") if b"\r\n" in p.read_bytes()]
    lf_only = [
        p.name for p in fixture_dir.glob("*.xml") if b"\r\n" not in p.read_bytes()
    ]

    assert not (crlf and lf_only), "mixed line endings suggest a checkout rewrote them"


def test_the_documentation_pdf_exists_and_is_a_pdf() -> None:
    pdf = ROOT / "docs" / "XmlFeeds20260305.pdf"

    assert pdf.is_file()
    assert pdf.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize(
    "needle",
    [
        "https://www.dst.dk/valg/Valg2546527/xml/",
        "generel.xml",
        "valgdag.xml",
        "2026-11-03",
        "XmlFeeds20260305.pdf",
        "https://dst.dk/Valg/XmlFeeds20260305.pdf",
    ],
)
def test_the_fixtures_readme_names_the_sources_and_the_retrieval_date(
    fixture_dir: Path, needle: str
) -> None:
    assert needle in (fixture_dir / "README.md").read_text(encoding="utf-8")


def test_gitattributes_keeps_the_fixtures_unmodified_on_checkout() -> None:
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "tests/fixtures/** -text" in text.splitlines()


def test_the_fixtures_are_the_march_2026_election(fixture_dir: Path) -> None:
    overview = parse_overview((fixture_dir / "valgdag.xml").read_bytes())

    assert overview.election_date.isoformat() == "2026-03-24"
