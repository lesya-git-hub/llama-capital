# Sprint 1O — Evidence admission and revocation coordination

Date: 2026-11-10 (Europe/Dublin). Inspected baseline: `main`, `4824f56`.
Supplied regression baseline: **967 passing tests**, not rerun for this design.

## 1. Executive recommendation

Introduce **one authoritative SQLite coordination ledger** containing immutable
six-stock evidence bundles, dependency identities, independent review/authorization
receipts, effective admission state and append-only audit events. Make admission,
revocation and qualified-use decisions linearize at commits in that database.
Other stores retain provenance and historical research; their rows, exported pins
or completed copies do not independently confer current authority.

Do not attempt to make separate current SQLite files a distributed atomic store
by performing two checks, comparing timestamps, or assuming an attached multi-file
transaction is power-loss atomic in every journal/filesystem configuration.
Instead, stage immutable copies, validate their complete dependency set, then
atomically admit the whole bundle and its authority receipt in the coordinator.
Recoverable copies to other stores happen afterward and remain non-authoritative.

**A critical qualification:** coherent, current cross-store admission requires
all relevant source writers to participate. Before changing a source, a managed
writer must durably acquire a coordinator mutation fence; source mutation and its
outbox receipt commit together; finalization incorporates the resulting generation
and invalidates affected old authority before releasing the fence. An untracked
source write cannot be made safe by a read adapter alone.

Request approval first for **Stage A: an isolated, synthetic-only coordinator
prototype**, immutable bundle import, atomic local admission/revocation/audit,
dependency invalidation, restart holds and deterministic crash/race tests. Use
read-only 1M/1N snapshots and separate synthetic participant databases to exercise
the future writer protocol. Do not modify original stores or claim their writers
are already coordinated. No real admission, production pins, broker integration,
FX enablement, scheduler or deployment belongs in Stage A.

**Gate B remains NO-GO.** This document is the only change. No test, provider
request/download, installation, trust change, order, commit or push was performed.
The protected script's pre-existing change is untouched; observed SHA-256:
`7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`.

## 2. Actual stores, identities and entry points

The following inventory comes from implementation inspection, not documentation
claims alone. Existing application IDs identify database **types**, not unique
instances. No current application ID, path or content hash is a replacement for
an authenticated authority or registered database-instance identity.

### Source and evidence stores

- **1D synthetic source archive:** `SourceSnapshotStore` in
  [providers/offline_market_data.py](../providers/offline_market_data.py).
  `source_batches` stores canonical synthetic batches by content SHA-256 and
  session date; no dedicated database application/version identity is established
  by this class. `save/load`, `assemble_source_batch` and
  `OfflineDailyOHLCVProvider.fetch_daily` do not admit real trust. Source candles
  remain provisional. Treat this as legacy synthetic provenance only.
- **1M provisional archive:** `ProvisionalArchive` in
  [providers/provisional_market_data.py](../providers/provisional_market_data.py),
  application `0x4C4C504F`, schema 1. Tables: `observations`, `normalization`,
  `batches`, `conflicts`. Identities include observation ID, predecessor, source/
  dataset/version/feed, requested dates, raw and metadata hashes, normalizer hash,
  calendar hash, batch ID/hash and normalized candle hashes. `record`, `normalize`,
  `save_batch`, `load_batch` and `acquire_recorded_batch` provide immutable API
  history. `conflicts(id)` exposes new-to-old edges; later reverse conflicts must
  also be considered. `ProvisionalDailyProvider.fetch_daily` always returns
  `final=False`. `licensed_offline` is a declaration, not a license grant.
- **1N evidence/review store:** `EvidenceStore` in
  [tools/calendar_finality_store.py](../tools/calendar_finality_store.py),
  application `0x4C4C4546`, schema 1. Tables: `sources`, `reviews`, `evaluations`.
  Source records bind raw BLOBs, receipt metadata/hash and explicit revision
  ancestry. The source-corpus hash follows source sequence/content; it does not
  alone summarize review decisions or the separate 1M database. Review IDs/hashes
  bind request/source corpus and authorized synthetic review. Evaluation IDs/hashes
  bind source/archive generations, manifest, review and engine fingerprint.
  These records currently provide synthetic evaluation, not real admission.

