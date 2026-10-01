"""Phase 7 - Chart Capture tests.

Acceptance criteria checked here:

* the PNG is produced from the REAL candle series and the REAL detections of the
  three engines (7.1): no placeholder image, and no file at all when there is no
  data;
* overlays are prioritised main event > confluence > sources > context, and what
  does not fit is reported instead of being piled up (7.2);
* the phone resolution is readable and a Telegram variant exists (7.3);
* the metadata carries capture_id / opportunity_id / symbol / timeframe /
  timestamp / path / hash, and the hash is the real sha256 of the file (7.4);
* two identical readings produce one file (dedup), two different readings do not;
* the renderer never blocks the scanner (7.5).

Image assertions are made on the real pixels with Pillow: a capture that would be
blank, truncated or of the wrong size fails here.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.capture.params import CaptureParams
from app.capture.renderer import _SlotAllocator, render_scene, save_png
from app.capture.scene import build_scene
from app.capture.service import (
    STATUS_DISABLED,
    STATUS_NO_DATA,
    STATUS_READY,
    CaptureService,
    capture_id_for,
)
from app.container import Container
from app.db.repository import CaptureRepository
from app.main import app as fastapi_app
from app.patterns.engine import ChartPatternEngine
from app.patterns.params import PatternParams
from app.price_action.engine import PriceActionEngine
from app.price_action.params import PriceActionParams
from app.smc_ict.engine import SmcIctEngine
from app.smc_ict.params import SmcIctParams
from app.confluence.engine import ConfluenceEngine
from app.confluence.params import ConfluenceParams
from app.opportunities.engine import OpportunityEngine
from app.opportunities.params import OpportunityParams
from tests import confluence_fixtures as cf_fx
from tests import opportunity_fixtures as op_fx


@pytest.fixture
def market():
    bars = cf_fx.calm(70) + [
        cf_fx.BarSpec(open=0.0, high=0.6, low=-0.4, close=0.4),
        cf_fx.BarSpec(open=0.4, high=1.2, low=0.2, close=1.0),
        cf_fx.BarSpec(open=1.0, high=1.6, low=0.8, close=1.4),
    ]
    return cf_fx.series(bars)


@pytest.fixture
def detections(market):
    """The six detections behind the reading, with the exact shape the engines publish.

    The prices are spread over the range of the series, as real levels are (this is
    what the capture has to show), and the times are real bar times of the series.
    """
    time = market.candles[-1].time
    return [
        cf_fx.bos("fx_bos", direction="BULLISH", time=time, price=1.09995),
        cf_fx.sweep("fx_sweep", direction="BULLISH", time=time, price=1.09997),
        cf_fx.fvg("fx_fvg", direction="BULLISH", time=time, price=1.10002),
        cf_fx.order_block("fx_ob", direction="BULLISH", time=time, price=1.10004),
        cf_fx.price_action("fx_pa", "BULLISH_PIN_BAR", direction="BULLISH", time=time, price=1.10010),
        cf_fx.chartist("fx_ct", "SUPPORT", direction="BULLISH", time=time, price=1.10014),
        cf_fx.displacement("fx_disp", direction="BULLISH", time=time, price=1.10012),
    ]


@pytest.fixture
def pipeline(market, detections):
    """The real chain: the confluence engine and the opportunity engine really run."""
    confluence = ConfluenceEngine(ConfluenceParams())
    cf_result = confluence.analyse(market, detections)
    confluence.commit(cf_result)

    engine = OpportunityEngine(op_fx.params())
    op_result = engine.analyse(market, cf_result.groups)
    engine.commit(op_result)

    return {
        "detections": detections,
        "confluences": cf_result.groups,
        "opportunity": op_result.opportunities[0] if op_result.opportunities else None,
        "engine": engine,
    }


@pytest.fixture
def service(tmp_path):
    return CaptureService(
        params=CaptureParams(enabled=True),
        repository=CaptureRepository(session_factory=_session_factory(tmp_path)),
        event_repository=None,
        output_dir=tmp_path / "captures",
    )


class TestRealImage:
    def test_a_capture_is_a_real_png_of_the_right_size(self, service, market, pipeline):
        result = service.capture_now(
            market,
            detections=pipeline["detections"],
            confluences=pipeline["confluences"],
            opportunity=pipeline["opportunity"],
        )
        assert result.status == STATUS_READY, result.reason
        metadata = result.metadata
        assert metadata is not None

        path = metadata.path
        assert path.endswith(".png")
        image = Image.open(path)
        assert image.format == "PNG"
        assert image.size == (1080, 1350), "resolution telephone exacte"
        assert metadata.width == 1080 and metadata.height == 1350
        assert metadata.bytes > 10_000, "une image non vide pese plus que quelques octets"

        telegrams = list((service.output_dir).glob("*_telegram.png"))
        assert telegrams, "la variante Telegram doit exister"
        telegram = Image.open(telegrams[0])
        assert telegram.size == (1200, 675)

    def test_the_image_is_not_blank_and_contains_candles(self, service, market, pipeline):
        result = service.capture_now(market, detections=pipeline["detections"], confluences=pipeline["confluences"])
        image = Image.open(result.metadata.path).convert("RGB")
        colours = image.getcolors(maxcolors=200_000)
        assert colours and len(colours) > 20, "une capture reelle contient de nombreuses couleurs"
        bull = sum(count for count, color in colours if _close(color, (38, 194, 129)))
        bear = sum(count for count, color in colours if _close(color, (239, 83, 80)))
        assert bull > 500 and bear > 500, "les bougies haussieres et baissieres sont dessinees"
        # the header is not empty: the text pixels are present
        header = image.crop((0, 0, image.width, 100))
        dark = sum(count for count, color in header.getcolors(maxcolors=200_000) if sum(color) > 480)
        assert dark > 500, "le bandeau (symbole, TF, etat, prix) est bien dessine"

    def test_no_placeholder_is_ever_written_without_data(self, service):
        empty = cf_fx.series(cf_fx.calm(0))
        result = service.capture_now(empty)
        assert result.status == STATUS_NO_DATA
        assert result.metadata is None
        assert list(service.output_dir.glob("*.png")) == [], "aucune image inventee"

    def test_a_disabled_capture_reports_not_implemented(self, tmp_path, market, pipeline):
        service = CaptureService(
            params=CaptureParams(enabled=False),
            repository=CaptureRepository(session_factory=_session_factory(tmp_path)),
            output_dir=tmp_path / "captures",
        )
        result = service.capture_now(market, detections=pipeline["detections"])
        assert result.status == STATUS_DISABLED
        assert list((tmp_path / "captures").glob("*.png")) == []

    def test_the_header_carries_the_real_identity(self, market, pipeline):
        scene = build_scene(
            market,
            detections=pipeline["detections"],
            confluences=pipeline["confluences"],
            opportunity=pipeline["opportunity"],
            params=CaptureParams(),
        )
        assert scene.symbol == "EURUSD"
        assert scene.timeframe == "M15"
        assert scene.price == market.candles[-1].close
        assert scene.title == "EURUSD - M15"
        assert scene.candles[-1].time == market.candles[-1].time
        assert any("onfluence" in line for line in scene.headline), "la confluence lue est nommee"


class TestOverlays:
    def test_overlays_are_prioritised(self, market, pipeline):
        scene = build_scene(
            market,
            detections=pipeline["detections"],
            confluences=pipeline["confluences"],
            opportunity=pipeline["opportunity"],
            params=CaptureParams(),
        )
        priorities = [overlay.priority for overlay in scene.overlays]
        assert priorities, "une capture reelle porte des overlays"
        assert min(priorities) == 1, "l'opportunite est dessinee en premier"
        assert 2 in priorities, "la confluence est dessinee"
        assert all(overlay.source or overlay.source_id for overlay in scene.overlays), "chaque overlay a sa source"

    def test_the_budget_is_enforced_and_reported(self, market, pipeline):
        params = CaptureParams(overlays={"max_sources": 2, "max_zones": 1, "max_levels": 2, "max_labels": 4})
        scene = build_scene(
            market,
            detections=pipeline["detections"],
            confluences=pipeline["confluences"],
            opportunity=pipeline["opportunity"],
            params=params,
        )
        zones = [item for item in scene.overlays if item.kind.value == "ZONE"]
        levels = [item for item in scene.overlays if item.kind.value == "LEVEL"]
        assert len(zones) <= 1 and len(levels) <= 2
        assert len(scene.overlays) <= 4 + 2 + 1 + 2
        assert scene.notes, "ce qui n'a pas ete dessine est annonce, jamais cache"

    def test_two_labels_never_share_the_same_slot(self):
        allocator = _SlotAllocator(top=0, bottom=200, height=20, gap=6, max_labels=5)
        placed = [allocator.place(100) for _ in range(5)]
        assert all(center is not None for center in placed)
        ordered = sorted(placed)
        for first, second in zip(ordered, ordered[1:]):
            assert second - first >= 20 + 6, "deux etiquettes ne peuvent pas se chevaucher"
        assert allocator.place(100) is None and allocator.skipped == 1, "au-dela du plafond, on saute"

    def test_the_render_scene_draws_all_the_engine_families(self, market, pipeline):
        scene = build_scene(
            market,
            detections=pipeline["detections"],
            confluences=pipeline["confluences"],
            opportunity=pipeline["opportunity"],
            params=CaptureParams(),
        )
        sources = {overlay.source for overlay in scene.overlays}
        assert "CONFLUENCE" in sources
        assert sources & {"CHART_PATTERN_ENGINE", "PRICE_ACTION_ENGINE", "SMC_ICT_ENGINE"}, (
            "les moteurs sources sont nommes avec leur vraie identite"
        )
        labels = {overlay.label for overlay in scene.overlays}
        assert any("SMC/ICT" in label or "(PA)" in label or "Chartiste" in label for label in labels), (
            "les etiquettes portent un nom lisible du moteur"
        )

    def test_labels_are_readable_and_short(self, market, pipeline):
        scene = build_scene(
            market,
            detections=pipeline["detections"],
            confluences=pipeline["confluences"],
            opportunity=pipeline["opportunity"],
            params=CaptureParams(),
        )
        for overlay in scene.overlays:
            assert overlay.label and len(overlay.label) <= 60
            assert "_ENGINE" not in overlay.label, "l'identifiant technique du moteur est traduit"
            assert "BULLISH_" not in overlay.label and "BEARISH_" not in overlay.label


class TestMetadataAndDedup:
    def test_metadata_is_complete_and_the_hash_is_the_real_one(self, service, market, pipeline):
        result = service.capture_now(
            market,
            detections=pipeline["detections"],
            confluences=pipeline["confluences"],
            opportunity=pipeline["opportunity"],
        )
        metadata = result.metadata
        assert metadata.capture_id.startswith("cap_")
        assert metadata.opportunity_id == (pipeline["opportunity"].id if pipeline["opportunity"] else None)
        assert metadata.symbol == "EURUSD" and metadata.timeframe == "M15"
        assert metadata.timestamp is not None
        assert metadata.overlay_count == len(result.scene.overlays)
        digest = hashlib.sha256(open(metadata.path, "rb").read()).hexdigest()
        assert metadata.hash == digest, "le hash est celui du fichier ecrit"

    def test_the_same_reading_produces_one_file(self, service, market, pipeline):
        first = service.capture_now(market, detections=pipeline["detections"], opportunity=pipeline["opportunity"])
        second = service.capture_now(market, detections=pipeline["detections"], opportunity=pipeline["opportunity"])
        assert second.status == STATUS_READY
        assert second.reused is True, "une lecture identique reutilise la capture"
        assert first.metadata.capture_id == second.metadata.capture_id
        assert len(list(service.output_dir.glob("*_phone.png"))) == 1
        assert service.repository.count() == 1
        assert service.rendered == 1 and service.reused == 1

    def test_a_new_bar_produces_a_new_capture(self, service, market, pipeline):
        first = service.capture_now(market, detections=pipeline["detections"])
        later = cf_fx.series([*cf_fx.calm(70), cf_fx.BarSpec(open=0.0, high=0.4, low=-0.2, close=0.2)])
        second = service.capture_now(later, detections=pipeline["detections"])
        assert second.metadata.capture_id != first.metadata.capture_id
        assert service.repository.count() == 2

    def test_identity_depends_on_the_observation(self):
        assert capture_id_for("EURUSD", "M15", 1_760_000_000, "op_1") != capture_id_for(
            "EURUSD", "M15", 1_760_000_000, "op_2"
        )
        assert capture_id_for("EURUSD", "M15", 1_760_000_000, "op_1") == capture_id_for(
            "EURUSD", "M15", 1_760_000_000, "op_1"
        )

    def test_the_database_row_keeps_the_traceability(self, service, market, pipeline):
        result = service.capture_now(service, market, detections=pipeline["detections"]) if False else None
        captured = service.capture_now(
            market,
            detections=pipeline["detections"],
            confluences=pipeline["confluences"],
            opportunity=pipeline["opportunity"],
        )
        row = service.get(captured.metadata.capture_id)
        assert row and row["path"] == captured.metadata.path
        assert row["digest"] == captured.metadata.hash
        assert row["width"] == 1080 and row["height"] == 1350
        assert row["overlays"]["items"], "les overlays dessines sont listes dans la ligne"


class TestNonBlocking:
    @pytest.mark.asyncio
    async def test_request_queues_without_rendering(self, service, market, pipeline):
        identifier = service.request(
            market, detections=pipeline["detections"], confluences=pipeline["confluences"]
        )
        assert identifier and service.queue_size == 1
        assert list(service.output_dir.glob("*.png")) == [], "l'appel ne rend rien : c'est un worker qui le fait"

        service.start_worker()
        for _ in range(80):
            if service.rendered or service.failed:
                break
            await __import__("asyncio").sleep(0.05)
        await service.stop_worker()
        assert service.rendered == 1, "le worker rend la capture demandee"
        assert list(service.output_dir.glob("*_phone.png")), "et le fichier existe bien"

    def test_a_broken_renderer_reports_a_failure_instead_of_raising(self, tmp_path, market, pipeline, monkeypatch):
        service = CaptureService(
            params=CaptureParams(enabled=True),
            repository=CaptureRepository(session_factory=_session_factory(tmp_path)),
            output_dir=tmp_path / "captures",
        )
        monkeypatch.setattr("app.capture.service.render_scene", _boom)
        result = service.capture_now(market, detections=pipeline["detections"])
        assert result.status == "CAPTURE_FAILED"
        assert service.failed == 1 and service.errors
        assert list((tmp_path / "captures").glob("*.png")) == []


class TestApi:
    @pytest.fixture
    def client(self, tmp_path):
        container = Container.build()
        container.capture = CaptureService(
            params=CaptureParams(enabled=True),
            repository=CaptureRepository(session_factory=_session_factory(tmp_path)),
            event_repository=None,
            output_dir=tmp_path / "captures",
        )
        fastapi_app.state.container = container
        with TestClient(fastapi_app) as test_client:
            yield test_client, container

    def test_the_gallery_is_empty_and_honest(self, client):
        test_client, _ = client
        body = test_client.get("/api/captures").json()
        assert body["count"] == 0 and body["captures"] == []
        assert body["stats"]["enabled"] is True
        assert body["trading_signal"] is False

    def test_a_capture_is_served_as_a_png(self, client, market, pipeline):
        test_client, container = client
        result = container.capture.capture_now(
            market, detections=pipeline["detections"], confluences=pipeline["confluences"]
        )
        identifier = result.metadata.capture_id

        gallery = test_client.get("/api/captures").json()
        assert gallery["count"] == 1 and gallery["captures"][0]["id"] == identifier

        detail = test_client.get(f"/api/captures/{identifier}")
        assert detail.status_code == 200
        assert detail.json()["digest"] == result.metadata.hash

        file_response = test_client.get(f"/api/captures/{identifier}/file")
        assert file_response.status_code == 200
        assert file_response.headers["content-type"] == "image/png"
        assert file_response.content[:8] == b"\x89PNG\r\n\x1a\n", "le fichier servi est bien un PNG"

        telegram = test_client.get(f"/api/captures/{identifier}/file?tier=telegram")
        assert telegram.status_code == 200 and telegram.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_unknown_capture_is_404(self, client):
        test_client, _ = client
        assert test_client.get("/api/captures/cap_inconnu").status_code == 404
        assert test_client.get("/api/captures/cap_inconnu/file").status_code == 404

    def test_params_are_visible_and_adjustable(self, client):
        test_client, container = client
        params = test_client.get("/api/captures/params").json()
        assert params["groups"] == ["layout", "overlays"]
        assert params["params"]["derived"]["resolutions"]["phone"]["width"] == 1080

        response = test_client.patch("/api/captures/params", json={"overrides": {"overlays": {"max_labels": 10}}})
        assert response.status_code == 200
        assert "overlays.max_labels=10" in response.json()["applied"]
        assert container.capture.params.overlays.max_labels == 10
        container.capture.params.overlays.max_labels = 14


def _close(colour, target, tolerance: int = 12) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(colour, target))


def _boom(*args, **kwargs):
    raise RuntimeError("renderer down")


def _session_factory(tmp_path):
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.db.models  # noqa: F401
    from app.db.base import Base

    engine = create_engine(f"sqlite:///{tmp_path/'captures.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return scope
