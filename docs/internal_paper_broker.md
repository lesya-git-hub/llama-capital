# Internal EUR paper broker — V2 Sprint 1A

`providers.paper_broker.PaperBroker` is a local, paper-only account backed by
standard-library SQLite. It has no broker API, credentials, network calls,
market-data feed, strategy loop or automatic execution. Constructing an order
or accepting it never fills it. The V1 simulators and strategies are unchanged.

## Account and order lifecycle

One SQLite file holds one virtual EUR account, initially EUR 10,000 unless
`initial_cash` is supplied on first creation. Reopening loads and reconciles
the same account; supplying a different initial capital fails rather than
resetting the ledger. The parent directory must already exist. Importing the
module does not open or create a ledger. Use a local filesystem, not a shared
network filesystem. Do not point it at an unrelated database.

```text
CREATED -> ACCEPTED -> FILLED
CREATED -> REJECTED
CREATED/ACCEPTED -> CANCELLED
```

All orders are long-only BUY or SELL instructions for whole shares. One explicit
fill executes the entire order once. Partial position sales are supported by
creating a SELL order smaller than the held position; partial *order* fills are
not supported. Further buys use a weighted-average position cost basis.

As confirmed for this sprint, ACCEPTED reserves neither cash nor shares. It
means the instruction is eligible for a later explicit execution attempt, not
a guarantee of execution. Every fill rechecks cash and holdings inside the
SQLite write transaction. A failed cash/holdings/kill check raises `ValueError`,
leaves the order ACCEPTED, and records FILL_BLOCKED; the caller may retry at a
different explicit execution or cancel. An accepted order never transitions
to REJECTED. `reject_order` is available for CREATED instructions.

## Explicit simulated execution

```python
from datetime import datetime, timezone
from providers.paper_broker import PaperBroker

# The directory exists; this opens/creates only a local virtual ledger.
with PaperBroker("runs/paper_broker.sqlite3") as broker:
    broker.create_order("research-buy-001", "SYNTH", "BUY", 10,
                        timestamp=datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc))
    broker.accept_order("research-buy-001",
                        timestamp=datetime(2026, 11, 6, 9, 1, tzinfo=timezone.utc))
    fill = broker.simulate_fill(
        "research-buy-001", price="100.00", commission="1.00",
        slippage_per_share="0.05",
        timestamp=datetime(2026, 11, 6, 9, 2, tzinfo=timezone.utc),
    )
    portfolio = broker.reconcile()
    audit = broker.audit_events()
```

The example is not run automatically. Fill price is the explicit reference
price, commission is the **total EUR fee**, and slippage is **adverse EUR per
share**, as confirmed for this sprint. BUY execution price adds slippage; SELL
execution price subtracts it. Missing commission/slippage default to zero;
the broker does not inherit V1's percentage-rate defaults or infer market costs.
Execution price must remain positive. Sale commissions may consume existing
cash, but total cash after execution must never be negative.

Timestamps must be explicit timezone-aware `datetime` objects and are stored
in UTC. New lifecycle actions cannot precede the order's last lifecycle event;
fills cannot predate any existing portfolio fill. Equal timestamps are allowed,
with actual transaction order preserved by audit sequence. Administrative
events and failed fill attempts retain supplied timestamps; audit sequence,
rather than wall-clock sorting, is the authoritative append order.

## Accounting and precision

For BUY: cash decreases by `quantity * execution_price + commission`, and that
amount becomes position cost basis. For SELL: cash increases by
`quantity * execution_price - commission`; net realized P&L is proceeds minus
the sold shares' allocated weighted-average cost basis. The position's
`average_entry_cost` includes entry commission and slippage. It is not a tax-lot
or FIFO cost model. The V1 round-trip helper assumes full exits and proportional
fees; this broker needs explicit fees and partial-position accounting. Tests
verify equivalent V1 round trips without duplicating the historical simulator.

