"""Artifact-kind plugins (PLAN Section 8.10). Phase 3 implements the factor plugin.

A plugin decides eligibility for a manifest, names its ordered stages, runs each stage
into an official record payload, maps a record to whitelisted released fields, and maps
records to the owner-grade view. Strategies are held at intake until the strategy
plugin arrives in Phase 6.
"""

import hashlib
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, cast

import numpy as np
from qfr_core.backtest import BacktestSettings, run_backtest
from qfr_core.config import canonical_json
from qfr_core.contracts import DiagnosticFlag, FactorManifest, HorizonKey, ReasonCode, W1Content
from qfr_core.dsl import DslError, DslLimits, compile_expression, declaration_mismatches
from qfr_core.eligibility import Eligibility
from qfr_core.metrics.factor import FactorEvaluation, MetricSettings, evaluate_factor
from qfr_core.metrics.matrix import Array, Market
from qfr_core.metrics.stats import moments

from qfr_eval.compute import ComputeResult

STAGES = ("screening", "w1")


def results_hash(metrics: dict[str, float | None]) -> str:
    """SHA-256 of the canonical metrics JSON (Section 8.9)."""
    return hashlib.sha256(canonical_json(metrics).encode()).hexdigest()  # type: ignore[arg-type]


def _f(value: float | int | np.floating | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def run_seed(protocol_seed: int, version_id: str) -> int:
    """The run seed is pinned per version: the protocol seed mixed with the version id."""
    digest = hashlib.sha256(f"{protocol_seed}:{version_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def probe_cuts(window: tuple[int, int], count: int, seed: int) -> list[int]:
    first, last = window
    days = np.arange(first, last + 1)
    picks = np.random.default_rng(seed).choice(days.size, size=min(count, days.size), replace=False)
    return sorted(int(days[p]) for p in picks)


@dataclass(frozen=True)
class StageOutcome:
    stage: Literal["screening", "w1"]
    passed: bool
    reasons: list[ReasonCode]
    metrics: dict[str, float | None]
    summary: dict[str, Any]
    resources: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)  # Full-precision release inputs.
    series: dict[str, dict[str, list[Any]]] = field(default_factory=dict)


class LazyLibrary(Mapping[str, Array]):
    """Library factors' W1 rows, read one at a time (the library may be large)."""

    def __init__(self, loaders: dict[str, Any]) -> None:
        self._loaders = loaders

    def __getitem__(self, key: str) -> Array:
        return self._loaders[key]()  # type: ignore[no-any-return]

    def __iter__(self) -> Iterator[str]:
        return iter(self._loaders)

    def __len__(self) -> int:
        return len(self._loaders)


class FactorPlugin:
    kind = "factor"
    stages = STAGES

    def __init__(self, protocol: dict[str, Any]) -> None:
        self.protocol = protocol
        self.limits = DslLimits.from_protocol(protocol["dsl"])
        self.eligibility = Eligibility.from_protocol(protocol["universe"], protocol["eligibility"])
        self.settings = MetricSettings.from_protocol(protocol)
        self.screening = protocol["screening"]
        self.gates = protocol["gates"]["w1_factor"]

    # Screening -------------------------------------------------------------------------

    def static_checks(self, manifest: FactorManifest) -> tuple[list[ReasonCode], int | None]:
        """Parse, type check, constraints and declared-versus-parsed consistency."""
        try:
            compiled = compile_expression(manifest.implementation.expression, self.limits)
        except DslError as error:
            return [error.code], None
        mismatches = declaration_mismatches(
            compiled.analysis,
            list(manifest.declared.fields_used),
            manifest.declared.max_lookback_days,
        )
        reasons = sorted({e.code for e in mismatches}, key=lambda c: c.value)
        return reasons, compiled.analysis.complexity

    def screen(
        self,
        result: ComputeResult,
        values: Array | None,
        market: Market,
        window: tuple[int, int],
    ) -> StageOutcome:
        """Coverage, the prefix-invariance probe, runtime limits and degeneracy on W1."""
        resources = {
            "cpu_seconds": result.cpu_seconds,
            "probe_cpu_seconds": result.probe_cpu_seconds,
            "peak_rss_bytes": result.peak_rss_bytes,
            "limit": result.limit,
        }
        if result.status == "dsl_error":
            code = ReasonCode(result.error_code or ReasonCode.PARSE_ERROR)
            return StageOutcome("screening", False, [code], {}, {"status": "FAIL"}, resources)
        if result.status == "runtime_limit" or values is None:
            return StageOutcome(
                "screening",
                False,
                [ReasonCode.RUNTIME_LIMIT],
                {},
                {"status": "FAIL", "limit": result.limit},
                resources,
            )
        first, last = window
        eligible = market.eligible[first : last + 1]
        finite = np.isfinite(values) & eligible
        eligible_counts = eligible.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            shares = finite.sum(axis=1) / eligible_counts
        coverage = _f(np.mean(shares[eligible_counts > 0])) if (eligible_counts > 0).any() else None
        degenerate = 0
        for row, mask in zip(values, finite, strict=True):
            sample = row[mask]
            if sample.size < 2 or not float(np.std(sample)) > 0:
                degenerate += 1
        degenerate_fraction = degenerate / max(1, values.shape[0])
        mismatches = sum(p.mismatches for p in result.probes)
        worst = max((p.max_abs_diff or 0.0 for p in result.probes), default=0.0)
        reasons = []
        if coverage is None or coverage < float(self.screening["coverage_min"]):
            reasons.append(ReasonCode.LOW_COVERAGE)
        if mismatches > 0:
            reasons.append(ReasonCode.LOOKAHEAD_DETECTED)
        if degenerate_fraction > float(self.screening["degenerate_date_fraction_max"]):
            reasons.append(ReasonCode.DEGENERATE)
        metrics = {
            "coverage": coverage,
            "degenerate_date_fraction": degenerate_fraction,
            "probe_cut_dates": float(len(result.probes)),
            "probe_mismatches": float(mismatches),
            "probe_max_abs_diff": _f(worst),
        }
        summary = {
            "status": "PASS" if not reasons else "FAIL",
            "reasons": [r.value for r in reasons],
            "probe_cuts": [p.cut.isoformat() for p in result.probes],
        }
        return StageOutcome("screening", not reasons, reasons, metrics, summary, resources)

    # W1 ------------------------------------------------------------------------------

    def run_w1(
        self,
        manifest: FactorManifest,
        factor: Array,
        market: Market,
        start: date,
        end: date,
        library_source: Mapping[str, Array],
        coverage: float | None,
        complexity: int,
    ) -> tuple[StageOutcome, FactorEvaluation]:
        sign = manifest.declared.expected_sign
        evaluation = evaluate_factor(
            factor,
            market,
            start,
            end,
            sign,
            self.settings,
            library_source,
            library_window_aligned=True,
        )
        m = evaluation.metrics
        backtest = run_backtest(
            sign * factor, market, start, end, BacktestSettings.from_protocol(self.protocol)
        )
        try:
            sharpe_daily, skew, kurt, n_obs = moments(evaluation.series.ls_net)
            ledger: dict[str, float | None] = {
                "sharpe_daily": sharpe_daily,
                "skew": skew,
                "kurt_raw": kurt,
                "n_obs": n_obs,
            }
        except ValueError:
            ledger = {
                "sharpe_daily": None,
                "skew": None,
                "kurt_raw": None,
                "n_obs": int(np.isfinite(evaluation.series.ls_net).sum()),
            }
        metrics: dict[str, float | None] = {
            "dates_evaluated": float(m.dates_evaluated),
            "ic_mean": m.ic_mean,
            "rankic_mean": m.rankic_mean,
            "rankic_std": m.rankic_std,
            "rankic_ir": m.rankic_ir,
            "rankic_t_nw": m.rankic_t_nw,
            "nw_lag": float(m.nw_lag),
            "hit_ratio": m.hit_ratio,
            "sign_consistency": float(m.sign_consistency),
            "ls_gross_mean": m.ls_gross_mean,
            "ls_gross_sharpe": m.ls_gross_sharpe,
            "ls_net_mean": m.ls_net_mean,
            "ls_net_sharpe": m.ls_net_sharpe,
            "top_turnover": m.top_turnover,
            "bottom_turnover": m.bottom_turnover,
            "monotonicity": m.monotonicity,
            "rank_autocorrelation": m.rank_autocorrelation,
            "coverage": m.coverage,
            "library_max_abs_correlation": m.library_correlation.max_abs,
            "size_neutral_rankic": m.size_neutral_rankic,
            "sharpe_daily": _f(ledger["sharpe_daily"]),
            "skew": _f(ledger["skew"]),
            "kurt_raw": _f(ledger["kurt_raw"]),
            "n_obs": float(ledger["n_obs"] or 0),
        }
        for horizon, value in m.decay.items():
            metrics[f"decay_h{horizon}"] = value
        for i, value in enumerate(m.quantile_returns, start=1):
            metrics[f"quantile_return_q{i}"] = value
        for year, value in m.yearly_rankic.items():
            metrics[f"yearly_rankic_{year}"] = value
        for name, value in backtest.metrics.model_dump().items():
            metrics[f"reference_{name}"] = _f(value)
        metrics = {k: _f(v) for k, v in sorted(metrics.items())}
        gates = self.w1_gates(metrics, sign, m.library_correlation.vacuous, coverage)
        passed = all(g["passed"] for g in gates)
        library = m.library_correlation
        summary = {
            "status": "PASS" if passed else "FAIL",
            "gates": gates,
            "sign": sign,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "library": {
                "vacuous": library.vacuous,
                "size": len(library_source),
                "argmax_version_id": library.argmax,
                "note": library.note,
            },
            "complexity": complexity,
        }
        raw = {
            "sign": sign,
            "rankic_mean": m.rankic_mean,
            "rankic_ir": m.rankic_ir,
            "rankic_t_nw": m.rankic_t_nw,
            "hit_ratio": m.hit_ratio,
            "decay": dict(m.decay),
            "ls_net_sharpe": m.ls_net_sharpe,
            "ls_gross_sharpe": m.ls_gross_sharpe,
            "monotonicity": m.monotonicity,
            "top_turnover": m.top_turnover,
            "rank_autocorrelation": m.rank_autocorrelation,
            "library_max_abs_correlation": library.max_abs,
            "library_argmax": library.argmax,
            "library_empty": library.vacuous,
            "yearly_rankic": dict(m.yearly_rankic),
            "coverage_passed": coverage is not None
            and coverage >= float(self.screening["coverage_min"]),
            "size_neutral_rankic": m.size_neutral_rankic,
            "complexity": complexity,
        }
        series = {
            "rankic": {
                "date": [d.isoformat() for d in evaluation.series.dates],
                "ic": evaluation.series.ic.tolist(),
                "rank_ic": evaluation.series.rank_ic.tolist(),
            },
            "ls_returns": {
                "date": [d.isoformat() for d in evaluation.series.dates],
                "ls": evaluation.series.ls.tolist(),
                "ls_net": evaluation.series.ls_net.tolist(),
                "top_turnover": evaluation.series.top_turnover.tolist(),
                "bottom_turnover": evaluation.series.bottom_turnover.tolist(),
            },
            "nav": {
                "date": [d.isoformat() for d in backtest.dates],
                "nav": backtest.nav.tolist(),
                "gross_return": backtest.gross_return.tolist(),
                "net_return": backtest.net_return.tolist(),
                "turnover": backtest.turnover.tolist(),
                "holdings": backtest.holdings.tolist(),
            },
        }
        outcome = StageOutcome(
            "w1", passed, [], metrics, summary, {}, raw | {"ledger": ledger}, series
        )
        return outcome, evaluation

    def w1_gates(
        self,
        metrics: dict[str, float | None],
        sign: int,
        library_vacuous: bool,
        coverage: float | None,
    ) -> list[dict[str, Any]]:
        """The public W1 factor gate (Section 8.8), each value sign-adjusted by s."""
        g = self.gates

        def adjusted(name: str) -> float | None:
            value = metrics.get(name)
            return None if value is None else sign * value

        def gate(
            name: str, value: float | None, threshold: float, above: bool = True
        ) -> dict[str, Any]:
            passed = value is not None and (value >= threshold if above else value <= threshold)
            return {
                "name": name,
                "passed": bool(passed),
                "value": value,
                "threshold": threshold,
                "skipped_reason": None,
            }

        gates = [
            gate("sign_consistency", metrics["sign_consistency"], float(g["sign"])),
            gate("rankic_mean", adjusted("rankic_mean"), float(g["rankic_min"])),
            gate("rankic_ir", adjusted("rankic_ir"), float(g["ir_min"])),
            gate("rankic_t_nw", adjusted("rankic_t_nw"), float(g["nw_t_min"])),
            gate("top_turnover", metrics["top_turnover"], float(g["turnover_max"]), above=False),
        ]
        if library_vacuous:
            gates.append(
                {
                    "name": "library_correlation",
                    "passed": True,
                    "value": None,
                    "threshold": float(g["library_correlation_max"]),
                    "skipped_reason": "the library is empty; the gate is vacuous",
                }
            )
        else:
            gates.append(
                gate(
                    "library_correlation",
                    metrics["library_max_abs_correlation"],
                    float(g["library_correlation_max"]),
                    above=False,
                )
            )
        gates.append(gate("coverage", coverage, float(self.screening["coverage_min"])))
        return gates

    # Release mapping -----------------------------------------------------------------

    def release_w1(self, raw: dict[str, Any], policy: dict[str, Any]) -> W1Content:
        """Whitelisted, rounded W1 fields and diagnostic flags (Section 9.2)."""
        r = policy["rounding"]
        flags_cfg = policy["flags"]
        sign = int(raw["sign"])
        rankic = raw["rankic_mean"] or 0.0
        t_value = raw["rankic_t_nw"]
        decay = {int(h): v for h, v in raw["decay"].items()}
        flags: set[DiagnosticFlag] = set()
        top = raw["top_turnover"]
        if top is not None and top > flags_cfg["high_turnover_above"]:
            flags.add(DiagnosticFlag.HIGH_TURNOVER)
        mono = raw["monotonicity"]
        if mono is None or mono < flags_cfg["low_monotonicity_below"]:
            flags.add(DiagnosticFlag.LOW_MONOTONICITY)
        if sign * rankic < 0:
            flags.add(DiagnosticFlag.SIGN_MISMATCH)
        library = raw["library_max_abs_correlation"]
        if library is not None and library > flags_cfg["crowded_library_correlation_above"]:
            flags.add(DiagnosticFlag.CROWDED_WITH_LIBRARY)
        yearly = [v for v in raw["yearly_rankic"].values() if v]
        if any(v > 0 for v in yearly) and any(v < 0 for v in yearly):
            flags.add(DiagnosticFlag.UNSTABLE_YEARLY)
        h1, h5 = decay.get(1), decay.get(5)
        if h1 is not None and h5 is not None and sign * h1 > 0:
            if sign * h5 < flags_cfg["decays_fast_h5_over_h1_below"] * sign * h1:
                flags.add(DiagnosticFlag.DECAYS_FAST)
        if not raw["coverage_passed"]:
            flags.add(DiagnosticFlag.LOW_COVERAGE)
        if (
            sign * rankic < flags_cfg["weak_signal_rankic_below"]
            or t_value is None
            or sign * t_value < flags_cfg["weak_signal_nw_t_below"]
        ):
            flags.add(DiagnosticFlag.WEAK_SIGNAL)
        gross, net = raw["ls_gross_sharpe"], raw["ls_net_sharpe"]
        if gross is not None and net is not None and gross > 0:
            if net < flags_cfg["cost_dominated_net_over_gross_below"] * gross:
                flags.add(DiagnosticFlag.COST_DOMINATED)
        return W1Content(
            type="w1",
            rankic_mean=quantize(rankic, r["rankic"]),
            rankic_ir=quantize(raw["rankic_ir"] or 0.0, r["ir"]),
            nw_t_bucket=t_bucket(None if t_value is None else sign * t_value, policy["t_buckets"]),
            hit_ratio=clamp(quantize(raw["hit_ratio"] or 0.0, r["shares"]), 0.0, 1.0),
            decay_profile={
                cast(HorizonKey, str(h)): quantize(v or 0.0, r["rankic"])
                for h, v in sorted(decay.items())
            },
            ls_net_sharpe=quantize(net or 0.0, r["sharpe"]),
            monotonicity=clamp(quantize(mono or 0.0, r["correlations"]), -1.0, 1.0),
            top_turnover=clamp(quantize(top or 0.0, r["shares"]), 0.0, 1.0),
            rank_autocorrelation=clamp(
                quantize(raw["rank_autocorrelation"] or 0.0, r["correlations"]), -1.0, 1.0
            ),
            max_library_correlation=None
            if library is None
            else clamp(quantize(library, r["correlations"]), 0.0, 1.0),
            library_version_id=raw["library_argmax"],
            library_empty=bool(raw["library_empty"]),
            yearly_rankic={
                year: quantize(v or 0.0, r["rankic"])
                for year, v in sorted(raw["yearly_rankic"].items())
            },
            coverage_bucket="PASS" if raw["coverage_passed"] else "FAIL",
            size_neutral_rankic=None
            if raw["size_neutral_rankic"] is None
            else quantize(raw["size_neutral_rankic"], r["rankic"]),
            complexity=int(raw["complexity"]),
            flags=sorted(flags, key=lambda f: f.value),
        )


def quantize(value: float, step: float) -> float:
    """Round half away from zero to a multiple of step (Section 9.2), in decimal arithmetic
    on the shortest repr, so 0.0125 at step 0.005 is 0.015 and not 0.01."""
    if not math.isfinite(value):
        raise ValueError("only finite values are released")
    size = Decimal(repr(step))
    units = (Decimal(repr(value)) / size).to_integral_value(rounding=ROUND_HALF_UP)
    return float(units * size) if units else 0.0


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def t_bucket(
    value: float | None, edges: list[float]
) -> Literal["below_1", "1_to_2", "2_to_3", "above_3"]:
    labels: list[Literal["below_1", "1_to_2", "2_to_3", "above_3"]] = [
        "below_1",
        "1_to_2",
        "2_to_3",
        "above_3",
    ]
    if value is None:
        return "below_1"
    index = sum(1 for edge in edges if value >= edge)
    return labels[min(index, len(labels) - 1)]


def released_value_count(content: W1Content) -> int:
    """Numeric values a W1 report releases, for burn accounting (Section 9.4)."""
    count = 6  # rankic_mean, rankic_ir, hit_ratio, ls_net_sharpe, monotonicity, top_turnover
    count += 1  # rank_autocorrelation
    count += len(content.decay_profile) + len(content.yearly_rankic)
    count += content.max_library_correlation is not None
    count += content.size_neutral_rankic is not None
    return count
