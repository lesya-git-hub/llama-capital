# Alpaca provisional daily-bar validation — Sprint 1T

Gate B remains **NO-GO**. This offline inspection layer checks data quality; it does not establish licensing clearance, consolidated market coverage, adjustment correctness or candle finality. No acquisition, archive, admission, portfolio, risk or execution integration is introduced.

## Usage and interpretation

`tools/alpaca_data_validation.py` accepts the existing in-memory `AlpacaDailyBatch` and frozen `CalendarArtifact`. It reuses the existing schema, America/New_York timezone, calendar coverage checks and canonical input hashing. It neither loads credentials nor requests or writes data.

```python
from tools.alpaca_data_validation import (
    AlpacaValidationSession, AlpacaQualityRejected, assess_alpaca_batch,
)

# batch and frozen_calendar are supplied in memory; no acquisition occurs here.
report = assess_alpaca_batch(batch, frozen_calendar)
session = AlpacaValidationSession()  # bounded history, at most 64 attempts
try:
    report = session.validate(batch, frozen_calendar)
except AlpacaQualityRejected as exc:
    report = exc.report  # HELD, with deterministic issue codes
```

`CHECKS_PASSED` means only that the supplied inputs passed this quality profile. Every report remains `PROVISIONAL`, `unverified`, and `trust_admitted=False`. Reports explicitly label IEX as **partial-venue coverage, not consolidated US market data**. `split` is a provider/request claim; corporate-action evidence and candle finality remain `NOT_ESTABLISHED`. A supplied calendar, even one marked `real`, is not independently authenticated or admitted by this validator.

## Checks and conservative boundaries

- Require exactly AAPL, MSFT, JPM, XOM, JNJ and WMT, with every expected session for every symbol. Reject missing/extra/duplicate symbols or sessions and nonchronological bars. HTTP success is irrelevant to completeness.
- Revalidate nested adapter models, including copies made without Pydantic validation. Require UTC timestamps that map to New York midnight and agree with the session label. Derive expected dates from explicit frozen sessions/closures, not weekdays or caller expectations. Reuse calendar rejection of divergent exchange schedules. Require coverage for the entire civil-date window and complete session windows, including early closes. DST uses the existing timezone implementation.
- Require finite positive, consistent OHLC; nonnegative integral volume within the adapter float representation's safe integer range; optional nonnegative integer trade count; and optional VWAP within low/high with positive volume. Positive volume with zero trades, or zero volume with positive trades, is held. Do not compare trade count numerically to split-adjusted volume: their units differ. Zero volume with zero/absent count and absent VWAP is allowed.
- Fractional split-adjusted volume is conservatively held by this profile. Provider rounding or VWAP-basis discrepancies are held for review, never repaired. The adapter already normalizes numbers to floats: this layer cannot recover precision lost before validation or validate raw response custody.
- Require consistent request/acquisition chronology and a calendar available by acquisition. Session completion is a necessary coverage check only; elapsed time, successful requests and matching hashes never establish finality. Local acquisition timestamps remain unattested observations, not independent clock evidence.
- Changed OHLCV, timestamps, optional fields or labels for the same provider/feed/currency/adjustment/symbol/session are unverified revision conflicts. Window changes do not hide overlapping changes. Identical observations with later receipt times may pass; stable hashes confer no trust.

`assess_alpaca_batch` / `validate_alpaca_batch` compare only explicitly supplied prior batches. `AlpacaValidationSession` retains immutable snapshots and reports for successful and held attempts in append-only, bounded **memory-only** history. A changed version and any subsequent return to an earlier version remain conflicted while both are present. Invalid history fails closed; reaching capacity rejects without pruning. There is no conflict-resolution API or persistent/restart history. Creating a new session loses that context, so this is not an authoritative revision registry or a concurrency/admission barrier. Deterministic replay requires the same snapshots, calendar and prior-history sequence. All-or-nothing rejection returns a report, never a partially accepted batch.

## Evidence checklist before a separately authorized real-data evaluation

These are unresolved requirements, not legal clearance. This sprint performed no network research and relies on the previously recorded findings in `alpaca_trial_feasibility.md` and `market_data_provider_onboarding_review.md`.

- **Personal noncommercial use:** confirm the exact account agreement, market-data entitlement, automated research and supervised simulated-use rights applicable to this operator and account.
- **Irish eligibility:** resolve the previously documented eligibility ambiguity with applicable current terms or written provider confirmation; connectivity does not prove eligibility.
- **Retention and derived outputs:** establish explicit permissions and deletion boundaries for temporary raw-data caching, longer archives, signals, simulated positions and performance records, including post-trial retention and redistribution restrictions. No general right is inferred from API access. This implementation stores no real payloads or derived outputs on disk.
- **Provider finality:** obtain an applicable publication/completion policy, revision semantics and independently supportable publication/receipt clock evidence for daily IEX bars. HTTP 200, a completed session and unchanged responses are insufficient.
- **Corporate actions:** obtain independent split identifiers, effective dates, ratios, price/volume adjustment and rounding rules, dividend treatment, VWAP basis and correction history. No absent action fields are invented and no price jump is treated as proof of an action.
- **Point-in-time history:** establish effective, published, observed and correction timestamps, retained superseded versions and evidence of what was available at each decision time. The bars' session labels alone do not provide this evidence.
- **Calendar authority and custody:** establish authorized, versioned exchange schedules and exceptional closures, provenance, integrity, receipt-clock support and independent review. Synthetic fixtures exercise behavior only; supplied calendar hashes do not establish authority.

Production trust admission, finality verification and Gate B remain blocked on these external evidence and operational requirements. No rights to execute, publish, value a portfolio or retain provider data are granted by this quality report.

## Offline validation

The synthetic tests mock the existing adapter transport and prohibit credential loading, HTTPS connections and subprocess-based transport. They cover complete batches; spring/fall DST; explicit holidays, exceptional closures and early closes; missing/extra/duplicate/order failures; numerical and timestamp failures; incomplete or forged metadata; split-like revisions; repeatable reports; history retention and attempted promotion. Fixtures are invented and confer no real calendar or adjustment authority.

Focused command: `uv run --no-sync pytest -q tests/test_alpaca_data_validation.py tests/test_alpaca_market_data.py` — **157 passed** (54 new validation tests, 103 existing adapter tests).

Full regression: `uv run --no-sync pytest -q` — **1,253 passed in 192.55 seconds**, preserving the 1,199 baseline tests plus 54 new cases. Focused tests passed in 0.60 seconds. Tests used the existing uv cache with approved sandbox escalation and without dependency synchronization; no authenticated requests or live data were used.
