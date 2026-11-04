import importlib.metadata
import re
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import (
    NATIONAL,
    OVERVIEW,
    FakeClock,
    FakeTransport,
    FlakyRecorder,
    Request,
    entry,
    feed_xml,
    kreds_entry,
    overview_xml,
)

from dkvalg import (
    CaptureReplay,
    FeedError,
    FetchError,
    FetchResult,
    HttpSource,
    PlaceType,
    PollCycle,
    Recorder,
    load_election,
    poll,
)
from dkvalg.adapters.folketingsvalg import parse_overview
from dkvalg.sources import http_source
from dkvalg.sources.http_source import (
    DEFAULT_INTERVAL,
    MAX_BACKOFF,
    MIN_INTERVAL,
    HttpResponse,
    overview_url,
    urllib_transport,
    user_agent,
    utc_now,
)

THREE = [NATIONAL, "valgdag_20.xml", "valgdag_7.xml"]
AGENT = re.compile(r"dkvalg/\S+ \(\+https://github\.com/petermads123/valg_data\)")


def _source(
    transport: FakeTransport,
    recorder: Recorder | None = None,
    clock: Callable[[], datetime] | None = None,
) -> HttpSource:
    return HttpSource(
        "Valg2546527",
        transport=transport,
        recorder=recorder,
        clock=FakeClock() if clock is None else clock,
    )


def _ids(result: FetchResult) -> set[tuple[PlaceType, str]]:
    return {(p.place_type, p.place_id) for p in result.changed}


def _ids_of_files(names: list[str]) -> set[tuple[PlaceType, str]]:
    refs = {
        f.file_name: (f.place_type, f.place_id)
        for f in parse_overview(FakeTransport().files[OVERVIEW]).feeds
    }
    return {refs[name] for name in names}


def _folders(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def _feed_requests(transport: FakeTransport) -> list[Request]:
    return [r for r in transport.requests if r.name != OVERVIEW]


# --- constants and small helpers (A4) ------------------------------------------


def test_interval_constants_are_the_documented_seconds() -> None:
    assert (DEFAULT_INTERVAL, MIN_INTERVAL, MAX_BACKOFF) == (60.0, 15.0, 300.0)


def test_user_agent_names_the_installed_version_and_the_repository() -> None:
    agent = user_agent()

    assert AGENT.fullmatch(agent)
    assert agent.startswith(f"dkvalg/{importlib.metadata.version('dkvalg')} ")


def test_user_agent_reads_unknown_when_the_package_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)

    assert user_agent() == (
        "dkvalg/unknown (+https://github.com/petermads123/valg_data)"
    )


def test_utc_now_is_timezone_aware_utc() -> None:
    now = utc_now()

    assert now.utcoffset() is not None
    assert now.utcoffset().total_seconds() == 0  # type: ignore[union-attr]  # checked above


# --- overview_url (T6, A7) -----------------------------------------------------

DST_OVERVIEW = "https://www.dst.dk/valg/Valg2546527/xml/valgdag.xml"


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Valg2546527", DST_OVERVIEW),
        ("-", "https://www.dst.dk/valg/-/xml/valgdag.xml"),
        ("_", "https://www.dst.dk/valg/_/xml/valgdag.xml"),
        ("1", "https://www.dst.dk/valg/1/xml/valgdag.xml"),
        # any token of letters, digits, _ and - is taken as an id, Valg prefix or not
        ("junk", "https://www.dst.dk/valg/junk/xml/valgdag.xml"),
        ("https://h/x", "https://h/x/valgdag.xml"),
        ("https://h/x/", "https://h/x/valgdag.xml"),
        ("https://h/x///", "https://h/x/valgdag.xml"),
        ("https://h/x/valgdag.xml", "https://h/x/valgdag.xml"),
        ("https://h/valgdag.xml", "https://h/valgdag.xml"),
        ("https://h", "https://h/valgdag.xml"),
        ("https://h/", "https://h/valgdag.xml"),
        ("http://127.0.0.1:8080/", "http://127.0.0.1:8080/valgdag.xml"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080/valgdag.xml"),
        # a trailing slash after the file name and any letter case are normalised
        ("https://h/x/valgdag.xml/", "https://h/x/valgdag.xml"),
        ("https://h/x/VALGDAG.XML", "https://h/x/valgdag.xml"),
        ("https://h/x/Valgdag.Xml/", "https://h/x/valgdag.xml"),
        # a host that happens to be called valgdag.xml is a host, not the file
        ("https://valgdag.xml", "https://valgdag.xml/valgdag.xml"),
        # the scheme's letter case is kept as given
        ("HTTPS://H/x/", "HTTPS://H/x/valgdag.xml"),
    ],
)
def test_overview_url_accepts_an_id_a_folder_or_the_file(
    location: str, expected: str
) -> None:
    assert overview_url(location) == expected


@pytest.mark.parametrize("location", [DST_OVERVIEW, "https://h/x/valgdag.xml"])
def test_overview_url_is_idempotent_on_its_own_output(location: str) -> None:
    assert overview_url(overview_url(location)) == overview_url(location)


@pytest.mark.parametrize(
    "location",
    [
        "",
        " ",
        "Valg 1",
        " Valg1",
        "Valg1 ",
        "Valg1\n",
        "Valgæ",
        "file:///a/valgdag.xml",
        "ftp://h/",
        "//h/x/",
        "https://",
        "https:/h",
        "https://h/x?y=1",
        "https://h/x#f",
        "https://u:p@h/x/",
        "https://u@h/x/",
        "https://h:99999/x/",
        "https://h:0/x/",
        "https://h:abc/x/",
        "https://:80/x/",
        "https://h/x\n/",
        "https://h/x\t/",
        "https://h/ x/",
        "https://h/x\x00/",
        "https://h/ø/",
        "https://h/x /",
        "valg/2546527",
    ],
)
def test_overview_url_rejects_junk_credentials_and_control_characters(
    location: str,
) -> None:
    with pytest.raises(ValueError, match=re.escape(repr(location))):
        overview_url(location)


# --- urllib_transport against a loopback server (T6) ---------------------------


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, *_args: object) -> None:
        """Stay quiet when a client hangs up early."""


