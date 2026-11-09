"""Persistent internal EUR paper broker. No network or automatic execution."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path
import re
import sqlite3


QUANTUM = Decimal("0.000000000001")
APPLICATION_ID = 0x4C4C5042


def _money(value, *, positive=False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Money must be an explicit finite numeric amount")
    try:
        number = Decimal(str(value))
        if (not number.is_finite() or number < 0 or (positive and number == 0)
                or number > Decimal("1000000000000")
                or number.as_tuple().exponent < -12):
            raise ValueError("Money must be nonnegative, <= 1e12, with at most 12 fractional digits")
    except InvalidOperation as exc:
        raise ValueError("Invalid money amount") from exc
    return number


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An explicit timezone-aware timestamp is required")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    ticker: str
    side: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    reason: str | None


@dataclass(frozen=True)
class PaperPosition:
    ticker: str
    quantity: int
    cost_basis: Decimal

    @property
    def average_entry_cost(self) -> Decimal:
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            return self.cost_basis / self.quantity


@dataclass(frozen=True)
class PaperPortfolio:
    currency: str
    initial_cash: Decimal
    available_cash: Decimal
    realized_pnl: Decimal
    positions: tuple[PaperPosition, ...]
    kill_switch: bool


@dataclass(frozen=True)
class PaperFill:
    order_id: str
    ticker: str
    side: str
    quantity: int
    reference_price: Decimal
    execution_price: Decimal
    commission: Decimal
    slippage_per_share: Decimal
    timestamp: str
    cash_delta: Decimal
    allocated_cost_basis: Decimal
    realized_pnl: Decimal


@dataclass(frozen=True)
class PaperAuditEvent:
    sequence: int
    order_id: str | None
    event: str
    timestamp: str
    reason: str


class PaperBroker:
    """One virtual EUR account per SQLite file; explicit whole-order fills only.

    ACCEPTED does not reserve cash/shares. Failed fill checks leave it ACCEPTED
    and append FILL_BLOCKED. Kill mode blocks creation/acceptance/fills, while
    cancellation, rejection, reads and exact idempotent retries remain possible.
    """

    def __init__(self, path: str | Path, *, initial_cash=None, strict: bool | None = None):
        if strict is not None and type(strict) is not bool:
            raise ValueError('Strict mode must be explicitly boolean or omitted')
        initial = None if initial_cash is None else _money(initial_cash, positive=True)
        self._db = sqlite3.connect(str(path), isolation_level=None, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        try:
            with self._transaction():
                app = self._db.execute("PRAGMA application_id").fetchone()[0]
                version = self._db.execute("PRAGMA user_version").fetchone()[0]
                tables = self._db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if not tables and app == 0 and version == 0:
                    self._create_schema()
                    capital = initial if initial is not None else Decimal("10000")
                    self._db.execute("INSERT INTO account VALUES (1, 'EUR', ?, ?, '0', 0)",
                                     (str(capital), str(capital)))
                    if strict is True:
                        self._create_strict_schema()
                elif app != APPLICATION_ID or version not in (1, 2, 3):
                    raise ValueError("Not a supported paper-broker ledger")
                elif version == 1 and any(t[0].startswith(('gate_', 'execution_mode', 'operational_')) for t in tables):
                    raise ValueError('Inconsistent strict schema: refusing a silent downgrade')
                elif strict is True and version == 1:
                    raise ValueError('Strict mode must be selected when creating a new ledger')
                self._strict = self._db.execute('PRAGMA user_version').fetchone()[0] in (2, 3)
                if self._strict:
                    mode = self._db.execute('SELECT mode FROM execution_mode WHERE id=1').fetchone()
                    if mode is None or mode[0] != 'strict_synthetic':
                        raise ValueError('Invalid persisted strict mode')
                    if strict is False:
                        raise ValueError('Strict ledgers cannot be downgraded')
                    from tools.operational_controls import migrate_strict_controls
                    migrate_strict_controls(self._db)
                account = self._db.execute("SELECT * FROM account WHERE id=1").fetchone()
                if account is None or account['currency'] != 'EUR':
                    raise ValueError("Invalid paper-broker account")
                if initial is not None and initial != Decimal(account['initial_cash']):
                    raise ValueError("Existing ledger initial capital differs; it will not be reset")
            self.reconcile()
        except BaseException:
            self._db.close()
            raise

    @contextmanager
    def _transaction(self):
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException as exc:
                try:
                    if self._db.in_transaction:
                        self._db.execute("ROLLBACK")
                except BaseException as cleanup:
                    exc.add_note(f'Transaction inspection/rollback also failed: {type(cleanup).__name__}: {cleanup}')
                raise

    def _create_schema(self):
        statements = (
            """CREATE TABLE account (id INTEGER PRIMARY KEY CHECK(id=1), currency TEXT NOT NULL CHECK(currency='EUR'),
               initial_cash TEXT NOT NULL, cash TEXT NOT NULL, realized_pnl TEXT NOT NULL,
               killed INTEGER NOT NULL CHECK(killed IN (0,1)))""",
            """CREATE TABLE orders (order_id TEXT PRIMARY KEY, ticker TEXT NOT NULL,
               side TEXT NOT NULL CHECK(side IN ('BUY','SELL')), quantity INTEGER NOT NULL CHECK(quantity>0),
               status TEXT NOT NULL CHECK(status IN ('CREATED','ACCEPTED','FILLED','REJECTED','CANCELLED')),
               created_at TEXT NOT NULL, updated_at TEXT NOT NULL, reason TEXT)""",
            """CREATE TABLE positions (ticker TEXT PRIMARY KEY, quantity INTEGER NOT NULL CHECK(quantity>0),
               cost_basis TEXT NOT NULL)""",
            """CREATE TABLE fills (order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
               reference_price TEXT NOT NULL, execution_price TEXT NOT NULL, commission TEXT NOT NULL,
               slippage_per_share TEXT NOT NULL, timestamp TEXT NOT NULL, cash_delta TEXT NOT NULL,
               allocated_cost_basis TEXT NOT NULL, realized_pnl TEXT NOT NULL)""",
            """CREATE TABLE audit (sequence INTEGER PRIMARY KEY AUTOINCREMENT,
               order_id TEXT REFERENCES orders(order_id), event TEXT NOT NULL,
               timestamp TEXT NOT NULL, reason TEXT NOT NULL)""",
        )
        for statement in statements:
            self._db.execute(statement)
        self._db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        self._db.execute("PRAGMA user_version=1")

    def close(self):
        self._db.close()

    def _create_strict_schema(self):
        self._db.execute("CREATE TABLE execution_mode (id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL CHECK(mode='strict_synthetic'))")
        self._db.execute("INSERT INTO execution_mode VALUES (1,'strict_synthetic')")
        self._db.execute('CREATE TABLE gate_attempts (attempt_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id), request_sha256 TEXT NOT NULL, outcome TEXT NOT NULL, record_sha256 TEXT NOT NULL, record_json TEXT NOT NULL)')
        self._db.execute("CREATE UNIQUE INDEX gate_success ON gate_attempts(order_id) WHERE outcome='FILLED'")
        self._db.execute('CREATE TABLE gate_holdings (ticker TEXT PRIMARY KEY, terms_json TEXT NOT NULL)')
        self._db.execute('CREATE TABLE gate_order_terms (order_id TEXT PRIMARY KEY REFERENCES orders(order_id), terms_json TEXT NOT NULL)')
        self._db.execute('PRAGMA user_version=2')

    @property
    def strict(self):
        return self._strict

    def execution_state(self):
        """Frozen state identity for an explicit gated request; not authorization."""
        from tools.gated_execution import read_state_locked
        with self._transaction():
            return read_state_locked(self)

    def execute_gated(self, request):
        """Manually invoked synthetic execution; final risk and fill share one lock."""
        from tools.gated_execution import ExecutionRequest, execute_locked
        request = ExecutionRequest.model_validate(request.model_dump(mode='json'))
        with self._transaction():
            if not self._strict:
                raise ValueError('Gated execution requires an explicitly created strict ledger')
            return execute_locked(self, request)

    def execution_attempt(self, attempt_id):
        from tools.gated_execution import load_attempt_locked
        with self._transaction():
            if not self._strict:
                raise ValueError('Not a strict ledger')
            return load_attempt_locked(self, attempt_id)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _event(self, order_id, event, timestamp, reason):
        self._db.execute("INSERT INTO audit(order_id,event,timestamp,reason) VALUES (?,?,?,?)",
                         (order_id, event, timestamp, reason))

    def _order(self, order_id) -> PaperOrder:
        row = self._db.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
        if row is None:
            raise KeyError(order_id)
        return PaperOrder(**dict(row))

    def get_order(self, order_id: str) -> PaperOrder:
        return self._order(order_id)

    def portfolio(self) -> PaperPortfolio:
        with self._transaction():
            a = self._db.execute("SELECT * FROM account WHERE id=1").fetchone()
            positions = tuple(PaperPosition(p['ticker'], p['quantity'], Decimal(p['cost_basis']))
                              for p in self._db.execute("SELECT * FROM positions ORDER BY ticker"))
            return PaperPortfolio(a['currency'], Decimal(a['initial_cash']), Decimal(a['cash']),
                                  Decimal(a['realized_pnl']), positions, bool(a['killed']))

    def audit_events(self) -> tuple[PaperAuditEvent, ...]:
        return tuple(PaperAuditEvent(**dict(row)) for row in self._db.execute("SELECT * FROM audit ORDER BY sequence"))

    def _ensure_time(self, order, timestamp):
        if timestamp < order.updated_at:
            raise ValueError("Timestamp precedes the order's last lifecycle event")

    def create_order(self, order_id: str, ticker: str, side: str, quantity: int, *, timestamp: datetime) -> PaperOrder:
        stamp = _timestamp(timestamp)
        if not isinstance(order_id, str) or not order_id.strip():
            raise ValueError("Nonempty order ID required")
        if not isinstance(ticker, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.^=-]*", ticker):
            raise ValueError("Canonical uppercase ticker required")
        if side not in ('BUY', 'SELL') or type(quantity) is not int or not 0 < quantity <= 1_000_000_000:
            raise ValueError("BUY/SELL and a positive whole-share quantity required")
        with self._transaction():
            existing = self._db.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
            if existing:
                order = PaperOrder(**dict(existing))
                if (ticker, side, quantity) != (order.ticker, order.side, order.quantity):
                    raise ValueError("Order ID conflicts with existing economic instructions")
                return order
            self._db.execute("INSERT INTO orders VALUES (?,?,?,?, 'CREATED',?,?,NULL)",
                             (order_id, ticker, side, quantity, stamp, stamp))
            self._event(order_id, 'CREATED', stamp, 'Explicit paper order creation')
            if self._db.execute("SELECT killed FROM account WHERE id=1").fetchone()[0]:
                self._transition(order_id, 'REJECTED', stamp, 'Kill switch enabled')
            return self._order(order_id)

    def _transition(self, order_id, status, stamp, reason):
        self._db.execute("UPDATE orders SET status=?,updated_at=?,reason=? WHERE order_id=?",
                         (status, stamp, reason, order_id))
        self._event(order_id, status, stamp, reason)

    def accept_order(self, order_id: str, *, timestamp: datetime) -> PaperOrder:
        stamp = _timestamp(timestamp)
        with self._transaction():
            order = self._order(order_id)
            if order.status in ('ACCEPTED', 'FILLED'):
                return order
            if order.status != 'CREATED':
                raise ValueError("Only CREATED orders can be accepted")
            self._ensure_time(order, stamp)
            if self._db.execute("SELECT killed FROM account WHERE id=1").fetchone()[0]:
                self._transition(order_id, 'REJECTED', stamp, 'Kill switch enabled')
            else:
                self._transition(order_id, 'ACCEPTED', stamp, 'Accepted without reservation; fill checks required')
            return self._order(order_id)

    def reject_order(self, order_id: str, *, timestamp: datetime, reason: str) -> PaperOrder:
        return self._terminate(order_id, 'REJECTED', timestamp, reason)

    def cancel_order(self, order_id: str, *, timestamp: datetime, reason: str = 'Explicit cancellation') -> PaperOrder:
        return self._terminate(order_id, 'CANCELLED', timestamp, reason)

    def _terminate(self, order_id, status, timestamp, reason):
        stamp = _timestamp(timestamp)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Audit reason required")
        with self._transaction():
            order = self._order(order_id)
            if order.status == status:
                return order
            allowed = ('CREATED', 'ACCEPTED') if status == 'CANCELLED' else ('CREATED',)
            if order.status not in allowed:
                raise ValueError("Invalid order lifecycle transition")
            self._ensure_time(order, stamp)
            self._transition(order_id, status, stamp, reason)
            return self._order(order_id)

    def set_kill_switch(self, enabled: bool, *, timestamp: datetime, reason: str):
        stamp = _timestamp(timestamp)
        if type(enabled) is not bool or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Boolean kill state and audit reason required")
        with self._transaction():
            self._db.execute("UPDATE account SET killed=? WHERE id=1", (int(enabled),))
            self._event(None, 'KILL_ENABLED' if enabled else 'KILL_DISABLED', stamp, reason)

    def _fill(self, order_id) -> PaperFill | None:
        row = self._db.execute("""SELECT f.*,o.ticker,o.side,o.quantity FROM fills f
                               JOIN orders o USING(order_id) WHERE order_id=?""", (order_id,)).fetchone()
        if row is None:
            return None
        values = dict(row)
        for name in ('reference_price', 'execution_price', 'commission', 'slippage_per_share',
                     'cash_delta', 'allocated_cost_basis', 'realized_pnl'):
            values[name] = Decimal(values[name])
        return PaperFill(**values)

    def fills(self) -> tuple[PaperFill, ...]:
        with self._transaction():
            return self._all_fills()

    def _all_fills(self) -> tuple[PaperFill, ...]:
        # Audit sequence preserves actual execution order when timestamps tie.
        ids = self._db.execute("""SELECT f.order_id FROM fills f JOIN audit a USING(order_id)
                               WHERE a.event='FILLED' ORDER BY a.sequence""").fetchall()
        return tuple(self._fill(row[0]) for row in ids)

    def reconcile(self) -> PaperPortfolio:
        """Reconstruct balances from committed fills and verify stored state.

        Startup runs this check too. It detects inconsistency, not malicious
        edits coordinated across every table; SQLite is not a signed ledger.
        """
        with self._transaction():
            a = self._db.execute("SELECT * FROM account WHERE id=1").fetchone()
            initial = Decimal(a['initial_cash'])
            cash, pnl = initial, Decimal(0)
            holdings = {}
            fills = self._all_fills()
            count = self._db.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
            filled_orders = self._db.execute("SELECT COUNT(*) FROM orders WHERE status='FILLED'").fetchone()[0]
            if len(fills) != count or filled_orders != count:
                raise ValueError("Ledger reconciliation failed: fill/order/audit count")
            for f in fills:
                if self._order(f.order_id).status != 'FILLED':
                    raise ValueError("Ledger reconciliation failed: fill status")
                quantity, basis = holdings.get(f.ticker, (0, Decimal(0)))
                if f.side == 'BUY':
                    quantity += f.quantity
                    basis -= f.cash_delta
                else:
                    quantity -= f.quantity
                    basis -= f.allocated_cost_basis
                cash += f.cash_delta
                pnl += f.realized_pnl
                if cash < 0 or quantity < 0 or basis < 0 or (quantity == 0 and basis != 0):
                    raise ValueError("Ledger reconciliation failed: negative balance or residual cost")
                if quantity:
                    holdings[f.ticker] = (quantity, basis)
                else:
                    holdings.pop(f.ticker, None)
            stored = {p['ticker']: (p['quantity'], Decimal(p['cost_basis']))
                      for p in self._db.execute("SELECT * FROM positions")}
            if (cash != Decimal(a['cash']) or pnl != Decimal(a['realized_pnl']) or holdings != stored
                    or cash + sum((basis for _, basis in holdings.values()), Decimal(0)) != initial + pnl):
                raise ValueError("Ledger reconciliation failed: stored balances differ from fills")
            return PaperPortfolio('EUR', initial, cash, pnl,
                                  tuple(PaperPosition(t, *holdings[t]) for t in sorted(holdings)), bool(a['killed']))

    def simulate_fill(self, order_id: str, *, price, timestamp: datetime,
                      commission=0, slippage_per_share=0) -> PaperFill:
        """Explicit manual fill. No fill quantity: the entire order fills once."""
        reference = _money(price, positive=True)
        fee = _money(commission)
        slippage = _money(slippage_per_share)
        stamp = _timestamp(timestamp)
        with self._transaction():
            if self._strict:
                raise ValueError('Strict ledger: direct manual fills are prohibited')
            fill, blocked = self._simulate_fill_locked(order_id, reference, fee, slippage, stamp)
        if blocked:
            raise ValueError(blocked)
        return fill

    def _simulate_fill_locked(self, order_id, reference, fee, slippage, stamp):
        """Shared accounting; only called while the owning write transaction is active."""
        if not self._db.in_transaction:
            raise ValueError('An active broker transaction is required')
        if self._strict and not getattr(self, '_gate_active', False):
            raise ValueError('Strict ledger requires in-transaction risk authorization')
        if self._strict:
            from tools.operational_controls import read_control
            if read_control(self._db)['blocked']:
                raise ValueError('Operational latch blocks strict execution')
            if not getattr(self, '_integrity_checked', False):
                raise ValueError('Strict fill requires transaction-scoped integrity preflight')
        blocked = None
        order = self._order(order_id)
        old = self._fill(order_id)
        if old is not None:
            if (reference, fee, slippage, stamp) != (
                old.reference_price, old.commission, old.slippage_per_share, old.timestamp,
            ):
                raise ValueError("Conflicting fill retry")
            return old, None
        if order.status != 'ACCEPTED':
            raise ValueError("Only ACCEPTED orders can be filled")
        self._ensure_time(order, stamp)
        last = self._db.execute("SELECT MAX(timestamp) FROM fills").fetchone()[0]
        if last is not None and stamp < last:
            raise ValueError("Execution cannot precede an existing portfolio fill")
        a = self._db.execute("SELECT * FROM account WHERE id=1").fetchone()
        p = self._db.execute("SELECT * FROM positions WHERE ticker=?", (order.ticker,)).fetchone()
        held = p['quantity'] if p else 0
        basis = Decimal(p['cost_basis']) if p else Decimal(0)
        cash, realized = Decimal(a['cash']), Decimal(a['realized_pnl'])
        execution = reference + slippage if order.side == 'BUY' else reference - slippage
        delta = -(execution * order.quantity + fee) if order.side == 'BUY' else execution * order.quantity - fee
        if a['killed']:
            blocked = 'Kill switch enabled'
        elif execution <= 0:
            blocked = 'Nonpositive slipped execution price'
        elif order.side == 'SELL' and held < order.quantity:
            blocked = 'Insufficient holdings'
        elif cash + delta < 0:
            blocked = 'Insufficient cash including execution costs'
        if blocked:
            self._event(order_id, 'FILL_BLOCKED', stamp, blocked)
        else:
            if order.side == 'BUY':
                allocated, pnl = Decimal(0), Decimal(0)
                new_quantity, new_basis = held + order.quantity, basis - delta
            else:
                allocated = basis if order.quantity == held else (
                    basis * order.quantity / held
                ).quantize(QUANTUM, rounding=ROUND_HALF_EVEN)
                pnl = delta - allocated
                new_quantity, new_basis = held - order.quantity, basis - allocated
            self._db.execute("UPDATE account SET cash=?,realized_pnl=? WHERE id=1",
                             (str(cash + delta), str(realized + pnl)))
            if new_quantity:
                self._db.execute("""INSERT INTO positions VALUES (?,?,?) ON CONFLICT(ticker)
                                 DO UPDATE SET quantity=excluded.quantity,cost_basis=excluded.cost_basis""",
                                 (order.ticker, new_quantity, str(new_basis)))
            else:
                self._db.execute("DELETE FROM positions WHERE ticker=?", (order.ticker,))
            self._db.execute("INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?)", (
                order_id, str(reference), str(execution), str(fee), str(slippage), stamp,
                str(delta), str(allocated), str(pnl),
            ))
            self._transition(order_id, 'FILLED', stamp, 'Explicit simulated execution')
            return self._fill(order_id), None
        return None, blocked
