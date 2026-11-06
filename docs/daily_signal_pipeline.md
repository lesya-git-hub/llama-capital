# Daily USD market data and research signals — V2 Sprint 1B

**Trust boundary:** this is the legacy, unverified research interface. A source
name or `final=True` does not authenticate exchange or provider authority. Use
the [Sprint 1C strict verification entry point](market_verification.md) for pinned
calendar and provider-evidence checks. Existing 1B behavior remains unchanged;
its runs are not silently promoted to trusted runs.

This is an explicitly invoked, paper-research pipeline. It generates decisions,
not orders, and does not import or call the paper broker. Its universe is fixed:
AAPL, JNJ, JPM, MSFT, WMT and XOM. No scheduler or automatic trading is added.

## Approved contracts

- A frozen, explicitly supplied US session schedule determines expected sessions
  and actual open/close timestamps, including holidays and early closes. Missing
  schedule coverage fails closed. There is no guessed weekday/16:00-close calendar.
- Both baseline and BEAR-filtered mean reversion are recorded as position-independent
  BUY / SELL / HOLD research conditions. SELL does not assert a position exists.
- Any provider failure, stale/missing/incomplete data, invalid metadata or evidence
  prevents publication of the entire six-ticker run. No partial batch is published.

US stock prices remain **USD**. The virtual broker ledger remains **EUR**. No
price is interpreted as EUR, no FX conversion is performed, and every decision
has `order_submission_allowed: false`. Even BUY/SELL records cannot be submitted
to the broker through this pipeline. A separately validated FX and order-policy
layer would be required; none is implemented here.

## Frozen schedule and observation evidence

`models.daily_signals.SessionSchedule` version 1 records:

- Calendar `US_EQUITIES`, a named schedule source and when it was available.
- Explicit timezone-aware coverage start/end, with an exclusive end.
- Unique increasing session dates and timezone-aware opens/closes, normalized
  to UTC. Session labels are plain ISO daily dates, not intraday timestamps.

The schedule must cover the decision instant and have been available by then.
Its producer attests completeness, including omitted closed days. This code
does not independently certify holiday, DST, emergency closure or early-close
accuracy. A missing trading date cannot be inferred from an incorrect schedule.
Synthetic test schedules identify themselves and are not real exchange calendars.

The provider interface returns `ObservedTicker`, containing a V1 `TickerSnapshot`,
fetch-completion timestamp, a named finality evidence source, and one dated
availability/finality record for every candle. Validation requires:

```text
session close <= candle availability <= fetch completion <= decision timestamp
```

All candles must be explicitly final, valid finite OHLCV, and match **every**
completed session in the supplied coverage window. At least 200 complete candles
are required for both variants' indicators/regimes. The latest candle must be
the latest completed scheduled session; missing a middle session common to all
tickers is also rejected. Incomplete/future extra rows are rejected rather than
silently trimmed. Duplicate dates and missing prices fail V1 snapshot validation.
All six ticker calendars must match. Availability timestamps cannot be inferred
retrospectively from a historical candle's date.

Each snapshot must declare USD, the matching calendar, split-adjusted prices
and volume, recorded-but-unapplied dividends, and already-adjusted split events.
This avoids raw split discontinuities or dividend-adjusted inputs changing the
V1 signal basis. Provider adjustment declarations remain external attestations;
their truth is not verified by the schema. Corporate actions are preserved, not
applied to positions or used to claim total-return performance.

## Existing logic and interpretation

The pipeline calls V1 `evaluate_mean_reversion`, `generate_mean_reversion_exits`,
`classify_market_regime` and `filter_entries_by_regime`. SMA50, the 5% discount,
RSI14 recovery through 30, ATR14, and regime parameters are unchanged. The
configuration is versioned, fixed and recorded, not an optimization interface.

Each ticker produces two records dated at its latest complete session. SELL
means the SMA50 exit condition is true; otherwise BUY means an entry condition
is true; otherwise HOLD. The filtered variant suppresses entries classified
BEAR and leaves exits unchanged. V1 high-volatility regime precedence is retained.
No holdings, stop execution, fill sizing, broker cash or FX are consulted. These
are end-of-day conditions intended for separate later-session evaluation, not
same-close fill instructions. The original simulators are unchanged.

## Ingestion and provider reuse

`providers.daily_ohlcv_provider.DailyOHLCVProvider.fetch_daily(ticker, sessions)`
is the narrow OHLCV/evidence interface. The existing close-only interface cannot
carry OHLCV or timestamps, so it is left unchanged. An optional
`YahooDailyOHLCVProvider` reuses `download_historical_data` and its validation.
Only an explicit fetch call can access market data; imports and replay never do.

