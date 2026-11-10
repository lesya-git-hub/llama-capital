# Sprint 1Z — targeted SELL stop validation repair

Inspected HEAD: `8c2e6005a7884fa466a3c1697196c51a856e6113`. Baseline: 1,276 tests. Synthetic/offline only; **Gate B remains NO-GO**.

## Diagnosis

The original [Sprint 1Y results](../runs/sprint1y-30-session-results.json) contain **42 rejected baseline SELL proposals**: nine stopped at `INVALID_STOP: held-position stop must be below current mark`; 33 were rejected for projected concentration, position stop risk and/or aggregate stop risk. These are counts of proposals; a proposal may contain several limit reasons. There was also one rejected BUY sizing candidate. Bear-filtered had no rejections.

Three distinct checks explain the behavior in `tools/pretrade_risk.py`:

1. `Proposal.valid_prices` required the proposed stop to be below reference price for both sides. That is an entry constraint incorrectly imposed on an exit: a real held position's recorded stop may already be above its available sale price.
2. `_evaluate` rejected the entire snapshot whenever any holding's stop was at/above its mark, before calculating what a SELL would remove. This prevented even an otherwise eligible complete exit.
3. The final projected-portfolio checks apply concentration, cash, exposure and planned-risk limits to **the whole remaining portfolio**, including SELLs. This was an explicitly approved pre-existing conservative policy. Those checks were not removed or replaced by a liquidation exception.

The strict path is `PaperBroker.execute_gated` → `tools/gated_execution.execute_locked` → FX conversion → `evaluate_pretrade` → locked financial fill. The gate verifies source holdings/stop metadata, pending quantities, state hashes, accepted-order identity, timestamps, FX and all independent safety controls before filling. Its transaction/savepoint/audit code is unchanged. Quantity, overselling, missing/stale marks, invalid FX, cash/cost, account-integrity, kill/latch and restore-fence rejections remain protective.

## Exact production correction

Only [tools/pretrade_risk.py](../tools/pretrade_risk.py) changes production behavior:

- Stop-below-entry-price validation applies to BUY proposals. SELL still requires a positive finite recorded stop, valid exit-cost assumptions and a positive adverse sale price; there is no shorting or invalid-quantity exception.
- The held-stop/current-mark entry check remains unchanged for BUY. SELL may proceed to projection even with breached stops.
- A breached stop receives **no protective credit**. For SELL evaluation, each remaining breached-stop share conservatively contributes its full marked value plus existing exit slippage to planned risk, with existing fixed exit fees retained. This avoids negative risk or an unsupported guarantee of execution at the old stop. A full exit removes that tranche; a partial exit retains its conservative residual risk.
- All existing numerical limits and final projected-portfolio checks are unchanged. Healthy-stop risk calculations are unchanged. Pending BUYs still count toward risk/exposure, and pending SELLs still cannot fund BUYs or release capacity.

Focused tests demonstrate eligible full exits at/below the recorded stop and eligible partial exits, while larger residual positions still reject. This is not a blanket approval of risk-reducing SELLs when the remaining portfolio is in breach.

No broker, gate, FX, authorization, workflow, fixture, sizing, strategy, threshold or market-price assumption was changed. The repair does not create executable stop orders. Historic risk audits remain bound to their original engine source hash; preserve the original checkout/environment for replay rather than rewriting old evidence with new policy code. Sprint 1V ledgers were not opened or migrated.

## Identical 30-session rerun

The original experiment harness was run unchanged, in fresh temporary strict ledgers. Fixture hash, 200 warm-up/30 trial sessions, all signals, dates, EUR 10,000 initial capital, FX, zero costs and driver rules were compared and match. The separately approved [Sprint 1Z comparison JSON](../runs/sprint1z-sell-policy-results.json) retains the original report SHA-256, before/after summaries, all revised daily records and exact rejection reasons. Original report SHA-256: `2070817ac345eec6aff1b9d392d4c0e24b1551951811073e5a2168a8f455b2de`.

| Metric | Baseline before → after | Bear-filtered before → after |
|---|---|---|
| Rejected SELL proposals | 42 → 42 | 0 → 0 |
| Executed fills | 3 → 3 | 2 → 2 |
| Final equity EUR | 10,595.60 → 10,595.60 | 10,217.035 → 10,217.035 |
| Final cash EUR | 4,139.60 → 4,139.60 | 10,217.035 → 10,217.035 |
| Final exposure EUR | 6,456 → 6,456 | 0 → 0 |
| Realized P&L EUR | 0 → 0 | 217.035 → 217.035 |
| Unrealized P&L EUR | 595.60 → 595.60 | 0 → 0 |
| Maximum closing drawdown | 6.008739% → 6.008739% | 0% → 0% |
| Reconciliation/monitoring | All 30 days passed → passed | All 30 days passed → passed |

**The targeted repair does not eliminate the 42 trial rejections.** The nine early stop failures now reach projection and reject for actual residual concentration/planned-risk breaches, including the conservative treatment of other breached-stop holdings. The other 33 preserve their portfolio-limit rejections. Zero revised SELL rejections are `INVALID_STOP`. Both strategies therefore retain the same fills, holdings and P&L on this particular invented path. Unit/integration exit cases prove changed eligibility where residual limits actually permit it; unchanged experiment totals do not imply that the code correction had no effect.

Permitting liquidation despite unrelated remaining-portfolio violations would be a **separate policy decision**, for example a narrowly defined remediation exception. It is not silently included here. Stop at this boundary for review. Marked gains are not guaranteed liquidation proceeds; stops remain non-executing risk assumptions and no new strategy or real-data permission is established.

## Verification

- Focused: `uv run --no-sync pytest -q tests/test_sell_policy_repair.py tests/test_pretrade_risk.py tests/test_gated_execution.py tests/test_fx_conversion.py` — **136 passed in 3.00 seconds**.
- New tests cover full/partial exits, breached-stop risk, BUY restrictions, invalid quantities/stops/costs, oversells, stale marks/FX, negative cash, unchanged remaining-portfolio limits, kill/latch blocking, durable gate audit, reconciliation and competing partial SELLs. The concurrency test produces one fill and one stale-state rejection without overselling.
- Full regression: `uv run --no-sync pytest -q` — **1,294 passed in 247.87 seconds**, preserving all 1,276 baseline cases plus 18 new SELL-policy cases. Existing concurrency, rollback, workflow-authorization, integrity, restore-fence and idempotency tests passed in the full suite.

Only the new test file and targeted risk module changed code. The two new comparison files were created after explicit permission, without overwriting original Sprint 1Y evidence. Existing uv dependencies were used with `--no-sync`; no network, credentials, production trust changes, commits or pushes. Protected files and prior artifacts were hash-checked unchanged. Temporary ledgers were removed. Stop for independent review.
