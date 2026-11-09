# Sprint 1L — Operational readiness and paper-trading launch audit

Audit date: 2026-11-09 (Europe/Dublin). Inspected HEAD: `0bf59ff` on `main`.
Proposed experiment: EUR 10,000, MSFT/AAPL/JPM/XOM/JNJ/WMT, US-listed equities,
long-only, 90 calendar days, simulated orders, initially local and explicitly
authorized. No profitability conclusion is made.

## 1. Executive decision

**Gate A — Offline synthetic rehearsal: CONDITIONAL GO.** The repository provides
a substantial deterministic research and strict paper-accounting foundation.
A trusted local operator can rehearse the workflow with explicitly synthetic
inputs, a newly created strict ledger and manual authorization. This is permission
to consider that restricted operating mode, not evidence of a completed 90-day
rehearsal or authorization to execute anything during this audit.

**Gate B — Real-world forward paper trading: NO-GO.** There is no accepted
end-to-end real observation path. Production market trust defaults to empty;
the new provider adapter, FX risk converter and workflow deliberately restrict
execution inputs to synthetic scope. Provider licensing, authoritative calendars,
candle finality, actual execution-price evidence, authenticated FX, an enforced
experiment policy and an operating control plane remain launch-critical gaps.
Changing a scope label or copying fixture trust pins would invalidate the safety
boundary rather than close these gaps. [E2–E7, E10]

No strict public financial-fill path was found that directly invokes manual
accounting without the gate. This finding has an important limit: strict mode
enforces **a caller-supplied risk calculation**, not authenticated workflow
approval or immutable experiment limits. `PaperBroker.execute_gated` can be
called directly without `Authorization`; its request supplies risk policy,
prices and signal time. It must not be described as a complete operational
authorization boundary. [E7–E9]

Recommended next sprint: **Sprint 1M — Licensed observation, calendar and finality
onboarding**, beginning with an approval-gated evidence assessment. Keep Gate B
closed until its evidence is accepted and the later execution/operations gates
are independently reviewed.

## 2. Audit method and evidence limits

This is a fresh static inspection of code and selected test bodies at the stated
commit, including the provider, verifier, FX converter, risk evaluator, broker,
gate, workflow, monitoring, controls, backup and fence implementations. Test
names below identify inspectable assertions; they are not new execution results.

The supplied baseline is **858 passing tests**. The preceding Sprint 1K record
also reports 858 passes, but this audit did **not** run pytest, import entry points,
open operational ledgers, create orders, simulate fills, request external data or
inspect secret values. No test run was needed to establish the structural launch
blockers, so no test-execution permission was requested. Any new test run requires
permission for its exact offline command. Prior pass counts do not establish
physical durability, provider truth, authentication or 90-day availability.

Only this new report is created. Existing runtime code, tests, configuration and
documentation remain unchanged. The pre-existing worktree modification to
`scripts/sec_match_recon.py` is excluded. Its observed SHA-256 is
`7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`.
No commits, pushes, dependencies, external services or deployment were used.

## 3. System inventory and evidence-based scorecard

READY means verified for the explicitly stated narrow mode by inspected code and
existing test assertions; it does not imply a fresh test result. CONDITIONAL means
usable only with the restrictions stated. BLOCKED means a launch-critical element
is absent. UNKNOWN means evidence is insufficient. These are domain decisions,
not numbers to average.

### Daily strategy and session selection — CONDITIONAL

`DailyStrategyConfiguration` fixes the V1 mean-reversion parameters, two variants,
200 completed-session minimum and SELL-before-BUY signal conflict rule.
`DailySignalInputs.validate_completed_inputs` requires exactly the six tickers,
matching session dates, available final candles, USD and declared split-adjusted
bases. `replay_daily_signals` checks hashes/environment and produces position-
independent conditions. It does not size orders or establish investment merit.
The intended experiment must select one variant before launch, or use separate
EUR 10,000 ledgers for separate experiments; combining variants in one portfolio
changes the experiment. The 90-day stop date and terminal valuation are not an
enforced lifecycle. [E1, E2]

### Real market provider and licensing — BLOCKED

`SourceProvider` is replaceable, but `SourceObservation`, `SourceBatch` and
`assemble_source_batch` support only `synthetic_test`. `as_observed` explicitly
sets every candle provisional. A Yahoo transport also exists in
`YahooDailyOHLCVProvider`, using `download_historical_data`, but by default has
no finality proof; it is not an approved real-world integration. Other legacy
research providers are not evidence of a licensed, verified six-stock daily
execution feed. No accepted provider contract or usage/retention/redistribution
authorization was established by this audit. Existing assessment documents also
record unresolved rights. This is an evidence gap, not a legal conclusion about
any vendor's current terms. [E3, E4, E18]

### Real calendars, holidays, DST and early closures — BLOCKED

The mechanism is implemented: `CalendarArtifact.complete_artifact` requires
explicit open/closed coverage and exchange mapping; `ExchangeSession` uses
America/New_York dates; divergent exchange schedules refuse. Synthetic tests
exercise both DST transitions and an early close. Those tests do not validate
an official current calendar, emergency closure feed or current listings.
No accepted real artifacts/pins ship with the default trust root. [E2, E3]

### Finality, freshness and fail-closed publication — CONDITIONAL

`verify_candle_finality` binds each candle hash, exchange, official close,
provider-final/completed flags and causal issuance/fetch/verification times.
Elapsed time and a publication delay are necessary but insufficient. Exact
external pins are required. Missing coverage, provisional data, cross-scope
evidence and changed hashes refuse verified publication. These are meaningful
synthetic guarantees; no actual provider finality/revision service is accepted.
Legacy `DailySignalStore.publish` can store unverified research results, so only
the verified loader is an eligible launch input. A generic run's existence is
not proof of verified publication. [E2–E4]

