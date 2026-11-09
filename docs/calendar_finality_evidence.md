# Sprint 1N Stage A — Offline synthetic evidence evaluation

Stage A prepares evidence and evaluates **synthetic** candidates only. It has no
download, provider transport, scheduler, real trust-admission, signal-publication,
broker, risk or order API. Gate B remains **NO-GO**.

## Files and contracts

- `models/calendar_finality_evidence.py`: frozen source receipts, calendar/notice/
  coverage documents, per-candle provider claims, manifests, independently
  authorized reviews, requests and results.
- `tools/calendar_finality_store.py`: separate append-only SQLite evidence store.
- `tools/calendar_finality_compiler.py`: pure calendar and completion compilers.
- `tools/calendar_finality_review.py`: synthetic evaluation and offline replay.
- `tests/test_calendar_finality_evidence.py`: invented evidence and deterministic
  failure scenarios. No official calendar or licensed vendor fixture is supplied.

The existing Sprint 1C verifier, 1M archive and all broker/risk/execution files are
unchanged. The earlier design document remains the architectural reference:
[exchange_calendar_finality_design.md](exchange_calendar_finality_design.md).

## Evidence preparation

Create an isolated `EvidenceStore(path)`. `record_source(SourceRecord(receipt,
body))` stores original bytes, not reconstructed text. `SourceReceipt` preserves
source/version, logical key, scope, publication time (or unknown), acquisition
start/end, clock identity/uncertainty, provenance, licensing reference, body hash
and explicit predecessor. Every source receipt stays `PROVISIONAL`, including
real-scope receipts. Unknown or malformed bodies can be retained but cannot pass
compilation. Source time is never inferred from elapsed time or local acquisition.

The supported evidence bodies are versioned offline documents, not vendor API
formats. A `CalendarSnapshot` wraps an existing `CalendarArtifact` and an explicit
listing-history assertion. The synthetic format declares a 16:00 local regular
close; earlier closes require separate `ExceptionalNotice` receipts. Exceptional
closed dates also require a matching notice. A separate `NoticeCoverage` binds
the calendar hash and declares complete channel coverage through evaluation time.
These are invented, reviewable assertions in Stage A, not independently validated
exchange facts. Actual intraday interruptions, listing transfers or divergent
exchange schedules remain unsupported and fail closed where not representable.

Provider `ClaimDocument` records contain one `ProviderClaim` per expected candle,
including all warm-up dates for all six tickers. Each claim identifies the original
1M observation, observation/raw/normalizer hashes, dataset/version/feed, release,
completion policy and adjustment policy, plus the unchanged 1C `CandleEvidence`.
An existing trading session never creates this claim automatically.

## Immutable history and conflicts

An exact source-ID retry is idempotent. Changed content or metadata under an old
ID refuses. Revisions of the same scope/kind/source/logical key must name their
current predecessor; ancestry and chronology validate on every corpus read.
The original version remains retained. A stable repeated body is still a revision,
never new evidence that a candle is final. Forks or missing ancestors refuse.

The compiler rejects selected superseded evidence. It also inspects active notice
and relevant provider-claim records omitted from a manifest, preventing a caller
from hiding competing assertions by excluding their references. The compiler
also compares overlapping active calendar snapshots, including listing
maps, open/closed classifications and session times. A different logical key
cannot hide a contradictory snapshot; disjoint coverage does not conflict.
This initial implementation has no discretionary conflict-resolution override: conflicting
candidates remain held and need a new explicitly reviewed evidence version.

1M history is inspected read-only, including overlapping normalized candles and
conflict edges in **both** directions. A newer conflicting observation referencing
an old candidate blocks that old candidate even if its outgoing `conflicts(id)`
list is empty. No 1M status, bytes, batch or normalization result is rewritten.

## Evaluation and review

Construct an `EvidenceManifest` of exact receipt IDs/hashes and an
`EligibilityRequest` binding the complete 1M batch hash, manifest hash, synthetic
purpose, verification/decision times and explicit publication delay.

A `ReviewDisposition` binds the exact request and source-corpus generation, an
operator, authorization ID, reason and review time. `record_review` requires a
separately configured trusted local callback returning the boolean `True` and
synthetic scope. It does not authenticate people itself. The operator application
must supply that authentication; a review-reference string is not a signature.
Denied/missing/stale reviews cannot yield a projection. There is no real-scope
review-admission or production pin-management API.
Multiple decisions for the same exact request are held rather than allowing a
caller to select the favorable decision. Resolve them with a new explicitly
reviewed request; old review records are never overwritten.

`evaluate_candidate(archive, store, request, manifest, review_id=...,
review_sha256=...)` independently compiles calendar and provider claims. The
`calendar_valid` and `finality_valid` flags report component consistency, not two
independent permissions to publish. A result is eligible only if both pass,
review succeeds and the unchanged 1C freeze/verifier accepts the whole projection.

Source publication and receipt times must be present and consistent. Receipt end
plus its uncertainty must be known by the relevant cutoff; completion evidence
must be recorded by the original 1M fetch end. Late evidence requires a genuine
new observation, not retimestamping an offline replay. Notice coverage must reach
evaluation time and cannot claim knowledge beyond its own receipt. Review occurs
after the source receipts and by verification. Existing 1C close/delay, exact
candle hash, exchange, availability and causal checks remain mandatory.