### Verification, publication and trust objects

- **Standalone frozen artifacts:** JSON calendars, provider evidence, raw/normalized
  snapshots, environment records and exported reports also carry version/content
  identities outside SQLite (for example `load_snapshot` / `load_experiment` in
  [tools/historical_snapshot.py](../tools/historical_snapshot.py)). File presence,
  a canonical hash or reproducible historical output has no current admission
  state. Imports must bind these exact objects to coordinator provenance; nothing
  is grandfathered into authority merely because a legacy loader accepts it.
- **1B daily-signal store:** `DailySignalStore` in
  [tools/daily_signal_pipeline.py](../tools/daily_signal_pipeline.py), application
  `0x4C4C4453`, schema 1. `runs` binds run ID, inputs/report hashes and frozen JSON;
  `run_verification` links optional verification JSON/hash. `publish` atomically
  writes a run and supplied verification metadata, but is a legacy research API,
  not an independent authority check. A row's existence is not admission.
- **1C artifacts/root:** [tools/market_verification.py](../tools/market_verification.py)
  defines `CalendarArtifact`, `ProviderEvidenceArtifact`, `CandleEvidence`,
  `TrustPin`, `TrustRegistry` and `verify_candle_finality`. `TrustRegistry` is a
  caller-supplied in-memory exact-content root, defaulting to real scope with no
  pins. It has no persistent epoch, authenticated administrator or revocation
  lookup. A review-reference string is not authentication.
- **1C entry points:** [tools/verified_daily_pipeline.py](../tools/verified_daily_pipeline.py),
  `freeze_verified_daily_inputs`, `replay_verified_daily_signals`,
  `publish_verified_daily_signals`, `load_verified_daily_signals`,
  `ingest_verified_daily_signals`. They validate exact supplied roots, scope,
  finality, chronology, environment and regenerated records. They do not consult
  current revocation state. Replay using an old root can establish historical
  consistency without establishing current permission to use the evidence.
- **1N evaluation boundary:** `compile_calendar` / `compile_provider_evidence` in
  [tools/calendar_finality_compiler.py](../tools/calendar_finality_compiler.py)
  reject competing overlapping calendars, omitted notices, incomplete claims and
  real-world compilation. `evaluate_candidate` / `replay_candidate` in
  [tools/calendar_finality_review.py](../tools/calendar_finality_review.py)
  return synthetic projections or holds. 1N compares its source generation and
  competing reviews inside its result write transaction. It checks 1M history
  separately before that commit; a later 1M write remains a race. Its local
  synthetic pins are neither persisted production pins nor an admission service.

### Other relevant consumers and recovery boundaries

- **FX:** [tools/fx_conversion.py](../tools/fx_conversion.py) has `FXQuote`,
  `CanonicalFX`, optional exact-content `FXSourcePin` / `FXTrustRegistry`, quote
  chronology/freshness checks and conversion/replay. No persistent FX authority
  store is implemented. `FXQuote.scope` is synthetic or unverified;
  `convert_risk_inputs` explicitly requires synthetic FX. No trusted real FX exists.
- **Workflow sidecar:** `WorkflowStore` in
  [tools/paper_orchestration.py](../tools/paper_orchestration.py), application
  `1280070487`, schema 1: `previews`, `authorizations`, `steps`, `reports`.
  Requests/outcomes are hash-linked but commit separately from broker accounting.
  Workflow preview checks synthetic roots and identity; this is not a persistent
  evidence-revocation consumer.
- **Financial boundary:** [providers/paper_broker.py](../providers/paper_broker.py)
  and [tools/gated_execution.py](../tools/gated_execution.py) retain independent
  strict-fill transactions, kill switch, operational latch and restore fence.
  Direct gated requests do not currently enforce this proposed evidence authority.
  This design does not alter or certify that boundary for real trading.
- **Backups:** [tools/backup_recovery.py](../tools/backup_recovery.py) backs up the
  broker and restores strict v3 into quarantined v4 copies. Its restore journal
  (`0x4C4C524A`, schema 1) is separate. These bundles are not atomic backups of
  1M/1N/signal/FX/coordination authority. They must not be treated as such.

## 3. State model: immutable evidence versus current authorization

