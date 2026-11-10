# Sprint 1Q: market-data provider onboarding feasibility review

Review date: 2026-11-10. Inspected checkout: `main @ 9a143f6`.
Supplied baseline: **1,096 passing tests**; not rerun for this static review.
**Gate B remains NO-GO. Recommendation: documentation-only Stage A; no adapter code.**

## 1. Decision and evidence limits

A safe path is plausible: contractually approved equity data and corporate actions,
separately authoritative exchange calendars/notices, and purpose-appropriate FX
publication evidence, followed by independently approved real-evidence admission
and operational enforcement. **No named provider has been established as suitable
or legally usable by this review.** We have no accepted vendor completion package,
current license, authentic receipt-clock evidence or enforced real cross-store path.

Repository findings below are **R: inspected code facts**. Provider comparisons are
**U: unverified candidates/questions**, not current product claims or approvals.
No network, provider calls, downloads or external research were used. No prices,
entitlements, publication SLAs or retention rights are assumed. Contract/legal review
must establish permitted use; public accessibility or a subscription is insufficient.

The main stop condition is substantive: if a provider cannot support the existing
completion/revision contract, reject that provider for verified use. Do not replace
evidence with a waited interval, repeated hashes, a successful HTTP response, locally
asserted `provider_final=True`, or a copied synthetic pin. Finality means a documented
completed release/version with correction semantics, not a promise never to revise.

## 2. Actual contracts and integration points (R)

| Sprint / concrete module and functions | Present guarantee and onboarding limit |
|---|---|
| **1C:** [tools/market_verification.py](../tools/market_verification.py), `CalendarArtifact.complete_artifact`, `ExchangeSession.new_york_dates`, `TrustRegistry.require`, `verify_candle_finality` | Explicit XNYS/XNAS listings and open/closed sessions; New York dates; exact-content external pins; every required candle bound to official close, completed/provider-final claims, hash and causal issuance. Default real root is empty. Calendar validity and delay do not establish finality. |
| **1C:** [tools/verified_daily_pipeline.py](../tools/verified_daily_pipeline.py), `freeze_verified_daily_inputs`, `replay_verified_daily_signals`, `publish_verified_daily_signals`, `load_verified_daily_signals`, `ingest_verified_daily_signals` | All-six verification precedes verified publication; replay checks roots/environment and regenerated proofs. Legacy research publication is not current admission. These APIs do not consult the 1O coordinator. |
| **1D:** [providers/offline_market_data.py](../providers/offline_market_data.py), `SourceProvider.fetch_source`, `assemble_source_batch`, `SourceSnapshotStore.save/load`, `SourceObservation.as_observed` | Replaceable injected source, raw payload/hash, USD/split-adjusted conventions and whole-six immutable batch. Synthetic only; adapted bars remain provisional even with stored reference evidence. No real provider normalizer. |
| **1M:** [providers/provisional_market_data.py](../providers/provisional_market_data.py), `RecordedProvider.read_recorded`, `normalize_recorded`, `ProvisionalArchive.record/normalize/conflicts/save_batch/load_batch`, `acquire_recorded_batch` | Raw bytes, acquisition metadata, versions/conflicts and deterministic normalization; exact complete six-stock USD batches. Accepts synthetic or declared licensed-offline observations, but all remain PROVISIONAL; a licensing-reference string grants no rights. Fixed `recorded_ohlcv_v1` is an internal schema, not a vendor format. |
| **1N:** [tools/calendar_finality_compiler.py](../tools/calendar_finality_compiler.py), `compile_calendar`, `compile_provider_evidence`; [tools/calendar_finality_review.py](../tools/calendar_finality_review.py), `evaluate_candidate`, `replay_candidate`; [tools/calendar_finality_store.py](../tools/calendar_finality_store.py), `EvidenceStore.record_review/save_evaluation` | Calendar/notices and finality evaluated independently; source receipts, corpus generations and competing-review checks; exact raw/normalizer/release mapping. Synthetic eligibility only. Real observations return PROVISIONAL, not a production projection. |
| **1O:** [tools/evidence_admission_coordinator.py](../tools/evidence_admission_coordinator.py), `prepare_from_stage_a`, `validate_bundle`, `record_review`, `admit_bundle`, `revoke`, `qualified_read`, `recover` | Independent review/admission, whole-six local authority transactions, dependency tombstones and restart quarantine. [models/evidence_admission.py](../models/evidence_admission.py) fixes USD research purpose, two synthetic sources and `FX_NOT_INCLUDED`; FX placeholders reject. Receipts are inspection-only. Real admission and EUR composition are absent. |
| **1O:** [tools/synthetic_evidence_participant.py](../tools/synthetic_evidence_participant.py), `apply/abort`; coordinator `begin_source_mutation/finish_source_mutation/abort_source_mutation` | Mock fence/outbox recovery, including durable abort. Existing 1M/1N writers do not participate. Import-generation checks detect capture-time changes, not all later source changes. SQLite authority atomicity is not cross-store atomicity. |
| **1P:** [models/fx_evidence.py](../models/fx_evidence.py), `FXReceipt/FXSeries/FXPublication/FXManifest`; [providers/provisional_fx_evidence.py](../providers/provisional_fx_evidence.py), `numeric_fx`, `normalize_fx`; [tools/fx_evidence_evaluator.py](../tools/fx_evidence_evaluator.py), `evaluate_snapshot/evaluate_fx/replay_fx`; [tools/fx_evidence_store.py](../tools/fx_evidence_store.py), `FXEvidenceArchive.record/save_evaluation` | Synthetic reference rates only; explicit original units/reciprocal, independent numerical/publication/calendar/time/history checks, local journal and generation CAS. Entire-record publication binding includes receipt metadata. Exact instants, one reference date per decision and NO_CARRY; no real parser, admission, valuation or risk integration. |

