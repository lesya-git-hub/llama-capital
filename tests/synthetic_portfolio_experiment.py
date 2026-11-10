"""Finite offline experiment driver; invented prices, temporary strict ledgers only."""
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from models.daily_signals import DAILY_UNIVERSE
from providers.alpaca_market_data import AlpacaDailyBar, AlpacaDailyBatch, AlpacaSymbolBars, DailyBarsRequest
from providers.paper_broker import PaperBroker
from tools.alpaca_shadow import analyze_shadow_batch
from tools.fx_conversion import (FXQuote, FXPolicy, USDProposal, USDHolding, USDMark,
    RiskConversionRequest, canonical_quote, convert_risk_inputs, convert, ConversionRequest)
from tools.gated_execution import ExecutionRequest, replay_execution_checks
from tools.historical_snapshot import input_hash
from tools.market_verification import CalendarArtifact, ExchangeSession, ClosedDate, Listing, NEW_YORK
from tools.operational_monitoring import monitor, MonitoringPolicy
from tools.pretrade_risk import RiskConfiguration, size_pretrade_buy
from tools.risk_manager import calculate_risk_plan

D = Decimal
QUANTUM = D('.000000000001')


def decimal_price(value):
    return D(str(value)).quantize(QUANTUM)


def invented_fixture():
    """230 invented weekday sessions; no claim of actual exchange holidays."""
    day, days, sessions, closed = date(2020, 1, 2), [], [], []
    source = 'SPRINT-1Y-INVENTED-CALENDAR'
    while len(days) < 230:
        if day.weekday() < 5:
            days.append(day)
            for exchange in ('XNYS', 'XNAS'):
                sessions.append(ExchangeSession(date=day, exchange=exchange, source=source, version='1',
                    opens_at=datetime.combine(day, time(9, 30), NEW_YORK),
                    closes_at=datetime.combine(day, time(16), NEW_YORK)))
        else:
            for exchange in ('XNYS', 'XNAS'):
                closed.append(ClosedDate(date=day, exchange=exchange, source=source, version='1', reason='weekend'))
        day += timedelta(days=1)
    calendar = CalendarArtifact(schema_version=1, scope='synthetic_test', source=source, version='1',
        available_at=datetime(2019, 1, 1, tzinfo=timezone.utc), coverage_start=days[0], coverage_end=day,
        listings=tuple(Listing(ticker=t, exchange='XNAS' if t in ('AAPL', 'MSFT', 'WMT') else 'XNYS') for t in DAILY_UNIVERSE),
        sessions=tuple(sessions), closed_dates=tuple(closed))
    recovery = list(range(99, 85, -1)) + [92]
    paths = {t: [100] * 230 for t in DAILY_UNIVERSE}
    for ticker in ('AAPL', 'MSFT', 'JPM'):
        paths[ticker][185:200] = recovery
    paths['JPM'][:150] = [60] * 150  # Different long trend, same local recovery condition.
    paths['AAPL'][200:] = [94,96,101,100,100,99,98,97,96,95,94,93,92,91,90,89,88,87,86,85,91,93,96,101,102,101,100,99,98,97]
    paths['MSFT'][200:] = [92,84,82,80,78,76,90,95,101,102,103,102,101,100,99,98,97,96,95,94,93,92,91,90,89,95,99,103,102,101]
    paths['JPM'][200:] = [94,96,101,102,103,104,103,102,101,100,99,98,97,96,95,94,93,92,91,90,89,88,94,98,102,104,103,102,101,100]
    paths['XOM'][200:] = recovery + [94,96,101,102,103,102,101,100,99,98,97,96,95,94,93]
    return calendar, tuple(days), paths


def shadow_at(calendar, days, paths, end):
    request = DailyBarsRequest(start=days[0], end=datetime.combine(days[end], time(16), NEW_YORK), limit=2000,
        expected_session_dates=days[:end+1])
    acquired = datetime.combine(days[end], time(16, 20), NEW_YORK).astimezone(timezone.utc)
    observations = []
    for ticker in DAILY_UNIVERSE:
        bars = []
        for index, day in enumerate(days[:end+1]):
            close = paths[ticker][index]
            opening = paths[ticker][index-1] if index else close
            bars.append(AlpacaDailyBar(timestamp=datetime.combine(day, time(), NEW_YORK).astimezone(timezone.utc),
                session_date=day, open=float(opening), high=float(max(opening, close)+1), low=float(min(opening, close)-1),
                close=float(close), volume=1000., trade_count=100, vwap=float(close)))
        observations.append(AlpacaSymbolBars(symbol=ticker, bars=tuple(bars)))
    batch = AlpacaDailyBatch(request=request, observations=tuple(observations), acquired_start=acquired, acquired_end=acquired,
        session_coverage='CALLER_EXPECTATIONS_MATCHED')
    return analyze_shadow_batch(batch, calendar)


