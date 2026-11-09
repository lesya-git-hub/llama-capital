# Sprint 1J: Option B implementation and evidence

Implements the conditionally approved [design](operational_safety_hardening_design.md)
against baseline `dea7a13` (774 tests). Offline synthetic, explicit manual calls
only. No new trading capability, risk threshold, strategy or database schema.

## What changed

Every **new strict gate attempt** now runs a broker-scoped integrity preflight
inside the broker's existing BEGIN IMMEDIATE transaction. Exact committed-result
retries remain read-only history retrieval and do not create another fill.

`strict_preflight_locked` captures the owning connection, runs the existing pure
independent reconciler and, on CRITICAL, persists a sticky latch and activation
evidence before financial processing. Healthy checks are not cached. Warnings
are not silently converted to CRITICAL. Failed/unreadable checks or failed audit
persistence propagate failure, never permission to fill. Existing active latches
are preserved without replacement or release.

The shared accounting helper requires the gate's transaction-scoped integrity
marker as well as its existing authorization and latch checks. Both markers are
set only around the checked accounting call and cleared in a finally block. No
public manual strict-fill bypass was added. Legacy version-1 behavior is unchanged.

`reconcile_and_latch` is a distinct manually invoked operational command: it
reserves the writer before broker capture/reconciliation and commits any CRITICAL
latch plus audit together. It calls no order or fill APIs. Ordinary `monitor`,
report serialization and replay remain read-only and never change control state.

## Proven transaction boundary

The supported strict call path is:

1. `PaperBroker.execute_gated` enters its existing `_transaction`: BEGIN IMMEDIATE.
2. `execute_locked` resolves an exact prior committed request without creating a
   new attempt. For a new known target it invokes preflight on the same connection.
3. Preflight reads and reconciles the consistent broker snapshot while retaining
   that writer reservation. No competing writer can commit between these checks
   and its latch write.
4. On CRITICAL, `_activate_locked` writes control metadata and activation evidence
   without issuing BEGIN or COMMIT. It preserves observed/expected finding details,
   report/snapshot hashes, source fingerprint, origin and broker-snapshot identity.
5. Only then does the gate capture its rejection `before` state and create its
   financial-attempt savepoint. It sees the latch and records REJECTED. Equal
   before/after rejection evidence is preserved; the latch is not inside the
   savepoint that ordinary rejection rolls back.
6. The outer broker transaction commits once. Any outer audit/commit failure rolls
   back all uncommitted writes; no successful fill, block or durable rejection is
   claimed. A subsequent new attempt runs preflight again, including if a previous
   latch write failed. There is no cached healthy result to bypass a failure.

For the manual command, `_open` obtains BEGIN IMMEDIATE before capture;
`inspect_and_latch_locked` captures/checks/writes on that connection; the command
alone commits. Neither transaction-scoped helper begins a second connection or
commits the caller's work. The returned receipt is durable only after the owning
wrapper successfully commits.

The automated preflight uses the ledger's declared opening-capital anchor to
preserve legitimately configured accounts other than EUR 10,000. It independently
checks financial history against that anchor; it does not authenticate the
original deposit. Manual inspection can still supply an independently expected
opening capital via `MonitoringPolicy`. Risk limits and SELL policy are unchanged.

## Race elimination and precise remaining boundaries

Within the coordinated command and every new strict-fill preflight, the
broker-scoped **capture/check-to-latch race is eliminated by the owning SQLite
writer reservation**. A competing fill cannot commit between the CRITICAL check
and latch commit. If latch persistence fails, that strict attempt performs no
financial mutation and the next new attempt must check again.

This is not an assertion of continuous monitoring or universal distributed
atomicity:

- A fill that commits before the coordinated command obtains its writer is
  outside that command's interval; the subsequent capture includes it. Each new
  strict fill still runs its own integrity preflight.
- Ordinary read-only reports and the older separate report/activate API remain
  separate observations/actions. A report alone never writes a latch. Current
  broker CRITICAL evidence encountered by a new strict fill no longer relies on
  an operator winning that older activation race: preflight checks it itself.
- Workflow sidecars are separate databases. Their broker-commit/journal-update
  gaps and cross-file capture limitations remain. The mandatory preflight checks
  broker authority; it does not claim atomic inspection of live sidecars or real
  market-data truth. Missing workflow inspection is a warning, not silent evidence
  of health across all files.
- Lock duration depends on history size, integrity scans, local replay and source
  hashing. There is no constant-time latency promise. Other writers can hit the
  existing SQLite busy timeout; timeout is an error, not permission to fill or
  proof that a latch was stored. Use independent connections and local SQLite
  filesystem locking; no shared cross-thread connection or remote lock assumptions.
