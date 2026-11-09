# Sprint 1K: verified backup and disaster recovery — approved architecture

Inspected baseline: `e93d059` on `main`; supplied baseline: 796 tests.
This is the required architecture assessment. No runtime code, migration,
backup/restore operation or new test is implemented before architectural approval.

## 1. Existing architecture and safety invariants

The inspected modules are `providers/paper_broker.py`, `tools/gated_execution.py`,
`tools/operational_controls.py`, `tools/operational_monitoring.py` and
`tools/paper_orchestration.py`, with their tests and operational documentation.
There is no separate `tools/operational_safety_hardening.py`: Sprint 1J hardening
is integrated into the broker, gate and operational-control modules.

The broker's account, orders, positions, fills and sequenced audit tables carry
financial history. Strict version-3 ledgers additionally retain execution mode,
gate attempts, USD stop/order assumptions, operational control and control events.
Version-1 legacy ledgers retain unrestricted manual-fill behavior. Financial
execution uses one BEGIN IMMEDIATE transaction; completed gate request IDs and
hashes prevent duplicate execution of the same order through supported APIs.

Strict new fills run integrity preflight and check the sticky operational latch
and independent kill switch under that writer. Rejections use a savepoint and
durable unchanged-state audit. Cached committed outcomes are historical reads.
Recovery never automatically repairs records or reauthorizes a rejected attempt.

The workflow journal is a separate SQLite database. Prepared requests can commit
before the broker outcome, and the sidecar update can fail afterward. That gap
is recoverable by matching the broker's immutable attempt ID; neither backup nor
restore may reinterpret it as a reason to issue a new fill.

The monitor can inspect read-only snapshots, independently recompute accounting,
validate schemas/audit envelopes and replay compatible gate evidence. Current
execution-state identity is not a backup identity: it excludes some full history,
and an internally consistent older state is not proof that no later state exists.
Historical source mismatches require archived code; hashes do not establish truth.

## 2. Recommendation and alternatives

### Recommended smallest safe scope

1. Operator-initiated, SQLite online backup into a private staging bundle.
2. Verification of the completed artifact, then one published immutable bundle
   containing database image, canonical manifest and verification evidence.
3. Authorized restore **only to a new, absent destination bundle/path**. No
   overwrite/replacement of an existing ledger in Sprint 1K, even if it appears
   idle. Preserve the original database and all sidecars untouched.
4. Every restored strict copy has an independent, persisted **restore quarantine**
   before publication. Preserve the backup's actual kill switch, operational
   latch, financial rows and old audit records; quarantine is an additional hold.
5. No restore-quarantine release or resumed trading is provided in this sprint.
   Restored data is available for reconciliation/inspection. Enabling a recovered
   branch later needs a separately approved reconciliation/activation procedure.

The deliberately limited restore scope avoids pretending that SQLite locking
alone proves the absence of other handles, or that a valid old backup authorizes
loss of later fills/controls. It adds recovery/inspection capability, not trading.

### Alternatives evaluated

- **Raw copying live `.sqlite` files:** reject. A live source can have committed
  state in WAL or be mid-update. Copying DB/WAL/SHM files separately is not an
  application-consistent snapshot protocol. Hashing that copy cannot repair it.
- **Quiescent raw file copy:** possible only with a proven offline maintenance
  protocol including all relevant sidecars. Offers no advantage over the supported
  backup API for this sprint and is not the recommended implementation.
- **Restore over an existing path:** defer. BEGIN EXCLUSIVE does not prove that
  no idle connection, WAL reader or later writer exists. Safe replacement needs
  an approved maintenance/exclusive-ownership protocol, platform-specific handling
  of open handles and stale WAL/SHM, original-target preservation and crash recovery.
- **Global broker/workflow backup transaction:** do not claim it. Independent
  online backups provide consistent individual images, not one cross-file instant.
  A truly coordinated set needs an additional multi-file maintenance design.
- **Reuse kill switch as the only quarantine:** reject. Existing manual kill
  clearing would remove the hold without disaster-recovery reconciliation.
- **Fake a financial CRITICAL report to activate the existing latch:** reject.
  A healthy old backup must not acquire manufactured inconsistency evidence.

## 3. Online backup, WAL and consistency

Use the standard-library SQLite connection `backup()` mechanism on an existing
source connection opened with URI `mode=ro`; never create a missing source.
Copy into a new private staging database on the destination filesystem. Do not
open/migrate the source through `PaperBroker` or issue source financial writes.

