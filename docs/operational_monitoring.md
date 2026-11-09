# Sprint 1I: operational monitoring and explicit recovery

Sprint 1J follow-up: [Option B hardening](operational_safety_hardening.md) adds a
coordinated reconcile-and-latch command and mandatory broker-scoped preflight on
every new strict fill. Ordinary reports remain read-only. The separate two-phase
report/activate API described below is no longer the only protection against
broker CRITICAL findings during a new strict fill.

Implements the approved [architecture assessment](operational_monitoring_design.md).
Mode: offline synthetic research, manually operated. No financial repair,
execution authorization, unattended execution, scheduler or notifications.

## Authority and independent reconciliation

`tools.operational_monitoring` opens existing databases with SQLite URI `mode=ro`,
query-only mode and a consistent read transaction. It does not construct a
`PaperBroker` or `WorkflowStore`, initialize a missing source, migrate schemas,
call order/fill methods or modify source records. Corrupt ledgers can be inspected
even when normal broker startup reconciliation refuses to open them.

The frozen `OperationalSnapshot` contains database identities, application/schema
versions, table/index metadata, SQLite integrity/foreign-key results and canonical
raw records. Logical data is captured rather than trusting file-byte hashes that
can omit WAL contents. Each broker capture is transaction-consistent; separately
captured workflow files do not form an atomic distributed snapshot. The policy's
`quiescent_asserted` setting is an operator assertion, not a lock or guarantee.
Missing cross-file references can require a confirmed recapture. Conflicting
immutable request/outcome hashes are different from a recoverable commit gap.

Independent accounting starts from stored opening cash, checked against an
explicit expected-opening-capital policy (default virtual EUR 10,000). There is
no independently signed opening-deposit event. Fill order comes from uniquely
sequenced FILLED events, with raw fills and orders checked separately so missing
records cannot disappear through an inner join.

Using a dedicated Decimal precision-50, ROUND_HALF_EVEN context, the monitor
recomputes adverse execution price, quantity-times-price cash movements, total
commissions, weighted basis allocation and realized P&L. Partial sales allocate
basis to twelve fractional places; full sales consume exact remaining basis.
Stored execution price, cash delta, allocated basis and realized P&L are compared
with those calculations. Reconstructed cash, quantities and cost basis are then
compared with the materialized account/positions. Average entry cost is computed
from reconstructed basis/quantity. This is a separate checker, not a replacement
accounting implementation or a repair path.

Audit sequence is the authoritative lifecycle/kill ordering. Existing semantics
permit administrative timestamps and different orders' timestamps to be backdated,
so the monitor does not infer global event ordering from timestamp sorting.
It checks UTC timestamps, order/fill lifecycle consistency, duplicate IDs/fills,
missing sequences, filled/cancelled status and fills occurring while kill mode
was active where sequenced evidence proves it. Incomplete history never produces
invented transactions or an invented unique financial reconstruction.

Strict fills require exactly one valid successful gate audit matching the broker
order, financial fill fields and independently reconstructed before/after cash,
P&L and holdings. Rejections must have equal before/after states and no fill.
Current-compatible gate checks are replayed read-only. Historical source mismatch
is reported as a WARNING requiring the archived checkout rather than rewriting
the historical source fingerprint or assuming it proves an unauthorized trade.

Workflow previews, authorizations, prepared requests, outcome references and
reports are checked against broker authority. A proven broker-commit/sidecar-update
gap is WARNING and is never resumed by monitoring. Missing required strict-fill
authority and conflicting immutable audit records are CRITICAL. Partial or
interrupted workflows remain visible; a later valid completed report can resolve
the run's incomplete-status warning without deleting its historical reports.
No supplied sidecar for existing workflow gate attempts yields a scope warning.

## Health, findings and daily reports

`MonitoringReport` records explicit report ID/time, frozen input/hash, policy,
ledger identity, strict/kill/operational-block state, stored EUR cash, holdings at
cost, reconstructed financial amounts, order/gate counts, workflow run phases,
findings and actions. It never invents current stock marks, market equity,
returns or investment performance. Synthetic FX evidence is not real-world
price/source authority.

Severity precedence is CRITICAL > WARNING > HEALTHY. Each finding has a stable
code, severity, evidence references, explanation and required operator action.
HEALTHY means the declared required checks passed with sufficient captured
evidence, not that investment risk is safe or that source data is authentic.
`financial_reconstruction_complete` describes calculability of the history;
it does not override CRITICAL mismatch findings. Unsupported/malformed sources,
financial conflicts and missing strict authority cannot become unqualified HEALTHY.