### Provenance and deterministic replay — CONDITIONAL

Raw fixture payload hashes, dataset/source identities, immutable run identities,
canonical inputs and source/environment fingerprints are present. Revisions can
be archived as different contents; a conflicting existing run ID refuses.
Replay depends on retained inputs, trusted pins, source checkout, dependencies
and timezone database. Hashes prove correspondence with a retained trust anchor,
not truth or resistance to a privileged replacement of all evidence.
The installed production data history and environment archive are UNKNOWN. [E1–E4, E15]

### FX mathematics — READY for supplied synthetic fixtures; real FX — BLOCKED

`CanonicalFX` uses EUR per USD with explicit reciprocal provenance. `convert`
multiplies quantity before quantization and uses the original divisor for reverse
rates, Decimal precision 80 and half-even rounding at 12 decimal places.
`validate_quote` rejects future/not-yet-retrieved and stale effective timestamps.
`convert_risk_inputs` leaves EUR cash unchanged and preserves the older of stock
mark/FX effective time for freshness. The risk adapter explicitly rejects
non-synthetic FX. Quote metadata and `indicative_mid` are supplied assertions;
there is no licensed/authenticated live FX transport. Optional exact FX pins are
not an authentication service, and the strict gate does not supply a separate
FX trust root when converting requests. [E5, E7]

### Risk calculation and accounting — CONDITIONAL

The default risk numbers match the proposal. Conservative pending-order coverage,
positive quantities, oversell checks, no borrowing and adverse supplied slippage
are implemented. Final risk and cash/share accounting use the same writer
transaction, with exact current cash, holdings and pending instructions checked.
However, marks, initial order costs/stops and `RiskConfiguration` are supplied
inputs; no persisted experiment-policy hash prevents looser parameters on another
request. Standalone sizing/evaluation is advisory until the locked gate runs.
EUR 10,000 must be checked in the actual broker account, not inferred from
`RiskConfiguration.starting_capital`. [E6–E9]

### Atomic strict execution, idempotency and restart — CONDITIONAL

Under supported APIs and a trusted local process, the inspected transaction,
savepoint and audit ordering are strong. A unique successful gate row per order,
request hashes and cached exact outcomes prevent another financial fill on retry.
Failure tests exercise errors after mutations, lost commit acknowledgement and
whole-transaction abort. These are deterministic injected failures, not real
power-loss or storage-controller tests. Legacy ledgers remain unrestricted and
must never be selected for this experiment. Python private flags and direct SQL
are not a security boundary against an owner of the process/database. [E7–E9, E12]

### Reconciliation and independent safety controls — CONDITIONAL

The monitor independently reconstructs cash, cost basis, realized P&L, shares,
lifecycle and gate/control evidence. This is accounting integrity, not market
valuation or evidence of execution quality. Coordinated reconciliation and new
strict-fill preflight detect and latch critical broker findings under one writer
reservation. Kill switch, operational latch and restore fence remain distinct.
Authorized latch recovery does not clear kill/quarantine; healthy reports do not
release a hold. There is no delivered alert dispatcher or operator-response SLA.
Unwritable/corrupt storage can prevent recording a latch, while the attempted
strict fill still fails; durable activation must not be claimed in that case.
Broker-only preflight does not continuously inspect all separate workflow/source
stores. [E10–E13]

### Backup and restoration — CONDITIONAL; execution resumption — BLOCKED

SQLite online backup, WAL consistency, image hashes, independent reconciliation,
new-directory-only Windows publication, explicit restore authorization and durable
PREPARED/SEALED/PUBLISHED audit are implemented. Restored strict v3 images become
v4 inspection branches with a persistent fence before publication. There is no
quarantine-release or overwrite API. Older copies preserve historical safety
bits and remain blocked even when later live restrictions are unknown.
Backups are broker-only, not an atomic recovery set for signal/source/workflow
stores. Publication is Windows-only; physical durability and off-device recovery
are unproven. Restoring a backup cannot presently resume the experiment. [E14–E16]

### Authorization, daily operation and deployment — BLOCKED for Gate B

Workflow authorization binds exact preview/run/ledger path and records operator,
ID and time, but `execute_workflow` does not authenticate that operator using an
independent callback, signature or external identity service. Direct gated calls
do not require this workflow record at all. Restore and operational recovery have
callback hooks, whose authenticators must be supplied by the application. The
kill-switch API also trusts its local caller. [E7, E10, E14, E17]

No complete daily experiment runner, missed-window policy, scheduler, alerting
service, clock synchronization check, experiment configuration/secrets boundary
or 90-day lifecycle was found in the inspected runtime directories. A scheduler
is optional for a supervised local launch, but repeatable manual operations and
missed-session handling are mandatory. Cloud infrastructure, filesystem ACLs,
disk provisioning, secret rotation and real operator identities are UNKNOWN.
`.env.example` and `.gitignore` provide placeholders/ignore rules, not a secrets
manager. Secret values were not inspected. `main.py` is a separate live research
entry point with module-level model construction/pipeline calls, not a safe
offline paper-experiment launcher; do not run it as a rehearsal shortcut. [E17, E18]

## 4. Material launch findings

### F1 — No accepted real observation authority (critical blocker)

Supply approved licensing evidence, current authoritative calendars/listings and
provider completion/revision evidence before pinning real artifacts. A named
provider, a downloaded OHLCV row, fixture `provider_final=True` or a waited delay
is insufficient. Fail closed if the chosen provider cannot meet the evidence
contract; do not manufacture finality or weaken Sprint 1C. [E2–E4]

### F2 — Execution price and wall-clock causality are not established (critical blocker)

