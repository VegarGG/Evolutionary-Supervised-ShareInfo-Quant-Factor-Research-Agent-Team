"""Run only inside the documented isolated oracle container, with original files read-only.

The package verifies all 24 business CSVs before the diagnostic panel is saved.
No old runtime is imported by QFR. Output is licensed task-local evidence, not a fixture to commit.
"""

import runpy
import sys


def main():
    captured = []

    def observe(frame, event, result):
        if (
            event == "return"
            and frame.f_code.co_name == "add_price_features"
            and frame.f_code.co_filename == "/bundle/runtime/research_v4/features.py"
        ):
            captured.append(result.copy(deep=True))

    model = sys.argv[1]
    if model not in {"P0", "P1"}:
        raise ValueError("original P0 or P1 package required")
    sys.argv = [f"/bundle/run_{model.lower()}.py", "run", "--output", "/out/replay"]
    sys.setprofile(observe)
    try:
        runpy.run_path(sys.argv[0], run_name="__main__")
    finally:
        sys.setprofile(None)
    if model == "P1":
        if len(captured) != 1:
            raise RuntimeError("Expected exactly one original price-feature computation")
        captured[0].to_csv("/out/replay/captured_panel.csv.gz", index=False)


if __name__ == "__main__":
    main()
