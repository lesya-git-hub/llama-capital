"""RAM-only provisional indicator diagnostics. No acquisition, publication or orders."""
from datetime import date
from typing import Literal

from models.daily_signals import DailyStrategyConfiguration
from providers.alpaca_market_data import AlpacaDailyBatch
from tools.alpaca_data_validation import AlpacaQualityReport, validate_alpaca_batch
from tools.historical_snapshot import FrozenModel
from tools.historical_signals import generate_mean_reversion_exits
from tools.market_regimes import MarketRegime, classify_market_regime, filter_entries_by_regime
from tools.quantitative_pipeline import evaluate_mean_reversion


class ShadowConditions(FrozenModel):
    symbol: str
    sessions: int
    last_session: date
    baseline_entry_condition: bool
    bear_filtered_entry_condition: bool
    exit_condition: bool
    regime: MarketRegime
    atr_usd: float


class ShadowReport(FrozenModel):
    status: Literal['PROVISIONAL'] = 'PROVISIONAL'
    purpose: Literal['unverified_indicator_diagnostics_only'] = 'unverified_indicator_diagnostics_only'
    feed_coverage: Literal['PARTIAL_VENUE_IEX_NOT_CONSOLIDATED'] = 'PARTIAL_VENUE_IEX_NOT_CONSOLIDATED'
    finality: Literal['NOT_ESTABLISHED'] = 'NOT_ESTABLISHED'
    adjustment_correctness: Literal['NOT_ESTABLISHED'] = 'NOT_ESTABLISHED'
    rights_clearance: Literal['UNRESOLVED'] = 'UNRESOLVED'
    order_submission_allowed: Literal[False] = False
    trust_admitted: Literal[False] = False
    configuration: DailyStrategyConfiguration
    quality: AlpacaQualityReport
    conditions: tuple[ShadowConditions, ...]


def analyze_shadow_batch(batch, calendar, *, previous_batches=()) -> ShadowReport:
    """Inspect an already supplied batch; caller must establish rights before real use.

    Uses pure research math, never completed/verified signal-pipeline inputs.
    No result is printed or persisted. History checks cover supplied priors only.
    """
    quality = validate_alpaca_batch(batch, calendar, previous_batches=previous_batches)
    snapshot = AlpacaDailyBatch.model_validate(batch.model_dump(mode='python', warnings=False))
    configuration = DailyStrategyConfiguration()
    if any(len(o.bars) < configuration.minimum_completed_sessions for o in snapshot.observations):
        raise ValueError('SHADOW_REQUIRES_200_SESSIONS_PER_SYMBOL')
    rows = []
    for observation in sorted(snapshot.observations, key=lambda o: o.symbol):
        bars = observation.bars
        highs = tuple(b.high for b in bars)
        lows = tuple(b.low for b in bars)
        closes = tuple(b.close for b in bars)
        entry, atr = evaluate_mean_reversion(observation.symbol, highs, lows, closes)
        exit_condition = generate_mean_reversion_exits(closes)[-1]
        regime = classify_market_regime(highs, lows, closes)
        filtered = filter_entries_by_regime([entry.triggered], [regime], {MarketRegime.BEAR})[0]
        rows.append(ShadowConditions(symbol=observation.symbol, sessions=len(bars),
            last_session=bars[-1].session_date, baseline_entry_condition=entry.triggered,
            bear_filtered_entry_condition=filtered, exit_condition=exit_condition,
            regime=regime, atr_usd=atr))
    return ShadowReport(configuration=configuration, quality=quality, conditions=tuple(rows))