The gate compares supplied `signal_available_at`, `execution_at` and
`execution_price_at`; it does not load the referenced verified signal or execution
calendar. Direct requests therefore do not inherit the workflow's six-stock,
later-session and signal-side checks. The workflow is stronger, requiring a later
dated session and `price_available_at <= preview_at <= execution_at`, but allows
the supplied price for that execution timestamp to be known at preview. That is
appropriate for invented fixtures, not proof of a future executable quote.
There is no check against actual invocation time or maximum signal/authorization
age. Replaying an old coherent time context later can pass relative freshness
checks. Real forward operation needs an acquisition clock, captured observation
availability, delayed-order expiry/repricing and a documented fill convention.
Daily OHLCV does not demonstrate executable spread, volume, latency or liquidity;
zero fees/slippage remain allowed inputs. [E5, E7, E17]

### F3 — Policy and authorization are not bound at the financial boundary (critical blocker)

`ExecutionRequest.risk_policy` and freshness policies are configurable per request.
Tests themselves use changed policy limits. The evaluator atomically applies
those values; it does not guarantee the experiment's proposed values persist.
The public direct gate also lacks authenticated operator/workflow approval.
For Gate B, bind approved policy, ledger/experiment identity, instrument universe,
verified observations and authorization at every supported new-fill entry point.
Do not equate skipping the workflow with skipping the accounting gate: the latter
still runs, but the former removes important operating restrictions. [E6–E9, E17]

### F4 — Planned stops and corporate actions are not execution/accounting services

The 1% and 4% limits describe planned downside at supplied stops and costs, not
maximum realized loss. There is no standing protective-stop order execution,
gap-risk guarantee or market-hours monitoring. Preserve the existing conservative
SELL policy: the whole projected portfolio must pass limits, and held stops must
remain below current marks. A breached stop or residual over-limit holding can
therefore reject a SELL; assuming all risk-reducing exits always execute is wrong.
This needs an explicit halt/escalation policy or a separately approved design,
not a silent relaxation. [E6, E8]

Splits/dividends are recorded in candles and adjustment conventions are declared.
The broker reconstructs financial state from buys/sells and has no split-share,
dividend-cash, fractional-share or cost-basis corporate-action booking path.
Persisted USD stops also are not rebased for an action. A coherent split-adjusted
research series alone cannot reconcile raw held shares and actual execution
prices across an action. Require a verified coherent basis and action-accounting
design, or halt affected operation and explicitly censor unsupported performance.
Ordinary reconciliation cannot detect a missing external dividend it never knew
about. [E1, E4, E7, E9, E11]

### F5 — Ninety-day capacity and operating continuity are unverified

Strict admission limits are 64 MiB, 10,000 rows and 1,000 gate attempts. History
growth includes full before/after order state in each outcome; serialized evidence
can grow faster than the number of fills. The timing fixture measures 0/8/24
historical fills without a timing pass threshold; it is not a 90-day soak/capacity
proof. Repeated rejections, full snapshots and sidecar growth matter. Account for
disk headroom, retained environments, backup/partial directories and operator
absence. There is no automatic compaction/retention or demonstrated real-time SLA.
Admission refusal is a safe halt, not evidence the full experiment can finish.
[E7, E10, E12, E14]

## 5. Proposed limits: enforcement boundary

- **20% per stock, 80% invested, 20% cash:** `_evaluate` checks the conservative
  projected portfolio using supplied marks and the minimum of current/projected
  equity. Checks occur again inside `execute_locked`; standalone previews are
  advisory. Numbers are defaults, not immutable ledger rules. [E6–E8]
- **1% per-position and 4% aggregate planned stop risk:** includes supplied entry,
  stop, fee and slippage assumptions, held metadata and pending BUY risk. Pending
  SELL proceeds do not finance BUYs or release capacity. This is not guaranteed
  stop execution or realized-loss protection. [E6–E8]
- **No leverage/shorting:** risk rejects negative cash and oversells; accounting
  independently checks cash/shares under the writer lock. This protects whole-
  share internal accounting, not external derivatives, borrowing or price truth.
  [E6, E8, E9]
- **Sizing:** `size_pretrade_buy` searches for the largest approved whole-share
  quantity up to a supplied cap; workflow orders are manually staged and do not
  automatically use it. Binding the selected sizing/stop policy remains an
  experiment setup obligation. [E6, E17]
- **Continuous limits:** these are admission checks at fills, not continuous
  portfolio surveillance. Mark/FX movements can breach limits between actions.
  No independent continuous mark monitor or automatic rebalancing was found.
  No strategy or risk-limit change is proposed by this audit. [E6, E10, E11]

## 6. Launch gates and operating restrictions

### Gate A — CONDITIONAL GO for a supervised synthetic rehearsal

Before a future authorized rehearsal, the operator must:

1. Create a dedicated local Windows strict ledger with EUR 10,000; verify strict
   mode, ledger identity and all three safety controls. Do not use legacy ledgers,
   restored copies or the live-research `main.py` entry point.
2. Freeze synthetic six-stock data, at least 200 warm-up sessions and full
   explicit calendar coverage for the rehearsal window. Keep fixture trust roots
   separate from the empty production root. Select one strategy variant and a
   fixed risk/freshness/fees/slippage/stop policy before observing results.
3. Use one trusted local operator and explicit preview/authorization/execution
   through the workflow. Permit no ad hoc direct-gate calls, direct SQL edits or
   new attempt IDs to work around an error. These are procedural restrictions
   until F3 is addressed, not software-authenticated guarantees.
4. Make each simulated time advance explicit and chronological; record missed
   decisions and rejected orders. Do not retrospectively choose favorable prices,
   retune inputs after results or describe synthetic P&L as investment evidence.
5. Reconcile and review findings after each explicit session/action batch, retain
   manifests and audit sidecars, monitor growth below admission budgets, and stop
   on corruption, ambiguous commits, missing evidence or budget failure. Recover
   an ambiguous result by its original identity; never issue a replacement fill.