SQLite's backup mechanism provides a coherent committed image while coordinating
with source writers, including WAL mode. Stepwise backup can restart or extend
when source pages change. Therefore manifest counts, logical snapshot identity,
schema and sequence boundaries must be read from the **completed destination**,
not assembled from source queries before/after the copy. Creation time records
the operator's operation, not a claim of an exact market/commit timestamp.

Do not checkpoint or change journal/synchronous settings on the source. Normalize
only the staged destination as needed: finish/close backup handles, checkpoint
any destination WAL and make the published database self-contained (for example,
destination-only DELETE journal mode). Record the final artifact mode. Hash only
the finished, closed main image after required destination checkpointing; never
publish an image that depends on an omitted destination WAL. These details must
be confirmed against the installed SQLite with WAL/concurrent-writer tests.

The backup is not a writer reservation covering the whole trading application.
Source writers can proceed subject to SQLite's backup locking. Use explicit
busy/page/retry budgets and progress-based cancellation; cancellation is failure,
not a partially verified recovery point. Do not promise a hard wall-clock bound
against stalled physical I/O. Do not rely on `immutable=1` to ignore live WAL.

Workflow journals can be backed up separately using the same safe primitive and
listed as individually verified artifacts. Mark capture as separate/non-atomic.
Do not automatically resume a restored workflow or silently retarget its stored
ledger-path identity. The broker outcome remains financial authority.

## 4. Immutable manifest and publication protocol

Proposed canonical manifest fields:

- Manifest format/version, operator-supplied backup ID and aware UTC creation time.
- Source normalized identity, broker application ID, schema/strict mode and
  completed-image journal mode; relevant code/verifier fingerprints.
- Destination image byte length and SHA-256, independently computed logical
  snapshot hash, account/order/fill/gate/control counts and audit/control sequence
  boundaries from that image. Preserve kill/latch values and identities explicitly.
- Verification policy, result/findings and scope, optional separately backed-up
  workflow image references and explicit cross-file consistency limitations.

Canonical serialization makes identical supplied metadata/content reproducible.
The backup ID does not replace content hashes. Do not assume repeated online
backups produce identical SQLite bytes; page layouts/backup times can differ.
Persist actual hashes and verify them rather than relabeling an old artifact.
Require an independently retained expected manifest hash for restore authorization.
Hashes provide integrity only when that expectation is controlled; a party able
to replace both image and manifest can recompute them. No signing, encryption,
off-device replication or tamper-proof claim is proposed.

Publication:

1. Allocate an exclusive private `.partial` staging directory under the chosen
   backup root; no completed bundle exists yet. Refuse reused final identities.
2. Produce/checkpoint/close the destination image. Verify and hash its final bytes.
3. Write canonical verification/manifest files, flush and fsync files where
   supported, then close every destination connection/handle.
4. Publish the whole directory through a same-filesystem atomic, **no-clobber**
   operation. On the target Windows platform, use explicitly verified semantics
   that refuse an existing destination; do not use `os.replace` to overwrite it.
   Other platforms/filesystems must supply a proven no-replace primitive or fail
   safely instead of relying on a check-then-rename race.
5. Inspection/restore accepts only the exact completed bundle layout with matching
   manifest/image hashes and verification results. `.partial` names or missing
   files never qualify. Return success only after final publication succeeds.

Atomic namespace visibility is not proof of power-loss durability. Directory
flush behavior, network/removable filesystems, antivirus/open-handle interference
and rename guarantees must be documented/tested for the actual platform. A failed
publication leaves no declared successful recovery point. An uncertain reply
after publication is resolved by inspecting the original backup ID/hash, not
overwriting it with a different artifact.

## 5. Verification policy

Before publication and again before restore, verify required files/identity/size/
hashes, SQLite integrity and foreign keys, supported broker schema, financial
reconstruction, lifecycle/fill consistency, strict gate authority, rejection
evidence, kill/latch/control history and relevant workflow references.

Missing/inconsistent required audit evidence, incomplete financial reconstruction,
CRITICAL findings, unsupported schemas and corrupt/unreadable SQLite refuse
verified publication/restore. Do not infer missing transactions or mark an
unreadable source healthy. A forensic corrupt copy is not a verified backup and
is not a separate feature proposed here.

Historical code-replay unavailability and deliberately omitted sidecar inspection
need explicit scope treatment. Recommend a small documented warning allow-list
for those two limitations only when structural/hash/financial/control checks
fully pass; retain the warnings in the manifest. Missing lifecycle sequences or
unknown required evidence are not eligible exceptions. An alternative strict
HEALTHY-only policy is simpler but can reject valid historical ledgers solely
because the verifier checkout changed. Approval must settle this policy; never
silently allow every WARNING or call limited verification full historical replay.

