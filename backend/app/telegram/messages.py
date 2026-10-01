"""Telegram message builder (Phase 8).

The message is exactly what the product asked for::

    🚨 SMART MARKET VISION
    EURUSD · M15
    🟢 BUY — OPPORTUNITÉ
    Confluence 8/10
    État : CREATED
    STRUCTURE ✅  LIQUIDITY ✅  IMBALANCE ✅  PRICE ACTION ✅  CHARTISTE ✅
    Prix : 1.16234
    Validité : 2026-10-01 17:15 UTC
    ⚠️ Observation uniquement — aucune exécution automatique, aucun ordre.

``WATCH`` uses 👀 and says what is still missing. ``NO_TRADE`` is silent by default
(8.3) and, when explicitly enabled, explains its reason. The message never
contains a target, a stop, a lot size or a performance claim: those words do not
exist in this file.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.opportunities.models import Opportunity, OpportunityDirection
from app.telegram.params import TelegramMessageParams, TelegramParams

DIMENSION_LABELS = {
    "STRUCTURE": "STRUCTURE",
    "LIQUIDITY": "LIQUIDITY",
    "IMBALANCE": "IMBALANCE",
    "PRICE_ACTION": "PRICE ACTION",
    "DISPLACEMENT": "DISPLACEMENT",
    "CHARTISTE": "CHARTISTE",
    "PREMIUM_DISCOUNT": "PREMIUM/DISCOUNT",
}

ICON_BY_DIRECTION = {
    OpportunityDirection.BUY.value: "buy",
    OpportunityDirection.SELL.value: "sell",
    OpportunityDirection.WATCH.value: "watch",
    OpportunityDirection.NO_TRADE.value: "no_trade",
}


def icon_for(opportunity: Opportunity, message: TelegramMessageParams) -> str:
    key = ICON_BY_DIRECTION.get(opportunity.direction, "watch")
    return {
        "buy": message.buy_icon,
        "sell": message.sell_icon,
        "watch": message.watch_icon,
        "no_trade": message.no_trade_icon,
    }[key]


def should_alert(opportunity: Opportunity, message: TelegramMessageParams) -> bool:
    """8.3 - NO_TRADE stays silent unless the operator explicitly allows it."""
    if opportunity.direction == OpportunityDirection.NO_TRADE.value:
        return bool(message.send_no_trade)
    return True


def heading_for(opportunity: Opportunity) -> str:
    if opportunity.direction == OpportunityDirection.BUY.value:
        return "BUY — OPPORTUNITÉ OBSERVÉE"
    if opportunity.direction == OpportunityDirection.SELL.value:
        return "SELL — OPPORTUNITÉ OBSERVÉE"
    if opportunity.direction == OpportunityDirection.WATCH.value:
        return "WATCH — SURVEILLANCE"
    return "NO_TRADE — AUCUNE OPPORTUNITÉ"


def _format_price(value: float | None) -> str:
    return f"{value:.5f}" if value is not None else "indisponible"


def _format_time(value: datetime | None) -> str:
    if value is None:
        return "indisponible"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_message(opportunity: Opportunity, params: TelegramParams) -> str:
    """The structured alert. Pure function: no I/O, no secret, no clock."""
    message = params.message
    lines: list[str] = [
        f"{message.header_icon} {message.title}",
        f"{opportunity.symbol} · {opportunity.timeframe}",
        f"{icon_for(opportunity, message)} {heading_for(opportunity)}",
    ]

    confluence_score = _confluence_score(opportunity)
    if confluence_score is not None:
        lines.append(f"Confluence {confluence_score}")
    lines.append(f"Score : {opportunity.score:g}/10")
    lines.append(f"État : {opportunity.state}")

    if message.show_dimensions:
        lines.append(_dimensions_line(opportunity))
    if message.show_levels and opportunity.reference_price is not None:
        lines.append(f"Prix : {_format_price(opportunity.reference_price)}")
    lines.append(f"Validité : {_format_time(opportunity.expires_at)}")

    if opportunity.direction == OpportunityDirection.WATCH.value and opportunity.blocked_by:
        lines.append(f"En attente : {opportunity.blocked_by}")
    if opportunity.no_trade_reason:
        lines.append(f"Refus : {opportunity.no_trade_reason}")

    evidence = [line for line in opportunity.evidence if line][:3]
    if evidence:
        lines.append("Détections : " + " | ".join(evidence[:2]))
    lines.append(message.disclaimer)
    text = "\n".join(lines)
    return text[: message.max_chars]


def build_caption(opportunity: Opportunity, params: TelegramParams) -> str:
    """Short caption used when the capture is sent as a photo."""
    message = params.message
    lines = [
        f"{icon_for(opportunity, message)} {opportunity.symbol} · {opportunity.timeframe} — {opportunity.direction}",
        f"Score {opportunity.score:g}/10 · {opportunity.state}",
    ]
    confluence_score = _confluence_score(opportunity)
    if confluence_score:
        lines.append(f"Confluence {confluence_score}")
    if opportunity.reference_price is not None:
        lines.append(f"Prix : {_format_price(opportunity.reference_price)}")
    lines.append(message.disclaimer)
    return "\n".join(lines)[: message.caption_max_chars]


def _confluence_score(opportunity: Opportunity) -> str | None:
    """The score of the confluence the observation comes from, e.g. ``5/10``.

    The evidence line looks like ``confluence cf_xxx : CONFLUENCE 5/10``: only the
    score is kept, so the message reads ``Confluence 5/10`` and never
    ``Confluence CONFLUENCE 5/10``.
    """
    for line in opportunity.evidence:
        if line.startswith("confluence "):
            _, _, tail = line.partition(":")
            tail = tail.strip()
            for state in ("STRONG_CONFLUENCE", "NO_CONFLUENCE", "CONFLUENCE", "WATCH", "CONTRADICTED", "EXPIRED"):
                if tail.startswith(state):
                    tail = tail[len(state) :].strip()
                    break
            return tail or None
    return None


def _dimensions_line(opportunity: Opportunity) -> str:
    passed = [
        DIMENSION_LABELS.get(check.dimension or "", check.label)
        for check in opportunity.conditions
        if check.dimension and check.passed
    ]
    missing = [
        DIMENSION_LABELS.get(check.dimension or "", check.label)
        for check in opportunity.conditions
        if check.dimension and not check.passed
    ]
    text = "  ".join(f"{name} ✅" for name in passed) or "aucune dimension confirmée"
    if missing:
        text += "   |   " + "  ".join(f"{name} ✗" for name in missing)
    return text
