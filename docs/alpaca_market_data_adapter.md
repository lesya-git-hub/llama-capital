# Sprint 1S: in-memory Alpaca daily-bars adapter

Gate B remains **NO-GO**. Baseline: `main @ dcc355b`, 1,096 tests.
This adapter is ready for a separately authorized supervised read-only trial.
Implementation/testing authorization does not authorize any Alpaca request.

## Scope and usage

`providers/alpaca_market_data.py` exposes `DailyBarsRequest`, `TransportLimits`,
`AlpacaMarketDataAdapter`, an injectable `AlpacaTransport` protocol and provisional
bar/batch models. Importing or constructing the adapter makes no request and does
not load credentials. An explicit `fetch(request)` invokes exactly one transport GET.
There is no CLI, scheduler, retry, redirect, fallback or automatic pagination.

Prepare a request without sending it:

```python
from providers.alpaca_market_data import DailyBarsRequest

request = DailyBarsRequest(
    symbols=("AAPL",),
    start="2026-10-26",
    end="2026-10-30",
    expected_session_dates=(
        "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30",
    ),
)
# request.url is the sanitized URL to review before any separate network approval.
# Do not invoke AlpacaMarketDataAdapter().fetch(request) without that approval.
```

Symbols default to the existing canonical AAPL/JNJ/JPM/MSFT/WMT/XOM universe;
subsets are supported. An expanded `permitted_symbols` list requires explicit caller
configuration and separate trial approval; it never automatically changes the feed
or endpoint. Timeframe is fixed to `1Day`, adjustment to `split`, feed to `iex` and
currency to USD. Limits default to 100 bars, with an absolute allowed maximum of
10,000. These are requested response limits, not entitlement or quota assertions.

Plain start/end dates mean inclusive New York civil days; UTC boundaries use the
installed timezone database, including DST. Explicit aware instants are also accepted
and normalized to UTC. Naive/numeric timestamps, reversed ranges and unordered or
duplicate expected dates reject. Requests extending beyond the local receipt clock
reject before transport. No official calendar is inferred from weekdays or a date range.

For offline use, inject a transport whose `get(request, credentials, limits)` returns
`HTTPResponse`; tests use only invented payloads and fake credentials. Do not use
real API responses as persisted fixtures until retention rights permit that use.

## Credential and transport boundary

`load_credentials` uses a complete `ALPACA_API_KEY` / `ALPACA_API_SECRET` environment
pair first, otherwise reads the same names from local `.env` with existing dotenv
parsing and **no interpolation or global environment mutation**. A partial environment
pair rejects rather than mixing it with a different file pair. Duplicate dotenv
credential names, malformed/blank/control-character values and load failures produce
fixed errors. No application bootstrap or broad service configuration is imported.
`AlpacaCredentials` has a redacted representation and refuses pickle serialization.

The default `SingleGETTransport` sends one GET only to
`https://data.alpaca.markets/v2/stocks/bars`, authenticating through the two Alpaca
headers. No secret is placed in URLs, subprocess arguments, logs or exception messages.
No environment proxy is used; HTTP redirects are returned as failures, not followed.
Non-200 bodies are never parsed or returned. Response bytes are never saved or
returned in the public batch. Credential echoes cause rejection.

The network call runs in a short-lived worker: request, credentials and response use
private memory pipes; stdout is not a terminal or artifact, and stderr is discarded.
Python bytecode writes are disabled for the child. Defaults are a 10-second socket
timeout, a 30-second worker deadline (including blocking DNS) and a 256 KiB body cap.
Limits are explicit and bounded in `TransportLimits`. Timeout terminates the worker;
the provider might already have received the request, so no retry follows. Worker
startup/OS failure also produces a sanitized error, not a fallback process/request.
Caller-supplied transports must honor the same single-GET/deadline/size contract;
the adapter also independently checks returned body size and schema.

The adapter itself writes no raw payload, derived data, database, archive or report.
The caller must not log, serialize, upload, cache or retain results without confirmed
rights. In-memory Python objects/IPC are not guaranteed cryptographic zeroization;
host swap, crash dumps and debugger custody remain operational concerns. This is
not protection against a malicious embedding process reading its own memory.

## Fail-closed response rules

- Require HTTP 200, JSON content type, identity encoding, valid UTF-8 JSON and unique
  object keys. Reject nonfinite values, unknown top-level/bar fields and wrong types.
