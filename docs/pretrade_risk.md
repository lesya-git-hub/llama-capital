# Sprint 1E: advisory portfolio risk engine

Baseline inspected: `afdaea3`, 604 existing tests. Research and simulation only.
The limits are provisional research assumptions, not evidence of safety or profit.

## Architecture assessment

`providers/paper_broker.py` maintains a EUR cash/holdings ledger using Decimal
and explicit whole-order lifecycle transitions. CREATED and ACCEPTED orders
reserve neither cash nor shares. FILLED, REJECTED and CANCELLED are terminal;
fills recheck resources transactionally. Portfolio positions retain cost basis,
not current market value. A broker portfolio alone cannot supply marked equity.

`tools/risk_manager.py` sizes whole-share long positions with ATR-derived stops,
the minimum of position/risk budgets and floor rounding. `tools/portfolio_risk.py`
checks aggregate exposure/risk for a precomputed V1 plan. The V1 portfolio
simulator marks holdings and executes its own fixed strategy/accounting semantics;
it does not enforce this sprint's aggregate risk policy. Those modules, signals,
strategy variants, broker lifecycle and simulator semantics remain unchanged.

`tools/pretrade_risk.py` adds pure portfolio-wide evaluation, rather than an
execution gateway or replacement simulator. It uses the existing frozen-model,
canonical JSON and input-hash patterns. Fixed-precision Decimal arithmetic is
isolated from caller context. There is no database connection, broker object,
order mutation, network call, live FX source or automatic scheduler.

## Required inputs

- `RiskConfiguration`: schema/version, starting-capital metadata (EUR 10,000),
  single-position limit 20%, invested limit 80%, cash floor 20%, position stop-risk
  limit 1%, aggregate stop-risk limit 4%. Limits are configurable. The caller must
  explicitly set `max_age_seconds`; no valuation freshness policy is guessed.
  Zero cash reserve is allowed for research comparisons; no borrowing/short
  configuration exists. Starting capital never replaces actual marked equity.
- `ValuationSnapshot`: synthetic scope, source and snapshot ID, timestamp,
  unreserved ledger cash, existing positive whole-share holdings, current
  timestamped marks, explicit existing stops, estimated stop-exit costs,
  outstanding orders and previously evaluated proposal IDs. The caller supplies
  a complete consistent snapshot; no broker read adapter guesses missing prices,
  stops, pending orders or history. Its currency labels every valuation/risk amount.
- `Proposal`: stable ID, ticker, BUY/SELL, positive whole shares, reference entry
  (or sale) price, explicit stop, total commission, adverse per-share slippage,
  total planned exit commission, adverse per-share exit slippage and currency.
  Prices/costs have at most 12 fractional places; finite amounts and valid long
  stops are required. All estimated costs must be supplied, even when zero.

Only explicit synthetic EUR valuation and order amounts are accepted. USD or
mixed-currency inputs return CURRENCY_MISMATCH. No conversion object or live FX
path is implemented: callers may supply reviewed EUR synthetic fixtures, never
silently relabel US-stock USD prices. Synthetic scope/source are declarations,
not cryptographic authentication or evidence of real market prices.

Missing/nonfinite/negative structural inputs raise validation errors before a
decision can be evaluated. Structurally valid but unsafe inputs (e.g. missing
marks, stale data, FX mismatch, oversell or limits) return REJECTED with explicit
reason codes. Missing metrics remain null rather than fabricated. Timestamps
must be timezone aware; marks must be no newer than the snapshot and every mark
and snapshot must satisfy the caller's age limit. Duplicate ticker/order IDs
within the snapshot are invalid. An outstanding entry represents only CREATED
or ACCEPTED; callers exclude terminal orders rather than resetting their state.

## Conservative projection policy

Current equity is unreserved cash plus current mark times held shares, with no
use of entry-cost valuation. Pending BUYs are treated as fully consuming cash,
marked exposure and stop-risk capacity, including commission and adverse entry
slippage. Pending SELLs reserve currently held shares, never potential shares
from unfilled BUYs. They do not credit proceeds or release concentration/risk
capacity. If a pending SELL's commission exceeds adverse proceeds, that net cash
cost is reserved. Oversubscribed pending SELLs reject the evaluation.

A proposed SELL must fit holdings after all pending SELL reservations. Its own
projected proceeds use adverse execution less commission. It reduces only the
existing held tranche; pending BUY risk remains intact. Remaining held shares
retain their full planned exit commission (a fixed fee). Existing and proposed
BUY tranches may have different explicit stops; risk is summed by ticker rather
than overwriting the existing stop. No stop is inferred from ATR or elapsed time.

