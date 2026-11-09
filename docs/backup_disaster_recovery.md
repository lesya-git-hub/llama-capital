# Sprint 1K: verified backup and inspection-only restore

These APIs are explicit local operator actions. They use no network, scheduler,
broker connection or automatic execution. No quarantine release or overwrite
operation exists. Legacy ledgers retain unrestricted legacy manual-fill behavior;
restored strict ledgers cannot execute new fills. This establishes no real-world
market-data trust, provider finality, licensing entitlement or verified publication.

## Create and verify a backup

Use `tools.backup_recovery.create_backup(source, root, backup_id=..., timestamp=...,
policy=MonitoringPolicy(...))`. Supply a timezone-aware timestamp and an explicit
opening-cash policy (default EUR 10000). IDs use letters, digits, `_` and `-`.
The return value contains `path` and `manifest_sha256`. Retain that hash separately
from the bundle. A repeated backup ID refuses rather than overwriting history.

For example, in a trusted local Python entry point:

```python
from datetime import datetime, timezone
from tools.backup_recovery import create_backup, verify_bundle

artifact = create_backup(
    'paper.sqlite', 'backups', backup_id='drill-001',
    timestamp=datetime(2026, 11, 9, 12, tzinfo=timezone.utc),
)
manifest = verify_bundle(
    artifact['path'], expected_manifest_sha256=artifact['manifest_sha256'],
)
```

SQLite's online backup API copies a consistent committed image, including WAL
content. The source is opened read-only; no source checkpoint or journal-mode
change is issued. Only the copied destination is checkpointed and normalized to
DELETE journal mode. Financial records, controls and audit values are copied.
Concurrent writes may advance the source beyond the captured recovery point.

The private `.partial-<random>` directory contains the completed image, canonical
`verification.json` and canonical `manifest.json`. All handles close and each
file is flushed before publication. Manifest timestamps, IDs, source identity,
schema, counts, safety flags, logical snapshot hash and closed database byte hash
come from the image. Random staging paths do not enter the manifest. Determinism
means identical inputs/image produce identical evidence, not that concurrent
backup calls must capture the same transaction or SQLite physical layout.

Publication uses Windows same-parent `os.rename`, which refuses an existing
destination even if another creator wins the race. Other platforms fail closed.
Verification refuses staging directories, extra/missing files, symlinks/junctions,
hash conflicts, identity conflicts, unsupported application/schema identity,
SQLite integrity/foreign-key errors, incomplete financial reconstruction and
inconsistent financial/control/gate audit evidence. It independently reconciles
the image, rather than accepting a stored HEALTHY label. Verification is read-only.

The only accepted warnings are `REPLAY_ENVIRONMENT_UNAVAILABLE` and
`WORKFLOW_SCOPE_NOT_INSPECTED`. The first requires archived historical code for
full replay; the second records the broker-only scope. Neither establishes full
cross-database recovery. Every other warning and every critical finding refuses.
Financial facts and snapshot evidence must still agree with current inspection.

Backups support recognized legacy v1, strict v3 and quarantined v4 images. Strict
v2 requires its existing explicit broker control migration before backup; unknown
schemas refuse. Initial restore supports strict v3 backups only. A v4 backup can
be inspected and retained, but cannot be restored again in this sprint.

## Authorized new-destination restore

Call `restore_backup(bundle, target, expected_manifest_sha256=..., journal=...,
restore_id=..., operator_id=..., authorization_id=..., reason=..., timestamp=...,
authorize=trusted_authorizer)`. The absent target is a **directory bundle** whose
name must equal the restore ID. Its parent must already exist. The ledger will
be `target/ledger.sqlite`. Journal parent must exist; journal must be independent
of the source and target bundles and must not be another application's database.

The independently configured local authorizer receives the exact request as a
dictionary and must return the boolean `True`. It must authenticate the operator
and check the backup hash, target, reason and authorization scope. A request's
operator string or authorization ID alone is no authentication. No authorizer,
denial or authorizer exception refuses and records DENIED when audit storage works.

```python
from tools.backup_recovery import restore_backup

# trusted_authorizer is supplied by the operator's authenticated application.
result = restore_backup(
    artifact['path'], 'recovery/drill-restore-001',
    expected_manifest_sha256=artifact['manifest_sha256'],
    journal='recovery/restore-audit.sqlite', restore_id='drill-restore-001',
    operator_id=operator_identity, authorization_id=approval_identity,
    reason='Authorized synthetic disaster-recovery drill',
    timestamp=explicit_aware_time, authorize=trusted_authorizer,
)
```

The restore journal commits PREPARED before staging. The copied strict-v3 ledger
gets an additive v4 `restore_fence` singleton with a hashed request and receipt,
inside its own write transaction. No original financial, gate, operational event
or switch value is rewritten. Migration is never applied automatically to a normal
live v3 ledger. Old broker versions reject v4; new versions reject a missing,
malformed or downgraded fence. A valid fence always means quarantined.

After independent verification and file flushing, a SEALED journal event commits
the final target manifest hash **before** directory publication. The complete
directory is renamed without replacement, verified at its published identity,
then PUBLISHED commits. Success returns only after that final audit commit.
The target-local receipt and external journal bind the operator, authorization,
reason, exact request, target identity, source backup manifest and outcome.

If publication succeeds but final audit fails, the call raises. The destination
already has a committed quarantine fence and SEALED audit evidence. An explicit
same-request retry reauthorizes, validates that exact sealed artifact and records
PUBLISHED; it never overwrites. A different request under the same restore ID
refuses. If the image has changed since publication, retry refuses: preserve it
for investigation rather than resealing or silently repairing it. Ordinary
quarantine rejections append gate audit records, so even those legitimate writes
invalidate the initial publication byte seal. That seal describes publication
time, not the later mutable inspection ledger.