Source bytes and original 1M/1N statuses are never changed to manufacture trust.
The coordinator owns new, scoped **derived admission records**, not an update of
the provisional archive's status column. State is qualified by object kind,
synthetic/real scope, purpose, authority instance and policy epoch.

- **PROVISIONAL:** raw capture, imported bundle or prepared candidate. Integrity
  and complete transport may be known, but independent review/authority is absent.
- **REVIEWED:** a current independent decision accepts exact content/dependencies
  for a specified purpose and cutoff. This is an approved assessment, not a grant.
  A successful 1N `ELIGIBLE_FOR_1C_PROJECTION` evaluation alone is not this state.
- **ADMITTED:** a separate authorized coordinator transaction commits the complete
  bundle, dependency closure, current review and audit receipt. This permits only
  the named governed evidence/research operation while its effective state remains
  valid. It is not order authorization or Gate B approval.
- **REVOKED:** an append-only deny decision applies to a named target: grant,
  artifact digest/version, review, license, clock policy, source/feed or policy
  epoch. Terminal for that target; no automatic un-revoke or ID aliasing. A grant-
  only revocation differs from revoking its underlying artifact. New candidates
  need new IDs/reviews and must still reject every applicable revoked dependency.
- **QUARANTINED:** current permission is blocked because evidence, history,
  currentness, recovery or integrity is uncertain. This deny state is sticky.
  Health checks, matching hashes, an elapsed lease or a source copy completing
  never release it. Any future recovery action needs separate authorization,
  reason and evidence, returning to PROVISIONAL/review, not directly to ADMITTED.

Transitions: `PROVISIONAL → REVIEWED → ADMITTED`; any relevant uncertainty can
quarantine a candidate/grant; authorized revocation denies applicable targets and
all dependent uses. A changed dependency invalidates REVIEWED and requires a new
review. Rejection/denial, preparation and pending mutation are explicit events or
workflow phases, not optimistic authorization states.

An immutable historical ADMITTED event remains in the audit after revocation;
the **effective current state** is derived from current denies and dependency
validity. Merely finding an earlier ADMITTED row must never return permission.
Evidence quarantine is distinct from the broker operational latch, kill switch
and restore quarantine; no cross-clearing API is proposed.

## 4. Recommended architecture and atomicity guarantees

### One authority; immutable bundles; non-authoritative mirrors

A new coordinator database stores:

- Authority UUID, schema/policy versions, boot/restore epoch and startup hold.
- Registered source-instance IDs, expected database types/schema, current managed
  generations and durable pending mutation records. Path/app ID alone is insufficient.
- Content-addressed immutable objects and sealed bundle manifests containing the
  entire six-stock observation/evidence set, required raw bytes where licensed,
  proofs, calendar/listings/notices, action/clock/license provenance and fingerprints.
- Explicit dependency/reverse-dependency edges, current deny targets and epochs.
- Immutable preparation, review, grant, revocation, use, recovery and audit events.
- Recoverable outbox entries for optional copies to research/report stores.

Objects/chunks may be staged before review to keep the admission transaction
bounded. A bundle becomes sealed only after its expected membership, lengths,
hashes and complete dependency graph validate. Reject cycles, dangling edges,
unknown object kinds and incompatible versions. Staging or sealing is not trust.
Do not rely on hashes instead of retaining data required for lawful replay.

Bundle identity binds the exact canonical six-stock universe, session window,
all warm-up candles/proofs, normalized/raw hashes, 1M and 1N IDs/generations,
calendar and revision/notice corpus, reviewer decisions, policies and source/
dependency/tzdata versions. No one-ticker-at-a-time admission. One bad/missing
symbol, conflicting calendar, unresolved reverse revision, stale review, false
finality or licensing gap denies the whole bundle.

### Admission transaction and its linearization point

1. Authenticate the preparer and import immutable copies from consistent source
   snapshots; record explicit source generations. Do not infer a simultaneous
   cross-file snapshot merely because the reads happened close together.
2. Independently evaluate using unchanged 1C/1M/1N requirements. Compute any future
   research output against frozen inputs before the short commit transaction.
   An evaluator has no admission credential.