- Kill/recovery writes also serialize. A kill request queued behind a fill cannot
  preempt that transaction: the fill may commit first, then the kill commits and
  blocks later new execution. This is explicit sequence order, not a claim of
  instantaneous cancellation.

The older activation API can acknowledge an already active **strict-preflight**
receipt only for the exact same frozen broker observation, after validating the
original critical report. It returns the actual existing event/actor/ID, not a
fabricated activation under the caller's new ID. It performs no new control change.
Different observations still require current-state validation; original evidence
is never overwritten. This safely handles a manual activator racing the new guard.

## Failure and recovery behavior

Broker exception cleanup now attempts ROLLBACK only when SQLite still has an
active transaction. A cleanup failure is attached to the original exception
rather than masking it. A successful COMMIT followed by lost acknowledgement
remains an uncertain response, resolved by reopening and querying/retrying the
**original attempt ID**. Never choose a new ID merely to get past uncertainty.

A SQLite whole-transaction abort does not produce a fictional savepoint rejection
audit. It propagates the original failure; reopen to inspect actual durability.
If the connection closes, even inspecting transaction status can fail. That
secondary error is attached to the primary failure, not substituted for it.
Reopen and resolve the original attempt ID: a close before commit rolls back;
a close after commit does not undo the recorded fill. Neither case permits a
duplicate fill on exact retry.
An ordinary savepoint-recoverable fault still preserves the existing durable
rejection contract. Audit insertion failure cannot accidentally commit a partial fill.

Existing recovery remains explicit, state-bound, reasoned and dependent on the
separately supplied trusted local verifier. Healthy inspection never releases the
latch or kill switch. Failure between clearing latch fields and writing recovery
audit rolls both back. A release does not authorize a previously rejected gate
request: exact retry still returns its rejection. A new attempt needs fresh state
and the existing explicit authorization flow. Local verifier code must stay
bounded and avoid reentrant broker writes or external interactions under the lock.

Migration now asserts an owning transaction. Existing version-2 to version-3 DDL
still migrates atomically without rewriting financial rows. Interruption between
metadata-table creation stages rolls the entire migration back; it does not
install an unblocked fragment or reset a prior latch. No version-4 migration,
journal-mode change, financial repair or new dependency was introduced.

## Manual use

Read-only reports retain their existing manual entry point. For coordinated
broker-only inspection use:

```python
from tools.operational_controls import reconcile_and_latch

receipt = reconcile_and_latch(
    broker_path,
    report_id="manual-check-001",
    timestamp=explicit_aware_simulation_time,
    activation_id="manual-activation-001",
    operator_id="investigating-operator",
    reason="Explicit operational safety inspection",
)
```

Inspect the returned report and actual block ID/activation receipt; preserve their
artifacts and expected hashes. A healthy repeat does not release an existing
block. A fresh critical observation after an earlier release needs a new action ID.
Do not open missing databases or repair unreadable storage through this command.

## Fifth safeguard: bounded integrity work and measured cost

The strict-fill preflight admits at most **64 MiB of logical SQLite database
pages**, **10,000 application-table rows in total**, and **1,000 gate-attempt
records**. It checks page size/count and row/history counts under the same writer
before the full capture/reconciliation. These are conservative operational work
limits, not position/risk thresholds. They are code policy, not fields that an
execution request can raise or disable. The first exceeded limit raises
`PreflightBudgetExceeded` and refuses the fill, leaving financial/control state
unchanged. No completed integrity check, durable rejection audit or stored latch
is falsely claimed. Retries cannot use a cached healthy result to evade the cap.

The limits apply to the input admitted for each new strict-fill integrity scan.
A newly appended outcome can grow the database beyond a cap; the next attempt
then stops. No history is automatically truncated, repaired, vacuumed or discarded.
Keep evidence and request an explicitly reviewed scaling/archival or budget change
if a cap is reached. Read-only forensic reports and explicitly requested manual
reconciliation can still inspect larger histories; they have no implied execution
permission and no claim of bounded per-fill latency.

Logical data-work limits are not a hard wall-clock deadline. Storage stalls,
SQLite busy waiting, OS scheduling, startup, request parsing, remaining risk/fill
work and trusted local recovery verifiers are not bounded in milliseconds by
these caps. No unsafe thread cancellation interrupts a live transaction.

A local offline profile measured the **entire strict integrity preflight**, including
budget checks, capture, independent reconciliation, gate audit checks and source
hashing, inside a reserved writer transaction. It used three measurements per
fixed synthetic history, reporting their median:

- 0 prior gates, 6 rows, 86,016 database bytes: **1.122 ms**.
- 8 prior gates, 62 rows, 266,240 database bytes: **48.510 ms**.
- 24 prior gates, 174 rows, 880,640 database bytes: **150.445 ms**.

