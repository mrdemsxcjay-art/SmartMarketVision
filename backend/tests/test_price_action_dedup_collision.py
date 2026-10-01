"""Identifiant des detections Price Action : niveaux distincts, lots sans collision.

Ce fichier est ne de l'audit `AUDIT_PRICE_ACTION_ID_COLLISION.md` (defaut observe en
production : ``UNIQUE constraint failed: pattern_detections.id``) et fixe desormais
la correction.

Defaut corrige
--------------
``REJECTION`` et ``FAILED_BREAKOUT`` sont emis **une fois par niveau chartiste
reel**. Leur identifiant ne contenait ni le niveau ni sa source : deux detections
légitimes nees de deux niveaux differents touchees par la meme bougie portaient le
meme id. ``DetectionRepository.save_many`` insere alors deux fois la meme cle
primaire dans une transaction -> SQLite refuse -> *tout le lot* etait perdu.

Correction verifiee ici
-----------------------
1. l'identifiant inclut l'identite du niveau reel (id publie + prix) : meme niveau
   + meme bougie = meme id ; niveau different = id different ;
2. ``extra_signature`` de ``FAILED_BREAKOUT`` porte en plus le niveau reellement
   casse ;
3. ``save_many`` deduplique le lot avant insertion et ne peut plus produire deux
   INSERT du meme PK, sans jamais perdre une detection legitime.

Aucun seuil, aucun critere, aucune confiance, aucune logique de detection n'a ete
modifie : seules les cles d'identite et la defense en profondeur de la persistance.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.db.models  # noqa: F401  (enregistre les tables sur Base.metadata)
from app.db.base import Base
from app.db.models import MarketEventRow, PatternDetectionRow
from app.db.repository import DetectionRepository, EventRepository
from app.db.repository import _stable_identity
from app.price_action.engine import PriceActionEngine, dedup_key
from app.price_action.params import PriceActionParams
from app.services.events import EventBus
from app.services.price_action import PriceActionService
from tests import price_action_fixtures as fx


# --------------------------------------------------------------- infrastructure
@pytest.fixture
def session_factory(tmp_path: Path):
    """Une base SQLite temporaire avec EXACTEMENT la session du projet.

    ``autoflush=False`` est la configuration de ``app.db.base.SessionLocal`` : c'est
    elle qui rendait le defaut visible (avec l'autoflush par defaut, SQLAlchemy
    fusionnait silencieusement les deux lignes de meme cle et perdait une detection
    sans rien signaler).
    """
    engine = create_engine(f"sqlite:///{tmp_path/'audit.db'}", future=True)
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

    try:
        yield scope
    finally:
        engine.dispose()


@pytest.fixture
def engine() -> PriceActionEngine:
    return PriceActionEngine(PriceActionParams())


@pytest.fixture
def rejection_series():
    """La fixture existante : derniere bougie qui rejette un niveau par le bas."""
    series = fx.rejection()
    return series, series.candles[-1]


@pytest.fixture
def two_real_levels(rejection_series):
    """Deux niveaux REELS distincts, tous deux touches par la meche finale."""
    _, last = rejection_series
    return [
        fx.chartist_level("SUPPORT", 0.0, time=last.time, detection_id="ct_A"),
        fx.chartist_level("SUPPORT", 0.3, time=last.time, detection_id="ct_B"),
    ]


def _rejections(engine: PriceActionEngine, series, levels) -> list:
    return [d for d in engine.analyse(series, chartist=levels).detections if d.pattern == "REJECTION"]


# ------------------------------------------------- 1. identite des REJECTION
class TestRejectionIdentity:
    """L'id distingue les niveaux reels : c'est la cause racine corrigee."""

    def test_same_candle_same_level_keeps_the_same_id(self, engine, rejection_series):
        """Meme bougie + meme niveau = meme id (une seule detection, un seul id)."""
        series, last = rejection_series
        level = [fx.chartist_level("SUPPORT", 0.0, time=last.time, detection_id="ct_A")]

        first = _rejections(engine, series, level)
        second = _rejections(PriceActionEngine(PriceActionParams()), series, level)

        assert len(first) == 1 and len(second) == 1
        assert first[0].id == second[0].id, "le meme evenement doit garder le meme id"
        assert first[0].id.startswith("pa_")

    def test_same_candle_different_level_gives_different_ids(self, engine, rejection_series, two_real_levels):
        """Meme bougie + niveau different = ids differents (le defaut d'origine)."""
        series, _ = rejection_series
        rejections = _rejections(engine, series, two_real_levels)

        assert len(rejections) == 2, "le moteur doit emettre un rejet par niveau reel"
        levels = [d.evidence_points["measurements"]["level_price"] for d in rejections]
        assert levels[0] != levels[1], "les deux niveaux doivent etre reellement differents"
        assert rejections[0].confidence != rejections[1].confidence, "ce sont deux mesures distinctes"
        assert len({d.id for d in rejections}) == 2, "deux niveaux distincts doivent donner deux ids"

    def test_the_id_is_deterministic_and_carries_the_level(self, engine, rejection_series, two_real_levels):
        """L'id reste deterministe, et recomposable a partir du niveau reel."""
        series, last = rejection_series
        rejections = _rejections(engine, series, two_real_levels)
        again = _rejections(PriceActionEngine(PriceActionParams()), series, two_real_levels)

        assert [d.id for d in rejections] == [d.id for d in again], "id stable d'un run a l'autre"

        expected = "pa_" + hashlib.sha1(
            f"EURUSD|M15|REJECTION|{last.time}|level=SUPPORT:ct_A@1.1".encode("utf-8")
        ).hexdigest()[:16]
        assert rejections[0].id == expected, "symbol|timeframe|pattern|bougie|niveau reel"
        assert dedup_key("EURUSD", "M15", "REJECTION", last.time, level_ref="SUPPORT:ct_A@1.1") == expected
        assert dedup_key("EURUSD", "M15", "REJECTION", last.time) != expected

    def test_the_same_price_published_twice_gives_two_distinct_ids(self, engine, rejection_series):
        """Le chartiste publie le meme prix deux fois (son niveau + sa reference de
        cassure, meme detection) : ce sont deux references distinctes, donc deux ids.

        C'est la seconde moitie du defaut mesure sur donnees reelles : sans le type
        de niveau dans l'identite, ces deux references se confondaient encore.
        """
        series, last = rejection_series
        neckline = fx.chartist_level("NECKLINE", 0.0, time=last.time, detection_id="ct_9f1c")
        breakout = fx.chartist_breakout(
            level_pips=0.0,
            breakout_time=last.time,
            breakout_price_pips=3.0,
            parent_pattern="DOUBLE_TOP",
            detection_id="ct_9f1c",
        )
        rejections = _rejections(engine, series, [neckline, breakout])

        kinds = sorted(d.evidence_points["level"]["kind"] for d in rejections)
        assert len(kinds) == 2 and len(set(kinds)) == 2, "les deux references du meme prix sont emises"
        assert len({d.id for d in rejections}) == 2, "deux references distinctes, deux ids distincts"
        assert {d.evidence_points["measurements"]["level_price"] for d in rejections} == {rejections[0].evidence_points["measurements"]["level_price"]}, (
            "meme prix, meme detection d'origine : seul le type de niveau les separe"
        )

    def test_both_rejections_are_tracked_and_persisted_together(
        self, engine, rejection_series, two_real_levels, session_factory
    ):
        """Les deux detections vivent en parallele : registre ET base de donnees."""
        series, _ = rejection_series
        result = engine.analyse(series, chartist=two_real_levels)
        engine.commit(result)

        tracked = [d for d in engine.all() if d.pattern == "REJECTION"]
        assert len(tracked) == 2, "les deux rejets doivent coexister (plus d'ecrasement en memoire)"

        repo = DetectionRepository(session_factory=session_factory)
        assert repo.save_many(result.detections) == len(result.detections)
        assert repo.count() == len(result.detections)

    def test_no_collision_survives_the_next_ticks(self, engine, rejection_series, two_real_levels):
        """La collision ne revient pas : chaque tick repart avec deux ids distincts."""
        series, _ = rejection_series
        duplicates = []
        for _ in range(3):
            detections = engine.analyse(series, chartist=two_real_levels).detections
            duplicates.append(len(detections) - len({d.id for d in detections}))
        assert duplicates == [0, 0, 0]

    def test_a_tracked_rejection_never_changes_id(self, engine, rejection_series, two_real_levels):
        """Un evenement suivi garde son id au fil des analyses (pas de ligne fantome)."""
        series, _ = rejection_series
        engine.commit(engine.analyse(series, chartist=two_real_levels))
        before = sorted(d.id for d in engine.all() if d.pattern == "REJECTION")

        engine.commit(engine.analyse(series, chartist=two_real_levels))
        after = sorted(d.id for d in engine.all() if d.pattern == "REJECTION")
        assert before == after and len(after) == 2


# -------------------------------------------- 2. identite des FAILED_BREAKOUT
class TestFailedBreakoutIdentity:
    """Meme exigence pour les cassures manquees, dont la signature etait trop courte."""

    @staticmethod
    def _series_with_two_breakouts(engine: PriceActionEngine):
        calm = fx.calm_bars(70)
        up = fx.BarSpec(open=0.0, high=3.4, low=-0.2, close=3.0)
        back = fx.BarSpec(open=3.0, high=3.2, low=-3.0, close=-2.5)
        series = fx.series(calm + [up, back])
        return series

    def _breakouts(self, series, *, second_level: float):
        return [
            fx.chartist_breakout(
                level_pips=0.0, breakout_time=series.candles[70].time,
                breakout_price_pips=3.0, detection_id="ct_up_A",
            ),
            fx.chartist_breakout(
                level_pips=second_level, breakout_time=series.candles[70].time,
                breakout_price_pips=3.0, detection_id="ct_up_B",
            ),
        ]

    @staticmethod
    def _failed(detections) -> list:
        return [d for d in detections if d.pattern == "FAILED_BREAKOUT"]

    def test_same_candle_same_level_keeps_the_same_id(self, engine):
        """Meme bougie de cassure + meme bougie d'echec + meme niveau = meme id."""
        series = self._series_with_two_breakouts(engine)
        one = self._breakouts(series, second_level=0.5)[:1]

        first = self._failed(engine.analyse(series, chartist=one).detections)
        second = self._failed(PriceActionEngine(PriceActionParams()).analyse(series, chartist=one).detections)

        assert len(first) == 1 and len(second) == 1
        assert first[0].id == second[0].id
        assert first[0].id == dedup_key(
            "EURUSD", "M15", "FAILED_BREAKOUT", series.candles[71].time,
            extra=[series.candles[70].time, series.candles[71].time],
            level_ref="UPPER:ct_up_A@1.1",
        )

    def test_same_candle_different_level_gives_different_ids(self, engine):
        """Deux niveaux differents casses sur la meme bougie = deux ids differents."""
        series = self._series_with_two_breakouts(engine)
        failed = self._failed(engine.analyse(series, chartist=self._breakouts(series, second_level=0.5)).detections)

        assert len(failed) == 2, "les deux cassures manquees sont attendues"
        assert len({d.id for d in failed}) == 2, "un id par niveau reellement casse"

    def test_the_broken_level_is_part_of_the_signature(self, engine):
        """Chaque id est recomposable : bougies reelles + niveau reellement casse."""
        series = self._series_with_two_breakouts(engine)
        detections = self._failed(engine.analyse(series, chartist=self._breakouts(series, second_level=0.5)).detections)
        assert len(detections) == 2

        for detection, source_id in zip(sorted(detections, key=lambda d: d.id), ("ct_up_A", "ct_up_B")):
            level = detection.evidence_points["measurements"]["breakout_level"]
            expected = dedup_key(
                "EURUSD",
                "M15",
                "FAILED_BREAKOUT",
                detection.detected_at_bar_time,
                extra=[series.candles[70].time, detection.detected_at_bar_time],
                level_ref=f"UPPER:{source_id}@{round(level, 6)}",
            )
            assert detection.id == expected, f"signature incomplete pour {source_id}"

        # sans le niveau casse, les deux cassures partageaient bien un seul id
        plain = {
            dedup_key(
                "EURUSD", "M15", "FAILED_BREAKOUT", d.detected_at_bar_time,
                extra=[series.candles[70].time, d.detected_at_bar_time],
            )
            for d in detections
        }
        assert len(plain) == 1, "c'est bien la signature d'origine qui etait ambigue"


# --------------------------------------------- 3. deduplication dans save_many
class TestSaveManyDeduplication:
    """Defense en profondeur : plus aucun lot ne peut etre perdu ou duplique."""

    def test_a_healthy_three_detection_batch_is_persisted(self, engine, rejection_series, two_real_levels, session_factory):
        """OUTSIDE_BAR + REJECTION niveau A + REJECTION niveau B = 3 lignes."""
        series, _ = rejection_series
        detections = engine.analyse(series, chartist=two_real_levels).detections
        patterns = sorted(d.pattern for d in detections)
        assert patterns == ["OUTSIDE_BAR", "REJECTION", "REJECTION"]

        repo = DetectionRepository(session_factory=session_factory)
        assert repo.save_many(detections) == 3
        assert repo.count() == 3, "les trois detections sont ecrites, y compris les deux rejets"
        assert sorted(row["pattern"] for row in repo.history(limit=10)) == patterns

    def test_strictly_identical_duplicates_are_written_once(self, engine, rejection_series, session_factory):
        """Deux objets strictement identiques : 1 ligne, aucune IntegrityError."""
        series, last = rejection_series
        level = [fx.chartist_level("SUPPORT", 0.0, time=last.time, detection_id="ct_A")]
        detection = _rejections(engine, series, level)[0]

        repo = DetectionRepository(session_factory=session_factory)
        assert repo.save_many([detection, detection, detection.model_copy()]) == 1
        assert repo.count() == 1

    def test_a_batch_of_same_id_different_events_never_fails(self, engine, rejection_series, two_real_levels, session_factory):
        """Cas extreme force a la main : meme id, contenus differents -> 2 lignes, pas d'erreur.

        C'est l'etat qui faisait echouer tout le lot avant la correction. La defense
        en profondeur ne perd aucune des deux detections : leurs cles de stockage
        sont desambiguisees par leur contenu, de facon deterministe.
        """
        series, _ = rejection_series
        rejections = _rejections(engine, series, two_real_levels)
        forced = [rejections[0], rejections[1].model_copy(update={"id": rejections[0].id, "dedup_key": rejections[0].id})]
        assert forced[0].id == forced[1].id and _stable_identity(forced[0]) != _stable_identity(forced[1])

        repo = DetectionRepository(session_factory=session_factory)
        assert repo.save_many(forced) == 2, "aucune detection legitime n'est perdue"
        assert repo.count() == 2, "deux lignes, deux cles primaires distinctes"

    def test_an_already_persisted_detection_is_updated_in_place(self, engine, rejection_series, two_real_levels, session_factory):
        """Une detection deja en base est mise a jour : aucun doublon, aucune erreur."""
        series, _ = rejection_series
        detections = engine.analyse(series, chartist=two_real_levels).detections
        repo = DetectionRepository(session_factory=session_factory)

        assert repo.save_many(detections) == 3
        assert repo.save_many(detections) == 3, "idempotent : la seconde ecriture met a jour"
        assert repo.count() == 3
        assert len({row["id"] for row in repo.history(limit=10)}) == 3

    def test_the_legacy_row_of_a_detection_is_not_duplicated(self, engine, rejection_series, session_factory, tmp_path):
        """Ancien id (avant correction) : la ligne existe, l'ecriture reste idempotente."""
        series, last = rejection_series
        level = [fx.chartist_level("SUPPORT", 0.0, time=last.time, detection_id="ct_A")]
        detection = _rejections(engine, series, level)[0]
        legacy = detection.model_copy(update={"id": "pa_0000000000000000", "dedup_key": "pa_0000000000000000"})

        repo = DetectionRepository(session_factory=session_factory)
        repo.save_many([legacy])
        repo.save_many([legacy])
        assert repo.count() == 1
        assert repo.get("pa_0000000000000000")["dedup_key"] == "pa_0000000000000000"

        # la nouvelle detection cohabite avec l'ancienne ligne, sans la toucher
        repo.save_many([detection])
        assert repo.count() == 2
        assert repo.get("pa_0000000000000000") is not None

    def test_the_autoflush_setting_no_longer_hides_anything(self, rejection_series, two_real_levels, tmp_path):
        """Le resultat ne depend plus du reglage d'autoflush de la session."""
        series, _ = rejection_series
        engine = PriceActionEngine(PriceActionParams())
        detections = engine.analyse(series, chartist=two_real_levels).detections

        for autoflush in (False, True):
            engine_db = create_engine(f"sqlite:///{tmp_path/f'autoflush_{autoflush}.db'}", future=True)
            Base.metadata.create_all(engine_db)
            factory = sessionmaker(bind=engine_db, autoflush=autoflush, expire_on_commit=False, future=True)

            @contextmanager
            def scope(factory=factory):
                session = factory()
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()

            repo = DetectionRepository(session_factory=scope)
            assert repo.save_many(detections) == 3
            assert repo.count() == 3, f"autoflush={autoflush} ne doit plus rien perdre"
            engine_db.dispose()


# ------------------------------------------------- 4. service : bout en bout
class TestServiceEndToEnd:
    """Le service ne journalise plus d'erreur de persistance sur ce cas."""

    def test_the_service_persists_the_whole_batch(self, engine, rejection_series, two_real_levels, session_factory):
        series, _ = rejection_series
        detections_repo = DetectionRepository(session_factory=session_factory)
        service = PriceActionService(
            engine=engine,
            bus=EventBus(),
            detection_repository=detections_repo,
            event_repository=EventRepository(session_factory=session_factory),
        )
        result = service.analyse(series, chartist=two_real_levels, publish=True)

        assert len(result.detections) == 3
        assert service.errors == [], "plus aucune erreur de persistance"
        assert detections_repo.count() == 3

        with session_factory() as session:
            events = [row[0] for row in session.execute(select(MarketEventRow.event_type)).all()]
        # 3 detections annoncees + l'evenement de cycle de vie de la bougie englobante
        assert events.count("PRICE_ACTION_DETECTED") == 3
        assert events.count("PRICE_ACTION_CONFIRMED") == 1

    def test_events_and_detections_stay_consistent_over_ticks(self, engine, rejection_series, two_real_levels, session_factory):
        """Detections persistees et evenements publies restent coherents."""
        series, _ = rejection_series
        detections_repo = DetectionRepository(session_factory=session_factory)
        service = PriceActionService(
            engine=engine,
            bus=EventBus(),
            detection_repository=detections_repo,
            event_repository=EventRepository(session_factory=session_factory),
        )
        for _ in range(3):
            service.analyse(series, chartist=two_real_levels, publish=True)

        with session_factory() as session:
            detections = session.scalar(select(func.count()).select_from(PatternDetectionRow))
            events = session.scalar(select(func.count()).select_from(MarketEventRow))
        assert service.errors == []
        assert detections == 3, "les trois detections restent en base"
        assert events == 4, "3 annonces + 1 cycle de vie, sans republication aux ticks suivants"