A legitimately active operational latch may coexist with a HEALTHY financial
report after investigation/correction. The latch stays set until explicit recovery;
report generation has no control writes. Historical critical findings remain in
the durable activation event even after the underlying condition is corrected.

Manual report entry point:

```powershell
uv run --no-sync python -m tools.operational_monitoring --broker runs/strict.sqlite --workflow runs/workflow.sqlite --report-id daily-review-001 --at 2026-11-09T17:00:00+00:00 --output runs/daily-review-001.json
```

The output is a new JSON artifact (existing files are not overwritten) plus a
human-readable console report. Omit `--workflow` when deliberately inspecting
only broker scope; use `--expected-cash` for an explicitly approved different
opening-capital expectation. No clock, external quote or notification is inferred.
Python callers can use `monitor`, `capture_operational_state`,
`reconcile_snapshot`, `human_report` and `replay_report` directly.

Retain `canonical_json(report)` and `input_hash(report)` independently.
`replay_report(report, expected_sha256=...)` regenerates results entirely from
the frozen source snapshot, policy, ID and time, with no live database or fills.
Preserve the original checkout/environment for matching fingerprints. Hashes
establish content consistency, not tamper-proof security or factual authenticity.

## Strict schema migration and persisted enforcement

Strict version-2 ledgers migrate transactionally to version 3 when opened by
the updated broker. The additive `operational_control` singleton and
`operational_events` journal preserve all prior account, order, fill, position,
broker audit, strict-mode and gate records byte-for-byte at the SQL-value level.
Migration does not set or clear the kill switch, reset capital, repair history or
retroactively approve old executions. A newly created strict ledger also uses
version 3. Legacy version-1 ledgers retain their existing schema and unrestricted
manual-fill behavior; they are not operational-latch enforced.

Version 3 requires valid control metadata on every reopen. Missing/corrupt control
state fails closed rather than initializing an unblocked replacement. Relabeling
a strict/control schema as version 1 or attempting to reset version 3 to version
2 with existing control tables is rejected. Startup financial reconciliation can
still raise after a committed metadata-only migration; financial rows remain
unchanged, and control actions can independently open the initialized strict
database for latching during investigation.

`execute_gated` checks the persisted latch under the SAME BEGIN IMMEDIATE write
transaction as risk evaluation and fill. The shared strict accounting helper
checks it again. Direct strict manual fills remain prohibited. The control state
and event sequence are included in execution-state identity, invalidating old
previews. Orchestration therefore cannot bypass the broker guard. Existing exact
retries of already committed outcomes remain historical reads, not new fills.
Malformed control state can raise an exception before a gate audit is constructible;
it never permits execution as a fallback.

The operational latch and kill switch are separate. Clearing kill mode never
changes the latch. Releasing the latch never disables kill mode. No new execution
is permitted while either applicable control is active.

## Explicit detection, activation and race window

Reporting and activation are separate manual operations. A CRITICAL report alone
does NOT automatically block execution. Until activation is durably committed,
another writer may fill. This pre-activation interval is not automatically
fail-closed protection, and no such protection is claimed.

`activate_operational_block(path, report, expected_sha256=..., activation_id=...,
operator_id=..., reason=..., timestamp=...)` opens an existing initialized strict
database using `mode=rw`, without running broker startup reconciliation. It
acquires BEGIN IMMEDIATE, replays/checks the exact report and ledger identity,
compares the FULL logical broker snapshot (including fills, schema and audits)
with current state, and requires CRITICAL status. If another writer changed the
snapshot, activation rejects stale evidence and the operator must recapture.
No smaller cash-only or 1G state hash substitutes for this comparison.

If activation wins the lock, latch state plus activation evidence commit atomically
and later new strict fills reject. The separate report/activate API can still see
stale observations. Sprint 1J additionally makes every new strict fill inspect
broker integrity under its own writer reservation and latch/refuse CRITICAL
findings; see the hardening document for that stronger guarantee and the remaining
cross-file/pre-lock boundaries. No background detector is introduced.

Activation stores block/report/snapshot identities, actor, reason, timestamp,
critical findings with observed/expected evidence references, content hashes and
control-source fingerprint. It preserves the original active block rather than
silently replacing it. Keep the full original report/snapshot artifact separately;
the control journal retains finding evidence and hashes, not recursively embedded
copies of all earlier source databases.

