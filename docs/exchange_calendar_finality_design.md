# Sprint 1N — Exchange-calendar and candle-finality evidence design

Date: 2026-11-09 (Europe/Dublin). Inspected baseline: `main`, `b70272d`.
Supplied regression baseline: 922 passing tests; not rerun for this design.

## Executive recommendation

Build an **offline evidence archive and review compiler** around the existing
Sprint 1C contracts. Keep scheduled exchange hours, exceptional-event notices,
provider completion assertions and independent acquisition receipts as distinct
evidence. Compile exact, externally reviewed calendar/provider artifacts only
when all required links and timestamps are supported.

Preserve Sprint 1M observations permanently as **PROVISIONAL**. Eventual promotion
must create a separately identified, evidence-backed observation projection and
eligibility receipt; it must never update an archived status, alter original
bytes or make `ProvisionalDailyProvider` return final candles.

**Gate B remains NO-GO.** No authoritative calendar, provider completion receipt,
license, real trust pin or actual promotion is established here. A stable hash,
an unchanged response, a scheduled close that has passed or an arbitrary overnight
delay is insufficient finality evidence.

Request approval first for a narrow **offline, synthetic-evidence implementation**:
evidence models/store, deterministic calendar compilation, conflict review and
promotion-candidate evaluation. Real evidence acquisition, license acceptance,
production pin administration and actual real publication require later explicit
approval. No broker, risk, execution or scheduler work belongs in this scope.

## 1. Audit basis and evidence status

This phase inspects code and selected test bodies, not operational ledgers or
provider systems. No test command, import with execution side effects, live
provider request, calendar download, dependency change or order was performed.
Only this new document is created. No existing runtime, tests, configuration,
documentation or trust settings are changed; no commit or push is made.

The source comparison below uses the locally retained Sprint 1M research in
[market_data_onboarding_design.md](market_data_onboarding_design.md), which
records public-source checks dated 2026-11-09. **Those sources are not fetched or
revalidated in Sprint 1N.** Links are future verification targets, not newly
downloaded evidence. Account-specific rights, current product terms, notice-feed
coverage, current listings and actual provider behavior remain UNVERIFIED.
This satisfies the no-download constraint without inventing current evidence.

Protected pre-existing modification: `scripts/sec_match_recon.py`, observed
SHA-256 `7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`.
It is excluded from the audit's edits and remains untouched.

### Implemented controls

- [market_verification.py](../tools/market_verification.py):
  `CalendarArtifact.complete_artifact` requires all six listings and complete
  open/closed classification of each covered civil date per represented exchange.
  Every session/closure uses the artifact's source/version. `ExchangeSession`
  validates the America/New_York date. `as_daily_schedule` refuses divergent
  exchange schedules instead of intersecting or filling them.
- [daily_signals.py](../models/daily_signals.py):
  `SessionSchedule.completed_sessions` checks aware decision time, coverage and
  calendar availability. `DailySignalInputs.validate_completed_inputs` requires
  at least 200 completed sessions, exact all-six/date coverage, USD, declared
  split-adjusted prices/volume and already-final, causally available observations.
- `TrustRegistry.require` defaults to an empty real root and compares externally
  supplied exact-content pins. It checks declarations and identities; it does not
  authenticate a reviewer or prove the source of downloaded bytes.
- `verify_candle_finality` binds every candle, including warm-up candles, to its
  exchange, date, exact normalized hash, official close, evidence ID and true
  provider-final/completed-session flags. Time checks supplement those assertions;
  they never replace them.
- [verified_daily_pipeline.py](../tools/verified_daily_pipeline.py): freeze/replay/
  publish/load APIs check registry identity, regenerated proof records and verifier/
  tzdata fingerprints. The underlying daily store atomically saves run and
  verification metadata. Calling the legacy 1B research publisher is not verified
  publication.
- [provisional_market_data.py](../providers/provisional_market_data.py):
  `ProvisionalArchive` retains exact raw BLOBs, metadata/hashes, predecessor chains,
  normalization outcomes and overlapping-window conflicts. Batch load recomputes
  raw normalization. `NormalizedObservation.as_observed` always returns
  `final=False`. `licensed_offline` and its reference are declarations, not rights
  approval or finality evidence. The supported interchange is `recorded_ohlcv_v1`,
  not a live vendor response adapter.

### Important limits found in actual code

