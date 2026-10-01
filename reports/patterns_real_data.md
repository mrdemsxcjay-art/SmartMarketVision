# Chartist engine - run on real Forex data

* generated (UTC): 2026-09-30T00:22:33.050936+00:00
* provider: `yahoo`
* pairs: AUDUSD, EURGBP, EURJPY, EURUSD, GBPJPY, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY
* timeframes: D1, H1, H4, M15
* closed bars requested per series: 300

> This report lists what the engine computed from real OHLC. It is **not** a
> claim that every detection is a valid trading pattern: each one is only the
> result of the criteria listed with it, and must be reviewed by a human.

## 1. Volume analysed

| series analysed | closed bars analysed | detections | errors |
|---|---|---|---|
| 40/40 | 11960 | 219 | 0 |

## 2. Detections by pattern

| pattern | count | DETECTED | CONFIRMED | INVALIDATED | EXPIRED |
|---|---|---|---|---|---|
| RESISTANCE | 61 | 61 | 0 | 0 | 0 |
| DOUBLE_BOTTOM | 50 | 6 | 22 | 22 | 0 |
| SUPPORT | 41 | 41 | 0 | 0 | 0 |
| DOUBLE_TOP | 37 | 5 | 23 | 9 | 0 |
| HEAD_SHOULDERS | 9 | 1 | 7 | 1 | 0 |
| RECTANGLE | 8 | 7 | 1 | 0 | 0 |
| INVERSE_HEAD_SHOULDERS | 7 | 3 | 3 | 1 | 0 |
| CHANNEL | 2 | 0 | 2 | 0 | 0 |
| FALLING_WEDGE | 2 | 1 | 1 | 0 | 0 |
| SYMMETRICAL_TRIANGLE | 1 | 1 | 0 | 0 | 0 |
| RISING_WEDGE | 1 | 0 | 1 | 0 | 0 |

## 3. Detections by pair and timeframe

| pair | detections | timeframes |
|---|---|---|
| EURGBP | 29 | D1, H1, H4, M15 |
| USDCHF | 26 | D1, H1, H4, M15 |
| NZDUSD | 23 | D1, H1, H4, M15 |
| USDJPY | 22 | D1, H1, H4, M15 |
| EURJPY | 22 | D1, H1, H4, M15 |
| GBPJPY | 22 | D1, H1, H4, M15 |
| GBPUSD | 21 | D1, H1, H4, M15 |
| EURUSD | 18 | D1, H1, H4, M15 |
| AUDUSD | 18 | D1, H1, H4, M15 |
| USDCAD | 18 | D1, H1, H4, M15 |

| timeframe | detections |
|---|---|
| H1 | 62 |
| M15 | 57 |
| H4 | 54 |
| D1 | 46 |

## 4. Series detail

