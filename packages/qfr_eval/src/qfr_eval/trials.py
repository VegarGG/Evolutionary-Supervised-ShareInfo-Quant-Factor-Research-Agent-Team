"""Multiple-testing statistics over the trial ledger (PLAN Section 8.7): N_eff, DSR, PBO
and the Harvey-Liu-Zhu hurdle.

N_eff is the number of behavioral clusters among a window's trials: single-linkage
grouping at fingerprint similarity 0.7, computed by the nightly job and recorded in
trial_cluster_runs and trial_clusters. Above 20,000 trials the number of families is
used instead. Trials are clustered within their kind: a factor's trial statistic is its
daily LS net return and a strategy's is its daily active return, so the two are never
pooled in one Sharpe variance or one cluster count. Similarity is exact: fingerprints
with the same support on every date are compared in blocks by matrix products (their
Spearman correlation is the Pearson correlation of the stored ranks), and the rare
pairs with different supports are re-ranked pairwise as in intake dedup.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import numpy as np
import polars as pl
from qfr_core.ids import uuid7
from qfr_core.metrics.fingerprint import Fingerprint, behavioral_similarity
from qfr_core.metrics.matrix import Array
from qfr_core.metrics.stats import dsr, expected_max_sharpe, newey_west_lag, newey_west_t, pbo, psr
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_eval.store import ArtifactStore

BLOCK = 512  # Fingerprints compared per matrix block.


# Clustering -----------------------------------------------------------------------------


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _support_key(fp: Fingerprint) -> tuple[Any, ...]:
    return (tuple(fp.instruments), np.isfinite(fp.ranks).tobytes())


def _block_similarity(group: Sequence[Fingerprint]) -> Array:
    """Mean |Spearman| between fingerprints that share their support on every date."""
    count = len(group)
    total = np.zeros((count, count))
    dates = np.zeros((count, count))
    stack = np.stack([fp.ranks for fp in group])  # (count, dates, names)
    for d in range(stack.shape[1]):
        ranks = stack[:, d, :]
        keep = np.isfinite(ranks[0])
        if keep.sum() < 2:
            continue
        x = ranks[:, keep]
        x = x - x.mean(axis=1, keepdims=True)
        norm = np.sqrt((x * x).sum(axis=1))
        valid = norm > 1e-300
        z = np.where(valid[:, None], x / np.where(valid, norm, 1.0)[:, None], 0.0)
        for start in range(0, count, BLOCK):
            stop = min(count, start + BLOCK)
            corr = np.abs(z[start:stop] @ z.T)
            ok = valid[start:stop, None] & valid[None, :]
            total[start:stop] += np.where(ok, corr, 0.0)
            dates[start:stop] += ok
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(dates > 0, total / np.maximum(dates, 1), np.nan)


def similarity_edges(
    fingerprints: Sequence[Fingerprint], threshold: float
) -> list[tuple[int, int]]:
    """Pairs (i, j), i < j, whose behavioral similarity is at least threshold."""
    groups: dict[tuple[Any, ...], list[int]] = {}
    for index, fp in enumerate(fingerprints):
        groups.setdefault(_support_key(fp), []).append(index)
    edges: list[tuple[int, int]] = []
    members = list(groups.values())
    for indices in members:
        if len(indices) < 2:
            continue
        values = _block_similarity([fingerprints[i] for i in indices])
        rows, cols = np.nonzero(np.triu(values >= threshold, k=1))
        edges += [
            (indices[a], indices[b]) for a, b in zip(rows.tolist(), cols.tolist(), strict=True)
        ]
    for g, first in enumerate(members):
        for second in members[g + 1 :]:
            for i in first:
                for j in second:
                    value = behavioral_similarity(fingerprints[i], fingerprints[j])
                    if value is not None and value >= threshold:
                        edges.append((min(i, j), max(i, j)))
    return sorted(set(edges))


def single_linkage(count: int, edges: Iterable[tuple[int, int]]) -> list[int]:
    """Connected components of the similarity graph, numbered 0.. in order of first member."""
    forest = _UnionFind(count)
    for a, b in edges:
        forest.union(a, b)
    labels: dict[int, int] = {}
    return [labels.setdefault(forest.find(i), len(labels)) for i in range(count)]


@dataclass(frozen=True)
class ClusterRun:
    run_id: Any
    method: Literal["single_linkage", "families"]
    trials: int
    families: int
    clusters: int
    n_eff: int
    without_fingerprint: int


def cluster_trials(
    conn: Connection,
    store: ArtifactStore,
    epoch_id: str,
    window: str,
    similarity: float,
    family_fallback_trials: int,
    at: datetime,
    request_id: str,
) -> ClusterRun:
    """Cluster the window's trials and record the run (the nightly N_eff job)."""
    rows = conn.execute(
        text(
            "SELECT t.version_id, t.family_id, i.kind, f.uri, f.sha256 "
            "FROM eval.trial_ledger t JOIN eval.intake i ON i.version_id = t.version_id "
            "LEFT JOIN eval.fingerprints f ON f.version_id = t.version_id "
            "  AND f.epoch_id = t.epoch_id "
            "WHERE t.epoch_id = :e AND t.window_name = :w ORDER BY t.counted_at, t.version_id"
        ),
        {"e": epoch_id, "w": window},
    ).all()
    families = {r.family_id for r in rows}
    labels: list[int] = [0] * len(rows)
    without = sum(1 for r in rows if r.uri is None)
    method: Literal["single_linkage", "families"]
    if len(rows) > family_fallback_trials:
        method = "families"
        order: dict[Any, int] = {}
        labels = [order.setdefault((r.kind, r.family_id), len(order)) for r in rows]
    else:
        method = "single_linkage"
        offset = 0
        for kind in sorted({r.kind for r in rows}):
            indices = [i for i, r in enumerate(rows) if r.kind == kind]
            printed = [i for i in indices if rows[i].uri is not None]
            fps = [store.read_fingerprint(rows[i].uri, rows[i].sha256) for i in printed]
            local = single_linkage(len(fps), similarity_edges(fps, similarity))
            for i, label in zip(printed, local, strict=True):
                labels[i] = offset + label
            offset += (max(local) + 1) if local else 0
            for i in indices:  # A trial without a fingerprint is its own cluster.
                if rows[i].uri is None:
                    labels[i] = offset
                    offset += 1
    clusters = len(set(labels)) if rows else 0
    run_id = uuid7()
    conn.execute(
        text(
            "INSERT INTO eval.trial_cluster_runs (run_id, epoch_id, window_name, computed_at, "
            "method, similarity, trials, families, clusters, n_eff, without_fingerprint, "
            "request_id) VALUES (:id, :e, :w, :at, :m, :s, :t, :f, :c, :n, :wo, :r)"
        ),
        {
            "id": run_id,
            "e": epoch_id,
            "w": window,
            "at": at,
            "m": method,
            "s": similarity,
            "t": len(rows),
            "f": len(families),
            "c": clusters,
            "n": clusters,
            "wo": without,
            "r": request_id,
        },
    )
    for row, label in zip(rows, labels, strict=True):
        conn.execute(
            text(
                "INSERT INTO eval.trial_clusters (run_id, epoch_id, window_name, version_id, "
                "cluster_id, computed_at) VALUES (:id, :e, :w, :v, :c, :at)"
            ),
            {"id": run_id, "e": epoch_id, "w": window, "v": row.version_id, "c": label, "at": at},
        )
    return ClusterRun(run_id, method, len(rows), len(families), clusters, clusters, without)


