# Sprint 1M — Real market-data onboarding design

Date: 2026-11-09 (Europe/Dublin). Inspected commit: `a443d2b`, branch `main`.
Universe: MSFT, AAPL, JPM, XOM, JNJ, WMT. Intended experiment: EUR 10,000,
USD-denominated US equities, long-only, supervised, 90 calendar days.

## 1. Decision and research scope

**Gate B remains NO-GO. No provider is admitted for verified real publication.**

Recommend **Massive, formerly Polygon, as the first vendor for a conditional
technical/licensing investigation**, with Alpaca's appropriately entitled
consolidated feed as the first alternative. This is an engineering preference,
not a purchase recommendation or a finding that either satisfies finality.
Massive has explicit bar/adjustment documentation and accessible current terms;
its documented corrections also make clear why ordinary daily bars cannot simply
be declared final. Its retention terms may disqualify the intended replay archive
unless suitable rights are agreed. [M1–M5]

The smallest future implementation should initially acquire and archive
**provisional** observations only, using approved recorded responses for offline
tests. Trusted publication remains a separate externally reviewed action. No
scope change to existing verification is proposed. If sufficient provider
completion evidence cannot be obtained, stop at provisional acquisition.

Public documentation, pricing pages and exchange notices were researched for this
design. No provider data endpoint, demo query, authenticated API, connected
market-data service, account signup, purchase or order was used. Some public pages
were inaccessible or JavaScript-only; their facts are labeled accordingly below.
Documentation access is not an empirical validation of provider responses.

Only this new design document is created. Runtime code, tests, existing docs,
dependencies, configuration and production trust remain unchanged. The supplied
858-test baseline was not rerun: tests were unnecessary for this design and would
require permission for the exact offline command. `scripts/sec_match_recon.py`
is excluded and its pre-existing modification preserved. No scheduler, deployment,
commit or push is included.

Evidence labels used throughout:

- **CODE:** inspected repository implementation or test assertions, not a fresh run.
- **DOC:** primary provider/exchange documentation inspected on the date above.
- **TERMS:** public contractual wording inspected; actual account/product rights
  and the user's subscriber classification still require approval.
- **INDEX:** official-domain search result available, full page not retrievable;
  details remain **UNVERIFIED** until the original is archived and reviewed.
- **EMPIRICAL:** no real provider behavior demonstrated in this sprint.
- **DESIGN:** proposed engineering policy, not an existing implementation or a
  provider guarantee. Anything absent from the sources is **UNVERIFIED**.

## 2. Existing verification contract — unchanged

### Repository contracts and call chain

The accepted path is `freeze_verified_daily_inputs` →
`verify_candle_finality` → `replay_verified_daily_signals` →
`publish_verified_daily_signals`, with verified loading through
`load_verified_daily_signals`. The 1B `DailySignalStore.publish` interface can
persist unverified research runs; it must not be substituted for 1C verification.
Acquisition must remain outside this publication authority. [R1–R4]

| Existing object | Required content and checks |
|---|---|
| `CalendarArtifact` v1 | `source`, `version`, `scope`, aware `available_at`, end-exclusive New York `coverage_start/end`, exactly six `Listing(ticker, exchange)` records, versioned `ExchangeSession` and explicit `ClosedDate` records. Exchanges are XNYS/XNAS. Every covered civil date for each represented exchange is classified, with no duplicates. |
| `ExchangeSession` | Session `date`, `opens_at`, `closes_at`, `exchange`, `source`, `version`; timestamps must map to the session's America/New_York date. Common 1B schedule requires identical sessions across represented exchanges; divergence refuses. |
| `Candle` | Plain session date; finite, positive `open/high/low/close`; nonnegative `volume` and `dividend`; positive `split_ratio` (new shares/old shares; 1 for no action); valid OHLC relationships. Existing fields are strict floats, not the FX Decimal model. |
| `TickerSnapshot` / `ObservedTicker` | USD, `US_EQUITIES`, named source, declared split-adjusted price **and volume**, dividend/split conventions, ordered bars; aware `fetched_at`, named `finality_source` and exact per-bar `BarAvailability(date, available_at, final)`. All six ticker histories must match all completed dates in the supplied schedule, with at least 200 completed sessions. |
| `ProviderEvidenceArtifact` v1 | `scope`, `source`, `version`, aware `available_at`, exactly one `CandleEvidence` per expected `(ticker,date)`, unique nonblank evidence IDs; no missing/extra proofs. Evidence source equals each ticker snapshot source. |
| `CandleEvidence` | Ticker, exchange, date, canonical normalized `candle_sha256`, actual evidence ID, aware `issued_at`, exact `official_close`, strict booleans `provider_final=True` and `completed_session=True`. Both flags need accepted external evidence, not adapter inference. |
| `VerificationPolicy` | Explicit nonnegative integer `publication_delay_seconds`; method fixed to `pinned_completed_session_evidence_v1`. No delay value supplies completion evidence. |
| `TrustRegistry` / `TrustPin` | Default is real scope with **no pins**. Separate reviewed exact-content pins bind kind, scope, source, version, SHA-256 and review reference for calendar and provider evidence. A run cannot authorize its own pins. |
| `VerifiedDailyInputs` | Frozen daily inputs, calendar, evidence, policy, verification records/time, exact external registry hash and verifier/source/tzdata fingerprint. Replay recomputes records and checks the retained environment. |