These are observations from this environment, not an SLA, cold-storage guarantee
or linear-growth promise. Historical outcomes embed prior states, so input bytes
and replay work can grow faster than gate count; a constant-time claim would be
incorrect. Total fill latency also includes the existing FX/risk/accounting work.
Every new strict fill repeats integrity checking; there is deliberately no health
cache. Reproduce the workload with:

```powershell
uv run --no-sync pytest -q -s tests/test_operational_safety_hardening.py::test_preflight_cost_profile_on_fixed_synthetic_histories
```

The test seeds only temporary synthetic ledgers; measured inspection issues no
fills of its pending target. It asserts no timing threshold, avoiding a flaky
machine-speed test. Separate tests force each budget overrun and prove repeated
attempts refuse execution without fabricating a persisted latch.

## Deterministic proof and validation scope

The new tests use real temporary SQLite files and controlled faults, not process
kills or random sleeps. Connection proxies inject faults after account/fill SQL,
before commit, after a successful commit response is lost, and during migration
DDL. SQLite triggers inject whole-transaction rollback and control/recovery audit
failures. Reopening verifies cash, shares, pending status, control persistence,
audit consistency and exact retry behavior.

The lock proof pauses after independent reconciliation has returned CRITICAL
while the coordinated writer remains held. A separate, already-open connection
signals its actual BEGIN IMMEDIATE attempt through a SQLite statement trace. It
cannot complete its fill until the checker is released and the latch commits;
it then records an operational-block rejection. No timing sleep decides the result.

Additional event-controlled tests show a fill waiting behind authorized recovery
rejects its stale state, and a queued kill writer commits after an in-flight fill
then blocks the pending order. Competing limited-cash orders cannot spend resources
reserved conservatively by existing risk checks. Earlier same-order and competing
order concurrency tests remain part of the focused regression.

Code, report and gate source fingerprints now include the integrity-checker code
that influences execution. Historical replay can require its original checkout;
old fingerprints and audits are never relabeled. Source mismatches retain their
documented warning classification rather than invented financial corruption.

SQLite is not tamper-proof, and transaction tests do not prove physical power-loss
durability for every filesystem, journal mode or synchronous setting. Unreadable
SQLite or failed audit/COMMIT cannot promise durable activation; refuse execution
and investigate. Coordinated owner edits, compromised local authorization tooling,
restored old backups and trusted-price authenticity remain outside these guards.

No external requests, dependencies, scheduler, unattended execution, strategy
changes, commits, pushes or tags were introduced. The protected
`scripts/sec_match_recon.py` modification was not touched, staged or discarded.

## Validation of the current implementation

- Focused: `uv run --no-sync pytest -q tests/test_operational_safety_hardening.py tests/test_operational_monitoring.py tests/test_gated_execution.py --tb=short`
  passed **81 tests** in 16.47 seconds (the final run also used `-s` to record the
  overhead profile).
- Final full: `uv run --no-sync pytest -q` passed **796 tests** in 65.81 seconds:
  all 774 baseline cases plus 22 deterministic hardening cases.
- `git diff --check` passed. uv cache initialization required test execution
  outside the filesystem sandbox; no dependencies were installed or synchronized.

The clarified five conditions are covered as follows:

1. **Atomic check/latch:** after CRITICAL detection, a zero-timeout independent
   BEGIN IMMEDIATE probe proves the checker still owns its writer reservation;
   the traced fill contender cannot proceed until latch commit and then rejects.
2. **Every strict-fill path:** the shared gate runs preflight, the accounting
   helper refuses to skip it, and repeated failed latch-audit writes cannot grant
   fill permission. Committed-result reads remain distinct from new fills.
3. **No silent recovery:** report generation stays read-only; failed migrations,
   transaction aborts and failed recovery audits are tested without repairing
   evidence. Cleanup failures retain the primary error and close their connection;
   they do not claim a successful rollback or durable block without evidence.
4. **Concurrency:** controlled events and SQL traces cover fills versus critical
   inspection/activation, authorized recovery and kill writes, plus competing
   limited-cash orders. Existing same-order idempotency/concurrency cases remain.
5. **Bounded overhead:** fixed code admission budgets and overrun refusal tests
   bound admitted data work. The reproducible profile quantifies actual scan/replay
   costs while explicitly making no universal latency promise.

Changed files for review: `providers/paper_broker.py`, `tools/gated_execution.py`,
`tools/operational_controls.py`, `tests/test_operational_safety_hardening.py`,
`docs/operational_safety_hardening_design.md`, `docs/operational_safety_hardening.md`
and `docs/operational_monitoring.md`. The pre-existing protected-file modification
is separate from this change set and remains untouched.