**Important compatibility details:** `normalize_recorded` requires split-adjusted USD
OHLCV and volume, `dividend_convention=recorded_not_applied`,
`split_convention=events_recorded_prices_adjusted`, explicit dividends/splits and exact
session coverage. It parses source decimals then creates existing float `Candle`
values; normalization and resulting candle hashes must be reproducible. This is not
a Decimal financial-price ingestion path. [models/daily_signals.py](../models/daily_signals.py),
`DailySignalInputs.validate_completed_inputs`, requires the canonical AAPL/JNJ/JPM/
MSFT/WMT/XOM universe and at least 200 completed sessions. Verify dated primary
listings; the code's XNYS/XNAS enum is not an actual listing-history source.

[providers/daily_ohlcv_provider.py](../providers/daily_ohlcv_provider.py),
`YahooDailyOHLCVProvider.fetch_daily`, is an existing explicit-fetch research route.
Its default finality is false; an injected named verifier does not itself establish
licensing or 1C external authority. Do not invoke it as an onboarding shortcut.

For FX, [tools/fx_conversion.py](../tools/fx_conversion.py), `canonical_quote`,
`reciprocal_quote`, `validate_quote`, `convert`, `convert_risk_inputs`, already provides
precision-80 Decimal arithmetic, original-divisor reciprocal handling and half-even
12-place money rounding. Its quote convention is `indicative_mid`, scopes are synthetic/
unverified and risk conversion is synthetic-only. A 1P `official_reference` rate must
not be relabeled as an indicative/executable quote to enter that boundary. Optional
exact FX pins do not establish current authority, licensing or publication evidence.

## 3. Provider requirements matrix

This is a **procurement/evidence acceptance specification**, not a claim that any
candidate supplies the capability. Unknown or unsupported requirements block the
corresponding purpose; no numerical score can average away a critical missing item.

