"""Price-action engine (Phase 3).

Deterministic, reproducible and explicable detection of candlestick patterns and
of the structure around them, on **closed candles only**:

* every rule comes from a named parameter (:mod:`app.price_action.params`);
* every detection carries the criteria it passed, their weights and the measured
  values - ``confidence`` is the weighted share of those criteria, never a guess;
* the engine is an observer: it never produces a trading signal, never sends an
  order, and never modifies the Phase 1 / Phase 2 foundations. It *consumes* the
  chartist levels and breakouts instead of recomputing them.
"""

from app.price_action.engine import PriceActionEngine

__all__ = ["PriceActionEngine"]
