# Sprint 1M — Offline provisional acquisition

Implementation: `providers/provisional_market_data.py`. This is a separate
recorded-response archive and normalizer. Existing 1C/1D models, calendar and
finality checks, production trust, signals, FX, trading, risk and execution are
unchanged. No provider transport, scheduler, retry worker or order path is added.

## Use and scope

An explicitly invoked `RecordedProvider.read_recorded(ticker, sessions)` supplies
a `RecordedResponse(metadata, body)` using bytes already available offline.
There is no default transport. The injected implementation is trusted local code;
the interface cannot sandbox arbitrary Python supplied by an application. The
shipped implementation performs no network request.

`ObservationMetadata` records fixture kind (`synthetic_test` or
`licensed_offline`), licensing reference, source/dataset/version/feed, ticker and
exchange, requested dates, calendar hash, aware acquisition start/end, optional
source timestamp and response ID, HTTP status/content type/encoding, pagination
state, optional retry-after value, exact raw SHA-256 and explicit predecessor ID.
Its only allowed status is `PROVISIONAL`. Missing source time stays `None`.

All bundled tests use invented synthetic data. No licensed vendor response,
account entitlement or usage right is supplied. `licensed_offline` is a caller's
provenance declaration, not a verified license or production classification.
The operator must establish permission to use, automate, retain and store any
actual fixture before supplying it. No live call is authorized or implemented.
Synthetic fixtures require a synthetic calendar; declared licensed offline
records use real-scope calendar context without establishing that it is trusted.
No calendar or evidence pins are added by these APIs.

The supported response format is explicitly **`recorded_ohlcv_v1`**, an offline
interchange format, not Massive/Polygon, Alpaca, Alpha Vantage or Yahoo JSON.
Do not label a transformed interchange fixture as an untouched vendor response.
A future vendor adapter must retain its original bytes and a separately approved
mapping/derivation; it needs its own implementation and licensing review.

The JSON root contains exactly `format`, `provider_id`, `dataset_id`,
`dataset_version`, `feed`, `ticker`, `exchange`, `currency`, `price_adjustment`,
`volume_adjustment`, `dividend_convention`, `split_convention` and `bars`.
Each bar contains exactly `date`, `open`, `high`, `low`, `close`, `volume`,
`dividend`, `split_ratio`. Numbers must be JSON numbers, not booleans or numeric
strings. Corporate-action fields must be explicit; absent events are not guessed.

Only USD, split-adjusted price and volume, `recorded_not_applied` dividends and
`events_recorded_prices_adjusted` splits are accepted. No split/dividend/FX
conversion or basis inference occurs. These labels remain supplied declarations;
normalization is not independent confirmation of the economic adjustment.

## Explicit operation

1. Construct `ProvisionalArchive(path)` in a dedicated application database.
2. Supply the calendar, aware `as_of`, stable batch ID and recorded provider to
   `acquire_recorded_batch`. Calendar structure, coverage and at least 200 completed
   sessions must validate before any recorded response is requested.
3. Each admitted response is committed as original BLOB bytes before decoding or
   normalization. Error statuses, invalid JSON and non-UTF-8 bodies can therefore
   remain inspectable even when normalization fails. Structurally invalid
   metadata, wrong raw hash or an over-budget body is refused before admission.
4. The pure normalizer validates exact source/symbol/exchange/calendar identity,
   chronology, expected dates, USD/basis, finite OHLCV/action values and schema.
   Duplicate JSON keys, duplicate/unordered/missing/extra session rows and unknown
   fields refuse; no trimming, repair, forward fill or fallback feed occurs.
5. A complete batch is written only after all six canonical tickers normalize
   from the archived bytes with one source/dataset version/feed/fixture kind and
   licensing reference. Failed acquisition leaves prior raw evidence/results,
   but no new complete-batch row. Existing batches are unchanged.

HTTP status must be 200, encoding UTF-8 and content type `application/json` for
normalization. The smallest implementation accepts one completely captured page
only: incomplete/multipage captures fail, never appear complete. Error bodies and
retry metadata are retained, but there are **no automatic retries**. Pagination,
vendor-specific normalization and bounded transport retries are deferred to a
separately approved adapter. This narrows the initial implementation to the
offline-first scope; it does not weaken the design's publication requirements.

## Immutability, revisions and replay

The separate SQLite archive uses its own application ID/schema. It refuses other
applications, incompatible versions and missing existing tables; it performs no
silent migration or repair. Missing files during use are not recreated. Its API
has no update/delete operation. This is API immutability, not a claim that a
privileged SQLite/filesystem owner cannot change evidence.

Observation IDs are immutable: an exact retry is idempotent, different bytes or
metadata under an existing ID refuse. SHA-256 binds both canonical metadata and
original bytes, with a separate raw hash. A new observation of the same source/
feed/ticker/requested-date window must explicitly identify its current predecessor.
The writer lock serializes competing revisions and prevents API-created forks.
Unknown/deleted/corrupt predecessors and backwards acquisition chronology refuse.
Stable repeated bytes remain separate observations when explicitly recorded as
revisions; they never acquire finality through repetition.

Normalization results or typed failure records are stored separately and never
overwritten. Failure records omit raw exception values; original bytes remain in
the protected archive. If a result/failure write cannot commit, an exception
propagates and no complete batch is written. Not every invalid API call can have
durable evidence, especially with invalid metadata or unavailable storage.