| pair | TF | closed bars | analysed | pivots | candidates | detections | ms |
|---|---|---|---|---|---|---|---|
| EURUSD | M15 | 299 | 299 | 32 | 3 | 3 | 122.8 |
| EURUSD | H1 | 299 | 299 | 40 | 8 | 6 | 46.6 |
| EURUSD | H4 | 299 | 299 | 40 | 4 | 4 | 42.3 |
| EURUSD | D1 | 299 | 299 | 40 | 5 | 5 | 45.8 |
| GBPUSD | M15 | 299 | 299 | 40 | 9 | 7 | 39.7 |
| GBPUSD | H1 | 299 | 299 | 40 | 7 | 6 | 39.5 |
| GBPUSD | H4 | 299 | 299 | 40 | 6 | 5 | 42.3 |
| GBPUSD | D1 | 299 | 299 | 40 | 3 | 3 | 44.3 |
| USDJPY | M15 | 299 | 299 | 40 | 6 | 5 | 42.0 |
| USDJPY | H1 | 299 | 299 | 40 | 8 | 7 | 47.1 |
| USDJPY | H4 | 299 | 299 | 40 | 7 | 6 | 42.2 |
| USDJPY | D1 | 299 | 299 | 40 | 4 | 4 | 43.1 |
| USDCHF | M15 | 299 | 299 | 40 | 7 | 7 | 41.2 |
| USDCHF | H1 | 299 | 299 | 40 | 8 | 6 | 48.2 |
| USDCHF | H4 | 299 | 299 | 40 | 6 | 6 | 48.2 |
| USDCHF | D1 | 299 | 299 | 40 | 8 | 7 | 45.6 |
| AUDUSD | M15 | 299 | 299 | 39 | 4 | 4 | 39.4 |
| AUDUSD | H1 | 299 | 299 | 40 | 6 | 5 | 38.5 |
| AUDUSD | H4 | 299 | 299 | 40 | 9 | 6 | 43.6 |
| AUDUSD | D1 | 299 | 299 | 40 | 3 | 3 | 47.2 |
| USDCAD | M15 | 299 | 299 | 34 | 6 | 6 | 43.4 |
| USDCAD | H1 | 299 | 299 | 40 | 13 | 7 | 46.0 |
| USDCAD | H4 | 299 | 299 | 40 | 2 | 2 | 42.5 |
| USDCAD | D1 | 299 | 299 | 40 | 3 | 3 | 45.6 |
| NZDUSD | M15 | 299 | 299 | 40 | 7 | 7 | 41.4 |
| NZDUSD | H1 | 299 | 299 | 40 | 10 | 7 | 40.7 |
| NZDUSD | H4 | 299 | 299 | 40 | 4 | 4 | 45.6 |
| NZDUSD | D1 | 299 | 299 | 40 | 5 | 5 | 49.5 |
| EURGBP | M15 | 299 | 299 | 40 | 6 | 6 | 40.2 |
| EURGBP | H1 | 299 | 299 | 40 | 11 | 8 | 57.6 |
| EURGBP | H4 | 299 | 299 | 40 | 8 | 8 | 45.1 |
| EURGBP | D1 | 299 | 299 | 40 | 10 | 7 | 46.4 |
| EURJPY | M15 | 299 | 299 | 40 | 7 | 6 | 42.6 |
| EURJPY | H1 | 299 | 299 | 40 | 4 | 4 | 45.0 |
| EURJPY | H4 | 299 | 299 | 40 | 7 | 6 | 53.0 |
| EURJPY | D1 | 299 | 299 | 40 | 6 | 6 | 50.4 |
| GBPJPY | M15 | 299 | 299 | 40 | 6 | 6 | 45.2 |
| GBPJPY | H1 | 299 | 299 | 40 | 7 | 6 | 40.2 |
| GBPJPY | H4 | 299 | 299 | 40 | 9 | 7 | 45.2 |
| GBPJPY | D1 | 299 | 299 | 40 | 3 | 3 | 43.7 |

## 5. Examples with their evidence (human review required)

### EURUSD M15 - SYMMETRICAL_TRIANGLE (DETECTED)

* direction: NEUTRAL, confidence: 100.0%
* last analysed bar (UTC): 2026-09-29 23:15:00+00:00
* criteria:
  * [x] Nombre de touches suffisant - 3+3 touches
  * [x] Chaque ligne touchee au moins deux fois - haute 3, basse 3
  * [x] Convergence des lignes - pentes -0.000034 / 0.000036
  * [x] Contraction de la figure - largeur reduite de 84.5% (minimum 30%)
  * [x] Qualite d'ajustement des lignes - R2 1.00 / 0.94
  * [x] Contraction mesurable - 84.5% de contraction
* why (evidence):
  * Ligne haute : 1.13610 -> 1.13470 (3 touches, pente -0.34 pip/bougie, DESCENDING)
  * Ligne basse : 1.13270 -> 1.13417 (3 touches, pente 0.36 pip/bougie, ASCENDING)
  * Touches totales : 6 (minimum 5)
  * Largeur : 34.0 pips -> 5.3 pips (contraction 84.5%)
  * Apex (convergence des lignes) : bougie 302 (dans 8 bougies)
  * Niveau de breakout surveille : 1.13470 (BOTH)
  * Statut : triangle en cours, pas de breakout observe
  * Confiance : 100.0%

### EURUSD M15 - RESISTANCE (DETECTED)

