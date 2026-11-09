# Sprint 1G: architecture approval gate

Follow-up: Option B was explicitly approved and implemented. See
[gated_execution.md](gated_execution.md) for the actual APIs, savepoint rejection
guarantees, creation-only strict-mode policy, validation and remaining limitations.
The proposal below records the review that preceded that approval.

Inspected baseline: `578e06d`. This is a proposed design, not implemented
execution functionality. Work stops at the request's Phase 1 approval gate.

## Findings

`PaperBroker` owns one SQLite connection. Its public state/lifecycle methods
independently acquire `BEGIN IMMEDIATE` through `_transaction()`. In particular,
`portfolio()`, `reconcile()`, `fills()` and `simulate_fill()` cannot be nested
inside another such transaction. Calling them sequentially from a service leaves
a race between risk evaluation and mutation. Checking a ledger hash before a
separately committed fill would leave the same race.

One write transaction is technically feasible if the broker is refactored to
expose an internal transaction-scoped state reader and its existing fill logic
without opening a nested transaction. SQLite's write lock then serializes
competing writers, including other connections using legacy lifecycle methods.
Keep accounting in that broker helper; do not copy fill accounting into a second
service, patch transaction methods at runtime, or write economic tables through
another ledger implementation.

Current manual `simulate_fill` checks accepted status, timing, kill switch,
positive slipped execution, cash and holdings. It does not enforce 1E portfolio
limits. It is a bypass if retained unrestricted on the same ledger. Existing
tests and documentation explicitly depend on manual fills and durable
`FILL_BLOCKED` events after failed checks. Silently routing all fills through a
new mandatory risk gate would break public behavior and tests.

The broker stores cash, aggregate cost basis and holdings, not USD marks, stops,
FX provenance or pending execution-cost assumptions. CREATED and ACCEPTED orders
reserve nothing and contain only identity, side, ticker, quantity and timestamps.
Never derive risk stops from average cost or pretend missing pending prices are
zero. A gated request needs complete explicit synthetic marks/stops/costs for all
current holdings and all other outstanding instructions, or must reject.

`pretrade_risk` is pure and can run under the write lock. Its current conservative
SELL policy requires the whole projected portfolio to satisfy limits; a sale
that reduces risk but leaves a breach is rejected. Preserve that policy unless
separately approved. Pending BUYs consume projected resources; pending SELLs
reserve shares but do not fund BUYs. Exclude the target order itself from pending
orders during its final evaluation to avoid counting it twice.

`fx_conversion` can run under the same transaction: it validates effective age,
retrieval causality, explicit direction and synthetic scope, and converts USD
marks, stops and costs into existing EUR risk inputs without approving orders.
Use one frozen quote for every valuation and fill field within a request. Never
substitute the signal close for an execution price. `offline_market_data`
observations remain provisional; `market_verification` completion evidence and
trust pins are not execution authority. No trusted-production mode is supported
by the proposed service; reject that mode outright, including synthetic or
unverified inputs, rather than inventing production FX/provider trust.

## Proposed compatible implementation (Option A)

Add an explicit manually invoked synthetic execution service for existing
ACCEPTED orders, with broker-owned transaction integration. Keep all existing
public signatures and legacy semantics; extract private transaction-scoped
helpers and add only a new gated entry point. No automatic creation/acceptance
of orders, scheduler, signal loop, real mode or external transport.

The single broker connection performs this sequence under `BEGIN IMMEDIATE`:

1. Read current account/kill state, positions, pending instructions and ledger
   identity. Check a caller-supplied expected state hash/version inside the lock;
   reject stale assumptions. Never accept caller cash or quantities as truth.
2. Bind the complete request hash to the order ID. An exact committed retry
   returns its prior outcome without a second fill; a changed payload conflicts.
   Retries are reads, not new executions, so a kill switch cannot trigger a new
   mutation through idempotency. Reject a legacy fill without gate evidence.
3. Match the target order's ticker/side/quantity and all supplied pending metadata
   to current broker rows. Require exact coverage for stop/cost assumptions and
   marks. Missing or conflicting coverage rejects. Retain source assumptions
   and their timestamps; do not silently overwrite prior holding risk metadata.
4. Validate explicit synthetic execution price, signal availability timestamp,
   valuation timestamps and one frozen FX quote. Require execution strictly
   after signal availability; quote effective/retrieval times and mark/source
   availability cannot be later than execution. Apply explicit freshness limits.
