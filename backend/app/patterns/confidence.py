"""Confidence scoring.

``confidence`` is NEVER guessed: it is the weighted share of the explicit
criteria a detector declares as passed.

    confidence = round(100 * sum(weight of passed criteria) / sum(all weights))

A criterion that is not declared cannot influence the score, and the weights live
in :mod:`app.patterns.params` (``ConfidenceWeights``).
"""

from __future__ import annotations

from app.schemas.events import ConfidenceFactor


def score(factors: list[tuple[str, bool, float, str]]) -> tuple[float, list[ConfidenceFactor]]:
    """Return (confidence 0-100, detailed factors)."""
    if not factors:
        return 0.0, []
    total_weight = sum(max(0.0, weight) for _, _, weight, _ in factors)
    passed_weight = sum(max(0.0, weight) for _, passed, weight, _ in factors if passed)
    confidence = 0.0 if total_weight <= 0 else round(100.0 * passed_weight / total_weight, 1)
    details = [
        ConfidenceFactor(criterion=criterion, passed=passed, weight=weight, detail=detail)
        for criterion, passed, weight, detail in factors
    ]
    return confidence, details


def describe(factors: list[ConfidenceFactor]) -> list[str]:
    """Human-readable summary used by the dashboard tooltip."""
    return [
        f"{'OK ' if factor.passed else 'NON'} {factor.criterion} (poids {factor.weight}) : {factor.detail}"
        for factor in factors
    ]