1. Structural calendar validation does not establish that a real exchange issued
   the schedule or that a planned session actually occurred. Fixture listings
   alternate exchanges and include invented 2020 closures; they are not usable
   production reference data.
2. `Listing(ticker, exchange)` applies over the entire calendar window; it has no
   effective-date history. A listing transfer within the warm-up/experiment window
   cannot be silently represented by applying today's exchange to past sessions.
3. One open/close interval per exchange/day and the common-schedule adapter cannot
   silently encode arbitrary intraday interruptions or different XNYS/XNAS hours.
   Unsupported exceptions require a hold and separate architecture review.
4. The 1C models do not hold raw notices, individual provenance links, independent
   receipt times, licensing approvals or revocation history. They need a reviewed
   sidecar manifest, not extra fields forced into frozen v1 models.
5. 1M acquisition timestamps are supplied metadata. There is no authenticated
   external clock/recorder. Its normalization checks calendar structure and hash,
   not calendar authority. `load_batch` does not automatically resolve conflicts
   or qualify observations for promotion.
6. `archive.conflicts(id)` returns conflicts recorded with that ID as the new
   observation. A later conflicting observation can reference an older candidate
   as `previous_id`. An empty outgoing conflict list is therefore not proof that
   an old candidate has no later contradictions. Eligibility needs both directions
   and the full relevant overlapping history, with review dispositions.
7. No automatic real trust admission, revocation service, current-notice monitor
   or downstream incident-to-execution hold exists. No such control is inferred
   from a successful historical replay.

## 2. Calendar requirements for the actual experiment

The universe is exactly AAPL, JNJ, JPM, MSFT, WMT and XOM. Obtain an authoritative
listing/share-class record and effective history for **each** ticker. No current
real exchange mapping is certified by this no-download design; use neither the
synthetic alternating mapping nor an assumed legacy listing. Both XNYS and XNAS
are supported calendar identifiers; a trading venue on a print is not necessarily
the security's listing exchange.

Required coverage is the full 200-completed-session warm-up, the proposed
90-calendar-day experiment and enough accepted future session coverage to evaluate
later execution dates. Ninety calendar days is not ninety sessions. Include year
boundaries and retain each as-of calendar version used by a decision.

The calendar must represent and independently validate:

- Regular equity-session operating rules and the official holiday/observance
  schedule, including moving holidays and observed dates. Review New Year's Day,
  Martin Luther King Jr. Day, Washington's Birthday/Presidents Day, Good Friday,
  Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving and Christmas
  where applicable to the covered year. This is a verification checklist, not an
  imported date set or a rule generator certified for all historical years.
- Explicit weekends/holidays/other closed dates under accepted exchange rules;
  absence of a data bar is never a holiday classification.
- Year-specific early closes, including any officially announced Thanksgiving,
  Independence Day or Christmas-related exceptions. Do not infer them from a
  repeating weekday formula or apply options/bond/settlement hours to equities.
- Extraordinary full closures, amended closing times, reopening notices and
  exchange-specific disruptions. A single security's halt, zero eligible trades
  or a vendor outage does not establish an exchange-wide closure.
- Actual local session date and aware open/close in America/New_York, normalized
  to UTC with retained tzdata version and original local/offset fields. Use the
  accepted local clock times, not hard-coded UTC hours. Europe/Dublin clock changes
  cannot determine US session times.
- Normal EST/EDT transitions, including intervals when US and Irish DST dates
  differ. Reject ambiguous/nonexistent local times or inconsistent supplied
  offsets rather than choosing a fold silently. UTC conversion is deterministic
  only relative to retained timezone rules.
- Correct distinction between regular-session candles and vendor daily aggregates
  with wider trading/condition eligibility. A daily bar's midnight or bar-start
  timestamp is not its official closing time.

If an effective listing change or exceptional schedule is not representable
truthfully by current v1 contracts, refuse the candidate. Do not fix it by changing
the universe, moving the calendar boundary into the future, dropping warm-up
sessions or relabeling historical exchange identities.

## 3. Calendar source comparison and authority hierarchy

The following are candidate evidence channels, not approved products. URLs are
from the prior assessment or named verification targets; no channel is contacted
in this phase. Fees, retention, redistribution and access terms need explicit
source/product review before acquisition.

