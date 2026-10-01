# SMART MARKET VISION - moteur Price Action (Phase 3) sur donnees reelles

Genere : 2026-09-30T12:41:50.928913+00:00  
Paires : EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,NZDUSD,EURGBP,EURJPY,GBPJPY  
Timeframes : M5,M15,H1,H4  
Bougies demandees par serie : 300 (fenetre du moteur : 300)

## 1. Volumetrie

- series analysees : **40** / 40 demandees
- bougies cloturees analysees : **11960**
- candidats bruts : **280**
- detections retenues : **280**
- erreurs : **0**, avertissements : **98**
- duree par serie : min 37.5 ms / mediane 44.9 ms / max 113.8 ms

## 2. Repartition

| Pattern | Detections |
| --- | --- |
| INSIDE_BAR | 58 |
| DOJI | 38 |
| OUTSIDE_BAR | 37 |
| FAILED_BREAKOUT | 36 |
| BEARISH_ENGULFING | 30 |
| BULLISH_PIN_BAR | 24 |
| BULLISH_ENGULFING | 18 |
| BEARISH_PIN_BAR | 15 |
| HAMMER | 14 |
| REJECTION | 5 |
| SHOOTING_STAR | 4 |
| IMPULSION | 1 |

| Statut | Detections |
| --- | --- |
| DETECTED | 87 |
| CONFIRMED | 161 |
| INVALIDATED | 12 |
| EXPIRED | 20 |

| Paire | Detections | | Timeframe | Detections |
| --- | --- | --- | --- | --- |
| USDJPY | 35 | | H4 | 88 |
| USDCAD | 35 | | H1 | 77 |
| EURJPY | 31 | | M15 | 58 |
| GBPUSD | 30 | | M5 | 57 |
| USDCHF | 27 | |  |  |
| EURUSD | 25 | |  |  |
| AUDUSD | 25 | |  |  |
| EURGBP | 25 | |  |  |
| GBPJPY | 25 | |  |  |
| NZDUSD | 22 | |  |  |

## 3. Controle anti-fiction (bougies reelles)

- detections sur une bougie inexistante : **0**
- mesures incoherentes avec l'OHLC reel : **0**
- coordonnees hors de la bougie reelle : **0**
- confidence non egale aux criteres ponderes : **0**
- volumes inventes : **0** (volume `None` partout, jamais 0)

## 4. Controle negatif (§20) - serie synthetique sans structure

- bougies : 300
- detections : **5** (1.67% des bougies)
- repartition : {'BULLISH_ENGULFING': 2, 'INSIDE_BAR': 2, 'OUTSIDE_BAR': 1}
- structures inventees (impulsion / consolidation) : aucune
- rappel : ces detections sont de la geometrie reelle presente dans une marche aleatoire (marteaux, englobements...) ; aucun reglage n'a ete modifie pour obtenir zero.

## 5. Instance live

- phase : None
- price_action_engine : ENABLED
- smc_ict_engine : NOT_IMPLEMENTED
- order_execution : False
- live_detections : 81
- live_counts : {'DETECTED': 20, 'CONFIRMED': 52, 'INVALIDATED': 5, 'EXPIRED': 4}
- params_groups : ['confluence', 'doji', 'enabled', 'engulfing', 'globals', 'hammer', 'inside_bar', 'levels', 'outside_bar', 'pin_bar', 'run_on', 'structure', 'weights']

## 6. Erreurs et avertissements