For successfully normalized observations, the archive also compares prior
normalized candles for the same fixture/source/dataset/feed/ticker across
**overlapping request windows**. Changed candle dates are recorded in immutable
conflict records linking both raw observations and normalization hashes.
`archive.conflicts(observation_id)` validates those links and exposes the detected
changes. This is a conflict report in archive order, not a determination of which
vendor value is true or a financial correction. No previously stored batch,
holding or signal is rewritten. A conflicting complete batch is still merely a
complete **PROVISIONAL** research artifact, never eligible trusted publication.

`archive.load_batch(batch_id, expected_sha256=...)` requires an independently
retained batch hash, validates membership/status, raw metadata/bytes and revision
chains, recomputes normalization and compares stored normalization evidence.
Missing/tampered evidence or a changed normalizer refuses. The fingerprint covers
this module, existing candle/calendar/signal models and Python, Pydantic and tzdata
versions. Retain that environment and source for replay; do not refresh the
fingerprint or overwrite old outcomes just to make a changed implementation pass.

Parsing preserves raw numeric spellings in the original bytes. Deterministic
normalization parses decimal lexemes before conversion to the existing strict
float `Candle` fields and uses existing `canonical_json`/`input_hash` for candle
and snapshot identity. Equivalent numeric spellings can yield identical candle
hashes while retaining different raw/observation hashes. This is intentionally
not a change to the existing numeric contract or an FX calculation.

## Strict trust boundary

`ProvisionalDailyProvider(archive, batch_id, expected_sha256=...)` implements the
existing `fetch_daily(ticker, sessions)` boundary and requires exact archived
session selection. Every returned `ObservedTicker` has a clearly unverified
finality label and **every availability record has `final=False`**.

The adapter supplies no completion proof, finality flags, trust pin or verified
publication method. Even separately pinned invented evidence cannot promote
these observations through `freeze_verified_daily_inputs` or
`ingest_verified_daily_signals`. A default real trust root also rejects synthetic
scope before publication. No existing validator was changed.

## Six approval safeguards and evidence

1. Acquisition/licensing: no network transport or accounts; explicit offline
   provenance/reference; synthetic test fixtures only. No licensing approval is
   assumed. See `test_replay_has_no_transport_or_execution_dependencies`.
2. Immutable evidence: original BLOB, metadata/hash, immutable IDs and predecessor
   chain. See `test_roundtrip_exact_bytes_metadata_hashes_and_restart_replay` and
   `test_exact_invalid_or_nonutf8_bytes_survive_normalization_failure`.
3. Deterministic validation: exact identities, sessions, times, OHLCV, currencies,
   bases and action fields. See the parameterized normalization/metadata failures
   and `test_raw_decimal_spellings_preserved_with_deterministic_normalized_hashes`.
4. Trust boundary: strict PROVISIONAL models and `final=False` at provider boundary.
   See `test_provisional_never_published_even_with_pinned_proof_and_stable_hash`
   and `test_provisional_ingestion_cannot_publish_any_verified_run`.
5. Revision/replay: immutable conflict links, explicit predecessor and raw replay.
   See `test_changed_overlapping_windows_are_durably_detected_and_replayed`,
   `test_concurrent_revision_writers_cannot_fork_a_request_history`, tampering,
   missing-evidence and normalizer-change tests.
6. Failure isolation: no batch success before all-six validation and commit.
   See `test_transport_failure_has_no_complete_batch_and_does_not_change_prior`,
   `test_failure_in_complete_batch_insert_leaves_raw_but_no_success` and
   `test_normalization_write_failure_does_not_lose_raw_or_complete_batch`.

## Limits and remaining Gate B blockers

Raw bodies are admitted up to 8 MiB; revision-chain validation caps at 10,000
entries. SQLite lock waits are two seconds. Conflict detection scans prior
normalization history and is not a measured 90-day capacity/SLA guarantee.
There is no automatic retention, deletion, alerting, quota management or remote
backup. The operator must protect licensed bytes, database location and disk
capacity. Flush/transaction behavior does not establish physical power-loss
durability or tamper resistance; hashes are not signatures or license grants.

Gate B remains NO-GO: no accepted real provider/license, authoritative production
calendar, completion/revision attestation or production trust admission exists.
This module neither resolves corporate-action booking nor supplies real FX,
execution prices/timing, authenticated operator controls, pinned experiment risk
policy, scheduling, deployment or the remaining Sprint 1L operating requirements.
No simulated order or financial-state API is called by acquisition/replay.

See [market_data_onboarding_design.md](market_data_onboarding_design.md) for the
approved architecture and public-source assessment, and
[operational_readiness_audit.md](operational_readiness_audit.md) for launch gates.
Independent review is required before any further provider integration or commit.

## Validation and changed files

Validation completed 2026-11-09 using only invented offline fixtures:

- `uv run --no-sync pytest -q tests/test_provisional_market_data.py tests/test_offline_market_data.py tests/test_market_verification.py tests/test_daily_signal_pipeline.py`
  — **148 passed in 38.68 seconds**.
- `uv run --no-sync pytest -q` — **922 passed in 118.82 seconds**:
  all 858 baseline cases plus 64 new cases.
- `git diff --check` passed. The exact pytest commands required sandbox escalation
  to access the existing uv cache. No dependency installation occurred.

Implementation files added: `providers/provisional_market_data.py`,
`tests/test_provisional_market_data.py` and this guide. The earlier
`docs/market_data_onboarding_design.md` remains present and unchanged during this
implementation. No existing runtime/test file was changed.

The protected script's pre-existing worktree modification remains separate and
unchanged (SHA-256
`7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`).
No simulated orders, live provider requests, production trust entries, commits
or pushes were made. Stop for independent review.