def fx_at(at, rate, identity):
    return canonical_quote(FXQuote(scope='synthetic_test', pair='USD_EUR', direction='EUR_PER_USD',
        rate=rate, effective_at=at, retrieved_at=at, provider_id='INVENTED', dataset_id='1Y', quote_id=identity,
        payload_sha256=sha256(identity.encode()).hexdigest(), price_convention='indicative_mid', provenance='INVENTED TEST ONLY'))


def holdings_from_state(state):
    terms = {h['ticker']: json.loads(h['terms_json']) for h in state['gate_holdings']}
    return tuple(USDHolding(**terms[h['ticker']], quantity=h['quantity']) for h in state['positions'])


def run_experiment():
    """Return daily synthetic records. No saved files except disposable SQLite ledgers."""
    with localcontext() as context:
        context.prec = 50
        return _run()


def _run():
    calendar, days, paths = invented_fixture()
    fixture_hash = sha256(json.dumps({'days': [str(d) for d in days], 'prices': paths}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    reports = [shadow_at(calendar, days, paths, end) for end in range(199, 229)]
    policy, fx_policy = RiskConfiguration(max_age_seconds=60), FXPolicy(max_age_seconds=60)
    result = {'scope': 'synthetic_test', 'warmup_sessions': 200, 'trial_sessions': 30,
        'fixture_sha256': fixture_hash, 'stops': 'RISK_ASSUMPTIONS_ONLY_NOT_EXECUTED',
        'costs': 'EXPLICIT_ZERO', 'rules': 'no topups; SELL full held quantity only; cancel unfilled attempts; no terminal liquidation',
        'portfolios': {}}
    with TemporaryDirectory(prefix='llama-1y-') as folder:
        root = Path(folder)
        for variant in ('baseline', 'bear_filtered'):
            records, peak, max_drawdown = [], D(10000), D(0)
            with PaperBroker(root / (variant + '.sqlite'), initial_cash='10000', strict=True) as broker:
                for trial_index, signal_report in enumerate(reports):
                    index = 200 + trial_index
                    opening_at = datetime.combine(days[index], time(9, 30), NEW_YORK).astimezone(timezone.utc)
                    closing_at = datetime.combine(days[index], time(16), NEW_YORK).astimezone(timezone.utc)
                    signal_at = datetime.combine(days[index-1], time(16, 20), NEW_YORK).astimezone(timezone.utc)
                    assert days[index-1] < days[index] and signal_at < opening_at
                    rate = D('.98') + D('.005') * (trial_index % 5)
                    signals, proposals = [], []
                    for sequence, row in enumerate(signal_report.conditions):
                        ticker = row.symbol
                        entry = row.baseline_entry_condition if variant == 'baseline' else row.bear_filtered_entry_condition
                        side = 'SELL' if row.exit_condition else 'BUY' if entry else 'HOLD'
                        signals.append({'ticker': ticker, 'decision': side, 'signal_date': str(days[index-1]), 'regime': row.regime.value})
                        state = json.loads(broker.execution_state().content)
                        held = next((h for h in holdings_from_state(state) if h.ticker == ticker), None)
                        if side == 'HOLD' or side == 'SELL' and held is None or side == 'BUY' and held is not None:
                            continue
                        at = opening_at + timedelta(seconds=sequence)
                        fx = fx_at(at, rate, f'{index}-open')
                        marks = tuple(USDMark(ticker=t, price=str(paths[t][index-1]), as_of=at) for t in DAILY_UNIVERSE)
                        equity = D(state['account'][0]['cash']) + sum(D(h['quantity']) * D(paths[h['ticker']][index-1]) * rate for h in state['positions'])
                        identity = f'{variant}-{trial_index}-{ticker}'
                        attempt = {'id': identity, 'ticker': ticker, 'side': side, 'decision_at': signal_at.isoformat(),
                            'execution_at': at.isoformat(), 'status': 'REJECTED', 'stage': 'PROPOSAL_SCHEMA', 'staged': False}
                        price = D(paths[ticker][index-1])
                        if side == 'BUY':
                            sizing = calculate_risk_plan(float(equity / rate), float(price), row.atr_usd)
                            quantity, stop = sizing.quantity, decimal_price(sizing.stop_price)
                        else:
                            quantity, stop = held.quantity, held.stop_price
                        attempt.update(quantity=quantity, price_usd=str(price), stop_usd=str(stop))
                        if quantity == 0:
                            attempt.update(stage='SIZE', reasons=['ZERO_QUANTITY'])
                            proposals.append(attempt)
                            continue
                        try:
                            proposal = USDProposal(proposal_id=identity, ticker=ticker, side=side, quantity=quantity,
                                entry_price=price, stop_price=stop, commission='0', slippage='0', exit_commission='0', exit_slippage='0')
                        except ValueError:
                            attempt['reasons'] = ['UNCHANGED_PROPOSAL_CONTRACT_REJECTED_STOP_OR_PRICE']
                            proposals.append(attempt)
                            continue
                        request = RiskConversionRequest(snapshot_id=identity, source='INVENTED-1Y', as_of=at,
                            cash_eur=state['account'][0]['cash'], holdings_usd=holdings_from_state(state),
                            marks_usd=marks, proposal_usd=proposal)
                        if side == 'BUY':
                            converted = convert_risk_inputs(request, fx, fx_policy, valuation_at=at)
                            quantity, sized = size_pretrade_buy(converted.snapshot, converted.proposal, policy, evaluated_at=at)
                            attempt['quantity'] = quantity
                            if not quantity:
                                attempt.update(stage='SIZE_RISK', reasons=list(sized.reasons))
                                proposals.append(attempt)
                                continue
                            proposal = USDProposal.model_validate(proposal.model_dump(mode='python') | {'quantity': quantity})
                            request = request.model_copy(update={'proposal_usd': proposal})
                        broker.create_order(identity, ticker, side, quantity, timestamp=at)
                        accepted = broker.accept_order(identity, timestamp=at)
                        attempt['staged'] = True
                        if accepted.status != 'ACCEPTED':
                            attempt.update(stage='BROKER_ACCEPT', reasons=[accepted.reason])
                            proposals.append(attempt)
                            continue
                        gate = ExecutionRequest(attempt_id=identity, order_id=identity,
                            expected_state_sha256=input_hash(broker.execution_state()), execution_at=at,
                            signal_available_at=signal_at, execution_price_at=at, risk_inputs=request,
                            fx=fx, fx_policy=fx_policy, risk_policy=policy)
                        outcome = broker.execute_gated(gate)
                        replay_execution_checks(outcome, expected_sha256=input_hash(outcome))
                        attempt.update(stage='GATE', status=outcome.status, reasons=list(outcome.reasons))
                        if outcome.status != 'FILLED':
                            broker.cancel_order(identity, timestamp=at, reason='Finite experiment: unfilled attempt expires, no automatic retry')
                        proposals.append(attempt)
                    portfolio = broker.reconcile()
                    close_fx = fx_at(closing_at, rate, f'{index}-close')
                    exposure = sum((convert(ConversionRequest(kind='USD_NOTIONAL', amount=D(paths[h.ticker][index]) * h.quantity),
                        close_fx, fx_policy, valuation_at=closing_at).value for h in portfolio.positions), D(0))
                    equity = portfolio.available_cash + exposure
                    basis = sum((h.cost_basis for h in portfolio.positions), D(0))
                    unrealized = exposure - basis
                    assert equity - D(10000) == portfolio.realized_pnl + unrealized
                    peak = max(peak, equity)
                    drawdown = (peak - equity) / peak * 100
                    max_drawdown = max(max_drawdown, drawdown)
                    check = monitor(root / (variant + '.sqlite'), report_id=f'{variant}-{trial_index}', reported_at=closing_at,
                        policy=MonitoringPolicy(expected_opening_cash='10000'))
                    if check.status != 'HEALTHY':
                        raise AssertionError('Operational integrity check failed: ' + check.status)
                    records.append({'session': str(days[index]), 'signal_date': str(days[index-1]), 'fx_eur_per_usd': str(rate),
                        'cash': str(portfolio.available_cash), 'equity': str(equity), 'exposure': str(exposure),
                        'realized_pnl': str(portfolio.realized_pnl), 'unrealized_pnl': str(unrealized),
                        'drawdown_pct': str(drawdown), 'cash_benchmark': '10000',
                        'positions': [asdict(h) for h in portfolio.positions], 'signals': signals, 'proposals': proposals,
                        'fills': sum(p['status'] == 'FILLED' for p in proposals),
                        'rejections': sum(p['status'] == 'REJECTED' for p in proposals),
                        'cumulative_fills': len(broker.fills()), 'reconciled': True, 'monitoring': check.status})
                result['portfolios'][variant] = {'daily': records, 'summary': {
                    'final_equity': str(equity), 'total_return_pct': str((equity / D(10000) - 1) * 100),
                    'max_drawdown_pct': str(max_drawdown), 'fills': len(broker.fills()),
                    'proposals': sum(len(r['proposals']) for r in records), 'rejections': sum(r['rejections'] for r in records),
                    'final_cash': str(portfolio.available_cash), 'final_exposure': str(exposure),
                    'realized_pnl': str(portfolio.realized_pnl), 'unrealized_pnl': str(unrealized),
                    'signal_counts': dict(Counter(s['decision'] for r in records for s in r['signals'])),
                    'control_failures': 0}}
    result['temporary_ledgers_removed'] = not root.exists()
    return result
