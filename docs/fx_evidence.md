# Sprint 1P Stage A: synthetic FX evidence preparation

Gate B remains **NO-GO**. This is an isolated offline archive, normalizer and
eligibility evaluator. It provides no trusted FX quote, admission, portfolio
valuation, risk decision, order or execution API. All fixture source names,
publication claims, rights documents, calendars and clocks are invented.

Approved architecture: [trusted_fx_evidence_design.md](trusted_fx_evidence_design.md).
Inspected baseline: `main`, `1bb54e6`, 1,013 existing tests.

## Files and interface

- `models/fx_evidence.py`: frozen, extra-field-rejecting synthetic receipts,
  records, series/calendar/publication evidence, coverage manifests, policies,
  snapshots, requests, normalized rates and evaluation results.
- `providers/provisional_fx_evidence.py`: replaceable `RecordedFXProvider`
  protocol and pure `numeric_fx` / `normalize_fx`; no provider transport.
- `tools/fx_evidence_store.py`: explicitly created separate SQLite archive,
  immutable record/evaluation IDs, canonical hashes and a single local journal.
- `tools/fx_evidence_evaluator.py`: `evaluate_fx(archive, request)`, pure
  `evaluate_snapshot(snapshot, request)` and inspection-only
  `replay_fx(evaluation, expected_hash=...)`.
- `tests/test_fx_evidence.py`: invented fixtures, independent evidence checks,
  corrections/conflicts, temporal boundaries, failure injection and restart replay.

Create a new `FXEvidenceArchive(path, create=True)` explicitly. Open an existing
archive with `FXEvidenceArchive(path)`; a missing archive is not recreated.
`record(FXRecord(...))` retains exact bytes as base64 plus a typed receipt. The
receipt includes source/dataset/feed, version and logical/release IDs, source
instance/generation, acquisition interval, publisher time, clock/uncertainty,
provenance, licensing reference, response status/completeness and raw hash.
Every receipt has immutable `scope=synthetic_test` and `status=PROVISIONAL`.
Raw malformed, partial and failed responses may be retained with their genuine
synthetic metadata; they cannot pass eligibility. Malformed receipt types or
incorrect body hashes reject before persistence.

Append synthetic series, calendar, document and publication records through the
same API. Build an `FXEvaluationRequest` binding the exact snapshot generation,
manifest, policy, decision time and evidence cutoff. The manifest specifies
selected raw IDs, exact expected dates and a pure mapping for all six canonical
equities for every requested date. It is an evidence coverage plan, not portfolio
state or an execution instruction. Missing coverage never produces an eligible
complete plan. Mapping one release to all six is allowed; duplicate mappings,
omissions and mismatched dates reject eligibility.

## Numeric and time contracts

Only an explicit original USD/EUR direction is accepted: USD base/EUR quote with
`EUR_PER_USD` plus `direct`, or EUR base/USD quote with `USD_PER_EUR` plus
`explicit_reciprocal`. Units must be `quote_per_one_base`. No slash-symbol guessing,
third currencies, crosses, bid/ask, indicative-mid or executable-price conventions
are accepted. `rate_kind=official_reference` remains explicit throughout.

Rate inputs are decimal strings, finite and positive, bounded to 1e12 with at most
36 digits and 24 fractional places (also limited by declared source precision).
Numeric JSON floats/booleans, exponent notation and silent precision truncation
are refused. Original lexical rate text is retained. The canonical EUR_PER_USD
text is derived under a dedicated precision-80 ROUND_HALF_EVEN context, independent
of the caller's Decimal context. A recurring reciprocal is a derived precision-80
value; it does not replace the archived original divisor or become a new source quote.
There is no monetary conversion or valuation in this implementation. The policy's
12-place monetary rounding identifier reserves compatibility semantics; the
normalizer does not round FX rates to a money quantum or change Sprint 1F.

Effective time comes from the raw rate payload. Publisher time appears separately
in the raw payload and receipt and must agree. Acquisition start/end is a separate
receipt interval. Effective <= publication <= acquisition-end is required. All
instants must be explicit and timezone-aware; date-only, naive and numeric epoch
timestamps are refused. A reference date must agree with effective time in the
series' IANA timezone. The configured timezone database and runtime are fingerprinted.
Every resolved supporting receipt must name available, current synthetic clock
evidence; preserving an unknown clock ID is insufficient for eligibility.

