# Offline portfolio research, version 1

`tools.portfolio_research` connects the frozen snapshot contract to the existing
shared-capital simulator. It does not generate signals, download data, tune
parameters, or implement an evaluation registry or release gate.

## Inputs and identity

`PortfolioExperiment` requires `schema_version: 1`,
`experiment_type: "offline_portfolio"`, a complete `HistoricalSnapshot`, its
canonical SHA-256, one common capital currency, exactly one `FrozenSignals`
record per snapshot ticker, all effective execution parameters, provenance,
`return_basis: "price_return_excluding_dividends"`, and
`entry_priority: "alphabetical"`.

Each signal record contains ticker, a nonempty signal description, entry and
exit booleans for every session, and explicit ATR (`null` for no ATR, otherwise
one value per session). ATR values must be finite and positive when present;
executable entry signals require a value. ATR warmup nulls are permitted.
Signal provenance and avoidance of future-data leakage remain the producer's
responsibility; replay freezes supplied signals without regenerating them.

The 20B snapshot validator enforces identical ordered dates and named calendars.
Every ticker currency must equal the declared capital currency: there is no FX
conversion. Corporate-action compatibility follows 20B independently per ticker:
split-adjusted prices pass through unchanged; unadjusted prices are allowed only
without split events; dividend-adjusted prices are rejected. No cross-ticker
price rescaling is inferred. The complete per-ticker adjustment declarations
remain in the embedded, hashed snapshot.

Signal records are sorted by ticker before hashing, as snapshot tickers already
are. Their ordering in JSON does not change experiment identity. Parameters,
signal contents/descriptions, snapshot metadata/data, currency, priority, and
provenance all contribute to the experiment SHA-256. A changed valid configuration
is a different experiment, not a replay of the original.

Portfolio provenance extends the unchanged 20B environment record by hashing
the portfolio simulator and integration/report module in addition to 20B's
execution-source fingerprint. Replay checks commit, source fingerprint, Python
patch version, and recorded dependency versions. Unrelated dirty-tree status is
recorded but need not match. SHA-256 provides integrity, not authentication.

## Python API

```python
from pathlib import Path
from tools.historical_snapshot import load_snapshot, canonical_json, input_hash
from tools.portfolio_research import (
    FrozenSignals, freeze_portfolio_experiment,
    load_portfolio_experiment, replay_portfolio_experiment,
)

snapshot = load_snapshot("frozen_snapshot.json")
# Build one FrozenSignals per ticker from the recorded signal artifact.
# Each record supplies ticker, signal_description, entry_signals,
# exit_signals, and atr_values; lengths must match the snapshot's sessions.
signals = tuple(FrozenSignals.model_validate(record) for record in recorded_signals)
experiment = freeze_portfolio_experiment(
    snapshot, signals, currency="EUR", initial_cash=10000,
)
experiment_hash = input_hash(experiment)  # Preserve separately for later verification.
Path("portfolio_experiment.json").write_text(canonical_json(experiment), encoding="utf-8")

loaded = load_portfolio_experiment(
    "portfolio_experiment.json", expected_sha256=experiment_hash,
)
report = replay_portfolio_experiment(loaded, expected_sha256=experiment_hash)
Path("portfolio_report.json").write_text(canonical_json(report), encoding="utf-8")
report_hash = input_hash(report)
```

File writes above are explicit caller actions; freeze/load/replay functions do
not persist files or fetch external data. Replay revalidates even an in-memory
experiment and checks the supplied expected experiment hash before simulation.
Use `UV_NO_SYNC=1` in the shell environment when running `uv run pytest -q`.

## Deterministic report

`PortfolioResearchReport` includes experiment/snapshot/per-ticker signal hashes,
currency, provenance, effective execution parameters, alphabetical priority,
dated combined portfolio equity, initial and final capital, final cash and
marked holdings, realized/unrealized P&L, metrics, dated completed trades with
full reused accounting records, and marked open positions with cost basis/stops.
It has no generated timestamp or random ID. Canonical report bytes are stable
for the same experiment and supported environment.

Ending capital is marked portfolio equity, not liquidation proceeds:

```text
ending_capital = ending_cash + marked_holdings_value
ending_capital = starting_capital + realized_pnl + unrealized_pnl
```

Unrealized P&L is final closing value minus entry cost basis, including slipped
entry price and entry fee. Completed trade net P&L includes entry and exit costs.
`incurred_execution_costs` sums completed-trade costs and open-position entry
costs; it is informational and is not deducted again from equity. Execution
price fields retain simulator raw/reference prices, with slippage represented
through accounting costs. All money fields use the one declared currency.

Return, annualized return, maximum drawdown, volatility, and Sharpe come directly
from the simulator's combined equity curve, never averages of ticker metrics.
Trade expectancy is a pooled completed-trade statistic. Flat/no-trade conventions
and short-history handling remain those of the simulator.

## Disclosures and limits

Every report discloses that there is no aggregate portfolio risk/exposure cap;
ATR stops are fixed rather than trailing; absent ATR means no stop; dividends
are excluded; execution is idealized; and open holdings exclude liquidation
costs. Opening exits precede opening entries; intraday stop proceeds cannot fund
opening purchases in the same session. No execution logic is duplicated here.

The integration assumes complete daily observations and 252 periods/year,
zero risk-free rate, and truthful adjustment/currency metadata. It does not prove
exchange-session completeness or vendor corporate-action accuracy. Results may
contain open positions. It does not add a per-day cash/position ledger, rejected
entry records, automatic environment repair, total-return accounting, data
acquisition, benchmarks, or Sprint 20D evaluation governance. Synthetic tests
establish accounting and replay behavior, not investment profitability.