## Quarantine and safety controls

Every new strict gated attempt reads and validates the fence under the broker's
BEGIN IMMEDIATE writer transaction. The shared accounting function also checks
the fence under that same transaction, before any financial mutation. Manual
strict fills remain prohibited. Orchestration goes through this gate. Cached
completed outcomes can be read, but cannot cause duplicate fills. Pending orders
remain pending and new attempts reject durably without financial changes.

There is **no visible unfenced restore interval**: v4 migration, receipt and fence
commit in the private image before its complete directory becomes visible. An
observer racing publication sees an absent destination or a fenced ledger.
Execution racing a kill/latch recovery is serialized by SQLite's existing writer
transaction; neither recovery API writes the independent restore fence.
The fence adds bounded singleton/schema reads and hashing of at most 16 KiB of
receipt per check. Normal strict ledgers still run their existing integrity
preflight. A quarantined request validates its fence then records rejection;
it does not repair state or manufacture a new operational-latch activation.

Use the existing read-only monitor and `human_report` to inspect reconstruction,
balances, holdings, pending orders, fills, kill switch and operational latch.
The human report explicitly labels v4 restore quarantine. `read_restore_fence`
validates the sealed local receipt. Keep the independently retained backup hash,
publication manifest, restore receipt and journal. A healthy reconciliation is
not authorization to release quarantine. There is no release API in Sprint 1K.

An older image preserves exactly its historical kill/latch states. Unknown later
fills, emergency controls and missing workflow outcomes cannot be inferred from
it. The independent permanent fence prevents execution even if those historical
bits were clear. Original live ledgers and workflow journals are not retargeted,
rolled back, repaired or resumed. This restores an inspection branch only.

## Failures and limitations

Existing files, directories and active ledgers are never replaced. Absence plus
atomic no-replace directory publication is the supported quiescence boundary;
this does not prove that another branch is shut down, or prevent a privileged
external process from changing files. Filesystem access must remain controlled
by the operator. There is no hostile-writer or malicious filesystem guarantee.

Interrupted staging directories are deliberately retained, never accepted by
verification or automatically reused. Preserve them and the failure journal for
review. Failures append FAILED where storage permits, then raise; failure to
write failure evidence is attached to the original exception. If journal storage
is unavailable before PREPARED or SEALED, publication does not occur. Hardware
failure can also prevent writing an attempted denial/failure; no API can promise
durable evidence on unavailable storage. No exception is treated as success.

Admission limits are 64 MiB images, 10000 inspected rows, 128 pages per online
backup step, 4096 progress callbacks and 30 seconds checked at those callbacks.
SQLite connections have two-second lock waits. These bound admitted work and
backup retries, not physical I/O completion, monitor CPU time or a hung device.
No automatic retention/deletion exists: storage and partial directories require
operator review. The supplied tests inject deterministic failures; they do not
simulate actual power loss or establish physical storage durability.

Bundles are immutable **through these APIs**, not write-protected or tamper-proof.
Hashes detect changes relative to an independently trusted hash; they do not
authenticate provider data, an operator or a maliciously replaced entire history.
File flushing, SQLite FULL audit commits and namespace rename do not establish
Windows directory durability across physical power loss. There is no off-device
replication, signing, encryption/key management or cross-file atomic recovery.

Future proposed objectives: operator backups at least daily and at important
accounting/control milestones, recovery point <=24 hours, quarantined inspection
copy available <=15 minutes. These are unmeasured future targets. Execution
resumption RTO is outside this sprint because quarantine release is excluded.

## Review and validation

The five approved safety conditions map to independent hash/schema/financial
verification; atomic persisted fence enforcement; restore-only additive migration;
explicit authorization with PREPARED/SEALED/PUBLISHED evidence; and staged
no-clobber publication with failure injection. Deterministic tests cover corruption,
audit faults, WAL writers, restart, direct/internal/orchestrated bypasses,
independent controls, duplicate identities/fills and publication races.

No overwrite, quarantine release, external request, dependency installation,
unattended action, commit or push is included. `scripts/sec_match_recon.py` is
excluded from Sprint 1K work.

Validation on 2026-11-09:

- Focused: `uv run --no-sync pytest -q tests/test_backup_recovery.py tests/test_operational_safety_hardening.py tests/test_operational_monitoring.py tests/test_gated_execution.py tests/test_paper_orchestration.py`
  — **168 passed in 57.84 seconds**.
- Full: `uv run --no-sync pytest -q` — **858 passed in 80.25 seconds**:
  the 796-test baseline plus 62 new recovery cases.
- `git diff --check` passed. Tests used the existing environment with `--no-sync`;
  access to its existing uv cache required sandbox escalation. No packages were
  installed and no external requests were made.

Changed Sprint 1K files: `providers/paper_broker.py`,
`tools/gated_execution.py`, `tools/operational_controls.py`,
`tools/operational_monitoring.py`, `tools/restore_quarantine.py`,
`tools/backup_recovery.py`, `tests/test_backup_recovery.py`,
`docs/backup_disaster_recovery_design.md` and this operational guide.
The protected script's pre-existing worktree change is separate and unchanged
(SHA-256 `7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`).

There are no scope deviations from the approved architecture. The additional
SEALED audit step strengthens its publication/retry protocol. Independent review
is required before any commit; no commit or push was performed.