For the accepted signal basis the exact snapshot literals are
`price_adjustment='split_adjusted'`, `volume_adjustment='split_adjusted'`,
`dividend_convention='recorded_not_applied'` and
`split_convention='events_recorded_prices_adjusted'`. Source currency remains
`USD`; no EUR conversion belongs in the acquisition normalizer. [R3,R5]

**Actual chronology constraints** (`verify_candle_finality` and
`DailySignalInputs.validate_completed_inputs`):

1. Calendar/evidence availability must not exceed `verified_at`, and
   `verified_at <= decision_at`; the calendar must cover verification and decision.
2. Every observation is fetched by verification, and every candle's declared
   availability is after its official close and no later than its fetch/decision.
3. `official_close <= evidence.issued_at <= observation.fetched_at <= verified_at`.
4. Verification is strictly after official close and at or after close plus the
   configured delay. Proof exchange/close and exact candle hash must agree.
5. `availability.final` must already be true on the separately constructed
   eligible observation. Pinned evidence does not promote a provisional object.

**Integration consequence:** if a genuine completion notice arrives after the
first data fetch, preserve that first observation as provisional. Obtain and
archive a subsequent observation after the notice, check that its contents are
covered by the notice, then create a distinct eligible observation with truthful
fetch/availability times. Never backdate the notice, mutate the old raw response
or set `issued_at` to a fabricated close/delay time. If the chronology cannot be
satisfied, verified publication refuses. [R1–R3]

### Provenance and replay

1D preserves exact UTF-8 fixture `raw_payload`, raw SHA-256, dataset ID/version,
exchange, optional source timestamp, retrieval time and normalized snapshot.
`SourceBatch` is synthetic-only and enforces complete six-stock/session coverage;
`as_observed` deliberately sets `final=False`. Reuse the provider boundary, not a
scope flip or modification of this synthetic object. A future real archive must
also preserve original response bytes when an HTTP payload is not UTF-8 text. [R4]

Retain separate hashes for original bytes, decoded response, normalized candles,
snapshot, calendar/evidence, adapter/action-factor version, policies and registry.
Use existing `canonical_json` / `input_hash` for existing model hashes; a vendor
raw checksum is not the normalized `Candle` checksum. Preserve decimal source
lexemes alongside deterministic, validated conversion to the existing float
fields. Retain the commit, relevant source hashes, Python/dependency versions and
tzdata version required by 1B/1C replay. Do not promise cross-version bitwise
replay or authentic data merely because hashes agree. [R2–R5]

## 3. Provider comparison matrix

All six are plausible members of each broad US-equity offering below, but
**six-symbol instrument IDs, share classes, historical coverage, entitlements and
actual responses are EMPIRICAL: NOT DEMONSTRATED for every candidate**. A sample
AAPL/MSFT example is not proof of all six. Each requires an explicit symbol and
listing inventory before acceptance. No uptime/SLA or error-rate comparison has
been measured.

### Technical and finality assessment

| Candidate | Coverage/history/update evidence | Time/basis/action concerns | Completion/revision evidence | Fit for unchanged 1C |
|---|---|---|---|---|
| Yahoo Finance / yfinance | Existing repository daily-history adapter; actual six-symbol/history coverage UNVERIFIED here. On-demand library requests, not an accepted licensed delivery schedule. [R6,Y1] | Repository declares split-adjusted OHLCV and preserves action columns; vendor semantics and timezone mappings need independent validation. Midnight labels are not close times. | No accepted finality marker. Repository defaults every fetched bar provisional without a named verifier; no evidence service was demonstrated. | **NO-GO for trusted publication**; research/provisional use only if rights permit. No unofficial scraping/auth workaround. |
| Alpha Vantage | DOC: daily adjusted endpoint is premium, offers 25+ years; compact returns 100 rows, full history needed for 200-session warm-up. [A1] | DOC: raw daily OHLCV plus adjusted close and split/dividend events. Adjusted close alone is not split-adjusted OHLCV. Date/metadata fields do not attest completion. | Per-candle completion ID, revision window and exact payload attestation **UNVERIFIED**. Realtime/delayed entitlement does not prove finality. | Conditional acquisition candidate; adjusted-series normalization and finality remain blockers. |
| Polygon / Massive | DOC: custom stock OHLCV bars; documented individual tiers and access windows. Qualifying trades and absent intervals have defined semantics. [M1,M2] | ET window and epoch-ms bar-start timestamp; split adjustment option. Resolve regular-session versus extended-session eligibility and volume basis explicitly. | DOC: late bars, end-of-day corrections and recalculation occur. Ordinary response has no accepted completion evidence in this assessment. [M3,M4] | **Preferred investigation**, not admitted. Needs a verifiable release/attestation and sufficient archive rights. |
| Nasdaq Data Link / Sharadar SEP | INDEX: premium daily US EOD OHLCV/actions, history from 1998, reporting lag under one day. Full product page is JS-only here. [N1] | INDEX: multiple adjusted/unadjusted bases and action/reference data. Exact field/time/factor semantics remain UNVERIFIED. | Product name “EOD” and reported lag are not proof of immutable completion. Release identity, cutoff and correction policy UNVERIFIED. | Useful EOD alternative if original documentation, entitlement, basis and finality are confirmed. |
| Alpaca market data | DOC: US stocks/ETFs, historical since 2016; Basic real-time IEX coverage differs from Plus all-exchange coverage. [P1] | DOC: paginated daily bars; raw/split/dividend/spin-off adjustments. Fix feed, adjustment and timestamp-to-session mapping; never substitute IEX-only totals for consolidated data. [P2] | DOC: daily bars update during the day; late updates and trade corrections exist. These are not an accepted daily completion receipt. [P3] | First alternative to investigate with appropriate consolidated entitlement, rights and finality evidence. |

