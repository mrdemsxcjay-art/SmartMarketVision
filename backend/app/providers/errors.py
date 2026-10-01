"""Provider error hierarchy.

Every failure keeps its root cause so it can be logged, surfaced to the API
as an explicit DATA UNAVAILABLE state, and never replaced by invented prices.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all market-data failures."""

    code = "PROVIDER_ERROR"

    def __init__(self, message: str, *, cause: BaseException | None = None, retryable: bool = True):
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.retryable = retryable

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "cause": f"{type(self.cause).__name__}: {self.cause}" if self.cause else None,
            "retryable": self.retryable,
        }

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.code}] {self.message}"


class ProviderUnavailable(ProviderError):
    code = "PROVIDER_UNAVAILABLE"


class ProviderTimeout(ProviderError):
    code = "PROVIDER_TIMEOUT"


class ProviderRateLimited(ProviderError):
    code = "PROVIDER_RATE_LIMITED"


class ProviderBadPayload(ProviderError):
    code = "PROVIDER_BAD_PAYLOAD"
    retryable = False


class UnknownSymbol(ProviderError):
    code = "UNKNOWN_SYMBOL"
    retryable = False


class UnsupportedTimeframe(ProviderError):
    code = "UNSUPPORTED_TIMEFRAME"
    retryable = False


class ProviderDisabled(ProviderError):
    code = "PROVIDER_DISABLED"
    retryable = False
