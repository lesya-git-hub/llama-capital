# Sprint 1I: monitoring and persistent-block approval gate

Follow-up: the conditional architecture approval authorized implementation.
See [operational_monitoring.md](operational_monitoring.md) for the implemented
read-only reconciler, strict version-3 migration, persisted enforcement, explicit
activation/recovery and the documented pre-activation race window. The assessment
below records the review that preceded approval.

Inspected baseline: `c43878f`, expected 747 tests. This is an architecture
assessment and implementation proposal; no reconciliation/blocking code or
database migration has been implemented at this gate.

## Architecture findings and evidence authority

- Broker version-1 ledgers are legacy/manual. Version-2 strict ledgers persist
  `execution_mode` and reject public manual fills. Broker startup calls
  `reconcile()` and may refuse a financially inconsistent ledger. Public reads
  such as `portfolio()`, `fills()` and `execution_state()` open BEGIN IMMEDIATE
  write transactions. These cannot supply a truly read-only independent capture
  of all evidence from a damaged ledger.
- `account.initial_cash` is the stored opening balance; `cash`, `realized_pnl`
  and `positions` are current materialized accounting state to verify, not
  unquestioned truth. Opening cash has no separate signed deposit history.
  An independently supplied expected opening-capital policy is needed to check
  the virtual EUR 10,000 assumption; configurable broker initial capital remains
  legitimate when explicitly expected.
- `orders` and sequenced `audit` events record lifecycle, kill enable/disable
  actions and execution order. `fills` records reference/slipped EUR prices,
  total commission, adverse per-share slippage, quantity through the order,
  allocated basis, cash delta and realized P&L. Those derived amounts need
  independent recomputation rather than merely summing stored cash deltas.
- Existing `reconcile()` rebuilds balances from stored fill cash deltas and
  allocated basis and compares account/positions; it does not independently
  rederive every slipped price, fee movement or basis allocation. The new monitor
  should independently implement the documented reconciliation formulas without
  changing the broker's authoritative execution/accounting algorithm.
- Strict fill authority is `gate_attempts`, with exactly one successful gated
  outcome per order, exact request/outcome hashes, before/after state, FX/risk
  records and broker/service source fingerprint. REJECTED attempts require
  unchanged before/after state and no fill. `gate_holdings` and `gate_order_terms`
  preserve stop/exit-cost and original USD instruction assumptions.
- `WorkflowStore` is a separate database containing immutable previews,
  authorizations, prepared steps, outcome references and content-addressed reports.
  The broker's committed gate outcome is the financial authority, not a workflow
  status label. A prepared step with an existing broker result but no journal
  result can be a recoverable post-commit gap. Conflicting IDs/hashes are not a
  harmless gap. A preview alone requires no authorization or fill.
- FX assumptions are embedded in conversion/gate/workflow envelopes: original
  source quote, direction, effective/retrieval times, policy and hashes. Existing
  replay functions can regenerate declared checks without executing. Synthetic
  scope and hashes establish neither real FX trust nor executable prices.

## Read-only reconciliation design

Use dedicated SQLite URI `mode=ro` connections with query-only mode and explicit
read transactions, rather than constructing a broker or journal object that
may initialize tables or run write transactions. Inspect application/schema
identifiers, table/column/index structure, integrity and foreign keys. Missing,
unreadable or corrupt tables must become findings, not implicit empty history.
Never create a missing source database or initialize/migrate it while reporting.

Capture canonical immutable records and a schema manifest from the broker and
each explicitly supplied workflow journal. Record file identities, supplied report
time, snapshot hashes, capture scope and failures. Do not use file-byte hashes
alone as logical snapshot identity (SQLite journals/WAL also matter). Separate
database captures are not an atomic cross-database snapshot: concurrent changes
can create apparent workflow gaps. Record that limitation and require a quiescent
capture or a confirmed recapture before declaring an ambiguous cross-file race
a proven integrity conflict. A broker snapshot itself is transaction-consistent.

Replay frozen captures without opening live ledgers, issuing orders, calling
execution methods, repairing journals or updating source files. Reports may be
written only to a separately selected output artifact. A manual entry point
should explicitly accept broker path, optional workflow paths, report ID/time
and expected opening cash; no scheduler or notification service is proposed.