* direction: BEARISH, confidence: 100.0%
* last analysed bar (UTC): 2026-09-29 21:45:00+00:00
* criteria:
  * [x] Touches multiples - 2 touches
  * [x] Reaction reelle - 1.82 ATR (minimum 0.5)
  * [x] Touches regroupees - 0.0 pips
  * [x] Niveau encore d'actualite - 6 bougies depuis la derniere touche (max 60)
  * [x] Niveau non depasse durablement - 0 cloture(s) au-dela du niveau (max 1)
  * [x] Solidite suffisante - 69.2/100
* why (evidence):
  * Resistance a 1.13482
  * Nombre de touches : 2 (1.13482, 1.13482)
  * Premiere touche : 2026-09-29T21:00:00+00:00
  * Derniere touche : 2026-09-29T21:45:00+00:00 (il y a 6 bougies)
  * Dispersion des touches : 0.0 pips (tolerance 6.0)
  * Reaction moyenne apres touche : 7.7 pips (1.82 ATR)
  * Solidite : 69.2/100
  * Confiance : 100.0%

### EURUSD M15 - SUPPORT (DETECTED)

* direction: BULLISH, confidence: 83.3%
* last analysed bar (UTC): 2026-09-29 23:00:00+00:00
* criteria:
  * [x] Touches multiples - 3 touches
  * [x] Reaction reelle - 1.52 ATR (minimum 0.5)
  * [ ] Touches regroupees - 6.4 pips
  * [x] Niveau encore d'actualite - 4 bougies depuis la derniere touche (max 60)
  * [x] Niveau non depasse durablement - 0 cloture(s) au-dela du niveau (max 1)
  * [x] Solidite suffisante - 70.9/100
* why (evidence):
  * Support a 1.13430
  * Nombre de touches : 3 (1.13469, 1.13417, 1.13404)
  * Premiere touche : 2026-09-29T07:30:00+00:00
  * Derniere touche : 2026-09-29T23:00:00+00:00 (il y a 4 bougies)
  * Dispersion des touches : 6.4 pips (tolerance 6.0)
  * Reaction moyenne apres touche : 6.4 pips (1.52 ATR)
  * Solidite : 70.9/100
  * Confiance : 83.3%

### EURUSD H1 - DOUBLE_TOP (CONFIRMED)

* direction: BEARISH, confidence: 75.0%
* last analysed bar (UTC): 2026-09-25 18:00:00+00:00
* criteria:
  * [x] Proximite des deux extremes - ecart 1.30 pip vs tolerance 5.00 pip
  * [x] Profondeur suffisante - 22.1 pips vs minimum 9.2 pips
  * [x] Reaction proportionnee a la jambe precedente - creux 22.1 pips vs 20% de 37.6 pips
  * [ ] Symetrie des deux moities - rapport 4.00
  * [ ] Duree de formation dans la bande ideale - 5 bougies
  * [x] Aucun depassement intermediaire - 0 pivot(s) extreme(s) entre les deux
  * [x] Neckline exploitable - neckline 1.13895
  * [x] Breakout confirme - cassure de NECKLINE a 1.1381744146347046
* why (evidence):
  * Peak 1 : 1.14116 (barre 239, 2026-09-25T11:00:00+00:00)
  * Peak 2 : 1.14129 (barre 244, 2026-09-25T16:00:00+00:00)
  * Ecart entre les deux : 1.30 pip (tolerance 5.00 pip)
  * Creux intermediaire : 1.13895 (barre 243)
  * Profondeur : 22.1 pips (minimum 9.2 pips)
  * Separation temporelle : 5 bougies (min 5, max 120)
  * Neckline : 1.13895
  * Symetrie des deux moities : rapport 4.00 (max 3.0)

### EURUSD H1 - DOUBLE_TOP (CONFIRMED)

* direction: BEARISH, confidence: 62.5%
* last analysed bar (UTC): 2026-09-28 10:00:00+00:00
* criteria:
  * [ ] Proximite des deux extremes - ecart 2.60 pip vs tolerance 5.00 pip
  * [x] Profondeur suffisante - 16.8 pips vs minimum 9.2 pips
  * [x] Reaction proportionnee a la jambe precedente - creux 16.8 pips vs 20% de 18.1 pips
  * [ ] Symetrie des deux moities - rapport 4.00
  * [ ] Duree de formation dans la bande ideale - 5 bougies
  * [x] Aucun depassement intermediaire - 0 pivot(s) extreme(s) entre les deux
  * [x] Neckline exploitable - neckline 1.13753
  * [x] Breakout confirme - cassure de NECKLINE a 1.1373976469039917
