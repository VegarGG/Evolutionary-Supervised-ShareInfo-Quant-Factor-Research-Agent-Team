"""Human publication via the same authenticated HTTP boundary as every writer."""

import argparse
import os
from pathlib import Path

from pydantic import ValidationError
from qfr_core.contracts.publication import PublicationRequest, RegistryClientConfiguration
from qfr_core.registry_client import RegistryClient, RegistryTransportError


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish a prepared immutable artifact over HTTP")
    parser.add_argument("request", type=Path)
    parser.add_argument("--client-config", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = RegistryClientConfiguration.model_validate_json(args.client_config.read_bytes())
        with args.request.open("rb") as source:
            content = source.read(config.max_request_bytes + 1)
        if len(content) > config.max_request_bytes:
            raise ValueError("request file exceeds limit")
        request = PublicationRequest.model_validate_json(content)
        response = RegistryClient.from_environment(config, os.environ).publish(request)
    except (OSError, ValidationError, ValueError, RegistryTransportError):
        parser.exit(
            1,
            "Publication failed; check local declarations, authorization and registry readiness.\n",
        )
    print(response.model_dump_json())


if __name__ == "__main__":
    main()