### Public costs, quotas and rights assessment

Prices are indicative USD/month snapshots of the cited pages, not quotes or a
subscription choice. Taxes, exchange fees, eligibility, business rights and later
changes are excluded. No purchase is authorized.

| Candidate | Approximate public cost / request constraints | Licensing/storage/redistribution status for this experiment |
|---|---|---|
| Yahoo/yfinance | Open-source client; no accepted vendor subscription, contractual request quota or SLA established. Do not infer unlimited/free data rights. | Y1 warns about personal use and directs users to Yahoo terms; Yahoo legal fetch failed. Automated experiment, local retention, cloud and redistribution rights **UNVERIFIED**. Library license is not a data license. |
| Alpha Vantage | DOC: standard free allowance 25 requests/day; premium removes daily caps subject to plan rate limits. Exact premium amount was not exposed in the retrieved selector and is **UNVERIFIED**, not assumed from older prices. [A2] | TERMS: public grant is personal/noncommercial unless otherwise agreed in writing. Paid access alone does not establish business, archive or redistribution rights; obtain written use/storage/termination terms. [A3] |
| Massive | DOC: Basic free; Starter $29; Developer $79; Advanced $199. History advertised by tier: 2/5/10/all-history years. Public stock page advertises free 5 requests/min and unlimited paid calls; actual account constraints and SLA still need confirmation. [M1,M2,M7] | TERMS: individual information license covers personal/non-business/noncommercial use; separate business/redistribution and source agreements apply. Storage during the license is permitted subject to terms; termination/downgrade imposes limits. Long-term replay rights are a blocker pending agreement. [M5,M6] |
| Nasdaq Data Link / SEP | INDEX: premium, price requires login. Current price, product quota, update SLA and eligibility **UNVERIFIED**. [N1] | Full terms/product license not retrievable (JS/404); personal/research/commercial, automation, storage after expiry, redistribution and cloud rights **UNVERIFIED**. Do not inherit rights from a different Data Link dataset. [N2] |
| Alpaca | DOC: Basic free / Plus $99; historical calls 200/min / 10,000/min; Basic excludes latest 15 minutes of historical access. Product/account eligibility still needs confirmation. [P1] | Agreement/disclosure entry points exist, but this project's automated/non-display, historical retention, business and redistribution entitlement is **UNVERIFIED**. A broker/customer agreement is not assumed to license every data use. [P4] |

### Interpretation and required vendor questions

The same ticker may have different bars across vendors because of eligible trade
conditions, session boundaries, feeds, split basis and later corrections. A
cross-vendor comparison is an anomaly check, not a vote that makes one bar final.
No candidate has demonstrated all current contract requirements. [M1,M3,P2,P3]

For each candidate obtain: all-six symbol coverage and start dates; supported
adjustment/action definitions; exact daily session and volume eligibility;
publication/receipt timestamps and timezone; completion/release mechanism and
its mapping to exact records; correction/cancel policy and notice channel;
backfill/revision window; current account quota and outage/SLA terms; personal
versus entity classification; automated/non-display/research use; local/cloud
storage and backups; retention after termination; sharing of raw/derived values
and screenshots; and costs including exchange agreements. **No documented
answer means UNVERIFIED, not assumed permission.** This checklist must be closed
with account-specific evidence, not just marketing pages.

## 4. Licensing and finality evidence gaps

The user must be classified explicitly as an individual personal researcher or
an organization/business/non-display user. A virtual portfolio and no real orders
do not by themselves decide that classification. Record operator/legal review,
accepted contract versions, datasets, access method, territory, permitted viewers,
automation and derivation use. Do not send licensed data to third-party tools or
public repositories unless separately permitted.

**Specific replay risk:** Massive's inspected terms require deletion of affected
data when its license ends, generally within 30 days, with a limited passive-backup
exception up to 90 days and no restore/use of that copy. Downgrade can change the
licensed historical set. These conditions must be resolved before promising
indefinite reproducible archives. A hash cannot replace retained data for replay,
and evidence immutability is not permission to keep unlicensed bytes. Prefer a
contract permitting the required archival/replay period; otherwise that provider
is unsuitable for this requirement. No deletion tool or retention change is
implemented here. [M5]

