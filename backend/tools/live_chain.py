"""Bout en bout P5 -> P8, rejouable : OHLC reels -> confluence -> opportunite ->
capture PNG reelle -> outbox Telegram -> expediteur.

Ce script est la verification manuelle de la chaine complete demandee en fin de
phase. Il ne fabrique AUCUNE donnee :

  * les chandeliers viennent du provider configure (Yahoo par defaut) ;
  * les detections, confluences et opportunites viennent des moteurs reels ;
  * la capture est un PNG rendu depuis ces chandeliers ;
  * l'alerte part dans l'outbox Telegram, en DRY_RUN par defaut.

SECURITE : le token n'est jamais ecrit, jamais affiche, jamais enregistre. Le
mode REAL n'est jamais force ici : lancez sans variables Telegram pour rester en
NOT_CONFIGURED, ou avec TELEGRAM_MODE=DRY_RUN + variables factices pour
verifier l'envoi simule. Aucun ordre n'est passe : le projet n'a pas d'API
d'execution.

Usage :
    python3 tools/live_chain.py                 # base SQLite temporaire
    python3 tools/live_chain.py --keep          # conserve la base temporaire
    python3 tools/live_chain.py --symbol SGDJPY --timeframe H1
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare_environment(database_path: Path) -> None:
    """Point the app at a throwaway database and keep Telegram in DRY_RUN."""
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{database_path}"
    os.environ.setdefault("TELEGRAM_MODE", "DRY_RUN")
    # a fake token only makes the notifier look configured: nothing is ever sent
    # over the network in DRY_RUN, and the value is never printed by this script.
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:DRY-RUN-NOT-A-REAL-TOKEN")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "0")
    os.environ.setdefault("LOG_LEVEL", "WARNING")


async def run(symbol: str | None, timeframe: str | None, keep: bool, test_alert: bool) -> int:
    from app.container import Container
    from app.db.base import init_db
    from app.telegram.messages import build_message

    def value(item) -> str:
        """Enum or already-serialised string: never altered, just unwrapped."""
        return getattr(item, "value", item)

    init_db()
    container = Container.build()
    scanner = container.scanner
    # le perimetre vient de la configuration (.env) : on ne modifie pas les
    # moteurs, on restreint seulement le tick a ce que l'operateur demande.
    from app.config import settings as app_settings

    if symbol:
        app_settings.watchlist = symbol.upper()
    if timeframe:
        app_settings.scanner_default_timeframe = timeframe.upper()

    print(f"mode Telegram : {container.telegram.mode} "
          f"(configure={container.telegram.configured})")
    print(f"paires scannees : {app_settings.symbol_list}")
    print("scan du tick reel...")

    await scanner.tick()
    # la capture est faite par le worker asynchrone : on attend que la file se
    # vide (le scanner, lui, n'attend jamais - c'est la garantie de performance).
    deadline = asyncio.get_running_loop().time() + 30
    while container.capture.queue_size and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.2)
    if test_alert:
        # verifie la livraison sans dependre du marche : c'est une alerte de test
        # explicitement etiquetee TELEGRAM_TEST (op_test EURUSD M15), jamais une
        # opportunite inventee.
        queued = container.telegram.enqueue_test_alert()
        print(f"alerte de test (TELEGRAM_TEST) mise en file : {queued}")
    await container.telegram.dispatch_once()
    deadline = asyncio.get_running_loop().time() + 15
    while container.telegram.status()["queue"].get("queued", 0) and asyncio.get_running_loop().time() < deadline:
        await container.telegram.dispatch_once()
        await asyncio.sleep(0.2)

    groups = container.confluence.tracked()
    opportunities = container.opportunities.tracked()
    captures = container.capture.history(limit=10)
    alerts = container.telegram.history(limit=10)

    print(f"\nconfluences observees : {len(groups)}")
    for group in groups[:5]:
        print(f"  {group.id} {group.symbol} {group.timeframe} {value(group.direction)} "
              f"{value(group.state)} {group.score}/{group.max_score}")
    print(f"opportunites observees : {len(opportunities)}")
    for opportunity in opportunities[:5]:
        print(f"  {opportunity.id} {opportunity.symbol} {opportunity.timeframe} "
              f"{value(opportunity.direction)} {value(opportunity.state)} "
              f"{opportunity.score}/{opportunity.max_score}"
              + (f" - {opportunity.no_trade_reason}" if opportunity.no_trade_reason else ""))
    print(f"captures PNG reelles : {len(captures)}")
    for capture in captures[:5]:
        goal = capture.get("opportunity_id") or "-"
        print(f"  {capture['id']} {capture['symbol']} {capture['timeframe']} "
              f"{capture['width']}x{capture['height']} {capture['size_bytes']} o "
              f"-> {goal}")

    print(f"\nalertes outbox : {len(alerts)}")
    for alert in alerts[:5]:
        print(f"  {alert['id']} {alert['symbol']} {alert['timeframe']} {alert['status']} "
              f"(mode {alert['mode']}, tentatives {alert['attempts']}/{alert['max_attempts']}, "
              f"capture {alert['capture_id'] or '-'})")

    # meme identite d'evenement de bout en bout : l'opportunite porte la cle
    # d'alerte, l'alerte porte l'opportunite, la capture porte l'opportunite.
    print("\nidentite bout en bout :")
    for opportunity in opportunities[:3]:
        key = opportunity.alert_key or "-"
        linked = [a for a in alerts if a["opportunity_id"] == opportunity.id]
        print(f"  {opportunity.id} | {key} | alertes={[a['id'] for a in linked]}")

    named = [o for o in opportunities if value(o.direction) in ("BUY", "SELL")]
    if named:
        print("\nexemple de message reel (aucun ordre, observation seulement) :")
        print("-" * 68)
        print(build_message(named[0], container.telegram.params))
        print("-" * 68)
    else:
        print("\naucune direction BUY/SELL sur ce tick : NO_TRADE est un resultat "
              "valide (aucune opportunite n'est inventee pour remplir un quota).")

    leaked = [row for row in alerts if "DRY-RUN" in str(row) or "BOT_TOKEN" in str(row)]
    print(f"\ntoken present dans les enregistrements ? {bool(leaked)}")

    if keep:
        print("base conservee : voir DATABASE_URL")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Chaine complete P5-P8 sur donnees reelles")
    parser.add_argument("--symbol", help="limiter le tick a une paire (ex. EURUSD)")
    parser.add_argument("--timeframe", help="limiter le tick a un timeframe (ex. M15)")
    parser.add_argument("--keep", action="store_true", help="conserver la base temporaire")
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="ajouter une alerte de test (TELEGRAM_TEST) pour verifier la livraison",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        database_path = Path(tmp) / "live_chain.db"
        prepare_environment(database_path)
        if args.keep:
            print(f"base temporaire : {database_path}")
        else:
            # the directory is removed on exit: nothing is left behind
            pass
        return asyncio.run(run(args.symbol, args.timeframe, args.keep, args.test_alert))


if __name__ == "__main__":
    raise SystemExit(main())