# The deflated Sharpe ratio --------------------------------------------------------------


@dataclass(frozen=True)
class DeflatedSharpe:
    value: float | None
    value_raw_n: float | None
    sharpe: float | None
    n_obs: int
    n_eff: int
    n_raw: int
    variance: float | None
    sr0: float | None
    cluster_run_id: str | None
    note: str | None


def _sr0(variance: float, trials: int) -> float:
    """The expected maximum Sharpe; with fewer than two trials there is nothing to deflate."""
    return expected_max_sharpe(variance, trials) if trials >= 2 else 0.0


def deflated_sharpe(
    conn: Connection, epoch_id: str, version_id: Any, kind: str, window: str = "W1"
) -> DeflatedSharpe:
    """DSR of the version's window trial with N_eff from the latest cluster run (ACC-01)."""
    own = conn.execute(
        text(
            "SELECT sharpe_daily, n_obs, skew, kurt_raw FROM eval.trial_ledger "
            "WHERE epoch_id = :e AND window_name = :w AND version_id = :v"
        ),
        {"e": epoch_id, "w": window, "v": version_id},
    ).first()
    trials = conn.execute(
        text(
            "SELECT t.sharpe_daily FROM eval.trial_ledger t JOIN eval.intake i "
            "ON i.version_id = t.version_id WHERE t.epoch_id = :e AND t.window_name = :w "
            "AND i.kind = :k"
        ),
        {"e": epoch_id, "w": window, "k": kind},
    ).all()
    run = conn.execute(
        text(
            "SELECT run_id FROM eval.trial_cluster_runs WHERE epoch_id = :e AND window_name = :w "
            "ORDER BY computed_at DESC, run_id DESC LIMIT 1"
        ),
        {"e": epoch_id, "w": window},
    ).scalar()
    n_eff = 0
    if run is not None:
        n_eff = int(
            conn.execute(
                text(
                    "SELECT count(DISTINCT c.cluster_id) FROM eval.trial_clusters c "
                    "JOIN eval.intake i ON i.version_id = c.version_id "
                    "WHERE c.run_id = :r AND i.kind = :k"
                ),
                {"r": run, "k": kind},
            ).scalar_one()
        )
    sharpes = np.array([r.sharpe_daily for r in trials if r.sharpe_daily is not None])
    variance = float(np.var(sharpes, ddof=1)) if sharpes.size >= 2 else None
    n_obs = 0 if own is None else int(own.n_obs)
    run_ref = None if run is None else str(run)

    def result(
        value: float | None,
        raw: float | None,
        sr: float | None,
        sr0: float | None,
        note: str | None,
    ) -> DeflatedSharpe:
        return DeflatedSharpe(
            value, raw, sr, n_obs, n_eff, len(trials), variance, sr0, run_ref, note
        )

    if own is None or own.sharpe_daily is None or own.skew is None or own.kurt_raw is None:
        return result(None, None, None, None, "no trial statistic")
    var = variance or 0.0
    try:
        value = (
            dsr(own.sharpe_daily, int(own.n_obs), own.skew, own.kurt_raw, var, n_eff)
            if n_eff >= 2
            else psr(own.sharpe_daily, 0.0, int(own.n_obs), own.skew, own.kurt_raw)
        )
        raw_n = len(trials)
        value_raw = (
            dsr(own.sharpe_daily, int(own.n_obs), own.skew, own.kurt_raw, var, raw_n)
            if raw_n >= 2
            else psr(own.sharpe_daily, 0.0, int(own.n_obs), own.skew, own.kurt_raw)
        )
    except ValueError as error:
        return result(None, None, float(own.sharpe_daily), None, str(error))
    note = None if n_eff >= 2 else "fewer than two clusters; SR0 = 0"
    return result(value, value_raw, float(own.sharpe_daily), _sr0(var, n_eff), note)


