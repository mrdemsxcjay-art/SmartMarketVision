"""Provider registry - single place where a concrete provider is selected."""

from __future__ import annotations

from app.config import ProviderName, settings
from app.logging_conf import get_logger
from app.providers.base import MarketDataProvider
from app.providers.yahoo import DisabledProvider, YahooForexProvider

logger = get_logger(__name__)

_REGISTRY: dict[str, type[MarketDataProvider]] = {
    ProviderName.YAHOO.value: YahooForexProvider,
    ProviderName.DISABLED.value: DisabledProvider,
}

_instance: MarketDataProvider | None = None


def build_provider(name: str | None = None) -> MarketDataProvider:
    key = (name or settings.market_data_provider.value).lower()
    provider_cls = _REGISTRY.get(key)
    if provider_cls is None:
        logger.error("Unknown MARKET_DATA_PROVIDER=%s - falling back to 'disabled'", key)
        provider_cls = DisabledProvider
    logger.info("Market data provider selected: %s", provider_cls.name)
    return provider_cls()


def get_provider() -> MarketDataProvider:
    """Process-wide singleton provider (shares its HTTP connection pool)."""
    global _instance
    if _instance is None:
        _instance = build_provider()
    return _instance


def set_provider(provider: MarketDataProvider | None) -> None:
    """Override the singleton - used by tests."""
    global _instance
    _instance = provider


def registered_providers() -> list[str]:
    return sorted(_REGISTRY)
