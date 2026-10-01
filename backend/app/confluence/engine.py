"""Confluence Engine (Phase 5) - pure logic, no I/O.

Pipeline
--------
::

    CHARTISTE + PRICE ACTION + SMC/ICT detections (already published)
            |
            v  normalisation (5.1)          -> ConfluenceEvent, identity preserved
            v  temporal alignment (5.2)     -> same window of bars, same price band
            v  direction alignment (5.3)    -> BULLISH / BEARISH / NEUTRAL, never merged
            v  explicable score (5.4)       -> one point per dimension, contradictions charged
            v  state (5.5)                  -> NO_CONFLUENCE ... EXPIRED
            v  multi-timeframe (5.6)        -> slower timeframes read as context
            v  why / against (5.7)          -> two explicit lists
            v  identity + lifecycle (5.8)   -> stable id, updated in place, expires

The engine never touches a database or a network: the service layer does that.

Identity
--------
``cf_<sha1(symbol|timeframe|direction|anchor_event_id|anchor_bar)[:16]>``

The anchor is the **oldest event** of the group, so the identity is stable while
the confluence lives (new events join it, the same id is updated in place) and a
genuinely new confluence gets a new id. The anchor is a real detection id: the
same event can be followed from the detector to the alert.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.confluence.models import (
    ConfluenceDimension,
    ConfluenceEvent,
    ConfluenceGroup,
    ConfluenceState,
    ScoreComponent,
    SeriesConfluence,
    opposite,
)
from app.confluence.normalizer import normalise
from app.confluence.params import ConfluenceParams
from app.confluence.params import params as default_params
from app.confluence.scoring import DIMENSION_LABELS, explain, score_group
from app.logging_conf import get_logger
from app.schemas.events import PatternDetection
from app.schemas.market import CandleSeries, Timeframe

logger = get_logger(__name__)

ENGINE_NAME = "CONFLUENCE_ENGINE"
CATEGORY = "CONFLUENCE"

#: states that describe a real agreement between several readings
OBSERVED_STATES: frozenset[str] = frozenset(
    {
        ConfluenceState.WATCH.value,
        ConfluenceState.CONFLUENCE.value,
        ConfluenceState.STRONG_CONFLUENCE.value,
    }
)


@dataclass
class LifecycleEvent:
    """A confluence state transition to publish (and persist)."""

    event_type: str
    group: ConfluenceGroup
    previous_state: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


def _group_id(symbol: str, timeframe: str, direction: str, window_start: int) -> str:
    """Stable identity of a confluence: one per (pair, timeframe, direction, window).

    The window start is the bar time of the OLDEST event of the group. Anchoring on
    a bar time (and not on one particular detection id) means a new reading joining
    the confluence updates the same object instead of creating a second one, while a
    genuinely new confluence - born later - gets its own identity.
    """
    payload = f"{symbol}|{timeframe}|{direction}|{window_start}"
    return "cf_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _signature(events: list[ConfluenceEvent], extra_ids: list[str]) -> str:
    ids = ",".join(sorted([event.id for event in events] + list(extra_ids)))
    return hashlib.sha1(ids.encode("utf-8")).hexdigest()[:16]


def _cluster_by_price(events: list[ConfluenceEvent], band: float) -> list[ConfluenceEvent]:
    """Keep the most populated price cluster inside ``band`` (deterministic).

    Prices come from the real drawings; no cluster is invented when a price is
    missing (the events are then kept as they are). The largest cluster wins; on a
    tie the most recent one wins, then the lowest price: the result never depends
    on the order the detections arrived in.
    """
    if band <= 0 or len(events) < 2 or any(event.price is None for event in events):
        return sorted(events, key=lambda event: (event.timestamp, event.id))

    ordered = sorted(events, key=lambda event: (event.price, event.timestamp, event.id))
    best: list[ConfluenceEvent] = []
    best_key: tuple = ()
    for start, floor in enumerate(ordered):
        cluster = [floor]
        for other in ordered[start + 1 :]:
            if other.price - floor.price <= band:
                cluster.append(other)
            else:
                break
        key = (len(cluster), max(event.timestamp for event in cluster), -min(event.price for event in cluster))
        if key > best_key:
            best, best_key = cluster, key
    return sorted(best, key=lambda event: (event.timestamp, event.id))


class ConfluenceEngine:
    """Runs the confluence logic on one series and tracks the groups over time."""

    ENGINE_NAME = ENGINE_NAME
    CATEGORY = CATEGORY

    def __init__(self, params: ConfluenceParams | None = None) -> None:
        self.params = params or default_params
        #: group id -> current group (updated in place, like the other engines)
        self._registry: dict[str, ConfluenceGroup] = {}
        #: group id -> bar time of the last run that saw it
        self._last_seen: dict[str, int] = {}
        self._runs = 0
        self._groups_seen = 0
        self._events_considered = 0

    # ------------------------------------------------------------- analysis
    def analyse(
        self,
        series: CandleSeries,
        detections: list[PatternDetection],
        *,
        context: dict[str, list[PatternDetection]] | None = None,
    ) -> SeriesConfluence:
        """Build the confluences of one series from the detections of all engines.

        ``context`` maps a slower timeframe to the detections tracked on it for the
        same symbol. Context readings are reported with their timeframe and can only
        contribute the MULTI_TIMEFRAME dimension - they are never mixed silently
        into the local ones.
        """
        started = time.perf_counter()
        result = SeriesConfluence(symbol=series.symbol, timeframe=series.timeframe.value)
        candles = [candle for candle in series.candles if candle.closed]
        result.bars_analyzed = len(candles)
        if not candles or not self.params.enabled:
            return result
        if len(candles) < self.params.global_.min_bars_required:
            result.notes.append("pas assez de bougies cloturees : aucune confluence tentee")
            return result

        atr = _atr(candles, self.params.global_.atr_period)
        slow_atr = _atr(candles, self.params.global_.atr_slow_period) or atr
        band = self.params.global_.price_band_atr * (slow_atr or atr)
        last_bar_time = candles[-1].time

        events = normalise(
            detections, symbol=series.symbol, timeframe=series.timeframe.value
        )
        # keep only the events that are still inside the temporal window
        fresh: list[ConfluenceEvent] = []
        for event in events:
            if _age_in_bars(candles, event.timestamp) <= self.params.global_.max_age_bars:
                fresh.append(event)
        result.events_considered = len(events)

        # context readings (slower timeframes, real detections, never invented)
        context_events: dict[str, list[ConfluenceEvent]] = {}
        for timeframe, items in (context or {}).items():
            if timeframe.upper() == series.timeframe.value.upper():
                continue
            normalised = normalise(items, symbol=series.symbol, timeframe=timeframe)
            if normalised:
                context_events[timeframe.upper()] = normalised

        bullish = [event for event in fresh if event.direction == "BULLISH"]
        bearish = [event for event in fresh if event.direction == "BEARISH"]
        neutral = [event for event in fresh if event.direction == "NEUTRAL"]

        groups: list[ConfluenceGroup] = []
        for direction, aligned in (("BULLISH", bullish), ("BEARISH", bearish)):
            if not aligned:
                continue
            group = self._build_group(
                series=series,
                candles=candles,
                atr=atr,
                band=band,
                direction=direction,
                aligned=aligned,
                opposing=bearish if direction == "BULLISH" else bullish,
                neutral=neutral,
                context_events=context_events,
                last_bar_time=last_bar_time,
            )
            if group is not None:
                groups.append(group)

        if not groups and neutral:
            groups.append(self._neutral_group(series, candles, neutral, last_bar_time, atr))

        # newest first, then strongest: the dashboard shows the most recent context
        groups.sort(key=lambda group: (group.window_end, group.score), reverse=True)
        result.groups = groups
        result.events_aligned = sum(len(group.events) for group in groups)
        self._runs += 1
        self._groups_seen += len(groups)
        self._events_considered += len(fresh)
        result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return result

    # ------------------------------------------------------------ group build
    def _build_group(
        self,
        *,
        series: CandleSeries,
        candles: list,
        atr: float,
        band: float,
        direction: str,
        aligned: list[ConfluenceEvent],
        opposing: list[ConfluenceEvent],
        neutral: list[ConfluenceEvent],
        context_events: dict[str, list[ConfluenceEvent]],
        last_bar_time: int,
    ) -> ConfluenceGroup | None:
        reference_time = max(event.timestamp for event in aligned)
        # (5.2) temporal alignment: a window of bars around the newest aligned event
        in_window = [
            event
            for event in aligned
            if abs(_bars_between(candles, event.timestamp, reference_time)) <= self.params.global_.window_bars
        ]
        in_window.sort(key=lambda event: (event.timestamp, event.id))
        if not in_window:
            return None

        # (5.2) price proximity: keep the most populated price cluster, then the
        # events inside the band around the anchor. An event far from that cluster
        # is another story and never joins this confluence.
        in_window = _cluster_by_price(in_window, band)
        if not in_window:
            return None
        anchor = in_window[0]
        reference_price = anchor.price
        if reference_price is not None and band > 0:
            in_window = [
                event
                for event in in_window
                if event.price is None or abs(event.price - reference_price) <= band
            ]
            if not in_window:
                return None
            anchor = in_window[0]
            reference_price = anchor.price

        kept = in_window[-self.params.global_.max_events :]

        opposing_local = [
            event
            for event in opposing
            if abs(_bars_between(candles, event.timestamp, reference_time)) <= self.params.global_.window_bars
            and (
                reference_price is None
                or event.price is None
                or abs(event.price - reference_price) <= band
            )
        ]

        # (5.6) multi-timeframe context, always labelled with its timeframe
        context_aligned, context_opposing, mtf_evidence = _split_context(
            context_events, direction, reference_time, self.params, local_timeframe=series.timeframe.value
        )
        mtf_component: list[ScoreComponent] = []
        if context_aligned and self.params.multi_timeframe.enabled:
            points = float(self.params.weights.multi_timeframe)
            if points > 0:
                timeframes = sorted(context_aligned.keys())
                mtf_component.append(
                    ScoreComponent(
                        dimension=ConfluenceDimension.MULTI_TIMEFRAME.value,
                        label=DIMENSION_LABELS[ConfluenceDimension.MULTI_TIMEFRAME.value],
                        points=points,
                        reason="tendance de contexte identique sur " + ", ".join(timeframes),
                        events=[event.id for events in context_aligned.values() for event in events],
                        timeframes=timeframes,
                    )
                )

        context_contradictions: list[ScoreComponent] = []
        if context_opposing:
            penalty = float(self.params.states.context_opposition_penalty)
            if penalty > 0:
                timeframes = sorted({event.timeframe for event in context_opposing})
                context_contradictions.append(
                    ScoreComponent(
                        dimension=ConfluenceDimension.STRUCTURE.value,
                        label=f"{DIMENSION_LABELS[ConfluenceDimension.STRUCTURE.value]} (contexte)",
                        points=-penalty,
                        reason="opposition de structure sur " + ", ".join(timeframes),
                        events=[event.id for event in context_opposing],
                        timeframes=timeframes,
                    )
                )

        components, contradictions, total = score_group(
            direction,
            kept,
            opposing_local,
            self.params,
            extra_components=mtf_component,
            extra_contradictions=context_contradictions,
        )
        contradiction_total = float(-sum(c.points for c in contradictions if c.points < 0))

        state = self._state(
            aligned=kept,
            opposing=opposing_local,
            components=components,
            contradictions=contradictions,
            score=total,
        )
        why, against = explain(direction, components, contradictions, neutral)

        group_id = _group_id(series.symbol, series.timeframe.value, direction, kept[0].timestamp)
        now = datetime.now(tz=timezone.utc)
        previous = self._registry.get(group_id)
        bar_seconds = series.timeframe.seconds
        group = ConfluenceGroup(
            id=group_id,
            dedup_key=group_id,
            signature=_signature(kept + opposing_local, [e.id for e in context_opposing]),
            symbol=series.symbol,
            timeframe=series.timeframe.value,
            direction=direction,
            state=state,
            score=total,
            max_score=self.params.max_score(),
            dimensions=[component.dimension for component in components],
            components=components,
            contradictions=contradictions,
            events=(
                kept
                + opposing_local
                + [event for items in context_aligned.values() for event in items]
                + context_opposing
            ),
            why=why,
            against=against,
            multi_timeframe=mtf_evidence,
            reference_price=reference_price,
            anchor_time=kept[0].timestamp,
            window_start=kept[0].timestamp,
            window_end=reference_time,
            created_at=previous.created_at if previous else now,
            updated_at=now,
            expires_at=now + timedelta(seconds=self.params.global_.validity_bars * bar_seconds),
            previous_state=previous.state if previous else None,
            state_since=(
                previous.state_since
                if previous and previous.state == state and previous.state_since
                else now
            ),
            generation=(previous.generation + 1) if previous else 1,
            note=(
                f"confluence {direction} sur {series.timeframe.value} : "
                f"{len(components)} dimension(s), {contradiction_total:g} point(s) de contradiction"
            ),
        )
        return group

    def _neutral_group(
        self,
        series: CandleSeries,
        candles: list,
        neutral: list[ConfluenceEvent],
        last_bar_time: int,
        atr: float,
    ) -> ConfluenceGroup:
        """Only neutral readings: explicit NO_CONFLUENCE, never a direction."""
        kept = neutral[-self.params.global_.max_events :]
        anchor = kept[0]
        group_id = _group_id(series.symbol, series.timeframe.value, "NEUTRAL", anchor.timestamp)
        now = datetime.now(tz=timezone.utc)
        previous = self._registry.get(group_id)
        return ConfluenceGroup(
            id=group_id,
            dedup_key=group_id,
            signature=_signature(kept, []),
            symbol=series.symbol,
            timeframe=series.timeframe.value,
            direction="NEUTRAL",
            state=ConfluenceState.NO_CONFLUENCE.value,
            score=0.0,
            max_score=self.params.max_score(),
            dimensions=[],
            events=kept,
            why=["lecture(s) neutre(s) uniquement : aucun biais directionnel observe"],
            against=["aucun element directionnel : rien a mettre en confluence"],
            reference_price=anchor.price,
            anchor_time=anchor.timestamp,
            window_start=kept[0].timestamp,
            window_end=last_bar_time,
            created_at=previous.created_at if previous else now,
            updated_at=now,
            expires_at=now
            + timedelta(seconds=self.params.global_.validity_bars * series.timeframe.seconds),
            previous_state=previous.state if previous else None,
            state_since=now,
            generation=(previous.generation + 1) if previous else 1,
            note="aucune confluence : lectures neutres",
        )

    def _state(
        self,
        *,
        aligned: list[ConfluenceEvent],
        opposing: list[ConfluenceEvent],
        components: list[ScoreComponent],
        contradictions: list[ScoreComponent],
        score: float,
    ) -> str:
        """Documented mapping (5.5): score + dimensions + contradictions -> state."""
        states = self.params.states
        glob = self.params.global_
        penalty = float(-sum(c.points for c in contradictions if c.points < 0))
        dimensions = [component.dimension for component in components]

        if len(aligned) < glob.min_events:
            return ConfluenceState.NO_CONFLUENCE.value
        if penalty >= states.contradiction_penalty and (opposing or contradictions):
            return ConfluenceState.CONTRADICTED.value
        if score >= states.strong_score and len(dimensions) >= states.strong_min_dimensions and not contradictions:
            return ConfluenceState.STRONG_CONFLUENCE.value
        # CONFLUENCE accepts a contradiction that stays below the CONTRADICTED
        # threshold (the points it cost are already deducted); STRONG_CONFLUENCE
        # requires a clean context. The opportunity engine (Phase 6) applies its own,
        # stricter rule before naming a BUY / SELL observation.
        if score >= states.confluence_score:
            return ConfluenceState.CONFLUENCE.value
        if score >= states.watch_score:
            return ConfluenceState.WATCH.value
        return ConfluenceState.NO_CONFLUENCE.value

    # ----------------------------------------------------------- registry
    def commit(self, result: SeriesConfluence) -> list[LifecycleEvent]:
        """Update the registry, then expire what the market left behind."""
        events: list[LifecycleEvent] = []
        symbol, timeframe = result.symbol, result.timeframe

        for group in result.groups:
            previous = self._registry.get(group.id)
            if previous is not None:
                group.created_at = previous.created_at
                group.previous_state = previous.state
                group.generation = previous.generation + 1
            self._registry[group.id] = group
            self._last_seen[group.id] = group.window_end
            events.extend(self._transitions(previous, group))
        events.extend(self._expire(symbol, timeframe, result))
        self._prune()
        return events

    def _transitions(
        self, previous: ConfluenceGroup | None, group: ConfluenceGroup
    ) -> list[LifecycleEvent]:
        if previous is None:
            # a group born already contradicted is an observation in itself: the two
            # camps are real and the dashboard must be able to say so immediately.
            if group.state == ConfluenceState.CONTRADICTED.value:
                return [LifecycleEvent("CONFLUENCE_CONTRADICTED", group, None)]
            if group.state in OBSERVED_STATES:
                return [LifecycleEvent("CONFLUENCE_DETECTED", group, None)]
            return []
        if previous.state == group.state:
            return []
        if group.state == ConfluenceState.CONTRADICTED.value:
            return [LifecycleEvent("CONFLUENCE_CONTRADICTED", group, previous.state)]
        if group.state in OBSERVED_STATES:
            return [LifecycleEvent("CONFLUENCE_UPDATED", group, previous.state)]
        return []

    def _expire(self, symbol: str, timeframe: str, result: SeriesConfluence) -> list[LifecycleEvent]:
        """A group nobody refreshed for ``validity_bars`` is expired, once."""
        if not result.groups:
            return []
        last_bar_time = max(group.window_end for group in result.groups)
        processed = {group.id for group in result.groups}
        events: list[LifecycleEvent] = []
        for group_id, group in list(self._registry.items()):
            if group.symbol != symbol or group.timeframe != timeframe or group_id in processed:
                continue
            age = _bars_between_seconds(last_bar_time, self._last_seen.get(group_id, group.window_end), Timeframe(timeframe).seconds)
            if age <= self.params.global_.validity_bars:
                continue
            previous_state = group.state
            group.state = ConfluenceState.EXPIRED.value
            group.previous_state = previous_state
            group.updated_at = datetime.now(tz=timezone.utc)
            events.append(LifecycleEvent("CONFLUENCE_EXPIRED", group, previous_state))
            self._registry.pop(group_id, None)
            self._last_seen.pop(group_id, None)
        return events

    def _prune(self) -> None:
        cap = self.params.global_.max_tracked
        if len(self._registry) <= cap:
            return
        ordered = sorted(self._registry.values(), key=lambda group: group.updated_at or datetime.min.replace(tzinfo=timezone.utc))
        for group in ordered[: len(self._registry) - cap]:
            self._registry.pop(group.id, None)
            self._last_seen.pop(group.id, None)
        logger.warning("Confluence registry pruned to %s entries", cap)

    def clear(self) -> None:
        self._registry.clear()
        self._last_seen.clear()

    # ------------------------------------------------------------- reading
    def all(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        *,
        states: tuple[str, ...] | None = None,
    ) -> list[ConfluenceGroup]:
        items = list(self._registry.values())
        if symbol:
            items = [group for group in items if group.symbol.upper() == symbol.upper()]
        if timeframe:
            items = [group for group in items if group.timeframe.upper() == timeframe.upper()]
        if states:
            items = [group for group in items if group.state in states]
        items.sort(key=lambda group: (group.window_end, group.score), reverse=True)
        return items

    def observed(self, symbol: str | None = None, timeframe: str | None = None) -> list[ConfluenceGroup]:
        return self.all(symbol, timeframe, states=tuple(OBSERVED_STATES))

    def get(self, group_id: str) -> ConfluenceGroup | None:
        return self._registry.get(group_id)

    def strongest(self, symbol: str | None = None, timeframe: str | None = None) -> ConfluenceGroup | None:
        items = self.observed(symbol, timeframe)
        return items[0] if items else None

    def stats(self) -> dict:
        states: dict[str, int] = {}
        directions: dict[str, int] = {}
        for group in self._registry.values():
            states[group.state] = states.get(group.state, 0) + 1
            directions[group.direction] = directions.get(group.direction, 0) + 1
        return {
            "engine": ENGINE_NAME,
            "runs": self._runs,
            "groups_built": self._groups_seen,
            "events_considered": self._events_considered,
            "tracked": len(self._registry),
            "by_state": states,
            "by_direction": directions,
            "max_score": self.params.max_score(),
        }


# --------------------------------------------------------------------- helpers
def _split_context(
    context_events: dict[str, list[ConfluenceEvent]],
    direction: str,
    reference_time: int,
    params: ConfluenceParams,
    *,
    local_timeframe: str,
) -> tuple[dict[str, list[ConfluenceEvent]], list[ConfluenceEvent], list[dict]]:
    """Split the context readings into aligned / opposing, keeping each timeframe visible.

    Only genuinely SLOWER timeframes are used as context, and nothing is mixed
    without its timeframe being written next to it. A higher timeframe reading the
    opposite way on STRUCTURE is reported as an opposition (it costs points).
    """
    if not params.multi_timeframe.enabled:
        return {}, [], []
    ordered = [tf for tf in params.multi_timeframe.higher_timeframes]
    local_seconds = _timeframe_seconds(local_timeframe)
    slower = [
        timeframe
        for timeframe in sorted(context_events)
        if _timeframe_seconds(timeframe) > local_seconds
    ]
    slower = slower[: params.multi_timeframe.context_timeframes]
    aligned: dict[str, list[ConfluenceEvent]] = {}
    opposing: list[ConfluenceEvent] = []
    evidence: list[dict] = []

    for timeframe in slower:
        events = context_events[timeframe]
        seconds = _timeframe_seconds(timeframe)
        window = params.multi_timeframe.max_age_bars * seconds
        recent = [event for event in events if abs(reference_time - event.timestamp) <= window]
        if not recent:
            continue
        same = [event for event in recent if event.direction == direction]
        against = [
            event
            for event in recent
            if event.direction == opposite(direction)
            and event.dimension == ConfluenceDimension.STRUCTURE.value
        ]
        if same:
            aligned[timeframe] = same
        opposing.extend(against)
        evidence.append(
            {
                "timeframe": timeframe,
                "direction": direction if same else ("OPPOSED" if against else "NEUTRAL"),
                "aligned": [event.id for event in same],
                "opposing": [event.id for event in against],
                "types": sorted({event.type for event in recent}),
                "bars_away": _bars_between_seconds(reference_time, recent[-1].timestamp, seconds),
            }
        )
    return aligned, opposing, evidence


def _timeframe_seconds(timeframe: str) -> int:
    try:
        return Timeframe(timeframe.upper()).seconds
    except ValueError:  # pragma: no cover - defensive
        return 900


def _bars_between(candles: list, start_time: int, end_time: int) -> int:
    index_start = _index_of_time(candles, start_time)
    index_end = _index_of_time(candles, end_time)
    if index_start is None or index_end is None:
        return 0
    return index_end - index_start


def _bars_between_seconds(start_time: int, end_time: int, seconds: int) -> int:
    if seconds <= 0:
        return 0
    return int(abs(end_time - start_time) // seconds)


def _index_of_time(candles: list, value: int) -> int | None:
    for index, candle in enumerate(candles):
        if candle.time == value:
            return index
    return None


def _age_in_bars(candles: list, event_time: int) -> int:
    """How many bars ago the event happened (0 = the last closed bar)."""
    last = candles[-1].time
    seconds = _timeframe_seconds_from_candles(candles)
    index = _index_of_time(candles, event_time)
    if index is not None:
        return len(candles) - 1 - index
    return int(max(0, (last - event_time) // seconds))


def _timeframe_seconds_from_candles(candles: list) -> int:
    if len(candles) >= 2:
        delta = candles[-1].time - candles[-2].time
        if delta > 0:
            return int(delta)
    return 900


def _atr(candles: list, period: int) -> float:
    """Mean true range over the last ``period`` closed bars (real OHLC only)."""
    if not candles:
        return 0.0
    window = candles[-max(1, period) :]
    start = len(candles) - len(window)
    ranges: list[float] = []
    for offset, candle in enumerate(window):
        index = start + offset
        if index == 0:
            ranges.append(candle.high - candle.low)
            continue
        previous_close = candles[index - 1].close
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return sum(ranges) / len(ranges) if ranges else 0.0
