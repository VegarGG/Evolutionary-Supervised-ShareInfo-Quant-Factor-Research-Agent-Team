"""QFR command router; deployment startup still admits no work."""

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "eval-admin":
        from qfr_eval.admin.cli import main as admin

        admin(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "eval":
        from qfr_eval.runtime_bootstrap import bootstrap_cli
        from qfr_eval.runtime_contracts import RuntimeCompatibilityError

        try:
            bootstrap_cli(sys.argv[2:])
        except RuntimeCompatibilityError as error:
            raise SystemExit("reproduction refused: " + error.reason) from None
        from qfr_eval.reproduce import main as evaluate

        evaluate(sys.argv[2:])
    else:
        from qfr_eval.ingest.cli import main as ingest

        ingest()