6. Treat restored copies as permanently inspection-only. A failed rehearsal or
   recovery can end the exercise; successful automatic continuation is not a
   promised property. Preserve evidence and seek review instead of releasing a
   restore fence, repairing financial history or weakening SELL policy.

The named tests support the individual controls, not completion of a full
90-calendar-day exercise. Manual scheduling is acceptable in this restricted
mode; no unattended execution or new scheduler is authorized here. [E1–E17]

### Gate B — NO-GO for observed-market forward paper trading

Do not start the proposed forward experiment using scraped/delayed rows or
synthetic FX labeled as real. Entry requires F1–F5 remediation, an authenticated
and policy-bound real-input path, verified price/action conventions, a repeatable
local operations procedure, retained evidence and a new independent launch
review. The 90 calendar days start at an approved launch instant; exact exchange
session count depends on accepted calendar coverage, not a weekdays formula.
Post-close finality delay must remain compatible with a later real execution
session. Local operation is the initial target; cloud deployment is a separate
gate. No claim about likely profitability or executable market prices follows
from Gate A or from backtest/release-gate tests. [E2–E7, E17–E19]

## 7. Independent failure-scenario assessment

### 1. Late market data or post-publication revision

Expected: missing/latest-session coverage or unavailable/provisional evidence
rejects the complete verified batch. A changed archived payload/hash conflicts
with its identity; a new revision is a new artifact, not an overwrite. Existing
published evidence remains historical and does not prove the vendor never
corrected it. Tests: `test_failed_batch_publishes_nothing` [E1],
`test_provider_evidence_must_be_sufficient_even_when_pinned` [E2],
`test_archive_tampering_and_revisions` [E3]. Unresolved: real revision notification,
quarantine of decisions affected by corrections, late-session operating policy.

### 2. US session closes early

Expected: supplied authoritative close governs completion/delay, and workflow
execution must be inside its pinned later session. Missing or divergent coverage
refuses. Tests: `test_early_close_and_both_dst_transitions` and
`test_divergent_exchanges_fail_instead_of_silently_intersecting` [E2]. Unresolved:
an actually accepted calendar and exceptional-closure updates; synthetic dates
are not official exchange claims. Direct gated calls do not check sessions. [E7]

### 3. FX is stale or unavailable

Expected: missing/malformed required FX fails validation; future/stale quotes
reject without financial mutation. The older stock/FX time prevents a fresh FX
conversion from refreshing old marks. Tests: `test_future_stale_and_unavailable_quote`,
`test_fx_adapter_does_not_refresh_stale_portfolio_state` [E5] and
`test_fx_and_timing_integrity` [E8]. Unresolved: actual approved FX source,
freshness policy binding, market spread and downtime/repricing rules.

### 4. Signal exists but execution is delayed

Expected: changed portfolio state rejects stale expected-state requests; supplied
FX/marks are checked against supplied execution time. Workflow requires later
session, signal match and causal authorization order. Tests:
`test_preliminary_approval_cannot_authorize_changed_state` [E8] and
`test_invalid_execution_inputs_are_rejected_without_fills` [E17]. Unresolved:
no comparison with actual current time, authorization expiry or maximum signal
age. A delayed invocation of coherent old inputs is not known to be timely. [F2]

### 5. Two orders compete for insufficient EUR cash

Expected: SQLite serializes writers; exact holdings/pending assumptions and cash
are checked under the lock. Pending BUYs reserve conservative risk; they are not
broker cash reservations. A contender rejects stale state/risk/cash rather than
spending twice. Tests: `test_concurrent_competitors_reject_old_state_and_never_overallocate`,
`test_pending_orders_cannot_collectively_bypass_risk` [E8] and
`test_concurrent_orders_cannot_spend_conservatively_reserved_limited_cash` [E12].
Unresolved: marks/policies remain supplied, and timeouts require explicit retry
handling rather than assuming either contender succeeded.

### 6. Crash during a simulated fill

Expected: fill, financial state and gate audit commit together, or roll back.
An ordinary rejection rolls back the savepoint then commits equal-state evidence.
If rollback/audit cannot be confirmed, propagate the error; do not invent durable
rejection. Resolve lost acknowledgement using the original attempt ID. Workflow
intent and broker outcome are separate commits, with an explicit recovery gap.
Tests: `test_evidence_failure_rolls_back_entire_success_and_recovers` [E8],
`test_lost_commit_acknowledgement_preserves_original_error_and_exact_retry`,
`test_whole_transaction_abort_does_not_invent_rejection_audit` [E12] and
`test_restart_recovers_gap_after_broker_commit` [E17]. Unresolved: physical crash,
disk/controller behavior and cross-file atomicity were not demonstrated.

### 7. Reconciliation detects a critical discrepancy

Expected: `reconcile_and_latch` and strict preflight hold one writer reservation
through inspection and activation; another strict fill cannot interleave in
that interval. Activation becomes durable only when the owning COMMIT succeeds.
Standalone read-only `monitor` followed by separate `activate_operational_block`
still has an observation/action interval and may be stale; do not call it an
atomic detector. Tests: `test_critical_check_holds_writer_until_latch_commit_with_waiting_fill`,
`test_failed_preflight_latch_audit_refuses_every_retry_without_false_durability`
[E12] and `test_detection_activation_race_and_concurrent_fill` [E13]. Unresolved:
no background detection/alerts; activity outside broker scope needs explicit
sidecar monitoring and escalation. A healthy report never clears any hold.

### 8. Database becomes corrupt

Expected: constructor/reconstruction, read-only monitor, integrity preflight or
backup verification refuses/returns critical rather than repairing data. If
the database is unreadable/unwritable, a durable latch/audit cannot be promised;
the strict fill must still refuse. Tests:
`test_missing_or_unreadable_database_is_critical_without_creation` [E13],
`test_restart_detects_inconsistent_cash_without_repairing_it` [E9],
`test_rehashed_corrupt_sqlite_refused` [E15]. Unresolved: storage faults and
off-device restore availability; no executable disaster-recovery release exists.

