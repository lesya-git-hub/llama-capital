from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from hashlib import sha256

import pytest

from tools.historical_snapshot import canonical_json, input_hash
from tools.pretrade_risk import RiskConfiguration, evaluate_pretrade
from tools.fx_conversion import (
    CanonicalFX, ConversionRecord, ConversionRequest, EURRiskInputs, FXPolicy, FXQuote,
    FXQuoteBook, FXSourcePin, FXTrustRegistry, RiskConversionRequest, USDHolding,
    USDMark, USDOutstanding, USDProposal, canonical_quote, convert, convert_risk_inputs,
    reciprocal_quote, replay_conversion, replay_risk_inputs,
)


NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


def quote(**changes):
    values = dict(scope='synthetic_test', pair='USD_EUR', direction='EUR_PER_USD',
                  rate='0.92', effective_at=NOW - timedelta(seconds=10), retrieved_at=NOW,
                  provider_id='SYNTHETIC-ONLY', dataset_id='fixture-v1', quote_id='q1',
                  payload_sha256=sha256(b'synthetic FX payload').hexdigest(),
                  price_convention='indicative_mid', provenance='Invented test data, no market authority')
    return FXQuote(**(values | changes))


def policy(**changes):
    return FXPolicy(**(dict(max_age_seconds=60) | changes))


def conversion(kind='USD_PRICE', amount='200', *, fx=None, quantity=1, p=None, trust=None):
    options = {} if trust is None else dict(trust=trust)
    return convert(ConversionRequest(kind=kind, amount=amount, quantity=quantity),
                   fx or canonical_quote(quote()), p or policy(), valuation_at=NOW, **options)


@pytest.mark.parametrize('kind,amount,quantity,expected,currency', [
    ('USD_PRICE', '200', 1, '184', 'EUR'),
    ('USD_NOTIONAL', '1000', 1, '920', 'EUR'),
    ('EUR_NOTIONAL', '184', 1, '200', 'USD'),
    ('USD_EQUITY_VALUE', '200', 7, '1288', 'EUR'),
    ('USD_COST', '2.5', 1, '2.3', 'EUR'),
    ('USD_COST', '0', 1, '0', 'EUR'),
])
def test_direction_units_and_costs(kind, amount, quantity, expected, currency):
    result = conversion(kind, amount, quantity=quantity)
    assert result.value == Decimal(expected)
    assert result.currency == currency
    assert result.scope == 'synthetic_test'


def test_explicit_reciprocal_preserves_original_evidence():
    original = quote(direction='USD_PER_EUR', rate='2')
    with pytest.raises(ValueError): canonical_quote(original)
    with pytest.raises(ValueError): reciprocal_quote(quote())
    inverse = reciprocal_quote(original)
    assert inverse.direction == 'EUR_PER_USD' and inverse.rate == Decimal('.5')
    assert inverse.source_quote == original
    assert conversion(amount='200', fx=inverse).value == 100
    assert conversion('EUR_NOTIONAL', '100', fx=inverse).value == 200


def test_reciprocal_uses_original_divisor_without_intermediate_rate_rounding():
    inverse = reciprocal_quote(quote(direction='USD_PER_EUR', rate='3'))
    assert conversion(amount='3', fx=inverse).value == 1
    assert conversion('USD_EQUITY_VALUE', '.1', quantity=3, fx=inverse).value == Decimal('.1')


@pytest.mark.parametrize('amount,expected', [('1.000000000001', '.500000000000'),
                                          ('1.000000000003', '.500000000002')])
def test_half_even_rounding_boundaries(amount, expected):
    assert conversion('USD_NOTIONAL', amount, fx=canonical_quote(quote(rate='.5'))).value == Decimal(expected)


def test_multi_share_rounding_occurs_after_multiplication():
    fx = canonical_quote(quote(rate='.5'))
    result = conversion('USD_EQUITY_VALUE', '1.000000000001', quantity=3, fx=fx)
    assert result.value == Decimal('1.500000000002')
    assert result.value != conversion(amount='1.000000000001', fx=fx).value * 3


@pytest.mark.parametrize('rate', ['NaN', 'Infinity', '-Infinity', '0', '-1', 0.92, True,
                                '.0000000000000000000000001'])
