"""All-or-nothing completed-session research pipeline. No paper broker imports."""

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3

from models.daily_signals import (
    DAILY_UNIVERSE, DailyDecision, DailySignalInputs, DailySignalReport,
    DailyStrategyConfiguration, ObservedTicker, SessionSchedule,
)
from providers.daily_ohlcv_provider import DailyOHLCVProvider
from tools.historical_snapshot import (
    EnvironmentRecord, FrozenModel, HistoricalSnapshot, _read_json, canonical_json, capture_environment, input_hash,
)
from tools.historical_signals import generate_mean_reversion_exits
from tools.market_regimes import MarketRegime, classify_market_regime, filter_entries_by_regime
from tools.quantitative_pipeline import evaluate_mean_reversion


def capture_daily_environment() -> EnvironmentRecord:
    base = capture_environment()
    root = Path(__file__).resolve().parents[1]
    digest = sha256(base.execution_source_sha256.encode('ascii'))
    for name in ('models/daily_signals.py', 'providers/daily_ohlcv_provider.py',
                 'tools/daily_signal_pipeline.py', 'tools/historical_data.py',
                 'tools/historical_signals.py', 'tools/quantitative_pipeline.py',
                 'tools/quantitative_signals.py', 'tools/market_indicators.py', 'tools/market_regimes.py'):
        digest.update(name.encode('utf-8') + b'\0' + (root / name).read_bytes() + b'\0')
    return base.model_copy(update={'execution_source_sha256': digest.hexdigest()})


def freeze_daily_inputs(schedule: SessionSchedule, observed: tuple[ObservedTicker, ...], *,
                        decision_at: datetime) -> DailySignalInputs:
    snapshot = HistoricalSnapshot(schema_version=1, tickers=tuple(o.snapshot for o in observed))
    return DailySignalInputs(
        schema_version=1, schedule=schedule, schedule_sha256=input_hash(schedule),
        snapshot=snapshot, snapshot_sha256=input_hash(snapshot), observed=observed,
        configuration=DailyStrategyConfiguration(), decision_at=decision_at,
        environment=capture_daily_environment(),
    )


def load_daily_inputs(path: str | Path, *, expected_sha256: str) -> DailySignalInputs:
    inputs = DailySignalInputs.model_validate(_read_json(path))
    if input_hash(inputs) != expected_sha256:
        raise ValueError('Daily input hash mismatch')
    return inputs


def replay_daily_signals(inputs: DailySignalInputs, *, expected_sha256: str) -> DailySignalReport:
    inputs = DailySignalInputs.model_validate(inputs.model_dump(mode='json'))
    if input_hash(inputs) != expected_sha256:
        raise ValueError('Daily input hash mismatch')
    environment = capture_daily_environment()
    for field in ('code_commit', 'execution_source_sha256', 'python_version', 'dependency_versions'):
        if getattr(environment, field) != getattr(inputs.environment, field):
            raise ValueError(f'Daily replay environment mismatch: {field}')
    decisions = []
    signal_date = inputs.snapshot.tickers[0].bars[-1].date
    for ticker in inputs.snapshot.tickers:
        highs = tuple(b.high for b in ticker.bars)
        lows = tuple(b.low for b in ticker.bars)
        closes = tuple(b.close for b in ticker.bars)
        entry, atr = evaluate_mean_reversion(ticker.ticker, highs, lows, closes)
        exit_signal = generate_mean_reversion_exits(closes)[-1]
        regime = classify_market_regime(highs, lows, closes)
        filtered = filter_entries_by_regime([entry.triggered], [regime], {MarketRegime.BEAR})[0]
        for variant, entry_signal in (('baseline', entry.triggered), ('bear_filtered', filtered)):
            decision = 'SELL' if exit_signal else 'BUY' if entry_signal else 'HOLD'
            decisions.append(DailyDecision(
                ticker=ticker.ticker, variant=variant, decision=decision, signal_date=signal_date,
                decision_at=inputs.decision_at, entry_signal=entry_signal, exit_signal=exit_signal,
                atr=atr, regime=regime,
            ))
    return DailySignalReport(
        schema_version=1, inputs_sha256=expected_sha256, snapshot_sha256=inputs.snapshot_sha256,
        schedule_sha256=inputs.schedule_sha256, configuration_sha256=input_hash(inputs.configuration),
        configuration=inputs.configuration, signal_date=signal_date, decision_at=inputs.decision_at,
        decisions=tuple(decisions), disclosures=(
            'Position-independent research conditions, not order instructions; SELL does not imply a holding.',
            'USD stock prices and EUR broker cash are separate; FX is unimplemented and order submission is prohibited.',
            'Both baseline and BEAR-filtered mean reversion reuse fixed V1 parameters.',
            'Only final, available candles from completed scheduled sessions are used; all six tickers must pass.',
            'Frozen schedule accuracy and provider finality are external attestations, not proof against later data revisions.',
            'Dividends are recorded, not modeled as performance; no trading or investment-edge claim.',
        ),
    )