No reviewed provider source establishes an accepted exact-record daily finality
attestation for this pipeline. Absence of a found marker is not proof that the
vendor cannot offer one privately; it is an unresolved onboarding gate. Ask for
an authoritative completion/release policy and sample evidence without pretending
that a normal OHLCV response or stable repeated response supplies it.

## 5. Exchange-calendar verification plan

**Authority:** use exchange-owned NYSE hours/calendar materials and Nasdaq Trader
holiday schedules plus exceptional/early-close notices. Both inspected sources
describe early closures; Nasdaq explicitly refers readers to alerts. NYSE's
yearly PDF says its dates can change. Therefore an annual schedule is a versioned
starting point, not perpetual authority for all future sessions. [C1–C3]

**Proposed pinned artifact procedure:**

1. After separate acquisition approval, archive original official pages/notices
   with URL, title, publisher, publication/effective time where supplied, honest
   retrieval time, byte hash and reviewer. If publication time is absent, record
   unknown externally and use truthful artifact availability, never an invented
   historical time. Cover the entire 200-session warm-up plus the planned 90-day
   window, including year boundaries and enough future coverage for execution.
2. Verify each ticker's actual listing and share class from accepted reference
   records; record effective dates and map to XNYS/XNAS. Do not copy fixture
   listings into production or infer listing exchange from a trade venue code.
3. Normalize regular equity session opens/closes and every closed civil date for
   each exchange; distinguish equity hours from options, bonds, settlement and
   extended trading. Record weekends using approved official operating rules,
   not an unreviewed weekdays-only generator. Check every scheduled date against
   official exceptions. Keep supporting evidence for each exception.
4. Convert America/New_York civil timestamps to UTC using pinned tzdata. Preserve
   original local time, zone, UTC offset and normalized UTC. The usual ET clock
   time is not a fixed UTC time; test both DST changes and early closures. Do not
   use Europe/Dublin DST to schedule US decisions.
5. A calendar library can propose a draft and support difference checks, but is
   not exchange-certified. Record its version separately and reconcile its entire
   covered date set against accepted exchange rules/notices before review.
   No library/dependency is added now.
6. Emit `CalendarArtifact` with reviewed source/version, `scope=real`, truthful
   `available_at`, closed-date reasons and complete coverage. Pin only after
   reviewer approval. If actual XNYS/XNAS sessions diverge, the common-schedule
   adapter must refuse; do not intersect or alter one silently. A broader calendar
   architecture would need separate approval.
7. Recheck notices before admitting each new session. An exceptional closure or
   correction creates a new artifact/version/hash and reviewed pin. Preserve old
   runs with the old context; suspend affected new publication while unresolved.

Public documentation was read here; **no official calendar artifact has been
created, pinned or claimed to validate the invented fixtures**. The synthetic
early-close/DST tests establish behavior only. [R1,R7]

## 6. Candle-finality and revision policy

### Eligibility is evidence-backed completion, not eternal immutability

DESIGN: a completed session and an accepted provider release can make a specific
version eligible under the unchanged 1C contract. It does not warrant that future
corrections are impossible. The reviewer must establish the precise meaning of
`provider_final` from real provider evidence. If mapping an actual provider's
semantics into that flag would require redefining it, stop for a separately
reviewed design; do not reinterpret it in the adapter.

Suggested lifecycle, implemented only in a future approved archive:

`ACQUIRED_PROVISIONAL → EVIDENCE_COMPLETE → INDEPENDENTLY_REVIEWED → ELIGIBLE`

Any inconsistency moves the candidate to `HELD_FOR_REVIEW`. A later correction
creates a new revision linked to its predecessor; no raw bytes, previously
published inputs or past decision times are overwritten.

Eligibility requires all of:

- Accepted licensing and calendar version for this use, complete all-six coverage
  and at least 200 completed sessions, with matching source/basis identities.
- Actual provider completion evidence identifying its dataset/release, applicable
  session, issue time and exact records or an authoritative release checksum
  covering them. A documented derivation must connect the release to every
  normalized candle hash. The provider need not use our JSON hash algorithm, but
  our mapping cannot invent its assertion or claim that a local checksum is an
  upstream signature.
- Completion/action evidence for **every warm-up candle**, not merely the latest
  day. A 200-row adjusted snapshot may change old bars after a split. An old raw
  candle's receipt does not automatically attest to a newly transformed hash;
  retain the accepted action factors, release and deterministic derivation.
- Truthful causal timestamps satisfying section 2, `final=True` only on eligible
  observation objects, exact `ProviderEvidenceArtifact` coverage and separately
  approved real pins. Acquisition code must not write its own trust root.
- Explicit configured delay after the authoritative close, justified by actual
  provider publication characteristics and operating policy. No universal
  “wait 15 minutes” or “wait overnight” rule is approved. If evidence is available
  only next morning, publication/decisions occur then; never pretend knowledge
  existed at the previous close. Later execution eligibility must be reevaluated.

Repeated observations/stability checks, second-vendor comparison, file arrival,
HTTP success, a “last refreshed” date, market closed status and an elapsed revision
window are useful checks but **none alone proves finality**. A post-close daily
bar may include different trade-eligibility rules from a regular-session series.
If no eligible trades produce a bar on a scheduled session, the six-stock exact
coverage contract fails; do not forward-fill or invent a zero-volume close.