### 9. Backup predates current safety-control state

Expected: never overwrite the live branch. New restore keeps historical switch
bits but adds an independent permanent quarantine. Unknown later restrictions
therefore cannot result in a new strict fill on that copy. Tests:
`test_old_backup_cannot_reactivate_later_kill_switch` and
`test_kill_and_operational_latch_preserved_independently_of_fence` [E15].
Unresolved: identifying the latest complete cross-store recovery point and
resuming execution; historical consistency is not evidence of latest state.

### 10. Computer is offline during a decision window

Expected: no scheduler means no implicit catch-up or automatic execution. Source
errors propagate; a local strict ledger may remain readable and synthetic work
possible, but no fresh real observation can be assumed. Tests demonstrate provider
failure preserving the previous run and post-fetch decision-clock sampling [E1].
There is no inspected offline-window escalation or actual uptime test. Required
operating rule: record the miss, obtain fresh accepted data and a new explicit
preview/authorization later, or skip; never backdate availability or fills. [F2]

### 11. A restored ledger is accidentally selected for execution

Expected: schema-v4 fence survives restart, normal controls cannot release it,
manual strict fills refuse, and direct gated/orchestrated requests reject under
the financial writer lock. Cached filled outcomes remain reads. Tests:
`test_populated_backup_restore_preserves_history_and_restart_fence`,
`test_orchestration_cannot_bypass_restore_fence`,
`test_first_fill_racing_publication_observes_committed_fence` and
`test_cached_completed_attempt_cannot_duplicate_a_fill_after_restore` [E15].
There is no published unfenced interval in the supported staging protocol.
Unresolved: a privileged process can alter files/private flags; no hostile-owner
security guarantee exists. A rejection audit legitimately changes the restored
image and invalidates its original publication byte seal; retry must refuse
changed images instead of resealing them silently. [E14–E16]

### 12. Provider changes format or licensing terms

Expected for fixtures: structural/schema/hash/coverage errors fail the batch,
and the `SourceProvider` interface permits replacing an adapter without changing
the strategy. Tests: `test_bad_source_rejected` and
`test_provider_failure_cannot_persist_partial_batch` [E3]. No runtime component
detects a contractual change, or a semantic unit/adjustment change that still
fits the schema. Required: vendor change review, versioned adapter contract and
license reapproval before new real observations are admitted. Provider rights
and service availability remain unverified externally in this audit. [F1, F4]

## 8. Prioritized future remediation roadmap

These are proposed sprints, not authorized implementation. Each requires its own
scope/architecture approval and must retain existing strict-ledger, latch,
kill-switch, rollback and restore-fence guarantees. Do not enable production by
loosening validators to make a test or a provider response pass.

### 1M — Licensed observations, calendars and finality evidence

- Objective: choose one usable real observation source and an independently
  reviewed official calendar/listing source; document usage, retention,
  redistribution and cloud rights, finality/revision semantics and failure policy.
- Critical risks/dependencies: F1; depends on vendor evidence and operator/legal
  review, not on inferred package licensing. If sufficient finality evidence is
  unavailable, remain NO-GO and choose a different source/design for review.
- Acceptance: an approved real adapter preserves raw bytes, timestamps, currency,
  adjustment conventions and versioned identity; all six tickers and every
  required session have exact accepted calendar/evidence coverage; separately
  reviewed real pins are admitted only after evidence approval. No fixture pins
  enter production. Corrections invalidate affected downstream use explicitly.
- Expected tests: recorded-response normalization, incomplete/late/revised bars,
  no-finality despite elapsed time, wrong exchange, exceptional/early closures,
  both DST transitions, bad semantic units, revisions and fail-closed pin changes.
- External involvement: vendor/licensing and official-calendar research required;
  any acquisition/service access needs explicit authorization. Core regression
  should use offline recorded fixtures. No trading or deployment is required.

### 1N — Real FX and causally evidenced simulated fill contract

- Objective: admit separately approved FX/stock marks and an explicit conservative
  simulated execution convention without inventing executable prices.
- Critical risks/dependencies: F2 and FX blocker; depends on 1M evidence and an
  approved timing/pricing architecture. Define actual decision/receipt clocks,
  allowed latency, spread/cost assumptions, signal expiry and repricing.
- Acceptance: real-scope risk inputs have approved independently bound FX and
  equity evidence; no future observation is available at preview; delayed calls
  expire/reprice explicitly. Preserve EUR/USD units and existing Decimal behavior;
  do not relabel synthetic fixtures. Clearly distinguish simulation from a market
  execution claim. Unavailable FX/data stops new fills.
- Expected tests: inverse rates, rounding boundaries, stale/unavailable FX, future
  or backdated prices, delayed authorization/invocation, clock skew, holiday/early
  close execution and cost-inclusive cash sufficiency.
- External involvement: approved FX/price services and rights review; recorded
  offline tests first. No broker orders or cloud deployment required.

### 1O — Experiment authority at every financial entry point

- Objective: persist the approved EUR 10,000 experiment identity, six instruments,
  selected variant, risk limits and freshness/fill policies, and independently
  authenticate an operator's exact permitted action.
- Critical risks/dependencies: F3; depends on 1N request/evidence design. Review
  migration and authorization architecture before changing strict execution.
- Acceptance: every new supported strict fill enforces approved policy, evidence,
  authorization scope, expiry and ledger identity under the same transaction;
  direct calls cannot omit workflow-equivalent restrictions or relax the proposed
  limits. Legacy behavior and all three independent holds remain intact. Existing
  conservative SELL policy stays unchanged unless separately approved.
- Expected tests: forged/absent approval, unauthorized direct gate, changed limits,
  wrong instrument/variant/ledger, revocation/expiry, restarts and concurrent policy
  or control changes, with atomic rollback and durable rejection evidence.