No backup proves that synthetic FX/prices were factual or that its source was
the latest authorized ledger. No backup procedure changes production data trust.

## 6. Authorized, new-target-only restore

Bind a restore request to a restore ID, independent authorization ID/operator,
reason, explicit time, exact expected manifest hash, chosen backup image and
normalized new target identity. Use a separately supplied trusted local verifier
as with existing recovery; a request string claiming approval is insufficient.
No default authorization or unattended restore is proposed.

Refuse an existing target namespace/file and refuse source/backup/staging/target
aliases. Resolve/validate paths inside explicitly selected recovery roots. Never
delete, reset, rename away or replace an existing original ledger or its sidecars.
An absent target and atomic no-clobber publication avoid an existing active
ledger altogether; they do not prove that the original source has been stopped.
Original-source shutdown is not required for a new **non-executable** inspection
copy, and is not claimed. Hostile owner access to private staging is outside the
application boundary; restrict its access and never treat it as a published ledger.

Restore into a private stage using the verified image and a supported copy/backup
mechanism. Preserve backup artifacts unchanged. Reverify staged financial data and
old controls, add the approved restore fence/audit metadata transactionally, and
validate the resulting target. Its final byte hash differs from the source image
because new quarantine metadata is real data; record both identities distinctly.

Durable restore evidence needs both a target-local receipt and an independently
retained recovery journal. Proposed journal states are PREPARED, PUBLISHED and
FAILED, keyed by exact request hash and restore ID. Commit PREPARED before target
publication; store authorization/reason/manifest and target identity. Publish a
quarantined target bundle atomically, then record PUBLISHED. These are separate
filesystem/database commits, not a distributed transaction. A crash after target
publication but before journal update is resolved by validating the already
published receipt/target hash and repairing only journal outcome metadata through
an explicit retry. It must not issue fills or republish conflicting bytes.

If publication fails, original targets/backups remain untouched. If outcome audit
completion fails after publication, return an unresolved/error outcome, not false
success; preserve the quarantined target and PREPARED evidence for explicit retry.
Changed request under the same restore ID conflicts. Existing target under a
different/unproven restore identity is never overwritten. No automatic restore
retry, order replay, audit synthesis or repair of financial records is allowed.

## 7. Conservative rollback and persistent quarantine

A valid old image may omit later fills, cancellations, kill activation, latch
activation or recovery events. Comparing counts or timestamps cannot prove
latestness; valid branches can have different histories. Preserve the original
target/current-state evidence when available and record observed post-backup
differences, without transplanting events into a fictional historical timeline.
If later history is missing or unknowable, record uncertainty, not an invented delta.

Every restored strict copy is therefore an inspection branch under an independent
persisted restore fence. Preserve the backup's kill/latch bits, block identities
and original audits exactly; the added fence prevents an older unblocked backup
from silently making later restrictions irrelevant. Existing kill clearing or
operational recovery cannot clear this separate fence. No unquarantine API in
Sprint 1K means no automatic or accidental resumption from incomplete history.

Proposed minimum integration: restored copies only use additive schema version 4,
with restore provenance/fence and local restore audit. New code recognizes the
version and checks the fence atomically in gate/shared strict-fill paths and
execution-state identity. Missing/malformed fence metadata fails closed. Old code
rejects the unsupported version rather than ignoring quarantine. Existing live
version-1/version-3 ledgers need not migrate just to create backups. Monitoring
and control-schema recognition need narrowly scoped updates for restored copies.

Legacy images may be backed up/verified as legacy but must not be restored as an
executable legacy broker that ignores a strict fence. Smallest initial restore
scope: support strict version-3 images only, explicitly reject legacy restore.
If legacy restoration is required, it needs an equally enforced non-executable
format or a separately approved migration; do not silently convert its semantics.

Future branch activation must separately resolve post-backup completed/pending
orders, possible discarded fills, all known later restrictions and lost original
state, with explicit rollback/loss acceptance and independent authorization.
It must not interpret an old pending order as proof it was never filled later.
This is intentionally outside this sprint. Historical completed-outcome reads
can remain reads; any new fill from a restored copy rejects while fenced.

## 8. Crash, concurrency and failure-injection strategy

Use temporary synthetic SQLite files, bounded page steps, barriers/events,
controlled connection/filesystem faults and original request identities. No
arbitrary process termination in the normal suite. Planned coverage:

- Populated BUY/SELL ledger with gate/control histories; verify every preserved
  financial/control row and independent reconstruction in the image/target.
- WAL source with committed and queued/concurrent writers. Backup remains
  internally consistent; manifest counts are derived solely from that image.
  Observe source contents are not modified by the backup procedure itself.
- Missing/partial manifests, altered image bytes, corrupt SQLite, unsupported
  versions, financial mismatch and missing/conflicting audit authority refuse.
- Faults during copy, destination checkpoint, hash/verification, manifest write,
  fsync/close and final publication: no partial bundle accepted as complete.
- Restore failures before/after stage verification, fence/audit commit and final
  publication. Existing originals remain unchanged; incomplete stages cannot run.
- Lost publication acknowledgement and recovery-journal completion failure:
  explicit retry resolves the same ID/receipt without overwriting or duplicate fills.
- Target already present or concurrently created/opened: no-clobber refusal.
  Existing-target restore is rejected even if SQLite could obtain a writer lock.
- Reopen the restored copy: exact backed-up fill history, pending statuses,
  kill/latch values and independent fence remain. New fills refuse, including
  attempts after normal kill/operational release. Completed-result reads do not fill.
- Old backups with known later fill/control changes and unavailable current
  state: uncertainty is audited; fence stays active and no automatic resume occurs.
- Unauthorized or conflicting restore requests refuse; restore audit failures
  cannot produce an executable target or falsely claim a complete restore.
- Quotas/disk-full/unsupported filesystem publication behavior fail explicitly.

After approval, run focused tests and then `uv run --no-sync pytest -q` against
796 existing cases. Request exact-command permission if sandboxing blocks it;
install/download/synchronize nothing. No live market-data/broker requests.

## 9. Retention, storage, RPO and RTO

No automatic retention deletion, rotation, compression, off-device upload or
scheduler. Immutable backup identities prevent silent replacement. Operators
choose a local backup root, storage quota and retention policy; check available
space and enforce artifact/page/retry budgets, but disk-space checks are not
reservations and allocation can still fail. Preserve old recovery points and
failed-operation evidence until explicit review. Do not delete a bundle merely
because a newer one exists.

Future policy candidates, not measured guarantees: operator backups after
important control/accounting milestones and before upgrades/restores, with a
daily manual cadence during active research; possible RPO target <=24 hours.
Possible target for producing a verified **quarantined inspection copy** is <=15
minutes for bounded small ledgers, subject to measured storage/verification cost.
Neither target is demonstrated by this design. Recovery-point loss equals the
unknown changes after the selected consistent image; there is no transaction-log
replay of missing later fills. Time to authorize resumed execution is not an RTO
established in Sprint 1K and can remain indefinite while history is unresolved.

Local backups do not protect against loss of the whole device/site or compromised
owner access. No claim of physical durability, off-device disaster recovery,
tamper resistance or market-data correctness is made.

## 10. Approval requested and current change scope

Approve the recommended scope: online SQLite backup with immutable bundle
publication; explicitly scoped invariant verification (including the narrow
historical-replay/omitted-sidecar warning policy); independently authorized
new-target-only restore; a restore audit journal; and persistently quarantined
strict restored copies with additive version-4 recognition and no fence-release
capability in this sprint. No existing-ledger overwrite or automatic reactivation.

If same-path replacement, legacy executable restore, cross-database atomic sets
or quarantine release are required, select that broader architecture explicitly
before implementation. They are not hidden convenience options.

At the original approval gate only this design document was changed. No runtime/test code,
database, backup or restore artifact was modified/created. The supplied 796-test
baseline is not presented as a new test result; regression is deferred to the
implementation phase. No commits, pushes, tags, dependencies or external requests.
The protected pre-existing `scripts/sec_match_recon.py` modification is untouched.

## Approved implementation follow-up

Architecture approval subsequently authorized implementation, with five explicit
conditions: fail-closed hash/identity/SQLite/schema/financial verification;
persistent atomic strict-fill quarantine independent of existing controls;
preservation of records and restrictions during additive schema integration;
explicit authorization/reason and durable publication audit; and interruption
safety without damage to existing destinations. Implementation and operational
limits are documented in `backup_disaster_recovery.md`.

The external restore journal additionally commits SEALED with the final target
manifest hash before namespace publication. This binds post-publication crash
retries to durable evidence; retries cannot derive their trust anchor merely
from the destination they are meant to verify. An altered inspection ledger
requires investigation, not automatic resealing. No broader architecture,
overwrite or quarantine release is included.