### Revisions and corrections

Archive each observation with retrieval time and new raw/content hashes. Compare
per ticker/session, adjustment factors, action events, feed/conditions version
and all OHLCV fields. Record exactly which prior artifact a revision supersedes.
Preserve “what was known when” separately from the provider's latest corrected
history. Never replay an old decision using a subsequently revised warm-up series
while retaining its original as-of time.

A correction affecting an unpublished candidate invalidates its candidate proof
set; rebuild and re-review the complete consistent snapshot. A correction affecting
a published signal produces an incident and explicit downstream hold/review; do
not silently replace that signal or rewrite financial history. Existing broker
integrity checks cannot discover an external data correction automatically.
Any future incident-to-execution-hold integration needs its own authorization and
atomicity design. This sprint does not add one.

## 7. Corporate-action and price-basis policy

Preserve the existing signal convention: **split-adjusted USD OHLC and
split-adjusted volume**, with dividends recorded separately rather than applied
as total-return adjustments. Do not substitute dividend-adjusted close for OHLC,
combine raw highs/lows with adjusted close, or mix volume share bases. These are
existing strategy contracts, not parameters to change for vendor convenience.
[R3,R5,R6]

DESIGN: prefer a provider-documented complete split-only OHLCV basis plus action
events. If transformation from raw data is necessary, preserve both series and
the reviewed factor schedule: for a split ratio `r = new shares / old shares`,
pre-split prices divide by `r` and pre-split volumes multiply by `r` when moving
to the post-split share basis. Compose effective splits in a defined order; handle
reverse splits explicitly. Validate cash dividend amounts in their declared USD
share basis and distinguish announcement, ex, record and payment dates. Missing
action information is unknown, not proof of no action.

For each snapshot record its adjustment anchor/as-of time. Use only action facts
and revisions actually available by that decision; today's back-adjusted history
is not point-in-time evidence for a past run. Freeze the six-stock universe at
launch and record instrument changes/delistings; do not retrospectively replace
a failed/delisted name or treat this selected universe as an unbiased market
sample. No new investment-edge conclusion follows from normalization.

**Execution/risk recommendation, not implemented:** actual USD execution quotes
and held quantities should use a consistent current share basis; split-adjusted
research prices must be explicitly mapped to that basis using only known factors.
Risk marks, held stops, order quantities and costs must refer to the same shares
and valuation time before conversion to EUR. Future simulated fills require
independent executable-price conventions, not an adjusted historical close.

The current broker has no general dividend-payment, split-share/fractional-share
or stop-rebasing accounting path. Therefore 1M does not resolve corporate-action
portfolio accounting. Until separately approved, an action that makes holdings,
orders or stops inconsistent must halt affected new execution for review; no
silent financial mutation, synthetic dividend P&L or automatic stop change is
authorized. Dividends remain excluded from claimed total-return performance.
[R8, operational readiness finding F4]

## 8. Proposed smallest adapter architecture

### Boundaries

1. **Explicit acquisition transport:** provider-specific, replaceable, no scheduler
   or publication privilege. Uses separately authorized endpoint/feed/plan and
   bounded requested session ranges. No broker or FX import is needed.
2. **Append-only observation archive:** retains original response bytes and a
   manifest; records retrieval start/end, source issue time if supplied, provider
   dataset/feed/version, response IDs, HTTP status, relevant date/rate-limit
   headers, request parameters without credentials, content type/encoding,
   currency, session/adjustment settings, byte hash and licensing reference.
   A missing upstream timestamp stays absent. Redact secrets before logging;
   protect licensed bodies and original authorization material by access control.
3. **Pure deterministic normalizer:** validates actual response schema, identifiers,
   OHLCV/action units, session labels and pagination. Produces the existing
   `TickerSnapshot` shape plus an external provenance/derivation manifest. Reject
   unsupported provider schema or mixed feeds rather than guessing columns.
4. **Independent evidence assembler/reviewer:** consumes accepted provider release
   and calendar evidence, links every normalized candle and action derivation,
   and prepares existing `ProviderEvidenceArtifact` / eligible `ObservedTicker`
   objects. It cannot turn unknown completion into true.
5. **Existing strict publication service:** takes the independently managed
   registry and calls 1C freeze/replay/publish. No bypass to 1B publication, no
   automatic real pin creation, no network fallback during replay.

Reuse `DailyOHLCVProvider.fetch_daily(ticker, sessions)` at the pipeline boundary.
The 1D `SourceProvider.fetch_source` idea is reusable, but its `SourceObservation`,
`SourceBatch` and `SourceSnapshotStore` are intentionally synthetic-only. Propose
a separate minimal real observation envelope/archive rather than broadening those
literals or weakening their validation. Its exact file/schema/migration design
needs implementation approval; no existing store is repurposed silently. [R4,R6]

### Error, quota and atomicity policy

- One explicitly requested six-stock batch; stage observations independently, but
  publish no daily signal until the complete consistent batch and evidence pass.
  Partial transport results can be retained as provisional evidence, never as a
  successful verified run. Actual pagination must finish for every symbol.