Existing planned risk is quantity times (current mark minus stop plus adverse
stop slippage), plus planned exit commission. New BUY risk uses the greater of
adverse entry and current mark, minus explicit stop, plus stop slippage; entry
and exit commissions are included. This conservatively measures both entry risk
and remaining marked downside. A stop at/above the current mark or an adverse
stop execution at/below zero rejects. Stop gaps and liquidity can cause losses
beyond these planned estimates; stops do not guarantee bounded loss.

Projected equity uses cash plus projected marked holdings. Limit denominators
use the smaller of current and projected equity so hypothetical favorable trade
prices cannot create capacity. `limit_equity` records that denominator explicitly.
Costs and adverse price differences can therefore reduce the permissible limits.
All holdings and all BUY tranches count toward individual/aggregate risk and
exposure, not only the proposed ticker. No negative cash, negative holdings,
shorts, borrowing or margin are permitted.

The entire projected portfolio must meet every limit for either side. A
risk-reducing SELL can still be rejected if another limit remains breached; no
remediation exception or liquidation policy has been implicitly authorized.

`size_pretrade_buy` returns the largest approved whole-share quantity up to the
explicit proposal quantity cap, using the same whole-share budget convention as
V1 while evaluating all portfolio constraints and explicit costs. It searches
the monotone conservative BUY approval boundary with integer bisection; it does
not synthesize ATR or invoke the float-based V1 strategy. If one share fails it
returns zero and that rejection audit; it never returns an approved zero order.

## Audit and repeatability

`evaluate_pretrade(snapshot, proposal, configuration, evaluated_at=explicit_time)`
returns a frozen serializable `RiskDecision`, including current/projected equity,
invested exposure, cash/reserve fractions, per-ticker concentration and planned
risk, decision/reason codes, all input identities/hashes, configuration version,
evaluation time and engine source hash. Amounts use decimal strings in canonical
JSON. Reasons have stable code prefixes and explanatory text. Input ticker/order
collections and decimal representations are normalized for deterministic hashes.

Serialize with existing `canonical_json(decision)` and identify with
`input_hash(decision)`. Preserve exact snapshot, proposal, configuration,
evaluation timestamp, code and dependency environment separately for replay;
hashes alone do not reconstruct missing inputs. Reevaluation with those inputs
reproduces the audit. No additional mutable audit store is introduced.

The repeated-proposal mechanism uses a stable caller-controlled proposal ID
checked against pending IDs and caller-maintained prior-proposal IDs. An exact
retry against the same frozen inputs yields the same decision. Different IDs
may represent intentional repeated economics, but all outstanding resource use
must still be included. Snapshot/ID hashes establish integrity, not truthfulness
or a guarantee that outstanding-order history is complete.

## Execution integration remains a future sprint

APPROVED is advisory: evaluation neither reserves resources nor creates, accepts,
fills or cancels orders. Portfolio state can change immediately afterward. Two
approvals against the same snapshot do not enforce limits on their combined
execution. Future integration needs an atomic state/version check, complete
pending-order capture, serialized evaluation/reservation, explicit idempotency
storage and resource rechecks at execution. This sprint does not alter the
broker's acceptance-time reservation semantics or connect signals to orders.

Implementation stops for review. No external data, dependency installation,
FX conversion, commits, pushes or tags were used. The pre-existing changes to
`scripts/sec_match_recon.py` were left untouched.

## Validation

Synthetic tests cover exposure boundaries, cash reserve, position and aggregate
stop risk, whole-share sizing, BUY/SELLs and oversells, duplicates, CREATED and
ACCEPTED pending orders, commissions/slippage, retained exit fees, stale/missing
marks, currency mismatches, invalid numerics, canonical replay, caller decimal
context isolation and unchanged input snapshots.

- Focused run: `uv run --no-sync pytest -q tests/test_pretrade_risk.py tests/test_portfolio_risk.py tests/test_risk_manager.py tests/test_paper_broker.py`
  passed 97 tests before the final additional zero-equity case/refinements.
- Final full run: `uv run --no-sync pytest -q` passed **640 tests**, comprising
  all 604 existing tests and 36 new risk-engine cases, in 22.73 seconds.
- `git diff --check` passed. Test runs required access outside the filesystem
  sandbox for uv's cache; no dependency synchronization or installation occurred.