| Requirement | Six-stock daily US equities | USD/EUR FX | Minimum acceptance evidence |
|---|---|---|---|
| Coverage and identity | All six, dated primary listings, full warm-up/decision window; consistent feed/dataset/version | Explicit USD and EUR base/quote, source series and methodology/version | Instrument/feed specification and complete sample manifest; no missing-member batch |
| Raw vs adjusted | Preserve original vendor fields; require documented split-only OHLCV/volume basis; distinguish raw and dividend/total-return adjustment | Explicit original direction/units; canonical EUR_PER_USD via direct or explicit reciprocal | Field mappings, factor vintage/as-of date and deterministic transformation; reject unknown/double adjustment |
| Dividends/splits | Explicit event values, units, event/effective dates, split-ratio direction, correction history; no implicit cash credit | FX adjustment policy NONE; reference vs benchmark/mid/bid/ask remains distinct | Corporate-action methodology and versioned event/factor evidence; FX convention document |
| Sessions/calendar | Official exchange identity, holidays, early closes, emergency closures and dated listings; regular-session OHLCV scope | Source publication calendar and exceptions, separately from US exchange sessions | Versioned authoritative schedule plus actual exceptional notices/coverage, source custody and availability |
| Completion/publication | Completed regular-session release binding each exact candle/version, including revised adjusted history | Actual identified published reference release, not presumed market close or an executable rate | Publisher completion/release policy, observed confirmation artifact and deterministic content inclusion mapping |
| Corrections | Revision IDs/sequence, changed bars/actions/factors, historical replacement and notification behavior | Release/correction IDs, supersession and comparable-period conflict handling | Preserved old/new payloads, predecessor references and conflict/incident disposition; no last-write-wins |
| Time semantics | Session label is a civil date, not publication midnight; actual official close, issuance, publication and acquisition times | Separate effective/measurement time, publication and observed acquisition time | Aware instants/credible bounds, UTC normalization, original zone/offset and clock uncertainty; no guessed times |
| Provenance/custody | Publisher, distributor, upstream feed, entitlement, request/response IDs, raw bytes and normalization | Same, plus original rate text/direction and publication artifact | Authenticated source channel/custody record, independent receipt evidence and content hashes |
| Point-in-time history | As-of bar/action/factor vintages and availability for historical decisions; future splits can restate past bars | Actual historical release vintages and availability; latest-revised series is not as-known history | Vintage archive/receipts, methodology availability and knowledge cutoff; today's backfill cannot prove yesterday's receipt |
| Freshness/availability | Complete six-stock delivery before a reviewed decision deadline; outage and partial-response behavior | Rate age and publication availability fit purpose; no silent carry on mismatched holidays/DST | Documented publication service behavior and explicit failure/expiry policy; no assumed SLA |
| Automation/usage | Internal non-display research, derived signals, forward paper use, authorized users/hosts and upstream exchange entitlements | Automated reference/derived reciprocal valuation and intended risk purpose; benchmark restrictions if applicable | Exact product contract and applicable upstream terms approved for the actual use; API access alone insufficient |
| Retention/replay | Raw data, factors, actions, revisions, artifacts, environments, local/off-device backups and post-termination rights | Raw releases, documents, corrections, reciprocals and audit snapshots under same needs | Written retention/replay scope, duration/deletion obligations and incident handling; not assumed perpetual storage |
| Redistribution | Internal reports, derived data, support/reviewer access and any sharing/publication | Same, including benchmark/derived FX restrictions | Explicit allowed recipients/outputs and prohibited redistribution; no default external sharing |

Raw unadjusted prices are important for a **future** execution/accounting basis; they
cannot replace the split-adjusted research contract. Likewise a dividend-adjusted
close alone cannot supply split-only OHLCV and adjusted volume. A normalization
derivation is acceptable only if independently documented, licensed and replayable.
Do not implement corporate-action transformations or change financial accounting here.

## 4. Candidate categories and practical shortlist (all U)

The following are names to evaluate after separately authorized evidence collection.
No current capability, price, correction guarantee or permission was checked.

