"""Statistics (F8): confidence intervals and significance tests between versions.

Agents are random, so one run proves little. Pass rates get Wilson and
bootstrap intervals; version comparisons use Fisher's exact test on pass counts
(overall and per category) and Mann-Whitney U on latency. A regression is only
reported when the drop is statistically significant.
"""

from __future__ import annotations

import math

from .models import RunResult

# numpy/scipy are imported inside the functions that need them: scipy.stats alone can
# take seconds to import, and most CLI commands never touch it.


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_ci(values: list[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    if not values:
        return (0.0, 1.0)
    import numpy as np

    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return (float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2)))


def _counts(results: list[RunResult], category: str | None = None) -> tuple[int, int]:
    rs = [r for r in results if category is None or r.category == category]
    return sum(r.passed for r in rs), len(rs)


def compare(base: list[RunResult], new: list[RunResult], alpha: float = 0.05, max_drop: float = 0.0) -> dict:
    """Compare two runs. `regression` is True if any pass rate drops by more than
    `max_drop` with p < alpha (one-sided Fisher exact test)."""
    import numpy as np
    from scipy import stats as sps

    rows = []
    categories = sorted({r.category for r in base} | {r.category for r in new})
    for cat in [None, *categories]:
        kb, nb = _counts(base, cat)
        kn, nn = _counts(new, cat)
        if nb == 0 or nn == 0:
            continue
        rb, rn = kb / nb, kn / nn
        # H1: the new version passes less often than the base.
        _, p = sps.fisher_exact([[kn, nn - kn], [kb, nb - kb]], alternative="less")
        rows.append({
            "metric": "pass_rate" if cat is None else f"pass_rate[{cat}]",
            "base": rb, "new": rn, "delta": rn - rb, "p_value": float(p),
            "base_ci": wilson_ci(kb, nb), "new_ci": wilson_ci(kn, nn),
            "regression": bool(p < alpha and rb - rn > max_drop),
        })
    lat_b, lat_n = [r.latency_s for r in base], [r.latency_s for r in new]
    if len(lat_b) > 1 and len(lat_n) > 1:
        _, p = sps.mannwhitneyu(lat_n, lat_b, alternative="greater")
        rows.append({
            "metric": "latency_s (median)", "base": float(np.median(lat_b)), "new": float(np.median(lat_n)),
            "delta": float(np.median(lat_n) - np.median(lat_b)), "p_value": float(p),
            "regression": False,  # reported, not gated: wall-clock latency is noisy on shared runners
        })
    return {"alpha": alpha, "max_drop": max_drop, "rows": rows,
            "regression": any(r["regression"] for r in rows)}


def cohen_kappa(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)
