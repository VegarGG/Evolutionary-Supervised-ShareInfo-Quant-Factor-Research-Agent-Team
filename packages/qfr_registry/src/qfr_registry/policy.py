"""Versioned publication resource controls, independent of financial admission gates."""

from pydantic import PositiveInt
from qfr_core.contracts.base import Contract, Text


class RegistryPolicy(Contract):
    revision: PositiveInt
    max_request_bytes: PositiveInt
    max_file_bytes: PositiveInt
    max_total_payload_bytes: PositiveInt
    max_payload_files: PositiveInt
    max_archive_members: PositiveInt
    max_archive_expanded_bytes: PositiveInt
    max_compression_ratio: PositiveInt
    allowed_runners: list[Text]


class RegistryReadPolicy(Contract):
    revision: PositiveInt
    max_page_size: PositiveInt
    max_page_bytes: PositiveInt
    max_lineage_depth: PositiveInt
    max_lineage_nodes: PositiveInt
    max_lineage_edges: PositiveInt
