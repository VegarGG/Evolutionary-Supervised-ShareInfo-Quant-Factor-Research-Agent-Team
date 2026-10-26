"""Full-size Stage 1 calibration gate through the independently implemented DSL/metrics."""

import json
from pathlib import Path

from qfr_core.data_layer.synthetic import SyntheticConfig, generate
from qfr_core.dsl.language import DSLConfig
from qfr_core.dsl.operators import evaluate
from qfr_core.metrics.core import MetricConfig, stock_metrics


def main():
    config = SyntheticConfig.load(Path("configs/data/synthetic.json"))
    print(f"Generating planted world: {config.instruments} names x {config.days} days", flush=True)
    world = generate(config, "planted")
    dsl = DSLConfig.load(Path("configs/dsl/stock_daily_v1.json"))
    metrics = MetricConfig.model_validate_json(
        Path("configs/metrics/stock_daily_v1.json").read_bytes()
    )
    panel = world.panel
    results = []
    for i, expression in enumerate(world.ground_truth["signals"][:2]):
        scores = evaluate(expression, panel, dsl)
        result = stock_metrics(
            panel, scores, metrics, start=panel["date"].min(), end=panel["date"].max()
        )
        actual = result.summary["RankIC_mean"].value
        target = config.target_rankic[i]
        passed = actual is not None and abs(actual - target) <= 0.005
        evidence = {
            "signal": f"A{i + 1}",
            "expression": expression,
            "RankIC": actual,
            "target": target,
            "tolerance": 0.005,
            "status": "PASS" if passed else "FAIL",
        }
        print(json.dumps(evidence), flush=True)
        results.append(evidence)
        if not passed:
            raise SystemExit("Stage 1 synthetic RankIC gate failed")
    output = Path(".local/stage-1/synthetic-gate.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "config": config.model_dump(mode="json"),
                "ground_truth": world.ground_truth,
                "results": results,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
