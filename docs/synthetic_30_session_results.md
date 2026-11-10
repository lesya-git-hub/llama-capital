# Sprint 1Y — 30-session synthetic portfolio experiment

Inspected HEAD: `8c2e6005a7884fa466a3c1697196c51a856e6113`. Production components are unchanged. **Gate B remains NO-GO.** These are invented-path accounting/control results, not evidence of investment performance.

The test-only driver is [synthetic_portfolio_experiment.py](../tests/synthetic_portfolio_experiment.py), with [focused tests](../tests/test_synthetic_portfolio_experiment.py). Full daily records are in the new, Git-ignored [synthetic results JSON](../runs/sprint1y-30-session-results.json). It records cash, positions/cost basis, equity, exposure, realized/unrealized P&L, drawdown, signals, candidate proposals, staging status, rejection stage/reasons, fills and cumulative fills for both portfolios.

## Shared experiment specification

- 200 invented weekday warm-up sessions followed by 30 consecutive invented trading sessions, **2020-10-08 through 2020-11-18**. This calendar is explicitly synthetic, not an official historical holiday calendar. Both variants receive the exact same six-stock OHLCV and FX paths, EUR 10,000 cash, costs and risk configuration.
- Fixture identity: `d99a2d0e932da50753ba78a65c482cc6bf3a4bde56110dfa3a0b2121b009ce4f`. Prices deliberately exercise recovery, regime filtering, holding periods and adverse-price/risk rejection paths. Signals are calculated rather than edited to force trades.
- Each decision uses only the completed prefix through the previous session's close. The existing shadow harness validates the prefix and reuses the existing mean-reversion/ATR/regime/exit calculations. SELL takes precedence over BUY, matching the existing daily research rule. No provisional observation is promoted into verified publication.
- The following session's invented opening price equals the preceding close; the driver explicitly declares that synthetic execution proxy. Each attempt occurs in the next valid session, at or just after 09:30 New York. No same-close fills or future closes influence decisions/sizing. The last trial close is marked, not used to manufacture an extra fill outside the 30-session window.
- Synthetic EUR_PER_USD cycles from 0.98 to 1.00, available at each simulated opening/closing valuation. Conversion uses the existing Decimal FX functions and 60-second freshness policies. No real or executable FX rate is implied.
- Existing ATR sizing uses a 1.5 ATR stop distance, 1% risk budget and 20% position budget; portfolio-aware `size_pretrade_buy` then reduces quantity or rejects against the unchanged aggregate gate. Limits remain 20% per position, 80% invested, 20% minimum cash, 1% position stop risk and 4% aggregate stop risk. All entry/exit commission and slippage assumptions are explicitly zero.
- Fixed canonical ticker order; no top-ups. SELL proposes only a full existing long position, never a short. No discretionary trades are inserted. An unfilled staged attempt is explicitly cancelled under the existing lifecycle so it cannot silently reserve future risk assumptions. A later signal can create a separately identified proposal; no rejected fill is rewritten as successful.
- Separate fresh strict temporary ledgers use `PaperBroker.execute_gated`, exact state hashes and full pending/holdings coverage. Every new fill passes existing transactional integrity, FX and risk checks. Authorization for this finite synthetic run came from the operator's Sprint 1Y instruction; this test driver is not a replacement workflow-authorization service.

## Comparison

Trade count means executed whole-order fills, not signals or round trips. Values below retain fractional EUR precision from the ledger; no cent-rounding policy has been added.

| Metric | Baseline | Bear-filtered | Cash benchmark |
|---|---:|---:|---:|
| Starting equity EUR | 10,000 | 10,000 | 10,000 |
| Final marked equity EUR | 10,595.60 | 10,217.035 | 10,000 |
| Total return | 5.956% | 2.17035% | 0% |
| Maximum close-to-close drawdown | 6.008739% | 0% | 0% |
| Final cash EUR | 4,139.60 | 10,217.035 | 10,000 |
| Final marked exposure EUR | 6,456 | 0 | 0 |
| Realized P&L EUR | 0 | 217.035 | 0 |
| Unrealized P&L EUR | 595.60 | 0 | 0 |
| Candidate proposals | 46 | 2 | 0 |
| Executed fills | 3 BUY, 0 SELL | 1 BUY, 1 SELL | 0 |
| Rejected candidates | 43 | 0 | 0 |
| BUY / HOLD / SELL signal counts | 5 / 64 / 111 | 1 / 68 / 111 | N/A |
| Operational integrity failures | 0 | 0 | N/A |

