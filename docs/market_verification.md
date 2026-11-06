# Strict exchange calendar and candle finality — V2 Sprint 1C

The strict entry point is `tools.verified_daily_pipeline`. It reuses Sprint 1B's
`Session`, `SessionSchedule`, frozen OHLCV inputs, V1 signals and SQLite run store.
It does not implement a second calendar rule engine, infer holidays, or generate
official schedules. The legacy Sprint 1B API remains an **unverified research
interface**, as approved; calling it directly does not provide 1C verification.

**No authoritative schedule or provider-finality artifact was available locally.**
None was downloaded. The default real-world `TrustRegistry()` is empty and
therefore rejects every run before provider ingestion or signal generation.
The repository's new fixtures are invented synthetic test data, not official
exchange dates, mappings, or completion evidence.

## External authority and trust pins

`tools.market_verification.CalendarArtifact` version 1 contains:

- Source and version, scope (`real` or `synthetic_test`) and availability time.
- End-exclusive New York date coverage and a versioned ticker-to-exchange mapping
  for all six stocks. Exchange identifiers are XNYS and XNAS. No current real
  instrument mapping is guessed or bundled.
- Sessions extending the existing 1B `Session`: trading date, exchange, source,
  version, timezone-aware opening time and official closing time.
- An explicit closed-date record for every non-session date on every covered
  exchange, including a reason: weekend, holiday, exceptional or other official
  closure. A missing date is an error, not an inferred weekend or previous price.

Record source/version must match the artifact. Dates must be covered and unique,
with sessions chronological for each exchange. Open and close timestamps must
match the trading date in America/New_York and satisfy the existing 1B validators.
UTC timestamps are preserved as instants; existing `zoneinfo`/tzdata handles New
York date/DST interpretation. There is no hardcoded weekday close in production
code. DST and early-close tests exercise explicitly supplied synthetic timestamps.

The mapping applies to the artifact's entire coverage window. Listing changes
within that window need a correctly scoped external artifact; mixed listing
history is not inferred. If the two exchanges have different session dates or
times, the existing shared-calendar pipeline cannot represent them: adaptation
fails closed instead of silently intersecting schedules or filling missing bars.

A `TrustPin` identifies artifact kind, source, version, scope, exact canonical
content SHA-256 and an external authority-review reference. `TrustRegistry` is
supplied separately by the caller, not trusted from a run's embedded metadata.
Its default mode is `real` with no pins. The application must independently
review an authoritative source and control these pins; computing a hash of an
untrusted file and calling it a pin is not authority verification. Source labels,
hashes and review-reference strings are not digital signatures or proof of origin.

Synthetic mode must be explicitly selected and all artifacts/pins must match
that scope. Reports retain `synthetic_test` scope and a warning. Synthetic pins
cannot authorize a real-mode run. No real trust entries ship with this code.

## Named finality verifier

`verify_candle_finality` implements method
`pinned_completed_session_evidence_v1`. It requires both the calendar and a
`ProviderEvidenceArtifact` to match externally controlled exact-content pins.
Publication delay is an explicit nonnegative integer policy setting; no default
delay is guessed.

Provider evidence is versioned and scoped, records when it became available,
and contains exactly one proof for every ticker/date in the frozen batch. Each
proof binds ticker, exchange, trading date, the exact V1 candle hash (including
OHLCV and corporate actions), provider evidence ID, issuance time, official close,
and explicit `provider_final` and `completed_session` booleans. Duplicate proof
identifiers, missing proofs, extra proofs and mismatched dataset sources fail.

The verifier requires all of the following:

1. Valid V1 OHLCV and exact session/calendar coverage for all six tickers.
2. The candle maps to an authoritative open session for its recorded exchange.
3. Its pinned proof matches that candle hash and official close, and explicitly
   attests both finality and completed-session representation.
4. Verification is strictly after the official close and at or after close plus
   the configured publication delay.
5. Evidence was issued no earlier than close and no later than observation
   fetch completion. The evidence artifact and fetched data were available by
   verification, and verification is no later than the decision timestamp.
6. Existing 1B finality and availability checks still pass. A provisional candle
   is never automatically promoted to final by this layer.