- Configure quotas from accepted account evidence. Bounded retries only for agreed
  transient errors/429, respecting `Retry-After`, a maximum attempt count and a
  wall-clock deadline. Use injected clock/backoff in tests. Authentication,
  entitlement, licensing, schema and finality errors refuse without automatic
  retry or vendor/feed substitution. No background catch-up loop.
- Check expected sessions against the pinned calendar, not response count alone.
  No missing-symbol trimming, silent shared-date intersection, forward fill or
  stale prior-run reuse as a current observation. Preserve existing verified
  run-ID conflict/idempotency semantics.
- Archive normalization failures and revisions with their identities, but do not
  label them eligible. Distinguish an empty permitted response, a quota/error body
  and an incomplete paginated response. Do not mistake HTTP 200 for valid data.
- Publication remains the existing atomic run+verification metadata transaction.
  Acquisition/archive commits and signal publication are not a single distributed
  transaction; reference immutable archive IDs and fail closed on missing links.
  A crash must leave provisional/staged artifacts, not a false verified run.

### Offline acceptance tests to write only after approval

Record licensed response fixtures or use clearly synthetic fixtures, never claim
invented fixtures are vendor evidence. Required cases: six symbols and exact
identifiers; full 200-session warm-up; pagination; float/hash normalization;
wrong currency/basis; adjusted-close/raw-OHLC mismatch; missing action fields;
splits/reverse splits and revised factors; holiday/early-close/DST/year boundary;
exceptional closure; delayed finality notice followed by a truthful new fetch;
unchanged bars without proof; proof for wrong release/hash; empty/partial/429/5xx/
authorization error bodies; deterministic bounded retries; conflicting revisions;
archive tampering; crash between archive and publication; proof/pin revocation;
no network on replay; and no broker/execution calls.

Preserve existing tests including
`test_provisional_candle_is_not_promoted_by_a_pinned_proof`,
`test_untrusted_calendar_blocks_ingestion_before_any_provider_call`,
`test_all_or_nothing_verified_publication`,
`test_atomic_verification_metadata_failure_rolls_back_run` and
`test_pinned_evidence_never_promotes_offline_candles`. Their contracts must not
be relaxed. After separately authorized implementation, request approval for the
exact focused/full offline test commands as applicable; retain the 858 baseline.

## 9. Explicit trust-registry admission criteria

No new real pin is admissible until a reviewer outside acquisition confirms:

1. User/entity classification, accepted current contract, source agreements and
   permitted automation/storage/replay/sharing/cloud use for the selected product.
2. All-six instrument/listing identity, exact accepted feed, 200-session history,
   original bytes and complete normalization/action-factor provenance.
3. Authoritative versioned calendar coverage and exceptional notices; correct
   timezone conversion and verifier/tzdata/environment fingerprints.
4. Real, sufficiently scoped completion evidence, exact-record derivation,
   truthful issuance/retrieval times, both required finality flags and every
   `CandleEvidence` field; no generated evidence IDs masquerading as vendor IDs.
   Local evidence-envelope IDs may reference real vendor receipts, with origin
   explicitly distinguished and retained.
5. Documented correction semantics and operational response, with a tested
   provisional hold for missing/inconsistent evidence. A future revision is not
   silently ignored or treated as impossible.
6. Exact calendar/evidence hashes, source/version, `scope=real`, reviewer identity,
   review reference/time and independent approval record. Pins remain external to
   incoming data and the run. Capture the exact registry hash in each run.
7. A controlled revocation/review process and retained old registry versions for
   audit. Do not mutate an old run's trust context or automatically re-authorize
   corrected contents. Revocation/distribution automation is not implemented.

These criteria are stricter operational admission requirements around unchanged
1C data models, not a claim that current `TrustPin` authenticates its reviewer.
Cryptographic signatures, an operator identity system or new registry-management
APIs would need their own implementation scope. Production pins stay empty now.

## 10. Recommendation and implementation go/no-go

**Preferred investigation:** Massive's appropriately licensed US-stock dataset,
chosen by required history/rights rather than highest-price tier. Resolve finality,
session eligibility, volume adjustment and durable archive rights first. Do not
buy a subscription merely to discover whether those critical requirements exist.

**Alternatives:** investigate Alpaca with explicitly entitled consolidated coverage;
then Sharadar SEP if its original documentation/license/release semantics can be
obtained. Alpha Vantage remains plausible for daily acquisition but needs full
history, reviewed split-only OHLCV derivation and completion evidence. Do not use
Yahoo/yfinance as a workaround for an unlicensed or unsupported primary path.

**Conditional GO for a future offline implementation:** only after explicit
architectural approval of the acquisition/normalization/archive boundaries in
section 8, preserving synthetic-only objects and independent publication. Start
with a provisional-only adapter and deterministic fixtures. This is not approval
for real provider API requests, account creation, procurement or trust admission.

**NO-GO for live integration validation until separately authorized:** name the
provider, account/product, permitted endpoints, quota/budget, licensed retention,
recorded responses and operator. No trading or FX service is implicitly included.

