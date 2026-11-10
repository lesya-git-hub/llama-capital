# Sprint 1W — provisional Alpaca shadow diagnostics

Inspected HEAD: `78232faf0cd9c35798bf93c79406449bb4257084` on main. Baseline: 1,253 passes; final Sprint 1W full regression: **1,266 passed** (see verification record below). **Gate B remains NO-GO.** This sprint adds an offline-tested numerical diagnostic, not a forward-trading workflow. No real samples or signals were acquired, calculated or stored.

## Compatibility and minimum history

The existing `DailySignalInputs.validate_completed_inputs` and verified daily pipeline require final/available candles. They **cannot consume provisional Alpaca observations** without violating their contracts. They remain unchanged and are not called by this harness.

The pure functions `evaluate_mean_reversion` (`tools/quantitative_pipeline.py`), `generate_mean_reversion_exits` (`tools/historical_signals.py`), `classify_market_regime` and `filter_entries_by_regime` (`tools/market_regimes.py`) accept numerical arrays without asserting trust. They can support isolated, explicitly unverified diagnostics. Minimum history: entry/ATR evaluation requires 51 sessions, exit evaluation first becomes meaningful at 50, and regime classification requires 200. This harness requires **at least 200 aligned sessions per symbol** for both existing variants and uses the unchanged `DailyStrategyConfiguration`. Wilder RSI/ATR initialization depends on the supplied history, so freeze the entire chosen window; do not assume 200 and 209 sessions yield identical results.

`tools/alpaca_shadow.py::analyze_shadow_batch(batch, calendar, previous_batches=())` accepts already supplied in-memory objects. It first reuses `validate_alpaca_batch`, then computes baseline-entry, bear-filtered-entry and exit conditions, regime and ATR for all six symbols. Output is a separate `ShadowReport`, always PROVISIONAL, rights UNRESOLVED, finality/adjustment correctness NOT_ESTABLISHED, `trust_admitted=False` and `order_submission_allowed=False`. It is not `DailyDecision`, a verified report or an order instruction; it has no conversion/publication/execution API. Entry and exit conditions remain separate; no BUY/SELL order arbitration or position inference is performed.

IEX-only high/low/close, gaps and volume can differ from consolidated market observations. Even indicators not using volume may therefore differ. These are conditions on **partial-venue IEX observations**, not validated consolidated-market strategy signals or evidence of investment performance. Split adjustment is a provider claim, not independently verified corporate-action correctness. No missing action fields are invented.

## Proposed single historical run — not authorized to request

- Universe in existing canonical order: **AAPL, JNJ, JPM, MSFT, WMT, XOM**.
- Fixed New York civil window: **2026-01-02 through 2026-10-30**, avoiding today's candle. Endpoint: `https://data.alpaca.markets/v2/stocks/bars`.
- Planning expectation: **209 sessions per symbol, 1,254 bars total**. This count excludes weekends and proposed scheduled closures January 19, February 16, April 3, May 25, June 19, July 3 and September 7. It is an **unverified planning schedule**, not an independently checked official calendar. Exceptional closures or listing changes could invalidate it.
- No applicable real frozen `CalendarArtifact` was found in the inspected repository. Existing synthetic calendars exercise contracts but must not be relabeled as actual 2026 schedules. Before request approval, supply and review a complete versioned calendar for the exact window, including listings, open/closed dates and provenance. Recompute the count; if it differs, stop and review a revised exact request rather than silently trimming expectations. A numerical calendar check does not establish its authority or candle finality.
- One GET, no retry, redirect, fallback or automatic pagination. Request limit 2,000 accommodates the planned batch. Require explicit null `next_page_token` and complete session coverage for every symbol. Any continuation token or incomplete response rejects the whole batch; a second request needs separate approval/design. HTTP 200 is not batch success.

Exact proposed sanitized URL:

```text
https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL%2CJNJ%2CJPM%2CMSFT%2CWMT%2CXOM&timeframe=1Day&start=2026-01-02T05%3A00%3A00Z&end=2026-10-31T03%3A59%3A59Z&adjustment=split&feed=iex&currency=USD&limit=2000&sort=asc
```