Money uses Decimal values persisted as text, not SQLite floating-point balances.
Use decimal strings or Decimal inputs. Inputs must be finite, nonnegative,
at most 1e12 EUR and at most 12 fractional digits; reference price and initial
capital must be positive. Quantity must be an integer from 1 through 1e9.
Internal arithmetic uses precision 50 independently of the caller's Decimal
context. Partial-sale cost allocation rounds half-even to 12 decimal places;
the final sale consumes the exact remaining basis. No cent rounding or broker
exchange-rate convention is implied. Average cost may be a repeating decimal.

The account contains available cash, aggregate realized P&L, and positions at
cost. No current quote is inferred, so this sprint does not report marked
equity or unrealized P&L. Useful ledger identities are:

```text
cash = initial_cash + sum(fill.cash_delta)
realized_pnl = sum(fill.realized_pnl)
cash + open_cost_basis = initial_cash + realized_pnl
position_quantity = bought_quantity - sold_quantity
```

## Persistence, idempotency and recovery

SQLite schema version 1 stores account, orders, positions, fills and audit
records with a paper-ledger application identifier. `BEGIN IMMEDIATE` serializes
writers; cash, holdings, fill, order status and successful-fill audit either
commit together or roll back together. Separate broker instances may share the
file. A single instance uses SQLite's default same-thread connection restriction.
The lock timeout is ten seconds; database/lock failures propagate for the caller
to handle. No background retry or execution scheduler is present.

Order IDs are unique within the ledger. Repeating `create_order` with the same
ticker/side/quantity returns the existing instruction regardless of retry time;
different economic instructions with the same ID fail. Repeating the same
successful fill requires identical reference price, commission, slippage and
UTC execution timestamp and returns the stored fill without another audit or
balance change. Changed fill details fail. IDs cannot be recycled after a
rejection, cancellation or fill. Repeated matching lifecycle actions are no-ops.

`reconcile()` reconstructs cash, cost basis, shares and realized P&L from fills
in actual execution order, and checks stored state and fill/order/audit counts.
It also runs when reopening. A mismatch fails without repairing or deleting
evidence. The ledger is not cryptographically signed or protected against
coordinated manual database modification. Keep normal local file backups;
automatic backup, migrations and external integrity attestation are not added.

## Emergency stop and audit

`set_kill_switch(True, timestamp=..., reason=...)` persists the emergency state
without deleting balances, positions or orders. As confirmed for this sprint,
it prevents creation of usable new orders, acceptance, and pending BUY/SELL
fills. New creation attempts are retained as CREATED then REJECTED audit
records; CREATED orders accepted while killed become REJECTED. Previously
accepted orders remain ACCEPTED with a blocked-fill event. Cancellation,
explicit rejection and reads remain available; exact already-completed retries
return prior records without new execution. Explicit manual disabling resumes
eligibility; it never automatically fills pending orders.

Audit records cover CREATED, ACCEPTED, REJECTED, CANCELLED, FILLED,
FILL_BLOCKED and kill changes. Structurally invalid inputs, conflicting IDs,
invalid lifecycle transitions, or database failures raise without fabricating
a successful event. Audit insertion failure rolls the entire fill back.

## Verification and limits

With the existing uv environment, set `UV_NO_SYNC=1` and run:

```text
uv run pytest tests/test_paper_broker.py -q
uv run pytest -q
```

Tests create only temporary virtual SQLite ledgers. They cover accounting,
partial sales, decimal costs, V1 cost parity, lifecycle/idempotency, restarts,
kill persistence, competing/same-ID concurrent fills, rollback injection and
ledger reconciliation.

This sprint is not an operational paper-trading service. No automated sizing,
aggregate risk cap, stop orders, market-calendar enforcement, liquidity model,
corporate actions, dividends, FX, taxes, cash deposits/withdrawals, external
orders, or real-money actions are implemented. Existing risk utilities remain
available for a future caller; they are not silently enforced by this ledger.
The kill switch blocks even position-reducing fills until explicitly disabled.
No investment edge or live/paper-trading deployment readiness is established.