**NO-GO for verified real publication:** until every section 9 criterion is
demonstrated. If no provider can supply the evidence, keep the observations
provisional and return for review. Any proposal to accept time/stability instead,
change finality meaning or replace the shared calendar requires a separate
architecture decision, not an adapter compatibility patch.

## 11. Residual Gate B blockers

This design can identify contracts, authoritative sources, candidate providers,
evidence gaps and a bounded adapter plan. It does not demonstrate actual provider
availability, account rights, a working finality release, a real pinned calendar,
an entitled data response or live operational reliability.

Even successful market-data onboarding leaves: trusted real USD/EUR FX and its
licensing; causal execution-price evidence and actual-clock/expiry checks;
authenticated operator approval and experiment-policy enforcement at all strict
entry points; coherent action accounting for held quantities/stops/dividends;
supervised daily configuration, missed-window handling and escalation; capacity,
retention/disk and environment archives; off-device/disaster procedures and
deployment qualification. The existing FX risk adapter and orchestrator remain
synthetic-only. Market-data pins do not authorize real execution. [R8,R9]

No historical performance or simulated fill proves future profitability or
market executability. Gate A remains a separate supervised synthetic rehearsal;
Gate B stays NO-GO pending its own independent review.

## 12. Evidence sources and verification status

All public source checks below occurred on 2026-11-09. URLs identify primary
sources; no community commentary was used as technical or licensing authority.
Pages may change; a future approved onboarding must retain reviewable originals,
versions and hashes. No public-source files or provider payloads are added now.

### Provider and licensing sources

