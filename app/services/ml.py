# app/services/ml.py
#
# Intentionally dependency-free "tiny ML". The brief asked for a *very basic*
# model that can be trained instantly per site/node on each request, so we use
# ordinary least-squares linear regression implemented in plain Python (no
# numpy / scikit-learn). This trains in microseconds on the few hundred rows a
# single heritage site realistically has, and never adds a heavy dependency to
# the Render deployment.

from __future__ import annotations
from typing import List, Tuple


def linear_regression(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """
    Fit y = slope * x + intercept by least squares.
    Returns (slope, intercept). Degenerate inputs fall back gracefully.
    """
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return 0.0, float(ys[0])

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0, mean_y
    slope = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / denom
    intercept = mean_y - slope * mean_x
    return slope, intercept


def predict(slope: float, intercept: float, x: float) -> float:
    return slope * x + intercept


def trend_label(slope: float, scale: float = 1.0) -> str:
    """Classify a slope into a human-readable trend, scaled by typical range."""
    threshold = 0.15 * max(scale, 1.0)
    if slope > threshold:
        return "rising"
    if slope < -threshold:
        return "falling"
    return "steady"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def site_engagement_score(
    completion_rate: float,      # 0–100
    avg_duration_mins: float,
    avg_rating: float,           # 0–5
    interactions_per_visit: float,
) -> float:
    """
    Blend a handful of normalised signals into a single 0–100 engagement score.
    Weights are deliberately simple and explainable.
    """
    completion = clamp(completion_rate, 0, 100) / 100.0
    duration = clamp(avg_duration_mins / 45.0, 0, 1)          # ~45 min = a full visit
    rating = clamp(avg_rating / 5.0, 0, 1)
    interaction = clamp(interactions_per_visit / 6.0, 0, 1)   # ~6 AI msgs = highly engaged

    score = (
        0.35 * completion +
        0.25 * duration +
        0.25 * rating +
        0.15 * interaction
    ) * 100.0
    return round(clamp(score, 0, 100), 1)


def node_engagement_score(
    popularity_pct: float,       # 0–100, share of visits that reached this node
    avg_rating: float,           # 0–5
    interactions: int,
    comments: int,
) -> float:
    popularity = clamp(popularity_pct, 0, 100) / 100.0
    rating = clamp(avg_rating / 5.0, 0, 1)
    social = clamp((interactions + comments) / 10.0, 0, 1)

    score = (0.5 * popularity + 0.3 * rating + 0.2 * social) * 100.0
    return round(clamp(score, 0, 100), 1)
