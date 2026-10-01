#!/usr/bin/env python3
"""Phase 2 acceptance check on a RUNNING instance (real provider, real bars).

    python3 scripts/verify_phase2_live.py http://localhost:8000

Everything is read from the live API / WebSocket: the script never fabricates a
detection. Its strongest check cross-references each detection's coordinates
with the real candles served for the same series, which is what makes a
"fictional detection" impossible to hide.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone

import httpx

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None

PASS, FAIL, WARN = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m", "\033[93mWARN\033[0m"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "", warn: bool = False) -> bool:
    status = "PASS" if condition and not warn else ("WARN" if condition else "FAIL")
    results.append((name, status, detail))
    print(f"  [{ {'PASS': PASS, 'WARN': WARN, 'FAIL': FAIL}[status] }] {name}{f' - {detail}' if detail else ''}")
    return bool(condition)


async def main(base_url: str) -> int:
    base = base_url.rstrip("/")
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    print(f"\nSMART MARKET VISION - verification Phase 2 (chartiste) sur {base}")
    print(f"heure UTC : {datetime.now(tz=timezone.utc).isoformat()}\n")

    async with httpx.AsyncClient(base_url=base, timeout=45.0) as client:
        print("1. Moteurs et parametres")
        status = (await client.get("/api/status")).json()
        engines = status["detection_engines"]
        check("CHART_PATTERN_ENGINE actif", engines["CHART_PATTERN_ENGINE"] == "ENABLED", str(engines["CHART_PATTERN_ENGINE"]))
        check(
            "price action / SMC-ICT non implementes",
            engines["PRICE_ACTION_ENGINE"] == "NOT_IMPLEMENTED" and engines["SMC_ICT_ENGINE"] == "NOT_IMPLEMENTED",
        )
        check("aucune execution d'ordre", status["safety"]["order_execution"] is False and status["safety"]["broker_connection"] is False)
        patterns_status = status.get("patterns", {})
        check("etat du moteur expose", "tracked" in patterns_status, f"{patterns_status.get('tracked')} formations suivies")

        params = (await client.get("/api/patterns/params")).json()
        groups = set(params["params"])
        expected = {
            "globals", "double_top_bottom", "head_shoulders", "triangle", "wedge",
            "rectangle", "flags", "levels", "channel", "breakout", "weights",
        }
        check("parametres centralises", expected <= groups, f"{len(groups)} groupes")
        check(
            "minimums anti sur-detection presents",
            params["params"]["globals"]["min_bars_required"] >= 20
            and params["params"]["triangle"]["min_touches_per_line"] >= 3
            and params["params"]["double_top_bottom"]["peak_tolerance_pips"] > 0,
        )

        print("\n2. Contrat des detections")
        payload = (await client.get("/api/detections")).json()
        detections = payload["detections"]
        check("endpoint /api/detections", payload["status"] in {"ACTIVE DETECTIONS", "NO ACTIVE DETECTION"},
              f"{len(detections)} detection(s)")
        if not detections:
            check("detections presentes pour verifier le contrat", False, "aucune detection: relancer apres un tour de scanner")
        required = {"id", "dedup_key", "symbol", "timeframe", "category", "pattern", "direction", "status",
                    "confidence", "evidence", "coordinates", "parameters", "confirmation", "invalidation"}
        shape_ok = all(required <= set(item) for item in detections)
        check("champs obligatoires du modele", shape_ok and bool(detections))
        check("categorie CHARTISTE uniquement", all(item["category"] == "CHARTISTE" for item in detections))
        check(
            "statuts valides",
            all(item["status"] in {"DETECTED", "CONFIRMED", "INVALIDATED", "EXPIRED"} for item in detections),
        )
        check("sens valides", all(item["direction"] in {"BULLISH", "BEARISH", "NEUTRAL"} for item in detections))
        check(
            "confiance = criteres valides (jamais arbitraire)",
            all(
                abs(item["confidence"] - 100 * sum(f["weight"] for f in item["confidence_factors"] if f["passed"])
                    / max(1e-9, sum(f["weight"] for f in item["confidence_factors"]))) < 0.6
                for item in detections
            ),
        )
        check("expliquabilite: evidence + points", all(item["evidence"] and item["evidence_points"] for item in detections))
        check("coordonnees tracables", all(item["coordinates"] for item in detections))
        check("aucune donnee inventee: volume jamais fabrique",
              all((item["confirmation"] or {}).get("volume") is None for item in detections))
        keys = [item["dedup_key"] for item in detections]
        check("dedup: une cle par formation", len(keys) == len(set(keys)), f"{len(keys)} cles")

        print("\n3. Filtres et historique")
        first = detections[0] if detections else None
        if first:
            scoped = (await client.get(f"/api/detections?symbol={first['symbol']}&timeframe={first['timeframe']}")).json()
            check("filtre pair + UT", all(i["symbol"] == first["symbol"] and i["timeframe"] == first["timeframe"] for i in scoped["detections"]))
            detail = await client.get(f"/api/detections/{first['id']}")
            check("lecture par identifiant", detail.status_code == 200 and detail.json()["id"] == first["id"])
        active = (await client.get("/api/detections/active")).json()
        check("liste des motifs actifs", all(item["status"] == "DETECTED" for item in active["detections"]),
              f"{len(active['detections'])} actif(s)")
        history = (await client.get("/api/detections/history?limit=100")).json()
        check("historique persiste", history["count"] >= len(detections), f"{history['count']} ligne(s)")
        if history["detections"]:
            row = history["detections"][0]
            check(
                "une ligne contient tout le cycle de vie",
                bool(row["dedup_key"]) and row["parameters"] is not None and row["first_seen_at"],
                f"{row['pattern']} {row['status']}",
            )
        check("filtre inconnu sans resultat", (await client.get("/api/detections/history?pattern=__NOPE__")).json()["count"] == 0)

        print("\n4. Donnees reelles: les coordonnees existent-elles vraiment ?")
        checked = 0
        mismatches: list[str] = []
        for item in detections[:6]:
            candles = await client.get(f"/api/candles/{item['symbol']}/{item['timeframe']}?limit=400")
            if candles.status_code != 200:
                mismatches.append(f"{item['symbol']} {item['timeframe']}: candles indisponibles")
                continue
            bars = {bar["time"]: bar for bar in candles.json()["candles"]}
            for coordinate in item["coordinates"]:
                bar = bars.get(coordinate["time"])
                if bar is None:
                    mismatches.append(f"{item['pattern']} {item['symbol']}: bougie {coordinate['time']} absente")
                    continue
                # a drawn point must sit inside the real high/low of its bar
                if not (bar["low"] - 1e-9 <= coordinate["price"] <= bar["high"] + 1e-9):
                    mismatches.append(
                        f"{item['pattern']} {item['symbol']} {coordinate['role']}: "
                        f"{coordinate['price']} hors [{bar['low']}, {bar['high']}]"
                    )
                checked += 1
            analysed = len(candles.json()["candles"])
            if item["bars_in_window"] <= 0 or item["bars_in_window"] > analysed:
                mismatches.append(f"{item['pattern']} {item['symbol']}: fenetre {item['bars_in_window']} > {analysed} bougies reelles")
        check(
            "chaque point trace tombe dans une bougie reelle",
            not mismatches,
            f"{checked} points verifies" + (f" | {mismatches[:2]}" if mismatches else ""),
        )

        print("\n5. Temps reel (WebSocket)")
        if websockets is None:
            check("websockets installe", False, "pip install websockets")
        else:
            url = f"{ws_base}/api/stream?symbol={first['symbol'] if first else 'EURUSD'}&timeframe={first['timeframe'] if first else 'M15'}"
            try:
                async with websockets.connect(url, open_timeout=15) as socket:
                    hello = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
                    check("hello du flux", hello["event_type"] == "STREAM_HELLO")
                    events: list[str] = []
                    try:
                        for _ in range(6):
                            message = json.loads(await asyncio.wait_for(socket.recv(), timeout=25))
                            events.append(message["event_type"])
                            if message["event_type"] in {"PATTERN_DETECTED", "PATTERN_CONFIRMED", "PATTERN_INVALIDATED",
                                                          "PATTERN_EXPIRED", "BREAKOUT_DETECTED", "RETEST_DETECTED"}:
                                detection = message["metadata"].get("detection") or {}
                                check(
                                    "evenement chartiste pousse avec sa charge utile",
                                    bool(detection.get("id")) and detection.get("evidence") is not None,
                                    f"{message['event_type']} {detection.get('pattern')}",
                                )
                                break
                    except asyncio.TimeoutError:
                        pass
                    check("etat pousse a la connexion", bool(events), f"recus: {events}")
            except Exception as exc:  # noqa: BLE001
                check("connexion WebSocket", False, f"{type(exc).__name__}: {exc}")

        print("\n6. Limites assumees")
        check("moteurs interdits toujours absents", engines["SMC_ICT_ENGINE"] == "NOT_IMPLEMENTED")
        check(
            "aucun ordre / broker / position",
            status["safety"]["order_execution"] is False
            and status["safety"]["broker_connection"] is False
            and status["safety"]["position_management"] is False,
        )

    passed = sum(1 for _, state, _ in results if state == "PASS")
    warned = sum(1 for _, state, _ in results if state == "WARN")
    failed = sum(1 for _, state, _ in results if state == "FAIL")
    print(f"\n{passed} PASS / {warned} WARN / {failed} FAIL")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    sys.exit(asyncio.run(main(target)))
