# Sprint 1P: trusted USD/EUR FX evidence design

Date: 2026-11-10. Audited checkout: `main`, `1bb54e6`.
Supplied baseline: **1,013 passing tests**; not rerun for this documentation-only
audit. **Gate B remains NO-GO. Phase 1 only; implementation requires approval.**

## 1. Executive recommendation

Prepare FX evidence in a **new, separate provisional archive**, with immutable raw
receipts, explicit rate units, publication evidence, versioned publication calendars,
revision/conflict history and a pure deterministic evaluator. Keep eligibility,
independent review and authority admission separate. Begin with invented offline
fixtures and no admission or financial-system integration.

Evaluate an ECB reference-rate series first for **daily reference valuation**, subject
to verified methodology, rights and publication/correction evidence. A reference
valuation is not an executable FX price or a cost-of-liquidation guarantee. Intraday
risk freshness, bid/ask spreads and any execution-price requirements may instead
require a separately licensed commercial feed. No provider is approved by this design.

Retain canonical **EUR_PER_USD** arithmetic from Sprint 1F, its original-rate
reciprocal handling and Decimal rounding. Do not relabel a central-bank reference
rate as `indicative_mid`, make real data synthetic, or widen the existing risk scope.
Sprint 1O currently rejects FX; a future versioned EUR-valuation composition must
check equity and FX dependencies together in its authoritative transaction.

The main gaps are evidentiary and operational: source rights, publication/revision
authority, point-in-time availability, independent clocks/authorization, participating
writers and governed consumers. A hash, a public web page, an elapsed delay or a
successful conversion establishes none of these.

## 2. Existing architecture assessment

The following are inspected code contracts, rather than future capabilities.

### Sprint 1F arithmetic and compatibility

- [`tools/fx_conversion.py`](../tools/fx_conversion.py), `FXQuote`: frozen schema 1,
  scope `synthetic_test` or `unverified`, pair `USD_EUR`, explicit `EUR_PER_USD` or
  `USD_PER_EUR`, positive bounded Decimal, effective/retrieval times, provider/dataset/
  quote IDs, payload hash, provenance and **only** `indicative_mid` convention.
  Effective time must not follow retrieval. There is no publication-time field,
  raw-byte store, source authority proof, correction journal or admitted state.
- `CanonicalFX`, `canonical_quote`, `reciprocal_quote`: reverse quotes require an
  explicit reciprocal operation; retain the original quote. Conversion divides by
  the original reverse rate, avoiding multiplication by a rounded reciprocal.
- `FXInput` rejects binary floats and booleans. Rates allow at most 24 fractional
  places/36 digits and value at most 1e12; amounts allow 12 places and value at most
  1e12. Calculations use local precision 80, ROUND_HALF_EVEN, final quantum 1e-12.
  Multi-share valuation multiplies quantity before final rounding. No cent rounding.
- `FXPolicy` requires explicit maximum effective age; retrieval/effective times must
  precede valuation. Fresh retrieval does not refresh an old rate. Approval defaults
  to `not_required`. `FXTrustRegistry` is separately supplied, exact-content and empty
  by default; matching a pin is not provider authenticity, publication proof, current
  revocation enforcement or a production authorization service.
- `ConversionRecord` binds quote/request/policy/trust/code hashes and valuation time;
  `replay_conversion` regenerates the result with the supplied root. `EURRiskInputs`
  preserves original USD inputs and conversion records. Its per-share rounding can
  differ from final-notional rounding. Zero-rounded prices or collapsed stops can
  fail downstream validation; rounding is not silently relaxed.
- `convert_risk_inputs` accepts only synthetic FX and synthetic risk requests. EUR
  cash and quantities remain unchanged; USD prices, stops and costs convert with
  explicit units. Converted mark age uses the earlier equity-mark/FX-effective time.
  The adapter neither decides risk nor creates an order. Equity candle floats are
  not automatically converted into admissible financial Decimal inputs.

### Evidence archives and authority