| Category / named candidates | Practical role to investigate | Disqualifying unanswered questions |
|---|---|---|
| Licensed daily equity API: **Alpaca, Tiingo, Nasdaq Data Link** (exact product/feed required) | Potential small-universe OHLCV/actions source with manageable delivery interface | Which consolidated/venue feed? Split-only OHLCV and volume? All-six history/actions? Completed-release semantics and revisions? Automated non-display/paper use and replay rights? Do not infer suitability from an SDK or daily-bars endpoint. |
| Enterprise data: **LSEG, Bloomberg, FactSet** | Investigate a contracted package for equity data/actions, versioning and possibly FX; potentially more documentation/governance | Exact dataset and license, not corporate brand; content-bound completion evidence, point-in-time factors/vintages, entitlement/retention scope, operational burden and commercial feasibility remain unknown. |
| Primary exchange sources: **NYSE and Nasdaq** | First candidates for official schedules, exceptional notices, listing identity and applicable upstream licensing | Historical/corrected schedule and notice coverage, distribution permission and reliably captured availability; an exchange schedule alone supplies neither consolidated OHLCV nor vendor finality. |
| Central-bank FX: **ECB**, alternatives **Federal Reserve H.10 / Bank of England** | First assess a documented reference-rate series for daily reference valuation, separately from intraday risk/execution | Original quote direction, measurement window, exact publication cadence/calendar/time, corrections/vintages and reuse/automation/retention terms. No precise publication hour or daily/weekly availability assumption is accepted. Different windows are not interchangeable rates. |
| Commercial FX/benchmark: **LSEG/WMR, Bloomberg** (specific series required) | Investigate if a documented fixing, faster indicative observations or licensed bid/ask evidence is necessary | Reference fixing versus indicative/executable nature, correction stream, spread/fees, historical availability and benchmark/non-display/derived-data rights; no claim of executable liquidity. |
| Retail/research aggregators: **Yahoo/yfinance**, central-bank redistributors | Research comparison or provisional acquisition only unless all evidence/rights independently qualify | Unverified upstream licensing, storage/redistribution, adjusted-field semantics and completion/correction evidence. Existing repository transport is not an endorsement or accepted production path. |

**Recommended procurement order:** ask one smaller licensed equity-data candidate
and one enterprise alternative for the exact same requirements/evidence response;
assess official exchange calendar/notice custody separately; assess ECB reference
FX for the narrowly defined valuation purpose. Choose by demonstrated fit and
approved total rights/cost, not a presumed free/cheap tier. Two providers agreeing
is an anomaly check, not proof of truth or finality. No automatic fallback or blending.

## 5. Minimum independently verifiable evidence package

Use an immutable manifest with exact references and expected hashes; documentary
assertions must be attributable to their actual publisher and independently reviewed.
The provider need not compute our normalized candle hash: an authenticated completed
release, evidence of its exact contents and a documented deterministic mapping can
bind publisher claims to local hashes. A local boolean without that chain cannot.

**Shared custody envelope:** original bytes, content type/encoding, complete request/
response/page identity, publisher/distributor/feed/dataset/version, entitlement and
usage-document hashes, acquisition start/end, source publication/receipt identifiers,
independently retained clock evidence with offset/uncertainty and custody/access audit.
Retain raw and metadata hashes, code/environment/timezone versions, predecessor and
conflict references. A URL, self-asserted clock label, TLS retrieval or local hash alone
does not authenticate the entire history. Establish source identity, clock operation
and independent expected checkpoints under controlled identities/storage.

**For every equity candle, including every warm-up candle:**

1. Dated instrument/listing and authoritative calendar hash, exchange/MIC/session date,
   official open/close, regular-session scope, adjustment/action/factor vintage and
   normalized OHLCV/dividend/split hashes.
2. Publisher release/completion artifact and applicable policy/version, content coverage,
   issuance/publication time and explicit completed-session semantics; correction policy
   and complete known revision/conflict chain. A final release can later be corrected;
   it must still be identifiable and invalidate dependent use when required.
3. Binding equivalent to [models/calendar_finality_evidence.py](../models/calendar_finality_evidence.py),
   `ProviderClaim`: observation/raw/normalizer hashes, dataset version/feed, release ID,
   completion/adjustment policy refs and exact `CandleEvidence` coverage.
   Preserve 1C ordering: official close <= proof issuance <= observation fetch <= verification
   <= decision, with supporting evidence availability and clock bounds. 1N also requires
   claim receipt completion before the selected observation's acquisition end. If a later
   completion notice arrives after an earlier raw capture, acquire a new recorded
   observation/version under reviewed rights; never backdate or rewrite the old receipt.

**For every FX observation:** original rate text, original base/quote/units and rate
kind, exact effective instant or evidenced measurement bounds, reference date, actual
publication evidence and separate acquisition interval. Include source publication
calendar/notices, methodology/precision/rounding and correction/rights/clock refs;
raw body **and complete receipt-record** hashes; explicit reciprocal operation preserving
the original divisor; all revisions and comparable-period conflicts. Reference-rate
publication does not prove suitability for intraday risk or executable conversion.
Current 1P holds intervals/date-only data it cannot safely represent; do not invent a
point timestamp to fit its exact-instant subset. All supporting evidence must have
been available at the relevant knowledge cutoff, including receipt uncertainty.