**Yahoo has no per-candle finality flag in the existing loader.** Consequently,
the adapter returns provisional rows by default, which the decision pipeline
rejects. A caller must provide an actual `finality_verifier(ticker, candle)` and
named `finality_source`, or use a provider exposing finality evidence directly.
An always-true callback is not real evidence and must not be used operationally.
Exchange closure alone is not treated as proof of vendor finality. Later vendor
revisions remain possible even with an attestation.

The Yahoo adapter requires corporate-action columns, explicitly converts its
zero split-event sentinel to the V1 no-event ratio of 1, and rejects non-midnight
daily indexes. Availability is conservatively recorded after fetching and
verification, not backdated to the exchange close.

`ingest_daily_signals(provider, schedule, store=..., run_id=...)` fetches all six
tickers and records the decision clock after fetching. An injectable clock is
available for deterministic tests. If a new session closes during ingestion,
the final completeness check fails instead of publishing the prior session as
fresh. A fixed `decision_at` may be supplied for already observed/offline data;
it cannot precede the evidence's fetch or availability timestamps.

This sprint made no market-data requests. All tests use synthetic data or a
mocked downloader. It does not connect any broker API.

## Persistence, identity and offline replay

`DailySignalStore` uses a **separate** local SQLite file and application/schema
identifier, rejecting a paper-broker ledger. One transaction publishes one row
containing the complete frozen schedule, observations, V1 snapshot, effective
configuration, signal date, decision timestamp, source/runtime provenance,
input hashes and the twelve decisions. Failures never publish a partial row.

`freeze_daily_inputs` creates the immutable input bundle. `input_hash` and
`canonical_json` reuse V1 canonical serialization. Ticker response order and
equivalent timezone offsets normalize without changing the hash. The input
identity includes the decision time, availability evidence, schedule, config
and environment. Provenance fingerprints the daily pipeline/provider/models and
the V1 signal/indicator/regime code in addition to existing source provenance.

```python
from tools.historical_snapshot import input_hash, canonical_json
from tools.daily_signal_pipeline import (
    DailySignalStore, freeze_daily_inputs, load_daily_inputs, replay_daily_signals,
)

# schedule and observed are validated frozen objects from explicit input artifacts.
inputs = freeze_daily_inputs(schedule, observed, decision_at=decision_timestamp)
expected = input_hash(inputs)  # Preserve independently with the run record.
with DailySignalStore("runs/daily_signals.sqlite3") as store:
    report = store.publish("daily-unique-run-id", inputs)
    restored_inputs, restored_report = store.load("daily-unique-run-id", expected_sha256=expected)

# To replay exported canonical input JSON, without any provider call:
loaded = load_daily_inputs("daily_inputs.json", expected_sha256=expected)
assert canonical_json(replay_daily_signals(loaded, expected_sha256=expected)) == canonical_json(report)
```

Export `canonical_json(inputs)` and `canonical_json(report)` using explicit caller
file I/O if desired. Repeated publication with the same run ID and exactly the
same inputs/report is idempotent across restarts. Changed data, evidence, config
or decision time under that ID raises a conflict; old results are never overwritten.
Resume a completed run by loading it with the preserved expected hash rather
than refetching and replacing its evidence. Deliberate new observations require
a new run ID. No run ID automatically creates a broker order.

Loading checks data/report hashes, indexed metadata and exact regenerated output.
Replay requires matching recorded Git commit, execution-source fingerprint,
Python version and dependency versions. It does not repair environments or
install dependencies. SHA-256 is integrity evidence, not authentication against
coordinated database edits. The store has no automatic backups or migrations.

## Verification and remaining limits

In PowerShell with the existing environment:

```powershell
$env:UV_NO_SYNC = '1'
uv run --no-sync pytest tests/test_daily_signal_pipeline.py -q
uv run --no-sync pytest -q
```

Tests freeze deterministic synthetic weekday/early-close schedules and candles,
then exercise six-ticker processing, both real V1 variants, causality, stale and
incomplete data, provider errors, transactional publication, hashes, restart
idempotency and the absence of broker actions. Synthetic BUY/SELL outcomes are
not historical performance evidence.

Operational deployment still requires a trustworthy complete session schedule,
real candle-finality evidence and honest adjustment metadata. No finality feed,
automatic calendar acquisition, scheduler, provider retry policy, failed-run
archive, FX layer, order bridge, or trading service is supplied. There is no
claim of profitability or unattended paper-trading readiness.
