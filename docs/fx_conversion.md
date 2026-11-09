# Sprint 1F: offline USD/EUR conversion

Baseline inspected: `eec6694`, 640 existing tests. All new fixtures are synthetic.

## Architecture assessment

The EUR paper broker uses Decimal, precision 50 and twelve fractional places,
but keeps positions at cost and does not supply marked equity. Its CREATED and
ACCEPTED orders do not reserve funds. The advisory `tools.pretrade_risk` engine
requires explicit synthetic EUR valuations/stops/costs, uses current marks and
caller-controlled freshness, and neither reserves resources nor executes orders.
It remains unchanged. No new accounting or order lifecycle is introduced.

`providers.offline_market_data` freezes USD OHLCV, adjustment conventions, raw
fixture hashes and source provenance. Its adapted candles remain provisional.
Sprint 1C's `market_verification`/`verified_daily_pipeline` require independent
exact-content authority pins and genuine completion evidence before verified
publication. FX arithmetic does not establish equity candle finality, replace
those pins or enable publication. Existing market-data snapshots use float
candles; this sprint does not silently convert those into financial Decimal
inputs. Callers must provide explicit decimal USD valuation fixtures.

`tools.fx_conversion` reuses frozen models, canonical JSON and `input_hash`,
and produces ordinary 1E `Mark`, `Holding`, `Proposal`, `Outstanding` and
`ValuationSnapshot` objects. No existing strategy, simulator, broker or risk
behavior changed; there are no network transports or provider dependencies.

## Quote direction, metadata and trust

`FXQuote` records pair `USD_EUR`, explicit direction, positive Decimal rate,
effective/retrieval timestamps, provider/dataset/quote IDs, SHA-256 of the source
payload, indicative-mid convention, provenance and synthetic/unverified scope.
Timestamps must be timezone aware and are normalized to UTC. Numeric epoch
timestamps are rejected. Effective time cannot follow retrieval.

The conversion API accepts only `CanonicalFX`, whose direction is
`EUR_PER_USD`: one dollar buys the stated number of euros. `canonical_quote(q)`
accepts an original EUR_PER_USD quote; `reciprocal_quote(q)` explicitly adapts an
original USD_PER_EUR quote. Neither function guesses the direction. The wrapper
retains the entire original quote and operation, preserving its rate and source
hash. Its canonical `rate` property is reproducibly derived; serialized inputs
retain the original rate plus explicit operation rather than replacing the
provider's record with an invented reciprocal quote.

`FXQuoteBook` rejects duplicate/conflicting provider + dataset + quote identities
within a frozen collection, including identical duplicates. Different providers
have separate namespaces. There is no global mutable quote registry; callers
must retain and compare their source collections when importing revisions.

`FXPolicy.max_age_seconds` is required. Both effective time and retrieval must
be no later than valuation time, and effective age must not exceed the limit.
Fresh retrieval never refreshes stale effective time. `approval='required'`
also requires an exact-content provider/dataset/quote pin in a separately supplied
`FXTrustRegistry`. Default pins are empty and no production identities ship.
Review-reference strings and hashes are not signatures or proof of correctness.
Payload hashes are metadata: the caller must retain source payload bytes to
independently check that hash; this module does not fetch or authenticate them.

No output is labeled trusted. Scope remains `synthetic_test` or `unverified`,
even when an externally supplied content pin is matched. The risk compatibility
adapter permits only synthetic quotes and synthetic input fixtures. Mathematical
validity, a metadata label, a computed hash or an illustrative test pin cannot
authorize production paper execution.

## Decimal units and rounding

All financial inputs at the new boundary reject binary floats and booleans.
Use Decimal, decimal strings or integers. Rates must be finite, positive, at
most 1e12, with at most 24 fractional places and 36 total digits. Amounts must
be finite, nonnegative, at most 1e12 with at most 12 fractional places. Equity
prices must be positive; zero notionals/costs are valid. Quantities are positive
whole shares up to 1e9. Missing inputs never receive guessed rates or costs.

Calculations use a dedicated precision-80, ROUND_HALF_EVEN context independent
of caller precision/rounding. Original direct rates multiply USD amounts;
original reciprocal rates divide them. EUR-to-USD explicitly reverses that
operation. There is no multiplication by an intermediately rounded reciprocal.
Multi-share valuations multiply price by quantity before converting and rounding.
The supported operand bounds keep finite multiplication within context precision;
recurring division uses precision 80 before final rounding.

Every final output rounds half-even to 0.000000000001 of its output currency,
matching the existing twelve-place accounting interface. No cent rounding is
implied. Values too small to survive this precision can round to zero; a zero
price or collapsed stop relationship is rejected by the existing risk models
when constructing compatible risk inputs. The module does not silently increase
precision or invent a positive price. Values outside 1E's amount bounds likewise
fail at that existing boundary.

