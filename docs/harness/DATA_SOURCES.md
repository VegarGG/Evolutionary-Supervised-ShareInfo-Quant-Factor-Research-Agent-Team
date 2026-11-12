# China A-share source selection and bounded pilot

Decision, 12 November 2026 Beijing: **BaoStock is the free testing default**.
iFind and RQData remain selectable in DSH → Settings → Research data. Each session
pins its first selected source. Changing the setting requires a new session;
there is no automatic fallback, cross-vendor merge, or silent synthetic substitute.
The comparison below queried different providers in separately identified probes,
not in a mixed research session.

| Candidate | Setup and relevant scope | Decision |
|---|---|---|
| BaoStock 0.9.4 | Anonymous `login()`, daily history, exact date/code/close fields; no personal token for the tested public service | Selected for small daily-data testing |
| AKShare / Eastmoney | No personal token for `stock_zh_a_hist`; one HTTPS request for this history function; broader report/news discovery exists | Comparison passed; not installed as a runtime adapter or fallback |
| TuShare Pro | Account and token; official daily-data free tier currently requires 120 points, with 50 requests/minute and 8,000/day | Convenient once configured, but adds an account/permission prerequisite here |
| iFind | Access token or refresh token entered in DSH; scarce paid entitlement | Retained, no real credential or provider request used in this package |
| RQData | License entered in DSH; API-specific entitlements | Retained, no real credential or provider request used in this package |

Sources checked on 12 November: [BaoStock's published SDK and usage example](https://pypi.org/project/baostock/0.9.4/),
[AKShare historical quote documentation](https://akshare.akfamily.xyz/data/stock/stock_quote.html),
[AKShare source at f5324ef](https://github.com/akfamily/akshare/blob/f5324effb9419cba50bba423b4bd33073c79bdc2/akshare/stock/quote/stock_hist_em.py),
[TuShare daily permissions](https://tushare.pro/document/1?doc_id=108),
[TuShare points explanation](https://tushare.pro/document/1?doc_id=290),
[TuShare token setup](https://tushare.pro/document/1?doc_id=39),
[RQData API](https://www.ricequant.com/doc/rqdata/python/manual), and the owner's
[ORS iFind implementation reference](https://github.com/VegarGG/Opinion-Radar-System).
These are current observations, not permanent service guarantees.

## What ran

All live data probes requested only `000001.XSHE`, 2026-10-28 through 2026-10-30,
daily and unadjusted. BaoStock returned three closes; the separate Eastmoney
comparison returned the same three closes. This is a transport/schema spot check,
not evidence of complete coverage, stable availability, or production data quality.
Full market rows remain in the private evidence store. The public
[result index](evidence/data-2026-11-12/RESULTS.json) records hashes, counts,
timing, resource measurements and outcomes without redistributing those rows.

| Attempt | Outcome |
|---|---|
| Anonymous BaoStock SDK comparison | Pass; one login, one history query, one logout; 3.43 s |
| AKShare-referenced Eastmoney endpoint comparison | Pass; one HTTPS request; 2.81 s; close values matched BaoStock |
| Guarded BaoStock 001 | Failed; reservation retained. Original exception record lacked its detailed reason |
| Cache check 001 | Refused locally because 001 had no verified result; zero new provider calls. Sandbox denied resource enumeration |
| Guarded BaoStock 002 | Failed; captured response enabled offline diagnosis. Relaxing a suspected compressed-frame suffix check had not fixed it |
| Offline SDK regression | Reproduced the actual framing defect: SDK 0.9.4 drops the final character when a decompressed response lacks a terminal newline, truncating adjustment flag `3` |
| Guarded BaoStock 003 | Pass after a bounded newline normalization; three validated daily rows; 6.17 s |
| Cache check 002 | Pass; same evidence hash, zero additional provider requests; 0.010 s |
| Native DSH tool check | Pass; actual DSH plugin → Python adapter → real BaoStock cache → DSH. Model responses were synthetic; zero live model or data requests |

The first failure is not retroactively assigned a captured cause. The second
failure and offline regression establish the framing issue. The failed attempts
remain visible; no usage database was cleared. Two manual, bounded free-source
allowance increases funded diagnosis/retest. The SDK's original source is unmodified.
Its scoped transport wrapper preserves the parser's expected newline, caps bytes
before decompression and after decompression, enforces deadlines and EOF handling,
and permits one login, one first-page history request and one logout per attempt.
It never follows SDK pagination, retries, or a VIP endpoint. Public BaoStock uses
TCP port 10030; this adapter does not turn that protocol into authenticated HTTPS.

## Controls and credentials

`harness/configs/data-pilot.yaml` allows one stock and three calendar days, close
only. iFind and RQData each retain **one business request, at most one authentication
request, and three estimated price cells**. BaoStock's cumulative cap is three
attempts and nine estimated price cells, including the two failures above. Its
fresh-query allowance is consumed; the verified exact query is reusable locally.
Further expansion requires an explicit operator policy revision and a new recorded
experiment. Counters survive restarts and changing session IDs. Each vendor has a
separate counter; free tests cannot consume or expand the iFind allowance.

Saving/removing a credential in DSH is local and makes no data request. Password
fields clear after saving. Stored values never enter model arguments, stdout,
evidence records or command-line arguments. iFind can exchange a refresh token
for the current access token through `get_access_token`; it never invokes token
rotation. RQData's SDK may have internal transport behavior beyond our logical
operation count; the pilot does not claim a packet-level cap for that SDK.

Exact-query caching keys include vendor, account fingerprint, dates, cutoff,
operation and adapter version. Workers receive a content hash and paginated
evidence only after a successful fetch. Reads are granted to a session; an unrelated
session cannot retrieve another session's evidence hash. Unknown/failed attempts
are not replayed automatically. Data and model allowances are separate ledgers.

## Reports, news and research limits

The native DSH/MCP surface includes `research_reports`, `company_announcements`,
`research_news`, `market_daily_bars` and `read_research_evidence`. RQData report
summaries and disclosure/news metadata are implemented behind entitlement checks;
`rqdatac_news` is additionally required for news. These return summaries/links,
not full report PDF extraction. iFind and BaoStock currently expose daily close
only. Report/news calls are deliberately disabled in this small transport pilot.

All observations here are downloaded today from historical date ranges, not a
point-in-time vintage archive. The harness has not yet validated corporate actions,
historical universes, delistings/suspensions, timezone edge cases across vendors,
or open-ended factor quality. Three daily closes are enough for a transport test,
not a factor backtest. No performance or alpha claim follows from this check.