**For the complete six-stock/EUR use:** a manifest binding every candle and every
required session/valuation-to-FX mapping, all dependency hashes and source instance/
generation vectors, policy/purpose/expiry, independent review and separate authorization.
No partial six-stock grant. A future real coordinator must commit whole-bundle admission,
dependency invalidation and audit locally, enforce current revocation at use, and hold
uncertain restart/recovery state. Every relevant source writer must participate in a
demonstrated fence/outbox protocol; every eligible consumer must use the governed path.
Current synthetic 1O does not provide that real path or EUR composition. Independent
SQLite commits, sealed imports and cached receipts are not cross-store atomicity.

**Historical distinction:** current acquisition of a licensed historical window may
support future decisions using that current vintage, if all proofs qualify. It does
not prove those values were knowable at earlier backtest decisions. Retroactive split
adjustment, later corporate-action corrections and revised FX can introduce look-ahead.
Historical as-known evaluation needs actual contemporaneous receipts or a separately
evidenced/labeled vintage reconstruction; those cannot be recovered from hashes alone.

## 6. Feasibility and smallest safe Stage A

**Offline now:** inspect user-supplied, lawfully retainable documentation; manually map
field/clock/release/license semantics to the matrix; run already authorized synthetic
tests in a separately approved task; rehearse existing immutable snapshots and rejection
contracts without promoting real evidence. No additional adapter is needed to discover
whether a vendor's contract or release evidence exists.

**Requires documents/contract confirmation:** exact product/feed, corporate-action and
adjustment semantics/vintages, official calendar/notice custody, actual completion and
correction evidence, publication timing, historical availability, clock attestation,
entitlements and all intended automation/storage/replay/sharing uses. Establish actual
rights before even a trial download or retaining sample payloads.

**Not establishable from current evidence:** legal permission for any named product;
real candle/FX release finality; authoritative actual calendars/listings/notices; prior
historical availability; credible independent clock history; real cross-store admission
and EUR risk authority; future executable prices, liquidity or forward operating readiness.
Some historical observations may never qualify if original vintages/custody were not
retained. It is acceptable to reject a provider or exclude an unsupported historical
purpose rather than fabricate missing facts. No data source can guarantee immutable
truth or future execution quality merely by supplying a daily bar.

**Proposed 1Q Stage A: documentation-only evidence qualification.** Under a future
explicit authorization, obtain approved-to-retain product/rights/methodology/release
documents and an independently attributable response to this matrix; do not implement
acquisition or contact vendors as part of this review. Record exact versions, effective
dates, custodian, hashes, evidence location, requirement result and unresolved owner.
Separate legal/entitlement review from technical evidence review; neither self-approves
admission. Missing items remain UNKNOWN/BLOCKED, never implicitly accepted.

Testable acceptance criteria for that documentary stage:

- Every matrix row has an inspectable artifact and independent reviewer disposition
  for the exact product and intended purpose; critical unknowns block selection.
- A paper walkthrough maps one normal session, early close, exceptional closure,
  split/dividend and corrected equity release, plus one ordinary/holiday/corrected FX
  release, onto the unchanged contracts. Use synthetic examples until real samples
  and their retention are explicitly licensed. Distinguish supported from missing facts.
- Demonstrate that a missing completion artifact, unknown adjustment factor vintage,
  date-only FX publication, unsupported rights or incomplete batch results in rejection.
  A cold reviewer must reproduce the disposition from the same versioned documents.
- Produce a separately reviewable integration proposal only after evidence fit is
  established. Any source-format, interval, real-scope, calendar or admission schema
  evolution needs its own approval and regression plan; no synthetic label substitution.
- No runtime, test, dependency, registry, data-store or execution changes; Gate B NO-GO.

Non-goals: provider adapters/downloads, new synthetic infrastructure duplicating 1M–1P,
trust promotion, finality heuristics, real admission, financial Decimal-price bridges,
EUR composition, broker/risk/valuation integration, corporate-action booking, fill
simulation, scheduling or changes to execution/SELL policies. If the documentary
blockers cannot be closed, stop. More code cannot manufacture authority or rights.

## 7. Gate B: possible route, no present approval

