from __future__ import annotations


class ProviderError(Exception):
    """Structured provider-side failure. Read fields, don't regex the message."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