def _send(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes = b"",
    headers: Mapping[str, str] | None = None,
    length: int | None = None,
) -> None:
    handler.send_response(status)
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.send_header("Content-Length", str(len(body) if length is None else length))
    handler.end_headers()
    handler.wfile.write(body)


@contextmanager
def _serve(respond: Callable[[BaseHTTPRequestHandler], None]) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            respond(self)

        def log_message(self, format: str, *args: object) -> None:  # noqa: ARG002 - silence the server log
            return

    server = _Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_urllib_transport_returns_200_with_lower_cased_header_names() -> None:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        _send(handler, 200, b"<x/>", {"ETag": '"abc"', "Last-Modified": "now"})

    with _serve(respond) as base:
        response = urllib_transport(base + "/valgdag.xml", {}, 5.0)

    assert response.status == 200
    assert response.body == b"<x/>"
    assert response.headers["etag"] == '"abc"'
    assert response.headers["last-modified"] == "now"
    assert all(key == key.lower() for key in response.headers)


def test_urllib_transport_sends_the_given_headers() -> None:
    seen: dict[str, str] = {}

    def respond(handler: BaseHTTPRequestHandler) -> None:
        seen.update({k: v for k, v in handler.headers.items()})
        _send(handler, 200, b"")

    headers = {
        "User-Agent": user_agent(),
        "If-None-Match": '"abc"',
        "Accept": "text/xml",
    }
    with _serve(respond) as base:
        urllib_transport(base + "/x.xml", headers, 5.0)

    assert seen["User-Agent"] == user_agent()
    assert seen["If-None-Match"] == '"abc"'
    assert seen["Accept"] == "text/xml"


@pytest.mark.parametrize("status", [304, 404, 500, 503])
def test_urllib_transport_returns_other_statuses_as_responses(status: int) -> None:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        _send(handler, status, b"" if status == 304 else b"nope", {"ETag": '"e"'})

    with _serve(respond) as base:
        response = urllib_transport(base + "/x.xml", {}, 5.0)

    assert response.status == status
    assert response.headers["etag"] == '"e"'
    assert response.body == (b"" if status == 304 else b"nope")


def test_urllib_transport_does_not_flag_a_304_that_declares_a_content_length() -> None:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(304)
        handler.send_header("Content-Length", "500")
        handler.end_headers()

    with _serve(respond) as base:
        response = urllib_transport(base + "/x.xml", {}, 5.0)

    assert (response.status, response.body) == (304, b"")


def test_urllib_transport_rejects_a_body_shorter_than_its_content_length() -> None:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        _send(handler, 200, b"0123456789", length=1000)

    with _serve(respond) as base:
        url = base + "/valgdag.xml"
        with pytest.raises(FetchError, match=re.escape(url)):
            urllib_transport(url, {}, 5.0)


def test_urllib_transport_rejects_a_short_error_body_too() -> None:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        _send(handler, 500, b"oops", length=900)

    with _serve(respond) as base, pytest.raises(FetchError, match="Content-Length"):
        urllib_transport(base + "/x.xml", {}, 5.0)


def test_urllib_transport_accepts_a_body_of_exactly_the_cap() -> None:
    body = b"x" * 10_000_000

    def respond(handler: BaseHTTPRequestHandler) -> None:
        _send(handler, 200, body)

    with _serve(respond) as base:
        response = urllib_transport(base + "/x.xml", {}, 30.0)

    assert len(response.body) == 10_000_000


@pytest.mark.parametrize("status", [200, 500])
def test_urllib_transport_rejects_a_body_one_byte_over_the_cap(status: int) -> None:
    body = b"x" * 10_000_001

    def respond(handler: BaseHTTPRequestHandler) -> None:
        _send(handler, status, body)

    with _serve(respond) as base:
        url = base + "/x.xml"
        with pytest.raises(FetchError, match=re.escape(url)):
            urllib_transport(url, {}, 30.0)


def test_urllib_transport_turns_a_refused_connection_into_a_fetch_error() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}/valgdag.xml"

    with pytest.raises(FetchError, match=re.escape(url)):
        urllib_transport(url, {}, 5.0)


def test_urllib_transport_turns_a_read_timeout_into_a_fetch_error() -> None:
    release = threading.Event()

    def respond(_handler: BaseHTTPRequestHandler) -> None:
        release.wait(10)

    with _serve(respond) as base:
        url = base + "/valgdag.xml"
        try:
            with pytest.raises(FetchError, match=re.escape(url)):
                urllib_transport(url, {}, 0.3)
        finally:
            release.set()


def test_urllib_transport_turns_a_dropped_connection_into_a_fetch_error() -> None:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.connection.close()

    with _serve(respond) as base, pytest.raises(FetchError):
        urllib_transport(base + "/x.xml", {}, 5.0)


def test_urllib_transport_follows_a_redirect_to_the_same_server() -> None:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        if handler.path == "/old.xml":
            _send(handler, 301, headers={"Location": "/new.xml"})
        else:
            _send(handler, 200, b"moved")

    with _serve(respond) as base:
        response = urllib_transport(base + "/old.xml", {}, 5.0)

    assert (response.status, response.body) == (200, b"moved")