Reaching real-world forward paper-trading Gate B is **conditional, not demonstrated**.
Provider qualification could close only the data-evidence portion. The
[operational readiness audit](operational_readiness_audit.md), especially F1–F5,
remains relevant; 1M–1P improve preparation and synthetic coordination, not launch
authorization. The following still require independent evidence/design/review:

1. **Data and legal gate:** all matrix/package requirements for actual equity, calendar,
   corporate-action and FX sources, reviewed rights, trustworthy custody/clocks,
   corrections/outages and accepted point-in-time scope. No provider has passed here.
2. **Authority gate:** real-scope review/admission, purpose-specific EUR composition,
   complete writer participation/current-use enforcement, revocation/restart/restore
   and external anti-rollback checkpoints. Preserve 1C verification and whole-six
   publication; unverified legacy research APIs cannot become admission bypasses.
3. **Forward causality/fill gate:** actual captured execution-price evidence, source
   time/availability and invocation-clock checks, signal/authorization expiry, later
   eligible session, repricing/missed-window policy, costs/spread/liquidity assumptions
   and an explicit paper-fill convention. Daily OHLCV and reference FX cannot prove
   executable prices. These controls are outside the proposed Stage A.
4. **Policy/authorization gate:** [tools/gated_execution.py](../tools/gated_execution.py),
   `ExecutionRequest` and `execute_locked`, still apply caller-supplied policies and
   synthetic FX inside the broker transaction. Bind approved immutable experiment,
   universe, ledger, risk/freshness/cost policy and authenticated authorization at every
   new-fill entry point, not just [tools/paper_orchestration.py](../tools/paper_orchestration.py),
   `preview_workflow/execute_workflow`. A recorded operator name and preview are not
   independent authentication; a direct gated call still runs accounting/risk checks
   but does not inherit a complete governed operating workflow.
5. **Financial semantics gate:** split/dividend/share/cash/cost-basis and persisted-stop
   treatment, coherent raw execution versus adjusted signal basis, supported EUR
   valuation conventions and reference-rate freshness. Preserve the conservative
   existing SELL policy; breached stops/residual limits can reject exits. Planned stop
   risk is not guaranteed realized-loss protection. Unsupported actions require a
   reviewed halt/escalation rule, not silent accounting repair or policy relaxation.
6. **Operations gate:** new strict ledgers only; independent kill switch, integrity
   preflight, operational latch and restore fence; controlled identities/files/secrets;
   actual receipt-clock monitoring; supervised runbook/alerts and operator response;
   missed sessions/outages, storage/latency/capacity and 90-day lifecycle/terminal
   valuation qualification. No scheduler is required merely to be supervised, but
   repeatable accountable operations are. [tools/operational_controls.py](../tools/operational_controls.py),
   `reconcile_and_latch/strict_preflight_locked/release_operational_block`, protects
   broker integrity, not all independent source stores or market truth.
7. **Recovery/independent review gate:** [tools/backup_recovery.py](../tools/backup_recovery.py),
   `create_backup/verify_bundle/restore_backup`, and
   [tools/restore_quarantine.py](../tools/restore_quarantine.py), `read_restore_fence`,
   provide bounded broker recovery with persistent quarantine, not a demonstrated
   whole-system recovery set or authorized execution resumption. Qualify coordinated
   backup/custody, physical durability and incident drills; healthy reconciliation
   cannot clear independent controls. A final launch decision must independently
   review actual evidence, supported software boundaries and operating readiness.

Unresolved questions: which exact equity product can document compatible completed
releases and adjusted vintages; who can approve all required rights and retention;
which official notice/listing history can be retained; what receipt clock/custody is
independently credible; whether reference FX meets the intended decision deadline;
which historical periods have genuine vintages; and who owns the separate authority,
forward-price, corporate-action and operational gates. No launch date or budget can
be responsibly fixed from the current evidence.

## Review record

Only `docs/market_data_provider_onboarding_review.md` is added. No implementation,
test execution, network access, downloads, dependencies, external messages, data or
registry changes, orders, staging, commits or pushes occurred. The supplied test
baseline is not a fresh result. The pre-existing modified protected script is unchanged:
`scripts/sec_match_recon.py`, SHA-256
`7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`.
Stop for human review. **Gate B remains NO-GO.**