- aucune erreur
- AVERTISSEMENT EURUSD M5 : 1 running bar(s) re-stamped on their M5 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURUSD M5 : 1 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT EURUSD M15 : 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURUSD M15 : 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURUSD M15 : 6 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT EURUSD H1 : 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURUSD H1 : 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURUSD H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT EURUSD H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURUSD H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT GBPUSD M5 : 1 running bar(s) re-stamped on their M5 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT GBPUSD M5 : 1 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT GBPUSD M15 : 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
- AVERTISSEMENT GBPUSD M15 : 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT GBPUSD M15 : 6 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT GBPUSD H1 : 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
- AVERTISSEMENT GBPUSD H1 : 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT GBPUSD H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT GBPUSD H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
- AVERTISSEMENT GBPUSD H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDJPY M5 : 1 partial bar(s) folded into the running M5 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDJPY M5 : 1 running bar(s) re-stamped on their M5 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDJPY M15 : 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDJPY M15 : 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDJPY M15 : 7 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT USDJPY H1 : 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDJPY H1 : 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDJPY H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT USDJPY H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDJPY H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDCHF M5 : 1 partial bar(s) folded into the running M5 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDCHF M5 : 1 running bar(s) re-stamped on their M5 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDCHF M15 : 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDCHF M15 : 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDCHF M15 : 8 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT USDCHF H1 : 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDCHF H1 : 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDCHF H1 : 5 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT USDCHF H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDCHF H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT AUDUSD M5 : 1 bar(s) snapped onto the M5 grid (source offset <= 5s, prices unchanged)
- AVERTISSEMENT AUDUSD M15 : 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
- AVERTISSEMENT AUDUSD M15 : 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT AUDUSD M15 : 5 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT AUDUSD H1 : 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
- AVERTISSEMENT AUDUSD H1 : 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT AUDUSD H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT AUDUSD H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
- AVERTISSEMENT AUDUSD H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDCAD M5 : 1 partial bar(s) folded into the running M5 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDCAD M5 : 1 running bar(s) re-stamped on their M5 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDCAD M15 : 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDCAD M15 : 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDCAD M15 : 7 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT USDCAD H1 : 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDCAD H1 : 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT USDCAD H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT USDCAD H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
- AVERTISSEMENT USDCAD H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT NZDUSD M5 : 1 bar(s) snapped onto the M5 grid (source offset <= 5s, prices unchanged)
- AVERTISSEMENT NZDUSD M15 : 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
- AVERTISSEMENT NZDUSD M15 : 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT NZDUSD M15 : 5 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT NZDUSD H1 : 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
- AVERTISSEMENT NZDUSD H1 : 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT NZDUSD H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT NZDUSD H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
- AVERTISSEMENT NZDUSD H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURGBP M5 : 1 partial bar(s) folded into the running M5 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURGBP M5 : 1 running bar(s) re-stamped on their M5 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURGBP M15 : 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURGBP M15 : 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURGBP M15 : 6 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT EURGBP H1 : 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURGBP H1 : 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURGBP H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT EURGBP H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURGBP H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURJPY M5 : 1 partial bar(s) folded into the running M5 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURJPY M5 : 1 running bar(s) re-stamped on their M5 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURJPY M15 : 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURJPY M15 : 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURJPY M15 : 6 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT EURJPY H1 : 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURJPY H1 : 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT EURJPY H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT EURJPY H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
- AVERTISSEMENT EURJPY H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT GBPJPY M5 : 1 partial bar(s) folded into the running M5 bar (newest close kept, high/low extended)
- AVERTISSEMENT GBPJPY M5 : 1 running bar(s) re-stamped on their M5 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT GBPJPY M15 : 1 partial bar(s) folded into the running M15 bar (newest close kept, high/low extended)
- AVERTISSEMENT GBPJPY M15 : 1 running bar(s) re-stamped on their M15 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT GBPJPY M15 : 6 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT GBPJPY H1 : 1 partial bar(s) folded into the running H1 bar (newest close kept, high/low extended)
- AVERTISSEMENT GBPJPY H1 : 1 running bar(s) re-stamped on their H1 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
- AVERTISSEMENT GBPJPY H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
- AVERTISSEMENT GBPJPY H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
- AVERTISSEMENT GBPJPY H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)

## 7. Exemples detailles (a verifier a la main)

### EURUSD M5 - BULLISH_ENGULFING (CONFIRMED, confiance 88.9)
Contexte : `BULLISH_ENGULFING_AT_BREAKOUT`
- Bougie 295 : O 1.1361054182052612 H 1.1361054182052612 L 1.1358473300933838 C 1.1358473300933838
- Bougie 296 : O 1.1358473300933838 H 1.1364928483963013 L 1.1358473300933838 C 1.1363636255264282
- Englobement du corps reel : 100% du corps precedent couvert
- Taille des corps : 5.2 pips contre 2.6 pips (x2.00)
- Niveau de confirmation : cloture au-dessus de 1.13649
- CONFIRMATION : cloture 1.1381744146347046 au-dessus de PATTERN_HIGH 1.1364928484
- niveau `TRIGGER` = 1.1364928483963013
- niveau `INVALIDATION` = 1.1358473300933838
- niveau `PATTERN_HIGH` = 1.1364928483963013
- niveau `PATTERN_LOW` = 1.1358473300933838

### EURUSD M5 - BULLISH_ENGULFING (CONFIRMED, confiance 88.9)
Contexte : `BULLISH_ENGULFING_AT_RECTANGLE_EDGE`
- Bougie 290 : O 1.1354604959487915 H 1.1354604959487915 L 1.1352026462554932 C 1.1353315114974976
- Bougie 291 : O 1.1353315114974976 H 1.135589361190796 L 1.1353315114974976 C 1.135589361190796
- Englobement du corps reel : 100% du corps precedent couvert
- Taille des corps : 2.6 pips contre 1.3 pips (x2.00)
- Niveau de confirmation : cloture au-dessus de 1.13559
- CONFIRMATION : cloture 1.1359764337539673 au-dessus de PATTERN_HIGH 1.1355893612
- niveau `TRIGGER` = 1.135589361190796
- niveau `INVALIDATION` = 1.1353315114974976
- niveau `PATTERN_HIGH` = 1.135589361190796
- niveau `PATTERN_LOW` = 1.1353315114974976