* why (evidence):
  * Peak 1 : 1.13947 (barre 254, 2026-09-28T03:00:00+00:00)
  * Peak 2 : 1.13921 (barre 259, 2026-09-28T08:00:00+00:00)
  * Ecart entre les deux : 2.60 pip (tolerance 5.00 pip)
  * Creux intermediaire : 1.13753 (barre 258)
  * Profondeur : 16.8 pips (minimum 9.2 pips)
  * Separation temporelle : 5 bougies (min 5, max 120)
  * Neckline : 1.13753
  * Symetrie des deux moities : rapport 4.00 (max 3.0)

### EURUSD H1 - DOUBLE_BOTTOM (INVALIDATED)

* direction: BULLISH, confidence: 85.7%
* last analysed bar (UTC): 2026-09-28 09:00:00+00:00
* criteria:
  * [x] Proximite des deux extremes - ecart 1.29 pip vs tolerance 5.00 pip
  * [x] Profondeur suffisante - 18.1 pips vs minimum 9.2 pips
  * [x] Reaction proportionnee a la jambe precedente - creux 18.1 pips vs 20% de 36.4 pips
  * [x] Symetrie des deux moities - rapport 1.00
  * [ ] Duree de formation dans la bande ideale - 8 bougies
  * [x] Aucun depassement intermediaire - 0 pivot(s) extreme(s) entre les deux
  * [x] Neckline exploitable - neckline 1.13947
* why (evidence):
  * Trough 1 : 1.13766 (barre 250, 2026-09-27T23:00:00+00:00)
  * Trough 2 : 1.13753 (barre 258, 2026-09-28T07:00:00+00:00)
  * Ecart entre les deux : 1.29 pip (tolerance 5.00 pip)
  * Sommet intermediaire : 1.13947 (barre 254)
  * Profondeur : 18.1 pips (minimum 9.2 pips)
  * Separation temporelle : 8 bougies (min 5, max 120)
  * Neckline : 1.13947
  * Symetrie des deux moities : rapport 1.00 (max 3.0)

## 6. Errors and warnings

