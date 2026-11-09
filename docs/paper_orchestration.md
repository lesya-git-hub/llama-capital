# Sprint 1H: manually authorized synthetic orchestration

Inspected baseline: `78c5b8c`, 722 existing tests. The new service is
`tools.paper_orchestration`; existing broker, strategy, risk, FX, market-data and
verification APIs and semantics remain unchanged.

## Architecture assessment

Sprint 1B represents each condition as `DailyDecision` (ticker, variant, side or
HOLD, session date, decision time and fixed strategy metadata). Canonical hashes
identify conditions and their frozen daily inputs. These remain position-independent
research conditions; `order_submission_allowed=False` is never flipped. The new
workflow requires separately supplied manual trade intents, pre-staged broker
orders and exact preview authorization. It does not turn signals into automatic
instructions or change strategy variants/parameters.

Sprint 1C's `VerifiedDailyInputs` embeds snapshot, session schedule, exact candle
proofs and trust/environment fingerprints. The orchestrator regenerates its
report with `replay_verified_daily_signals`, rather than accepting a mutable report
label or implementing another signal engine. Only synthetic-test scope is allowed.
An externally supplied synthetic `TrustRegistry` must match the exact registry
recorded by 1C and pin the execution calendar too. Include that calendar pin when
freezing source inputs; extending a registry afterward invalidates existing 1C
root identity. No check is weakened to accommodate a different registry.

The source snapshot preserves USD, OHLCV adjustments and provider/evidence hashes.
Provisional output from `offline_market_data` cannot be promoted into final candles
by this orchestrator. Synthetic fixtures need their own explicit synthetic proofs.
No real provider evidence or real trust pins are created. Default real trust stays
empty, and neither production-verified input nor execution mode is supported.

Sprint 1F validates frozen FX direction, market-effective/retrieval timestamps,
staleness and numerical conventions, and produces synthetic EUR risk inputs.
Sprint 1E supplies the advisory preview and final marked exposure metrics.
Sprint 1G alone supplies execution authority: `execute_gated` rechecks expected
state, kill status, risk, pending orders, FX and accounting under one SQLite write
transaction. Its outcome and attempt ID are the restart recovery authority.

No existing public API or transaction model changes were needed. The orchestrator
uses public broker state/gate/attempt APIs and one read-only `PRAGMA database_list`
query on its connection to bind authorization to a file-backed ledger path. It
never writes broker financial tables or calls unrestricted manual fill methods.

## PREVIEW

Manually stage the desired orders as CREATED then ACCEPTED on a strict ledger
using the existing lifecycle APIs. The orchestrator creates or accepts no orders.
Supply a `WorkflowInput` containing:

- A stable run ID, frozen synthetic `VerifiedDailyInputs` and expected hash.
- An externally pinned synthetic execution `CalendarArtifact`, with explicit
  sessions, listings and closed dates; no weekday/session inference.
- One explicit strategy variant for the six-stock batch.
- A `RiskConversionRequest` context containing initial EUR cash, USD marks,
  existing holdings/stops and outstanding-order assumptions.
- Ordered `TradeIntent` entries: exact selected-signal hash, manual USD proposal,
  synthetic execution time/price-time/availability, explicit frozen FX quote and
  FX/risk policies. At most one intent per ticker/order; all source valuation and
  pending tickers must belong to MSFT, AAPL, JPM, XOM, JNJ or WMT.

Call `preview_workflow(..., broker=..., store=..., preview_at=..., trust=...)`.
This reads a strict-ledger snapshot, validates/replays the sources and persists
an immutable `WorkflowPreview` in a separate journal. It creates **no broker
orders, lifecycle events or fills**. `human_preview` renders signals, proposed
USD trades and advisory risk results. Missing trade intents and HOLD signals are
SKIPPED; invalid intents or exceeded risk limits are REJECTED. Structurally invalid
inputs, invalid roots or invalid source replay fail before saving a preview.

Each selected signal is recorded, even when it produces no trade. Proposed orders
use all outstanding BUY/SELL assumptions in the existing conservative risk engine.
Initial cash, quantities and held stop assumptions must agree with the broker's
snapshot/persisted metadata. All recalculated contexts are revalidated before
hashing so Decimal representations remain stable through JSON round trips.

## Timing and FX boundaries

Preview cannot precede source signal availability. The source valuation and FX
quote must already be available at preview; a fresh retrieval cannot renew an
old FX effective timestamp. Explicit synthetic execution prices cannot be
presented as known before their declared availability. Execution-price time must
equal execution time. Signals must execute strictly after their decision time,
inside an explicitly supplied later trading session, strictly after the signal's
session date. Same-close execution is unconditionally rejected in this sprint.
Execution intents must be chronological, in the caller's explicit order.

Every intent carries its own explicit FX observation; there is no last-rate cache.
Only 1F's canonical EUR_PER_USD wrapper is accepted, including its explicit
reciprocal provenance when used. Quote validity is checked at preview and again
at its planned execution. Equity amounts stay USD in the frozen intent; cash and
broker accounting remain EUR. No float price is inferred from the signal close.

All timestamps are supplied simulation instants, not assertions that an actual
market fill occurred. No wall clock, quote polling, executable liquidity evidence,
scheduler or real-world data feed is introduced.

## EXECUTE and authorization

Create an explicit `Authorization` with purpose `execute_synthetic_workflow`,
run ID, exact preview SHA-256, authorization ID, operator ID and aware authorization
timestamp. Preview time <= authorization time <= every proposed execution time.
Pass it explicitly to `execute_workflow`; null/missing authorization cannot execute.
These are local manual authorization declarations, not cryptographic signatures
or remote authentication. Merely generating a preview never invokes execution.