- External involvement: local OS/authenticator integration may suffice; identity
  service use is optional and separately approved. No market requests are needed
  for deterministic acceptance tests; no scheduler or deployment is required.

### 1P — Corporate-action and experiment accounting policy

- Objective: establish coherent research/execution/held-share adjustment bases,
  dividend treatment, FX valuation and terminal reporting for the experiment.
- Critical risks/dependencies: F4; depends on 1M action evidence and 1N pricing.
  Decide supported action booking versus an explicit action-triggered halt and
  censored experiment. Any financial-state mutation API needs architectural review.
- Acceptance: no split is applied twice or ignored for held shares/stops; no
  dividend return or realized-loss bound is fabricated. Missing action evidence
  halts affected operation. Specify below-stop/over-limit SELL escalation without
  silently changing policy. Define end-of-90-day valuation versus liquidation,
  and report missed/rejected trades and unsupported intervals.
- Expected tests: split before/after acquisition, partial sales, dividend dates,
  changing FX, fractional entitlements, revised/missing actions, gap through stop,
  rejected conservative SELL and terminal valuation with missing marks.
- External involvement: corporate-action rights/evidence from approved sources;
  deterministic action fixtures for tests. No real orders or deployment required.

### 1Q — Supervised local operating qualification and launch review

- Objective: a reproducible operator-controlled daily procedure and measured
  90-day-equivalent workload, with restart, escalation and disaster drills.
- Critical risks/dependencies: F5 and deployment/operations gaps; depends on
  accepted 1M–1P contracts. Keep cloud and unattended scheduling out of the initial
  local launch unless separately approved.
- Acceptance: reviewed run configuration and environment archives, actual clock
  checks, protected database/secret locations and ACLs, missed-window/holiday
  rules, alert owner/escalation, disk/retention budgets, separate source/signal/
  workflow/broker recovery inventory and verified off-device backup procedure.
  Measure growth/latency through expected fills plus rejection bursts below
  admission limits. State the remaining quarantine-only recovery restriction
  explicitly; any execution release needs a separate approved design. Re-audit
  Gate B before starting its 90-day clock.
- Expected tests/drills: complete deterministic 90-calendar-day schedule with
  warm-up, DST/closures, capacity and disk-full faults, missed windows, clock skew,
  callback/storage failures, lost acknowledgements, restart and selection of a
  restored copy. Physical/off-device disaster drills require separate evidence;
  unit tests cannot certify them.
- External involvement: initial deterministic qualification is offline. Any
  observed-market dry run, external alert transport/off-device destination or
  deployment requires explicit authorization. Optional cloud/Linux work follows
  a separate platform assessment because current bundle publication is Windows-only.

## 9. Residual risks and acceptance boundaries

Even after remediation, simulation prices, assumed slippage, spreads and stop
levels cannot guarantee executable fills or cap realized losses. Forward outcomes
can differ from historical results, and six stocks over 90 calendar days provide
limited evidence of investment edge. Pre-register variant, metrics, missing-data
treatment and evaluation dates before observing results. [E1, E6, E19]

The monitor's accounting baseline is not an independently authenticated deposit;
it cannot discover a jointly fabricated ledger/history or external omitted cash
events. Hashes are not signatures. Local privileged users can modify SQLite and
Python internals. Operator authentication, file ownership and external evidence
must supply the remaining trust boundary. [E9–E11, E14]

SQLite writer serialization is local transactional evidence, not a claim about
network filesystems, hostile owners, storage firmware or multi-host deployment.
Backup callback/time/size limits are admission checks, not a hard I/O deadline.
Broker-only backups allow narrow replay/scope warnings and require independently
retained manifest hashes; they are not automatically complete workflow recovery
points. No automatic release, financial repair or failover is present. [E12–E16]

The independent next decision is approval of 1M's evidence-onboarding scope.
This audit ends here; no roadmap implementation or launch is authorized by it.

## 10. Exact repository evidence index

Paths are relative to this report. Function and test names identify the inspected
contracts; line links are entry anchors rather than claims that a whole control
is contained on one line.

