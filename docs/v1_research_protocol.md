# Llama Capital V1 research protocol

Protocol version: 1. Scope: research-only software. Audit baseline: `d41c507`.
This protocol describes existing rules; it does not establish that those rules
were frozen before historical results were inspected. It takes precedence over
the older draft strategy specification for V1 release scope.

## Supported hypothesis

V1's supported historical hypothesis is mean reversion: close at or below 95%
of SMA50, with prior RSI14 below 30 and current RSI14 at least 30. RSI and ATR
use the implemented Wilder smoothing. Entry/exit signals use completed candles.
Entries and signal exits execute at the next session's open.

The signal exit is close at or above SMA50. An entry uses prior-session ATR14
and a fixed stop at slipped entry price minus 1.5 ATR. A subsequent opening
price at or below the stop exits at that open; otherwise a low at or below the
stop exits at the stop reference price with exit slippage/fees. Entry-day stops
are supported. Gap stops take precedence over simultaneous signal exits;
opening exits take precedence over intraday stops. No same-ticker re-entry
occurs on an opening-exit session. Stops do not trail. One long position per
ticker, whole shares, full exits, no leverage or shorting, no forced terminal
liquidation. Without ATR, generic replay is possible but does not implement
the complete supported mean-reversion risk configuration.

Trend-breakout signal utilities exist; their presence and tests do not constitute
a V1 validated breakout trading strategy. The draft trailing-stop hypothesis is
not implemented and is outside this release's historical evaluation scope.

## Universe, capital, costs and risk

The legacy historical universe is MSFT, AAPL, JPM, XOM, JNJ and WMT. It is a
fixed six-stock case study, not a point-in-time representative universe. There
is no delisting treatment, randomized selection, or demonstrated protection
against selection/survivorship bias. Synthetic gate tickers are test data only.

The reference starting capital is 10,000 currency units. Each legacy stock
simulation starts with its own 10,000; a shared-capital portfolio starts with
one 10,000 balance. Snapshot currency must match capital currency for every
ticker. US-dollar price data cannot be labeled euro returns without FX modeling.

Default per-entry maximum position fraction is 20%, risk budget 1%, ATR
multiplier 1.5, fee rate 0.001 per side and slippage rate 0.001 per side. Buy
cost is quantity × open × (1 + slippage) × (1 + fee); sale proceeds are quantity
× reference exit × (1 - slippage) × (1 - fee). Both costs are already reflected
in cash and net P&L; they are not deducted again in reporting.

The single-stock simulator sizes using available cash. The portfolio simulator
uses opening equity for risk/position budgets, capped by available cash including
entry costs. All opening exits precede alphabetical entries; later candidates
receive remaining cash. Equity is re-marked after each fill. Intraday proceeds
cannot finance opening entries. There is no aggregate stop-risk/exposure cap,
correlation control, sector limit or guaranteed loss ceiling. Limits apply when
entering, not continuously after market moves. The separate portfolio approval
utility is not connected to replay. Gaps and costs may exceed nominal risk.

All effective settings are frozen in each experiment. Changes create a new
experiment identity and must not be presented as a repeat of an earlier run.
This protocol does not authorize parameter optimization.

## Warmup and market regimes

Mean-reversion entries become evaluable with 51 observations, SMA exits with
50, and regimes with 200. The development scripts begin loading at 2020-01-01
without preceding history; their initial warmup is part of the supplied equity
period. Preserve that fact when interpreting annualized results.

Baseline accepts unfiltered entries. The comparison variant excludes only
`MarketRegime.BEAR`, keeping the same exits, sizing and costs. Unknown warmup
regimes are allowed by existing filtering. High volatility takes precedence in
classification, so exclusion of BEAR does not exclude every bearish price
configuration. This is a per-stock regime, not a broad-market benchmark regime.

A new holdout-boundary validation requires at least 200 observations before the
first evaluation open when the regime variant is used. The preceding signal
row is retained; it is not a trading session before the evaluation boundary.
Warmup candles may compute indicators, not retrospective cash/trades in a
cash-reset evaluation. The legacy holdout starts loading on 2024-01-01 and
resets each stock to cash at the evaluation boundary, not carried positions.

## Evaluation periods and prior inspection

Development/in-sample period: `[2020-01-01, 2025-01-01)` (2020–2024).
Previously inspected holdout: `[2025-01-01, 2026-11-01)`.
These end dates are exclusive. The latter is not all of calendar 2026 and must
not be described as an untouched holdout or independent final confirmation.
It must not drive optimization or retrospective selection of reported variants.

No fitting stage exists in these fixed-rule scripts; "training" denotes the
development period, not a trained model. First valid holdout execution must
have a preceding signal observation, sufficient history, nonoverlapping periods,
and at least one supplied session within the end-exclusive window. Dates do
not need to fall on exchange sessions, but supplied-session completeness must
be assessed separately. A passing boundary check does not certify data coverage.

No new evaluation, future holdout, or strategy ranking is performed in this
release audit. An independent future evaluation requires a separately recorded
protocol before inspecting those future outcomes.

## Data and reporting conventions

The supported release path is frozen snapshot → versioned experiment → verified
offline replay → deterministic report. See [reproduction](v1_reproduce.md).
Raw download scripts are exploratory legacy entry points, not replay artifacts.
They have no archived data identity and the holdout script lacks defensive
checks for empty/insufficient history; do not use it as the release gate.

Snapshots preserve session dates, OHLCV, identity, currency, source/calendar
labels, adjustment metadata, dividends and split ratios. Replay accepts
split-adjusted candles without applying an additional split, or unadjusted
candles without split events. It rejects dividend-adjusted prices and unadjusted
split events. Dividends are recorded but excluded from cash and performance.
This is price-return research, not total-return accounting. Metadata correctness
and corporate-action basis remain input-producer responsibilities.

Equity metrics use the combined portfolio curve; independent-stock averages
are not shared-capital metrics. Sharpe assumes zero risk-free rate, annualization
252 sessions/year, and volatility is sample-based. With only two observations,
volatility is reported as zero and Sharpe undefined by existing convention;
that is not evidence of low risk. Open holdings are marked at final close
without liquidation costs. Unrealized P&L includes entry costs. Expectancy uses
only completed trades; its percentage is an unweighted per-trade mean.

Fills are idealized, with no spread dynamics, participation limits, partial fills,
halts, taxes or financing model. No claim of investable returns or profitability
follows from a backtest, software gate, or this protocol.