5. Build EUR risk inputs from the locked cash/holdings/pending state using 1F,
   then evaluate the current policy using 1E inside the lock. Require approval.
   Independently retain broker cash, holdings, timing and kill checks.
6. Apply the existing accounting helper using precisely the same converted EUR
   reference price, commission and adverse slippage used by the risk engine.
   Persist the broker fill/audit and the gated request, input hashes, locked
   state, full FX/risk evidence, policy and resulting state in that transaction.
7. Commit once. Any unexpected failure, including audit insertion, rolls back
   all economic and success-evidence writes. Restart cannot expose half a fill.

Concurrency is handled by the write lock, not preliminary advisory approval.
For two competitors against the same expected state, at most the first mutation
can succeed; the second must reject stale state or be explicitly resubmitted
with a new request identity and reevaluated current state. Expected-state identity
should include cash, holdings/cost basis, kill state, pending IDs/status/quantities
and committed lifecycle/audit version so intervening cancellations/acceptances
are observable. Audit metadata must not recursively hash itself.

Proposed rejection handling: ordinary gate rejection commits rejection evidence
only, with no economic mutation or target status change. Unexpected exceptions
roll back the entire attempt. This distinction preserves reconstructible risk
rejections without claiming that a durable rejection record is a rolled-back
transaction. Legacy failed-fill auditing remains unchanged. Malformed requests
that cannot be serialized/identified can fail validation before opening a
transaction. A rejected gate attempt is not a broker ACCEPTED-to-REJECTED
transition. Retries of the same rejected request return its recorded rejection;
changed assumptions require a new attempt ID while preserving the same target
order identity and conflicting-success protection.

Additive evidence tables in the broker database are preferable to a separate
database: evidence and balances then share the exact SQLite transaction. Do not
destructively migrate old ledgers. Gate-managed ledger identification, schema
checks and migration/rollback tests are part of implementation after approval.
If legacy fills or changes make durable stop/pending assumptions incomplete,
subsequent gated requests must fail closed until explicit complete assumptions
are supplied and checked; never silently recover them from cost basis.

**Option A limitation:** legacy manual fills remain available and bypass 1E.
Only the new service is risk-gated. The entire broker cannot be advertised as
risk-enforced. SQLite files remain editable by their owner; audit is neither
signed nor tamper-proof. Transaction integrity does not authenticate input prices.

## Alternative (Option B): opt-in enforced ledgers

Persist an irreversible or explicitly administered ledger-mode choice for a new
strict synthetic ledger. Disable direct legacy fills on those ledgers; require
the new gated path. Default existing ledgers retain manual behavior, preserving
the original 690 tests. This needs an approved new public mode/API, additional
schema/migration rules and explicit scope for legacy access restrictions.
No ledger mode may claim trusted-production execution. Direct SQLite edits remain
outside application enforcement. A global mandatory gate on every old ledger
would be a broader incompatible change and is not proposed.

## Approval required before implementation

The Sprint 1G request explicitly says: "STOP FOR APPROVAL before implementation
if the architecture requires changing existing broker semantics or public APIs."
It also requires approval if closing a legacy bypass breaks compatibility.
Choose A (new additive gated service with explicitly documented manual bypass)
or B (additive gated service plus opt-in strict ledgers disabling direct fills).
Approval should include the above rejection-audit distinction and unchanged
conservative SELL policy. No broker/runtime code has been modified at this gate.

## Validation planned after approval

Synthetic tests must cover approved BUY/SELL, every portfolio/risk/cash constraint,
exact FX/price/timestamp binding, kill switching, missing assumptions, stale
state, exact/conflicting retries, two independent SQLite connections competing,
changes after preliminary advice, failures after balance updates and evidence
insertion, restart/reconciliation, reconstructed audit hashes and legacy bypass
behavior. No tests will contact external providers or real brokers. Preserve all
690 existing cases and run `uv run --no-sync pytest -q`.

No dependencies, credentials, orders, commits, pushes or tags were introduced.
The pre-existing `scripts/sec_match_recon.py` modification was not touched or
staged. No V1 release tag was changed.

Baseline verification: `uv run --no-sync pytest -q` passed **690 tests** in
22.63 seconds; `git diff --check` passed. uv cache access required running the
tests outside the filesystem sandbox; no dependencies were synchronized or
installed. No new execution tests are claimed before implementation approval.
