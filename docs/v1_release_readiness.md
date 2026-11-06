# V1 research-only release readiness

Audit date: 2026-11-06 (Europe/Dublin). Baseline reviewed: `d41c507`.
Recommendation: a narrowly scoped offline research-software release candidate,
subject to owner review. No release tag, deployment, or trading approval is implied.

## Phase 1 findings

The baseline suite passed: **466 tests**. Code, tests, historical scripts,
snapshot/replay documentation and available result-artifact structure were
inspected before implementation. No CRITICAL or HIGH blocker was identified
for the limited offline research scope. Scope excludes investment validation,
live operation, and unattended paper trading.

- **MEDIUM:** Legacy holdout scripts do not guard empty holdout/insufficient
  prehistory and download current provider data. They remain exploratory and
  outside the supported reproducible release path. The new boundary validator
  provides fail-closed checks without changing their execution behavior.
- **MEDIUM:** No archived quantitative backtest report was found in inspected
  repository artifacts. Local `runs/` files inspected by top-level structure
  are research-orchestrator records, not quantitative replay bundles. Missing
  evidence prevents performance verification; it does not prevent software testing.
- **MEDIUM:** The draft strategy specification mentions breakout trailing stops;
  fixed ATR stops are what execution implements. The V1 protocol explicitly
  scopes the supported hypothesis to mean reversion and fixed stops.
- **MEDIUM:** No aggregate portfolio risk/exposure cap, exchange-calendar
  completeness certification, point-in-time universe, FX or dividend cash model.
  These are disclosed limitations, not verified protections.
- **LOW:** Code/environment checks are intentionally strict; old experiments
  require the recorded checkout and source. A commit identifies history, not
  necessarily a clean workspace. The existing unrelated modification to
  `scripts/sec_match_recon.py` was not changed by this work.

If scope expands to operational trading or claims of validated investment
performance, the missing evidence and controls become blockers for that scope.

## Historical evidence inventory

Development period is 2020–2024, end-exclusive 2025-01-01. The legacy multi-stock
script evaluates baseline and BEAR-filtered mean reversion independently for
MSFT/AAPL/JPM/XOM/JNJ/WMT, each with its own 10,000 starting capital. Its average
return improvements and average drawdown reductions are independent-stock
summaries, not shared-capital portfolio performance.

The 2025-01-01 to 2026-11-01 end-exclusive period is a **previously inspected
holdout**. Its script evaluates the same two variants independently per stock,
using 2024 indicator warmup and fresh cash at the evaluation boundary. It is not
an untouched confirmatory sample. Repository code alone does not establish when
all research choices were frozen relative to inspection.

For both periods, numerical returns, trade counts, drawdowns, Sharpe ratios and
variant improvements are **unavailable for verification in the inspected archived
artifacts**. No figures have been invented, recovered from synthetic tests,
or recomputed. No ranking of baseline versus filtered strategy is supported here.
The offline portfolio implementation has synthetic end-to-end evidence, not an
archived historical shared-capital result for either period. A code path is not
evidence that a historical experiment was run or that it was profitable.

## Verified capabilities and release checks

The implementation supports frozen versioned daily snapshots, explicit action
and currency conventions, deterministic hashes, effective parameter records,
code/runtime provenance, offline single-stock and shared-capital replay, ATR
sizing and fixed stops, execution costs, and deterministic portfolio reports.
Existing tests cover next-open execution, entry-day/intraday/gap stops, trade
and cash accounting, flat curves, pooled expectancy and portfolio equity metrics.

New release checks repeat replay byte-for-byte, enforce identity/provenance and
input compatibility, and reconcile final cash, marked positions and P&L. Boundary
checks reject overlap, empty samples and missing/insufficient prehistory.
Synthetic future-suffix tests check causal signal/ATR/exit/regime generation and
portfolio prefix execution. They cannot certify the provenance of arbitrary
externally supplied signals or prove complete exchange data.

Final regression result: **484 passed** (466 preserved baseline cases plus 18
new release-gate cases), using the existing uv environment with dependency
synchronization disabled. No new market data were downloaded or evaluated.

## Investment-edge assessment

**No investment edge has been established by this audit.** Passing software
tests validates behavior on tested inputs, not expected future performance.
There is no verified historical performance bundle here, no untouched final
holdout, no benchmark-relative attribution, and no statistically independent
confirmation. The six-stock selection, prior inspection, unmodeled dividends,
idealized fills and market evolution all constrain inference. No profitability,
significance or deployment claim is justified.

## Paper-trading readiness

Ready for offline replay and human-reviewed research exercises. **Not certified
for unattended paper trading or live trading.** No operational paper broker
integration, order/fill reconciliation, monitoring, aggregate risk enforcement,
kill switch or forward-run track record is verified by this release. Manual
observation experiments can be planned separately under a new predeclared
protocol; this audit neither runs nor authorizes account actions.

## Review decision

Approve only a research-software release candidate with these limitations
visible. Preserve [the protocol](v1_research_protocol.md),
[reproduction instructions](v1_reproduce.md), source identity, test evidence,
and any future archived experiment/report hashes. Do not label the inspected
2025–2026 period untouched, merge independent-stock averages into portfolio
claims, or promote synthetic results as historical evidence. Release tagging
and acceptance remain pending owner review.