* none
* EURUSD M15 (provider warning): 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
* EURUSD M15 (provider warning): 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURUSD M15 (provider warning): 9 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* EURUSD H1 (provider warning): 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
* EURUSD H1 (provider warning): 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURUSD H1 (provider warning): 3 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* EURUSD H4 (provider warning): 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
* EURUSD H4 (provider warning): 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURUSD D1 (provider warning): 1 running bar(s) re-stamped on their D1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURUSD D1 (provider warning): 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* GBPUSD M15 (provider warning): 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
* GBPUSD M15 (provider warning): 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* GBPUSD M15 (provider warning): 9 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* GBPUSD H1 (provider warning): 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
* GBPUSD H1 (provider warning): 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* GBPUSD H1 (provider warning): 3 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* GBPUSD H4 (provider warning): 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
* GBPUSD H4 (provider warning): 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* GBPUSD D1 (provider warning): 1 running bar(s) re-stamped on their D1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* GBPUSD D1 (provider warning): 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* USDJPY M15 (provider warning): 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
* USDJPY M15 (provider warning): 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDJPY M15 (provider warning): 10 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* USDJPY H1 (provider warning): 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
* USDJPY H1 (provider warning): 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDJPY H1 (provider warning): 4 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* USDJPY H4 (provider warning): 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
* USDJPY H4 (provider warning): 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDJPY D1 (provider warning): 1 running bar(s) re-stamped on their D1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDJPY D1 (provider warning): 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* USDCHF M15 (provider warning): 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
* USDCHF M15 (provider warning): 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDCHF M15 (provider warning): 11 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* USDCHF H1 (provider warning): 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
* USDCHF H1 (provider warning): 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDCHF H1 (provider warning): 5 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* USDCHF H4 (provider warning): 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
* USDCHF H4 (provider warning): 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDCHF D1 (provider warning): 1 running bar(s) re-stamped on their D1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDCHF D1 (provider warning): 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* AUDUSD M15 (provider warning): 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
* AUDUSD M15 (provider warning): 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* AUDUSD M15 (provider warning): 8 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* AUDUSD H1 (provider warning): 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
* AUDUSD H1 (provider warning): 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* AUDUSD H1 (provider warning): 3 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* AUDUSD H4 (provider warning): 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
* AUDUSD H4 (provider warning): 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* AUDUSD D1 (provider warning): 1 running bar(s) re-stamped on their D1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* AUDUSD D1 (provider warning): 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* USDCAD M15 (provider warning): 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
* USDCAD M15 (provider warning): 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDCAD M15 (provider warning): 10 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* USDCAD H1 (provider warning): 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
* USDCAD H1 (provider warning): 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDCAD H1 (provider warning): 3 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* USDCAD H4 (provider warning): 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
* USDCAD H4 (provider warning): 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDCAD D1 (provider warning): 1 running bar(s) re-stamped on their D1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* USDCAD D1 (provider warning): 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* NZDUSD M15 (provider warning): 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
* NZDUSD M15 (provider warning): 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* NZDUSD M15 (provider warning): 8 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* NZDUSD H1 (provider warning): 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
* NZDUSD H1 (provider warning): 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* NZDUSD H1 (provider warning): 3 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* NZDUSD H4 (provider warning): 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
* NZDUSD H4 (provider warning): 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* NZDUSD D1 (provider warning): 1 running bar(s) re-stamped on their D1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* NZDUSD D1 (provider warning): 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* EURGBP M15 (provider warning): 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
* EURGBP M15 (provider warning): 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURGBP M15 (provider warning): 9 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* EURGBP H1 (provider warning): 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
* EURGBP H1 (provider warning): 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURGBP H1 (provider warning): 3 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* EURGBP H4 (provider warning): 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
* EURGBP H4 (provider warning): 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURGBP D1 (provider warning): 1 running bar(s) re-stamped on their D1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURGBP D1 (provider warning): 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* EURJPY M15 (provider warning): 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
* EURJPY M15 (provider warning): 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURJPY M15 (provider warning): 9 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* EURJPY H1 (provider warning): 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
* EURJPY H1 (provider warning): 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURJPY H1 (provider warning): 3 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* EURJPY H4 (provider warning): 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
* EURJPY H4 (provider warning): 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURJPY D1 (provider warning): 1 running bar(s) re-stamped on their D1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* EURJPY D1 (provider warning): 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* GBPJPY M15 (provider warning): 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
* GBPJPY M15 (provider warning): 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* GBPJPY M15 (provider warning): 9 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* GBPJPY H1 (provider warning): 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
* GBPJPY H1 (provider warning): 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* GBPJPY H1 (provider warning): 3 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
* GBPJPY H4 (provider warning): 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
* GBPJPY H4 (provider warning): 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* GBPJPY D1 (provider warning): 1 running bar(s) re-stamped on their D1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
* GBPJPY D1 (provider warning): 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)

## 7. Timing (one series, single pass)

* min 38.5 ms / median 44.65 ms / max 122.8 ms over 40 series

## 8. Thresholds in force for this run