Only evidence whose acquisition-end plus recorded clock uncertainty is <= evidence
cutoff can be used. Cutoff must be <= decision time. Publication and supporting
documents must be available by that cutoff. Maximum effective age is explicit;
retrieval never refreshes effective age. The Stage A policy is strictly NO_CARRY:
the selected rate reference date must equal the source-zone decision date and
be a publication day. Holidays, weekends, early decision times and outages cannot
trigger fallback, forward-fill or selection of a later release. Recorded release
availability, not a US session-date join or a constant US/Europe hour offset, governs.

## Independent evidence predicates

Evaluation reports separate booleans and stable, sorted reason codes for:

1. **Numerical validity/coverage:** original units, explicit operation, source identity,
   supported rate precision and complete date/six-stock manifest.
2. **Publication validity:** exactly one current explicit publication claim for each
   selected observation, exact original release ID, raw body hash **and complete record
   hash**, series ID, confirmed/complete claim and available publication artifact.
   Binding the complete record prevents acquisition metadata changes from silently
   retaining the same release proof. A hash or elapsed time alone is insufficient.
3. **Calendar validity:** source-specific calendar identity, source timezone, explicit
   contiguous coverage through decision time, schedule documentation, exception
   documentation and a publication session for the selected rate. Omitted conflicting
   overlapping calendars cannot be selected around.
4. **Temporal integrity:** causality, receipt uncertainty, age, source date and no-carry
   requirements. A numerical rate can be valid while publication or temporal checks fail.
5. **Revision/conflict integrity:** complete predecessor references, unambiguous heads,
   current selected version and no omitted contemporaneously known competing observation.

Series definitions also require available synthetic methodology, correction policy,
license and clock documents. These are explicit test predicates; they are not legal
approval, real independent clock attestation or authenticated provider statements.
Active conflicting definitions for the same source/dataset/feed hold eligibility.

Only a result with all predicates true is `ELIGIBLE_FOR_SYNTHETIC_REVIEW`.
Otherwise it is `HELD`. Both are inspection-only, synthetic outputs. A held result
may retain partial normalized rates for inspection; that does not make its plan
complete or usable. No REVIEWED/ADMITTED/REVOKED authority state is implemented.
No FXTrustRegistry or production market registry is mutated. Sprint 1O still
expects `FX_NOT_INCLUDED` and rejects FX placeholders; all old scope restrictions
remain unchanged.

## Immutable history and deterministic replay

New IDs append; exact retry is idempotent. Reusing an ID with different receipt,
bytes, policy or evaluation content rejects without altering the original event.
Evaluation IDs likewise cannot silently overwrite decision history.

Corrections append a new raw receipt with an explicit predecessor. Missing links,
backward chronology and forks remain recorded but hold evaluation. New-ID overlapping
rates and alternative providers for a requested period cannot be hidden by omitting
them from the manifest. Different providers are conservatively treated as unresolved
comparability/conflict, without averaging or automatic primary/fallback selection.
There is no conflict-resolution or quarantine-release API in Stage A.

A linear, explicitly evidenced correction can be evaluated only by selecting its
new ID and supplying its own publication proof. Earlier evaluations are retained.
Fresh evaluation of a superseded selected observation is held. An acquisition or
correction after a historical knowledge cutoff cannot rewrite the as-known result.
Raw bytes, all revisions/documents/conflicts, source metadata, exact request and
policy are captured in every evaluation snapshot. Replay verifies its externally
supplied expected hash and fingerprints of the new implementation, canonicalization
source, Python, Pydantic and timezone database, then regenerates every predicate and
normalized rate. Changed environment or content refuses exact replay.

Historical replay uses the original immutable snapshot, even after the current
archive changes. Current evaluation uses a newly captured generation and full known
corpus; replay is never a claim of current source authority. Stage A models only
`AS_KNOWN_TO_THIS_SYSTEM` using synthetic receipt times. Backfills cannot be relabeled
as historically observed, and no vintage reconstruction or ex-post revised mode exists.

