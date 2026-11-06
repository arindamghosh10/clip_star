"""Error classes that tell the job engine whether to retry."""


class ClipstarError(Exception):
    """Base error. `user_message` is safe to show in the UI."""

    retryable: bool = True

    def __init__(self, message: str, *, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message or message


class RetryableError(ClipstarError):
    """Temporary problem (network, rate limit, busy resource). The job is retried with backoff."""

    retryable = True


class PermanentError(ClipstarError):
    """Retrying won't help (bad input, missing credentials, unsupported file). The job stops and asks the user."""

    retryable = False


class Cancelled(ClipstarError):
    """The job was cancelled or its lease was lost; stop quietly."""

    retryable = False