3. An independent reviewer signs/authorizes the exact bundle, source-generation
   vector, dependency closure, purpose, policy and review expiry. Capture competing
   and denied decisions; do not let the applicant select a favorable review.
4. A separately authorized admission request names that exact reviewed object and
   expected authority/dependency epochs. Under `BEGIN IMMEDIATE`, require a healthy
   recovered authority, no relevant pending source fences, current participant
   acknowledgements, valid roles, unique request identity, no applicable denies
   and complete unchanged dependency/review state.
5. In **one coordinator transaction**, commit the whole grant, membership/dependency
   bindings, current-state index, audit and any qualified research-output record
   or mirror-outbox request. Only acknowledged commit is admission success. If
   audit cannot commit, there is no new admission.

**Linearization point: this commit.** An existing daily-store row is not a second
commit that must also succeed to make the grant real. A qualified consumer uses
the coordinator's committed canonical object/receipt. Optional 1B mirrors are
historical copies; a partial/failed mirror cannot create authority. If mirroring
is required by an operator workflow, report `MIRROR_PENDING` separately rather
than falsely declaring all copies complete.

### Source mutation fencing: required future participation

Immutable copied bytes solve partial-copy visibility, but do not prove that no
later conflicting source/review exists. Before claiming currentness:

1. Every relevant managed writer requests `begin_source_mutation` with authenticated
   source instance, mutation ID and expected generation. Coordinator commit records
   a persistent fence and quarantines/blocks dependent new uses **before** a source
   write is permitted. Start with conservative whole-source fencing.
2. The source transaction writes the immutable change and a participant outbox/
   generation receipt with that mutation ID atomically in its own database.
   Proposed additive participant metadata would need approval and compatibility
   tests; it does not exist in current 1M/1N schemas.
3. `finish_source_mutation` verifies original source-instance identity, receipt,
   complete new snapshot and conflict/dependency effects. Coordinator commit
   registers the generation, appends invalidation evidence and closes that pending
   mutation. Closing a fence does not readmit quarantined old grants.
4. A crash before source commit leaves a durable deny fence; a crash after source
   commit leaves the same fence and a recoverable outbox receipt. Recovery resolves
   the original mutation ID, never assumes success/failure from elapsed time.
   A missing/replaced source or ambiguous outcome keeps the hold.

This is a safely recoverable protocol, **not two-file atomic commit**. Availability
is deliberately lost while a mutation is unresolved. All relevant 1M record/
normalization/batch writers, 1N source/review/evaluation writers and future FX/
license/notice authority writers must be routed through enforced participating
interfaces before live-currentness claims. Read-only source inspection is not
enforcement. An unmanaged writer or unregistered replacement invalidates that
guarantee; block governed serving until coverage is established.

Stage A can simulate this with new synthetic participant stores and read-only
imports, without claiming the existing production-facing writers participate.
Actual 1M/1N integration, additive schemas and filesystem/process permissions are
a separate implementation stage requiring approval.

### Why not the alternatives?

- **Double-check generations:** still permits a write immediately after the final
  check. Keep hashes for detection, but do not call this atomic admission.
- **Rely on SQLite ATTACH across current files:** multi-file crash guarantees vary
  with WAL/journal/filesystem configuration. It would couple unrelated private
  schemas and migrations. No cross-file power-loss guarantee is assumed or proposed.
- **Merge every existing store now:** could give a larger single-file transaction
  domain, but requires disruptive migration and broader compatibility work. The
  smaller design centralizes authority and immutable admission inputs first.
- **TTL-only or a cached signed registry:** expiry can restrict a grant but cannot
  prove finality or prevent use after an earlier revocation. A live authority check
  is required for governed operations; disconnected caches deny.

## 5. Revocation, invalidation and qualified use

`revoke(target, reason, incident_evidence, authorization)` is deny-only and requires
an authenticated incident/revocation role. It need not wait for a second human
to approve a safety hold. Granting/recovery still require independent approval.

In one coordinator transaction: validate target/request identity; append the
revocation and reason; make its tombstone effective; advance the deny epoch;
invalidate applicable review/grant/use authority; and commit required audit.
Return successful revocation only after commit. Reverse-edge materialization and
notifications may follow via outbox, but access checks must already deny when
**any** dependency is revoked/quarantined, even before those secondary rows update.
No notification or periodic background task is relied on to enforce the denial.