- **E1 — Daily inputs and signal replay:**
  [models/daily_signals.py](../models/daily_signals.py), `SessionSchedule.completed_sessions`,
  `DailyStrategyConfiguration`, `DailySignalInputs.validate_completed_inputs`;
  [tools/daily_signal_pipeline.py:51](../tools/daily_signal_pipeline.py#L51),
  `replay_daily_signals`, `DailySignalStore.publish/load`, `ingest_daily_signals`.
  [tests/test_daily_signal_pipeline.py](../tests/test_daily_signal_pipeline.py):
  `test_six_tickers_both_variants_usd_contract_and_early_close`,
  `test_freeze_json_replay_and_restart_idempotency`,
  `test_ingestion_samples_decision_clock_after_fetch`,
  `test_failed_batch_publishes_nothing`, `test_provider_error_keeps_previous_run`,
  `test_future_fetched_evidence_cannot_be_replayed_into_the_past`,
  `test_strategy_parameters_cannot_be_overridden`.
- **E2 — Market authority and finality:**
  [tools/market_verification.py:58](../tools/market_verification.py#L58),
  `CalendarArtifact`, `TrustRegistry.require`, `verify_candle_finality`;
  [tools/verified_daily_pipeline.py:57](../tools/verified_daily_pipeline.py#L57),
  `freeze_verified_daily_inputs`, `replay_verified_daily_signals`,
  `publish_verified_daily_signals`, `load_verified_daily_signals`.
  [tests/test_market_verification.py](../tests/test_market_verification.py):
  `test_empty_default_real_trust_and_cross_scope_rejection`,
  `test_early_close_and_both_dst_transitions`,
  `test_divergent_exchanges_fail_instead_of_silently_intersecting`,
  `test_provider_evidence_must_be_sufficient_even_when_pinned`,
  `test_provisional_candle_is_not_promoted_by_a_pinned_proof`,
  `test_unverified_legacy_run_is_not_silently_upgraded`,
  `test_all_or_nothing_verified_publication`.
- **E3 — Synthetic provider/provenance:**
  [providers/offline_market_data.py](../providers/offline_market_data.py),
  `SourceProvider`, `SourceObservation.as_observed`, `SourceBatch.complete_batch`,
  `assemble_source_batch`, `SourceSnapshotStore.save/load`.
  [tests/test_offline_market_data.py](../tests/test_offline_market_data.py):
  `test_roundtrip_preserves_source_and_provisional_state`,
  `test_bad_source_rejected`, `test_provider_failure_cannot_persist_partial_batch`,
  `test_pinned_evidence_never_promotes_offline_candles`,
  `test_archive_tampering_and_revisions`.
- **E4 — Existing network-capable adapter, not accepted authority:**
  [providers/daily_ohlcv_provider.py](../providers/daily_ohlcv_provider.py),
  `YahooDailyOHLCVProvider.fetch_daily`;
  [tools/historical_data.py](../tools/historical_data.py), `download_historical_data`
  (`yf.download(auto_adjust=False, actions=True)`), `validate_ohlcv_data`;
  [tools/historical_snapshot.py](../tools/historical_snapshot.py), `Candle`,
  `TickerSnapshot.valid_dates_and_basis`.
  Tests: `test_yahoo_adapter_reuses_existing_loader_without_network` [E1];
  `test_yahoo_like_delayed_response_cannot_replace_evidence` [E2].
- **E5 — FX:** [tools/fx_conversion.py:45](../tools/fx_conversion.py#L45),
  `FXQuote`, `CanonicalFX`, `FXPolicy`, `FXTrustRegistry`, `validate_quote`,
  `convert`, `convert_risk_inputs`.
  [tests/test_fx_conversion.py](../tests/test_fx_conversion.py):
  `test_direction_units_and_costs`, `test_explicit_reciprocal_preserves_original_evidence`,
  `test_reciprocal_uses_original_divisor_without_intermediate_rate_rounding`,
  `test_half_even_rounding_boundaries`, `test_future_stale_and_unavailable_quote`,
  `test_unapproved_source_is_rejected_when_required`,
  `test_risk_boundary_rejects_unverified_fx_and_binary_floats`,
  `test_fx_adapter_does_not_refresh_stale_portfolio_state`.
- **E6 — Risk and sizing:** [tools/pretrade_risk.py:44](../tools/pretrade_risk.py#L44),
  `RiskConfiguration`, `evaluate_pretrade`, `_evaluate`, `size_pretrade_buy`.
  [tests/test_pretrade_risk.py](../tests/test_pretrade_risk.py):
  `test_defaults_and_exact_position_boundary`, `test_mark_to_market_not_entry_cost`,
  `test_total_exposure_and_cash_reserve_separately`,
  `test_aggregate_and_per_position_stop_risk`,
  `test_sell_and_oversell_and_pending_share_reservation`,
  `test_pending_sells_do_not_fund_buys_or_release_capacity`,
  `test_position_sizing_with_explicit_stop_and_costs`.
- **E7 — Actual strict-fill gate:**
  [tools/gated_execution.py:159](../tools/gated_execution.py#L159), `execute_locked`,
  `ExecutionRequest`, `read_state_locked`, `load_attempt_locked`.
  [providers/paper_broker.py:208](../providers/paper_broker.py#L208),
  `execute_gated`, `_transaction`, `_simulate_fill_locked`.
  The request carries policies/times/prices, not an authenticated workflow approval.
- **E8 — Gate tests:** [tests/test_gated_execution.py](../tests/test_gated_execution.py):
  `test_strict_persists_and_cannot_downgrade_or_manually_fill`,
  `test_legacy_remains_unrestricted_and_not_silently_upgraded`,
  `test_success_sell_and_unchanged_conservative_sell_policy`,
  `test_risk_limits_are_durable_rejections`, `test_fx_and_timing_integrity`,
  `test_preliminary_approval_cannot_authorize_changed_state`,
  `test_pending_coverage_and_frozen_assumptions`,
  `test_evidence_failure_rolls_back_entire_success_and_recovers`,
  `test_concurrent_identical_requests_execute_once`,
  `test_concurrent_competitors_reject_old_state_and_never_overallocate`,
  `test_pending_orders_cannot_collectively_bypass_risk`.
- **E9 — Accounting and local API boundary:**
  [providers/paper_broker.py:103](../providers/paper_broker.py#L103), `__init__`,
  `_create_strict_schema`, `create_order`, `set_kill_switch`, `reconcile`,
  `simulate_fill`, `_simulate_fill_locked`.
  [tests/test_paper_broker.py](../tests/test_paper_broker.py):
  `test_default_capital_and_no_automatic_execution`,
  `test_buy_and_sell_include_explicit_costs`,
  `test_order_and_fill_idempotency_and_conflict_detection`,
  `test_restart_reconstructs_state_orders_fills_and_audit`,
  `test_transaction_rollback_after_cash_and_position_update`,
  `test_restart_detects_inconsistent_cash_without_repairing_it`.
- **E10 — Operational activation and recovery:**
  [tools/operational_controls.py:200](../tools/operational_controls.py#L200),
  `inspect_and_latch_locked`, `reconcile_and_latch`, `strict_preflight_locked`,
  `activate_operational_block`, `release_operational_block`,
  `_check_preflight_budget` and `PREFLIGHT_MAX_*` constants.
- **E11 — Independent monitor:**
  [tools/operational_monitoring.py:77](../tools/operational_monitoring.py#L77),
  `capture_connection`, `capture_database`, `reconcile_snapshot`, `_check_gates`,
  `_check_controls`, `_check_workflow`, `monitor`, `replay_report`, `human_report`.
  Reconstruction operates on sequenced buy/sell evidence and supplied opening
  policy; it is not a price feed or corporate-action accounting engine.
- **E12 — Failure, concurrency and overhead tests:**
  [tests/test_operational_safety_hardening.py](../tests/test_operational_safety_hardening.py):
  `test_preflight_latches_critical_before_new_fill_and_preserves_rejection_contract`,
  `test_lost_commit_acknowledgement_preserves_original_error_and_exact_retry`,
  `test_whole_transaction_abort_does_not_invent_rejection_audit`,
  `test_failed_preflight_latch_audit_refuses_every_retry_without_false_durability`,
  `test_recovery_clear_before_audit_failure_rolls_back_latch_and_kill`,
  `test_critical_check_holds_writer_until_latch_commit_with_waiting_fill`,
  `test_fill_during_recovery_waits_then_rejects_stale_authorization`,
  `test_private_accounting_helper_cannot_skip_integrity_preflight`,
  `test_concurrent_orders_cannot_spend_conservatively_reserved_limited_cash`,
  `test_preflight_work_budget_refuses_fill_without_claiming_durable_latch`,
  `test_preflight_cost_profile_on_fixed_synthetic_histories`.
- **E13 — Monitoring/control tests:**
  [tests/test_operational_monitoring.py](../tests/test_operational_monitoring.py):
  `test_healthy_buy_partial_sell_and_independent_cost_rounding`,
  `test_independent_financial_and_authority_mismatches`,
  `test_explicit_authorized_recovery_and_independent_kill`,
  `test_detection_activation_race_and_concurrent_fill`,
  `test_missing_or_unreadable_database_is_critical_without_creation`,
  `test_workflow_commit_gap_is_warning_and_monitor_never_resumes_it`,
  `test_all_strict_fill_paths_check_persisted_latch`.
- **E14 — Backup/restore protocol:**
  [tools/backup_recovery.py:73](../tools/backup_recovery.py#L73), `_publish`,
  `_copy_online`, `_inspect`, `verify_bundle`, `create_backup`, `_journal_event`,
  `_sealed_hash`, `restore_backup`; `MAX_BYTES`, `MAX_STEPS`, `MAX_SECONDS`,
  and narrow `WARNINGS` allowlist.
- **E15 — Recovery tests:** [tests/test_backup_recovery.py](../tests/test_backup_recovery.py):
  `test_populated_backup_restore_preserves_history_and_restart_fence`,
  `test_independent_financial_schema_and_audit_checks`,
  `test_post_publication_audit_failure_retry_never_overwrites`,
  `test_existing_destination_preserved`,
  `test_old_backup_cannot_reactivate_later_kill_switch`,
  `test_kill_and_operational_latch_preserved_independently_of_fence`,
  `test_cached_completed_attempt_cannot_duplicate_a_fill_after_restore`,
  `test_first_fill_racing_publication_observes_committed_fence`,
  `test_rehashed_corrupt_sqlite_refused`,
  `test_unsupported_publication_platform_fails_closed`,
  `test_orchestration_cannot_bypass_restore_fence`,
  `test_wal_writer_commits_between_online_backup_steps`,
  `test_recovery_racing_strict_fill_cannot_release_restore_fence`,
  `test_backup_change_between_verification_and_copy_refuses_restore`.
- **E16 — Persistent fence:**
  [tools/restore_quarantine.py:6](../tools/restore_quarantine.py#L6),
  `validate_fence`, `read_restore_fence`, `install_restore_fence`;
  constructor/schema recognition and accounting guard [E9], locked gate [E7].
- **E17 — Workflow:**
  [tools/paper_orchestration.py:168](../tools/paper_orchestration.py#L168),
  `WorkflowInput.unique`, `_request`, `_preview`, `Authorization`,
  `WorkflowStore._immutable/_step`, `preview_workflow`, `execute_workflow`.
  [tests/test_paper_orchestration.py](../tests/test_paper_orchestration.py):
  `test_preview_is_persisted_and_never_executes`,
  `test_authorization_exact_identity_buy_replay_and_report`,
  `test_invalid_execution_inputs_are_rejected_without_fills`,
  `test_missing_fx_synthetic_trust_and_strict_separation`,
  `test_sequence_can_fill_two_orders_without_adopting_external_state`,
  `test_partial_completion_and_durable_gate_rejection`,
  `test_restart_recovers_gap_after_broker_commit`,
  `test_authorization_cannot_be_reused_on_identical_other_ledger`.
- **E18 — Operational evidence/absence scope:** inspected runtime inventory under
  `tools/`, `providers/`, `workflows/`, `config/`; [main.py](../main.py),
  [.env.example](../.env.example), [.gitignore](../.gitignore),
  [pyproject.toml](../pyproject.toml), README and available scripts by filename.
  Searched inspected runtime for scheduler/cron/alert/NTP/clock-sync integration.
  No complete experiment service was found; external machine/account/cloud state
  remains UNKNOWN. Supporting prior gap records, not independent vendor approval:
  [market_data_sprint_1d_assessment.md](market_data_sprint_1d_assessment.md),
  [offline_market_data.md](offline_market_data.md),
  [fx_conversion.md](fx_conversion.md),
  [backup_disaster_recovery.md](backup_disaster_recovery.md).
- **E19 — Historical research boundary:**
  [tools/release_gate.py](../tools/release_gate.py), `check_portfolio_release_gate`;
  [tests/test_release_gate.py](../tests/test_release_gate.py),
  `test_release_gate_deterministic_replay_and_accounting`,
  `test_real_signal_regime_and_exit_prefixes_are_causal`,
  `test_portfolio_future_suffix_does_not_change_prior_execution`.
  These concern historical determinism/causality, not forward profitability or
  authenticated real-market operation.