- **Y1 — DOC:** [yfinance documentation and legal disclaimer](https://ranaroussi.github.io/yfinance/).
  Research/education and personal-use warning, not a Yahoo contract. Yahoo's
  [linked legal terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)
  failed retrieval (999); current detailed rights remain UNVERIFIED.
- **A1 — DOC:** [Alpha Vantage API documentation](https://www.alphavantage.co/documentation/),
  daily and daily-adjusted sections. Premium/raw-versus-adjusted structure and
  historical row counts documented; no accepted finality receipt found.
- **A2 — DOC, price amount UNVERIFIED:** [Alpha Vantage premium page](https://www.alphavantage.co/premium/).
  Standard daily allowance and premium policy available; actual selector prices
  not exposed in retrieved text. No obsolete dollar amount is asserted.
- **A3 — TERMS:** [Alpha Vantage terms](https://www.alphavantage.co/terms_of_service/).
  Personal/noncommercial grant versus separately agreed uses. No account-specific
  archive, redistribution or business-use approval obtained.
- **M1 — DOC:** [Massive custom bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars).
  OHLCV fields, ET windows, bar-start milliseconds, split flag and individual
  tier prices. No endpoint was called.
- **M2 — DOC:** [Massive historical coverage](https://massive.com/knowledge-base/article/how-much-historical-stock-data-does-massive-have)
  and [pricing](https://massive.com/pricing). Plan history windows differ; pricing
  page partially dynamic, cross-checked with M1. Costs are not account entitlements.
- **M3 — DOC:** [Massive late aggregates](https://massive.com/knowledge-base/article/why-am-i-receiving-a-late-aggregate-bar-through-massives-websockets).
  Late/repeated aggregate updates; does not establish an immutable final release.
- **M4 — DOC:** [Massive canceled trades](https://massive.com/knowledge-base/article/how-much-does-massives-feeds-handle-canceled-trades).
  End-of-day aggregate changes after canceled trades.
- **M5 — TERMS:** [Massive market-data terms](https://massive.com/legal/market-data-terms-of-service),
  marked updated 2026-11-03; sections on personal use, source agreements,
  restrictions, plan changes and termination/retention. No individual eligibility
  or business/archive approval is inferred from this reading.
- **M6 — TERMS/DOC:** [Massive individual terms](https://massive.com/legal/individuals-terms-of-service)
  and [redistribution guidance](https://massive.com/knowledge-base/article/how-can-i-redistribute-massives-market-data).
  Separate business/redistribution rights must be resolved for the actual use.
- **M7 — DOC:** [Massive stock product page](https://massive.com/stocks).
  Advertised free/paid request limits are not a measured throughput or uptime
  guarantee. Its displayed demonstration prices were not used as observations.
- **N1 — INDEX; full product content UNVERIFIED:** [Sharadar SEP product documentation](https://data.nasdaq.com/databases/SEP/documentation?anchor=sample-data).
  Official-domain indexed description supplied coverage/history/daily-lag summary;
  direct documentation rendered only a JavaScript shell. Price requires login.
- **N2 — INDEX; TERMS UNVERIFIED:** [Nasdaq Data Link terms](https://data.nasdaq.com/about/terms).
  JavaScript-only; an alternative `/terms` fetch returned 404. Obtain original
  product/subscriber agreements before any licensing decision.
- **P1 — DOC:** [Alpaca market-data plans](https://docs.alpaca.markets/us/docs/about-market-data-api).
  Coverage, history, quotas and public prices; not actual subscription approval.
- **P2 — DOC:** [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars).
  Pagination, date-time inputs and adjustment choices. No API data was requested.
- **P3 — DOC:** [Alpaca real-time stock data](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data).
  Updating daily bars, late minute updates and trade corrections/cancels; these
  are not an accepted completed-daily-bar attestation.
- **P4 — DOC entry point; specific rights UNVERIFIED:** [Alpaca disclosures and agreements](https://alpaca.markets/disclosures).
  Account, exchange and data agreements require product-specific review; no
  automated archival/redistribution entitlement was demonstrated.

### Calendar sources

- **C1 — DOC, exchange-owned:** [NYSE holidays and trading hours](https://www.nyse.com/trade/hours-calendars).
  Distinguishes equity/other sessions and lists early closures; not yet imported.
- **C2 — DOC, exchange-owned:** [Nasdaq Trader calendar](https://nasdaqtrader.com/Trader.aspx?id=Calendar).
  Holidays/early closes and alerts reference; no production calendar pin created.
- **C3 — INDEX, exchange-owned:** [NYSE 2026 trading-calendar PDF](https://www.nyse.com/publicdocs/nyse/ICE_NYSE_2026_Yearly_Trading_Calendar.pdf).
  Indexed PDF text identifies early closes and a change caveat; the complete PDF
  was not downloaded or visually validated. Historical and
  future coverage still require the full approved notice set, not this PDF alone.

### Repository evidence inspected (CODE)

- **R1:** [tools/market_verification.py](../tools/market_verification.py),
  `CalendarArtifact`, `ExchangeSession`, `CandleEvidence`,
  `ProviderEvidenceArtifact`, `TrustRegistry.require`, `verify_candle_finality`;
  [docs/market_verification.md](market_verification.md).
- **R2:** [tools/verified_daily_pipeline.py](../tools/verified_daily_pipeline.py),
  `verification_source_sha256`, freeze/replay/publish/load/ingest verified APIs;
  [tools/daily_signal_pipeline.py](../tools/daily_signal_pipeline.py),
  `capture_daily_environment`, `DailySignalStore.publish/load`.
- **R3:** [models/daily_signals.py](../models/daily_signals.py),
  `SessionSchedule.completed_sessions`, `DailyStrategyConfiguration`,
  `DailySignalInputs.validate_completed_inputs`, `ObservedTicker`/`BarAvailability`.
- **R4:** [providers/offline_market_data.py](../providers/offline_market_data.py),
  synthetic `SourceObservation`, `SourceBatch`, `SourceSnapshotStore`,
  `SourceProvider`, `assemble_source_batch`, `OfflineDailyOHLCVProvider`;
  [docs/offline_market_data.md](offline_market_data.md).
- **R5:** [tools/historical_snapshot.py](../tools/historical_snapshot.py), `Candle`,
  `TickerSnapshot`, `canonical_json`, `input_hash`, `capture_environment`.
- **R6:** [providers/daily_ohlcv_provider.py](../providers/daily_ohlcv_provider.py),
  `DailyOHLCVProvider`, `YahooDailyOHLCVProvider.fetch_daily`;
  [tools/historical_data.py](../tools/historical_data.py), `download_historical_data`.
  No fetch method was invoked.
- **R7:** [tests/test_market_verification.py](../tests/test_market_verification.py),
  `fixture` is invented 2020 calendar/evidence, including synthetic exceptional/
  early closures; `test_early_close_and_both_dst_transitions`,
  `test_empty_default_real_trust_and_cross_scope_rejection`,
  `test_provisional_candle_is_not_promoted_by_a_pinned_proof`,
  `test_records_cannot_be_self_authorized_or_tampered`,
  `test_untrusted_calendar_blocks_ingestion_before_any_provider_call`,
  `test_all_or_nothing_verified_publication`,
  `test_atomic_verification_metadata_failure_rolls_back_run`;
  [tests/test_offline_market_data.py](../tests/test_offline_market_data.py),
  `test_roundtrip_preserves_source_and_provisional_state`,
  `test_pinned_evidence_never_promotes_offline_candles`,
  `test_archive_tampering_and_revisions`;
  [tests/test_daily_signal_pipeline.py](../tests/test_daily_signal_pipeline.py),
  completed-session, post-fetch clock, failed-batch and deterministic replay
  assertions. These tests were read, not rerun, and certify no real calendar.
- **R8:** [providers/paper_broker.py](../providers/paper_broker.py), `reconcile`,
  `_simulate_fill_locked`; [tools/gated_execution.py](../tools/gated_execution.py),
  persisted holding/order terms and supplied request policy;
  [docs/operational_readiness_audit.md](operational_readiness_audit.md), F2–F5.
- **R9:** [tools/fx_conversion.py](../tools/fx_conversion.py), `FXQuote`,
  `validate_quote`, `convert_risk_inputs` (synthetic-only risk path);
  [tools/paper_orchestration.py](../tools/paper_orchestration.py),
  `WorkflowInput.unique`, `_preview`, `execute_workflow` (synthetic workflow).

## Approval request — stop here

Approve or revise the proposed **provisional acquisition/archive/normalization
architecture**, with unchanged 1C verification and separate evidence review.
Live API validation, account expenditure and real trust admission require their
own explicit authorization and the evidence gates above. The Sprint 1M approval
gate requires stopping before runtime code, new tests or provider integrations;
this deliverable stops at that boundary.