- [`providers/provisional_market_data.py`](../providers/provisional_market_data.py),
  `ObservationMetadata`, `ProvisionalArchive`, `ProvisionalBatch`: immutable raw bytes,
  acquisition interval, provider/dataset/feed/version, licensing reference, hashes,
  normalization environment, revision/conflict checks and complete six-stock USD
  batches. `status` remains PROVISIONAL. Its ticker/OHLCV/session/adjustment schema is
  equity-specific; FX must not masquerade as a seventh ticker or USD equity response.
  A licensing-reference string is not a grant of rights.
- [`models/calendar_finality_evidence.py`](../models/calendar_finality_evidence.py),
  [`tools/calendar_finality_store.py`](../tools/calendar_finality_store.py),
  [`tools/calendar_finality_compiler.py`](../tools/calendar_finality_compiler.py) and
  [`tools/calendar_finality_review.py`](../tools/calendar_finality_review.py): source
  receipts preserve raw body hashes, publication/acquisition times, clock uncertainty,
  provenance, previous IDs and versions. Corpus generations, immutable review/results
  and transactional checks reject stale or competing reviews. Calendar and candle
  finality are evaluated independently. Real evaluations remain PROVISIONAL; eligible
  synthetic projection is not production admission. Their source-kind and candle
  proof schemas do not implement FX methodology or FX publication calendars.
- [`tools/market_verification.py`](../tools/market_verification.py) and
  [`tools/verified_daily_pipeline.py`](../tools/verified_daily_pipeline.py): 1C requires
  externally supplied exact-content calendar/provider roots, all required candle
  proofs, completed-session claims and availability causality. The default real
  registry is empty. An equity finality pin cannot authorize FX, and FX evidence
  cannot repair missing equity finality or calendar evidence.
- [`models/evidence_admission.py`](../models/evidence_admission.py) and
  [`tools/evidence_admission_coordinator.py`](../tools/evidence_admission_coordinator.py):
  bundles have purpose `USD_RESEARCH_SIGNALS` and `FX_NOT_INCLUDED`; `validate_bundle`
  rejects `fx_placeholder`. Exactly two synthetic source versions are expected.
  Independent review/admission, whole-six admission, dependency tombstones, current-use
  checks, sticky quarantine and boot epochs are implemented only for synthetic equity
  authority. Receipts are inspection-only. The separate FX content pin has no bridge
  to this journal. There is no FX grant to consume or revoke today.
- [`tools/synthetic_evidence_participant.py`](../tools/synthetic_evidence_participant.py)
  models fence/APPLIED-or-ABORTED outbox recovery. Existing 1M/1N writers are not fenced.
  Sealed imports detect capture-time changes; later unfenced changes do not constitute
  an enforced cross-store currentness protocol. See
  [`evidence_admission_coordination.md`](evidence_admission_coordination.md).

### Risk and broker boundary

[`tools/pretrade_risk.py`](../tools/pretrade_risk.py) requires synthetic EUR snapshots,
complete marks, explicit stop/cost assumptions, matching currency and freshness at
evaluation. Its configuration and thresholds are unchanged. The older
[`tools/portfolio_risk.py`](../tools/portfolio_risk.py) is another advisory interface;
it is not an evidence admission gateway.

[`tools/gated_execution.py`](../tools/gated_execution.py), `ExecutionRequest` and
`execute_locked`, operate in strict synthetic mode. They convert synthetic USD inputs
and evaluate risk in the broker's SQLite write transaction against locked holdings,
cash and outstanding instructions. No coordinator FX authority is consulted. The
current call supplies no FX trust root; requiring a pin is not a substitute for a
future admitted-evidence check. [`providers/paper_broker.py`](../providers/paper_broker.py)
stores EUR accounting values, uses precision-50 accounting and 12-place units, and
preserves opt-in strict controls. Its legacy numeric boundary is broader than the new
FX boundary; do not use it to justify accepting floats for FX evidence.

Kill switch, integrity preflight, operational latch, restore quarantine, idempotency,
SELL policy and atomic financial-state checks remain independent and untouched.
No authority read in a separate coordinator transaction can, by itself, make a later
broker fill atomic with revocation. Financial-use enforcement requires a separate
approved coordination design; this sprint proposes valuation evidence only.

## 3. Source comparison and licensing questions

**Offline assessment only.** No source website, endpoint, current terms or release
document was fetched. The descriptions below are candidate categories/onboarding
hypotheses, not verified current service commitments. Exact hours, holiday calendars,
historical availability, permissions and correction semantics are unresolved. Links
are official review starting points, not citations to inspected documents.

