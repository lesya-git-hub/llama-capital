# Sprint 1J: operational safety hardening design — approval required

Follow-up: Option B was conditionally approved. See
[operational_safety_hardening.md](operational_safety_hardening.md) for the implemented
transaction boundaries, fault/concurrency evidence and remaining limitations.
The assessment below records the proposal before approval.

Inspected baseline: `dea7a13` on `main`; stated regression baseline: 774 tests.
This document is the architecture assessment required before implementation.
No runtime, accounting, risk-policy, schema or test changes are made at this gate.

## 1. Existing guarantees and their limits

The inspected sources are `providers/paper_broker.py`, `tools/gated_execution.py`,
`tools/operational_controls.py`, `tools/operational_monitoring.py` and
`tools/paper_orchestration.py`, their tests and operational documentation.

### Financial execution and idempotency

- The broker owns a connection and uses BEGIN IMMEDIATE for write transactions.
  New strict fills read state, validate risk and mutate balances/orders/fills
  under that same writer reservation. SQLite serializes other writers.
- Shared broker accounting preserves whole-order long-only execution, cash/share
  checks, weighted cost basis, commissions, adverse slippage and realized P&L.
  No replacement execution or accounting algorithm is needed.
- Gate attempt IDs bind exact request hashes. Exact committed retries return
  the original result; conflicting payloads reject. One successful gate record
  per order is additionally protected by a partial unique index. A new attempt
  against an already filled order cannot create another fill.
- A savepoint encloses fill/lifecycle/assumption writes. Rejection rolls those
  writes back, verifies unchanged state and commits only a rejection audit.
  Failure persisting the outer audit rolls back the whole transaction. An
  exception before commit is not a durable rejection unless that audit commits.
- Historical exact-result retries are reads, not new fills. Returning a prior
  result while controls are active must remain distinguishable from execution.

### Controls, migration and reporting

- Strict schema version 3 persists an operational latch and control-event journal.
  Gate and shared strict-fill helper check the latch inside the write transaction.
  Missing/inconsistent control state fails closed rather than resetting it.
  Strict manual fills reject; version-1 legacy/manual behavior remains separate.
- Kill switch and operational latch are independent. A healthy report releases
  neither. Recovery needs a current state-bound report, current block identity,
  explicit reason and a separately supplied trusted local authorization verifier.
  Authorizer absence/failure denies release; valid denials have durable evidence.
- Version-2 strict migration runs as additive DDL inside broker initialization's
  transaction. Existing financial/audit rows are not rewritten. Startup financial
  reconciliation occurs after that migration transaction commits: startup failure
  does not mean a previously committed metadata migration was rolled back.
- Reports use read-only SQLite snapshots and independent Decimal accounting.
  They do not activate controls, repair history or execute orders. Corrupted
  financial rows can be inspected without constructing a broker that rejects them.
- Current `activate_operational_block` reserves a writer, verifies a previously
  captured report against current broker data and atomically stores latch plus
  activation audit. **It does not reserve a writer during the earlier detection.**

### Workflow recovery

The workflow sidecar commits a prepared exact request before calling the broker.
The broker then commits its outcome independently. Sidecar outcome/report saving
can fail afterward. This is a real two-database gap, already covered by recovery
through the broker's stable attempt ID. Recovery must retrieve/reconcile that
outcome; it must not create a replacement order or new attempt ID to hide the gap.
There is no atomic batch or distributed transaction.

## 2. Concrete scenarios and severity

### A. CRITICAL detection before latch activation — safety-critical gap

A read-only report finds missing gate authority or another CRITICAL violation.
Before activation obtains BEGIN IMMEDIATE, an existing strict fill can reserve
the writer, pass the currently unblocked latch and commit. Activation then rejects
its stale report. This is tested behavior, not an atomicity defect in SQLite.
The fill/latch operations are individually serialized; detection was outside both.

No new design may describe ordinary read-only reporting as automatic protection.
Fills before a coordinated command acquires its writer are outside its guarantee.

### B. Critical older history while the latest control state looks valid

