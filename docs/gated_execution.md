# Sprint 1G: opt-in strict synthetic execution

Implements approved Option B from [the architecture assessment](atomic_execution_design.md).
Only explicit, manually invoked offline synthetic simulation is supported.

## Ledger modes and public APIs

`PaperBroker(path)` still creates a legacy version-1 ledger by default. Existing
ledgers preserve all prior manual lifecycle/fill behavior, including accepted
orders reserving neither shares nor cash and durable legacy FILL_BLOCKED events.
**Legacy ledgers remain unrestricted by portfolio risk policy.** This is not a
claim that every broker instance is risk-enforced.

Create a **new** strict ledger with `PaperBroker(path, strict=True)`. Strict mode
uses persisted schema version 2 and an `execution_mode` record. Reopening without
the keyword inherits strict mode; `strict=False` rejects a downgrade. Opening an
existing legacy ledger with `strict=True` rejects rather than silently migrating
old holdings without stop provenance. Use a separate new strict ledger. A strict
schema relabeled as version 1 fails closed; older version-1 code also rejects a
version-2 ledger. There is no supported downgrade or automatic migration.

Strict ledgers retain explicit creation, acceptance, cancellation, rejection and
kill-switch APIs. They reject `simulate_fill`, including retries, before any
execution. The internal shared accounting helper also requires an active write
transaction and gate authorization on strict ledgers. `execute_gated(request)`
is the sole supported strict execution path. No constructor, import, state read,
order acceptance or signal calls it automatically.

`execution_state()` returns immutable canonical JSON of account, positions,
orders, last broker audit sequence, strict flag and persisted USD risk assumptions.
Pass `input_hash(state)` as the expected state identity. The last audit sequence
detects lifecycle/kill changes even if balances return to previous values.
Gated rejection records are excluded from that identity so recording a rejection
does not itself invalidate an otherwise unchanged financial/lifecycle snapshot.

## Explicit request contract

`ExecutionRequest` contains a distinct attempt ID, target order ID, expected state
hash, execution timestamp, signal-availability timestamp, execution-price timestamp,
the existing 1F `RiskConversionRequest`, one frozen canonical FX quote and explicit
FX/risk policies. The target USD proposal ID must equal the broker order ID and
its ticker, side and whole-share quantity must exactly match an ACCEPTED order.
No request creates or accepts an order.

USD execution prices, marks, stops, total commissions and adverse per-share
slippage must be explicitly supplied synthetic fixtures. The EUR cash and holding
quantities supplied to the compatibility boundary must exactly match the locked
broker state. Missing holdings, marks, pending instructions or persisted stops
fail closed. All CREATED/ACCEPTED orders except the target must appear with exact
IDs, statuses, tickers, sides and quantities. The target is excluded from pending
orders when evaluating itself; it is never counted twice.

The source snapshot's timestamp is preserved. Require execution strictly after
signal availability; a close-derived signal therefore cannot fill at that same
close. The separately supplied execution price must be timestamped at execution.
These are fixture declarations, not proof of market executability. FX effective
and retrieval times must not exceed execution time and effective age must pass
the explicit policy. Marks retain the older of source mark and FX effective
timestamps and also pass 1E freshness. All prices/stops/costs in one attempt use
the same quote. No provider is fetched. Production mode is unsupported and
rejected; unverified FX cannot enter this synthetic gate. Synthetic FX scope
does not establish real-world source trust or candle finality.

## Atomic risk and accounting

The broker owns one `BEGIN IMMEDIATE` write transaction around the complete
operation. After acquiring that lock the service rereads actual cash, holdings,
kill status, target status, all pending orders and stored assumptions. It checks
the expected state under the lock, converts with 1F, and runs the unchanged 1E
evaluator against that consistent state. Preliminary advisory approval is never
accepted as final authorization.

Risk policy remains configurable and caller-selected with the existing defaults:
20% individual exposure, 80% invested, 20% cash reserve, 1% per-position planned
stop risk, 4% aggregate planned stop risk. Pending BUYs consume resources; pending
SELLs reserve existing shares without funding BUYs or freeing risk capacity.
**SELL policy is unchanged:** even a risk-reducing SELL rejects if the entire
conservative projected portfolio still breaches a policy limit. Holdings,
commissions, adverse slippage and nonnegative cash are checked for SELLs too.

On approval, the extracted broker accounting helper applies exactly the same EUR
reference price, total commission and per-share slippage that the risk engine
checked. There is no second accounting implementation. Weighted cost allocation,
realized P&L, whole-order fills, broker time checks, cash/holdings checks, kill
checks, audit ordering and precision remain the original broker behavior.

The write lock serializes independent SQLite connections, including concurrent
kill/lifecycle operations. A request with old expected state is rejected after a
competing mutation; it cannot execute using its preliminary risk approval. Kill
activation linearizes before or after an in-progress transaction, not halfway
through one. A kill committed before final evaluation blocks that attempt.