The preview hash binds the full input snapshot, signal identities, execution
calendar, initial ledger state, ledger file identity, order intents, prices, FX,
costs, policies, preview time, trust root and orchestration source hash. Changing
any of those invalidates authorization. Run IDs and authorizations are immutable
in the journal. Use a new run/preview/authorization after a genuine input or state
change. File-path binding prevents accidentally reusing authorization on another
identical ledger; it is not a cryptographic database identity and does not protect
against owner-level database replacement or restoring older backups.

Execution first replays all preview-critical checks. It then handles only PROPOSED
steps, in explicit intent order, via the existing strict gate. Preview approvals
are never submitted as final risk decisions. SELL policy and the handling of
cash, concentration, stops, fees and pending orders are unchanged from 1E/1G.
Risk-reducing SELLs can still reject when the whole portfolio remains over a limit.

## Batch semantics and state transitions

The batch is **a sequence of independently gated orders**, not an atomic batch.
Earlier successful fills remain committed if a later order rejects or errors.
Reports contain all six signal outcomes, including rejected, skipped and
not-attempted entries, and explicitly disclose partial execution.

Authorization binds the fixed transition rule
`carry_forward_only_own_gate_outcomes_v1`. The first request uses the exact preview
state. Later requests may carry forward only cash, holdings, stops and lifecycle
state from the immediately preceding committed gate outcome of this workflow.
They retain the original authorized prices, FX, marks, costs, policy and signal
identities. The orchestrator reads that frozen state; it performs no fill accounting
or guessed reservation updates. Each reconstructed request still needs a fresh
atomic gate evaluation with its expected state hash.

An intervening outside mutation produces a stale-state rejection in the broker.
The orchestrator records it and stops subsequent attempts; it never adopts that
unrelated state to continue under old authorization. Kill activation is therefore
rechecked by the gate too. Final ledger cash is captured where available; marked
exposure is omitted when the state chain drifted or valuations cannot be validated.
No raw broker cost basis is mislabeled as current exposure.

## Journal, crash recovery and retries

`WorkflowStore` is a separate, application-identified SQLite file containing
immutable previews, exact authorizations, prepared requests, broker outcome
references and content-addressed complete reports. Use a dedicated file, not the
broker, source archive or daily-signal ledger. The sidecar and broker are **not**
a distributed transaction.

Before invoking a gate, the exact deterministic attempt ID and request are committed
to the workflow journal. If preparation fails, no broker attempt is made. After
the broker commits, its full hash-checked outcome is saved in the journal. A
process may stop between those commits. On a later **explicit** execute call with
the same authorization, the orchestrator retrieves the broker's durable attempt
by ID, checks its request hash, replays its checks and repairs the sidecar. It
does not send another fill for an existing outcome. If no attempt exists, only
the originally prepared, state-bound gate request can be submitted. No automatic
resume worker exists.

Each prepared request/outcome is immutable. Conflicting or corrupted references
stop processing rather than authorize a replacement attempt. A rejection is
durable in the broker when it reached 1G; preview-only rejection has workflow
evidence and no broker attempt. Journal errors after a committed fill cannot undo
that fill; the report may be INTERRUPTED or its save may raise. Reinvoke manually
to recover using the persisted broker attempt. Never delete the broker audit or
change attempt IDs to force a retry.

## Reporting and replay

`human_preview(preview)` and `human_report(report, preview=preview)` provide concise
text with synthetic warning, workflow status, proposed USD trades, risk results,
filled/rejected/skipped/error counts, EUR cash/exposure when available, FX IDs and
broker attempt references. Persisted models retain full FX and input provenance,
execution timestamps, signal IDs, authorization identity, before/after states and
policy parameters through their preview/outcome references. COMPLETED can mean
all HOLD/no-trade signals were skipped; it does not imply any investment return.

`replay_preview` regenerates source verification, signals, FX conversion and
advisory checks against the frozen preview state and external trust root.
`replay_workflow_report` validates an independently retained expected report hash,
authorization/signal references, authorized request/state-transition chain and
each embedded 1G outcome using its existing read-only replay function. It issues
no broker fills and requires no current broker connection. Use the broker's
`execution_attempt` and `reconcile` APIs separately to verify actual persisted
attempt references and reconstruct financial balances. Preserve the original
checkout/environment, workflow journal, broker database, external trust root
and expected hashes for repeatability.

Replay verifies declared frozen evidence and calculations. It cannot prove a
historical runtime error happened, authenticate fixture data, prove every embedded
reference still exists in a separately supplied live database or repair missing
input artifacts. SQLite files and local authorization declarations are not
tamper-proof. Scope labels, hashes and synthetic proofs confer no real-world
market-data trust. Legacy ledgers remain unrestricted and are rejected by this
orchestrator. Production publication/execution remains blocked.

No external requests, credential/dependency changes, unattended execution,
strategy changes, commits, pushes or tags were introduced. No V1 release tag was
changed. `scripts/sec_match_recon.py` was not modified or staged.

## Validation results

- `uv run --no-sync pytest -q tests/test_paper_orchestration.py tests/test_gated_execution.py --tb=short`:
  **57 passed**.
- `uv run --no-sync pytest -q`: **747 passed** in 82.60 seconds, preserving
  all 722 existing tests and adding 25 orchestration integration cases.
- `git diff --check`: passed. Test execution required access outside the
  filesystem sandbox for uv cache initialization; no dependencies were installed
  or synchronized.

Coverage includes preview without fills, exact authorization and ledger binding,
changed inputs/state/FX, same-close rejection, source trust and strict-mode
separation, successful BUY/SELL, HOLD skipping, risk rejection, partial batches,
kill switching, repeated execution, process interruption after broker commit,
journal errors, invalid audit references, replay and blocked external transport.
