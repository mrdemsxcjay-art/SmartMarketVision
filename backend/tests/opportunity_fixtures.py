"""Fixtures for the Phase 6 opportunity tests.

Only construction helpers live here: real engines and real confluence groups are
used by the tests, so an opportunity is never validated against a hand-made
confluence that the engine itself could not produce.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.confluence.engine import ConfluenceEngine
from app.confluence.params import ConfluenceParams
from app.confluence.models import ConfluenceGroup, ConfluenceState
from app.opportunities.params import OpportunityParams
from app.schemas.market import CandleSeries
from tests import confluence_fixtures as cf_fx
from tests import price_action_fixtures as pa_fx

BarSpec = pa_fx.BarSpec
series = cf_fx.series
calm = cf_fx.calm
bar_time = cf_fx.bar_time
detection = cf_fx.detection

#: real timeframes used by the confluence fixtures
TF = "M15"


def params(**overrides) -> OpportunityParams:
    """A parameter set isolated per test (the engine defaults are untouched)."""
    instance = OpportunityParams()
    if overrides:
        instance.apply_overrides(overrides)
    return instance


def confluence_from(series: CandleSeries, detections, params: ConfluenceParams | None = None):
    """Runs the real confluence engine so the input is a genuine Phase 5 group."""
    engine = ConfluenceEngine(params or ConfluenceParams())
    result = engine.analyse(series, detections)
    engine.commit(result)
    return result.groups


def strong_group(series: CandleSeries) -> ConfluenceGroup:
    """The strongest realistic group: 5 detections, 7 points, 5 dimensions."""
    groups = confluence_from(series, cf_fx.bullish_stack(series.candles[-1].time))
    assert groups, "la confluence de reference doit produire un groupe"
    return groups[0]


def group_copy(group: ConfluenceGroup, **changes) -> ConfluenceGroup:
    """A mutated copy of a real group (used to model a market that turns)."""
    clone = group.model_copy(deep=True)
    for key, value in changes.items():
        setattr(clone, key, value)
    return clone


def bearish_group(series: CandleSeries) -> ConfluenceGroup:
    """A real bearish group, built from the mirrored detection set."""
    from tests.confluence_fixtures import bearish_stack

    groups = confluence_from(series, bearish_stack(series.candles[-1].time))
    assert groups, "la confluence baissiere de reference doit produire un groupe"
    return groups[0]


def following_bars(count: int = 1, *, close: float = 0.5, spread: float = 0.3) -> list[BarSpec]:
    """Closed bars that follow the confluence.

    The fixture series maps a BarSpec value onto ``1.1000 + value`` pip, so a
    ``close`` of +0.5 closes ABOVE the reference price and a negative one below,
    which is exactly what the confirmation observation needs.
    """
    return [
        BarSpec(open=close - spread / 2, high=close + spread, low=close - spread, close=close)
        for _ in range(count)
    ]


def now() -> datetime:
    return datetime.now(tz=timezone.utc)