Actions update ONLY control metadata/journal in one transaction. Audit insertion
failure rolls back the control change. Snapshot comparison includes prior control
events, so activation/recovery cannot silently ignore another committed control
action. Sidecar snapshots are frozen cross-file evidence; activation does not
lock all live sidecars. Operators must account for that separate capture limitation.

## Explicit recovery and authorization boundary

Use `RecoveryRequest` with a new recovery ID, active block ID, operator identity,
independent authorization identity, nonblank reason, aware timestamp and the exact
fresh investigation-report hash. `release_operational_block(path, request, report,
authorize=trusted_verifier)` requires current matching broker snapshot, the actual
active block, complete financial reconstruction and no remaining CRITICAL findings.
It never accepts a healthy status string without regenerating the report.

The independently supplied trusted LOCAL application verifier must return exactly
True for the operator, authorization, block and investigated evidence. It is not
deserialized from report/request data. Missing verifier, a denial or verifier
failure rejects recovery and durably records DENIED while leaving the latch set.
There is no default allow-list, guessed identity, password, external service or
new credential. The library does not authenticate humans: callers must control
the verifier in trusted application/operator tooling. An arbitrary untrusted
Python caller who can inject its own verifier or edit SQLite files is outside
this local application authorization boundary; this is not a remote security API.

A successful release clears ONLY the latch fields and atomically stores RELEASED
with actor, reason, independent authorization ID, investigation hashes and source
fingerprint. Healthy reports do not call it. A still-enabled kill switch continues
to block execution. Two recoveries based on the same state cannot both mutate it:
the second becomes stale. Exact action-ID/payload retries return the original
historical event without another control change, including a release for an older
block; inspect current state separately. Changed payload under the same action ID
conflicts. Stale/malformed recovery requests may fail validation without an action
event; no success or release is claimed in that case.

## Operator investigation procedure

1. Inspect CRITICAL codes and the referenced account/order/fill/gate/workflow rows.
2. Preserve consistent SQLite backups, journals/WAL evidence, full monitoring
   snapshots/reports and their expected hashes before any correction.
3. Explicitly activate the state-bound operational latch; if stale, recapture.
   Do not claim protection until its commit succeeds. Independently enable the
   existing kill switch when appropriate.
4. Investigate with original code/FX/risk/workflow artifacts. Correct underlying
   problems only through a separately approved process. Monitoring/control APIs
   never rewrite balances, fills, orders or historical audits.
5. Capture/reconcile again. Retain the old critical evidence. A HEALTHY report
   alone does not release either control.
6. Supply independently authorized, reasoned recovery against the current block
   and exact current snapshot. Confirm the durable RELEASED event and inspect
   the independent kill state before any later manually authorized workflow.

SQLite owner edits, coordinated changes to all records, compromised local
authorization tooling, restored old backups and unretained source artifacts are
not solved by hashes or these application guards. The system is not tamper-proof.
Legacy execution stays unrestricted. No production market-data trust or live
execution capability is established by an operationally healthy result.

No external requests, dependency changes, scheduler, notifications, unattended
execution, commits, pushes or tags were introduced. `scripts/sec_match_recon.py`
was not modified or staged, and no V1 release tag was changed.

## Validation results

- Focused integration: `uv run --no-sync pytest -q tests/test_operational_monitoring.py tests/test_gated_execution.py tests/test_paper_orchestration.py --tb=short`
  passed **83 tests** in 44.19 seconds.
- Final targeted checks for downgraded control schema and missing operational-audit
  authority passed **2 tests**. The latter adds the final new regression case.
- Final full regression: `uv run --no-sync pytest -q` passed **774 tests** in
  61.69 seconds: all 747 existing cases plus 27 new monitoring/control cases.
- `git diff --check` passed. Test execution required uv cache access outside the
  filesystem sandbox; no dependencies were installed or synchronized.

Tests use synthetic fixtures and temporary databases. Coverage includes independent
cash/quantity/basis/P&L and fill arithmetic checks, duplicate/missing/corrupt audits,
healthy and damaged read-only captures, frozen replay, real workflow journal gaps
and partial batches, migration row preservation, kill/latch independence, all
strict fill guards, orchestration bypass rejection, stale activation, concurrent
fills/activation and concurrent recoveries, restart persistence, authorized/denied
recovery, control-audit rollback and schema fail-closed behavior.