| Candidate source | Suitable evidence role | Limitation and admission requirement |
|---|---|---|
| [NYSE official hours/calendar](https://www.nyse.com/trade/hours-calendars) and exchange-issued notices | Primary scheduled hours, holiday/early-close rules and official amendments for its markets | A published annual schedule establishes planned operation, not a guarantee against later exceptional closure. Retain the applicable notice set, origin, effective times and retrieval coverage. Public visibility is not blanket storage/redistribution permission. |
| [Nasdaq Trader calendar](https://nasdaqtrader.com/Trader.aspx?id=Calendar) and official operational/Head Trader alerts | Primary Nasdaq schedule and explicit exceptional-event amendments | The prior 1M assessment notes that the calendar refers to alerts. A calendar page alone is insufficient if alert coverage is missing. Verify authentic notice identity, equity scope and supersession. |
| Official annual calendar PDFs, such as the [NYSE calendar reference recorded in 1M](https://www.nyse.com/publicdocs/nyse/ICE_NYSE_2026_Yearly_Trading_Calendar.pdf) | Versioned baseline that can be archived and compared offline after acquisition approval | Snapshot may become outdated. The prior assessment had only indexed PDF text, not a downloaded/visually validated original. It is not admitted evidence here. |
| Appropriately licensed consolidated calendar/reference vendor | Potential convenient delivery of multiple venues, versioned reference history and amendments | Product existence, issuer attribution, extraordinary-event coverage, update latency, correction semantics and archive rights are UNVERIFIED. Require source lineage and licensed original notices or an accepted vendor authority contract; no inference from a price-feed subscription. |
| Provider market-calendar/market-status response | Cross-check or transport of an accepted source if its provenance and license support that role | A vendor's market-closed flag does not prove a particular candle is complete or establish exceptional-closure authority. A price-provider calendar is not automatically exchange-certified. Exact endpoint/product semantics remain UNVERIFIED. |
| Software-generated exchange calendar | Draft generation, coverage/difference checking and test construction | Library version/rules are not an exchange notice or certification. Reconcile against accepted official rules/notices. No new calendar dependency is needed or approved for the first implementation. |

**Recommended hierarchy:** accepted official exchange rules/schedules plus official
amendments first; a licensed distributor can deliver that evidence if lineage and
rights are demonstrated. Libraries and independent providers detect differences,
not outvote an unresolved official conflict. Do not choose whichever source has
the later timestamp or whichever schedule makes a batch pass.

## 4. Evidence matrix and trust boundaries

| Claim | Required retained evidence | Insufficient substitute | Present status |
|---|---|---|---|
| A date is scheduled open/closed | Accepted exchange rules and dated schedule, issuer/market, coverage, original bytes and provenance | Weekday calculation or missing OHLCV | Contract implemented; no admitted real artifact |
| An exceptional closure/early close applies | Authentic notice ID/content, affected venue/date, effective time, issuance and independently recorded receipt; explicit supersession | Old annual PDF, vendor outage or one halted stock | No accepted notice corpus or monitoring coverage |
| Calendar remained suitable as of a decision | Reviewed version plus evidence of relevant notice-channel coverage through the admission cutoff; no unresolved amendments | Assuming a frozen planned schedule is current forever | Proposed control only |
| Provider completed a specific daily candle/version | Approved provider completion/release semantics and a real receipt covering the exact raw records or immutable release checksum, session and feed | HTTP 200, daily date label, last-refreshed field, stable repeated hash or elapsed time | No sufficient vendor receipt admitted |
| Release maps to existing candle hash | Original bytes, exact record locator, normalization version, action factors and canonical `input_hash(Candle)` mapping | A local checksum presented as an upstream signature | 1M raw/hash foundation exists; authority mapping missing |
| Times are causally credible | Original provider issue timestamp plus independent acquisition start/end, clock identity/uncertainty and receipt record | Backdating to close or trusting a caller's timestamp string as authentication | 1M retains supplied times; independent recorder absent |
| Adjusted values mean the same shares/prices | Reviewed price/volume/action policy, effective/as-of factors and source releases for all affected dates | Adjusted close mixed with raw OHLC, missing dividend treated as zero | Declarations validated; vendor economic basis unproven |
| Evidence is usable legally | Approved dataset/user/automation/local-storage/retention/replay rights and permitted recipients | `licensed_offline`, payment, open-source client license or public page access | Unresolved; no license is accepted here |
| Candidate is approved for publication | Independent review binding exact archive/calendar/evidence/registry hashes and qualified observation projection | Self-created pins or a nonblank review string | 1C checks supplied pins; operational admission service absent |
| A past decision can be replayed | Original bytes, calendar/provider manifests, actual old registry, environment/source/tzdata and frozen decision time | Replacing old data with today's corrected history | Existing replay mechanisms; full evidence bundle proposed |

Trust flows from source authority and independently controlled review into pinned
artifacts, never from acquisition into its own authorization. Hashes establish
integrity relative to a retained trusted reference; they do not authenticate the
issuer, license, clock or reviewer. Review credentials/signatures, OS access
control and any service integration require their own approved scope. A Python
library is not a security boundary against a privileged caller or SQLite owner.

## 5. Calendar snapshot and exceptional-event design

Propose a new append-only **evidence sidecar**, separate from the 1M database and
daily-signal store. Do not migrate their schemas in the first implementation.
The sidecar has a distinct application/schema identity and refuses incompatible,
missing or corrupted evidence rather than repairing it.

Retain three separate layers:

1. **Source documents/receipts:** exact bytes, issuer, source URL/reference,
   document/notice ID, market/product, published/effective times if genuinely
   supplied, independently captured acquisition times, content type/encoding,
   license reference and raw SHA-256. Unknown source publication time stays
   unknown; local receipt time is never substituted as an issuer claim.
2. **Calendar assertion manifest:** every covered `(exchange,date)` maps to
   applicable standing rules and specific notices, classification, interval,
   authority type and supersession chain. Keep planned schedules distinct from
   positively confirmed exceptional closures. Record channel gaps and unresolved
   contradictions explicitly. A normal planned open day need not have a fictional
   exchange-issued “completed” notice; actual candle completion is a separate
   provider assertion and must account for any known interruption.
3. **Reviewed v1 projection:** deterministically compile `CalendarArtifact`, with
   explicit sessions/closed dates for both represented venues. Use a clearly
   labeled composite source/version when combining NYSE and Nasdaq materials;
   existing v1 requires every record to match that composite identity. Per-record
   original issuers stay in the sidecar manifest. Do not imply that either
   exchange signed the locally compiled JSON.

Versioning: original documents, assertions, projections and review decisions are
separate immutable IDs/hashes. A new notice or corrected parse creates a new
version with explicit predecessor and changed dates. No latest-write-wins update.
Conflict reports must include forward and reverse links and the exact store
generation/corpus reviewed. Unsupported intraday or divergent-venue situations
remain held; do not flatten them into a normal session.

Use an acyclic integrity graph: raw source hashes → assertion/provenance manifest
hash → compiled projection hash → review receipt binding both. Do not include
the final receipt's hash inside a projection whose hash that receipt signs.
`CalendarArtifact.available_at` is the actual availability of the compiled
artifact after its inputs are available; separate review time is not backdated.

A missing notice channel, unclear supersession or source conflict prevents new
eligibility when it affects the candidate window. “No event found” is acceptable
only relative to a reviewed, sufficiently covered channel/rule set and cutoff;
it is not proof that no unobserved event exists.

## 6. Provider completion, timing and adjustment requirements

Before mapping any provider assertion into `provider_final=True`, retain and
review the actual dataset/feed documentation and applicable contractual/service
statement. Identify daily aggregation session/conditions, publication cadence,
what completion means, issue-time semantics, corrections/cancels, revision
windows, release identity and exact-record linkage. “End of day” alone does not
answer these questions. No provider is assumed to offer sufficient evidence.

An acceptable receipt might cover an immutable completed-session release/file,
provided its authority, completion meaning, checksum and exact record mapping are
demonstrated. Local normalized hashes need not be the provider's native hashing
format, but a reproducible reviewed derivation must connect them. A local evidence
ID can namespace a real batch receipt by ticker/date/hash to meet 1C's unique-ID
requirement; the manifest must distinguish local identifiers from upstream IDs.

Require proof for **every candle in the frozen all-six history**, not just the
most recent day. The hash includes OHLCV, dividend and split ratio. An old receipt
for raw historical data does not automatically attest to a newly split-adjusted
history: retain the raw records and accepted as-of action-factor derivation and
review whether the provider's completion assertion covers that representation.
If it does not, remain provisional.

Keep current signal conventions: USD, split-adjusted prices and volume,
`recorded_not_applied` dividends and `events_recorded_prices_adjusted` splits.
Do not infer missing actions, recompute a total-return series, change a stop,
book a dividend or convert FX in this evidence layer. Later action corrections
invalidate affected candidate mappings; no financial history is rewritten.

### Required chronology

For each candidate preserve source-issued time, independent evidence receipt
time, observation acquisition start/end, content availability, compiler/review
times, verification and decision time as different facts. Record clock source,
UTC offset/error bound and a monotonic acquisition duration where supported.
Local receipt logs are not automatically independent/authenticated; the recorder
and its retention/access policy must be approved. Uncertainty that prevents
establishing an ordering results in a hold, not a convenient timestamp choice.

Existing 1C constraints remain mandatory:

- `official_close <= proof.issued_at <= observation.fetched_at`;
  every proof issue time is also no later than provider-artifact availability.
- Candle content availability is after its official close and no later than its
  original retained fetch; every fetch is no later than verification.
- Calendar/evidence artifacts are available by `verified_at <= decision_at`;
  calendar coverage includes verification and decision, and schedules match.
- Verification is strictly after close and at least the explicitly configured
  publication delay later. No fixed delay is prescribed without provider evidence.

Proposed conservative admission adds independently recorded receipt of completion
evidence **by the retained acquisition end** for an initially qualified projection,
and completed independent review before verification/decision. If evidence was
issued or first recorded after the retained fetch, require a new genuinely
acquired observation after receipt with consistent bytes and a new identity.
Do not relabel an offline replay time as a fresh provider fetch. This is an
additional fail-closed admission rule, not a weakening of 1C or a current feature.

Completion means the accepted provider's specific released version qualified
under the unchanged contract, not that revisions can never happen. If the vendor
cannot support that meaning without redefining finality, stop for another design
decision. Stability sampling and expiry of a nominal revision window are only
diagnostics; they never manufacture completion evidence.

## 7. Eventual promotion of Sprint 1M observations

The original archive object, metadata status and `as_observed()` behavior stay
PROVISIONAL forever. Promotion is a **separate derived projection**, proposed as
follows, with no real promotion performed in this phase:

1. Load the complete 1M batch by independently retained hash; replay raw bytes,
   normalization and original environment. Reject missing/changed dependencies,
   predecessors or identities. A `licensed_offline` label is insufficient.
2. Resolve the complete relevant conflict/revision corpus, including new records
   referencing the candidate and overlapping windows. Each disposition binds the
   exact competing versions, affected sessions, rationale, reviewer and time.
   Merely accepting the later response, seeing equal hashes or receiving an
   empty one-direction conflict list does not resolve it.
3. Load accepted source/license, listing, calendar and provider-receipt manifests.
   Bind their exact hashes to original observation IDs/raw hashes/candle hashes,
   adjustment basis, normalizer and requested session window. The candidate's
   archived calendar hash must agree with the reviewed calendar projection.
4. If a necessary calendar/evidence version differs from the one used by 1M,
   keep the archived batch unchanged. Require a separately approved, explicitly
   linked new normalization/acquisition candidate, not an in-place hash rewrite.
   There is no such re-contextualization API today. If the original acquisition
   chronology cannot satisfy section 6, stop and request a genuine new observation
   when authorized.
5. Compile exact existing `ProviderEvidenceArtifact` and `CandleEvidence` objects.
   Every candle must have accepted true provider-final/completed-session assertions,
   matching exchange/official close/hash and a unique traceable evidence ID.
   A compiler cannot derive true merely because an interval ended.
6. Produce a separate eligibility receipt binding the original 1M batch, raw
   observations, both manifests, registry generation, policy, fingerprints and
   reviewer decision. An independently authorized future admission action would
   supply real pins externally; acquisition/normalization cannot create them.
7. Construct new `ObservedTicker` projections with the same qualified snapshot and
   original honest fetch/content-availability timestamps, `final=True` only for
   individually qualified candles and a traceable finality source. Finality review
   time is separate. Do not mutate or monkey-patch the provisional provider.
8. Pass through existing `freeze_verified_daily_inputs` and replay before any
   separately authorized `publish_verified_daily_signals`. No legacy publish
   fallback, partial-ticker success or silent removal of a missing proof.

Fail closed on unknown authority/rights, stale notice coverage, missing or
unsupported completion, incompatible schema/environment, revision conflict,
ambiguous listing/session/action basis, false/missing finality, wrong scope or
hash, inadequate history, missing identity, clock uncertainty, unmet delay,
unreviewed/revoked inputs or an expired admission decision.

### Revocation and race boundaries

Historical replay uses the exact old evidence and registry to answer what the
decision used; it is read-only and must also expose subsequent revocation or
correction as a separate status. Old registry replay is not fresh authorization.
New admission must use the current reviewed corpus/generation and reject stale
receipts or unresolved later contradictions.

A separate evidence store and the existing signal-store transaction are not one
atomic database transaction. A revocation after candidate evaluation and before
signal publication is a real check-to-use race unless publication/admission is
serialized by an approved coordinator. **The proposed first implementation only
prepares/evaluates candidates; it performs no real publication.** Before supporting
concurrent real admission/revocation, approve either an enforced single-operator
quiescent procedure with an explicitly bounded interval or an architecture that
atomically binds current admission generation to publication. Rechecking twice
does not eliminate that race. No automatic fail-closed response to external
events or downstream execution revocation is claimed by this design.

## 8. Proposed interfaces, files and implementation boundaries

New files proposed for a future approved implementation:

- `models/calendar_finality_evidence.py`: frozen `SourceReceipt`,
  `ClockReceipt`, `CalendarAssertion`, `EvidenceManifest`, `ReviewDisposition`,
  `EligibilityRequest` and `EligibilityResult`; explicit schema/scope/status,
  strict fields, aware timestamps and hash identities. Candidate result states
  could be `PROVISIONAL`, `HELD_FOR_REVIEW`, `ELIGIBLE_FOR_1C_PROJECTION`;
  none alone means verified publication or trading authorization.
- `tools/calendar_finality_store.py`: separate append-only evidence database,
  original BLOBs, provenance/revision/conflict edges and review receipts. API
  candidates: `record_source`, `load_source(expected_sha256=...)`,
  `record_review`, `load_manifest(expected_sha256=...)`. Immutable IDs,
  transactional receipts, fail-closed integrity and no schema repair.
- `tools/calendar_finality_compiler.py`: pure
  `compile_calendar(assertions, manifest)` and
  `compile_provider_evidence(receipts, candle_mapping, manifest)` returning
  existing 1C objects plus derivation manifests. No download, network, pin creation,
  data rewrite or strategy evaluation.
- `tools/calendar_finality_review.py`: explicit
  `evaluate_candidate(archive, request, manifests, review_context)` and
  `replay_candidate(receipt, expected_sha256=..., archived_context=...)`;
  dry projection to existing `ObservedTicker`/1C inputs only for fully reviewed
  **synthetic** acceptance scenarios in the initial scope. No real promotion or
  production registry management is implemented without another approval.
- `tests/test_calendar_finality_evidence.py` and
  `docs/calendar_finality_evidence.md`: deterministic invented fixtures, failure
  injection, replay rules and operator boundaries. All examples marked synthetic.

No changes are initially required to 1C verification or 1M archive schemas/statuses,
and no new dependency is proposed. If implementation reveals a necessary change
to their contracts, stop and explain it before editing them. In particular,
effective-dated listing changes, divergent exchange sessions and intraday-session
representations are not disguised as simple compiler work.

## 9. Test plan and acceptance criteria

Existing assertions to preserve, read but not rerun in this phase:

- [test_market_verification.py](../tests/test_market_verification.py):
  `test_weekends_holidays_and_exceptional_closures_are_explicit`,
  `test_early_close_and_both_dst_transitions`,
  `test_missing_coverage_fails_without_falling_back`,
  `test_divergent_exchanges_fail_instead_of_silently_intersecting`,
  `test_empty_default_real_trust_and_cross_scope_rejection`,
  `test_provider_evidence_must_be_sufficient_even_when_pinned`,
  `test_publication_delay_and_verification_causality`,
  `test_provisional_candle_is_not_promoted_by_a_pinned_proof`,
  `test_records_cannot_be_self_authorized_or_tampered`,
  `test_atomic_verification_metadata_failure_rolls_back_run`.
- [test_provisional_market_data.py](../tests/test_provisional_market_data.py):
  `test_changed_overlapping_windows_are_durably_detected_and_replayed`,
  `test_schema_context_and_normalizer_changes_refuse_historical_replay`,
  `test_missing_normalization_and_prior_revision_evidence_fail_closed`,
  `test_provisional_never_published_even_with_pinned_proof_and_stable_hash`,
  `test_provisional_ingestion_cannot_publish_any_verified_run`.
- [test_daily_signal_pipeline.py](../tests/test_daily_signal_pipeline.py):
  `test_no_decisions_from_an_unfinished_session`,
  `test_future_fetched_evidence_cannot_be_replayed_into_the_past`,
  `test_unfinished_extra_candle_is_rejected_not_silently_trimmed`,
  `test_timezone_offsets_normalize_without_changing_input_hash`.

Proposed new offline cases:

1. Complete exchange/date coverage, year boundary, 200-session warm-up, all six
   listing identities and effective-listing-change refusal; absent/duplicate
   open/closed assertions, unsorted sessions and conflicting notices.
2. Both DST changes, US/Irish transition mismatch, supplied-offset disagreement,
   ambiguous/nonexistent local times, early close and ordinary session UTC
   conversions; wrong options/equity session and bar-start/close confusion.
3. Planned schedule amended by confirmed exceptional closure, reopening/conflicting
   authority, notice gap and unrepresentable intraday/different-exchange events.
   Tests must not invent a universally official holiday dataset.
4. Wrong source/hash/session/feed/action basis, partial receipt coverage,
   nonfinal/false-completion flags, one proof missing from warm-up, duplicate local
   evidence IDs and batch receipt mapped to the wrong normalized record.
5. Stable repeated responses, midnight labels and elapsed delay without evidence
   remain held. Evidence issued/received after fetch requires a genuine new
   observation; fake refetch/backdating, future review and clock uncertainty fail.
6. Split-adjusted history with changed factors and dividends, historical provider
   correction after publication, missing action evidence and reverse-direction
   conflict links. Preserve original raw/provisional objects and old run context.
7. Raw/manifest/projection/receipt tampering, missing ancestry, incompatible schema,
   lost acknowledgement, interrupted evidence/review writes, duplicate IDs and
   competing review writers. No partial bundle appears accepted.
8. Deterministic replay with retained code/versions/tzdata; changed environment
   refuses. Separate historical replay from current admission after revocation.
   Stale store generation rejects during evaluation. Do not claim a concurrency
   test can eliminate the separate-store publication race without that design.
9. Empty real root and cross-scope misuse still refuse; synthetic compiler outputs
   cannot become production pins. The existing 1M provider continues returning
   `final=False`. No network, broker, FX, risk, execution or scheduler is called.

Acceptance requires all these invariants, independent review of the synthetic
implementation, no existing-validator weakening, durable raw/review evidence and
explicit unsupported cases. After approval, run focused offline tests and the
full `uv run --no-sync pytest -q` regression, preserving all 922 baseline tests;
obtain exact-command permission if required. No test result is claimed here.

## 10. Staged plan and unresolved blockers

**Stage A — requested first implementation:** offline evidence models and isolated
store, deterministic reviewed-calendar compiler, raw-to-candle receipt mappings,
conflict evaluation and synthetic dry projections. Invented fixtures only; no
real eligibility/pins/publication, no downloads and no new dependencies. Produce
focused/full results and stop for independent review.

**Stage B — separately authorized source validation:** obtain actual original
official schedules/notices and listing history, appropriately licensed provider
documentation/completion samples and independent recorder evidence. Close
automation, retention/replay, local/cloud storage and redistribution rights.
Validate exceptional-notice delivery and correction coverage. No live/provider
downloads are authorized by Stage A approval.

**Stage C — another approval gate before real admission:** resolve vendor finality
meaning and all warm-up proofs, authenticate source/reviewer/clock boundaries,
qualify rights/environment, approve pin administration and admission/revocation
serialization. Only then consider controlled real projection/publication under
unchanged 1C. Missing evidence leaves observations provisional indefinitely.

Unresolved blockers include current all-six listing identities/effective history;
authoritative notice coverage; provider completion semantics/release identifiers;
as-of adjustment evidence and correction handling; archive rights after license
expiry; independent clock/receipt authenticity; review authorization/revocation;
unsupported calendar representations; cross-store admission races; and operational
response when new external information invalidates a past decision.

Successful calendar/finality onboarding would still not resolve real USD/EUR FX,
execution price/actual-clock realism, operator authorization and fixed experiment
policy, corporate-action portfolio accounting, alerts, missed sessions, capacity,
deployment or executable disaster recovery. See
[operational_readiness_audit.md](operational_readiness_audit.md) and
[provisional_market_data.md](provisional_market_data.md). Gate B remains NO-GO.

## Human approval required

Please approve or revise **Stage A only** before any runtime code, new tests,
schema or provider integration is written. This is the Sprint 1N Phase 1 audit
and design deliverable; work stops here for human review.
