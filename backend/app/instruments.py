"""Instrument catalog.

Adding an instrument = adding one entry here (or via ``WATCHLIST`` in .env).
No code change is required elsewhere.
"""

from __future__ import annotations

from app.schemas.market import SymbolInfo

# symbol -> (description, digits, pip_size)
CATALOG: dict[str, tuple[str, int, float]] = {
    "EURUSD": ("Euro / US Dollar", 5, 0.0001),
    "GBPUSD": ("British Pound / US Dollar", 5, 0.0001),
    "USDJPY": ("US Dollar / Japanese Yen", 3, 0.01),
    "USDCHF": ("US Dollar / Swiss Franc", 5, 0.0001),
    "AUDUSD": ("Australian Dollar / US Dollar", 5, 0.0001),
    "USDCAD": ("US Dollar / Canadian Dollar", 5, 0.0001),
    "NZDUSD": ("New Zealand Dollar / US Dollar", 5, 0.0001),
    "EURGBP": ("Euro / British Pound", 5, 0.0001),
    "EURJPY": ("Euro / Japanese Yen", 3, 0.01),
    "GBPJPY": ("British Pound / Japanese Yen", 3, 0.01),
    "USDSEK": ("US Dollar / Swedish Krona", 5, 0.0001),
    "USDNOK": ("US Dollar / Norwegian Krone", 5, 0.0001),
    "EURCHF": ("Euro / Swiss Franc", 5, 0.0001),
    "AUDJPY": ("Australian Dollar / Japanese Yen", 3, 0.01),
    "CADJPY": ("Canadian Dollar / Japanese Yen", 3, 0.01),
    "CHFJPY": ("Swiss Franc / Japanese Yen", 3, 0.01),
    "EURAUD": ("Euro / Australian Dollar", 5, 0.0001),
    "EURCAD": ("Euro / Canadian Dollar", 5, 0.0001),
    "GBPCHF": ("British Pound / Swiss Franc", 5, 0.0001),
    "GBPAUD": ("British Pound / Australian Dollar", 5, 0.0001),
    "XAUUSD": ("Gold / US Dollar", 2, 0.01),
}

DEFAULT_WATCHLIST = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD",
    "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
]


def normalize_symbol(symbol: str) -> str:
    """Accept ``eurusd``, ``EUR/USD``, ``EUR_USD`` -> ``EURUSD``."""
    raw = (symbol or "").strip().upper().replace("/", "").replace("_", "").replace("-", "")
    return raw


def split_pair(symbol: str) -> tuple[str, str]:
    s = normalize_symbol(symbol)
    if len(s) == 6:
        return s[:3], s[3:]
    return s[:3], s[3:6] or "USD"


def get_symbol_info(symbol: str) -> SymbolInfo | None:
    code = normalize_symbol(symbol)
    meta = CATALOG.get(code)
    if meta is None:
        return None
    description, digits, pip = meta
    base, quote = split_pair(code)
    return SymbolInfo(
        symbol=code,
        description=description,
        base=base,
        quote=quote,
        digits=digits,
        pip_size=pip,
        provider_symbol=f"{code}=X",
    )


def available_symbols() -> list[SymbolInfo]:
    return [info for code in CATALOG if (info := get_symbol_info(code)) is not None]