def test_urllib_transport_does_not_follow_a_redirect_to_a_file_url(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "secret.xml"
    secret.write_bytes(b"<secret/>")

    def respond(handler: BaseHTTPRequestHandler) -> None:
        _send(handler, 302, headers={"Location": secret.as_uri()})

    with _serve(respond) as base:
        try:
            response = urllib_transport(base + "/x.xml", {}, 5.0)
        except FetchError:
            return

    assert response.body != b"<secret/>"
    assert response.status == 302


def test_urllib_transport_keeps_the_last_of_two_headers_with_the_same_name() -> None:
    def respond(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("ETag", '"first"')
        handler.send_header("etag", '"second"')
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    with _serve(respond) as base:
        response = urllib_transport(base + "/x.xml", {}, 5.0)

    assert response.headers["etag"] == '"second"'


def test_urllib_transport_rejects_a_url_http_client_refuses() -> None:
    url = "http://127.0.0.1:1/x\r\nHost: evil"

    with pytest.raises(FetchError):
        urllib_transport(url, {}, 1.0)


# --- construction ---------------------------------------------------------------


@pytest.mark.parametrize(
    "timeout", [float("nan"), float("inf"), -float("inf"), 0, -1, -0.0, True, False]
)
def test_http_source_rejects_a_timeout_that_is_not_finite_and_positive(
    timeout: float,
) -> None:
    with pytest.raises(ValueError, match="timeout"):
        HttpSource("Valg2546527", timeout=timeout)


def test_http_source_timeout_error_names_the_value() -> None:
    with pytest.raises(ValueError, match="-1"):
        HttpSource("Valg2546527", timeout=-1)


@pytest.mark.parametrize("timeout", [5, 0.001, 20.0])
def test_http_source_accepts_a_positive_finite_timeout(timeout: float) -> None:
    HttpSource("Valg2546527", timeout=timeout)


@pytest.mark.parametrize(
    "location", ["", "Valg 1", "file:///x/valgdag.xml", "ftp://h/", "https://u:p@h/"]
)
def test_http_source_rejects_a_bad_location_naming_it(location: str) -> None:
    with pytest.raises(ValueError, match=re.escape(repr(location))):
        HttpSource(location)


def test_http_source_has_no_election_before_the_first_fetch() -> None:
    assert HttpSource("Valg2546527", transport=FakeTransport()).election is None


def test_http_source_clock_property_returns_the_injected_clock() -> None:
    clock = FakeClock()

    assert HttpSource("Valg2546527", clock=clock).clock is clock


def test_constructing_a_source_makes_no_request() -> None:
    transport = FakeTransport()

    HttpSource("Valg2546527", transport=transport)

    assert transport.requests == []


# --- the first fetch (T1, A1) ---------------------------------------------------


def test_first_fetch_equals_load_election_of_the_same_files(
    transport: FakeTransport, tmp_path: Path
) -> None:
    result = _source(transport).fetch()

    assert result.election == load_election(transport.write_to(tmp_path / "copy"))


def test_first_fetch_stores_the_election_on_the_source(
    transport: FakeTransport,
) -> None:
    source = _source(transport)

    result = source.fetch()

    assert source.election is result.election


def test_first_fetch_reports_every_reported_place_as_changed(
    transport: FakeTransport,
) -> None:
    result = _source(transport).fetch()

    assert result.changed == result.election.places
    assert len(result.changed) == 107


def test_first_fetch_requests_the_overview_then_each_listed_feed_once(
    transport: FakeTransport,
) -> None:
    _source(transport).fetch()

    listed = [f.file_name for f in parse_overview(transport.files[OVERVIEW]).feeds]
    assert transport.names[0] == OVERVIEW
    assert sorted(transport.names[1:]) == sorted(listed)
    assert "generel.xml" not in transport.names
    assert len(transport.requests) == 108


def test_first_fetch_builds_feed_urls_from_the_overview_folder(
    transport: FakeTransport,
) -> None:
    _source(transport).fetch()

    assert {r.url.rsplit("/", 1)[0] + "/" for r in transport.requests} == {
        "https://www.dst.dk/valg/Valg2546527/xml/"
    }


def test_first_fetch_sends_no_conditional_header_anywhere(
    transport: FakeTransport,
) -> None:
    _source(transport).fetch()

    assert not any(r.conditional for r in transport.requests)


@pytest.mark.parametrize("timeout", [20.0, 7.5])
def test_every_request_carries_the_user_agent_accept_and_the_timeout(
    transport: FakeTransport, timeout: float
) -> None:
    source = HttpSource(
        "Valg2546527", transport=transport, timeout=timeout, clock=FakeClock()
    )

    source.fetch()
    transport.touch(THREE)
    source.fetch()

    assert len(transport.requests) > 100
    for request in transport.requests:
        assert request.headers["User-Agent"] == user_agent()
        assert request.headers["Accept"] == "text/xml"
        assert request.timeout == timeout


def test_the_default_timeout_is_twenty_seconds(transport: FakeTransport) -> None:
    HttpSource("Valg2546527", transport=transport).fetch()

    assert {r.timeout for r in transport.requests} == {20.0}


def test_fetch_reads_the_clock_once_per_call_and_reports_that_time(
    transport: FakeTransport,
) -> None:
    clock = FakeClock()
    source = _source(transport, clock=clock)

    first = source.fetch()
    second = source.fetch()

    assert clock.calls == 2
    assert first.fetched_at == FakeClock()()
    assert second.fetched_at > first.fetched_at


def test_fetch_works_for_an_overview_url_location(transport: FakeTransport) -> None:
    source = HttpSource(
        "https://www.dst.dk/valg/Valg2546527/xml/valgdag.xml/",
        transport=transport,
        clock=FakeClock(),
    )

    assert len(source.fetch().changed) == 107


# --- later fetches: validators and unchanged answers (T2, A2) -------------------


def test_second_fetch_sends_only_the_overview_with_both_previous_validators(
    transport: FakeTransport,
) -> None:
    source = _source(transport)
    source.fetch()
    first_overview = transport.responses[0]
    transport.requests.clear()

    source.fetch()

    assert transport.names == [OVERVIEW]
    headers = transport.requests[0].headers
    assert headers["If-None-Match"] == first_overview.headers["etag"]
    assert headers["If-Modified-Since"] == first_overview.headers["last-modified"]


@pytest.mark.parametrize(
    "vary_etag", [False, True], ids=["304", "200-same-body-new-etag"]
)
def test_an_unchanged_overview_returns_the_same_election_and_no_changes(
    vary_etag: bool,
) -> None:
    transport = FakeTransport(vary_etag=vary_etag)
    source = _source(transport)
    first = source.fetch()
    transport.requests.clear()

    second = source.fetch()

    assert transport.responses[-1].status == (200 if vary_etag else 304)
    assert second.election is first.election
    assert second.changed == ()
    assert transport.names == [OVERVIEW]
    assert source.election is first.election


def test_an_identical_200_without_any_validators_is_also_no_change(
    transport: FakeTransport,
) -> None:
    source = _source(transport)
    first = source.fetch()
    body = transport.files[OVERVIEW]
    transport.script(OVERVIEW, HttpResponse(200, {}, body))
    transport.requests.clear()

    second = source.fetch()

    assert second.election is first.election
    assert second.changed == ()
    assert transport.names == [OVERVIEW]


def test_a_304_records_nothing_and_an_identical_200_records_only_the_overview(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    recorder = Recorder(tmp_path / "cap")
    source = _source(transport, recorder)
    source.fetch()
    source.fetch()  # 304
    assert len(_folders(tmp_path / "cap")) == 1

    transport.vary_etag = True
    source.fetch()  # 200, byte-identical

    folders = _folders(tmp_path / "cap")
    assert len(folders) == 2
    assert _folders(tmp_path / "cap" / folders[1]) == [OVERVIEW]
    assert (tmp_path / "cap" / folders[1] / OVERVIEW).read_bytes() == transport.files[
        OVERVIEW
    ]


def test_the_new_etag_of_an_identical_200_is_the_one_sent_next(
    transport: FakeTransport,
) -> None:
    source = _source(transport)
    source.fetch()
    transport.vary_etag = True
    source.fetch()
    newest = transport.responses[-1].headers["etag"]
    transport.requests.clear()

    source.fetch()

    assert transport.requests[0].headers["If-None-Match"] == newest


@pytest.mark.parametrize(
    ("given", "if_none_match", "if_modified_since"),
    [
        ({"etag": '"a"', "last-modified": "LM"}, '"a"', "LM"),
        ({"etag": '"a"'}, '"a"', None),
        ({"last-modified": "LM"}, None, "LM"),
        ({}, None, None),
        ({"etag": 'W/"weak"', "last-modified": "LM"}, 'W/"weak"', "LM"),
        ({"etag": "", "last-modified": "LM"}, None, "LM"),
        ({"etag": '"a"', "last-modified": ""}, '"a"', None),
        ({"etag": "", "last-modified": ""}, None, None),
        # a transport must lower-case header names; a mixed-case key is not seen
        ({"ETag": '"a"', "Last-Modified": "LM"}, None, None),
    ],
    ids=[
        "both",
        "etag-only",
        "last-modified-only",
        "neither",
        "weak-etag-verbatim",
        "empty-etag",
        "empty-last-modified",
        "both-empty",
        "mixed-case-names-ignored",
    ],
)
def test_only_the_validators_a_response_carried_are_sent_back(
    transport: FakeTransport,
    given: dict[str, str],
    if_none_match: str | None,
    if_modified_since: str | None,
) -> None:
    source = _source(transport)
    transport.script(OVERVIEW, HttpResponse(200, given, transport.files[OVERVIEW]))
    source.fetch()
    transport.requests.clear()

    source.fetch()

    headers = transport.requests[0].headers
    assert headers.get("If-None-Match") == if_none_match
    assert headers.get("If-Modified-Since") == if_modified_since


def test_a_304_on_the_very_first_fetch_is_a_fetch_error(
    transport: FakeTransport,
) -> None:
    transport.script(OVERVIEW, HttpResponse(304, {}, b""))
    source = _source(transport)

    with pytest.raises(FetchError, match="304"):
        source.fetch()

    assert source.election is None


def test_a_304_for_a_feed_nothing_is_held_for_is_a_fetch_error(
    transport: FakeTransport,
) -> None:
    transport.script("valgdag_20.xml", HttpResponse(304, {}, b""))
    source = _source(transport)

    with pytest.raises(FetchError, match=r"valgdag_20\.xml.*304"):
        source.fetch()

    assert source.election is None


@pytest.mark.parametrize("status", [204, 206, 301, 302, 400, 404, 500, 503])
@pytest.mark.parametrize("target", [OVERVIEW, "valgdag_20.xml"])
def test_any_status_but_200_and_304_is_a_fetch_error_naming_url_and_status(
    transport: FakeTransport, target: str, status: int
) -> None:
    transport.script(target, HttpResponse(status, {}, b"x"))
    source = _source(transport)

    with pytest.raises(FetchError) as caught:
        source.fetch()

    assert f"https://www.dst.dk/valg/Valg2546527/xml/{target}" in str(caught.value)
    assert str(status) in str(caught.value)
    assert source.election is None


def test_an_empty_200_overview_after_a_good_fetch_is_not_taken_as_unchanged(
    transport: FakeTransport,
) -> None:
    source = _source(transport)
    good = source.fetch()
    transport.script(OVERVIEW, HttpResponse(200, {}, b""))

    with pytest.raises(FeedError, match="malformed"):
        source.fetch()

    assert source.election is good.election


# --- later fetches: only newer feeds (T3, A3) -----------------------------------


def test_only_the_feeds_with_a_newer_timestamp_are_requested_conditionally(
    transport: FakeTransport,
) -> None:
    source = _source(transport)
    source.fetch()
    transport.touch(THREE)
    transport.requests.clear()

    source.fetch()

    assert transport.names[0] == OVERVIEW
    assert sorted(transport.names[1:]) == sorted(THREE)
    for request in _feed_requests(transport):
        assert "If-None-Match" in request.headers
        assert "If-Modified-Since" in request.headers


def test_a_feed_request_uses_the_feeds_own_validators_not_the_overviews(
    transport: FakeTransport,
) -> None:
    source = _source(transport)
    source.fetch()
    first = {
        r.name: resp
        for r, resp in zip(transport.requests, transport.responses, strict=True)
    }
    transport.touch(THREE)
    transport.requests.clear()

    source.fetch()

    for request in _feed_requests(transport):
        assert request.headers["If-None-Match"] == first[request.name].headers["etag"]
        assert request.headers["If-None-Match"] != first[OVERVIEW].headers["etag"]


def test_the_changed_list_names_exactly_the_touched_places(
    transport: FakeTransport, tmp_path: Path
) -> None:
    source = _source(transport)
    before = source.fetch()
    transport.touch(THREE)

    after = source.fetch()

    assert _ids(after) == _ids_of_files(THREE)
    assert len(after.changed) == 3
    assert after.election == load_election(transport.write_to(tmp_path / "now"))
    differing = {
        (p.place_type, p.place_id)
        for p in after.election.places
        if p != before.election.get(p.place_type, p.place_id)
    }
    assert differing == _ids_of_files(THREE)


def test_the_changed_list_follows_the_election_order(transport: FakeTransport) -> None:
    source = _source(transport)
    source.fetch()
    transport.touch(THREE)

    after = source.fetch()

    positions = [after.election.places.index(p) for p in after.changed]
    assert positions == sorted(positions)


def test_a_third_fetch_after_a_change_requests_only_the_overview(
    transport: FakeTransport,
) -> None:
    source = _source(transport)
    source.fetch()
    transport.touch(THREE)
    source.fetch()
    transport.requests.clear()

    third = source.fetch()

    assert transport.names == [OVERVIEW]
    assert third.changed == ()


def test_a_feed_going_from_never_reported_to_reported_is_fetched_unconditionally(
    transport: FakeTransport,
) -> None:
    transport.never_reported("valgdag_20.xml")
    source = _source(transport)
    first = source.fetch()
    assert "valgdag_20.xml" not in transport.names
    assert first.election.get(PlaceType.OPSTILLINGSKREDS, "20").last_changed is None
    assert len(first.changed) == 106
    transport.touch(["valgdag_20.xml"])
    transport.requests.clear()

    second = source.fetch()

    request = _feed_requests(transport)[0]
    assert request.name == "valgdag_20.xml"
    assert not request.conditional
    assert _ids(second) == _ids_of_files(["valgdag_20.xml"])


def test_a_feed_going_back_to_never_reported_is_dropped_and_not_listed_as_changed(
    transport: FakeTransport,
) -> None:
    source = _source(transport)
    source.fetch()
    transport.never_reported("valgdag_20.xml")
    transport.requests.clear()

    second = source.fetch()

    assert transport.names == [OVERVIEW]
    assert second.changed == ()
    place = second.election.get(PlaceType.OPSTILLINGSKREDS, "20")
    assert place.last_changed is None
    assert place.parties == ()
    assert second.election.counting_progress().counted == 91

    transport.touch(["valgdag_20.xml"], "2026-03-25T02:00:00")
    transport.requests.clear()
    third = source.fetch()

    request = _feed_requests(transport)[0]
    assert not request.conditional  # the held body was dropped, so no validators
    assert _ids(third) == _ids_of_files(["valgdag_20.xml"])


def test_a_feed_removed_from_the_overview_leaves_the_election_and_is_not_requested(
    transport: FakeTransport,
) -> None:
    source = _source(transport)
    source.fetch()
    lines = transport.files[OVERVIEW].decode("utf-8").split("\n")
    kept = [line for line in lines if '/valgdag_20.xml"' not in line]
    assert len(kept) == len(lines) - 1
    transport.publish(OVERVIEW, "\n".join(kept).encode("utf-8"))
    transport.requests.clear()

    second = source.fetch()

    assert transport.names == [OVERVIEW]
    assert len(second.election.places) == 106
    assert second.changed == ()
    with pytest.raises(KeyError):
        second.election.get(PlaceType.OPSTILLINGSKREDS, "20")


@pytest.mark.parametrize(
    "vary_etag", [False, True], ids=["feed-304", "feed-200-same-body"]
)
def test_a_moved_timestamp_with_an_identical_feed_body_is_no_change(
    vary_etag: bool,
) -> None:
    transport = FakeTransport(vary_etag=vary_etag)
    source = _source(transport)
    first = source.fetch()
    transport.retime_only(THREE)
    transport.requests.clear()

    second = source.fetch()

    assert sorted(transport.names[1:]) == sorted(THREE)
    assert second.changed == ()
    assert second.election == first.election
    transport.requests.clear()
    source.fetch()
    assert transport.names == [OVERVIEW]  # the held timestamps moved forward


def test_an_overview_that_changed_without_newer_timestamps_requests_no_feed(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    recorder = FlakyRecorder(tmp_path / "cap", fail_on=[])
    source = _source(transport, recorder)
    first = source.fetch()
    reserialised = transport.files[OVERVIEW] + b"\n<!-- a reserialised copy -->\n"
    transport.publish(OVERVIEW, reserialised)
    transport.requests.clear()

    second = source.fetch()

    assert transport.names == [OVERVIEW]
    assert second.changed == ()
    assert second.election == first.election
    assert recorder.calls[-1][1] == {OVERVIEW: reserialised}
    transport.vary_etag = True
    third = source.fetch()  # byte-identical to the latest accepted overview
    assert third.election is second.election
    assert recorder.calls[-1][1] == {OVERVIEW: reserialised}
    assert third.changed == ()


def test_a_shared_file_name_is_requested_per_listing_and_both_places_are_built() -> (
    None
):
    overview = overview_xml(
        [
            kreds_entry("20", "A"),
            entry(
                "Opstillingskreds",
                "B",
                "valgdag_20.xml",
                opstillingskreds_id="21",
                storkreds_id="10",
            ),
        ]
    )
    transport = FakeTransport(
        {OVERVIEW: overview, "valgdag_20.xml": feed_xml()},
        base_url="https://www.dst.dk/valg/Valg1/xml/",
    )
    source = HttpSource("Valg1", transport=transport, clock=FakeClock())

    result = source.fetch()

    assert [p.place_id for p in result.election.places] == ["20", "21"]
    assert transport.names == [OVERVIEW, "valgdag_20.xml", "valgdag_20.xml"]


# --- unsafe feed names (T4) ------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "C:x.xml",
        "a#b.xml",
        "valgdag.xml",
        "VALGDAG.xml",
        "Valgdag.xml",
        "x y.xml",
        "ñ.xml",
        ".xml",
        "a.txt",
        "x.xml.bak",
        "X.XML",
        "a%2Fb.xml",
        "a?b.xml",
    ],
)
def test_an_overview_listing_an_unsafe_name_is_refused_before_any_feed_request(
    transport: FakeTransport, bad: str
) -> None:
    source = _source(transport)
    good = source.fetch()
    text = transport.files[OVERVIEW].decode("utf-8")
    transport.publish(
        OVERVIEW, text.replace('/valgdag_20.xml"', f'/{bad}"').encode("utf-8")
    )
    transport.requests.clear()

    with pytest.raises(FeedError, match="unsafe feed file name"):
        source.fetch()

    assert transport.names == [OVERVIEW]
    assert source.election is good.election


@pytest.mark.parametrize("bad", ["C:x.xml", "a#b.xml", "valgdag.xml"])
def test_an_unsafe_name_on_the_first_fetch_requests_only_the_overview(
    transport: FakeTransport, bad: str
) -> None:
    text = transport.files[OVERVIEW].decode("utf-8")
    transport.publish(
        OVERVIEW, text.replace('/valgdag_20.xml"', f'/{bad}"').encode("utf-8")
    )
    source = _source(transport)

    with pytest.raises(FeedError):
        source.fetch()

    assert transport.names == [OVERVIEW]
    assert source.election is None


# --- failures leave state untouched (T4) ----------------------------------------

DOCTYPE_BODY = b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "b">]><Data/>'

FEED_FAILURES = [
    pytest.param(FetchError("connection reset"), id="network-error"),
    pytest.param(HttpResponse(500, {}, b"oops"), id="http-500"),
    pytest.param(HttpResponse(404, {}, b""), id="http-404"),
    pytest.param(HttpResponse(200, {}, b"<Data><unclosed"), id="malformed-feed"),
    pytest.param(HttpResponse(200, {}, b""), id="empty-feed"),
    pytest.param(HttpResponse(200, {}, DOCTYPE_BODY), id="doctype-feed"),
]

OVERVIEW_FAILURES = [
    pytest.param(FetchError("connection reset"), id="network-error"),
    pytest.param(HttpResponse(500, {}, b"oops"), id="http-500"),
    pytest.param(HttpResponse(404, {}, b""), id="http-404"),
    pytest.param(HttpResponse(200, {}, b"<Data><unclosed"), id="malformed-overview"),
    pytest.param(HttpResponse(200, {}, DOCTYPE_BODY), id="doctype-overview"),
    pytest.param(HttpResponse(200, {}, b""), id="empty-overview"),
]


@pytest.mark.parametrize("failure", FEED_FAILURES)
def test_a_failure_on_the_second_of_three_feeds_changes_nothing_and_records_nothing(
    tmp_path: Path, failure: HttpResponse | Exception
) -> None:
    transport = FakeTransport()
    capture = tmp_path / "cap"
    source = _source(transport, Recorder(capture))
    good = source.fetch()
    transport.touch(THREE)
    second_requested = sorted(THREE, key=lambda n: _feed_order(transport).index(n))[1]
    transport.script(second_requested, failure)
    transport.requests.clear()

    with pytest.raises(FeedError):
        source.fetch()

    assert source.election is good.election
    assert len(_folders(capture)) == 1
    assert not any(name.startswith(".tmp-") for name in _folders(capture))

    transport.requests.clear()
    retry = source.fetch()

    assert sorted(transport.names[1:]) == sorted(THREE)  # all three, not just two
    assert _ids(retry) == _ids_of_files(THREE)
    assert len(_folders(capture)) == 2


def _feed_order(transport: FakeTransport) -> list[str]:
    """The order in which the overview lists feeds, which is the request order."""
    return [f.file_name for f in parse_overview(transport.files[OVERVIEW]).feeds]


@pytest.mark.parametrize("failure", OVERVIEW_FAILURES)
def test_a_failing_overview_keeps_the_last_good_election_and_the_next_fetch_recovers(
    tmp_path: Path, failure: HttpResponse | Exception
) -> None:
    transport = FakeTransport()
    capture = tmp_path / "cap"
    source = _source(transport, Recorder(capture))
    good = source.fetch()
    transport.touch(THREE)
    transport.script(OVERVIEW, failure)

    with pytest.raises(FeedError):
        source.fetch()

    assert source.election is good.election
    assert len(_folders(capture)) == 1
    retry = source.fetch()
    assert _ids(retry) == _ids_of_files(THREE)


@pytest.mark.parametrize("failure", FEED_FAILURES)
def test_a_failing_feed_on_the_first_fetch_leaves_the_source_empty(
    failure: HttpResponse | Exception,
) -> None:
    transport = FakeTransport()
    transport.script("valgdag_20.xml", failure)
    source = _source(transport)

    with pytest.raises(FeedError):
        source.fetch()

    assert source.election is None
    transport.requests.clear()
    assert len(source.fetch().changed) == 107
    assert len(transport.requests) == 108  # nothing was held from the failed try


def test_a_doctype_feed_error_names_the_feed(transport: FakeTransport) -> None:
    transport.script("valgdag_20.xml", HttpResponse(200, {}, DOCTYPE_BODY))

    with pytest.raises(FeedError, match=r"valgdag_20\.xml.*DOCTYPE"):
        _source(transport).fetch()


def test_a_recorder_that_fails_on_fetch_two_changes_nothing_and_fetch_three_records_the_full_set(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    recorder = FlakyRecorder(tmp_path / "cap", fail_on=[2])
    source = _source(transport, recorder)
    first = source.fetch()
    two = ["valgdag_20.xml", "valgdag_7.xml"]
    transport.touch(two)
    transport.requests.clear()

    with pytest.raises(FeedError, match="disk full"):
        source.fetch()

    assert source.election is first.election
    transport.requests.clear()
    third = source.fetch()

    assert sorted(transport.names[1:]) == sorted(two)
    assert all(r.conditional for r in _feed_requests(transport))
    assert _ids(third) == _ids_of_files(two)
    assert set(recorder.calls[-1][1]) == {OVERVIEW, *two}
    steps = list(CaptureReplay(tmp_path / "cap", speed=float("inf")))
    assert len(steps) == 2
    assert steps[-1].election == source.election
    assert steps[-1].changed == third.changed


def test_a_disk_error_from_the_recorder_is_a_feed_error_and_state_is_kept(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "cap"
    blocker.write_bytes(b"not a directory")
    source = _source(FakeTransport(), Recorder(blocker))

    with pytest.raises(FeedError, match="cannot write capture"):
        source.fetch()

    assert source.election is None


def test_a_naive_clock_with_a_recorder_is_a_loud_value_error_not_a_feed_error(
    tmp_path: Path,
) -> None:
    def naive() -> datetime:
        return datetime.fromisoformat("2026-03-24T20:00:00")

    source = _source(FakeTransport(), Recorder(tmp_path / "cap"), clock=naive)

    with pytest.raises(ValueError, match="timezone-aware"):
        source.fetch()

    assert source.election is None


def test_a_stuck_clock_with_a_recorder_never_overwrites_an_earlier_capture(
    tmp_path: Path,
) -> None:
    def stuck() -> datetime:
        return datetime.fromisoformat("2026-03-24T20:00:00+00:00")

    transport = FakeTransport()
    capture = tmp_path / "cap"
    source = _source(transport, Recorder(capture), clock=stuck)
    first = source.fetch()
    before = (capture / _folders(capture)[0] / OVERVIEW).read_bytes()
    transport.touch(THREE)

    with pytest.raises(FeedError, match="already exists"):
        source.fetch()

    assert source.election is first.election
    assert (capture / _folders(capture)[0] / OVERVIEW).read_bytes() == before


def test_a_fetch_that_fails_midway_records_nothing_even_though_it_received_bodies(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    capture = tmp_path / "cap"
    source = _source(transport, Recorder(capture))
    transport.script("valgdag_20.xml", HttpResponse(500, {}, b""))

    with pytest.raises(FetchError):
        source.fetch()

    assert not capture.exists()


# --- thread safety (T12) ---------------------------------------------------------


def test_two_threads_calling_fetch_never_run_inside_the_transport_together(
    transport: FakeTransport,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    guard = threading.Lock()
    state = {"inside": 0, "peak": 0}

    def slow(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        with guard:
            state["inside"] += 1
            state["peak"] = max(state["peak"], state["inside"])
        entered.set()
        release.wait(10)
        try:
            return transport(url, headers, timeout)
        finally:
            with guard:
                state["inside"] -= 1

    source = HttpSource("Valg2546527", transport=slow, clock=FakeClock())
    results: list[FetchResult] = []
    threads = [
        threading.Thread(target=lambda: results.append(source.fetch()))
        for _ in range(2)
    ]

    threads[0].start()
    assert entered.wait(5)
    threads[1].start()
    still_blocked = not release.wait(0.3)  # the second fetch waits on the lock
    peak_while_blocked = state["peak"]
    release.set()
    for thread in threads:
        thread.join(30)

    assert still_blocked
    assert peak_while_blocked == 1
    assert state["peak"] == 1
    assert sorted(len(r.changed) for r in results) == [0, 107]


# --- poll (T4, T5, A4, A5) --------------------------------------------------------


class _Pattern:
    """A transport that fails the overview request on the cycles marked False."""

    def __init__(self, inner: FakeTransport, pattern: list[bool]) -> None:
        self.inner = inner
        self.pattern = pattern
        self.cycle = 0

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        if url.endswith("/" + OVERVIEW):
            ok = self.pattern[min(self.cycle, len(self.pattern) - 1)]
            self.cycle += 1
            if not ok:
                raise FetchError(f"{url}: connection reset")
        return self.inner(url, headers, timeout)


def _run(
    pattern: list[bool],
    *,
    interval: float = 60.0,
    max_cycles: int | None = None,
    stop: Callable[[], bool] | None = None,
    recorder: Recorder | None = None,
) -> tuple[list[PollCycle], list[float], FakeClock, FakeTransport]:
    inner = FakeTransport()
    clock = FakeClock()
    source = HttpSource(
        "Valg2546527",
        transport=_Pattern(inner, pattern),
        recorder=recorder,
        clock=clock,
    )
    sleeps: list[float] = []
    cycles = list(
        poll(
            source,
            interval=interval,
            max_cycles=len(pattern) if max_cycles is None else max_cycles,
            stop=stop,
            sleep=sleeps.append,
        )
    )
    return cycles, sleeps, clock, inner


def test_poll_waits_120_240_300_300_then_60_after_a_success_then_120_again() -> None:
    pattern = [False, False, False, False, False, True, False]

    cycles, sleeps, _, _ = _run(pattern)

    assert [c.wait for c in cycles] == [120, 240, 300, 300, 300, 60, 120]
    assert sleeps == [120, 240, 300, 300, 300, 60]  # nothing after the last cycle


@pytest.mark.parametrize(
    ("interval", "expected"),
    [
        (60.0, [120, 240, 300, 300]),
        (15.0, [30, 60, 120, 240, 300, 300]),
        (300.0, [300, 300, 300]),
        (400.0, [400, 400, 400]),
        (15.0000001, [30.0000002, 60.0000004, 120.0000008, 240.0000016, 300, 300]),
    ],
)
def test_poll_backoff_doubles_to_the_cap_or_the_interval_if_that_is_larger(
    interval: float, expected: list[float]
) -> None:
    cycles, _, _, _ = _run([False] * len(expected), interval=interval)

    assert [c.wait for c in cycles] == pytest.approx(expected)


def test_poll_cycle_numbers_start_at_one_and_count_up() -> None:
    cycles, _, _, _ = _run([True, True, True])

    assert [c.number for c in cycles] == [1, 2, 3]


def test_a_successful_cycle_carries_the_election_changes_and_the_interval() -> None:
    cycles, sleeps, _, _ = _run([True, True], interval=90.0)

    first, second = cycles
    assert first.error is None
    assert first.election is not None
    assert len(first.changed) == 107
    assert first.wait == 90.0
    assert second.election is first.election
    assert second.changed == ()
    assert sleeps == [90.0]


def test_a_failed_first_cycle_has_no_election_and_no_changes() -> None:
    cycles, _, _, _ = _run([False])

    (cycle,) = cycles
    assert cycle.election is None
    assert cycle.changed == ()
    assert isinstance(cycle.error, FetchError)


def test_a_later_failed_cycle_keeps_the_last_good_election() -> None:
    cycles, _, _, _ = _run([True, False])

    good, bad = cycles
    assert bad.election is good.election
    assert bad.changed == ()
    assert bad.error is not None


def test_the_cycle_after_a_failed_first_one_recovers_with_every_place_changed() -> None:
    source = HttpSource(
        "Valg2546527",
        transport=_Pattern(FakeTransport(), [False, True]),
        clock=FakeClock(),
    )

    failed, recovered = poll(source, max_cycles=2, sleep=lambda _s: None)

    assert failed.error is not None
    assert recovered.error is None
    assert len(recovered.changed) == 107


def test_poll_reads_the_clock_once_per_cycle_and_stamps_the_cycle_with_it() -> None:
    cycles, _, clock, _ = _run([True, False, True])

    assert clock.calls == 3
    assert [c.at for c in cycles] == sorted(c.at for c in cycles)
    assert len({c.at for c in cycles}) == 3


def test_each_recorded_cycles_at_is_the_name_of_its_capture_folder(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "cap"
    inner = FakeTransport()
    source = HttpSource(
        "Valg2546527",
        transport=inner,
        recorder=Recorder(capture),
        clock=FakeClock(),
    )
    waits = iter([lambda: inner.touch(THREE), lambda: None])

    cycles = list(poll(source, max_cycles=3, sleep=lambda _s: next(waits)()))

    # cycle 1 is a full fetch, 2 a partial one, 3 a 304 that records nothing
    assert _folders(capture) == [c.at.strftime("%Y%m%dT%H%M%S.%fZ") for c in cycles[:2]]
    assert len(cycles[1].changed) == 3
    assert cycles[2].changed == ()


def test_a_cycles_at_is_the_fetch_time_the_recorder_received() -> None:
    clock = FakeClock()
    recorder = FlakyRecorder(Path("/nonexistent-never-written"), fail_on=[1])
    source = HttpSource(
        "Valg2546527", transport=FakeTransport(), recorder=recorder, clock=clock
    )

    (cycle,) = poll(source, max_cycles=1, sleep=lambda _s: None)

    assert (
        cycle.error is not None
    )  # the recorder was told to fail; it still got the time
    assert recorder.calls[0][0] == cycle.at
    assert clock.calls == 1


def test_poll_stops_after_max_cycles_and_never_sleeps_after_the_last() -> None:
    cycles, sleeps, _, _ = _run([True] * 5, max_cycles=3)

    assert len(cycles) == 3
    assert sleeps == [60.0, 60.0]


def test_poll_with_one_cycle_does_not_sleep_at_all() -> None:
    cycles, sleeps, _, _ = _run([True], max_cycles=1)

    assert len(cycles) == 1
    assert sleeps == []


def test_poll_stop_is_checked_after_each_cycle() -> None:
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] >= 2

    cycles, sleeps, _, _ = _run([True] * 9, max_cycles=9, stop=stop)

    assert len(cycles) == 2
    assert sleeps == [60.0]


def test_poll_without_a_limit_runs_until_stop_says_so() -> None:
    inner = FakeTransport()
    source = HttpSource("Valg2546527", transport=inner, clock=FakeClock())
    sleeps: list[float] = []
    seen: list[int] = []

    def stop() -> bool:
        return len(seen) >= 4

    for cycle in poll(source, stop=stop, sleep=sleeps.append):
        seen.append(cycle.number)

    assert seen == [1, 2, 3, 4]
    assert len(sleeps) == 3


def test_poll_does_not_sleep_when_stop_and_max_cycles_hit_together() -> None:
    cycles, sleeps, _, _ = _run([True] * 3, max_cycles=2, stop=lambda: True)

    assert len(cycles) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "interval",
    [14.999, 14.0, 0, -1, -15.0, float("nan"), float("inf"), -float("inf"), True],
)
def test_poll_rejects_a_bad_interval_at_call_time_before_any_request(
    interval: float,
) -> None:
    transport = FakeTransport()
    source = HttpSource("Valg2546527", transport=transport, clock=FakeClock())

    with pytest.raises(ValueError, match="interval"):
        poll(source, interval=interval)

    assert transport.requests == []


def test_poll_interval_error_names_the_value() -> None:
    source = HttpSource("Valg2546527", transport=FakeTransport())

    with pytest.raises(ValueError, match=r"14\.9"):
        poll(source, interval=14.9)


@pytest.mark.parametrize("max_cycles", [0, -1, True, False, 2.5, 1.0, "3"])
def test_poll_rejects_a_max_cycles_that_is_not_an_integer_of_at_least_one(
    max_cycles: int,
) -> None:
    transport = FakeTransport()
    source = HttpSource("Valg2546527", transport=transport, clock=FakeClock())

    with pytest.raises(ValueError, match="max_cycles"):
        poll(source, max_cycles=max_cycles)

    assert transport.requests == []


@pytest.mark.parametrize("interval", [15, 15.0, 15.5, 60, 3600.0])
def test_poll_accepts_the_floor_and_anything_above(interval: float) -> None:
    source = HttpSource("Valg2546527", transport=FakeTransport(), clock=FakeClock())

    cycles = list(poll(source, interval=interval, max_cycles=1))

    assert cycles[0].wait == interval


def test_poll_does_nothing_until_it_is_iterated() -> None:
    transport = FakeTransport()
    clock = FakeClock()
    source = HttpSource("Valg2546527", transport=transport, clock=clock)

    poll(source, max_cycles=1)

    assert transport.requests == []
    assert clock.calls == 0


def test_poll_lets_a_keyboard_interrupt_from_the_transport_propagate() -> None:
    def interrupted(
        url: str,  # noqa: ARG001 - signature fixed by the Transport protocol
        headers: Mapping[str, str],  # noqa: ARG001 - signature fixed by the Transport protocol
        timeout: float,  # noqa: ARG001 - signature fixed by the Transport protocol
    ) -> HttpResponse:
        raise KeyboardInterrupt

    source = HttpSource("Valg2546527", transport=interrupted, clock=FakeClock())

    with pytest.raises(KeyboardInterrupt):
        next(poll(source, max_cycles=2, sleep=lambda _s: None))


def test_poll_lets_a_naive_clock_with_a_recorder_raise_a_value_error(
    tmp_path: Path,
) -> None:
    def naive() -> datetime:
        return datetime.fromisoformat("2026-03-24T20:00:00")

    source = HttpSource(
        "Valg2546527",
        transport=FakeTransport(),
        recorder=Recorder(tmp_path / "cap"),
        clock=naive,
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        next(poll(source, max_cycles=1))


def test_poll_never_touches_the_network_or_the_real_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("real network or sleep used")

    monkeypatch.setattr(time, "sleep", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(http_source.urllib.request, "urlopen", forbidden)

    cycles, sleeps, _, _ = _run([True, False, True])

    assert len(cycles) == 3
    assert len(sleeps) == 2