### Independent financial reconstruction

Use Decimal precision 50, half-even twelve-place partial-sale allocation and
the broker's documented whole-order conventions. Recover fill sequence from
unique FILLED audit sequence entries, not timestamp sorting or an inner join
that could hide missing evidence. Check all raw fill/order/audit identifiers
and duplicate counts before reconstructing.

For a BUY, rederive adverse execution = reference + per-share slippage and cash
movement = -(quantity * execution + total commission); add that movement's
absolute amount to cost basis. For a SELL, execution = reference - slippage,
cash movement = quantity * execution - commission; allocate the exact remaining
basis on full exit, or half-even twelve-place weighted basis on partial exit;
realized P&L = net proceeds - allocated basis. Rebuild quantities, remaining
basis, cash and realized P&L after every fill, checking nonnegative resources
and all stored derived fill fields. Compute average entry cost only from rebuilt
basis/quantity, using the documented precision rather than a rounded display.

Compare reconstructed totals and every stored position against materialized
tables. Do not infer historical deposits, missing fills, prices or share events.
If sequencing or opening evidence is insufficient, report reconstruction as
incomplete; never fabricate a unique history. Cost basis is not market value.

### Lifecycle, gate and workflow checks

Reconstruct lifecycle and kill state in audit sequence order. Administrative
timestamps can be backdated under existing semantics, so timestamp ordering alone
cannot prove historical kill status. Require sufficient sequence evidence for
fill-after-cancel or fill-while-killed findings; identify missing evidence separately.
Compare current kill state to reconstructed events and enforce valid lifecycle
transitions while respecting existing idempotent retries, which append no duplicate
fill. Check schemas/uniqueness as well as duplicate records in malformed fixtures.

For every strict fill, require its unique successful gate outcome and agreement
between stored request/outcome hashes, order, broker fill, checked EUR costs,
before/after accounting and FX/risk provenance. Rejections cannot contain financial
mutations or fills. Read-only replay of compatible records supplements these
independent checks; an old source/environment fingerprint is a replay limitation,
not automatically proof that a historical fill was unauthorized. Preserve old
checkouts for complete historical replay, without rewriting old fingerprints.

Check workflow run identity, preview/authorization hashes, prepared requests,
gate attempt references and report step coverage. Classify a demonstrable
missing strict-fill audit or conflicting outcome as CRITICAL. A committed broker
outcome missing only its sidecar update can be WARNING when identity/hash/state
evidence proves that recoverable gap. Never resume the workflow from monitoring.
Partially completed or interrupted runs must remain visible in daily reporting;
intentional preview-only and HOLD/no-trade workflows are not missing fills.

## Findings and deterministic report

Use stable codes, explicit evidence references, descriptions and required operator
actions. Suggested codes include CASH_MISMATCH, HOLDINGS_MISMATCH,
COST_BASIS_MISMATCH, REALIZED_PNL_MISMATCH, FILL_ARITHMETIC_MISMATCH,
DUPLICATE_FILL, STRICT_FILL_WITHOUT_GATE, REJECTION_STATE_MUTATION,
AUDIT_LIFECYCLE_CONFLICT, KILL_STATE_CONFLICT, WORKFLOW_OUTCOME_CONFLICT,
WORKFLOW_COMMIT_GAP, INCOMPLETE_HISTORY and REPLAY_ENVIRONMENT_UNAVAILABLE.

Severity precedence is CRITICAL > WARNING > HEALTHY. Proven financial mismatch,
unauthorized strict fill or conflicting required audit is CRITICAL. Incomplete
but noncontradictory evidence or a proven recoverable sidecar gap is WARNING.
HEALTHY requires sufficient evidence for every declared required check, not
merely absence of a detected error. Missing required strict execution authority
must not be downgraded to a harmless warning. Unsupported/unreadable captures
cannot receive an unqualified HEALTHY result.

Report ID/time, source/schema identities, strict/kill/block state, cash, holdings
at cost, open/filled/cancelled orders, gate execution/rejection counts, workflow
runs/gaps, findings and actions are derived deterministically from the frozen
capture and explicit policy. Hash canonical report JSON; retain expected hashes
independently. Report synthetic FX/price limitations and omit invented market
equity, returns or investment performance. SQLite is not tamper-proof.