def test_invalid_rates(rate):
    with pytest.raises(ValueError): quote(rate=rate)


@pytest.mark.parametrize('changes', [dict(pair='EUR_GBP'), dict(direction='USD/EUR'),
    dict(provider_id=' '), dict(dataset_id=''), dict(quote_id=''), dict(provenance=''),
    dict(payload_sha256='bad'), dict(price_convention='unknown'),
    dict(effective_at=NOW.replace(tzinfo=None)), dict(effective_at=123),
    dict(effective_at=NOW + timedelta(seconds=1))])
def test_malformed_quote_metadata(changes):
    with pytest.raises(ValueError): quote(**changes)


def test_missing_metadata():
    data = quote().model_dump(mode='json')
    del data['payload_sha256']
    with pytest.raises(ValueError): FXQuote.model_validate(data)


def test_future_stale_and_unavailable_quote():
    for q in (quote(effective_at=NOW - timedelta(seconds=61)),
              quote(retrieved_at=NOW + timedelta(seconds=1)),
              quote(effective_at=NOW + timedelta(seconds=1), retrieved_at=NOW + timedelta(seconds=2))):
        with pytest.raises(ValueError): conversion(fx=canonical_quote(q))
    assert conversion(fx=canonical_quote(quote(effective_at=NOW - timedelta(seconds=60)))).value == 184
    # A fresh retrieval does not refresh an old market-effective quote.
    with pytest.raises(ValueError, match='Stale'):
        conversion(fx=canonical_quote(quote(effective_at=NOW - timedelta(days=1))))


def test_naive_valuation_and_timestamp_normalization():
    with pytest.raises(ValueError):
        convert(ConversionRequest(kind='USD_COST', amount='1'), canonical_quote(quote()), policy(),
                valuation_at=NOW.replace(tzinfo=None))
    q = quote(retrieved_at=NOW.astimezone(timezone(timedelta(hours=2))))
    assert q.retrieved_at.tzinfo == timezone.utc
    assert input_hash(q) == input_hash(quote())


def test_unapproved_source_is_rejected_when_required():
    q = quote()
    p = policy(approval='required')
    assert FXTrustRegistry().pins == ()
    with pytest.raises(ValueError, match='Unapproved'): conversion(p=p)
    trust = FXTrustRegistry(pins=(FXSourcePin(provider_id=q.provider_id, dataset_id=q.dataset_id,
        quote_sha256=input_hash(q), review_reference='SYNTHETIC FIXTURE REVIEW ONLY'),))
    assert conversion(p=p, trust=trust).scope == 'synthetic_test'
    with pytest.raises(ValueError, match='Unapproved'):
        conversion(p=p, trust=trust, fx=canonical_quote(quote(rate='.93')))


def test_quote_book_rejects_duplicates_and_conflicts():
    for other in (quote(), quote(rate='.93')):
        with pytest.raises(ValueError): FXQuoteBook(quotes=(quote(), other))
    a = FXQuoteBook(quotes=(quote(), quote(quote_id='q2')))
    assert input_hash(a) == input_hash(FXQuoteBook(quotes=a.quotes[::-1]))


@pytest.mark.parametrize('changes', [dict(amount=1.2), dict(amount=True), dict(amount='NaN'),
    dict(amount='Infinity'), dict(amount='-1'), dict(amount='0'), dict(quantity=0),
    dict(quantity=True), dict(quantity=1.5), dict(kind='USD_NOTIONAL', quantity=2)])
def test_invalid_conversion_inputs(changes):
    with pytest.raises(ValueError): ConversionRequest(**(dict(kind='USD_PRICE', amount='1') | changes))


def test_replay_hashes_caller_context_and_tampering(tmp_path):
    result = conversion()
    restored = ConversionRecord.model_validate_json(canonical_json(result))
    with localcontext() as ctx:
        ctx.prec = 3
        ctx.rounding = 'ROUND_UP'
        assert canonical_json(conversion()) == canonical_json(result)
        assert replay_conversion(restored, expected_sha256=input_hash(result)) == result
    assert input_hash(quote(rate='.9200')) == input_hash(quote())
    altered = result.model_copy(update={'value': Decimal('1')})
    with pytest.raises(ValueError): replay_conversion(altered, expected_sha256=input_hash(result))
    with pytest.raises(ValueError): replay_conversion(altered, expected_sha256=input_hash(altered))
    assert list(tmp_path.iterdir()) == []


