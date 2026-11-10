# Sprint 1AA — risk-reducing SELL exception

Checkout: `8c2e6005a7884fa466a3c1697196c51a856e6113` plus the reviewed, uncommitted Sprint 1Y/1Z work. Synthetic/offline only. **Gate B remains NO-GO.** This change implements the newly authorized exit policy; it does not alter BUY limits or create executable stop orders.

## Exception contract

[tools/pretrade_risk.py](../tools/pretrade_risk.py) retains the existing projection, FX inputs and all numerical limits. A SELL can retain only **already-existing exposure/stop-risk breaches** when all of the following hold:

1. It sells owned shares within all pending-SELL reservations, leaves a nonnegative smaller position, and strictly decreases total projected marked exposure.
2. Projected absolute planned portfolio risk does not increase, using the existing Sprint 1Z conservative treatment of breached stops (no protective credit; residual shares carry full marked-value risk plus existing exit costs).
3. There is no pending BUY using the exit exception to obtain capacity.
4. A retained breach has the same limit category and ticker, if applicable, as a breach in the current snapshot. A new breach, including a concentration breach introduced by fees lowering equity, remains a rejection.

The only waivable reasons are `TOTAL_EXPOSURE`, `AGGREGATE_RISK`, `POSITION_EXPOSURE` and `POSITION_RISK`. Cash reserve, nonnegative cash, positive equity, duplicate identity, fresh/complete valuation, currency/FX, valid quantities/costs/stops and pending-order coverage remain mandatory. BUY projection, thresholds and rejection reason ordering are unchanged. Fully compliant SELLs still use normal approval; an exception approval explicitly records `RISK_REDUCING_SELL_EXCEPTION` in its durable risk decision.

No changes were made to broker transactions, workflow authorization, gate state checks, position/stop provenance, kill switch, operational latch, quarantine, audit insertion or concurrency/idempotency mechanisms. Every fill still requires the existing transactional gate. No shorting, stop execution, trailing stops, emergency liquidation scheduler, real feed or strategy change was added.

## Tests and prior expectation changes

Added [tests/test_risk_reducing_sell.py](../tests/test_risk_reducing_sell.py). Tests cover full/partial reductions with remaining violations, pending BUY risk/exposure increases, fee-induced new violations, oversells and reservations, negative cash, cash reserve, duplicate proposals, unchanged BUY boundaries, FX-backed strict fills and reconciliation.

Updated the explicitly superseded SELL expectations in `tests/test_gated_execution.py` and the existing Sprint 1Z exit tests. Expanded the competing-exit test to a breached-stop position that qualifies for the exception: exactly one request fills; the other rejects for stale state, with shares and audit preserved. The experiment test now checks that SELL fills went through the gate rather than requiring rejected SELLs to exist under the new policy. No fixture or experiment-driver code changed.

- Focused command: `uv run --no-sync pytest -q tests/test_risk_reducing_sell.py tests/test_sell_policy_repair.py tests/test_pretrade_risk.py tests/test_gated_execution.py tests/test_fx_conversion.py` — **149 passed in 2.86 seconds**.
- Full command: `uv run --no-sync pytest -q` — **1,307 passed in 212.44 seconds**, including 13 additional cases beyond the 1,294-test Sprint 1Z suite. Prior SELL-policy expectations were explicitly updated for the authorized exception; workflow-authorization, kill/latch, restore fence, stale FX/state, rollback, concurrency and audit tests passed.

## Identical 30-session comparison

New artifact: [runs/sprint1aa-risk-reducing-sell-results.json](../runs/sprint1aa-risk-reducing-sell-results.json). It contains prior artifact hashes, before/after summaries and all revised daily records. Both [Sprint 1Y](../runs/sprint1y-30-session-results.json) and [Sprint 1Z](../runs/sprint1z-sell-policy-results.json) artifacts remain unchanged.

The unchanged test-only driver used separate temporary strict ledgers, EUR 10,000 each, 200 warm-up sessions and 30 invented trial sessions (2020-10-08 through 2020-11-18). It verified identical fixture identity, all signal decisions, session dates, FX, zero costs and driver rules against Sprint 1Z. Fixture SHA-256: `d99a2d0e932da50753ba78a65c482cc6bf3a4bde56110dfa3a0b2121b009ce4f`.

| Metric | Baseline before → after | Bear-filtered before → after |
|---|---|---|
| Rejected SELL proposals | 42 → 0 | 0 → 0 |
| All rejected candidates | 43 → 0 | 0 → 0 |
| Executed whole-order fills | 3 → 8 | 2 → 2 |
| Final marked equity EUR | 10,595.60 → 10,920.590 | 10,217.035 → 10,217.035 |
| Total return | 5.956% → 9.2059% | 2.17035% → 2.17035% |
| Realized P&L EUR | 0 → 920.590 | 217.035 → 217.035 |
| Unrealized P&L EUR | 595.60 → 0 | 0 → 0 |
| Maximum closing drawdown | 6.008739% → 1.229178% | 0% → 0% |
| Final cash EUR | 4,139.60 → 10,920.590 | 10,217.035 → 10,217.035 |
| Final exposure EUR | 6,456 → 0 | 0 → 0 |
| Integrity/control failures | 0 → 0 | 0 → 0 |

Both portfolios finish flat. All 60 daily reconciliations and read-only monitoring checks passed (HEALTHY), with no short/negative-cash positions or forced terminal fills. Temporary ledgers were removed. The cash-only benchmark remains EUR 10,000 with zero return and drawdown.

The reduction from 42 rejections to zero does not mean 42 additional fills: successful exits change subsequent holdings, so later repeated SELL candidates disappear. Baseline now has eight fills rather than three, while signals themselves are unchanged. The exception allows recovery from existing limit breaches; it does not promise that every SELL will pass other safeguards.

These results are on invented prices/FX with zero costs. They do not establish strategy profitability, realistic liquidity, provider rights, executable FX or real-data readiness. Stops remain non-executing risk assumptions. The trial did not deliberately activate/release kill or latch controls; their rejection behavior is exercised separately by the regression suite.

## Preservation and review

No existing result or pre-existing untracked document was edited. Original Sprint 1Y/1Z reports, .env, protected script and Sprint 1V artifacts were hash-checked unchanged during the rerun. Only the risk module, the explicitly affected test expectations, the new focused test and this new document were changed/added; the new JSON is Git-ignored under `runs/`. No network, dependency synchronization, commits or pushes. Risk audits are source-hash-bound; prior audits should be replayed using their original code environment rather than rewritten. Stop for review.