### EURUSD M5 - BEARISH_ENGULFING (INVALIDATED, confiance 75.0)
Contexte : `BEARISH_ENGULFING_AT_CHARTIST_BOUNDARY`
- Bougie 294 : O 1.1358473300933838 H 1.1361054182052612 L 1.1357183456420898 C 1.1361054182052612
- Bougie 295 : O 1.1361054182052612 H 1.1361054182052612 L 1.1358473300933838 C 1.1358473300933838
- Englobement du corps reel : 100% du corps precedent couvert
- Taille des corps : 2.6 pips contre 2.6 pips (x1.00)
- Niveau de confirmation : cloture en dessous de 1.13585
- INVALIDATION : cloture 1.1363636255264282 au-dela de 1.1361054182052612 a la bougie 295
- niveau `TRIGGER` = 1.1358473300933838
- niveau `INVALIDATION` = 1.1361054182052612
- niveau `PATTERN_HIGH` = 1.1361054182052612
- niveau `PATTERN_LOW` = 1.1358473300933838

### EURUSD M5 - INSIDE_BAR (DETECTED, confiance 100.0)
Contexte : `INSIDE_BAR_AT_CHARTIST_BOUNDARY`
- Bougie mere 297 : range 16.8 pips (1.1364928483963013 - 1.1381744146347046)
- Bougie interne 298 : range 9.1 pips (1.1371389627456665 - 1.138044834136963)
- Le range interne represente 54% du range de la mere
- Niveau surveille : sortie du range de la bougie mere, dans un sens ou dans l'autre
- niveau `MOTHER_HIGH` = 1.1381744146347046
- niveau `MOTHER_LOW` = 1.1364928483963013
- niveau `INSIDE_HIGH` = 1.138044834136963
- niveau `INSIDE_LOW` = 1.1371389627456665

### EURUSD M15 - BULLISH_ENGULFING (CONFIRMED, confiance 77.8)
Contexte : `BULLISH_ENGULFING_AT_RESISTANCE`
- Bougie 296 : O 1.1359764337539673 H 1.1359764337539673 L 1.1352026462554932 C 1.1353315114974976
- Bougie 297 : O 1.1353315114974976 H 1.1359764337539673 L 1.1353315114974976 C 1.1359764337539673
- Englobement du corps reel : 100% du corps precedent couvert
- Taille des corps : 6.4 pips contre 6.4 pips (x1.00)
- Niveau de confirmation : cloture au-dessus de 1.13598
- CONFIRMATION : cloture 1.1363636255264282 au-dessus de PATTERN_HIGH 1.1359764338
- niveau `TRIGGER` = 1.1359764337539673
- niveau `INVALIDATION` = 1.1353315114974976
- niveau `PATTERN_HIGH` = 1.1359764337539673
- niveau `PATTERN_LOW` = 1.1353315114974976

### EURUSD M15 - BULLISH_ENGULFING (INVALIDATED, confiance 87.5)
Contexte : `BULLISH_ENGULFING_AT_RESISTANCE`
- Bougie 291 : O 1.1361054182052612 H 1.1362345218658447 L 1.1358473300933838 C 1.1358473300933838
- Bougie 292 : O 1.1357183456420898 H 1.1363636255264282 L 1.1357183456420898 C 1.1363636255264282
- Englobement du corps reel : 100% du corps precedent couvert
- Taille des corps : 6.5 pips contre 2.6 pips (x2.50)
- Niveau de confirmation : cloture au-dessus de 1.13636
- INVALIDATION : cloture 1.1353315114974976 au-dela de 1.1357183456420898 a la bougie 292
- niveau `TRIGGER` = 1.1363636255264282
- niveau `INVALIDATION` = 1.1357183456420898
- niveau `PATTERN_HIGH` = 1.1363636255264282
- niveau `PATTERN_LOW` = 1.1357183456420898

### EURUSD M15 - BEARISH_PIN_BAR (CONFIRMED, confiance 87.5)
Contexte : `BEARISH_PIN_BAR_AT_RESISTANCE`
- Bougie 287 : O 1.1358473300933838 H 1.1362345218658447 L 1.1357183456420898 C 1.1357183456420898
- Meche haute : 3.9 pips = 75% du range (5.2 pips)
- Corps : 1.3 pips = 25% du range, rapport meche/corps x3.00
- Meche opposee : 0.0 pips = 0% du range
- Position du corps : 12% du range depuis le bas
- Niveau de confirmation : cloture au-dessus de 1.13623
- niveau `TRIGGER` = 1.1362345218658447
- niveau `INVALIDATION` = 1.1357183456420898
- niveau `PATTERN_HIGH` = 1.1362345218658447
- niveau `PATTERN_LOW` = 1.1357183456420898