A delayed Yahoo response, `final=True`, or a named always-true callback alone
does not meet these requirements. The Yahoo adapter remains provisional by
default. No production verifier feed is implemented: real provider confirmation
must be independently obtained and pinned, with truthful completion semantics.
The code verifies that declared evidence matches frozen inputs, not that an
arbitrary administrator is honest or that a provider can never revise data.

## Strict workflow

Use validated external artifacts and observations; no example below downloads
data or contacts a broker:

```python
from tools.historical_snapshot import input_hash
from tools.market_verification import TrustRegistry, VerificationPolicy
from tools.daily_signal_pipeline import DailySignalStore
from tools.verified_daily_pipeline import (
    freeze_verified_daily_inputs, publish_verified_daily_signals,
    load_verified_daily_signals,
)

trust = TrustRegistry()  # Empty: REAL runs must fail until independently reviewed pins exist.
policy = VerificationPolicy(publication_delay_seconds=configured_delay)
inputs = freeze_verified_daily_inputs(
    calendar_artifact, observed_tickers, provider_evidence_artifact,
    policy=policy, verified_at=verification_time, decision_at=decision_time, trust=trust,
)
expected = input_hash(inputs)  # Preserve independently.
with DailySignalStore("runs/daily_signals.sqlite3") as store:
    report = publish_verified_daily_signals(store, "unique-run-id", inputs,
                                           expected_sha256=expected, trust=trust)
    replayed = load_verified_daily_signals(store, "unique-run-id",
                                          expected_sha256=expected, trust=trust)
```

`ingest_verified_daily_signals` optionally orchestrates an explicit existing
`DailyOHLCVProvider` call per ticker. It checks pinned authority before calling
the provider. Verification and decision times must describe when the fetched
data and completion evidence were actually known; do not backdate them. Any
provider or verification failure prevents the entire batch from being published.

`replay_verified_daily_signals` regenerates every evidence check before delegating
to 1B signal generation. It requires the separately supplied trust registry and
expected input hash. It compares persisted verification records to regenerated
records, checks source fingerprints and timezone database version, and retains
1B's code/Python/dependency provenance checks. It never fetches data.

## Persistence and compatibility

`VerifiedDailyInputs` embeds 1B inputs, calendar and provider artifacts, policy,
verification time, external trust-registry hash, verification-source fingerprint
and one verification record per candle. Records persist calendar source/version,
exchange, official close, verification method/time, provider source/version,
evidence identifier/hash and candle hash. Reports expose these with the original
daily decisions, artifact identities and explicit scope.

The existing daily SQLite store gains an additive `run_verification` table,
using the same account-free store/application identifier. A run and its verification
metadata commit atomically. Failure inserting evidence rolls back the run row.
Matching retries are idempotent; differing or removed verification metadata under
an existing run ID conflicts. Old 1B rows remain readable as unverified and are
not silently upgraded. Strict loading rejects rows without proof metadata.

Existing schema-version-1 daily stores can acquire this additive table without
rewriting old records; there is no destructive migration. Frozen old experiments
retain their original source/commit requirements, so replay under changed code
still requires the recorded checkout, as before. No old hashes are relabeled.
The strict wrapper adds its two source files and installed tzdata version to its
fingerprint; it uses the already available timezone data without installation.

## Tests and limitations

```powershell
$env:UV_NO_SYNC = '1'
uv run --no-sync pytest tests/test_market_verification.py -q
uv run --no-sync pytest -q
```

Tests cover synthetic open/closed dates, exceptional closures, early closes,
spring/fall DST, invalid coverage/order/timezones, missing/untrusted authority,
insufficient provider proofs, publication delay, causal timestamps, provisional
candles, failed providers, six-ticker atomicity, metadata rollback, restart replay
and trust/tamper rejection. They do not establish the accuracy of real exchange
calendars or provider evidence. No official calendar facts are claimed from these
invented fixtures.

Real-world signals remain blocked until trusted artifacts and completion evidence
are supplied. The legacy 1B interface is intentionally still available for
unverified research, not a route to claim strict verification. There is no
automatic trust discovery, digital-signature infrastructure, live finality feed,
calendar acquisition, FX conversion, order creation/execution, or strategy change.
USD prices remain separate from the EUR paper ledger. No investment edge or
operational trading readiness is claimed.
