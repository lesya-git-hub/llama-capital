# Sprint 1O Stage A: synthetic coordination

Gate B remains **NO-GO**. This implementation demonstrates isolated authority
semantics using invented evidence and identities. It grants no real market-data
trust and exposes no broker, order, risk or signal-publication integration.
The approved architecture is in `evidence_admission_coordination_design.md`.

## Implemented boundary

`models/evidence_admission.py` defines frozen bundle, evidence, dependency,
source-version, review, principal and inspection-receipt contracts.
`tools/evidence_admission_store.py` owns a separate SQLite database with a
version/application identifier, immutable sealed copies, canonical hashes and a
hash-chained authority journal. No existing database is migrated.
`tools/evidence_admission_coordinator.py` owns all authority decisions.
`tools/synthetic_evidence_participant.py` is a new, isolated mock source store.

The read-only importer seals an existing synthetic 1M batch and reviewed 1N
evaluation after checking source generations before and after capture. Evaluation
replays raw normalization, calendar compilation and provider-finality compilation
independently, and runs the unchanged 1C verifier with a local synthetic root.
Calendar validity, elapsed time and equal hashes do not substitute for finality.
The original observations remain PROVISIONAL; original source stores are unchanged.
Real scope, incomplete six-stock bindings and FX evidence are refused.

Preparation and evaluation confer no authority. A separate authenticated reviewer
must approve the exact bundle hash and current boot epoch with an expiry and
reason. An independent admitter, distinct from both preparer and reviewer, admits
all six members in one event. More than one review holds the bundle, including
when the later review arrives after admission. Failed evaluations, expired reviews,
changed source vectors, pending mutations and restart quarantine refuse use.

The authentication callback and clock are explicit trusted inputs supplied by the
embedding application. Tests supply invented principals. These inputs are not a
production identity/clock service. Tokens are not persisted. Caller-controlled
callbacks are not an authorization boundary against a malicious embedding process.

## Atomicity, history and current use

Each authority operation acquires `BEGIN IMMEDIATE`. State validation, whole-bundle
decision and journal/tail writes commit in that single SQLite transaction with
FULL synchronous mode. Expected denials roll back candidate writes to a savepoint,
then durably append a denial in the outer transaction. SQLite or unexpected failures
roll back and hold that coordinator instance; no successful receipt is returned.
Authentication failures and preflight/identity failures may precede an audited
transaction; they do not alter authority.

Revocation creates an irrevocable tombstone for a bundle, typed content fingerprint,
source, review, grant or synthetic policy. Effective dependency invalidation is
computed from tombstones in the same transaction as each qualified read, across all
six members. Renaming an object cannot escape its typed-content tombstone. Audit
events are authority, rather than an asynchronously updated replica of authority.
Bundle bytes must match both the stored object rows and the original PREPARE hash.

Qualified reads revalidate the sealed evidence and current authority in a write
transaction. They record one synthetic use linearized before or after revocation.
Receipts and replay output are **inspection only**; they are never reusable offline
capabilities. Reusing a qualified-read operation ID is rejected. Other duplicate
IDs return the original historical receipt only when request and actor match;
conflicting reuse is rejected. An already committed read cannot be retroactively
cancelled by a later revocation. There is no downstream consumer or execution API.

Replay folds canonical journal records with an explicit trusted clock. At the same
clock instant the same history produces the same state; advancing the clock may
expire reviews. Admission/revocation retain original immutable hashes, versions,
dependency references, actors, reasons and event order. The local hash chain detects
inconsistency; it is not a signature or protection against an attacker able to
rewrite the entire database and its checkpoints.

## Restart and source-fence protocol

Every new coordinator instance commits a boot epoch, holds serving and permanently
quarantines previously prepared bundles. Previous instances become stale. Explicit
recovery requires a trusted external checkpoint that exists in the local history,
an authorized recovery principal and no unresolved source mutations. Recovery does
not resurrect prior grants or clear revocation. New bundles and reviews are needed.
The operator must retain the latest expected checkpoint outside a restored database;
accepting an old anchor cannot detect rollback of an entire self-consistent file.
No automatic schema repair, audit repair, quarantine release or real admission exists.

The synthetic protocol is deliberately recoverable rather than cross-store atomic:

1. Commit a coordinator fence; affected bundles are immediately quarantined.
2. The mock participant commits its generation and immutable APPLIED outbox receipt
   in one local transaction. A crash before commit rolls both back; a lost reply
   after commit is resolved using the original mutation ID.
3. The coordinator verifies that receipt against the fence and source instance,
   then commits the new source vector and closes the fence. Old bundles stay held.
4. If unapplied, authorized recovery first commits an ABORTED participant tombstone,
   then closes the coordinator fence. Apply and abort share the participant write
   lock, so a late apply cannot follow a committed abort. Absence of an outbox row
   alone never permits coordinator abort. Pending fences survive restart.

Participant receipt reads precede coordinator finalization; their immutability and
the participant's no-bypass write discipline are assumptions of this mock protocol.
SQLite guarantees atomicity only for operations inside its participating transaction.
**Existing 1M/1N writers do not participate.** Mutations after a sealed read-only
import are not automatically detected by this harness. Legacy research APIs are
unchanged and cannot acquire coordinator authority, but are not globally blocked
from research. No claim of production cross-store atomicity or enforced real-source
currentness is made. Production writer/consumer coverage requires separate approval.

## Validation and limitations

`tests/test_evidence_admission.py` covers positive admission and unchanged provisional
inputs; unauthorized/self/stale/conflicting reviews; malformed/raw/incomplete/policy/
dependency/FX evidence; immutable identity conflicts; duplicate and competing requests;
all revocation target types across restart; alias invalidation; both write-lock race
orders for read versus revocation; abrupt process exit; failed audit writes and lost
acknowledgments; participant crashes; apply-versus-abort and recovery-versus-finalize
races; wrong source instances; missing, corrupt and incompatible stores; deterministic
replay; and an empty default production registry. No orders or external calls occur.

The intentionally small prototype bounds bundles to 64, objects per evaluated bundle
to 256, object bytes to 8 MiB, bundle bytes to 16 MiB and journal events to 10,000.
Current-use validation replays all six observations under the coordinator write lock;
it is not a production latency claim. Journal validation is linear and repeated
per operation; replay and storage grow with immutable evidence. Capacity/latency,
filesystem/power-loss qualification, checkpoint custody, real identity service,
source participation and consumer enforcement require further work.

Provider usage/automation/retention rights, official exchange schedules and exceptional
notice coverage, provider completion/revision/adjustment policies, credible acquisition
clocks and future licensed FX evidence remain unresolved. Synthetic success does not
resolve any of them. No dependencies, production registry or financial controls change.
Stop for independent human review; no commits or pushes are authorized.

## Recorded validation

On 2026-11-10, branch `main`, commit `4824f56`:

- `uv run --no-sync pytest -q tests/test_evidence_admission.py`: **46 passed**
  in **52.14 seconds**.
- `uv run --no-sync pytest -q`: **1,013 passed** in **185.49 seconds**,
  preserving the **967-test** baseline plus the **46** new cases.

The sandbox could not initialize the existing user uv cache; the exact offline
commands ran with approved escalation and `--no-sync`. No dependency installation
or external request was performed. The protected `scripts/sec_match_recon.py`
retains its pre-existing SHA-256
`7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`.
The prior architecture document is retained unchanged. No implementation files
outside the six new model/store/coordinator/participant/test/notes files changed.