Track dependencies on raw releases, observations, normalizer/action policy,
calendar/listing/notice coverage, provider completion, clock proof, licenses,
reviewers/decisions, verifier environment and later FX. Revoking a shared calendar
can invalidate many grants; a changed old warm-up candle can invalidate a later
signal. Preserve all original artifacts and historical outputs subject to rights;
mark their current use invalid rather than rewriting them or financial records.

The first implementation should favor complete dependency traversal and conservative
holds over a clever incremental cache. An index is an optimization, not a way to
ignore a deny. If the closure is too large to validate within its documented
resource budget, fail closed; no demonstrated latency/SLA is implied here.

### Qualified-use gateway

Do not export an indefinitely reusable production `TrustRegistry` as a capability.
A proposed `with_qualified_evidence` / `commit_qualified_publication` interface
authenticates purpose/principal and checks the live coordinator, current dependency
states, source fences, expiry/clock certainty and authority epoch. A returned
ticket binds authority UUID/epoch, grant, bundle, purpose, principal and request;
it is a lookup reference, not standalone permission for offline use.

Read/use and revocation have a defined order under the coordinator's lock. A
revocation that commits first makes a later governed operation deny. A bounded
pure use already linearized before revocation may finish; delivered information
cannot be retracted. A publication computed earlier must revalidate and commit
its authoritative publication record under the same coordinator transaction as
its current-use decision. Slow/external side effects are not executed while
holding this transaction; they require a separately specified outbox/consumer
protocol and must not be represented as instantaneously revocable actions.

**Guarantee boundary:** this governs evidence/research authority, not financial
fills. It does not add checks to direct broker calls, guarantee that a revocation
interrupts an in-flight fill, or clear a kill/latch/restore hold. Preventing all
financial use without a fresh admission check at the financial commit boundary
would require another expressly approved broker/execution architecture. Gate B
must not be opened on the strength of this evidence design alone.

## 6. Authorization and prevention of self-approval/bypass

Proposed roles: acquisition/preparer, independent reviewer, admission operator,
deny-only incident operator and recovery operator. Trusted authentication maps
identities/roles outside request metadata; strings such as `operator_id` or a
reference to a license are not credentials. Enforce preparer/subject-authorizer
separation from reviewer, and require the admission actor's separate permission.
A single operator may occupy only combinations expressly allowed by the reviewed
policy; the default prohibits preparing and approving one's own evidence.

Approval binds exact content, subject, scope/purpose, generation vector, expiry,
policy, expected authority epoch and operation ID. Scope cannot be changed from
synthetic to real. Denied, conflicting, revoked, expired or stale reviews never
become authority by repetition or by choosing another review ID. Independent
callback/authenticator failure denies; a production identity service is not
assumed to exist today. Stage A uses an injected deterministic synthetic verifier
and synthetic identities only, not fabricated real credentials.

Keep legacy research APIs available for compatibility but **outside the qualified
authority namespace**. They can still write research rows and accept caller-made
roots. Governed consumers must refuse a bare 1B row, old 1C verification JSON,
1N eligibility result, workflow authorization or caller-supplied pin set lacking
a current coordinator decision. Synthetic research output cannot be presented
as a production-qualified output merely by renaming its file or copying metadata.

Deployment must restrict writer/authority credentials and file ownership to the
governed service, and eligible consumer configuration must point only to that
service. A library wrapper alone cannot prevent arbitrary Python/direct SQL with
the same privileges. Until those integration controls are approved and tested,
report **no repository-wide bypass-prevention guarantee**. In particular, existing
legacy ledgers and direct gated execution remain outside this new evidence gate.
No current broker/risk/API behavior is changed in this design or proposed Stage A.

## 7. Restart, audit, recovery and storage failures

Use immutable operation IDs plus request hashes for exact idempotent retries.
After lost commit acknowledgement, look up the original ID and validate its full
receipt; never create a replacement grant, review or revocation to guess an outcome.
No success response precedes both effective authority state and required audit.
Denials are durably recorded when storage allows; inability to record an audit
denies the operation rather than inventing evidence.