```json
{
  "breakout": {
    "buffer_pips": 1.0,
    "max_bars_after_formation": 80,
    "require_close": true,
    "retest_max_bars": 30,
    "retest_min_distance_pips": 0.0,
    "retest_tolerance_pips": 3.0
  },
  "channel": {
    "confirmation_buffer_pips": 1.0,
    "flat_slope_atr_per_bar": 0.02,
    "max_width_drift": 0.5,
    "min_total_touches": 6,
    "min_touches_per_line": 3,
    "min_width_atr": 0.8,
    "parallel_tolerance": 0.35,
    "touch_tolerance_atr": 0.6,
    "touch_tolerance_pips": 6.0
  },
  "dedup_cooldown_bars": 5,
  "double_top_bottom": {
    "confirmation_buffer_pips": 1.0,
    "forbid_intervening_extreme": true,
    "invalidation_buffer_pips": 2.0,
    "max_bars_since_formation": 60,
    "max_bars_to_confirm": 60,
    "max_peak_separation_bars": 120,
    "min_peak_separation_bars": 5,
    "min_valley_depth_atr": 1.0,
    "min_valley_depth_pips": 8.0,
    "min_valley_depth_ratio": 0.2,
    "peak_tolerance_atr": 0.5,
    "peak_tolerance_pips": 5.0,
    "prior_lookback_bars": 60,
    "symmetry_max_ratio": 3.0
  },
  "enabled": true,
  "flags": {
    "confirmation_buffer_pips": 1.0,
    "consolidation_max_bars": 60,
    "consolidation_min_bars": 5,
    "impulse_max_bars": 30,
    "impulse_min_atr": 2.0,
    "impulse_min_pips": 25.0,
    "max_bars_to_confirm": 40,
    "max_box_drift_ratio": 0.5,
    "max_retrace_ratio": 0.6,
    "max_width_atr": 2.0,
    "max_width_pole_ratio": 0.5,
    "min_contraction": 0.2,
    "parallel_tolerance": 0.35
  },
  "globals": {
    "atr_period": 14,
    "atr_slow_period": 100,
    "max_pivots": 40,
    "min_bars_required": 60,
    "pip_fallback": 0.0001,
    "pivot_left": 2,
    "pivot_right": 2,
    "window_bars": 300
  },
  "head_shoulders": {
    "confirmation_buffer_pips": 1.0,
    "head_min_prominence_atr": 0.6,
    "head_min_prominence_pips": 6.0,
    "invalidation_buffer_pips": 2.0,
    "max_bars_since_formation": 80,
    "max_bars_to_confirm": 80,
    "max_total_bars": 160,
    "min_valley_depth_atr": 1.0,
    "min_valley_depth_pips": 8.0,
    "neckline_max_slope_atr_per_bar": 0.25,
    "require_trend_context": true,
    "shoulder_tolerance_atr": 0.8,
    "shoulder_tolerance_pips": 8.0,
    "trend_lookback_bars": 40,
    "trend_min_atr": 2.0,
    "trend_min_pips": 25.0
  },
  "levels": {
    "cluster_tolerance_atr": 0.5,
    "cluster_tolerance_pips": 6.0,
    "max_bars_since_touch": 60,
    "max_closes_beyond": 1,
    "max_levels": 6,
    "min_touches": 2,
    "reaction_min_atr": 0.5
  },
  "rectangle": {
    "confirmation_buffer_pips": 1.0,
    "horizontal_tolerance_atr": 0.6,
    "horizontal_tolerance_pips": 8.0,
    "max_bars": 200,
    "max_bars_to_confirm": 60,
    "min_bars": 12,
    "min_height_atr": 1.2,
    "min_height_pips": 12.0,
    "min_touches_per_side": 2
  },
  "run_on": "CLOSED_CANDLES_ONLY",
  "triangle": {
    "confirmation_buffer_pips": 1.0,
    "convergence_required": true,
    "flat_slope_atr_per_bar": 0.02,
    "max_bars_to_confirm": 60,
    "min_total_touches": 5,
    "min_touches_per_line": 3,
    "min_width_atr": 1.5,
    "min_width_contraction": 0.3,
    "min_width_pips": 25.0,
    "touch_tolerance_atr": 0.5,
    "touch_tolerance_pips": 5.0
  },
  "wedge": {
    "confirmation_buffer_pips": 1.0,
    "flat_slope_atr_per_bar": 0.02,
    "max_bars_to_confirm": 60,
    "min_total_touches": 6,
    "min_touches_per_line": 3,
    "min_width_atr": 1.5,
    "min_width_contraction": 0.25,
    "min_width_pips": 25.0,
    "touch_tolerance_atr": 0.5,
    "touch_tolerance_pips": 5.0
  },
  "weights": {
    "breakout": 1.0,
    "level_quality": 1.0,
    "no_conflict": 1.0,
    "structure_clear": 1.0,
    "symmetry": 1.0,
    "volume_or_time": 1.0
  }
}
```

## 9. What this run does NOT prove

* that the detections are profitable or even correct chartistically;
* that no pattern was missed (only that the criteria did not match);
* anything about price action / SMC-ICT: those engines are not implemented.