Prepare `DailyBarsRequest` with those explicit UTC instants and `expected_session_dates` derived from the reviewed calendar. Preparing the object does not fetch data. Preserve the existing credential loader and intended Alpaca authentication headers; never put credentials in the URL or output. No credential access is needed to prepare the request.

Proposed limits using the existing `TransportLimits`: 10-second socket timeout, 30-second overall deadline, **1 MiB response cap** (explicitly configured; no change to the adapter default). Budget roughly 0.2–0.4 MiB for 1,254 compact bars, an estimate based on field counts, not observed payload size or a provider guarantee. Oversized responses fail closed. Provider quota/entitlement and actual response encoding remain to be confirmed; no claim that the requested limit guarantees a single page.

## In-memory flow and stop conditions

After rights, calendar and exact-request approval only: operator manually invokes the existing adapter once → complete batch validation → isolated shadow diagnostics → transient local review → discard objects. This sprint provides **only the batch-to-diagnostics function**, no CLI, fetch wrapper, scheduler, archive, signal publication, broker connection, sizing or FX/risk integration.

```python
from tools.alpaca_shadow import analyze_shadow_batch

# Already supplied batch and reviewed frozen calendar; this call never fetches.
report = analyze_shadow_batch(batch, calendar, previous_batches=prior_batches)
# Inspect locally only if permitted; do not print/log/serialize a real report.
```

The validator rejects missing/extra/duplicate/unordered sessions, malformed OHLCV, mismatched timestamps and unresolved changes against supplied earlier observations. Missing calendars or insufficient history stop analysis; no forward-fill or shorter-history fallback. Deterministic replay requires the same inputs/calendar/prior sequence. This function has no durable revision memory: omitting prior batches or restarting loses comparison context, so it does not establish historical-vintage completeness. A stable hash or successful response never establishes finality. The diagnostic does not require or manufacture provider-final evidence; that absent evidence remains a blocker to the **official signal/trading path**, not a fact hidden by this experiment.

Real raw bars, derived per-symbol conditions, prices, report hashes and summaries must remain out of files, logs, Git, screenshots, notebooks, chat and external services unless separately permitted. The function writes and prints nothing, but a caller can serialize its result; nonpersistence is an operating restriction, not a sandbox guarantee. RAM, IPC, swap and crash dumps are host-custody limitations, not cryptographic erasure. A six-stock/date-specific condition count is not automatically non-reconstructable or exempt from data rights.

## Rights/evidence approval checklist

No public network research was separately authorized for this sprint, so **no current account-specific permission was established**. Prior recorded findings in `alpaca_trial_feasibility.md` and the [Sprint 1U review](supervised_forward_trial_readiness.md) are not refreshed legal clearance. Earlier connectivity does not resolve eligibility or licensing.

Before a real shadow run, obtain applicable terms or attributable provider clarification answering:

