"""Naive loop-based reference implementations of every qfr-dsl/1 operator (tests only).

These restate PLAN Section 7.3 independently of qfr_core.operators: plain Python loops
over each instrument's rows and each date's cross-section, using the statistics module
and SciPy instead of the production kernels.
"""

import math
import statistics

import numpy as np
import polars as pl
from qfr_core.dsl.ast import BinOp, Call, Compare, Field, Neg, Node, Num, Window
from scipy import stats

EPS = 1e-12
FIELD_COLUMNS = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "vwap": "vwap",
    "volume": "volume",
    "amount": "amount",
    "ret": "ret_1d",
    "adv20": "adv20",
    "close_raw": "close_raw",
}


def required(days: int) -> int:
    return days if days < 5 else math.ceil(0.8 * days)


def finite(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def divide(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or abs(b) < EPS:
        return None
    return finite(a / b)


class Reference:
    def __init__(self, panel: pl.DataFrame, universe: str, listed_min: int, cs_min: int):
        self.panel = panel
        self.rows = panel.height
        instruments = panel["instrument"].to_list()
        dates = panel["date"].to_list()
        self.groups: dict[str, list[int]] = {}
        self.dates: dict[object, list[int]] = {}
        for i, (inst, day) in enumerate(zip(instruments, dates, strict=True)):
            self.groups.setdefault(inst, []).append(i)
            self.dates.setdefault(day, []).append(i)
        universe_flags = panel[f"in_{universe}"].to_list()
        listed = panel["listed_days"].to_list()
        suspended = panel["is_suspended"].to_list()
        self.eligible = [
            bool(u) and lst >= listed_min and not s
            for u, lst, s in zip(universe_flags, listed, suspended, strict=True)
        ]
        self.cs_min = cs_min

    def column(self, name: str) -> list[float | None]:
        return [finite(v) for v in self.panel[name].to_list()]

    def evaluate(self, node: Node) -> list[float | None]:
        if isinstance(node, Num):
            return [node.value] * self.rows
        if isinstance(node, Field):
            return self.column(FIELD_COLUMNS[node.name])
        if isinstance(node, Neg):
            return [None if v is None else finite(-v) for v in self.evaluate(node.operand)]
        if isinstance(node, BinOp):
            a, b = self.evaluate(node.left), self.evaluate(node.right)
            out: list[float | None] = []
            for x, y in zip(a, b, strict=True):
                if x is None or y is None:
                    out.append(None)
                elif node.op == "+":
                    out.append(finite(x + y))
                elif node.op == "-":
                    out.append(finite(x - y))
                elif node.op == "*":
                    out.append(finite(x * y))
                else:
                    out.append(divide(x, y))
            return out
        if isinstance(node, Compare):
            a, b = self.evaluate(node.left), self.evaluate(node.right)
            ops = {
                ">": lambda p, q: p > q,
                "<": lambda p, q: p < q,
                ">=": lambda p, q: p >= q,
                "<=": lambda p, q: p <= q,
            }
            return [
                None if x is None or y is None else float(ops[node.op](x, y))
                for x, y in zip(a, b, strict=True)
            ]
        assert isinstance(node, Call)
        return self.call(node)

    def call(self, node: Call) -> list[float | None]:
        name = node.name
        if name in {"Corr", "Cov"}:
            a, b = self.evaluate(node.args[0]), self.evaluate(node.args[1])
            window = node.args[2]
            assert isinstance(window, Window)
            return self.pair(name, a, b, window.days)
        if isinstance(node.args[-1], Window):
            window = node.args[-1]
            return self.time_series(name, self.evaluate(node.args[0]), window.days)
        if name in {"Rank", "Zscore", "Demean", "Scale", "Neutralize"}:
            return self.cross_section(name, self.evaluate(node.args[0]))
        args = [self.evaluate(a) for a in node.args]
        return self.elementwise(name, node, args)

    def windows(self, values: list[float | None], days: int):
        for rows in self.groups.values():
            for k, row in enumerate(rows):
                positions = [rows[j] if j >= 0 else None for j in range(k - days + 1, k + 1)]
                yield row, k, rows, positions

    def time_series(self, name: str, x: list[float | None], days: int) -> list[float | None]:
        out: list[float | None] = [None] * self.rows
        need = required(days)
        if name == "EMA":
            alpha = 2.0 / (days + 1)
            for rows in self.groups.values():
                state, count = None, 0
                for row in rows:
                    value = x[row]
                    if value is None:
                        continue
                    state = value if state is None else alpha * value + (1 - alpha) * state
                    count += 1
                    if count >= days:
                        out[row] = finite(state)
            return out
        for row, k, rows, positions in self.windows(x, days):
            if name in {"Ref", "Delta", "Pct"}:
                past = x[rows[k - days]] if k - days >= 0 else None
                current = x[row]
                if name == "Ref":
                    out[row] = past
                elif current is not None and past is not None:
                    out[row] = finite(current - past) if name == "Delta" else None
                    if name == "Pct":
                        ratio = divide(current, past)
                        out[row] = None if ratio is None else finite(ratio - 1)
                continue
            points = [(j, x[p]) for j, p in enumerate(positions) if p is not None]
            points = [(j, v) for j, v in points if v is not None]
            values = [v for _, v in points]
            n = len(values)
            current = x[row]
            if n < need:
                continue
            if name == "Mean":
                out[row] = finite(sum(values) / n)
            elif name == "Sum":
                out[row] = finite(math.fsum(values))
            elif name in {"Std", "Var"} and n >= 2:
                var = statistics.variance(values)
                out[row] = finite(var if name == "Var" else math.sqrt(var))
            elif name == "Min":
                out[row] = min(values)
            elif name == "Max":
                out[row] = max(values)
            elif name == "Med":
                out[row] = float(statistics.median(values))
            elif name == "WMA":
                weights = [j + 1 for j, _ in points]
                weighted = sum(w * v for w, v in zip(weights, values, strict=True))
                out[row] = finite(weighted / sum(weights))
            elif name == "TsRank" and current is not None:
                less = sum(v < current for v in values)
                equal = sum(v == current for v in values)
                rank = less + (equal + 1) / 2
                out[row] = divide(rank - 1, n - 1)
            elif name == "TsZ" and current is not None and n >= 2:
                out[row] = divide(current - statistics.fmean(values), statistics.stdev(values))
            elif name in {"ArgMax", "ArgMin"}:
                target = max(values) if name == "ArgMax" else min(values)
                latest = max(j for j, v in points if v == target)
                out[row] = float(days - 1 - latest)
            elif name in {"Slope", "Rsq", "Resi"} and n >= (2 if name == "Slope" else 3):
                taus = [float(j) for j, _ in points]
                slope, intercept = statistics.linear_regression(taus, values)
                if name == "Slope":
                    out[row] = finite(slope)
                elif name == "Rsq":
                    mean = statistics.fmean(values)
                    sst = sum((v - mean) ** 2 for v in values)
                    sse = sum(
                        (v - intercept - slope * t) ** 2 for t, v in zip(taus, values, strict=True)
                    )
                    out[row] = None if sst < EPS else finite(1 - sse / sst)
                elif current is not None:
                    out[row] = finite(current - (intercept + slope * (days - 1)))
            elif name in {"Skew", "Kurt"} and n >= (3 if name == "Skew" else 4):
                array = np.array(values)
                if np.sqrt(np.mean((array - array.mean()) ** 2)) < EPS:
                    continue
                if name == "Skew":
                    out[row] = finite(float(stats.skew(array, bias=False)))
                else:
                    out[row] = finite(float(stats.kurtosis(array, fisher=True, bias=False)))
        return out

    def pair(
        self, name: str, a: list[float | None], b: list[float | None], days: int
    ) -> list[float | None]:
        out: list[float | None] = [None] * self.rows
        need = max(required(days), 2)
        for row, _, _, positions in self.windows(a, days):
            pairs = [
                (a[p], b[p])
                for p in positions
                if p is not None and a[p] is not None and b[p] is not None
            ]
            if len(pairs) < need:
                continue
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            covariance = statistics.covariance(xs, ys)
            if name == "Cov":
                out[row] = finite(covariance)
            else:
                out[row] = divide(covariance, statistics.stdev(xs) * statistics.stdev(ys))
        return out

    def cross_section(self, name: str, x: list[float | None]) -> list[float | None]:
        out: list[float | None] = [None] * self.rows
        adv = self.column("adv20")
        for rows in self.dates.values():
            members = [r for r in rows if self.eligible[r] and x[r] is not None]
            if name == "Neutralize":
                members = [r for r in members if adv[r] is not None and adv[r] > 0]
            if len(members) < self.cs_min:
                continue
            values = [x[r] for r in members]
            n = len(values)
            if name == "Rank":
                for r, v in zip(members, values, strict=True):
                    less = sum(w < v for w in values)
                    equal = sum(w == v for w in values)
                    out[r] = divide(less + (equal + 1) / 2 - 1, n - 1)
            elif name in {"Zscore", "Demean"}:
                mean = statistics.fmean(values)
                spread = statistics.stdev(values)
                for r, v in zip(members, values, strict=True):
                    out[r] = finite(v - mean) if name == "Demean" else divide(v - mean, spread)
            elif name == "Scale":
                total = sum(abs(v) for v in values)
                for r, v in zip(members, values, strict=True):
                    out[r] = divide(v, total)
            else:
                u = [math.log(adv[r]) for r in members]
                u_mean, x_mean = statistics.fmean(u), statistics.fmean(values)
                suu = sum((p - u_mean) ** 2 for p in u)
                sux = sum((p - u_mean) * (q - x_mean) for p, q in zip(u, values, strict=True))
                beta = divide(sux, suu)
                for r, p, q in zip(members, u, values, strict=True):
                    out[r] = None if beta is None else finite(q - x_mean - beta * (p - u_mean))
        return out

    def elementwise(
        self, name: str, node: Call, args: list[list[float | None]]
    ) -> list[float | None]:
        out: list[float | None] = []
        for i in range(self.rows):
            values = [a[i] for a in args]
            x = values[0]
            if name == "If":
                if x is None:
                    out.append(None)
                else:
                    out.append(values[1] if x != 0 else values[2])
                continue
            if any(v is None for v in values):
                out.append(None)
                continue
            assert x is not None
            if name == "Abs":
                out.append(abs(x))
            elif name == "Sign":
                out.append(float((x > 0) - (x < 0)))
            elif name == "Log":
                out.append(math.log(x) if x > 0 else None)
            elif name == "Sqrt":
                out.append(math.sqrt(x) if x >= 0 else None)
            elif name == "SignedPower":
                out.append(finite(math.copysign(abs(x) ** values[1], x) if x else 0.0))
            elif name == "Clip":
                out.append(min(max(x, values[1]), values[2]))
            elif name == "Max2":
                out.append(max(x, values[1]))
            elif name == "Min2":
                out.append(min(x, values[1]))
        return out


def assert_matches(actual: list[float | None], expected: list[float | None], label: str) -> None:
    assert len(actual) == len(expected)
    for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
        if a is None or e is None:
            assert a is None and e is None, f"{label}: row {i} null mismatch {a} vs {e}"
        else:
            # Inputs reach 3e9 ($amount), so differences carry ~1e-6 absolute rounding.
            assert abs(a - e) <= 1e-9 * abs(e) + 1e-6, f"{label}: row {i} {a} vs {e}"