## Rejection and failure guarantees

Inside the outer write transaction a `gated_financial_attempt` savepoint encloses
all possible financial, lifecycle and risk-assumption writes. For a rejected
attempt, including an exception after partial fill writes:

1. Roll back to the savepoint and release it.
2. Reread ledger state and require exact equality with the pre-attempt state.
3. Clear any tentative fill output and record a REJECTED outcome.
4. Insert only the gated audit record, then commit the outer transaction.

The target remains ACCEPTED; this is not an ACCEPTED-to-REJECTED broker transition.
A risk rejection can include its REJECTED risk decision. A later execution fault
can include an APPROVED risk decision plus an execution-failure reason. Neither
is reported as a fill. Any tentative FILL_BLOCKED/FILLED broker audit entries
inside the savepoint are rolled back along with balances and order status.

Rollback failure or state mismatch propagates immediately to the outer rollback;
the code never commits rejection evidence after an unverified rollback. If audit
insertion fails, the outer transaction rolls back **all** writes, including a
successful fill and its gate assumptions. The caller receives an exception, not
a falsely durable rejection or success. Process interruption before commit also
leaves no committed partial fill. Storage failure cannot promise an audit write;
an operation is reported as durably rejected only after the atomic commit succeeds.

## Persistent assumptions and idempotency

Successful attempts persist original USD stop/exit-cost assumptions per holding
and original USD proposal terms for the target and every outstanding order.
Future requests must match those records rather than reducing apparent risk by
silently changing stops or costs. Partial sales retain the remaining fixed exit
commission; full exits remove holding metadata. Top-ups require the same stop
and adverse stop slippage as the existing holding and add the new estimated
exit commission. Different-stop tranches and stop amendments need a later
explicit design; they are rejected here. Changing frozen pending terms requires
cancelling and replacing that instruction with a new order ID. The system never
invents missing stop or pending-price assumptions from cost basis.

An attempt ID binds one exact canonical request hash. The same committed request
returns its stored result without a new fill, even after restart or kill activation
(a read-only retry). Reusing that attempt ID with a different payload raises a
conflict. A new attempt against an already FILLED target rejects. A partial unique
index additionally permits at most one successful gated record per order.
Rejected attempts are also immutable/idempotent; updated assumptions or state
require a new attempt ID. One filled target can never fill again under another ID.

## Audit and replay

`execution_attempt(attempt_id)` loads and checks the stored outcome/request
hashes. An `ExecutionOutcome` embeds the complete request, before/after ledger
state, FX input/output envelope, risk decision/policy, fill details, reasons and
combined broker/service source fingerprint. Request/FX/risk envelopes retain their
own canonical hashes and source identities. Store an expected outcome hash
independently if you need an external integrity reference.

`replay_execution_checks(outcome, expected_sha256=...)` is side-effect free: it
checks integrity/source identity, regenerates recorded FX/risk checks and verifies
that filled instructions match those checked inputs. It never executes again or
reconstructs financial accounting through a second algorithm. Use the existing
broker `reconcile()` (also run on restart) to reconstruct balances, cost basis
and P&L from committed fills. Error-audit replay cannot prove a recorded runtime
failure happened. Preserve the original checkout/environment for old fingerprints.

SQLite owner access, arbitrary SQL edits, Python monkeypatching/private attribute
tampering and malicious caller policy/fixture declarations are outside this
application-level API boundary. This is neither a signed nor tamper-proof ledger.
Audit hashes do not establish real market-data authority. Limits use estimated
stops/costs, not guaranteed executable prices, liquidity or bounded losses.

## Validation scope

Synthetic tests cover compatible BUY/SELL, all requested risk limits, insufficient
cash/shares, pending coverage and frozen assumptions, USD/EUR binding, missing/
stale/future FX and invalid timing, kill behavior, exact/conflicting retries,
restart and manual/internal-helper bypass rejection, competing connections,
post-advisory changes, financial and evidence insertion faults, durable rejection
recovery, audit integrity/replay and disabled external transport. Existing tests
continue to cover legacy accounting and its manual lifecycle. No external data,
credentials, dependencies, commits, pushes, tags or unattended execution were
introduced. `scripts/sec_match_recon.py` was not modified or staged.

Validation results:

- Focused: `uv run --no-sync pytest -q tests/test_gated_execution.py tests/test_paper_broker.py tests/test_pretrade_risk.py tests/test_fx_conversion.py`
  passed **154 tests**.
- Final regression: `uv run --no-sync pytest -q` passed **722 tests** in
  37.31 seconds: all 690 existing cases plus 32 new gated-execution cases.
- `git diff --check` passed. uv cache access required tests outside the
  filesystem sandbox; no dependency synchronization or installation occurred.