## Local transaction and failure boundary

Records and evaluations are journal events; their canonical contents, identity,
sequence, preceding hash and event hash are protected by a persisted tail. A new
record and its audit evidence commit in the same `BEGIN IMMEDIATE` transaction,
with FULL synchronous mode. Evaluation commits check the expected source generation
inside that transaction. Partial/stale evaluations cannot appear complete.

Expected test injections before commit roll back event and tail together. After-commit
lost replies are recovered using the original immutable ID; they do not imply rollback.
Abrupt subprocess exit also leaves uncommitted SQLite writes rolled back. Missing
tail/events, content corruption, incompatible application/schema IDs and missing
archives fail closed without migration or repair. Different revision writers serialize;
both observations remain available and a fork holds evaluation. An interrupted
evaluation audit produces no successfully published evaluation.

Generation identifies source-record history, excluding evaluation-only journal events.
Capture plus commit-CAS demonstrates local archive consistency, not cross-store
atomicity. No 1M/1N/1O writer, broker database or financial state participates.
An evaluated immutable generation can become stale immediately after commit; obtain
a fresh evaluation for current evidence rather than treating a receipt as authority.
The local chain detects inconsistency, not a complete malicious rewrite of all hashes.
No physical power-loss, filesystem durability or off-device backup claim is made.

Prototype bounds: 1 MiB raw body, 32 MiB event content, 64 MiB journal content,
4,096 events and 3,661 calendar days. Capacity violations refuse writes/evaluations;
existing history is not pruned. Full snapshots and repeated journal validation favor
clarity and reproducibility over production throughput. No performance guarantee.

## Validation and remaining scope

Focused tests cover direct/explicit reciprocal arithmetic, recurring division,
caller Decimal contexts, equivalent aware timestamps, malformed pairs/rates,
missing publication/calendar/license/clock documents, stale rates, clock uncertainty,
publication identity/metadata hashes, publisher holidays and no weekend carry,
early US decisions versus later European releases, naive DST wall times, look-ahead,
backfills, corrections/new proof, historical replay, omitted conflicts, incomplete
six-stock plans, partial responses, immutable IDs, corruption, capacity, failed
evaluation audit, competing revisions, process interruption and lost acknowledgments.
No simulated order is used by the new tests.

Deliberate supported subset: exact publication/effective **instants**, one source
reference date per decision under NO_CARRY, explicit complete civil-day calendars,
invented reference rates/documents and exact-point knowledge cutoffs. Publication or
measurement intervals, provider-specific real parsers, historical reconstruction,
carry policies, trusted FX quotes, authorization/admission and financial conversion
are not implemented. Date-only/ambiguous evidence is held rather than guessed.

Provider rights, methodology and actual publication/correction processes, authoritative
calendar exceptions, independent clocks, authentic operator/source identities, real
vintage availability, trusted storage/checkpoints and enforced source/consumer
participation remain unresolved. No real provider is onboarded or licensed by a
synthetic document. Later EUR composition and financial-use design require separate
approval. Existing risk thresholds, arithmetic, trust registries, broker controls and
execution behavior are unchanged. Stop for independent human review; no commits/pushes.

## Recorded validation

Final code tested on 2026-11-10, branch `main`, baseline commit `1bb54e6`:

- `uv run --no-sync pytest -q tests/test_fx_evidence.py`: **83 passed** in **10.10 s**.
- `uv run --no-sync pytest -q`: **1,096 passed** in **191.89 s**, preserving all
  **1,013 baseline tests** plus **83 new cases**.
- Whitespace checks on all six new implementation/test/notes files and the local
  documentation link check passed.

The sandbox could not initialize the existing user uv cache. The exact offline
commands used approved escalation with `--no-sync`; no dependencies were installed
or changed and no external data request was made. The prior approved design remains
unchanged. Only the six new files listed above were added by this implementation.
The pre-existing modified `scripts/sec_match_recon.py` was left untouched; SHA-256:
`7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`.
No files were staged, no commits or pushes were made, and Gate B remains **NO-GO**.