- Require exactly `bars` and `next_page_token`; token must be **null**. A nonempty,
  empty-string or malformed token, or a missing marker, rejects the entire result.
  No partial first-page batch is returned and no page is followed.
- Require exactly the requested symbol set, nonempty lists, unique ordered dates,
  aligned dates across symbols and no more bars than the requested total limit.
- Require `t,o,h,l,c,v`; support optional `n,vw`. Parse numeric JSON decimals before
  converting OHLCV to the existing repository's finite float research convention.
  Reject bool/string financial values, negative volume/count, invalid OHLC relationships,
  nonpositive prices/VWAP, overflow and underflow to zero. This is not a Decimal risk
  or valuation input boundary.
- Require explicit UTC RFC3339 bar timestamps at New York midnight, within the exact
  requested interval, with weekday session labels. Whole-second/microsecond precision
  is supported; unsupported finer precision rejects rather than being silently truncated.
  No midnight label is interpreted as publication or candle completion time.
- When `expected_session_dates` is provided, every symbol must match it exactly.
  These are **caller expectations**, not verified exchange sessions. Without them,
  aligned nonempty source dates can return with `session_coverage=UNVERIFIED`; a date
  missing uniformly from all symbols cannot be discovered without an independent
  expected calendar. Neither mode claims authoritative session coverage.

Failures raise `AlpacaDataError` with a fixed code and optional numeric HTTP status.
Native errors, provider error bodies and credential-bearing messages/context are
suppressed. HTTP 401/403/429/5xx, transport timeouts and oversized/partial/malformed
responses do not trigger retries or return a partial successful batch.

## Result and existing-contract separation

The frozen `AlpacaDailyBatch` retains the request (symbols, UTC boundaries, feed,
adjustment, currency and limit), fixed provider/source endpoint, local acquisition
interval and normalized per-symbol bars. It is always `PROVISIONAL`, scope
`unverified`, `provider_final=False`, `calendar_verified=False`; source publication
time is unknown. Split adjustment is labeled request acceptance, not independently
verified adjustment correctness. Missing dividends/split ratios are **not invented**.

The separate bar model deliberately does not construct `Candle`, `SourceBatch`,
`ProvisionalBatch` or an admitted object: those require corporate actions, calendars,
scope and evidence this endpoint does not supply. There is no `as_observed`, publish,
persist, admission, signal, broker, risk, valuation or execution API. Existing modules
and their verification contracts remain unchanged.

The previously authorized five-day trials reported 5 AAPL bars and then 30 bars
across six symbols. Those observations are session reports only, not stored test
fixtures or proof of completion, rights, adjustment math or future availability.
All new tests use invented data; this sprint makes no authenticated requests.

## Limitations and review gate

Refer to [alpaca_trial_feasibility.md](alpaca_trial_feasibility.md) and
[market_data_provider_onboarding_review.md](market_data_provider_onboarding_review.md).
Irish eligibility/applicable terms, permitted retention and sharing, actual account
entitlement, IEX versus consolidated coverage, detailed bar/session/volume semantics,
corporate actions, official calendar/finality evidence and independent receipt clocks
remain unresolved. Current connectivity does not resolve those questions. Exact
response schemas intentionally fail closed on provider changes until reviewed.

There is no license approval, trusted root, archival replay guarantee or forward
paper-trading authorization. No dependency, existing financial behavior or protected
script changes are needed. Stop for independent operator review before any real fetch,
commit or push. Gate B remains **NO-GO**.

## Validation record

Final code tested on 2026-11-10 against baseline `dcc355b`:

- `uv run --no-sync pytest -q tests/test_alpaca_market_data.py`: **103 passed**
  in **1.00 second**. All HTTP/process responses are mocked; an autouse guard
  forbids real connections and unmocked worker creation in these tests.
- `uv run --no-sync pytest -q`: **1,199 passed** in **193.51 seconds**,
  preserving **1,096 baseline tests** plus **103 new cases**.
- New implementation/test/documentation whitespace checks passed.

The sandbox could not initialize the existing user uv cache; tests used approved
escalation with `--no-sync`, without installing or changing dependencies. No
authenticated request was performed in this sprint. The three new files are this
document, the provider module and its tests. The prior untracked Alpaca feasibility
and Tiingo design documents remain unchanged. No files were staged, committed or
pushed. The pre-existing modified protected script retains SHA-256
`7465165612e9c4b7a438ffc185f0a07bf608b4e6d73acad7777b33085eb7fbe4`.
