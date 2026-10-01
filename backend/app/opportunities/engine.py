"""Opportunity Engine (Phase 6) - pure logic, no I/O.

::

    confluences (Phase 5, from CHARTISTE + PRICE ACTION + SMC/ICT)
            |
            v  explicit conditions (6.2)          -> BUY / SELL / WATCH / NO_TRADE
            v  explicable score (6.4)             -> one point per criterion really checked
            v  state machine (6.5)                -> CREATED ... EXPIRED
            v  anti-spam key (6.6)                -> one observation, one alert key
            v  real data only (6.7)               -> reference price from the detections

Vocabulary
----------
``BUY`` and ``SELL`` are the analytical directions **observed** here; they are the
words the product asked for and they describe a market reading. Nothing in this
codebase can send an order: there is no broker client, no execution endpoint, no
position object.

A direction is named only when structure, several independent dimensions and the
score all agree, and when **no major reading opposes it**. Otherwise the engine
says WATCH (something is happening) or NO_TRADE **with its reason** - inventing an
opportunity to fill a quota is exactly what this engine must not do.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.confluence.models import ConfluenceGroup, ConfluenceState
from app.logging_conf import get_logger
from app.opportunities.models import (
    NoTradeReason,
    Opportunity,
    OpportunityCondition,
    OpportunityDirection,
    OpportunityState,
    SeriesOpportunities,
    WatchedLevel,
    direction_for,
)
from app.opportunities.params import OpportunityParams
from app.opportunities.params import params as default_params
from app.schemas.market import CandleSeries

logger = get_logger(__name__)

ENGINE_NAME = "OPPORTUNITY_ENGINE"
CATEGORY = "OPPORTUNITY"

#: states worth telling the world about (the outbox decides the delivery)
NOTIFIABLE_DEFAULT = ("CREATED", "CONFIRMED", "INVALIDATED")

#: priority order used to pick THE reason when several are true
#: a refusal that may still be *observed* (something is alive, just not enough yet)
WATCHABLE_REASONS: frozenset[str] = frozenset(
    {
        NoTradeReason.INSUFFICIENT_CONFLUENCE.value,
        NoTradeReason.MISSING_DIMENSIONS.value,
    }
)

#: priority order used to pick THE reason when several are true
REASON_PRIORITY: tuple[str, ...] = (
    NoTradeReason.DISABLED.value,
    NoTradeReason.EXPIRED.value,
    NoTradeReason.STALE_DATA.value,
    NoTradeReason.CONTRADICTORY.value,
    NoTradeReason.LOW_VOLATILITY.value,
    NoTradeReason.MISSING_DIMENSIONS.value,
    NoTradeReason.INSUFFICIENT_CONFLUENCE.value,
)


@dataclass
class LifecycleEvent:
    """An opportunity transition to publish (and to queue for Telegram)."""

    event_type: str
    opportunity: Opportunity
    previous_state: str | None = None
    notifiable: bool = False
    extra: dict[str, object] = field(default_factory=dict)


def _opportunity_id(symbol: str, timeframe: str, confluence_id: str | None) -> str:
    """Stable identity: pair + timeframe + the confluence it reads.

    The direction is deliberately NOT part of the identity: an observation that
    turns into a refusal (or back) is the SAME observation changing state, not a
    new one. The confluence carries pair, timeframe, direction and window already.
    """
    payload = f"{symbol}|{timeframe}|{confluence_id or 'none'}"
    return "op_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def alert_key(symbol: str, timeframe: str, direction: str, confluence_id: str | None) -> str:
    """Anti-spam key of the observation (6.6): stable for as long as it is the same."""
    return f"{symbol}|{timeframe}|{direction}|{confluence_id or 'none'}"


def alert_id(key: str) -> str:
    """Identity of the alert itself, used by the outbox to never send it twice."""
    return "al_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


class OpportunityEngine:
    """Turns a confluence into a named observation - or refuses to."""

    ENGINE_NAME = ENGINE_NAME
    CATEGORY = CATEGORY

    def __init__(self, params: OpportunityParams | None = None) -> None:
        self.params = params or default_params
        self._registry: dict[str, Opportunity] = {}
        self._runs = 0
        self._built = 0

    # ------------------------------------------------------------- analysis
    def analyse(self, series: CandleSeries, confluences: list[ConfluenceGroup]) -> SeriesOpportunities:
        started = time.perf_counter()
        candles = [candle for candle in series.candles if candle.closed]
        result = SeriesOpportunities(
            symbol=series.symbol,
            timeframe=series.timeframe.value,
            bars_analyzed=len(candles),
            last_bar_time=candles[-1].time if candles else None,
        )
        if not candles or not self.params.enabled:
            return result
        if len(candles) < self.params.lifecycle.min_bars_required:
            result.notes.append("pas assez de bougies cloturees : aucune opportunite tentee")
            return result

        result.confluences_considered = len(confluences)
        atr = _atr(candles, self.params.lifecycle.atr_period)
        for group in confluences:
            opportunity = self._build(series, candles, atr, group)
            if opportunity is not None:
                result.opportunities.append(opportunity)

        # actionable observations first (BUY / SELL), then WATCH, then the refusals
        order = {
            OpportunityDirection.BUY.value: 0,
            OpportunityDirection.SELL.value: 0,
            OpportunityDirection.WATCH.value: 1,
            OpportunityDirection.NO_TRADE.value: 2,
        }
        result.opportunities.sort(key=lambda item: (order.get(item.direction, 3), -item.score))
        self._runs += 1
        self._built += len(result.opportunities)
        result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return result

    # ---------------------------------------------------------------- build
    def _build(
        self,
        series: CandleSeries,
        candles: list,
        atr: float,
        group: ConfluenceGroup,
    ) -> Opportunity | None:
        conditions = self.params.conditions
        direction = direction_for(group.direction)
        if group.direction == "NEUTRAL":
            return self._no_trade(
                series, group, direction, NoTradeReason.INSUFFICIENT_CONFLUENCE.value,
                detail="lectures neutres uniquement : aucune direction observee",
            )

        dimensions = set(group.dimensions)
        contradictions = len(group.contradictions)
        contradiction_points = float(-sum(item.points for item in group.contradictions if item.points < 0))
        major_contradiction = group.state == ConfluenceState.CONTRADICTED.value or (
            contradictions > conditions.max_contradictions
        )
        age_bars = _age_in_bars(candles, group.window_end, series.timeframe.seconds)
        pip_size = _pip_size(series.symbol)
        last_close = float(candles[-1].close) or 1.0
        atr_ratio = atr / abs(last_close)

        checks: list[OpportunityCondition] = [
            self._check(
                "Structure alignee sur la direction",
                "STRUCTURE" in dimensions,
                f"dimensions observees : {', '.join(group.dimensions) or 'aucune'}",
                self.params.weights.structure,
                "STRUCTURE",
            ),
            self._check(
                "Liquidite observee",
                "LIQUIDITY" in dimensions,
                "pool estime, sweep ou niveaux egaux presents" if "LIQUIDITY" in dimensions
                else "aucune lecture de liquidite dans la fenetre",
                self.params.weights.liquidity,
                "LIQUIDITY",
            ),
            self._check(
                "Desequilibre (FVG / order block)",
                "IMBALANCE" in dimensions,
                "zone ou gap non comble present" if "IMBALANCE" in dimensions else "aucun desequilibre present",
                self.params.weights.imbalance,
                "IMBALANCE",
            ),
            self._check(
                "Declencheur price action",
                "PRICE_ACTION" in dimensions,
                "bougie de declenchement observee" if "PRICE_ACTION" in dimensions
                else "aucun declencheur price action",
                self.params.weights.trigger,
                "PRICE_ACTION",
            ),
            self._check(
                "Volatilite utilisable",
                atr > 0 and atr_ratio >= conditions.min_atr_ratio,
                (
                    f"ATR {atr / pip_size:.2f} pip(s) soit {atr_ratio * 100:.4f}% du prix"
                    if pip_size
                    else f"ATR {atr:.6f} ({atr_ratio * 100:.4f}% du prix)"
                ),
                0.0,
                "VOLATILITY",
                gate=True,
            ),
            self._check(
                "Displacement",
                "DISPLACEMENT" in dimensions,
                "mouvement impulsif mesure" if "DISPLACEMENT" in dimensions else "aucun displacement",
                self.params.weights.displacement,
                "DISPLACEMENT",
            ),
            self._check(
                "Confluence suffisante",
                group.state in (ConfluenceState.CONFLUENCE.value, ConfluenceState.STRONG_CONFLUENCE.value),
                f"etat de confluence {group.state} ({group.score:g}/{group.max_score:g})",
                self.params.weights.confluence_level,
            ),
            self._check(
                "Aucune contradiction majeure",
                not major_contradiction,
                "aucune lecture opposee"
                if not major_contradiction
                else (
                    "etat de confluence CONTRADICTED : lectures opposees majeures"
                    if group.state == ConfluenceState.CONTRADICTED.value
                    else f"{contradictions} lecture(s) opposee(s) : {contradiction_points:g} point(s) retires"
                ),
                0.0,
                gate=True,
            ),
        ]
        score = round(sum(item.points for item in checks if item.passed), 2)

        # ---- the refusal reasons, in the documented priority order
        reason: str | None = None
        if age_bars > conditions.max_age_bars:
            reason = NoTradeReason.STALE_DATA.value
        elif major_contradiction:
            reason = NoTradeReason.CONTRADICTORY.value
        elif atr <= 0 or atr_ratio < conditions.min_atr_ratio:
            reason = NoTradeReason.LOW_VOLATILITY.value
        elif not set(conditions.required_dimensions).issubset(dimensions):
            reason = NoTradeReason.MISSING_DIMENSIONS.value
        elif len(dimensions) < conditions.min_dimensions:
            reason = NoTradeReason.MISSING_DIMENSIONS.value
        elif score < conditions.min_score or len(group.events) < conditions.min_events:
            reason = NoTradeReason.INSUFFICIENT_CONFLUENCE.value

        if reason is not None:
            # A WATCH means "something is happening, but it is not actionable yet".
            # A frozen, stale or contradicted market is not "something happening":
            # those refusals stay NO_TRADE, as the negative controls require.
            watch = score >= conditions.watch_score and reason in WATCHABLE_REASONS
            return self._finalise(
                series=series,
                group=group,
                direction=OpportunityDirection.WATCH.value if watch else OpportunityDirection.NO_TRADE.value,
                state=OpportunityState.ACTIVE.value,
                score=score,
                checks=checks,
                no_trade_reason=None if watch else reason,
                blocked_by=reason,
                note=(
                    f"observation en surveillance : direction non nommee ({reason}) - {_reason_text(reason)}"
                    if watch
                    else f"refus explicite : {reason} - {_reason_text(reason)}"
                ),
                candles=candles,
            )

        return self._finalise(
            series=series,
            group=group,
            direction=direction,
            state=OpportunityState.CREATED.value,
            score=score,
            checks=checks,
            no_trade_reason=None,
            blocked_by=None,
            note=(
                f"direction {direction} observee : structure, {len(dimensions)} dimension(s), "
                f"score {score:g}/{self.params.max_score():g}. Lecture de marche : rien n'est transmis."
            ),
            candles=candles,
        )

    def _finalise(
        self,
        *,
        series: CandleSeries,
        group: ConfluenceGroup,
        direction: str,
        state: str,
        score: float,
        checks: list[OpportunityCondition],
        no_trade_reason: str | None,
        note: str,
        candles: list,
        blocked_by: str | None = None,
    ) -> Opportunity:
        now = datetime.now(tz=timezone.utc)
        identifier = _opportunity_id(series.symbol, series.timeframe.value, group.id)
        previous = self._registry.get(identifier)
        key = alert_key(series.symbol, series.timeframe.value, direction, group.id)

        levels = _watch_levels(group)
        confirmation = None
        if (
            previous is not None
            and previous.direction in (OpportunityDirection.BUY.value, OpportunityDirection.SELL.value)
            and previous.reference_price is not None
        ):
            confirmation = _confirmation_bar(
                candles,
                previous.reference_price,
                previous.direction,
                after_time=group.window_end,
                params=self.params,
            )
        confirmed = confirmation is not None
        resolved_state = self._next_state(previous, state, confirmed, group, score)
        notifiable = resolved_state in tuple(self.params.lifecycle.notify_states) and (
            previous is None or previous.state != resolved_state
        )

        opportunity = Opportunity(
            id=identifier,
            dedup_key=identifier,
            symbol=series.symbol,
            timeframe=series.timeframe.value,
            direction=direction,
            state=resolved_state,
            score=score,
            max_score=self.params.max_score(),
            confluence_id=group.id,
            confluence_state=group.state,
            reference_price=group.reference_price,
            conditions=checks,
            evidence=[
                f"confluence {group.id} : {group.state} {group.score:g}/{group.max_score:g}",
                *group.why[:4],
                *(f"oppose : {line}" for line in group.against[:2] if "aucun element oppose" not in line),
            ],
            no_trade_reason=no_trade_reason,
            blocked_by=blocked_by,
            watch_levels=levels,
            created_at=previous.created_at if previous else now,
            updated_at=now,
            #: bar time of the reading the current state comes from: the
            #: confirmation candle when there is one, the confluence anchor otherwise.
            observed_bar_time=confirmation.time if confirmation is not None else group.window_end,
            confirmation_bar_time=confirmation.time if confirmation is not None else None,
            # validity is counted in REAL bars, not in wall clock time: the same
            # series always yields the same expiration.
            expires_at=datetime.fromtimestamp(
                group.window_end + self.params.lifecycle.validity_bars * series.timeframe.seconds,
                tz=timezone.utc,
            ),
            generation=(previous.generation + 1) if previous else 1,
            alert_key=key,
            previous_state=previous.state if previous else None,
            note=note,
        )
        #: kept on the object so the service can hand it to the outbox as-is
        opportunity.__dict__["_notifiable"] = notifiable
        return opportunity

    def _next_state(
        self,
        previous: Opportunity | None,
        created_state: str,
        confirmed: bool,
        group: ConfluenceGroup,
        score: float,
    ) -> str:
        """Documented state machine (6.5).

        CREATED  -> ACTIVE       : the observation survives the next reading
        any      -> CONFIRMED    : a closed candle after the confluence closes in
                                   the observed direction (never a forecast)
        any      -> WEAKENED     : the score falls back below the watch threshold
        any      -> INVALIDATED  : the confluence turns contradictory
        any      -> EXPIRED      : nothing fresh arrives before the validity ends
        """
        if previous is None:
            return created_state
        if group.state == ConfluenceState.CONTRADICTED.value:
            return OpportunityState.INVALIDATED.value
        if group.state == ConfluenceState.EXPIRED.value:
            return OpportunityState.EXPIRED.value
        if confirmed:
            return OpportunityState.CONFIRMED.value
        if score < self.params.conditions.watch_score:
            return OpportunityState.WEAKENED.value
        return OpportunityState.ACTIVE.value

    def _no_trade(
        self,
        series: CandleSeries,
        group: ConfluenceGroup,
        direction: str,
        reason: str,
        *,
        detail: str,
    ) -> Opportunity:
        return self._finalise(
            series=series,
            group=group,
            direction=OpportunityDirection.NO_TRADE.value,
            state=OpportunityState.ACTIVE.value,
            score=0.0,
            checks=[self._check("Direction observee", False, detail, 0.0)],
            no_trade_reason=reason,
            blocked_by=reason,
            note=f"refus explicite : {reason}",
            candles=[],
        )

    @staticmethod
    def _check(
        label: str,
        passed: bool,
        detail: str,
        points: float,
        dimension: str | None = None,
        *,
        gate: bool = False,
    ):
        return OpportunityCondition(
            label=label,
            passed=passed,
            detail=detail,
            points=0.0 if gate else (points if passed else 0.0),
            dimension=dimension,
            gate=gate,
        )

    # ----------------------------------------------------------- registry
    def commit(self, result: SeriesOpportunities) -> list[LifecycleEvent]:
        events: list[LifecycleEvent] = []
        for opportunity in result.opportunities:
            previous = self._registry.get(opportunity.id)
            if previous is not None:
                opportunity.created_at = previous.created_at
                opportunity.previous_state = previous.state
            notifiable = bool(opportunity.__dict__.get("_notifiable", False))
            self._registry[opportunity.id] = opportunity
            if previous is None:
                # A refusal (NO_TRADE) is stored and shown, but it is not an event:
                # the dashboard reads it, nobody gets woken up for it.
                if opportunity.direction in (
                    OpportunityDirection.BUY.value,
                    OpportunityDirection.SELL.value,
                ):
                    events.append(
                        LifecycleEvent("OPPORTUNITY_CREATED", opportunity, None, notifiable=notifiable)
                    )
                elif opportunity.direction == OpportunityDirection.WATCH.value:
                    events.append(
                        LifecycleEvent("OPPORTUNITY_CREATED", opportunity, None, notifiable=False)
                    )
                continue
            if previous.state == opportunity.state:
                opportunity.created_at = previous.created_at
                continue
            event_type = {
                OpportunityState.CONFIRMED.value: "OPPORTUNITY_CONFIRMED",
                OpportunityState.WEAKENED.value: "OPPORTUNITY_WEAKENED",
                OpportunityState.INVALIDATED.value: "OPPORTUNITY_INVALIDATED",
                OpportunityState.EXPIRED.value: "OPPORTUNITY_EXPIRED",
                OpportunityState.ACTIVE.value: "OPPORTUNITY_CREATED",
            }.get(opportunity.state, "OPPORTUNITY_CREATED")
            events.append(
                LifecycleEvent(event_type, opportunity, previous.state, notifiable=notifiable)
            )
        events.extend(self._expire(result))
        self._prune()
        return events

    def _expire(self, result: SeriesOpportunities) -> list[LifecycleEvent]:
        """Expires the observations of this series that did not survive.

        The reference is the bar time of the current reading - a real value from the
        data - so the outcome depends on the market, never on the machine clock.
        """
        reference = result.last_bar_time
        if reference is None:
            return []
        processed = {item.id for item in result.opportunities}
        events: list[LifecycleEvent] = []
        for identifier, opportunity in list(self._registry.items()):
            if opportunity.symbol != result.symbol or opportunity.timeframe != result.timeframe:
                continue
            if identifier in processed or opportunity.expires_at is None:
                continue
            if reference < int(opportunity.expires_at.timestamp()):
                continue
            previous_state = opportunity.state
            opportunity.state = OpportunityState.EXPIRED.value
            opportunity.previous_state = previous_state
            events.append(
                LifecycleEvent(
                    "OPPORTUNITY_EXPIRED",
                    opportunity,
                    previous_state,
                    notifiable=previous_state
                    in (OpportunityState.CREATED.value, OpportunityState.ACTIVE.value),
                )
            )
            self._registry.pop(identifier, None)
        return events

    def _prune(self) -> None:
        cap = self.params.lifecycle.max_tracked
        if len(self._registry) <= cap:
            return
        ordered = sorted(
            self._registry.values(),
            key=lambda item: item.updated_at or datetime.min.replace(tzinfo=timezone.utc),
        )
        for opportunity in ordered[: len(self._registry) - cap]:
            self._registry.pop(opportunity.id, None)
        logger.warning("Opportunity registry pruned to %s entries", cap)

    def clear(self) -> None:
        self._registry.clear()

    # ------------------------------------------------------------- reading
    def all(self, symbol: str | None = None, timeframe: str | None = None) -> list[Opportunity]:
        items = list(self._registry.values())
        if symbol:
            items = [item for item in items if item.symbol.upper() == symbol.upper()]
        if timeframe:
            items = [item for item in items if item.timeframe.upper() == timeframe.upper()]
        items.sort(key=lambda item: (item.updated_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        return items

    def get(self, opportunity_id: str) -> Opportunity | None:
        return self._registry.get(opportunity_id)

    def named(self, symbol: str | None = None, timeframe: str | None = None) -> list[Opportunity]:
        """Observed directions only (BUY / SELL)."""
        return [
            item
            for item in self.all(symbol, timeframe)
            if item.direction in (OpportunityDirection.BUY.value, OpportunityDirection.SELL.value)
        ]

    def stats(self) -> dict:
        by_direction: dict[str, int] = {}
        by_state: dict[str, int] = {}
        for item in self._registry.values():
            by_direction[item.direction] = by_direction.get(item.direction, 0) + 1
            by_state[item.state] = by_state.get(item.state, 0) + 1
        return {
            "engine": ENGINE_NAME,
            "runs": self._runs,
            "built": self._built,
            "tracked": len(self._registry),
            "by_direction": by_direction,
            "by_state": by_state,
            "max_score": self.params.max_score(),
        }


# --------------------------------------------------------------------- helpers
def _confirmation_bar(
    candles: list,
    reference_price: float,
    direction: str,
    *,
    after_time: int,
    params: OpportunityParams,
):
    """Observation of a confirmation close (real bars only, never a forecast).

    A BUY observation is confirmed when a closed candle *after* the confluence
    closes above the reference price; a SELL one when it closes below. Only the
    ``confirm_bars`` candles that follow are considered: after that the observation
    keeps its own state instead of claiming a late confirmation. Bars before the
    confluence are never used - that would be hindsight, not observation.
    """
    following = [candle for candle in candles if candle.time > after_time][: params.lifecycle.confirm_bars]
    for candle in following:
        if direction == OpportunityDirection.BUY.value and candle.close > reference_price:
            return candle
        if direction == OpportunityDirection.SELL.value and candle.close < reference_price:
            return candle
    return None


def _watch_levels(group: ConfluenceGroup) -> list[WatchedLevel]:
    """Real prices the observation refers to (never a target, never a stop)."""
    levels: list[WatchedLevel] = []
    if group.reference_price is not None:
        levels.append(
            WatchedLevel(
                label="PRIX DE REFERENCE",
                price=float(group.reference_price),
                kind="REFERENCE",
                note="prix reel de l'evenement le plus ancien de la confluence",
            )
        )
    for event in group.events:
        if event.price is None:
            continue
        if group.reference_price is not None and abs(event.price - group.reference_price) < 1e-12:
            continue
        levels.append(
            WatchedLevel(
                label=f"{event.type} ({event.timeframe})",
                price=float(event.price),
                kind="NIVEAU OBSERVE",
                note=f"detection {event.id}",
            )
        )
        if len(levels) >= 3:
            break
    return levels


REASON_TEXT = {
    NoTradeReason.INSUFFICIENT_CONFLUENCE.value: "score, nombre de detections ou etat de confluence insuffisants",
    NoTradeReason.CONTRADICTORY.value: "lectures opposees majeures dans la fenetre",
    NoTradeReason.MISSING_DIMENSIONS.value: "structure ou dimensions independantes manquantes",
    NoTradeReason.STALE_DATA.value: "evenement trop ancien par rapport a la derniere bougie",
    NoTradeReason.LOW_VOLATILITY.value: "marche trop calme : aucune volatilite exploitable",
    NoTradeReason.EXPIRED.value: "evenement expire",
    NoTradeReason.DISABLED.value: "moteur desactive",
}


def _reason_text(reason: str | None) -> str:
    return REASON_TEXT.get(reason or "", "conditions non reunies")


def _age_in_bars(candles: list, bar_time: int, seconds: int) -> int:
    for index in range(len(candles) - 1, -1, -1):
        if candles[index].time <= bar_time:
            return len(candles) - 1 - index
    return len(candles)


def _atr(candles: list, period: int) -> float:
    if not candles:
        return 0.0
    window = candles[-max(1, period):]
    start = len(candles) - len(window)
    ranges: list[float] = []
    for offset, candle in enumerate(window):
        index = start + offset
        if index == 0:
            ranges.append(candle.high - candle.low)
            continue
        previous_close = candles[index - 1].close
        ranges.append(
            max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close))
        )
    return sum(ranges) / len(ranges) if ranges else 0.0


def _pip_size(symbol: str) -> float:
    try:
        from app.instruments import get_instrument

        instrument = get_instrument(symbol)
        return float(instrument.pip_size)
    except Exception:  # pragma: no cover - unknown pair
        return 0.0001