## Persistent operational block: approval required

No operational-block field/table or independent recovery authority currently
exists. The only persisted execution stop is `account.killed`. Reusing it would
not satisfy the task: `set_kill_switch(False)` could clear the stop without an
investigation, and preserving existing kill-switch behavior forbids silently
changing that method's meaning. A read-only report or orchestration-side flag
would also leave the strict fill path unprotected.

Recommended additive design for approval:

1. Persist a separate sticky operational latch plus append-only latch/recovery
   events in the strict broker database, binding critical report/snapshot hashes,
   triggering findings, block identity, actor and explicit timestamp. Version and
   migrate strict schemas transactionally; legacy/manual ledgers retain their
   current behavior and must not be advertised as monitoring-enforced.
2. Add an explicit state-bound command to apply a critical report. Read-only
   report generation itself performs no write. Applying the latch uses a broker
   write transaction and must confirm that its snapshot still matches the ledger
   (or reconcile current state under the same lock); otherwise reject stale input.
   The interval between reporting and applying is not protected, and must not be
   described as automatic instantaneous monitoring enforcement.
   Match the monitor's full logical broker snapshot (including fills, gate audits
   and schema), not only 1G's smaller execution-state hash. A manual
   inspect-and-latch command could instead capture/reconcile/latch under one
   broker write lock; keep the ordinary report/replay entry points read-only.
3. Check persisted latch state atomically in the shared strict fill path and
   strict gate before any new fill. Include it in expected execution-state identity
   so old previews are invalidated. Orchestration cannot bypass that broker check.
   Preserve read-only exact retries of already committed outcomes. Kill and
   operational block are independent: clearing one never clears the other.
4. Add an explicit recovery command bound to the active block ID, expected ledger
   state, investigated evidence, independently authorized recovery identity and
   a subsequent reconciliation result. Recovery must not edit cash, fills,
   positions, orders or old audits. Define its trusted authorization/verification
   boundary separately from user-controlled report/request fields; a mere string
   claiming to be an authorized operator is insufficient. Unauthorized, stale or
   wrong-block requests reject without releasing the latch.
5. A newer HEALTHY report does not clear the latch. Only the explicit authorized
   recovery action releases it. If kill remains enabled, fills remain blocked.
   Persist release evidence and retain the original critical history. Test restart,
   concurrent fill/block/recovery attempts and failure rollback before claiming
   enforcement. Do not add a scheduler or automatic recovery.

This requires approved broker-internal checks, additive public control APIs and
strict database migration. The Sprint 1I request explicitly says to stop before
those changes, so implementation is paused at this architecture gate.

## Proposed operator recovery procedure

Inspect critical findings; preserve consistent broker/journal snapshots including
WAL evidence using a safe SQLite backup procedure; identify affected IDs and
hashes; investigate against the retained source/code/environment. Correct the
underlying problem only through a separately approved process, never through an
automatic monitor repair. Capture/reconcile again. If justified, supply the
explicit independently authorized release bound to the original block and current
state; retain that release record. Keep the kill switch independent. A healthy
report alone is neither authorization to execute nor permission to rewrite history.

## Implementation and test scope after approval

Build independent read-only capture/reconciliation/report/replay, strict-latch
migration and fill enforcement, explicit latch/recovery controls and manual
documentation. Synthetic tests should cover healthy empty and BUY/SELL histories,
cash/quantity/basis/P&L and arithmetic corruption, duplicate/missing fills and
audits, rejection conflicts, workflow commit gaps, strict/legacy scope, kill/block
interaction, unauthorized recovery, restart, concurrent state changes, rollback,
stable hashes, source-file immutability and no external/execution calls from reports.
Preserve all 747 tests and run `uv run --no-sync pytest -q`.

No runtime files, schemas or tests changed at this gate. No orders, external
requests, dependency changes, commits, pushes or tags were introduced.
`scripts/sec_match_recon.py` was not modified or staged; no V1 tag was changed.

Baseline validation: `uv run --no-sync pytest -q` passed **747 tests** in
54.02 seconds. `git diff --check` passed. uv cache access required test execution
outside the filesystem sandbox; no dependency synchronization or installation
occurred. No new monitoring tests are claimed before implementation approval.
