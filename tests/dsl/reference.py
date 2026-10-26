"""Slow scalar-loop references, independent of the Polars operator kernels."""

import math
import statistics as stats

from qfr_core.dsl.language import CROSS, TIME_BINARY, TIME_UNARY


def average_rank(value, sample):
    return (sum(x < value for x in sample) + (sum(x == value for x in sample) + 1) / 2) / len(
        sample
    )


def covariance(x, y):
    return sum((a - stats.mean(x)) * (b - stats.mean(y)) for a, b in zip(x, y, strict=True)) / (
        len(x) - 1
    )


def rolling(name, values, other, distance, minimum, eps):
    valid = [x for x in values if x is not None]
    if name in {"Corr", "Cov"}:
        pairs = [
            (x, y) for x, y in zip(values, other, strict=True) if x is not None and y is not None
        ]
        if len(pairs) < max(2, minimum):
            return None
        x, y = map(list, zip(*pairs, strict=True))
        cov = covariance(x, y)
        denominator = stats.stdev(x) * stats.stdev(y)
        return cov if name == "Cov" else cov / denominator if denominator > eps else None
    if len(valid) < minimum:
        return None
    if name == "Mean":
        return stats.mean(valid)
    if name == "Sum":
        return sum(valid)
    if name == "Min":
        return min(valid)
    if name == "Max":
        return max(valid)
    if name == "Med":
        return stats.median(valid)
    if name in {"Std", "Var"}:
        return (
            (stats.stdev(valid) if name == "Std" else stats.variance(valid))
            if len(valid) > 1
            else None
        )
    if name == "WMA":
        weighted = [
            (distance - len(values) + i + 1, x) for i, x in enumerate(values) if x is not None
        ]
        return sum(w * x for w, x in weighted) / sum(w for w, _ in weighted)
    if name == "TsRank":
        return average_rank(values[-1], valid) if values[-1] is not None else None
    if name == "TsZ":
        sd = stats.stdev(valid) if len(valid) > 1 else 0
        return (
            (values[-1] - stats.mean(valid)) / sd if values[-1] is not None and sd >= eps else None
        )
    if name in {"ArgMax", "ArgMin"}:
        goal = max(valid) if name == "ArgMax" else min(valid)
        return next(i for i, x in enumerate(reversed(values)) if x == goal)
    if name in {"Skew", "Kurt"}:
        n, mean = len(valid), stats.mean(valid)
        if n < (3 if name == "Skew" else 4):
            return None
        m2 = sum((x - mean) ** 2 for x in valid) / n
        if m2 < eps:
            return None
        if name == "Skew":
            m3 = sum((x - mean) ** 3 for x in valid) / n
            return math.sqrt(n * (n - 1)) / (n - 2) * m3 / m2**1.5
        m4 = sum((x - mean) ** 4 for x in valid) / n
        return (n - 1) / ((n - 2) * (n - 3)) * ((n + 1) * (m4 / m2**2 - 3) + 6)
    if name in {"Slope", "Rsq", "Resi"}:
        if len(valid) < 2:
            return None
        times = [i for i, x in enumerate(values) if x is not None]
        slope = covariance(times, valid) / stats.variance(times)
        intercept = stats.mean(valid) - slope * stats.mean(times)
        if name == "Slope":
            return slope
        if name == "Resi":
            return (
                values[-1] - intercept - slope * (len(values) - 1)
                if values[-1] is not None
                else None
            )
        total = sum((v - stats.mean(valid)) ** 2 for v in valid)
        error = sum((v - intercept - slope * t) ** 2 for t, v in zip(times, valid, strict=True))
        return 1 - error / total if total >= eps else None
    raise AssertionError(name)