On startup, default governed serving to a persistent/startup **QUARANTINED** state.
Validate expected authority/source instance IDs, schema, object hashes, event
continuity, deny state, dependency closure and pending mutations/outboxes. Missing
or corrupt authority is not initialized as a fresh empty real root. Drain only
idempotent, fully evidenced recovery work. No healthy report, expired timeout or
absence of a source row automatically releases a hold.

Recovery requires an explicitly authenticated reasoned action and a fresh boot/
restore epoch. A restored authority is not permitted to resurrect old grants,
reader tickets or reviews by reusing old instance/epoch state. Broker-only backups
do not recover this authority. Define a separate evidence/coordinator backup and
legal retention inventory before any real deployment.

**Rollback boundary:** local hashes and a restored SQLite file cannot independently
prove that no later revocation existed. Anti-rollback requires an independently
retained trusted checkpoint/epoch or equivalent external authority and a verified
recovery procedure. Without that evidence, remain quarantined; do not infer
freshness from a valid old database. Privileged filesystem replacement of all
history is outside a local checksum-only guarantee.

If revocation/audit commit fails or its outcome is uncertain, stop the process's
qualified serving immediately and do not acknowledge durable revocation. A dead
or full device may prevent *any* persistent write. Restart must stay denied until
authorized recovery reconciles expected external checkpoints and pending incident
requests; it cannot silently resume from the last readable ADMITTED row. Stage A
can test these failure decisions with synthetic anchors, but proves no physical
durability or real off-device recovery.

## 8. Future trusted FX integration

Reserve a typed dependency domain for FX observations/releases, pair/direction,
quote and raw hashes, effective/retrieval times, source/license, adjustment/spread
convention, clock evidence, freshness policy, reviewer and conversion environment.
Do not coerce an equity calendar pin into an FX pin or interpret a synthetic FX
quote as real. Current `FXTrustRegistry` is separate, optional and empty by default;
real FX acquisition/admission and real risk conversion are not implemented.

An equity-only grant may have purpose **USD research signals** and explicitly
`FX_NOT_INCLUDED`. A future **EUR valuation** composition must atomically bind
current admitted equity and FX dependencies, valuation time, conversion policy
and rounding at one coordinator decision. Revoking either invalidates the composed
use. Separate cached equity/FX approvals cannot be combined without that check.
Freshness expiry can deny use; it does not create provider finality. Actual FX
licenses, feed authenticity, economics and execution integration remain separate
approval gates; existing FX/risk code is unchanged.

## 9. Threat model and failure matrix

Protect against accidental stale/cross-scope use, bypass through unqualified
research records, missing/contradictory evidence, concurrent valid writers/reviewers,
crashes and lost acknowledgements, partial copy/audit writes and detectable file
tampering. Trust only the approved authentication boundary, governed writer
coverage, original issuer evidence and correctly functioning supported storage.
Do not claim protection against a privileged owner replacing all keys/history,
unreported external provider corrections, dishonest issuers or unobserved legal
changes. Notice acquisition and legal review remain operational requirements.