`read_control` checks current fields and walks backward through denials to the
latest activation/release. It is not a full history reconciliation. An older
corrupt gate/control record can therefore be detected by monitoring without
being discovered by a simple current-latch read. This is a gap between an
operational-state guard and an integrity preflight, not proof of a fill generated
by the current API without its transaction. Once a latch commits, new fills block.

### C. Fill, latch, recovery or audit failure before commit

SQLite rollback/savepoints already protect economic atomicity if the connection
and transaction remain usable. More failure stages need deterministic coverage:
after cash/position changes, after fill/status writes, after latch/release updates,
before their audit insert, and at COMMIT. Never turn a storage error into an
apparently successful fill, release or durably stored block.

If a SQL error aborts the entire transaction, savepoint rollback can also fail.
The result must be an exception with no claimed durable rejection or latch;
financial consistency is checked after reopening. A report is not a substitute
for a commit acknowledgement.

### D. Lost/failed acknowledgement after a successful COMMIT

The caller may not know whether its request committed. Retrying with a new ID
could duplicate intent across orders; retrying the same ID is the supported path.
The broker's current `_transaction` unconditionally executes ROLLBACK after an
exception, including a commit exception. If COMMIT already ended the transaction,
that cleanup can mask the original error with a no-active-transaction error.
Propose a minimal cleanup correction: rollback only when a transaction remains,
preserve the original failure/cause, and resolve outcome through durable IDs.
Do not claim an acknowledged rollback after an uncertain commit.

### E. Migration interruption

An exception between creating the control singleton/table, event table and version
update must leave either the original version-2 schema or the complete version-3
schema. No unblocked replacement may be synthesized for partially existing control
tables. Test the migration transaction itself; distinguish it from the subsequent
startup reconciliation transaction. Preserve every original row and strict flag.

### F. Recovery races and unsafe retry

A fill attempted while blocked either observes the block or, if recovery commits
first, has an old expected-state identity and rejects. Concurrent releases against
one snapshot cannot both mutate it. A rejected gate attempt must remain rejected
after release; recovery is not authorization to reinterpret that attempt as a fill.
New execution requires a new explicitly authorized request/state as already defined.

### G. Unreadable SQLite or unusable control storage

Failure to open/read/lock the database means reconciliation or durable latching
cannot be proved. Stop execution and report that limitation. Never claim a latch
was stored if COMMIT/audit failed, and never recreate missing tables to clear a
block. Existing corrupt-schema paths already fail on open or control access.

## 3. Proposed alternatives and recommendation

### Option A: coordinated manual reconcile-and-latch only

Add a distinct, manually invoked operational command. It opens an existing strict
ledger, acquires BEGIN IMMEDIATE **before capturing/checking broker state**, runs
the independent checker over that frozen capture, and, when CRITICAL, writes
activation evidence and latch before the same COMMIT. Ordinary monitor/replay
functions stay read-only.

This eliminates detection-to-latch interleaving **within this command**. A concurrent
fill either commits before the command obtains its lock and is included in the
capture, or waits and sees the committed latch. It does not make future fills
run reconciliation, and the old read-only report/explicit-activation workflow
still has its documented gap. New corruption after a healthy check remains
undetected until another inspection. Lowest execution-path semantic change.

### Option B — recommended: coordinated command plus strict-fill preflight

Implement Option A and run the same broker-scoped integrity preflight inside
every transaction that could create a new strict fill. Place it in the shared
gate's transaction path, not only in the orchestration wrapper. Preserve exact
committed-result reads as idempotent reads before considering a new fill.

For a CRITICAL broker result, persist the latch/evidence before financial mutation
and return a gate rejection under the same outer transaction. If inspection or
control/audit persistence fails, propagate failure and perform **no fill**; a
later new-fill request must run preflight again rather than trusting cached health.
This prevents a failed latch write from becoming permission to execute.

Keep the current severity policy: CRITICAL blocks; warnings are not silently
reclassified as critical. Unreadable/malformed required broker evidence cannot
be treated as a successful preflight. Preserve the monitor's documented handling
of historical source/environment mismatches and separately scoped workflow evidence.
No risk threshold, strategy or trading feature changes are proposed.