Baseline finishes holding **22 AAPL, 21 JPM and 22 MSFT**, with cost bases EUR 1,983.52, EUR 1,893.36 and EUR 1,983.52 respectively. Bear-filtered bought and later sold 21 JPM and finishes flat. SELL conditions for unheld stocks were recorded but produced no proposal. All 60 daily portfolio reconciliations and operational monitoring checks passed.

**The unchanged SELL restriction materially prevents liquidation.** Baseline recorded **42 SELL gate rejections** and one BUY rejection during portfolio-aware sizing. SELLs were rejected when another held position's stop was at/above its current mark, or when remaining positions breached concentration/stop-risk/aggregate-risk limits. No gate was bypassed. The baseline's positive final marked value is not realized proceeds or evidence that those positions could be liquidated under the current policy.

Limits govern execution eligibility: subsequent market marks can move a portfolio outside a limit, and this experiment has no automatic remediation exception. Expected policy rejections are distinct from implementation/control failures. Stops are **risk assumptions only**, not executed orders; crossing one does not cause a stop fill. No terminal liquidation, forced exit, trailing stop, split/dividend accounting, liquidity/spread or realistic cost model was added. Kill switch/latch stayed inactive; new fills retained their checks, but this price-path trial did not deliberately activate or release them. Existing regression tests cover those controls separately.

## Daily marked equity comparison (EUR)

The cash-only benchmark is EUR 10,000 every day. Complete daily financial/control records and rejected-proposal evidence are in the JSON, not just the equity series below.

| Session | Baseline | Bear-filtered |
|---|---:|---:|
| 2020-10-08 | 10084.28 | 10041.16 |
| 2020-10-09 | 10025.96 | 10092.40 |
| 2020-10-12 | 10225.13 | 10206.43 |
| 2020-10-13 | 10211.09 | 10217.035 |
| 2020-10-14 | 10218.60 | 10217.035 |
| 2020-10-15 | 10052.92 | 10217.035 |
| 2020-10-16 | 10344.115 | 10217.035 |
| 2020-10-19 | 10441.94 | 10217.035 |
| 2020-10-20 | 10562.325 | 10217.035 |
| 2020-10-21 | 10573.60 | 10217.035 |
| 2020-10-22 | 10424.34 | 10217.035 |
| 2020-10-23 | 10392.38 | 10217.035 |
| 2020-10-26 | 10359.77 | 10217.035 |
| 2020-10-27 | 10326.51 | 10217.035 |
| 2020-10-28 | 10292.60 | 10217.035 |
| 2020-10-29 | 10105.84 | 10217.035 |
| 2020-10-30 | 10072.255 | 10217.035 |
| 2020-11-02 | 10038.02 | 10217.035 |
| 2020-11-03 | 10003.135 | 10217.035 |
| 2020-11-04 | 9967.60 | 10217.035 |
| 2020-11-05 | 9938.26 | 10217.035 |
| 2020-11-06 | 9968.83 | 10217.035 |
| 2020-11-09 | 10166.72 | 10217.035 |
| 2020-11-10 | 10368.30 | 10217.035 |
| 2020-11-11 | 10483.60 | 10217.035 |
| 2020-11-12 | 10505.68 | 10217.035 |
| 2020-11-13 | 10582.485 | 10217.035 |
| 2020-11-16 | 10659.74 | 10217.035 |
| 2020-11-17 | 10627.995 | 10217.035 |
| 2020-11-18 | 10595.60 | 10217.035 |

## Verification and reproduction

Focused command: `uv run --no-sync pytest -q tests/test_synthetic_portfolio_experiment.py` — **10 passed in 50.92 seconds**. Tests cover shared sessions, accounting/P&L identities, no shorts, later-session execution, all three signal states, retained SELL rejections, future-price isolation, drawdown/return calculations and exact deterministic replay of the complete experiment. Network/credential entry points are guarded, and protected files/artifacts are hash-checked without printing secrets. Initial fixture metadata/time-bound failures were fixed in the new test driver; production validation was not changed.

Full command: `uv run --no-sync pytest -q` — **1,276 passed in 265.41 seconds**, preserving all 1,266 baseline tests plus 10 new tests. Tests used existing uv dependencies without synchronization and only disposable ledgers. Final protected-file and all five Sprint 1V artifact hashes match their pre-run values; no files are staged.

Reproduce in memory: `from tests.synthetic_portfolio_experiment import run_experiment; report = run_experiment()`. The function removes its temporary ledgers before returning. The separately saved JSON contains invented results only; saving it was an exclusive new-file operation, not an overwrite of any prior artifact. No database from Sprint 1V is opened by the harness. No broker/risk/FX/strategy production module, dependency, .env or protected document/script was changed. No network, commits or pushes. Stop for independent review.