| Failure | Required behavior and evidence |
|---|---|
| Incomplete six-stock import or one missing warm-up proof | Retain provisional staging; no partial REVIEWED/ADMITTED grant; exact membership and closure tests reject. |
| Conflicting overlapping calendars, notices, releases or reverse revisions | Quarantine candidate/dependent use; retain both versions and dispositions; no manifest omission or latest-write-wins selection. |
| Concurrent approvals/denials or changed generation | Admission CAS/role checks and current review/deny scan under one coordinator writer reject stale or competing decisions. |
| Crash while copying objects | Unsealed objects have no authority; deterministic cleanup/retry is explicit and never fabricates completion. |
| Crash before admission commit | No grant. Exact-ID recovery distinguishes uncommitted preparation from admission. |
| Commit succeeded, acknowledgement lost | Original-ID lookup returns the same validated receipt; no duplicate grant/use. |
| Source fence committed, source write not yet committed | Dependent use remains denied. Recovery verifies original participant instance/outbox and mutation ID; no timeout release. |
| Source write committed, finalization absent | Durable fence plus source receipt survive; reconstruct generation/invalidation and finalize idempotently, not optimistic serving. |
| Legacy/unmanaged source write | Currentness guarantee is unavailable. Governed deployment must block or quarantine until that writer is integrated; a periodic hash scan is only detection. |
| Revocation races with admission/publication | Shared coordinator transaction order decides; revoked dependency cannot win a later admission/qualified-publication commit. |
| Revocation races with an already completed read | New use denies after revocation commit; previously delivered bytes remain historical information, never an irrevocable capability. |
| Partial 1B mirror write or sidecar failure | Coordinator remains sole authority; mirror marked pending/failed, never treated as independently trusted. Retry same output ID/hash only. |
| Tampered body, graph, review, audit or schema | Refuse serving/replay/admission and quarantine; no automatic evidence repair or migration. |
| Full disk, failed revocation audit or uncertain commit | No success acknowledgement; process stops qualified serving; startup hold requires evidenced recovery. No durability claim on unavailable storage. |
| Old authority/source backup selected | New restore epoch and quarantine; old tokens/currentness cannot be resurrected. Missing external anti-rollback evidence prevents recovery. |
| Consumer uses old pins or legacy report directly | Qualified gateway rejects missing/currently invalid authority receipt. Existing non-governed APIs remain research, not protected financial consumers. |
| FX missing, stale or revoked | USD-only purpose stays explicit; EUR composition denies without current typed FX dependencies. No synthetic substitution. |
| Provider/license/exception notice changes externally | Protocol acts when change is durably accepted; it cannot guarantee awareness before receipt. Intake latency/coverage is an unresolved real-operating requirement. |

## 10. Proposed interfaces, schema and synthetic test plan

Candidate new modules, subject to approval:

- `models/evidence_admission.py`: typed bundle/dependency refs, registered source
  identity, role/purpose-bound requests, review/grant/revocation/quarantine events
  and current-use receipts. Explicit synthetic/real scope; Stage A permits only
  synthetic authority operations and returns real candidates PROVISIONAL.
- `tools/evidence_admission_store.py`: isolated coordinator identity/schema,
  immutable objects/bundles, dependency indexes, CAS epochs, states, operation/audit
  journal, pending mutations and outbox. `prepare_bundle`, `record_review`,
  `admit_bundle`, `revoke`, `quarantine`, `lookup_operation` and startup inspection.
- `tools/evidence_admission_coordinator.py`: role validation, deterministic 1C/1M/
  1N evaluation/import adapters and `with_qualified_evidence`; no returned production
  pin-management interface, financial operation or live acquisition.
- `tests/test_evidence_admission_coordination.py`: invented fixtures, temporary
  synthetic participant stores, injected clocks/authenticators/faults and event-
  coordinated thread/process tests. No live provider or order calls.
- `docs/evidence_admission_coordination.md`: exact guarantee/implementation stage,
  source participation coverage, failure/recovery and legal retention procedures.

Schema invariants: unique operation ID/request hash, unique canonical bundle
membership and dependency keys, required audit-to-transition linkage, immutable
artifact digests, referential integrity, monotonic authority/deny generations,
explicit original source-instance identity and terminal per-target revocation.
Document bounds for object bytes, closure size, lock work and retries. Fail
closed on exceeded budgets; no hardware/latency guarantee is assumed.

Synthetic acceptance tests must prove:

1. Valid whole-batch admission and deterministic replay; no source observation
   status changes; incomplete batches and unsupported scopes never admit.
2. Evaluation success without independent review/admission still denies use;
   preparer self-approval, wrong roles/purpose, forged/expired/stale credentials
   and exact-ID payload conflicts reject.
3. Conflicting calendar keys, omitted notices, reverse archive revisions and
   competing reviews cannot be hidden by manifest or reviewer selection.
4. Admission, audit and authoritative output visibility commit together. Inject
   failures before/after every write and acknowledgement; verify all-or-none
   membership, original-ID recovery and no false success.
5. Revoked calendar/raw/action/license/review dependencies deny every affected
   grant immediately, including before reverse-index/outbox completion. Revoked
   bytes cannot evade a tombstone through a renamed ID.
6. Deterministic barrier races for review/admit/revoke/read, checking actual writer
   acquisition and serialization rather than sleeps. Validate both transaction
   orders and the stated allowance for reads already linearized before revocation.