Option B adds execution-time cost and can reject requests previously accepted
against an unlatched but inconsistent ledger. That safety semantic change requires
explicit approval. Do not describe Option A alone as equivalent to Option B.

### Not recommended

- Cached healthy reports or prechecks followed by a separate fill transaction:
  they leave a state-change race unless validated under the final writer lock.
- Calling the current read-only `monitor()` from inside a writer and then calling
  `activate_operational_block()`: those open other connections/transactions rather
  than sharing one proven transaction and can cause locking/staleness failures.
- An asynchronous latch worker, automatic retries with new IDs, automatic audit
  repair or a second execution/accounting implementation.
- Assuming ATTACH or WAL makes the broker and workflow files an atomic whole.

## 4. Exact transaction and locking design for approval

Extract a small **transaction-scoped control persistence helper** that accepts an
already reserved connection and never issues its own BEGIN/COMMIT. Existing
explicit activation remains a wrapper with its original report/state validation;
the coordinated path supplies a report captured under the same lock. Reuse
`capture_connection` and pure `reconcile_snapshot`; do not give report generation
implicit write side effects.

Proposed strict new-fill path for Option B:

1. Existing broker wrapper acquires BEGIN IMMEDIATE on its owning connection.
2. Validate strict/schema/control identity; resolve exact committed retries without
   creating another outcome or fill.
3. Capture required broker evidence on that connection, then independently check
   it. Do not open another broker connection or call nested public transaction APIs.
4. On CRITICAL, persist latch plus control evidence using the locked helper. The
   existing gate captures its `before` state **after that control change**, sees
   the active latch and records REJECTED with equal before/after gate states.
   This ordering matters: changing control state inside an existing rejection
   savepoint can either roll the latch back or violate the current before==after
   rejection contract. Neither shortcut is acceptable.
5. Otherwise execute the existing risk/FX/gate/fill path. The gate and accounting
   helper still check the persisted latch. No financial mutations precede preflight.
6. Commit control/gate evidence and any permitted fill once. If outcome/audit
   persistence fails, roll the outer transaction back and return failure. A
   subsequent new-fill attempt reruns integrity checks. Never claim a durable
   block or rejection when that commit did not succeed.

The manual coordinated command uses capture/check/latch/COMMIT without issuing
any order or calling execution. An already active latch is preserved, not replaced
or cleared by a healthy result. Missing/corrupt control storage cannot be safely
reinitialized by this command: return explicit failure, retain read-only diagnostic
options, and keep strict execution refused.

Use one connection per worker/thread, existing SQLite locking and bounded busy
timeouts. Do not share a connection across threads, disable locking, use dirty
reads or rely on network-filesystem locking. A writer reservation blocks other
writers while allowing snapshot readers where SQLite/journal mode permits it.

Capture, integrity checks and replay can scan history and read source files;
lock duration is workload-dependent and must be measured, not advertised as
constant or instantaneous. No network calls, remote authorization or unbounded
operator interactions belong under this lock. The current recovery verifier is
trusted local code and must remain side-effect-free/bounded; reentrant broker
writes or user interaction inside it are unsupported. Do not introduce an unsafe
thread-cancellation timeout to interrupt a transaction mid-write.

Workflow reconciliation remains separately captured forensic evidence. Broker
writer reservation does not lock live workflow journals. Cross-file findings
must retain their stated capture/quiescence limitations and must not be described
as atomically checked by this broker-only preflight. A broader distributed
snapshot/locking design is outside this minimal hardening proposal.

## 5. Migration and compatibility risks

Prefer **no new database schema**: current control events can retain critical
report/snapshot identities, findings, actor/reason/time and code fingerprint.
Use deterministic operational action IDs tied to the request/check identity and
retain existing exact/conflicting-retry semantics. Confirm event envelopes remain
compatible with current independent control-audit verification before coding.

Do not change legacy version-1 fills, strict-mode persistence, current version-2
to version-3 migration, control/kill independence, SELL policy, risk thresholds,
FX direction or source trust classification. No automatic release or amendment
of a rejected execution is introduced.