The positive result is `ELIGIBLE_FOR_1C_PROJECTION` with a separately identified
**synthetic** `VerifiedDailyInputs` JSON projection. It uses a local, hard-coded
synthetic registry only inside dry evaluation; no registry is persisted or
populated for production. No signals are generated or published. Original 1M
provider observations continue to return `final=False`.

Any real request or declared real-world batch returns `PROVISIONAL`, with no final
projection and no successful component flags. The result model also rejects
attempts to construct real eligible results. Synthetic provenance cannot be
converted into production authority by this API.

Ordinary calendar/finality/review rejection returns a durably recorded
`HELD_FOR_REVIEW` result with separate reasons and no projection. Corrupted/missing
archive or store evidence, incompatible schema and audit-write failures raise;
they do not return success or pretend that failure evidence was committed.

## Replay, transactions and race limits

Save the returned result hash independently. `replay_candidate(archive, store,
request_id=..., expected_sha256=...)` reloads the immutable result and its review
identity, validates source and archive generations, recomputes the same evaluation
and requires equality. Code changes, missing/tampered evidence or new history
refuse replay in the current corpus. Historical inspection requires preserving
the original database snapshots and environment; changed history is never silently
adopted into an old result. Replay is not new operational authorization.

Review and evaluation commits compare the source-corpus generation inside the
same SQLite write transaction as their required audit insert. A source revision
that wins before this commit causes refusal; a failed audit cannot return an
eligible result. IDs/results are immutable, including rejected results.
An eligible result's selected review is revalidated against the complete review
history under that same writer lock. A competing decision committed before it
therefore cannot be hidden in the evaluation-to-commit interval.

The 1M database and evidence database remain separate. Evaluation captures an
archive generation and checks it again before its evidence-store commit, but a
write **after that final archive check** can still occur before/after the commit.
A source revision **after commit** likewise invalidates the result's currentness.
These are generation-bound offline evaluations, not a cross-store atomic trust
or publication service. They issue no order or real publication authority.
Future concurrent real admission, review revocation and publication require a
separately approved coordinator/atomicity design; double checks alone do not
eliminate the race. No automatic financial latch or downstream revocation is
claimed or implemented here.

## Safeguards, tests and limits

The synthetic cases include calendar-valid/finality-invalid and the reverse;
missing warm-up and whole-ticker claims; missing exceptional notices; stale or
incomplete notice coverage; false completion claims; wrong raw hashes/feeds;
late/uncertain receipts and unknown publication time; omitted competing notices;
unauthorized/denied/stale review; real requests and mislabeled real batches;
forward/reverse revisions; immutable-ID conflicts; corrupted receipts/reviews/
results; audit-insert failure; review/result generation races; deterministic
replay and continued 1M provisional isolation. Existing holiday/early-close/DST
fixtures are explicitly invented, never an official calendar certification.

Source bodies are capped at 8 MiB, source corpus at 4096 records, and SQLite lock
waits at two seconds. Archive-history evaluation scans retained records and is
not a measured 90-day performance guarantee. No automatic retention/deletion,
notification, pin revocation or physical/off-device durability guarantee exists.
API immutability and hashes are not protection against a privileged owner rewriting
the whole corpus. Clock IDs, licensing and completion-policy references in these
synthetic records are declarations, not authenticated external evidence.

No live source rights, authoritative production listings/calendar, provider finality
release, independent real clock recorder or production admission has been proved.
The remaining Gate B blockers also include real FX, execution realism, authenticated
operating policy, corporate-action accounting, monitoring and deployment. Gate B
remains NO-GO. Stop for independent review before any broader implementation.

## Final validation and change list

Validation completed on 2026-11-09:

- Focused command: `uv run --no-sync pytest -q tests/test_calendar_finality_evidence.py tests/test_market_verification.py tests/test_provisional_market_data.py tests/test_daily_signal_pipeline.py`
  — **177 passed in 90.41 seconds**.
- Full command: `uv run --no-sync pytest -q`
  — **967 passed in 179.37 seconds**. All 922 baseline cases were preserved;
  45 new Stage A cases were added.
- `git diff --check` passed. The pytest commands required access to the existing
  uv cache outside the sandbox, using exact-command escalation. No dependencies
  were installed or changed.

Six implementation files were added: `models/calendar_finality_evidence.py`,
`tools/calendar_finality_store.py`, `tools/calendar_finality_compiler.py`,
`tools/calendar_finality_review.py`, `tests/test_calendar_finality_evidence.py`
and `docs/calendar_finality_evidence.md`. The earlier
`docs/exchange_calendar_finality_design.md` was retained unchanged during Stage A.
No existing runtime or test file was edited.

The protected script's pre-existing worktree change remains separate and
unchanged: SHA-256
`7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`.
No production trust entries, live requests, downloads, operational orders,
broker/risk changes, scheduler, deployment, commits or pushes were made.
The work is stopped for independent review; Gate B remains NO-GO.