- Does this Ireland-based individual's actual paper/data account permit Basic/IEX automated personal noncommercial analysis, including transient RAM/IPC processing? Reconcile the prior global-paper documentation versus territorial terms conflict. Check [paper-trading documentation](https://docs.alpaca.markets/us/docs/paper-trading), [terms](https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf) and [country support](https://alpaca.markets/support/countries-alpaca-is-available).
- May any aggregate, supposedly non-reconstructable observation be retained? Confirm precise fields, duration, deletion/backups and sharing scope instead of assuming a derived-data exception. Check the applicable [customer agreement](https://files.alpaca.markets/disclosures/library/AcctAppMarginAndCustAgmt.pdf) and upstream subscriber agreements in the [disclosure library](https://alpaca.markets/disclosures). Until resolved, **retain no real-run outputs**, including aggregate counts/hashes; no aggregate export is implemented.
- Confirm historical IEX entitlement, UTC daily labels, adjustment/volume/VWAP conventions and page/response limits in the [bars reference](https://docs.alpaca.markets/us/reference/stockbars), [market-data API documentation](https://docs.alpaca.markets/us/docs/about-market-data-api) and [FAQ](https://docs.alpaca.markets/us/docs/market-data-faq). Independent corporate actions, publication/finality, revision/vintage evidence and an authoritative calendar remain unavailable for verified use; check the [corporate-actions reference](https://docs.alpaca.markets/us/reference/corporateactions-1).

**Decision:** offline mocked diagnostics are ready for independent review. The proposed authenticated real shadow request is **HOLD** pending rights, reviewed calendar/count, entitlement and separate exact-request authorization. No production pins, trust promotion or change to Gate B is proposed.

## Offline validation and changed files

Added `tools/alpaca_shadow.py`, `tests/test_alpaca_shadow.py` and this document. Existing adapter, validator, completed-candle signal contracts and all execution modules are unchanged.

`uv run --no-sync pytest -q tests/test_alpaca_shadow.py tests/test_alpaca_data_validation.py tests/test_alpaca_market_data.py`: **170 passed in 2.56 seconds**, including **13 new shadow cases**. New tests feed invented responses through the mocked adapter and frozen synthetic calendar, compare outputs with the original numerical functions, cover exactly 200/insufficient 199 sessions, missing/uniformly missing/duplicate/reversed/malformed data and revision holds, reject relabeling, and assert deterministic/no-output/no-file behavior. Guards forbid real HTTPS, credential loading, subprocess transport and SQLite connections in shadow tests. Existing focused tests cover DST/holidays and transport/pagination failures.

Tests used the existing uv cache with approved sandbox escalation and no dependency synchronization. The Sprint 1V artifacts and protected script/provider documents remain unchanged. No authenticated calls, network research, real data storage, orders, broker writes, staging, commits or pushes. Stop for review.

## Final independent offline verification

`uv run --no-sync pytest -q`: **1,266 passed in 201.26 seconds**, preserving all 1,253 baseline tests plus 13 new cases. No dependencies were synchronized or changed.

Independent date enumeration found **216 weekdays minus the seven listed planning closures = 209 proposed sessions**, hence **1,254 bars** and **nine surplus sessions per symbol** above the 200 minimum, conditional on complete data and the schedule being correct. There is **no exact calendar-authoritative count available from the repository** for this window: inspected `CalendarArtifact` instances are generated synthetic tests, and the preserved Sprint 1V snapshot is the invented 2020 calendar. The other existing run JSON files are research/intelligence records, not frozen exchange-calendar artifacts. No real 2026 snapshot was found or manufactured. Consequently, no numerical discrepancy was found in the proposal, but the requested independent frozen-calendar confirmation remains blocked; actual six-symbol coverage cannot be asserted before approved acquisition and validation.

The 2,000-bar limit exceeds the planned 1,254 by **746 bars**. A separately constructed in-memory invented payload with timestamps, OHLCV, trade count and VWAP measured **165,611 bytes compact / 185,683 bytes with default JSON spacing**, both below **1,048,576 bytes**. Thus the cap is adequate for these representative fixtures and gives roughly 836 bytes per expected bar, but it is not a proven upper bound for a provider response with arbitrary numeric precision/whitespace. Keep the cap fixed and fail closed if exceeded; no automatic increase or second page. Adapter code requires exactly null `next_page_token`; non-null/empty tokens raise `PAGINATION_NOT_SUPPORTED`, while a missing marker fails schema validation. Tests confirm exactly one transport call on those failures.

Static inspection and mocked guards confirm the harness has no fetch, order-staging, broker, database, trusted-publication or trust-admission call path. It only validates supplied memory objects and returns a separate provisional diagnostic model. This is not an OS sandbox: embedding code could persist or misuse a returned object, so caller restrictions still apply. No trusted-data gate is relaxed. Protected-file and all five Sprint 1V artifact SHA-256 values were checked before and after verification and remain unchanged. Gate B remains NO-GO; stop for review.
