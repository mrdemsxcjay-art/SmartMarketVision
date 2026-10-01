"""§16 - internal SMC/ICT confluence: descriptive, never a signal.

A confluence group is a set of SMC objects that sit in the same direction, close
together in time, and come from **different families** (structure, liquidity,
gaps, blocks, range). Grouping the same family twice would be a tautology
("two order blocks agree"), so at least two distinct families are required.

Nothing here scores anything, and nothing here is a signal: the group carries the
list of the objects it is made of and the numbers that tie them (distance in
bars, families involved). ``confluence.trading_signal`` is frozen to ``False`` and
the payload says so explicitly.
"""

from __future__ import annotations

from app.smc_ict.models import ScanContext, SmcCandidate


def detect_confluence(ctx: ScanContext, candidates: list[SmcCandidate]) -> list[dict[str, object]]:
    """Group the candidates into descriptive confluence clusters."""
    params = ctx.params.confluence
    if not candidates:
        return []

    ordered = sorted(candidates, key=lambda c: (c.direction, c.index))
    groups: list[dict[str, object]] = []

    for direction in ("BULLISH", "BEARISH", "NEUTRAL"):
        if params.require_same_direction and direction == "NEUTRAL":
            continue
        bucket = [c for c in ordered if c.direction == direction]
        current: list[SmcCandidate] = []
        for candidate in bucket:
            if not current:
                current = [candidate]
                continue
            same_window = candidate.index - current[-1].index <= params.max_bars_between
            families = {c.family for c in current}
            if same_window and len(current) < params.max_items_per_group:
                current.append(candidate)
            else:
                _close_group(ctx, current, direction, families, groups)
                current = [candidate]
        if current:
            _close_group(ctx, current, direction, {c.family for c in current}, groups)

    return groups


def _close_group(
    ctx: ScanContext,
    items: list[SmcCandidate],
    direction: str,
    families: set[str],
    groups: list[dict[str, object]],
) -> None:
    """Keep a group only when it really is a confluence (2+ families, 2+ items)."""
    if len(items) < 2:
        return
    distinct = {c.family for c in items}
    if len(distinct) < 2:
        return
    groups.append(
        {
            "direction": direction,
            "from_index": items[0].index,
            "to_index": items[-1].index,
            "span_bars": items[-1].index - items[0].index,
            "families": sorted(distinct),
            "count": len(items),
            "items": [
                {
                    "pattern": c.pattern,
                    "index": c.index,
                    "family": c.family,
                    "levels": {k: v for k, v in c.levels.items()},
                }
                for c in items
            ],
            "description": (
                f"{len(items)} objets SMC {direction.lower()} sur "
                f"{items[-1].index - items[0].index} bougie(s) : "
                + ", ".join(f"{c.pattern}@{c.index}" for c in items)
            ),
            "trading_signal": False,
        }
    )
