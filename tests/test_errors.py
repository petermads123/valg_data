import pytest

from dkvalg import FeedError


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