# PBO and HLZ ----------------------------------------------------------------------------


def trial_series(
    conn: Connection, store: ArtifactStore, record_id: Any, kind: str
) -> pl.DataFrame | None:
    """A record's daily trial series by date: LS net returns for a factor, active
    returns (net minus benchmark) for a strategy, from its series files."""
    run = conn.execute(
        text("SELECT run_ids[1] FROM eval.official_records WHERE record_id = :r"),
        {"r": record_id},
    ).scalar()
    name = "nav" if kind == "strategy" else "ls_returns"
    row = conn.execute(
        text("SELECT uri, sha256 FROM eval.series_files WHERE run_id = :r AND kind = :k"),
        {"r": run, "k": name},
    ).first()
    if row is None:
        return None
    frame = store.read_series(row.uri, row.sha256)
    if kind == "strategy":
        values = frame.get_column("net_return") - frame.get_column("benchmark_return")
    else:
        values = frame.get_column("ls_net")
    return pl.DataFrame({"date": frame.get_column("date"), "value": values})


@dataclass(frozen=True)
class PboResult:
    value: float | None
    cohort: Literal["family", "generation"] | None
    members: int
    rows: int
    note: str | None


def backtest_overfitting(
    conn: Connection,
    store: ArtifactStore,
    epoch_id: str,
    version_id: Any,
    kind: str,
    blocks: int,
    cohort_min: int,
) -> PboResult:
    """PBO by CSCV on the version's cohort of W1 trials (Section 8.7)."""
    me = conn.execute(
        text(
            "SELECT family_id, manifest -> 'manifest' -> 'provenance' ->> 'generation_id' AS g "
            "FROM eval.intake WHERE version_id = :v"
        ),
        {"v": version_id},
    ).first()
    if me is None:
        return PboResult(None, None, 0, 0, "the version has no intake row")
    base = (
        "SELECT t.version_id, t.record_id FROM eval.trial_ledger t JOIN eval.intake i "
        "ON i.version_id = t.version_id WHERE t.epoch_id = :e AND t.window_name = 'W1' "
        "AND i.kind = :k AND "
    )
    family = conn.execute(
        text(base + "t.family_id = :f ORDER BY t.version_id"),
        {"e": epoch_id, "k": kind, "f": me.family_id},
    ).all()
    cohort: Literal["family", "generation"] = "family"
    members = family
    if len(family) < cohort_min and me.g is not None:
        members = conn.execute(
            text(
                base + "i.manifest -> 'manifest' -> 'provenance' ->> 'generation_id' = :g "
                "ORDER BY t.version_id"
            ),
            {"e": epoch_id, "k": kind, "g": me.g},
        ).all()
        cohort = "generation"
    if len(members) < cohort_min:
        return PboResult(
            None, None, len(members), 0,
            f"the family and generation cohorts have fewer than {cohort_min} W1 trials",
        )  # fmt: skip
    frames = []
    for member in members:
        series = trial_series(conn, store, member.record_id, kind)
        if series is not None:
            frames.append(series.rename({"value": str(member.version_id)}))
    if len(frames) < cohort_min:
        return PboResult(None, cohort, len(frames), 0, "cohort series are missing")
    joined = frames[0]
    for frame in frames[1:]:
        joined = joined.join(frame, on="date", how="inner")
    matrix = joined.drop("date").to_numpy().astype(np.float64)
    matrix = matrix[np.isfinite(matrix).all(axis=1)]
    try:
        value, _ = pbo(matrix, blocks)
    except ValueError as error:
        return PboResult(None, cohort, len(frames), int(matrix.shape[0]), str(error))
    return PboResult(value, cohort, len(frames), int(matrix.shape[0]), None)


