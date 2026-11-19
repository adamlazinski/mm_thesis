"""
inference.py
============
Interval estimates for the thesis's headline quantities.

Every P&L figure in this thesis is a sample mean over a small number of days,
and until now none carried an interval. Three features of the data make the
textbook standard error wrong, and each gets its own tool here:

  dependence   daily P&L is serially correlated (a regime persists across
               days), so the iid standard error understates the spread.
               `block_bootstrap_mean` resamples contiguous blocks instead of
               single days, preserving within-block dependence.
  clustering   the thirty coin-days of Ch8 are six coins observed five times,
               not thirty independent observations. The coin is the unit of
               replication, so `cluster_bootstrap_mean` resamples coins.
  overlap      markouts at horizon h taken from trades arriving faster than h
               share future price path. `effective_n` reports how many
               independent observations the sample is actually worth.

The intervals are percentile bootstrap, reported at 95%. They are wide, and
for n = 5 they are very wide; that is the honest content of a five-day sample
and the reason a one-sided reading of any single column is unsafe.
"""
from __future__ import annotations

import numpy as np

RNG = np.random.default_rng(20261119)   # fixed: the intervals are reproducible


def _ci(draws, alpha=0.05):
    lo, hi = np.quantile(draws, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def iid_ci(x, alpha=0.05):
    """Textbook normal-approximation interval, for comparison only."""
    x = np.asarray(x, float)
    n = len(x)
    se = x.std(ddof=1) / np.sqrt(n)
    z = 1.959963984540054
    return float(x.mean() - z * se), float(x.mean() + z * se)


def auto_block(n):
    """Politis-White-flavoured default: b ~ n^(1/3), at least 2."""
    return max(2, int(round(n ** (1 / 3))))


def block_bootstrap_mean(x, block=None, B=20000, alpha=0.05, rng=RNG):
    """
    Moving-block bootstrap for the mean of a dependent series.

    Blocks of length `block` are drawn with replacement from the n - block + 1
    overlapping blocks and concatenated to length n. With block = 1 this
    reduces to the iid bootstrap.
    """
    x = np.asarray(x, float)
    n = len(x)
    if block is None:
        block = auto_block(n)
    block = min(block, n)
    k = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(B, k))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(B, -1)[:, :n]
    draws = x[idx].mean(axis=1)
    return {"mean": float(x.mean()), "n": n, "block": block,
            "ci": _ci(draws, alpha), "se_boot": float(draws.std(ddof=1)),
            "ci_iid": iid_ci(x, alpha)}


def cluster_bootstrap_mean(values, clusters, B=20000, alpha=0.05, rng=RNG):
    """
    Cluster bootstrap: resample whole clusters with replacement, then take the
    mean of the pooled observations. Use where the unit of replication is the
    cluster (an instrument observed on several days) rather than the
    observation.
    """
    values = np.asarray(values, float)
    clusters = np.asarray(clusters)
    uniq = np.unique(clusters)
    groups = [values[clusters == c] for c in uniq]
    g = len(groups)
    draws = np.empty(B)
    pick = rng.integers(0, g, size=(B, g))
    for b in range(B):
        draws[b] = np.concatenate([groups[i] for i in pick[b]]).mean()
    return {"mean": float(values.mean()), "n": len(values), "n_clusters": g,
            "ci": _ci(draws, alpha), "se_boot": float(draws.std(ddof=1)),
            "ci_iid": iid_ci(values, alpha)}


def effective_n(x, max_lag=None):
    """
    Effective sample size n / (1 + 2 * sum_k rho_k), with the sum truncated at
    the first non-positive autocorrelation (the initial-positive-sequence rule).
    Reported so that a large nominal n built from overlapping observations is
    not mistaken for a large independent one.
    """
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 8:
        return {"n": n, "n_eff": float(n), "rho1": None}
    xc = x - x.mean()
    denom = np.dot(xc, xc)
    if denom <= 0:
        return {"n": n, "n_eff": float(n), "rho1": 0.0}
    max_lag = max_lag or min(n // 4, 200)
    rhos, tot = [], 0.0
    for k in range(1, max_lag + 1):
        r = float(np.dot(xc[:-k], xc[k:]) / denom)
        if r <= 0:
            break
        rhos.append(r); tot += r
    return {"n": n, "n_eff": float(n / (1 + 2 * tot)),
            "rho1": (rhos[0] if rhos else 0.0), "n_lags_used": len(rhos)}


def sharpe_with_ci(x, periods=365, B=20000, block=None, alpha=0.05, rng=RNG):
    """Annualised Sharpe of a daily series, with a block-bootstrap interval."""
    x = np.asarray(x, float)
    n = len(x)
    if block is None:
        block = auto_block(n)
    block = min(block, n)
    k = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(B, k))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(B, -1)[:, :n]
    s = x[idx]
    sd = s.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        draws = np.where(sd > 0, s.mean(axis=1) / sd * np.sqrt(periods), np.nan)
    draws = draws[np.isfinite(draws)]
    pt = x.mean() / x.std(ddof=1) * np.sqrt(periods)
    return {"sharpe": float(pt), "n": n, "block": block, "ci": _ci(draws, alpha)}


def holm(pvals, alpha=0.05):
    """
    Holm-Bonferroni step-down. Returns (reject, adjusted) in input order.
    Used where a sweep reports its best cell: k configurations tried means the
    nominal p of the winner is not its p.
    """
    p = np.asarray(pvals, float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    running = 0.0
    for i, j in enumerate(order):
        running = max(running, (m - i) * p[j])
        adj[j] = min(1.0, running)
    return adj <= alpha, adj