def usd_proposal(**changes):
    values = dict(proposal_id='proposal-1', ticker='AAPL', side='BUY', quantity=5,
                  entry_price='200', stop_price='190', commission='1', slippage='.1',
                  exit_commission='1', exit_slippage='.1')
    return USDProposal(**(values | changes))


def risk_request(**changes):
    values = dict(snapshot_id='usd-synthetic', source='SYNTHETIC-ONLY', as_of=NOW,
                  cash_eur='10000', marks_usd=(USDMark(ticker='AAPL', price='200', as_of=NOW),),
                  proposal_usd=usd_proposal())
    return RiskConversionRequest(**(values | changes))


def test_risk_interface_converts_units_preserves_cash_and_leaves_approval_separate():
    request = risk_request()
    original = canonical_json(request)
    result = convert_risk_inputs(request, canonical_quote(quote()), policy(), valuation_at=NOW)
    assert result.snapshot.cash == 10000
    assert result.snapshot.currency == result.proposal.currency == 'EUR'
    assert result.snapshot.marks[0].price == 184
    assert result.proposal.entry_price == 184
    assert result.proposal.stop_price == Decimal('174.8')
    assert result.proposal.commission == Decimal('.92')
    assert result.proposal.slippage == Decimal('.092')
    assert result.snapshot.marks[0].as_of == quote().effective_at
    assert canonical_json(request) == original
    assert not hasattr(result, 'decision')
    decision = evaluate_pretrade(result.snapshot, result.proposal,
                                RiskConfiguration(max_age_seconds=60), evaluated_at=NOW)
    assert decision.decision == 'APPROVED'  # Separate, explicit advisory test call.


def test_holdings_pending_and_replay():
    holding = USDHolding(ticker='AAPL', quantity=2, stop_price='190', exit_commission='1', exit_slippage='.1')
    pending = USDOutstanding(order=usd_proposal(proposal_id='pending'), status='ACCEPTED')
    request = risk_request(cash_eur='9000', holdings_usd=(holding,), outstanding_usd=(pending,))
    result = convert_risk_inputs(request, canonical_quote(quote()), policy(), valuation_at=NOW)
    assert result.snapshot.holdings[0].quantity == 2
    assert result.snapshot.holdings[0].stop_price == Decimal('174.8')
    assert result.snapshot.outstanding[0].order.entry_price == 184
    restored = EURRiskInputs.model_validate_json(canonical_json(result))
    assert replay_risk_inputs(restored, expected_sha256=input_hash(result)) == result
    altered = result.model_copy(update={'snapshot_sha256': '0' * 64})
    with pytest.raises(ValueError): replay_risk_inputs(altered, expected_sha256=input_hash(altered))


def test_risk_boundary_rejects_unverified_fx_and_binary_floats():
    with pytest.raises(ValueError):
        convert_risk_inputs(risk_request(), canonical_quote(quote(scope='unverified')), policy(), valuation_at=NOW)
    assert conversion(fx=canonical_quote(quote(scope='unverified'))).scope == 'unverified'
    with pytest.raises(ValueError): usd_proposal(entry_price=200.0)
    with pytest.raises(ValueError): USDMark(ticker='AAPL', price=200.0, as_of=NOW)
    with pytest.raises(ValueError): risk_request(cash_eur=10000.0)


def test_fx_adapter_does_not_refresh_stale_portfolio_state():
    old = NOW - timedelta(seconds=120)
    request = risk_request(as_of=old, marks_usd=(USDMark(ticker='AAPL', price='200', as_of=old),))
    result = convert_risk_inputs(request, canonical_quote(quote()), policy(), valuation_at=NOW)
    assert result.snapshot.as_of == old
    decision = evaluate_pretrade(result.snapshot, result.proposal,
                                RiskConfiguration(max_age_seconds=60), evaluated_at=NOW)
    assert decision.decision == 'REJECTED'