def reference(node, frame, config, eligible=None):
    rows = frame.sort("instrument", "date").to_dicts()
    by_name, by_date = {}, {}
    for i, row in enumerate(rows):
        by_name.setdefault(row["instrument"], []).append(i)
        by_date.setdefault(row["date"], []).append(i)
    eps = config.zero_epsilon

    def calculate(item):
        if item.op == "field":
            field = "ret_1d" if item.value == "$ret" else item.value[1:]
            return [row[field] for row in rows]
        if item.op == "number":
            return [float(item.value)] * len(rows)
        timed = item.op in TIME_UNARY | TIME_BINARY
        args = [calculate(child) for child in (item.args[:-1] if timed else item.args)]
        result = [None] * len(rows)
        if timed:
            d = int(item.args[-1].value)
            minimum = (
                d if d < config.full_window_below else math.ceil(config.rolling_valid_fraction * d)
            )
            for indices in by_name.values():
                history, other = [], []
                ema, weight, count = None, 1.0, 0
                alpha = 2 / (d + 1)
                for i in indices:
                    current = args[0][i]
                    history.append(current)
                    if len(args) > 1:
                        other.append(args[1][i])
                    if item.op in {"Ref", "Delta", "Pct"}:
                        old = history[-d - 1] if len(history) > d else None
                        if item.op == "Ref":
                            result[i] = old
                        elif old is not None and current is not None:
                            result[i] = (
                                current - old
                                if item.op == "Delta"
                                else current / old - 1
                                if abs(old) >= eps
                                else None
                            )
                    elif item.op == "EMA":
                        if ema is not None:
                            weight *= 1 - alpha
                            if current is not None:
                                ema = (weight * ema + alpha * current) / (weight + alpha)
                                weight = 1
                        elif current is not None:
                            ema = current
                        count += current is not None
                        if (
                            count >= d
                            and current is not None
                            and sum(x is not None for x in history[-d:]) >= minimum
                        ):
                            result[i] = ema
                    else:
                        result[i] = rolling(item.op, history[-d:], other[-d:], d, minimum, eps)
            return result
        if item.op in CROSS:
            for indices in by_date.values():
                valid = [
                    i
                    for i in indices
                    if args[0][i] is not None and (eligible is None or rows[i][eligible])
                ]
                sample = [args[0][i] for i in valid]
                if not sample:
                    continue
                if item.op == "Neutralize":
                    valid = [
                        i for i in valid if rows[i]["adv20"] is not None and rows[i]["adv20"] > 0
                    ]
                    if len(valid) < 2:
                        continue
                    x, y = [math.log(rows[i]["adv20"]) for i in valid], [args[0][i] for i in valid]
                    if stats.variance(x) < eps:
                        continue
                    slope = covariance(x, y) / stats.variance(x)
                    for i, a, b in zip(valid, x, y, strict=True):
                        result[i] = b - stats.mean(y) - slope * (a - stats.mean(x))
                    continue
                for i in valid:
                    x = args[0][i]
                    if item.op == "Rank":
                        result[i] = average_rank(x, sample)
                    if item.op == "Demean":
                        result[i] = x - stats.mean(sample)
                    if item.op == "Zscore" and len(sample) > 1 and stats.stdev(sample) >= eps:
                        result[i] = (x - stats.mean(sample)) / stats.stdev(sample)
                    if item.op == "Scale" and sum(abs(v) for v in sample) >= eps:
                        result[i] = x / sum(abs(v) for v in sample)
            return result
        for i in range(len(rows)):
            values = [arg[i] for arg in args]
            if item.op == "If":
                result[i] = values[1] if values[0] else values[2] if values[0] is not None else None
                continue
            if any(x is None for x in values):
                continue
            result[i] = element(item.op, values, eps)
        return result

    return calculate(node)


def element(name, values, eps):
    x = values[0]
    y = values[1] if len(values) > 1 else None
    operations = {
        "neg": lambda: -x,
        "+": lambda: x + y,
        "-": lambda: x - y,
        "*": lambda: x * y,
        "/": lambda: x / y if abs(y) >= eps else None,
        ">": lambda: float(x > y),
        "<": lambda: float(x < y),
        ">=": lambda: float(x >= y),
        "<=": lambda: float(x <= y),
        "Abs": lambda: abs(x),
        "Sign": lambda: float((x > 0) - (x < 0)),
        "Log": lambda: math.log(x) if x > 0 else None,
        "Sqrt": lambda: math.sqrt(x) if x >= 0 else None,
        "SignedPower": lambda: math.copysign(abs(x) ** y, x),
        "Max2": lambda: max(values),
        "Min2": lambda: min(values),
        "Clip": lambda: min(max(x, y), values[2]),
    }
    return operations[name]()
