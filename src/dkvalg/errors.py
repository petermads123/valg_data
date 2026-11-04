"""The one exception dkvalg raises for bad input."""


class FeedError(Exception):
    """A feed is missing, unreadable, malformed, or of an unsupported election type.

    The message names the file or value at fault.
    """


class FetchError(FeedError):
    """A request failed: network error, timeout, oversize body or HTTP status.

    The message names the URL and the cause. A `FeedError`, so callers that
    handle bad feeds handle failed fetches the same way.
    """


def main() -> None:
    """Showcase this module's functionality."""
    message = "valgdag.xml: not found"

    error = FeedError(message)

    print(f"{type(error).__name__}: {error}")
    print(f"is an Exception: {isinstance(error, Exception)}")

    # A failed request is a FeedError too, so one handler covers both.
    message = "https://example.invalid/valgdag.xml: HTTP status 503"

    fetch_error = FetchError(message)

    print(f"{type(fetch_error).__name__}: {fetch_error}")
    print(f"is a FeedError: {isinstance(fetch_error, FeedError)}")


if __name__ == "__main__":
    main()
