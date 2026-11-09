# Sprint 1D: market-data integration review gate

Assessment date: 2026-11-09. Repository HEAD: `3e7faff`.

Follow-up: the user subsequently approved synthetic-only offline implementation.
That work is described in [offline_market_data.md](offline_market_data.md).
The assessment below records the original review gate; real provider licensing,
finality and production-publication gates remain unresolved.

## Decision

STOP pending approval under the mission's explicit instruction: if no free
provider can satisfy the existing verification contract, document the gap and
stop rather than weakening verification. No assessed provider has established
the required per-candle finality evidence. This is an assessment of documented
capabilities, not proof that every free provider is incapable.

Recommend reusing Yahoo/yfinance for **provisional research ingestion only**,
conditional on permitted-use review. No provider is recommended for trusted
publication yet. No network market-data calls, subscriptions, dependency changes,
trust entries, or production enablement are part of this assessment.

## Existing architecture and exact contracts

- `providers/daily_ohlcv_provider.py`: `DailyOHLCVProvider.fetch_daily(ticker,
  sessions)` returns `ObservedTicker`. The existing Yahoo implementation reuses
  `tools.historical_data`, requesting daily bars with `auto_adjust=False` and
  corporate actions. It defaults to provisional; its optional callback cannot
  substitute for Sprint 1C evidence.
- `models/daily_signals.py`: the batch must contain exactly AAPL, JNJ, JPM,
  MSFT, WMT and XOM, with identical exact completed-session coverage and at least
  200 sessions. Prices and volume must declare split adjustment, dividends must
  be recorded rather than applied, and currency must be USD. Every availability
  record must attest finality and obey close <= availability <= fetch <= decision.
- `tools/historical_snapshot.py`: immutable validated candles include OHLCV,
  dividend and split ratio. Snapshot source, currency, adjustment conventions,
  unique chronological dates, canonical JSON and SHA-256 are already available.
- `tools/market_verification.py`: `CalendarArtifact` carries source/version,
  availability, scope, end-exclusive local-date coverage, six listing identities,
  sessions and explicit closed dates for every exchange/date. New York timezone
  interpretation uses zoneinfo. `as_daily_schedule()` rejects divergent exchange
  schedules; no weekday approximation is needed or acceptable.
- `ProviderEvidenceArtifact` requires exactly one uniquely identified proof for
  every candle, binding ticker, exchange, date, exact candle hash, official close,
  issuance time, `provider_final=True` and `completed_session=True`. Source must
  match the snapshot source. Close <= issuance <= fetch <= verification <=
  decision; artifact availability and publication-delay checks also apply.
- `TrustRegistry` requires caller-controlled reviewed exact-content pins for
  both artifacts. Its real-mode default is empty. A hash establishes integrity,
  not factual authority. No synthetic identities belong in production pins.
- `tools/verified_daily_pipeline.py` delegates freezing, replay and publication
  to the existing daily pipeline. Ingestion checks trust before provider calls.
  `DailySignalStore` atomically stores all six stocks, reports and verification
  metadata in SQLite. Replay rechecks hashes, external trust, evidence and code,
  Python/dependency/tzdata provenance without fetching data.

The older `YahooPriceHistoryProvider` uses `auto_adjust=True` and returns closes
only; it is not a substitute for this contract. The Finnhub market-snapshot
provider combines quotes/fundamentals with those closes, not verified daily OHLCV.

## Free-source assessment

Documentation was inspected; no authenticated endpoint or market-data request
was made. Sources below are capability references, not approved trust artifacts.

### Yahoo through installed yfinance

Daily OHLCV and corporate-action loading already exist locally. Daily labels
identify sessions, not evidence issuance times. Retrieval time is recorded by
the adapter; currency is currently declared USD rather than checked against
provider metadata. Exchange identity lives in the external calendar. These are
normalization gaps to address before any trusted integration.

