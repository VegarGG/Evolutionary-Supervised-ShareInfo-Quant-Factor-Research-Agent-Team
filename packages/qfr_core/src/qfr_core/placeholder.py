"""P0.3 service placeholder: boundary check, log lifecycle, exit zero."""

import sys

from qfr_core.config import RuntimeSettings, load_config, logging_config
from qfr_core.correlation import bind
from qfr_core.logging import JsonLogger


def main() -> None:
    settings = RuntimeSettings()
    logger = JsonLogger(
        settings.service, settings.zone, settings.log_dir, logging_config(settings.config_dir)
    )
    with bind(principal="phase0_placeholder"):
        logger.logger.info(
            "service_started",
            payload={
                "implementation": "phase0_placeholder",
                "configuration_digest": load_config("logging", settings.config_dir).sha256,
            },
        )
        logger.logger.info(
            "service_stopped", outcome="skipped", payload={"reason": "not_implemented_in_phase_0"}
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