Source fingerprint changes can make historical full replay unavailable under the
new checkout. Preserve old evidence/fingerprints; report the archived-code
requirement as already documented. Never relabel old records to the new source.
Existing tests asserting rejection identity and idempotency remain required.
New preflight-generated control state must not break the gate rejection contract.

SQLite transaction isolation is not a blanket guarantee of power-loss durability.
Record/inspect journal mode, synchronous settings and integrity; do not silently
change them or claim crash guarantees beyond SQLite plus the underlying local
filesystem. Unreadable storage and uncertain commit acknowledgement require
inspection/retry by original identity, not guessed financial recovery.

## 6. Deterministic test and failure-injection plan

Use synthetic data and temporary real SQLite files. No arbitrary process kills.
Prefer SQLite authorizer-denied operations, transactional trigger failures,
connection proxies or narrowly scoped private test hooks over timing sleeps.
Hooks must not create a production bypass or alter default transaction behavior.

Fault stages:

- Fill after account/position writes, after fill/status writes, before gate audit,
  and immediately before outer COMMIT: reopen and compare economic state/audits.
- Commit executes but acknowledgement raises: preserve the error, reopen, resolve
  the original durable attempt and prove exact retry cannot create another fill.
- Latch update before activation audit/commit: either both persist or neither;
  under Option B no new strict fill may proceed on persistence failure.
- Recovery after clearing fields but before release audit/commit: latch remains
  active on rollback; kill state is untouched. Denial audit failure cannot release.
- Migration after each DDL/version stage: reopen as the complete original or
  complete migrated schema, preserving original balances/orders/fills/audits.
- Whole-transaction abort versus savepoint-only rollback: assert what is actually
  durable and never manufacture a rejection record after an unconfirmed rollback.

Concurrency tests use independent connections and explicit barriers/events at
known transaction stages. Demonstrate which contender owns BEGIN IMMEDIATE,
rather than relying on scheduler luck or fixed sleeps. Cover:

- Same order/same request, same order/conflicting requests, and different orders
  competing for limited cash/exposure with no over-allocation.
- Coordinated critical inspection versus fill: a blocked writer cannot slip
  between detection and committed latch.
- Fill versus recovery: blocked or stale-state rejection as appropriate; release
  cannot execute an old rejected attempt. Two releases cannot both mutate state.
- Kill enable/disable versus fill with sequence-consistent outcomes and no implicit
  operational unblock.
- Reopen/retry after every failure, including broker-commit/sidecar-write gaps,
  preserving pending statuses and exact result/audit identities.

Run focused failure/concurrency tests first, then `uv run --no-sync pytest -q`.
Preserve the stated 774 existing tests. If sandboxing blocks the command, request
permission for that exact test command; install/synchronize/download nothing.

## 7. Remaining limitations and approval scope

Neither option is continuous background monitoring. Option A closes only its
coordinated command's window. Option B adds broker-scoped checking at each
explicit new-fill call, but neither guarantees the truth of synthetic prices,
cross-file atomicity, malicious owner-edit detection, authenticated human identity
or physical-storage durability beyond documented SQLite/filesystem behavior.
Legacy fills remain outside strict enforcement. Frozen report replay cannot
prove that a historical external runtime error actually occurred.

Unreadable SQLite or failed audit/COMMIT means no durable latch can be promised.
Refuse execution, expose the error and require explicit investigation. Do not
silently reconstruct history or auto-clear controls to make a test pass.

**Approval requested:** Option B (recommended) — a manual coordinated
reconcile-and-latch command, mandatory broker-scoped preflight before every new
strict fill, minimal transaction-cleanup corrections where failure tests prove
necessary, and deterministic failure/restart/concurrency tests. Ordinary reports
stay read-only, existing recovery authorization stays explicit, and no new schema
is planned. Option A is available if only the narrower manual-command guarantee
is desired; its residual fill-before-next-check window must remain explicit.

Implementation and tests are intentionally deferred until this design is approved.
The 774-test baseline is the supplied baseline, not a new regression result from
this architecture-only turn. No external requests, dependencies, trading activity,
commits, pushes or tag changes were performed. The pre-existing
`scripts/sec_match_recon.py` modification was not touched, staged, reset or discarded.
