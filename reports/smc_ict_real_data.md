# SMART MARKET VISION - moteur SMC/ICT (Phase 4) sur donnees reelles

Genere : 2026-09-30T14:00:18.148077+00:00  
Paires : EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,NZDUSD,EURGBP,EURJPY,GBPJPY  
Timeframes : M15,H1,H4  
Bougies demandees par serie : 300 (fenetre moteur : 300,
fenetre d'evenements : 12, historique de structure : 200)

## 1. Volumetrie

- series analysees : **30** / 30 demandees
- bougies cloturees analysees : **8970**
- candidats bruts : **1325**
- objets SMC/ICT retenus : **1325**
- groupes de confluence : **87**
- erreurs : **0**, avertissements moteur : **0**, avertissements qualite du provider : **60** (gaps de week-end, bougie en cours repliee)
- duree par serie : min 79.5 ms / mediane 133.1 ms / max 222.6 ms

## 2. Repartition

| Pattern | Objets |
| --- | --- |
| BEARISH_FVG | 307 |
| BULLISH_FVG | 238 |
| LIQUIDITY_POOL_ESTIMATE | 216 |
| EQUAL_HIGH | 127 |
| EQUAL_LOW | 115 |
| BEARISH_ORDER_BLOCK | 98 |
| BULLISH_ORDER_BLOCK | 68 |
| DISPLACEMENT | 39 |
| BOS | 33 |
| BREAKER_BLOCK | 31 |
| DEALING_RANGE | 25 |
| CHOCH | 10 |
| DISCOUNT | 7 |
| MSS | 4 |
| PREMIUM | 4 |
| LIQUIDITY_SWEEP | 3 |

| Famille | Objets | | Statut | Objets |
| --- | --- | --- | --- | --- |
| GAPS | 545 | | ACTIVE | 648 |
| LIQUIDITY | 461 | | FILLED | 396 |
| BLOCKS | 197 | | CONFIRMED | 120 |
| RANGE | 75 | | MITIGATED | 82 |
| STRUCTURE | 47 | | INVALIDATED | 75 |
|  |  | | DETECTED | 4 |

| Etat SMC (FVG / blocs) | Objets |
| --- | --- |
| FILLED | 396 |
| ACTIVE | 154 |
| INVALIDATED | 75 |
| MITIGATED | 42 |
| PARTIALLY_FILLED | 40 |
| CREATED | 4 |

| Paire | Objets | | Timeframe | Objets |
| --- | --- | --- | --- | --- |
| AUDUSD | 159 | | H1 | 448 |
| NZDUSD | 158 | | M15 | 443 |
| USDJPY | 153 | | H4 | 434 |
| EURJPY | 149 | |  |  |
| GBPUSD | 146 | |  |  |
| EURUSD | 137 | |  |  |
| GBPJPY | 128 | |  |  |
| USDCHF | 124 | |  |  |
| EURGBP | 93 | |  |  |
| USDCAD | 78 | |  |  |

## 3. Controle anti-fiction (bougies reelles)

- objets dont la bougie d'ancrage n'existe pas : **0**
- objets dont une mesure ne se recompose pas sur l'OHLC reel : **0**
- objets dont une coordonnee sort de la bougie : **0**
- confiances non reproductibles a partir des criteres : **0**
- objets contenant un mot d'instruction de trading : **0**
- objets explicitement marques comme estimation : **219** (liquidite)
- objets portant un volume invente : **0**

## 4. Controle negatif (§25)

| Marche | Bougies | Objets | Objets/bougie | Structure (BOS/CHOCH/MSS) |
| --- | --- | --- | --- | --- |
| bruit_aleatoire | 300 | 43 | 0.1433 | 1/1/0 |
| marche_plat | 200 | 0 | 0.0 | 0/0/0 |
| fortement_directionnel | 200 | 0 | 0.0 | 0/0/0 |

- **bruit_aleatoire** : {'BULLISH_FVG': 8, 'BEARISH_FVG': 7, 'EQUAL_HIGH': 6, 'EQUAL_LOW': 5, 'LIQUIDITY_POOL_ESTIMATE': 5, 'BULLISH_ORDER_BLOCK': 3, 'BEARISH_ORDER_BLOCK': 3, 'BREAKER_BLOCK': 2, 'DISCOUNT': 1, 'DEALING_RANGE': 1, 'CHOCH': 1, 'BOS': 1}
- **marche_plat** : aucun objet
- **fortement_directionnel** : aucun objet

Ce controle est publie tel quel : les seuils ne sont pas ajustes pour atteindre zero.

## 5. Erreurs et avertissements

- aucune erreur
- aucun avertissement moteur
- avertissements qualite du provider (donnees reelles, non masques) :
  - EURUSD M15 : 1 bar(s) snapped onto the M15 grid (source offset <= 5s, prices unchanged)
  - EURUSD M15 : 6 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
  - EURUSD H1 : 1 bar(s) snapped onto the H1 grid (source offset <= 5s, prices unchanged)
  - EURUSD H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
  - EURUSD H4 : 1 partial bar(s) folded into the running H4 bar (newest close kept, high/low extended)
  - EURUSD H4 : 1 running bar(s) re-stamped on their H4 period start (upstream stamps the in-progress bar with the current time; prices unchanged)
  - GBPUSD M15 : 1 bar(s) snapped onto the M15 grid (source offset <= 5s, prices unchanged)
  - GBPUSD M15 : 6 incomplete source bar(s) inside the returned window (weekend / holiday gaps)
  - GBPUSD H1 : 1 bar(s) snapped onto the H1 grid (source offset <= 5s, prices unchanged)
  - GBPUSD H1 : 2 incomplete source bar(s) inside the returned window (weekend / holiday gaps)

## 6. Surface live (si un serveur repond)

- moteurs : {'SMC_ICT_ENGINE': 'ENABLED'}
- trading_signal : False
- groupes de parametres exposes : 17
- objets suivis par l'instance : 400 (statut ACTIVE SMC ICT)
- mots d'instruction de trading dans la reponse : aucun

## 7. Definitions retenues (une seule par concept)

- **BOS** : cloture au-dela du dernier swing confirme, dans le sens de la structure. Une meche seule ne casse rien.
- **CHOCH** : la structure est cassee dans l'autre sens (seuil de cassure 1.0 pip / 0.05 ATR, minimum 3 swings).
- **MSS** : CHOCH + deplacement (extension >= 0.8 ATR, dans les 3 bougies). Un CHOCH sans deplacement reste un CHOCH.
- **Equal high/low** : >= 2 pivots dans une tolerance de max(3.0 pips, 0.15 ATR).
- **LIQUIDITY_POOL_ESTIMATE** : inference geometrique d'une zone de liquidite - jamais un carnet d'ordres observe.
- **Liquidity sweep** : depassement + reintroduction par la cloture + excursion reelle (les trois etapes).
- **FVG** : bande non tradee sur trois bougies, taille >= max(1.0 pips, 0.1 ATR) ; mitigation CREATED/ACTIVE/PARTIALLY_FILLED/FILLED.
- **Order block** : derniere bougie opposee avant un deplacement qui casse la structure (<= 8 bougies).
- **Breaker** : jamais detecte seul - cycle ORDER_BLOCK -> INVALIDATION -> STRUCTURAL_BREAK -> BREAKER.
- **Displacement** : range >= max(8.0 pips, 1.2 ATR), corps/range >= 0.55, progression au-dela de l'extreme precedent.
- **Dealing range** : plus haut sommet et plus bas creux confirmes de 120 bougies, hauteur >= 2.0 ATR ; premium >= 0.75, discount <= 0.25.
- **Confluence** : descriptive uniquement, familles distinctes exigees, aucun score, trading_signal = False.
