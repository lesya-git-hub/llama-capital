# Sprint 1D offline market-data sources

`providers.offline_market_data` adds a synthetic-only boundary to the existing
Sprint 1B/1C pipeline. It has no default network transport, clock-based finality,
broker integration, strategy changes or production trust entries. No dependencies
were added. Provider suitability, licensing and finality gaps remain as described
in [the assessment](market_data_sprint_1d_assessment.md).

## Contracts and use

Implement the replaceable `SourceProvider.fetch_source(ticker, sessions)` protocol
with mocked responses. It returns `SourceObservation`: an existing validated
`TickerSnapshot`, dataset ID/version, exchange, source timestamp (explicitly null
when unavailable), retrieval timestamp, exact UTF-8 fixture response and its
SHA-256. OHLCV and corporate-action normalization into the existing Candle schema
is the injected provider's responsibility; no vendor-specific field mapping or
currency/adjustment inference is built into the common boundary.

`assemble_source_batch(mock, synthetic_calendar, evidence=optional_fixture)`
validates all six responses before returning a `SourceBatch`. Missing, duplicate,
stale, invalid or conflicting observations reject the batch. A provider exception
is wrapped with ticker context and preserved as the cause, including mocked
`OfflineRateLimitError`; there is no retry, sleep or fallback request. Inputs must
already declare USD and split-adjusted prices/volume. No conversions occur.

The supplied calendar is the existing `CalendarArtifact`, including explicit
closed dates, official session timestamps, listing identities and versioned
provenance. Existing adaptation handles New York/DST and early closures and
rejects divergent exchange schedules. The source archive requires exact full
session coverage of its calendar; scope a calendar to the desired source window.
The unchanged signal layer separately requires at least 200 completed sessions.

```python
batch = assemble_source_batch(mock_source, synthetic_calendar)
archive = SourceSnapshotStore("runs/synthetic_sources.sqlite3")
digest = archive.save(batch)  # Preserve this expected hash independently.
restored = archive.load(expected_sha256=digest)
provider = OfflineDailyOHLCVProvider(restored)
observation = provider.fetch_daily("AAPL", restored.calendar.as_daily_schedule().sessions)
assert all(not value.final for value in observation.availability)
```

This provider implements the existing `DailyOHLCVProvider` protocol. Passing its
observations to Sprint 1C preserves all existing checks: default real trust
rejects the synthetic authorities; even synthetic pins cannot promote the
provisional observations. Optional stored provider evidence is preserved as
reference material, never synthesized, rewritten, accepted or used to set finality.
Retrieval success, provider completion claims and reviewed trust stay distinct.

## Persistence and replay

`SourceSnapshotStore` is a source archive, separate from the existing signal
ledger; it does not generate or publish signals. SQLite stores a complete batch
in one transaction, indexed by canonical content hash and dated with its final
session. The batch embeds dated OHLCV, raw fixture payloads/hashes, timestamps,
conventions and calendar/evidence artifacts; their canonical hashes can be
computed with the existing `input_hash`. Exact retries are idempotent. A changed
dataset version or observation produces a new immutable record, preserving prior
revisions. Loading requires an independently retained expected hash and checks
content and date metadata before returning validated frozen inputs. No live
requests are made during replay. Synthetic raw payloads are not evidence that a
real provider supplied or licensed the values.

## Remaining review gates

- No real provider normalizer, licensed feed, official historical calendar import
  or external finality-evidence transport is enabled.
- Vendor timestamp semantics, historical corrections, USD/exchange metadata,
  split-adjusted volume and permitted retention/redistribution need review.
- No assessed free source established Sprint 1C's candle-bound completion/finality
  evidence. Neither elapsed time nor a response status fills that gap.
- Real publication remains blocked by the empty default trust registry. Any
  future real adapter needs reviewed authority and separate publication approval.

Tests use invented source fixtures and the existing explicitly synthetic 1C
calendar. They exercise source validation, provider errors/rate limits, atomic
batch rejection, snapshot determinism/revisions/tampering, absent evidence,
provisional status and strict verification rejection. Existing 1C tests cover
holidays, early closes, DST, trust identities and atomic verified persistence.

Validation on 2026-11-09:

- `uv run --no-sync pytest -q tests/test_offline_market_data.py tests/test_market_verification.py`:
  48 passed.
- `uv run --no-sync pytest -q`: 604 passed (588 existing plus 16 new cases).

The uv cache required running the tests outside the filesystem sandbox; no
dependency synchronization or installation was performed. Work stops for review
with production trust unchanged and no real-world publication enabled.