- **ECB euro foreign-exchange reference rates** — first candidate for a daily
  reference valuation series. Expected model: a scheduled working-day reference
  observation with currencies quoted against EUR, requiring explicit inversion for
  EUR_PER_USD where the source is USD per EUR. Confirm the actual consultation/
  calculation window, publication time and timezone, non-publication calendar,
  suspensions, rounding and historical correction process. A same-date value alone
  proves neither its exact measurement instant nor its historical availability.
  Review [ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html),
  [ECB data portal](https://data.ecb.europa.eu/) and
  [ECB legal information](https://www.ecb.europa.eu/services/disclaimer/html/index.en.html).
  Verify permitted automated retrieval, local immutable retention/versioning, derived
  reciprocal valuations, attribution, redistribution and paper-risk use. Public access
  is not licensing approval, and reference rates are not executable bid/ask quotes.
- **Other central-bank publications, such as Federal Reserve H.10 or Bank of England
  exchange-rate series** — potential corroboration or a separately approved alternative.
  Daily observations may have a different release cadence, observation window, base
  currency and later availability than the date they describe. Confirm daily-versus-
  weekly publication behavior, quote basis, methodology, revision/vintage retention
  and holiday coverage before designing selection rules. Review
  [Federal Reserve H.10](https://www.federalreserve.gov/releases/h10/) and
  [Bank of England statistics](https://www.bankofengland.co.uk/statistics).
  Check each publisher's automation/reuse terms, third-party rights and retention
  permissions. Do not average differently timed observations into an invented fixing.
- **Licensed commercial spot/reference or benchmark feeds** — candidates when a
  documented intraday as-of time, publication SLA, correction stream or bid/ask is
  necessary. Distinguish a benchmark fixing from an indicative mid and a tradable
  quote; a commercial label does not imply executable liquidity. Potential onboarding
  target: [LSEG FX benchmarks](https://www.lseg.com/en/ftse-russell/benchmarks/wmr-fx-benchmarks).
  Require the exact vendor/feed contract, entitlement, methodology/version, source
  timestamps, release sequence, historical vintages and outage/correction policies.
  Resolve non-display analytics, benchmark restrictions, derived data, local storage,
  audit backups, retention after termination and redistribution rights. No contract,
  price or API capability is assumed here.
- **Redistributors/aggregators of central-bank data** — operationally convenient but
  add another provenance, latency and licensing boundary. Verify both upstream rights
  and distributor terms, units, transformations, cache age and preservation of source
  release IDs/corrections. A distributor retrieval timestamp cannot stand in for
  upstream publication evidence. Prefer direct authoritative evidence where approved.

Choose one primary series and one explicit methodology per purpose. Cross-provider
comparison is an anomaly check under a versioned tolerance/window policy, not a
majority-vote trust mechanism. A fallback is a new reviewed source/methodology binding,
never an automatic substitution or blend. Do not claim a secondary observation is a
conflict until pair, units, window and convention are comparable; unresolved comparability
or material disagreement holds the affected valuation.

## 4. Proposed evidence schema and numeric identity

All names below are proposed contracts, not implemented APIs. Use frozen, extra-field-
rejecting models, strict booleans/integers, bounded payloads, explicit decimal text,
aware UTC-normalized instants and versioned canonical serialization. Reject duplicate
JSON keys, nonfinite values and ambiguous units. Preserve raw lexical rate text even
when normalized numeric identity treats `0.9200` and `0.92` equally.

1. **`FXRawReceiptV1`**: observation ID; scope (`synthetic_test` or real/provisional);
   source authority ID, provider/dataset/feed and versions; source instance/generation;
   release/response ID; raw bytes/hash; content type/encoding and response metadata;
   query identity and pagination/completeness; acquisition start/end, independent clock
   evidence ID and uncertainty; provenance; licensing/entitlement document IDs/hashes;
   prior observation ID and ingest sequence. Preserve every attempt, including failed
   or partial responses. Secrets and credentials are excluded.
2. **`FXSeriesDefinitionV1`**: explicit original base currency, quote currency, units
   (`quote units per one base unit`), publisher's original symbol, rate kind
   (`official_reference`, `benchmark_fixing`, `indicative_mid`, `bid`, `ask`), observation
   methodology/window, timezone and publication calendar, source precision/rounding,
   correction policy and documentation hashes. Only USD and EUR in initial scope.
   Corporate-action adjustments do not apply to FX; retain an explicit `NONE` FX
   adjustment policy and never inherit equity split/dividend conventions. Synthetic
   provider policies are labeled invented, not representations of ECB/vendor terms.
3. **`FXNormalizedRateV1`**: raw receipt ref/hash; series-definition ref/hash; original
   decimal rate and original units; reference date as a date; observed/effective instant
   or documented measurement interval; publisher release time or independently supported
   publication interval; acquisition interval; release/revision ID; normalization/code/
   environment hashes; original direction and explicit `direct` or `reciprocal` transform.
   Canonical currency identity is base USD, quote EUR, **EUR_PER_USD**. Store the original
   USD_PER_EUR divisor when inverted, not an authoritative rounded replacement quote.
4. **`FXPublicationEvidenceV1`**: source authority, series/release/raw hashes, publication
   confirmation artifact and time semantics, methodology/correction-policy refs, clock
   evidence, completeness/supersession claims, coverage horizon and known conflicts.
   Claims bind exact release contents, not merely a URL or provider name. Use
   `published_release_confirmed`, not an unsupported `will_never_change` assertion.
   A correction can supersede a completed publication; every version remains available.
5. **`FXPublicationCalendarV1`**: source-specific expected publication dates, exceptions,
   time windows and IANA timezone; coverage; authoritative schedule/exception refs; version,
   hash, availability time and timezone-database fingerprint. Expected publication and
   observed actual release are independent. An equity session calendar is not this calendar.
6. **`FXSelectionPolicyV1` / `FXEvaluationRequestV1`**: purpose, decision/valuation time,
   historical mode, age limits (elapsed duration plus publication-session gaps), allowed
   source/convention, explicit carry policy, conflict rules, evidence cutoff, complete
   dependency manifest, source generations and policy/environment hashes. No defaults
   that authorize carry-forward or fallback. Record a source-rate age and a separate
   equity-mark age; neither is refreshed by combining them.
7. **`FXEvaluationResultV1`**: deterministic pass/hold reasons for identity/arithmetic,
   licensing evidence, publication proof, time alignment, completeness and conflicts;
   all input hashes and generation vector; scope; evaluator version; replay inputs.
   Stage A result is `ELIGIBLE_FOR_SYNTHETIC_REVIEW` or `HELD`, never real verified FX.

Logical series/release identity includes scope, authority/provider, dataset/feed,
methodology version, original base/quote/convention and reference period/window.
Separate observation ID from content hash and revision ID. Reject conflicting reuse
of an ID; identical-content retry is idempotent but does not create fresh availability.
Detect overlapping-window corrections even when providers assign new IDs. A source
fork or unsupported metadata change requires resolution, not last-write-wins.

Arithmetic follows 1F: `EUR = USD * original_EUR_PER_USD`, or
`EUR = USD / original_USD_PER_EUR` through an explicit reciprocal operation.
Record scale, context and final rounding policy. Keep original numeric precision;
unsupported precision is archived but held at the compatibility boundary, not silently
rounded into 1F. Preserve amount units and per-share versus total costs. Bound errors
from per-share versus notional rounding in a future EUR envelope; display rounding
must never alter valuation or risk inputs.

## 5. Trust states and publication evidence

Raw observations always remain **PROVISIONAL**. Derived candidate/authority state is
separate from immutable source facts:

- **PROVISIONAL**: acquired/normalized; no authority. Evaluation eligibility remains here.
- **REVIEWED**: an independently authenticated reviewer has approved exact content,
  dependencies, source generations, purpose, temporal policy, scope and expiry. Evaluation
  is evidence for that decision, not authorization. A self-supplied pin is insufficient.
- **ADMITTED**: future coordinator grant by an independent admitter, distinct from
  preparer and reviewer, after current-generation/conflict/revocation checks. Unavailable
  in Stage A. Real admission remains disabled through all synthetic-only stages.
- **REVOKED**: durable deny-only tombstone on release, typed content, series/methodology,
  source, license, clock, policy or grant; dependent compositions are invalidated.
  Renaming an ID cannot evade content/dependency invalidation. No transition back.
- **QUARANTINED**: sticky safety hold for conflicts, uncertain currentness, integrity,
  startup, migration or recovery. A healthy response or elapsed timeout does not clear it.
  Any future release requires authenticated reason/evidence and fresh review/admission.

Positive evidence must cover source authority and rights, actual identified publication,
methodology, complete response, independently credible receipt time, raw integrity,
known revisions/conflicts and required temporal coverage. Missing publication instant
may be represented as an evidenced interval; its **upper bound** governs availability.
A date-only release or expected schedule must not be converted to an invented midnight,
fixing time or publication timestamp. If no justified bound exists, hold time-qualified
eligibility. Unknown methodology/effective window also holds compatibility evaluation.

Neither acquisition time nor HTTP metadata alone proves source publication authority;
neither official publication nor a valid calendar proves suitability for a risk purpose.
Retain policy/release documents and their own availability/revision history. Optional
signatures strengthen authenticity only with independently established keys and custody.
Hashes establish content consistency, not licensing, truth, finality or authorization.

## 6. Time alignment and look-ahead safeguards

Use **two timescales**: the economic reference period/effective window and the time the
information and its evidence were actually available. A third, admission decision time,
must not be backdated to either. Preserve IANA zones and original offsets in provenance;
normalize instants to UTC with the pinned timezone database. Reject naive times,
ambiguous/nonexistent local DST instants and numeric epochs at this boundary.

For an operational decision at `D`, require:

- effective window ends no later than `D`; use the earliest supported effective bound
  for conservative age, never a later fabricated timestamp;
- publication upper bound and acquisition-end-plus-clock-uncertainty are no later than
  `D`; all required documents/evidence are available by `D`;
- candidate is admitted/current for the requested purpose at actual use (future scope);
- source publication calendar coverage reaches `D`, no unresolved expected release gap,
  no superseding/conflicting evidence at the current evidence cutoff, and elapsed age
  and allowed missed-publication count both satisfy explicit policy.

Use the latest **eligible available** release under a deterministic ordering policy,
not the release whose reference date equals the equity session date. Ties/forks hold.
Record why every later candidate was excluded. Wall-clock age still advances over
holidays; a closed publication calendar never resets effective age or implies finality.

Alignment fixtures must include these cases (invented times, not provider promises):

- US normal close, US early close and exceptional closure: select by the actual
  valuation decision instant and source release availability, not a date join. An
  early US close may precede a European release; that day's unpublished rate is excluded.
- Weekends and different US/EU holidays: an EU release on a US holiday may be available
  for the next US valuation; a US session on a publisher holiday may have no new FX
  observation. Strict no-carry is the Stage A default. Explicit later carry policy
  must bind original release/age/calendar and may still fail elapsed freshness limits.
- US/Europe DST transition weeks: compute zone offsets independently. Never hard-code
  a constant hour difference between New York, Frankfurt and UTC. Euro currency identity
  does not identify the publisher's timezone or calendar.
- Missing, suspended, delayed or interrupted publication: distinguish evidenced scheduled
  non-publication from unknown outage. A successful retrieval of yesterday's file is
  not today's release. Never substitute rate 1, newest downloaded vintage or another feed.
- Valuation time differs from a later execution time: any future consumer must recheck
  evidence, age and authority at the actual decision. A daily reference valuation cannot
  authorize execution, ensure liquidation proceeds or change a stop/risk threshold.

**Historical modes are deliberately separate.** `AS_KNOWN_TO_THIS_SYSTEM` requires
actual independently recorded receipt/evidence availability no later than historical
`D`. A backfill acquired today cannot satisfy this for yesterday. A later
`RECONSTRUCTED_SOURCE_PUBLICATION` mode would require independently supported vintage
release history and historical methodology/availability; label it reconstructed, not
system-observed, and review separately. A latest-revised historical series may be used
only for explicitly labeled ex-post analysis, never point-in-time decisions. Corrections
learned after `D` cannot silently rewrite an as-known historical run.

Historical replay and current authority are separate queries. Inspection can reproduce
a prior result with its original evidence cutoff; a currently revoked dependency cannot
be reused through that historical receipt. A later license restriction may also prevent
otherwise reproducible replay; preserve legal disposition without claiming unlimited retention.

## 7. Immutable storage, revisions and recovery

Use a separate SQLite application/schema identity. Append raw receipt/body, normalized
versions, publication claims, policy/document snapshots, conflict/resolution events and
evaluations. Commit each observation and its local audit evidence together. Partial
responses remain labeled incomplete; an atomic period manifest names exact expected
coverage and cannot hide a missing release or a ticker's missing FX binding.

Maintain explicit previous-version links, sequence and expected-generation checks;
refuse forks, missing predecessors, changed identity reuse, incompatible schemas and
unresolved overlaps. A correction appends a new immutable release and conflict/history
evidence. Resolution names both versions, reason, operator and applicable knowledge
cutoff; it cannot delete the earlier observation or repair financial history.

Deterministic replay binds exact raw bytes/metadata, normalized rate, release documents,
publication/equity calendars, all relevant conflicts/revisions, policy, uncertainty,
decimal/rounding and parser/code/dependency/timezone fingerprints. Use a bounded canonical
format, defined stable ordering and a complete manifest. Reprocessing with changed
code/environment creates a new evaluation or refuses exact replay, never overwrites it.
Persist failures, original operation IDs and inspection-only receipts. Missing bytes,
hash mismatch or incomplete history fail closed. Hash chains do not protect against a
full malicious rewrite without trusted external checkpoints/authentication.

Future recovery must preserve revocations and unresolved fences, hold serving on restart,
require an independent authorized reason and external expected checkpoint, and never
reactivate historical grants. Backups do not grant current authority. Storage-full,
unknown commit and audit failures return no success; recovery uses the original operation
ID. Source normalization and conflict append must participate in the same generation
discipline as acquisition; otherwise a source write can evade currentness checks.

## 8. Future admission coordination and integration boundaries

Do not add FX objects to the existing v1 USD bundle or treat `fx_placeholder` as authority.
Propose a **new versioned `EUR_REFERENCE_VALUATION` composition** binding:

1. The complete canonical six-stock equity bundle ID/hash and current grant/dependencies.
2. Every required FX release, original direction, normalization/publication proof and
   purpose-specific source/calendar/license/clock/policy/environment refs.
3. An explicit mapping of each ticker/session/valuation instant to a selected FX release;
   one rate may cover all six at one instant. Historical ranges require every mapping,
   not one FX quote for the entire backtest. Missing one required mapping refuses the
   whole composition. This is evidence preparation, not a portfolio/order request.
4. Decision/evidence-cutoff times, conversion/rounding policy, source instance/generation
   vector, independent authorization, expiry and coordinator epoch.

A future coordinator transaction must validate both domains and all six mappings,
then commit one whole composition grant with durable audit; current qualified use must
check all revocation/fence/expiry dependencies again. FX, license or clock revocation
invalidates every dependent EUR composition, while an independently valid USD-only
equity grant can remain valid. Equity revocation invalidates the composition too.
Prepared/reviewed FX alone is never composed into current authority by cached pin matching.

Real cross-store safety needs approved source participation: commit coordinator fence
before an FX mutation; commit source generation/change plus immutable outbox locally;
finalize generation/invalidation in the coordinator. A durable abort tombstone must
serialize against late apply. Retain pending fences through crashes/restart; no lease
expiry proves safe abort. Extend the synthetic participant protocol first. Until **all**
relevant writers participate, imported generation checks are capture-time checks only.
Independent SQLite transactions do not establish cross-store atomicity. Admission and
use linearize in the authoritative coordinator, not in raw/archive or research mirrors.

Current v1 explicitly expects two sources, USD purpose and no FX. Supporting a third
domain, new dependency kinds, purpose, validation, revocation projection and persisted
replay requires a separately approved schema/API evolution. Preserve all v1 behavior
and deny guarantees; never reinterpret an old grant as a EUR grant on migration.
No production FX/market registry population, real admission, broker changes, risk-scope
widening, order creation or accounting migration is part of the proposed Stage A.

## 9. Failure matrix and threat boundaries

Each row states **condition -> check -> disposition -> synthetic test**.

- Wrong base/quote, silent inversion or mixed bid/ask/reference units -> exact series/
  direction/transform validation -> hold -> direct/reciprocal round-trip and mislabel tests.
- Zero, negative, NaN/Infinity, float/bool, excessive precision, overflow, duplicate JSON
  keys -> strict parser/numeric bounds -> raw retained, normalization/compatibility held
  -> malformed payload and Decimal-context tests; no rate truncation.
- Missing publication/acquisition/clock evidence or date-only timestamp -> explicit
  evidence/time-bound checks -> provisional/held -> missing, naive, numeric, uncertain
  and DST-ambiguous timestamp tests.
- Old rate freshly downloaded, publisher holiday, weekend, late release or outage ->
  separate effective age/calendar gap/availability checks -> no automatic carry/fallback
  -> age boundaries, mismatched US/EU holidays and unchanged old-body tests.
- Future observation, future publication, later correction or backfill -> knowledge-time
  cutoff -> excluded from as-known run -> before/at/after decision and revision tests.
- Same ID changed body, new ID overlapping correction, fork or competing provider ->
  content/series/window/comparability checks -> append conflict, quarantine affected
  candidates -> reverse-arrival, omitted-conflict and no averaging tests.
- Calendar valid but release absent, or published release with missing calendar coverage
  -> independent evaluations -> hold -> calendar-only/publication-only negative cases.
- Partial period batch or absent FX mapping for one of six equities -> exact manifest
  coverage -> no complete result/grant -> incomplete-period and incomplete-six tests.
- Spoofed provider, absent rights, expired entitlement or copied self-approved pin ->
  authority/license/role/purpose checks -> refuse eligibility/admission -> fabricated
  document, cross-scope and unauthorized promotion tests. Hash match never overrides.
- Tampered raw bytes, metadata, policy or history -> canonical hashes/dependencies and
  external checkpoint checks -> fail closed, no repair -> missing-row/schema/tail tests.
- Concurrent review/correction, stale generation or source mutation during capture ->
  snapshot/CAS generation check -> refuse stale result -> deterministic barriers/CAS
  tests. Without participating writers there remains a post-capture race, explicitly unclosed.
- Crash, full disk, interrupted append or lost acknowledgement -> local transaction/
  audit integrity and original-ID lookup -> rollback or inspection-only committed result
  -> injected failures and subprocess exit tests; never report a partial manifest complete.
- Future composed admission versus revocation or source update -> coordinator write
  serialization/fences -> whole composition admitted before denial, or denied entirely
  -> both race orders, abort/apply and restart tests in a separately approved stage.
- Historical or cached receipt presented as current authority -> current-use gateway and
  purpose/epoch/revocation checks -> reject -> revoked-replay and cached-pin bypass tests.

Trust assumes controlled files/processes, authenticated role mapping, trustworthy clocks
and external checkpoint custody. A hostile embedding process can replace callbacks or
rewrite files; hashes and synthetic roles do not solve that deployment threat. Provider
content can also be wrong despite authenticity: methodology and cross-check policy still
matter. Reference-rate valuation excludes spread/fees/settlement/hedging/liquidity risks;
it must not be advertised as a liquidation risk guarantee.

## 10. Interfaces, files and staged implementation proposal

### Stage A: request approval for isolated synthetic evidence preparation only

Proposed new files:

- `models/fx_evidence.py`: frozen receipts, series definitions, rate/publication/calendar
  evidence, revision/conflict manifests, selection policy and evaluation result.
- `providers/provisional_fx_evidence.py`: replaceable `RecordedFXProvider.read_recorded`
  protocol plus strict pure normalization of **invented recorded fixtures only**;
  no transport implementation. Reuse conventions, not equity OHLCV schemas.
- `tools/fx_evidence_store.py`: new SQLite archive with immutable receipt/body/history,
  local audit, generation and atomic complete-manifest publication; no migration of
  1M/1N/1O or broker stores. Explicit create/open and incompatible-schema refusal.
- `tools/fx_evidence_evaluator.py`: `evaluate_fx(manifest, policy, decision_at,
  evidence_cutoff, expected_generation)` and `replay_fx(evaluation, expected_hash)`;
  independent publication/calendar/causality/conflict predicates; results only.
- `tests/test_fx_evidence.py`: synthetic positive and failure matrix fixtures, including
  a pure six-stock **coverage plan** that grants no admission and invokes no orders.
- `docs/fx_evidence.md`: operational boundary, evidence limitations, replay semantics,
  failure results and approved scope. This design remains the architecture record.

Scope excludes persisted authorization/admission, new 1O kinds/purposes/schema,
production pins, real provider fixtures, live acquisition, changing 1F enums/rounding,
risk adapters or broker controls. An eligibility result may be serialized for review;
it never mutates a registry or creates an admitted FXQuote. No scheduler, CLI auto-fetch,
automatic fallback, broad historical reconstruction or quarantine-release API.

Acceptance criteria:

1. Preserve all **1,013** existing tests and existing code/contracts. Only approved
   new files; no dependency or protected-script changes.
2. Synthetic direct and reciprocal releases replay identically from raw bytes under
   the same environment regardless of caller Decimal context and equivalent UTC offsets.
   Retain original rate lexical precision and all source/time/provenance refs.
3. Every independent missing/ambiguous/conflicting evidence condition returns a held
   result with stable reason codes; no calendar/hash/delay shortcut establishes publication.
4. Demonstrate no look-ahead at uncertainty boundaries, US/EU holiday/DST mismatches,
   late corrections, date-only releases and today-acquired historical data. No-carry default.
5. Atomic local observation/audit and complete manifests survive failure injection,
   competing revision writers, process interruption and restart; failed attempts never
   appear complete. Deterministic replay preserves earlier versions and conflict history.
6. All raw data remains PROVISIONAL; results are synthetic eligibility only. Real scope,
   unauthorized promotion, 1O FX placeholder use and existing risk real-FX use remain
   rejected. Default FX and market-data registries remain empty.
7. After approval, run focused offline tests and full `uv run --no-sync pytest -q`;
   report exact counts, files, rejected cases, time alignment, replay and remaining gaps.
   No implementation or test execution is performed by this Phase 1 document.

### Stage B: separate approval, synthetic composition and writer protocol

Design/approve versioned 1O EUR composition, new dependency types and source participation;
then implement isolated synthetic admission/revocation/recovery and both race-order tests.
Keep production pins empty, v1 USD semantics unchanged and all financial consumers untouched.
Specify schema migration and replay compatibility before modifying the coordinator.

### Stage C: separate real-provider onboarding and operational gate

Obtain approved rights and methodology/publication/correction documents; qualify source
identity, actual release evidence, independent acquisition clocks, point-in-time vintages,
publication calendar exceptions, outage behavior, source participation and external
checkpoint/backup custody. Only an additional explicit trust-promotion authorization
could enable real admission. Provider onboarding does not authorize execution integration.

### Stage D: separate financial-use architecture and approval

Define EUR valuation envelopes, source-rate convention compatibility and a governed
consumer boundary. Resolve real risk scopes, portfolio-state consistency, freshness,
rounding and revocation-versus-use atomicity before proposing any risk/broker changes.
Do not solve slow daily-reference freshness by silently increasing risk age thresholds.
All existing operational controls remain mandatory and independent.

## 11. Remaining blockers and review decision

No current provider terms, API entitlement, publication clock/cadence, correction SLA,
vintage coverage or methodology has been verified in this offline audit. No real source,
licensed fixture, publication calendar, receipt-clock evidence, FX authority service,
production reviewer authentication or enforced writer/consumer protocol is approved.
ECB/reference-rate suitability for intraday portfolio risk is a policy decision, not
an arithmetic consequence. Exact carry limits, publication-gap limits, comparability
tolerances and risk-use conventions need review; none are silently chosen as production defaults.

The recommendation is **Stage A only**: new synthetic provisional storage, immutable
publication evidence and deterministic evaluation/replay. Approval would not include
real onboarding, coordinator schema evolution, financial execution or registry changes.
Stop for human architecture approval. Gate B remains **NO-GO**.

## Audit validation

This phase changes only this document. No provider/network requests, downloads,
dependency installation, orders, scheduling, commits or pushes were performed.
The supplied 1,013-test baseline is recorded without claiming a new regression run.
The pre-existing modified `scripts/sec_match_recon.py` was read only for its hash and
left unchanged: SHA-256
`7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`.