@dataclass(frozen=True)
class HurdleResult:
    t_value: float | None
    observations: int
    lag: int
    windows: list[str]


def hlz_hurdle(
    conn: Connection,
    store: ArtifactStore,
    epoch_id: str,
    version_id: Any,
    kind: str,
    horizon: int,
) -> HurdleResult:
    """Newey-West t of the daily trial series over W1, W2 and W3 combined; embargo gaps
    are excluded because only the windows' own days are used (Section 8.7)."""
    rows = conn.execute(
        text(
            "SELECT record_id, window_name FROM eval.official_records WHERE version_id = :v "
            "AND epoch_id = :e AND stage IN ('w1', 'w2', 'holdout') ORDER BY window_name"
        ),
        {"v": version_id, "e": epoch_id},
    ).all()
    parts: list[Array] = []
    windows = []
    for row in rows:
        series = trial_series(conn, store, row.record_id, kind)
        if series is None:
            continue
        values = series.get_column("value").cast(float).fill_null(np.nan).to_numpy()
        parts.append(values[np.isfinite(values)])
        windows.append(row.window_name)
    combined = np.concatenate(parts) if parts else np.zeros(0)
    lag = newey_west_lag(int(combined.size), horizon)
    value = newey_west_t(combined, lag) if combined.size else None
    return HurdleResult(
        None if value is None or not math.isfinite(value) else value,
        int(combined.size),
        lag,
        windows,
    )
