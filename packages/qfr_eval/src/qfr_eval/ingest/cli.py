"""qfr data build: explicit local ingestion, without starting any research/evaluation job."""

import argparse
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import cast

import polars as pl
from qfr_core.contracts.data import ExposureAndQuality, QualityLabels
from qfr_core.contracts.enums import PITGrade
from qfr_core.data_layer.pilot import PilotConfig, import_pilot
from qfr_core.data_layer.qlib import StockImportConfig, extract_release, read_qlib
from qfr_core.data_layer.snapshots import TableInput, canonical_json
from qfr_core.data_layer.synthetic import SyntheticConfig, generate

from qfr_eval.ingest.build import build_zones


def _quality(synthetic: bool) -> QualityLabels:
    return QualityLabels(
        timing_grade=PITGrade.A,
        timing_basis="Explicit observation dates",
        vintage_status="verified" if synthetic else "unknown",
        vintage_notes="Synthetic generated data" if synthetic else "Release vintages unverified",
        membership_grade=PITGrade.A if synthetic else PITGrade.D,
        membership_status="point_in_time" if synthetic else "unknown",
        membership_notes="Synthetic intervals"
        if synthetic
        else "Source intervals; historical vintages unverified",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    data = sub.add_parser("data").add_subparsers(dest="action", required=True)
    build = data.add_parser("build")
    build.add_argument("--source", choices=["synthetic", "cn", "pilot"], required=True)
    build.add_argument("--config", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--cutoff", type=date.fromisoformat, required=True)
    build.add_argument("--principal", required=True)
    build.add_argument("--request-id", required=True)
    build.add_argument("--build-code-version", required=True)
    build.add_argument("--world", choices=["planted", "null", "decay"])
    build.add_argument("--package", type=Path)
    build.add_argument("--fixtures", type=Path)
    build.add_argument("--archive", type=Path)
    build.add_argument("--archive-sha256")
    build.add_argument("--release-tag")
    build.add_argument("--authorization-ref")
    build.add_argument("--qlib-subdir", default=".")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="qfr-ingest-") as temporary:
        if args.source == "pilot":
            if args.package is None or args.fixtures is None:
                parser.error("pilot requires --package and --fixtures")
            cfg = PilotConfig.model_validate_json(args.config.read_bytes())
            result = import_pilot(args.package, args.fixtures, cfg)
            tables, exposure = result.tables, result.exposure
            profile = "pilot_industry_v1"
            conventions = {
                "exposure": "previously_seen",
                "new_supplier_requests": "0",
                "financial_availability": json.dumps(cfg.fundamental_availability, sort_keys=True),
                "vintage": cfg.vintage_note,
                "membership": cfg.membership_note,
            }
        else:
            synthetic = args.source == "synthetic"
            quality = _quality(synthetic)
            exposure = ExposureAndQuality(
                history="previously_seen",
                inspected_periods=[],
                training_tuning_history="Imported for local research",
                provider_knowledge_exposure="unknown",
                quality=quality,
                licence_constraints=[
                    "Synthetic" if synthetic else "Operator-authorized source release"
                ],
                unknowns=[] if synthetic else ["Historical value and membership vintages"],
            )
            private = []
            if synthetic:
                if args.world is None:
                    parser.error("synthetic requires an explicit --world")
                world = generate(SyntheticConfig.load(args.config), args.world)
                panel, calendar, membership = world.panel, world.calendar, world.membership
                conventions = {"source": "synthetic", "timing": str(world.ground_truth["timing"])}
                private = [
                    TableInput(
                        "ground_truth",
                        pl.DataFrame(
                            {
                                "id": ["truth"],
                                "payload": [canonical_json(world.ground_truth).decode()],
                            }
                        ),
                        ("id",),
                        quality,
                        "Synthetic",
                        None,
                        None,
                        research_visible=False,
                    )
                ]
            else:
                if not all(
                    [args.archive, args.archive_sha256, args.release_tag, args.authorization_ref]
                ):
                    parser.error(
                        "cn requires --archive, --archive-sha256, --release-tag "
                        "and --authorization-ref"
                    )
                cfg_cn = StockImportConfig.model_validate_json(args.config.read_bytes())
                extracted = extract_release(
                    args.archive,
                    args.archive_sha256,
                    Path(temporary) / "release",
                    cfg_cn,
                    authorization_ref=args.authorization_ref,
                )
                import_root = (extracted / args.qlib_subdir).resolve()
                if not import_root.is_relative_to(extracted.resolve()):
                    parser.error("qlib subdirectory escapes verified archive")
                stock = read_qlib(
                    import_root,
                    cfg_cn,
                    authorization_ref=args.authorization_ref,
                    release_tag=args.release_tag,
                    archive_sha256=args.archive_sha256,
                )
                panel, calendar = stock.panel, stock.calendar
                membership = panel.select(
                    "date", "instrument", *[f"in_{u}" for u in cfg_cn.universes]
                )
                conventions = stock.conventions
                private = [
                    TableInput(
                        "benchmark",
                        stock.benchmark,
                        ("date",),
                        quality,
                        "Authorized stock release",
                        research_visible=False,
                    )
                ]
            profile = "stock_daily_v1"
            tables = [
                TableInput("panel", panel, ("instrument", "date"), quality, "Authorized source"),
                TableInput("calendar", calendar, ("date",), quality, "Authorized source"),
                TableInput(
                    "membership", membership, ("instrument", "date"), quality, "Authorized source"
                ),
                *private,
            ]
        as_of = max(
            cast(date, table.frame[column].max())
            for table in tables
            for column in [table.date_column, table.available_date_column]
            if column and table.frame[column].len() and table.frame[column].max() is not None
        )
        research, full = build_zones(
            args.output,
            tables,
            cutoff=args.cutoff,
            as_of=as_of,
            profile=profile,
            source=args.source,
            build_code_version=args.build_code_version,
            exposure=exposure,
            conventions=conventions,
            principal=args.principal,
            request_id=args.request_id,
            release_tag=args.release_tag,
            archive_sha256=args.archive_sha256,
        )
    print(
        json.dumps(
            {
                "research": str(research.path),
                "full": str(full.path),
                "research_snapshot_id": research.manifest.snapshot_id,
                "full_snapshot_id": full.manifest.snapshot_id,
            }
        )
    )


if __name__ == "__main__":
    main()
