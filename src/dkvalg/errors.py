"""The one exception dkvalg raises for bad input."""


class FeedError(Exception):
    """A feed is missing, unreadable, malformed, or of an unsupported election type.

    The message names the file or value at fault.
    """


def main() -> None:
    """Showcase this module's functionality."""
    message = "valgdag.xml: not found"

    error = FeedError(message)

    print(f"{type(error).__name__}: {error}")
    print(f"is an Exception: {isinstance(error, Exception)}")


if __name__ == "__main__":
    main()