The project's [download reference](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
documents adjustment options; it does not establish the required candle-bound
finality attestation. No immutable correction history or guaranteed free-service
rate limit was established in this review. Preserve each retrieval independently
because historical values may change; do not silently overwrite revisions.

The [project notice](https://pypi.org/project/yfinance/) describes research and
educational intent and Yahoo personal-use restrictions. The package license
does not grant market-data redistribution or commercial-use rights. Suitability
for this project's intended use remains unapproved.

### Finnhub through installed client

The existing integration does not ingest stock candles or record candle-finality
evidence. The official [stock-candle documentation](https://finnhub.io/docs/api/stock-candles)
and [rate-limit page](https://finnhub.io/docs/api/rate-limit) were not readable by
the documentation reader. Current free candle entitlement, rate limits,
adjustment details, correction policy and permitted use therefore remain
unverified. Do not infer access from the installed client or an API status value.
No qualifying finality mechanism was established.

### Alpha Vantage as an alternative

Its [official documentation](https://www.alphavantage.co/documentation/) describes
daily raw OHLCV with free compact coverage of 100 points; full daily coverage
requires premium access. That compact history cannot bootstrap the required
200-session window. Raw prices also do not directly meet the existing adjustment
contract. No qualifying candle-bound finality proof was established. Entitlements,
rate limits, correction guarantees and permitted use require further review;
there is no reason to install another dependency at this gate.

## Calendar and source-artifact integration plan after approval

Reuse `CalendarArtifact`, its existing adapter and exact-content pins. Import
reviewed NYSE and Nasdaq schedules from their respective official sources:
[NYSE hours/calendar](https://www.nyse.com/markets/hours-calendars) and
[Nasdaq Trader calendar](https://nasdaqtrader.com/Trader.aspx?id=Calendar).
These document holidays and early closes but are not themselves ready-made
artifacts covering the entire research window or historical listing mappings.
Do not copy the invented test mappings into production.

An approved importer should preserve original source bytes and retrieval time,
source URLs, declared schedule version, coverage and hashes; explicitly classify
every closed date; represent official opens/closes in America/New_York before
UTC normalization; and retain the tzdata version. Independently review historical
coverage, exceptional closures, revisions and effective listing identities.
Retain the current rejection of exchange-schedule divergence.

Extend ingestion provenance alongside the existing snapshot, not through a
second signal pipeline: dataset/version, exchange, explicit coverage, provider
source timestamps (or an explicit unavailable state), retrieval completion,
currency and adjustment declarations, original response hash, normalized hash,
calendar reference and independently supplied evidence reference. Missing source
timestamps must never be filled with invented close or retrieval timestamps.
Provisional retrieval, provider completion and externally accepted trust must
remain separate states. Pin a new revision rather than mutating old artifacts.

Existing verified snapshots already persist normalized data, calendar/evidence
contents and integrity references atomically. A raw-response archive and richer
provider provenance would be additive; none has been implemented at this gate.

## Review choices

1. Recommended: authorize offline-only adapter/provenance and raw-artifact
   persistence work with mocked responses, keeping all unapproved observations
   provisional and real verified publication blocked. This does not resolve
   finality or authorize live requests.
2. Supply an independently reviewed provider evidence specification/sample and
   approved calendar provenance that satisfy the unchanged 1C contract, then
   implement that integration with mocks before separately approving live access.

Weakening finality, inferring it from elapsed time, or treating hashes/status
responses as trust is not proposed. Real publication requires a separate review.

## Validation and scope

No runtime files or tests changed, so no new implementation tests are claimed.
The existing synthetic calendar/finality tests remain the relevant baseline;
new normalization, rate-limit, raw-snapshot and batch-failure tests belong with
the approved implementation. Full regression results are recorded in the
handoff. The pre-existing modification to `scripts/sec_match_recon.py` was left
untouched. No commits, pushes, tags, broker calls or order creation were made.
