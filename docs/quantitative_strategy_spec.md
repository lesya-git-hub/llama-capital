
# Llama Capital — Quantitative Strategy Specification

Status: Draft v0.1
Purpose: Define three independent asset-discovery strategies.

## 1. Emerging Opportunities

Discovery:
- News and sentiment analysis
- Structural demand growth
- Financial fundamentals
- New technologies and market opportunities

Validation:
- Verify evidence and source dates
- Examine liquidity and price history
- Evaluate valuation where applicable
- Reject unsupported growth narratives

Output: RESEARCH_CANDIDATE or REJECTED

## 2. Mean Reversion

Initial parameters:
- SMA period: 50 trading sessions
- Price deviation: at least 5% below SMA50
- RSI period: 14
- ATR period: 14

Screening condition:
Close <= 0.95 * SMA50

Confirmation hypothesis:
RSI crosses above 30 after an oversold period.

Exit hypothesis:
Price returns towards SMA50.

Risk:
ATR-based stop, initially 1.5 * ATR.

Note:
A price below its moving average does not establish
fundamental undervaluation.

## 3. Trend Breakout

Initial parameters:
- Donchian lookback: 20 completed trading sessions
- Volume lookback: 20 completed trading sessions
- Volume multiplier: 1.5
- ATR period: 14

Screening condition:
Close[t] > max(High[t-20:t])

Confirmation:
Volume[t] > 1.5 * mean(Volume[t-20:t])

Exit hypothesis:
ATR-based trailing stop.

Note:
Exclude the current session from Donchian and
historical volume calculations to prevent look-ahead bias.

## Shared Requirements

- Signals must be deterministic and reproducible.
- Indicators use completed candles only.
- Each signal records asset, timestamp, strategy,
  parameters, data source and supporting evidence.
- Strategies must be tested independently.
- Backtests must include transaction costs and slippage.
- No automatic live orders without risk approval.
- Paper trading precedes any live deployment.
- All numerical thresholds are hypotheses requiring
  out-of-sample validation.