class DailySignalStore:
    """A separate SQLite file, atomically storing one complete frozen run per ID."""

    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(str(path), isolation_level=None, timeout=10)
        self._db.execute('PRAGMA foreign_keys=ON')
        app_id = 0x4C4C4453
        try:
            self._db.execute('BEGIN IMMEDIATE')
            app = self._db.execute('PRAGMA application_id').fetchone()[0]
            version = self._db.execute('PRAGMA user_version').fetchone()[0]
            tables = self._db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not tables and app == 0 and version == 0:
                self._db.execute('''CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY, inputs_sha256 TEXT NOT NULL, report_sha256 TEXT NOT NULL,
                    signal_date TEXT NOT NULL, decision_at TEXT NOT NULL,
                    inputs_json TEXT NOT NULL, report_json TEXT NOT NULL)''')
                self._db.execute(f'PRAGMA application_id={app_id}')
                self._db.execute('PRAGMA user_version=1')
            elif app != app_id or version != 1:
                raise ValueError('Not a supported daily-signal ledger')
            # Additive metadata extension; existing 1B rows remain unverified.
            self._db.execute('''CREATE TABLE IF NOT EXISTS run_verification (
                run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
                verification_sha256 TEXT NOT NULL, verification_json TEXT NOT NULL)''')
            self._db.execute('COMMIT')
        except BaseException:
            if self._db.in_transaction:
                self._db.execute('ROLLBACK')
            self._db.close()
            raise

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def publish(self, run_id: str, inputs: DailySignalInputs, *, verification: FrozenModel | None = None) -> DailySignalReport:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError('Nonempty stable run ID required')
        report = replay_daily_signals(inputs, expected_sha256=input_hash(inputs))
        values = (input_hash(inputs), input_hash(report), report.signal_date.isoformat(),
                  report.decision_at.isoformat(), canonical_json(inputs), canonical_json(report))
        metadata = None if verification is None else (input_hash(verification), canonical_json(verification))
        self._db.execute('BEGIN IMMEDIATE')
        try:
            old = self._db.execute('SELECT inputs_sha256,report_sha256,signal_date,decision_at,inputs_json,report_json FROM runs WHERE run_id=?', (run_id,)).fetchone()
            if old is not None:
                if old != values:
                    raise ValueError('Run ID conflicts with existing frozen inputs/results')
                old_metadata = self._db.execute('SELECT verification_sha256,verification_json FROM run_verification WHERE run_id=?', (run_id,)).fetchone()
                if old_metadata != metadata:
                    raise ValueError('Run ID conflicts with existing verification metadata')
            else:
                self._db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)', (run_id, *values))
                if metadata is not None:
                    self._db.execute('INSERT INTO run_verification VALUES (?,?,?)', (run_id, *metadata))
            self._db.execute('COMMIT')
        except BaseException:
            self._db.execute('ROLLBACK')
            raise
        return report

    def load_verification(self, run_id: str) -> tuple[str, str]:
        """Read integrity-checked metadata; authority must be checked externally."""
        row = self._db.execute('SELECT verification_sha256,verification_json FROM run_verification WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise ValueError('Run has no strict verification metadata')
        if sha256(row[1].encode('utf-8')).hexdigest() != row[0]:
            raise ValueError('Stored verification integrity mismatch')
        return row

    def load(self, run_id: str, *, expected_sha256: str) -> tuple[DailySignalInputs, DailySignalReport]:
        row = self._db.execute('SELECT inputs_sha256,report_sha256,inputs_json,report_json,signal_date,decision_at FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        inputs = DailySignalInputs.model_validate_json(row[2])
        report = DailySignalReport.model_validate_json(row[3])
        if input_hash(inputs) != row[0] or row[0] != expected_sha256 or input_hash(report) != row[1]:
            raise ValueError('Stored daily-run integrity mismatch')
        if (report.signal_date.isoformat(), report.decision_at.isoformat()) != row[4:]:
            raise ValueError('Stored daily-run metadata mismatch')
        replayed = replay_daily_signals(inputs, expected_sha256=expected_sha256)
        if canonical_json(replayed) != canonical_json(report):
            raise ValueError('Stored decisions do not match frozen replay')
        return inputs, report


def ingest_daily_signals(provider: DailyOHLCVProvider, schedule: SessionSchedule, *,
                         store: DailySignalStore, run_id: str,
                         decision_at: datetime | None = None, clock=None) -> DailySignalReport:
    """Explicit ingestion; fixed as-of time is for already observed/offline data.

    Otherwise sample the clock after fetching, so network retrieval cannot be
    falsely recorded as known before the fetch. Crossing a session close during
    ingestion fails completeness checks rather than publishing a stale batch.
    """
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    schedule = SessionSchedule.model_validate(schedule.model_dump(mode='json'))
    completed = schedule.completed_sessions(decision_at if decision_at is not None else clock())
    if len(completed) < 200:
        raise ValueError('At least 200 completed sessions required')
    observed = []
    for ticker in DAILY_UNIVERSE:
        try:
            fetched = provider.fetch_daily(ticker, completed)
            if fetched.snapshot.ticker != ticker:
                raise ValueError('Provider returned a different ticker identity')
            observed.append(fetched)
        except Exception as exc:
            raise RuntimeError(f'Daily provider failed for {ticker}') from exc
    inputs = freeze_daily_inputs(schedule, tuple(observed),
                                decision_at=decision_at if decision_at is not None else clock())
    return store.publish(run_id, inputs)
