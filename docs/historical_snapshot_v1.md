# Historical snapshots and offline replay, version 1

This foundation freezes data and single-stock execution inputs. It does not
download data, regenerate strategy signals, run a portfolio research workflow,
or implement total-return accounting.

## Snapshot contract

`tools.historical_snapshot.HistoricalSnapshot` is the versioned schema. JSON
has required `schema_version: 1` and a nonempty `tickers` array. Each ticker
requires:

- `ticker`, uppercase identity; `currency`, a three-letter uppercase code.
- `source`, an author-supplied source identifier, and `calendar`, an explicit
  session convention identifier. Synthetic sources must identify themselves.
- `price_adjustment`: `unadjusted`, `split_adjusted`, or `dividend_adjusted`.
- `volume_adjustment`: `unadjusted` or `split_adjusted`.
- `dividend_convention`: `recorded_not_applied`.
- `split_convention`: `events_recorded_prices_unadjusted` for unadjusted prices,
  otherwise `events_recorded_prices_adjusted`.
- `bars`: at least two ordered daily observations with `date`, `open`, `high`,
  `low`, `close`, `volume`, `dividend`, and `split_ratio`.

Dates are session labels, serialized as YYYY-MM-DD. Prices must be finite and
positive, OHLC relationships valid, and volume/dividends finite and nonnegative.
Dividend is per share in the declared currency and the supplied share basis.
`split_ratio` is new shares divided by old shares on the effective session;
**1** means no split. A zero event sentinel must be explicitly converted by
the producer, not silently interpreted by the loader.

Every ticker must have identical dates and calendar identifiers. Duplicate
tickers, duplicate/descending dates, duplicate JSON object keys, missing fields,
unknown fields, and unsupported schema versions are rejected. Equality of
calendars does not prove completeness against an exchange calendar. Currency
codes and source adjustment declarations are structural metadata, not externally
verified claims. Snapshot producers remain responsible for their accuracy.

The snapshot can preserve adjustment modes that execution cannot support.
Single-stock replay rejects dividend-adjusted prices, and rejects unadjusted
prices with split events: current execution does not change quantities on splits.
Split-adjusted prices are passed through without additional share adjustment.
Dividend events are retained and hashed but never credited to cash.
All replay results are labeled **price_return_excluding_dividends**.
There is no FX conversion or claim of dividend-adjusted investment performance.

## Freezing an experiment

`freeze_experiment(snapshot, ticker, entries, exits,
signal_description=..., atr_values=..., **execution_parameters)` creates an
immutable `HistoricalExperiment`. Signals and ATR are already computed inputs;
their generation provenance belongs in `signal_description`. This phase does
not choose strategies or infer corporate-action conventions.

The experiment embeds the complete snapshot and its SHA-256, chosen ticker,
signals, optional ATR, and all effective simulator parameters, including resolved
defaults. It records the Git commit, dirty-tree indicator, execution-source
fingerprint, Python patch version, and installed pandas/pydantic/yfinance versions.
The source fingerprint covers the snapshot/replay module, historical simulator,
risk sizing, trade accounting, performance metrics, and trade metrics. It detects
local edits to that execution path even when HEAD is unchanged. The dirty flag
also reports unrelated changes; it does not identify or archive them.

`canonical_json(model)` produces compact UTF-8 JSON with sorted object keys,
normalized model numbers, and no nonfinite values. Tickers sort by identity;
bars and signals retain meaningful session order. `input_hash(model)` is SHA-256
of those bytes. Snapshot hashes identify data; experiment hashes also cover
parameters, signals, return convention, and recorded environment. This is a
versioned Python JSON convention, not a cross-language canonical-JSON standard.

Persist `canonical_json(snapshot)` and `canonical_json(experiment)` using normal
file I/O. Preserve `input_hash(experiment)` separately with the run record.
`load_snapshot(path)` validates a snapshot; `load_experiment(path,
expected_sha256=...)` also verifies both embedded data and experiment integrity.
A digest is a content-integrity check, not a signature or proof of provenance.

## Replay and limits

`replay_experiment(experiment)` delegates to the unchanged single-stock
simulator. It checks commit, execution-source fingerprint, Python version, and
recorded dependency versions before execution. A mismatch fails explicitly;
there is no download, package installation, or automatic environment repair.
Unrelated dirty-tree status need not match because it does not change the
fingerprinted execution path. Replaying after a commit change requires the
recorded checkout and execution source; this is intentionally strict.

Use the existing environment with `UV_NO_SYNC=1 uv run pytest -q` (set the
environment variable with the syntax appropriate to the shell).

The contract preserves simulator semantics: first-row signals execute on the
second row, previous-session ATR sizes entries, closing marks value open
positions, costs are charged as before, and end holdings are not liquidated.
The model assumes 252 sessions/year and zero risk-free rate. No exchange-calendar
completion, liquidity model, dividend cash flows, raw split accounting, result
artifact storage, experiment registry, or portfolio runner is added in 20B.
Tests use synthetic corporate actions and frozen signals; they do not validate
vendor adjustment accuracy or historical profitability.