### EURUSD M15 - SHOOTING_STAR (CONFIRMED, confiance 90.0)
Contexte : `SHOOTING_STAR_AT_RESISTANCE`
- Bougie 287 : O 1.1358473300933838 H 1.1362345218658447 L 1.1357183456420898 C 1.1357183456420898
- Meche haute : 3.9 pips = 75% du range (5.2 pips)
- Corps : 1.3 pips = 25% du range, rapport meche/corps x3.00
- Meche opposee : 0.0 pips = 0% du range
- Position du corps : 12% du range depuis le bas
- Niveau de confirmation : cloture au-dessus de 1.13623
- niveau `TRIGGER` = 1.1362345218658447
- niveau `INVALIDATION` = 1.1357183456420898
- niveau `PATTERN_HIGH` = 1.1362345218658447
- niveau `PATTERN_LOW` = 1.1357183456420898

## 8. Parametres effectifs (extrait)

- `globals` : {"atr_period": 14, "atr_slow_period": 100, "confirmation_buffer_pips": 1.0, "context_bars": 3, "invalidation_buffer_pips": 1.0, "max_bars_to_confirm": 12, "max_tracked": 400, "min_bars_required": 60, "pip_fallback": 0.0001, "scan_bars": 12, "window_bars": 300}
- `engulfing` : {"max_opposite_wick_ratio": 0.45, "min_body_multiple": 1.0, "min_body_ratio": 0.45, "min_candle_range_atr": 0.35, "min_candle_range_pips": 2.0, "min_coverage": 1.0, "min_previous_body_atr": 0.05, "min_previous_body_pips": 1.0, "require_direction_change": true}
- `pin_bar` : {"body_position_min": 0.6, "max_body_ratio": 0.35, "max_opposite_wick_ratio": 0.15, "min_range_atr": 0.6, "min_range_pips": 4.0, "min_wick_body_ratio": 2.0, "min_wick_range_ratio": 0.6}
- `hammer` : {"body_position_min": 0.6, "context_lookback_bars": 8, "context_min_move_atr": 0.8, "context_min_move_pips": 5.0, "max_body_ratio": 0.35, "max_opposite_wick_ratio": 0.12, "min_range_atr": 0.6, "min_range_pips": 4.0, "min_wick_body_ratio": 2.0, "min_wick_range_ratio": 0.6}
- `inside_bar` : {"containment_tolerance_pips": 0.0, "max_range_ratio": 0.9, "min_mother_range_atr": 0.6, "min_mother_range_pips": 4.0}
- `outside_bar` : {"min_breach_pips": 0.5, "min_range_atr": 0.6, "min_range_pips": 4.0, "min_range_ratio": 1.1}
- `doji` : {"long_legged_wick_ratio": 0.3, "max_body_ratio": 0.1, "min_range_atr": 0.5, "min_range_pips": 3.0}
- `structure` : {"consolidation_box_bars": 10, "consolidation_max_compression": 0.6, "consolidation_max_height_atr": 1.5, "consolidation_min_bars": 5, "consolidation_reference_bars": 40, "consolidation_tolerance_pips": 1.0, "consolidation_window_bars": 20, "failed_breakout_max_bars_to_fail": 20, "failed_breakout_min_return_pips": 1.0, "impulse_max_lookback_bars": 24, "impulse_max_pullback_ratio": 0.4, "impulse_min_bars": 4, "impulse_min_efficiency": 0.8, "impulse_min_move_atr": 1.5, "impulse_min_move_pips": 15.0, "rejection_level_tolerance_atr": 0.25, "rejection_level_tolerance_pips": 2.0, "rejection_max_bars_after_touch": 1, "rejection_min_close_distance_pips": 3.0, "rejection_min_wick_range_ratio": 0.5}
- `levels` : {"context_band_atr": 5.0, "context_labels": true, "max_level_age_bars": 80, "proximity_atr": 0.5, "proximity_pips": 6.0, "zone_tolerance_atr": 0.7, "zone_tolerance_pips": 8.0}
- `confluence` : {"enabled": true, "trading_signal": false, "window_bars": 10}

> Ce rapport ne pretend pas que les detections sont toutes correctes : il montre ce que le moteur a mesure, sur quelles bougies reelles, et avec quels criteres. Le marche reste a interpreter par un humain.
