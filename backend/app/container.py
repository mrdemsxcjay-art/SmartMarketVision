"""Service container.

Plain object graph, built once at startup: no framework, no microservice.
Tests can swap any member (``container.market = FakeMarketService()``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.confluence.engine import ConfluenceEngine
from app.confluence.params import params as confluence_params
from app.capture.params import params as capture_params
from app.capture.service import CaptureService
from app.db.repository import (
    CandleRepository,
    CaptureRepository,
    ConfluenceRepository,
    OpportunityRepository,
    TelegramOutboxRepository,
    DetectionRepository,
    EventRepository,
    ScannerRunRepository,
)
from app.patterns.engine import ChartPatternEngine
from app.patterns.params import params as pattern_params
from app.price_action.engine import PriceActionEngine
from app.price_action.params import params as price_action_params
from app.opportunities.engine import OpportunityEngine
from app.opportunities.params import params as opportunity_params
from app.services.confluence import ConfluenceService
from app.services.opportunities import OpportunityService
from app.services.events import EventBus, event_bus
from app.services.market_service import MarketService
from app.services.patterns import PatternService
from app.services.price_action import PriceActionService
from app.services.scanner import MarketScanner
from app.services.smc_ict import SmcIctService
from app.services.telegram import TelegramNotifier, notifier
from app.services.visual_capture import ChartSnapshotService, snapshot_service
from app.telegram.outbox import TelegramOutbox
from app.telegram.params import params as telegram_params
from app.smc_ict.engine import SmcIctEngine
from app.smc_ict.params import params as smc_ict_params


@dataclass
class Container:
    market: MarketService
    scanner: MarketScanner
    bus: EventBus
    notifier: TelegramNotifier
    snapshots: ChartSnapshotService
    candles_repo: CandleRepository
    events_repo: EventRepository
    detections_repo: DetectionRepository
    runs_repo: ScannerRunRepository
    patterns: PatternService
    price_action: PriceActionService
    smc_ict: SmcIctService

    #: Phase 5+ members have defaults so a container built by an older caller (a
    #: test fixture, for instance) keeps working without carrying them explicitly.
    confluences_repo: ConfluenceRepository = field(default_factory=ConfluenceRepository)
    confluence: ConfluenceService = field(default_factory=ConfluenceService)
    opportunities_repo: OpportunityRepository = field(default_factory=OpportunityRepository)
    opportunities: OpportunityService = field(default_factory=OpportunityService)
    captures_repo: CaptureRepository = field(default_factory=CaptureRepository)
    capture: CaptureService = field(default_factory=CaptureService)
    telegram: TelegramOutbox = field(default_factory=TelegramOutbox)

    @classmethod
    def build(cls) -> "Container":
        candles_repo = CandleRepository()
        events_repo = EventRepository()
        runs_repo = ScannerRunRepository()
        detections_repo = DetectionRepository()
        confluences_repo = ConfluenceRepository()
        market = MarketService(repository=candles_repo, event_repository=events_repo)
        patterns = PatternService(
            engine=ChartPatternEngine(pattern_params),
            bus=event_bus,
            detection_repository=detections_repo,
            event_repository=events_repo,
        )
        price_action = PriceActionService(
            engine=PriceActionEngine(price_action_params),
            bus=event_bus,
            detection_repository=detections_repo,
            event_repository=events_repo,
        )
        smc_ict = SmcIctService(
            engine=SmcIctEngine(smc_ict_params),
            bus=event_bus,
            detection_repository=detections_repo,
            event_repository=events_repo,
        )
        captures_repo = CaptureRepository()
        captures = CaptureService(
            params=capture_params,
            repository=captures_repo,
            bus=event_bus,
            event_repository=events_repo,
        )
        #: one notifier instance for the app: the outbox is its only caller besides
        #: the Phase 1 test route, and it exposes no secret in any of its payloads.
        telegram = TelegramOutbox(
            params=telegram_params,
            repository=TelegramOutboxRepository(),
            notifier=notifier,
            bus=event_bus,
            captures=captures,
            event_repository=events_repo,
        )
        opportunities_repo = OpportunityRepository()
        opportunities = OpportunityService(
            engine=OpportunityEngine(opportunity_params),
            bus=event_bus,
            repository=opportunities_repo,
            event_repository=events_repo,
            outbox=telegram,
        )
        confluence = ConfluenceService(
            engine=ConfluenceEngine(confluence_params),
            bus=event_bus,
            repository=confluences_repo,
            event_repository=events_repo,
        )
        scanner = MarketScanner(
            market_service=market,
            bus=event_bus,
            event_repository=events_repo,
            run_repository=runs_repo,
            pattern_service=patterns,
            price_action_service=price_action,
            smc_ict_service=smc_ict,
            confluence_service=confluence,
            opportunity_service=opportunities,
            capture_service=captures,
        )
        return cls(
            market=market,
            scanner=scanner,
            bus=event_bus,
            notifier=notifier,
            snapshots=snapshot_service,
            candles_repo=candles_repo,
            events_repo=events_repo,
            detections_repo=detections_repo,
            confluences_repo=confluences_repo,
            runs_repo=runs_repo,
            patterns=patterns,
            price_action=price_action,
            smc_ict=smc_ict,
            confluence=confluence,
            opportunities_repo=opportunities_repo,
            opportunities=opportunities,
            captures_repo=captures_repo,
            capture=captures,
            telegram=telegram,
        )


container = Container.build()
