import pytest

from dkvalg import FeedError, FetchError


def test_feed_error_is_an_exception_that_keeps_its_message() -> None:
    assert str(FeedError("valgdag.xml: not found")) == "valgdag.xml: not found"


@pytest.mark.parametrize("other", [ValueError, KeyError, OSError])
def test_feed_error_is_not_a_subclass_of_common_builtin_errors(
    other: type[Exception],
) -> None:
    assert not issubclass(FeedError, other)


def test_feed_error_keeps_the_original_cause() -> None:
    cause = ValueError("boom")
    with pytest.raises(FeedError) as caught:
        try:
            raise cause
        except ValueError as error:
            raise FeedError("wrapped") from error
    assert caught.value.__cause__ is cause


# --- FetchError (A4, A7) ---------------------------------------------------------


def test_fetch_error_is_a_feed_error_and_an_exception() -> None:
    assert issubclass(FetchError, FeedError)
    assert issubclass(FetchError, Exception)


def test_fetch_error_keeps_its_message() -> None:
    message = "https://h/valgdag.xml: HTTP status 503"

    assert str(FetchError(message)) == message


@pytest.mark.parametrize("other", [ValueError, KeyError, OSError, TimeoutError])
def test_fetch_error_is_not_a_subclass_of_common_builtin_errors(
    other: type[Exception],
) -> None:
    assert not issubclass(FetchError, other)


def test_a_feed_error_handler_also_catches_a_fetch_error() -> None:
    with pytest.raises(FeedError):
        raise FetchError("down")


def test_a_plain_feed_error_is_not_a_fetch_error() -> None:
    assert not issubclass(FeedError, FetchError)
    assert not isinstance(FeedError("bad xml"), FetchError)


def test_fetch_error_keeps_the_original_cause() -> None:
    cause = OSError("connection refused")
    with pytest.raises(FetchError) as caught:
        try:
            raise cause
        except OSError as error:
            raise FetchError("wrapped") from error
    assert caught.value.__cause__ is cause