Supported `ConversionRequest.kind` values:

- `USD_PRICE`: one USD share price to EUR per-share price.
- `USD_NOTIONAL`: USD amount to EUR amount.
- `EUR_NOTIONAL`: EUR amount to USD amount.
- `USD_EQUITY_VALUE`: USD per-share price times explicit quantity to EUR notional.
- `USD_COST`: USD-denominated total fee or per-share adverse cost to the same
  unit in EUR; total versus per-share units must remain explicit at the caller.

```python
fx = canonical_quote(synthetic_quote)  # direction must already be EUR_PER_USD
policy = FXPolicy(max_age_seconds=60)
record = convert(
    ConversionRequest(kind="USD_EQUITY_VALUE", amount="200", quantity=7),
    fx, policy, valuation_at=explicit_timestamp,
)
# With a synthetic 0.92 EUR_PER_USD rate: record.value == Decimal("1288") EUR.
digest = input_hash(record)
restored = ConversionRecord.model_validate_json(canonical_json(record))
assert replay_conversion(restored, expected_sha256=digest) == record
```

## Pure risk compatibility boundary

`RiskConversionRequest` explicitly separates `cash_eur` from USD marks,
holdings/stops, proposed instructions and outstanding instructions. New
`USDMark`, `USDHolding` and `USDProposal` models reuse the 1E shapes while
rejecting floats. A USD proposal defaults to explicitly declared USD currency;
its fees are total USD and slippage is adverse USD per share, matching 1E units.

`convert_risk_inputs` leaves EUR cash and quantities unchanged, converts each
USD price/stop/cost and constructs ordinary synthetic EUR risk inputs. Existing
duplicate and numeric/stop constraints are preserved. It does not call the risk
evaluator. `EURRiskInputs` embeds original request, FX quote/operation, policy,
conversion records and input/output hashes; retain the whole envelope alongside
any separate advisory risk decision so provenance is not lost.

The source portfolio timestamp is preserved. Converted marks use the earlier
of their USD mark time and FX effective time; retrieval cannot make an old mark
fresh. `valuation_at` in the envelope records when all quote information was
available, and quote retrieval must precede it. The unchanged 1E evaluator still
checks portfolio and mark freshness against its own configured policy. A valid
FX conversion can therefore produce inputs that 1E subsequently rejects.

1E consumes per-share prices, so that adapter rounds each per-share input once
at twelve places before 1E multiplies quantities. A separately calculated
multi-share notional rounds only the final notional and can differ by accumulated
sub-quantum per-share rounding (at most quantity times half a twelve-place unit
for one mark). This representational boundary is explicit; the adapter never
overrides 1E's accounting to force totals to match. Positive estimated costs may
also round to zero at that precision. These are research valuations, not assured
execution prices or cash reservations.

## Replay and limitations

`ConversionRecord` embeds original quote, explicit reciprocal operation, request,
policy, timestamp, result currency/value, hashes of source quote/request/policy,
external trust-root hash and engine-source hash. `replay_conversion` checks an
independently supplied expected hash, revalidates freshness and trust at the
recorded time, reruns arithmetic and compares the full result. Tampered output,
changed code or a different trust root fails. `replay_risk_inputs` performs the
equivalent regeneration for the entire risk-input envelope. Canonical decimal
representations and UTC timestamps make JSON/hash replay reproducible. Preserve
the original code/dependency environment and any external reviewed pins as well
as the expected hashes; hashes cannot recover lost inputs or establish truth.

Indicative mid quotes do not include executable bid/ask spread, conversion fees,
market impact, settlement or FX hedging. Underlying equity adjustment conventions
remain the caller's responsibility; conversion changes currency units only.
No live provider, license review, real trust evidence, authenticated FX feed or
execution integration exists in this sprint. Advisory approval can become stale
as portfolio state changes; neither FX conversion nor advisory checks atomically
enforce portfolio limits. Production paper execution remains unenabled.

No credentials, dependencies, external data requests, commits, pushes or tags
were introduced. `scripts/sec_match_recon.py` was left untouched. Work stops for
review after validation.

## Validation results

- `uv run --no-sync pytest -q tests/test_fx_conversion.py`: **50 passed**.
- `uv run --no-sync pytest -q`: **690 passed** in 22.18 seconds, preserving
  all 640 existing cases and adding 50 synthetic FX cases.
- `git diff --check`: passed. uv cache access required test execution outside
  the filesystem sandbox; no dependency installation or synchronization occurred.
