"""Read-only RiceQuant research tools; credentials never enter tool arguments."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from qfh.evidence import EvidenceStore, Query, SourceRecord

SHANGHAI = ZoneInfo("Asia/Shanghai")


class DataUnavailable(RuntimeError):
    """Missing credentials, entitlement, module or data; no synthetic fallback."""


class RiceQuantTools:
    def __init__(
        self,
        client,
        store: EvidenceStore,
        cutoff: datetime,
        max_rows: int = 2000,
        price_fields: list[str] | None = None,
    ):
        if cutoff.tzinfo is None:
            raise ValueError("timezone-aware cutoff required")
        self.client, self.store, self.cutoff, self.max_rows = client, store, cutoff, max_rows
        self.price_fields = price_fields or [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "total_turnover",
        ]

    def fetch(self, kind: str, query: Query, fiscal_year: str | None = None) -> dict:
        end = datetime.combine(query.end, time.max, SHANGHAI)
        if end > self.cutoff:
            raise ValueError("query exceeds research cutoff")
        args = {
            "order_book_ids": query.symbols,
            "start_date": query.start.isoformat(),
            "end_date": query.end.isoformat(),
        }
        if kind not in {"bars", "announcements", "report_summaries", "news"}:
            raise ValueError("unsupported source kind")
        if kind == "report_summaries" and (
            fiscal_year is None or not fiscal_year.isdigit() or len(fiscal_year) != 4
        ):
            raise ValueError("explicit four-digit fiscal_year required")
        try:
            # SDK warnings can contain account identifiers. MCP stdout is protocol-only.
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                if kind == "bars":
                    frame = self.client.get_price(
                        **args,
                        frequency="1d",
                        fields=self.price_fields,
                        adjust_type="none",
                        skip_suspended=False,
                        expect_df=True,
                        market="cn",
                    )
                elif kind == "announcements":
                    frame = self.client.get_announcement(**args, market="cn")
                elif kind == "report_summaries":
                    frame = self.client.consensus.get_indicator(
                        **args,
                        fiscal_year=fiscal_year,
                        fields=["institute", "summary"],
                        date_rule="rice_create_tm",
                        market="cn",
                    )
                elif kind == "news":
                    frame = self.client.news.get_stock_news(
                        **args, fields=["news_id", "title", "original_time", "url", "source"]
                    )
                else:
                    raise ValueError("unsupported source kind")
        except Exception as exc:
            raise DataUnavailable(f"ricequant {kind}: {type(exc).__name__}; check access") from None
        if frame is None or frame.empty:
            raise DataUnavailable(f"ricequant {kind}: empty result")
        if len(frame) > self.max_rows:
            raise ValueError("too many rows; narrow the request")
        rows = json.loads(frame.reset_index().to_json(orient="records", date_format="iso"))
        eligible, excluded = [], 0
        for row in rows:
            time_fields = (
                ("date",)
                if kind == "bars"
                else (
                    "date",
                    "datetime",
                    "info_date",
                    "original_time",
                    "rice_create_tm",
                    "create_tm",
                )
            )
            observed = [row[name] for name in time_fields if row.get(name) is not None]
            if not observed:
                excluded += 1
                continue
            available = max(self._timestamp(value) for value in observed)
            if available > self.cutoff:
                excluded += 1
                continue
            eligible.append({**row, "available_at_from_returned_metadata": available.isoformat()})
        if not eligible:
            raise DataUnavailable("no rows with eligible availability metadata")
        request = {
            **query.model_dump(mode="json"),
            "fiscal_year": fiscal_year,
            "adjust_type": "none" if kind == "bars" else None,
        }
        record = SourceRecord(
            provider="ricequant",
            kind=kind,
            request=request,
            retrieved_at=datetime.now(UTC),
            research_cutoff=self.cutoff,
            content=eligible,
            timing_limit="Retrospective retrieval with as-of filtering; not a vintage archive. "
            "Date-only values become end of day Asia/Shanghai. Missing intraday publication "
            "time must not be inferred. Summary/title data is not a full report/article.",
        )
        digest = self.store.put(record.model_dump(mode="json"))
        return {
            "evidence_id": digest,
            "provider": "ricequant",
            "kind": kind,
            "row_count": len(eligible),
            "excluded_rows": excluded,
            "timing_limit": record.timing_limit,
            "preview": eligible[:5],
        }

    @staticmethod
    def _timestamp(value) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        # RiceQuant date fields serialize midnight even where precision is only a day.
        if parsed.time().replace(tzinfo=None) == time.min:
            parsed = datetime.combine(parsed.date(), time.max, parsed.tzinfo)
        return parsed
