"""Thresholdout for W2 (PLAN Section 9.5, P8.3), after Dwork et al.'s reusable holdout.

Optional: a release policy with `w2_mode: thresholdout` and its parameters replaces the
Ladder's release of a family best with one Thresholdout answer per W2 query. The query
statistic is s x RankIC_mean, which the evaluator computes on W0 itself and on W2.

  - The noisy threshold starts at T + Laplace(2 sigma).
  - Per query: draw eta = Laplace(4 sigma). If |W2 - W0| > noisy threshold + eta, the
    answer is W2 + Laplace(sigma), the budget B falls by one and the noisy threshold is
    drawn again; otherwise the answer is the W0 value ("consistent with in-sample").
  - Once B is below 1, W2 answers nothing until the next epoch.

PASS or FAIL is still the true W2 gate, as in Ladder mode (it is what the pipeline acts
on, and the W2 quota bounds it). The state is per epoch and its parameters are pinned at
the epoch's first query, so activating another policy cannot refill the budget. Every
draw comes from a generator seeded by (policy seed, epoch, draw number), so each one can
be recomputed, and is logged insert-only with the query it served; the seed is private
(it is left out of the policy card).
"""

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Connection

Purpose = Literal["threshold", "query", "answer"]
Source = Literal["w0", "w2", "exhausted", "missing"]


@dataclass(frozen=True)
class Params:
    threshold: float
    sigma: float
    budget: int
    seed: int

    @classmethod
    def from_policy(cls, policy: dict[str, Any]) -> "Params | None":
        """The policy's Thresholdout parameters, or None in Ladder mode."""
        if policy.get("w2_mode", "ladder") != "thresholdout":
            return None
        t = policy["thresholdout"]
        return cls(float(t["threshold"]), float(t["sigma"]), int(t["budget"]), int(t["seed"]))


@dataclass(frozen=True)
class State:
    noisy_threshold: float
    budget: int


@dataclass(frozen=True)
class Answer:
    value: float | None
    source: Source
    over: bool
    query_noise: float | None
    noisy_threshold: float  # the threshold the query was compared with
    budget_after: int


def laplace(seed: int, epoch_id: str, seq: int, scale: float) -> float:
    """Draw number `seq` of an epoch: reproducible from the seed alone."""
    key = int.from_bytes(hashlib.sha256(epoch_id.encode()).digest()[:8], "big")
    return float(np.random.default_rng([seed, key, seq]).laplace(0.0, scale))


Draw = Callable[[Purpose, float], float]


def start(params: Params, draw: Draw) -> State:
    return State(params.threshold + draw("threshold", 2 * params.sigma), params.budget)


def step(params: Params, state: State, w0: float, w2: float, draw: Draw) -> tuple[Answer, State]:
    """One query (Section 9.5)."""
    if state.budget < 1:
        return Answer(None, "exhausted", False, None, state.noisy_threshold, state.budget), state
    eta = draw("query", 4 * params.sigma)
    if abs(w2 - w0) > state.noisy_threshold + eta:
        value = w2 + draw("answer", params.sigma)
        budget = state.budget - 1
        after = State(params.threshold + draw("threshold", 2 * params.sigma), budget)
        return Answer(value, "w2", True, eta, state.noisy_threshold, budget), after
    return Answer(w0, "w0", False, eta, state.noisy_threshold, state.budget), state


def query(
    conn: Connection,
    params: Params,
    epoch_id: str,
    policy_ref: str,
    record_id: UUID,
    version_id: UUID,
    w0: float | None,
    w2: float | None,
    at: datetime,
) -> Answer:
    """Answer one W2 query in the caller's transaction (under the evaluator's lock) and
    log it with every draw. A missing statistic answers nothing and spends nothing."""
    row = conn.execute(
        text(
            "SELECT threshold, sigma, budget_initial, seed, noisy_threshold, budget_remaining, "
            "draws FROM eval.thresholdout_state WHERE epoch_id = :e FOR UPDATE"
        ),
        {"e": epoch_id},
    ).first()
    seq = 0 if row is None else int(row.draws)
    pinned = (
        params
        if row is None
        else Params(float(row.threshold), float(row.sigma), int(row.budget_initial), int(row.seed))
    )

    def draw(purpose: Purpose, scale: float) -> float:
        nonlocal seq
        seq += 1
        value = laplace(pinned.seed, epoch_id, seq, scale)
        conn.execute(
            text(
                "INSERT INTO eval.thresholdout_draws (epoch_id, seq, purpose, scale, value, "
                "record_id, version_id, at) VALUES (:e, :q, :p, :s, :v, :r, :ver, :at)"
            ),
            {"e": epoch_id, "q": seq, "p": purpose, "s": scale, "v": value, "r": record_id,
             "ver": version_id, "at": at},
        )  # fmt: skip
        return value

    if row is None:
        state = start(pinned, draw)
        conn.execute(
            text(
                "INSERT INTO eval.thresholdout_state (epoch_id, policy_ref, threshold, sigma, "
                "budget_initial, seed, noisy_threshold, budget_remaining, draws, queries, "
                "started_at, updated_at) VALUES (:e, :p, :t, :s, :b, :seed, :nt, :b, :d, 0, "
                ":at, :at)"
            ),
            {"e": epoch_id, "p": policy_ref, "t": pinned.threshold, "s": pinned.sigma,
             "b": pinned.budget, "seed": pinned.seed, "nt": state.noisy_threshold, "d": seq,
             "at": at},
        )  # fmt: skip
    else:
        state = State(float(row.noisy_threshold), int(row.budget_remaining))
    if w0 is not None and w2 is not None and math.isfinite(w0) and math.isfinite(w2):
        answer, after = step(pinned, state, w0, w2, draw)
    else:
        source: Source = "exhausted" if state.budget < 1 else "missing"
        answer = Answer(None, source, False, None, state.noisy_threshold, state.budget)
        after = state
    conn.execute(
        text(
            "UPDATE eval.thresholdout_state SET noisy_threshold = :nt, budget_remaining = :b, "
            "draws = :d, queries = queries + 1, updated_at = :at WHERE epoch_id = :e"
        ),
        {"nt": after.noisy_threshold, "b": after.budget, "d": seq, "at": at, "e": epoch_id},
    )
    conn.execute(
        text(
            "INSERT INTO eval.thresholdout_queries (record_id, epoch_id, version_id, w0_value, "
            "w2_value, noisy_threshold, query_noise, over_threshold, answer, source, "
            "budget_after, at) VALUES (:r, :e, :v, :w0, :w2, :nt, :eta, :over, :a, :src, :b, :at)"
        ),
        {"r": record_id, "e": epoch_id, "v": version_id, "w0": w0, "w2": w2,
         "nt": answer.noisy_threshold, "eta": answer.query_noise, "over": answer.over,
         "a": answer.value, "src": answer.source, "b": answer.budget_after, "at": at},
    )  # fmt: skip
    return answer