7. Synthetic participant fence/outbox crash recovery, forks, source replacement,
   missing receipt and stale-generation finalize; no lease/time-based recovery.
   Tests must state clearly that mocks do not fence actual unchanged 1M/1N writers.
8. Mirror failure and unauthorized legacy publish/caller-made root remain outside
   qualified authority. Copying files/rows/old tickets cannot create admission.
9. Startup after crash/restore stays held; missing schema/evidence, old epochs,
   corrupted audit and absent anti-rollback checkpoint never create a fresh real
   authority or automatically release quarantine.
10. FX placeholder alone denies EUR use; future synthetic composition/revocation
    covers both domains without changing real FX/risk behavior.
11. Replay reports historical and current status separately. Old snapshots can
    reproduce history only in inspection mode, never bypass a current deny.
12. No network/dependency installation, production pin mutation, broker/risk/order
    calls or unattended work. Preserve all 967 existing regression cases.

Existing evidence tests to retain include:
[test_calendar_finality_evidence.py](../tests/test_calendar_finality_evidence.py)
(`test_evidence_changed_before_result_commit_fails_without_success`,
`test_review_generation_is_checked_inside_its_write_transaction`,
`test_competing_review_before_result_commit_prevents_eligible_return`,
`test_manifest_cannot_hide_conflicting_overlapping_calendar_snapshot`,
`test_real_1m_batch_is_isolated_even_when_request_claims_synthetic`);
[test_market_verification.py](../tests/test_market_verification.py)
(`test_empty_default_real_trust_and_cross_scope_rejection`,
`test_records_cannot_be_self_authorized_or_tampered`,
`test_all_or_nothing_verified_publication`);
[test_provisional_market_data.py](../tests/test_provisional_market_data.py)
(`test_provisional_ingestion_cannot_publish_any_verified_run`,
`test_changed_overlapping_windows_are_durably_detected_and_replayed`);
[test_fx_conversion.py](../tests/test_fx_conversion.py)
(`test_unapproved_source_is_rejected_when_required`,
`test_risk_boundary_rejects_unverified_fx_and_binary_floats`).
These are inspected assertions, not new test-run results.

## 11. Implementation stages and real-world blockers

**Stage A — requested first scope:** new synthetic-only coordinator database,
read-only sealed imports from 1M/1N, independent synthetic authorization, atomic
local whole-bundle admit/revoke/quarantine/audit, current-use gateway, original-ID
recovery and deterministic tests. Model future source participation with new
temporary synthetic stores; retain explicit refusal for real admission. No
original-store migration, legacy writer modification, signal-store publication,
broker/risk change, production registry or external identity service.

Stage A proves local authority semantics and simulated recoverable coordination,
**not actual cross-store writer enforcement or real currentness**. Its output and
documentation must label that limit. Approval does not authorize Stage B work.

**Stage B — separate architecture/implementation approval:** add source instance/
generation/outbox participation to all relevant real 1M/1N writers without
weakening their contracts; establish process/file permissions and governed
consumer routing; implement and test actual source mutation fences and
recoverable research-store mirrors. Verify source registration/restore behavior
and role separation. Only after full writer coverage may the system claim to
close the current post-check source-write race within its stated trust model.
Real admission stays disabled absent separate evidence approval.

**Stage C — separate real authority/deployment gate:** establish actual provider
rights and completion evidence for every required candle, official listings/
calendar/exception-notice coverage, independently credible acquisition clocks,
adjustment/revision provenance, approved retention/replay rights and authenticated
independent operators. Qualify startup/anti-rollback recovery and any future FX
authority. Review actual-source latency, storage capacity and source/consumer
coverage; no hash, elapsed time, successful API response or synthetic test result
substitutes for these facts. No live research is performed in this design.

Future financial-use enforcement, FX/risk enablement, scheduling, automatic
execution and cloud operations require their own approvals. No architecture
proposal here opens Gate B or alters existing financial restrictions.

## Approval gate

Approve or revise **Stage A only**: synthetic coordinator semantics, isolated
bundle/dependency state, admission/revocation audit, recovery and simulated
participant protocol, with read-only existing-store inputs. The Sprint 1O Phase 1
instruction requires stopping before implementation. This document stops there
for human review; Gate B remains NO-GO.
