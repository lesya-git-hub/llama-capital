"""Independent read-only ledger capture, accounting reconciliation and replay."""

from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal

from pydantic import AwareDatetime, StrictBool

from tools.historical_snapshot import FrozenModel, canonical_json, input_hash
from tools.gated_execution import ExecutionOutcome, replay_execution_checks, source_hash as gate_source_hash


CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
QUANTUM = Decimal('.000000000001')
BROKER_APP = 0x4C4C5042
WORKFLOW_APP = 1280070487


def stable_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=repr)


class DatabaseSnapshot(FrozenModel):
    identity: str
    content: str


class OperationalSnapshot(FrozenModel):
    broker: DatabaseSnapshot
    workflows: tuple[DatabaseSnapshot, ...] = ()


class MonitoringPolicy(FrozenModel):
    expected_opening_cash: Decimal = Decimal('10000')
    cross_database_capture: Literal['unconfirmed', 'quiescent_asserted'] = 'unconfirmed'


class Finding(FrozenModel):
    code: str
    severity: Literal['WARNING', 'CRITICAL']
    evidence: tuple[str, ...]
    explanation: str
    action: str


class MonitoringReport(FrozenModel):
    schema_version: Literal[1] = 1
    report_id: str
    reported_at: AwareDatetime
    snapshot: OperationalSnapshot
    snapshot_sha256: str
    policy: MonitoringPolicy
    status: Literal['HEALTHY', 'WARNING', 'CRITICAL']
    strict: StrictBool | None
    kill_switch: StrictBool | None
    operational_block: StrictBool | None
    cash_eur: Decimal | None
    holdings_json: str
    order_counts_json: str
    gate_counts_json: str
    workflow_runs_json: str
    reconstructed_json: str
    financial_reconstruction_complete: StrictBool
    evidence_complete: StrictBool
    findings: tuple[Finding, ...]
    limitations: tuple[str, ...]
    engine_sha256: str


def capture_connection(db, identity):
    """Caller holds a read or write transaction; no writes performed here."""
    content = {'application_id': db.execute('PRAGMA application_id').fetchone()[0],
               'user_version': db.execute('PRAGMA user_version').fetchone()[0], 'tables': {}, 'schema': [],
               'columns': {}, 'indexes': {}}
    try:
        content['integrity'] = [tuple(r) for r in db.execute('PRAGMA integrity_check')]
        content['foreign_keys'] = [tuple(r) for r in db.execute('PRAGMA foreign_key_check')]
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        content['schema'] = [tuple(r) for r in schema]
        for kind, name, _, _ in schema:
            if kind == 'table':
                quoted = '"' + name.replace('"', '""') + '"'
                cursor = db.execute(f'SELECT * FROM {quoted}')
                names = [d[0] for d in cursor.description]
                rows = [dict(zip(names, tuple(r))) for r in cursor]
                content['tables'][name] = sorted(rows, key=stable_json)
                content['columns'][name] = [tuple(r) for r in db.execute(f'PRAGMA table_info({quoted})')]
                indexes = []
                for index in db.execute(f'PRAGMA index_list({quoted})').fetchall():
                    index_name = '"' + index[1].replace('"', '""') + '"'
                    indexes.append({'name': index[1], 'unique': index[2], 'partial': index[4],
                        'columns': [r[2] for r in db.execute(f'PRAGMA index_info({index_name})')]})
                content['indexes'][name] = sorted(indexes, key=stable_json)
    except (sqlite3.Error, ValueError) as exc:
        content['capture_error'] = f'{type(exc).__name__}: {exc}'
    return DatabaseSnapshot(identity=identity, content=stable_json(content))


def database_identity(path):
    return os.path.normcase(str(Path(path).resolve()))


def capture_database(path):
    identity = database_identity(path)
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            return capture_connection(db, identity)
    except (sqlite3.Error, OSError) as exc:
        return DatabaseSnapshot(identity=identity, content=stable_json({'capture_error': f'{type(exc).__name__}: {exc}'}))


def capture_operational_state(broker_path, *, workflow_paths=()):
    identities = [database_identity(p) for p in workflow_paths]
    if len(set(identities)) != len(identities) or database_identity(broker_path) in identities:
        raise ValueError('Distinct broker/workflow database paths required')
    return OperationalSnapshot(broker=capture_database(broker_path),
        workflows=tuple(capture_database(p) for p in sorted(workflow_paths, key=database_identity)))


def _decimal(value):
    if isinstance(value, (float, bool)) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('Explicit finite Decimal amount required')
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError('Nonfinite accounting amount')
    return number


def _time(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError('Stored broker timestamps must be timezone-aware UTC')
    return stamp


def _view(tables):
    account = tables['account'][0]
    return (_decimal(account['cash']), _decimal(account['realized_pnl']),
            {p['ticker']: (p['quantity'], _decimal(p['cost_basis'])) for p in tables['positions']})


def reconcile_snapshot(snapshot, *, report_id, reported_at, policy=MonitoringPolicy()):
    snapshot = OperationalSnapshot.model_validate(snapshot.model_dump(mode='json'))
    policy = MonitoringPolicy.model_validate(policy.model_dump(mode='json'))
    if not report_id.strip() or not isinstance(reported_at, datetime) or reported_at.tzinfo is None or reported_at.utcoffset() is None:
        raise ValueError('Nonblank report identity and explicit aware time required')
    if not policy.expected_opening_cash.is_finite() or policy.expected_opening_cash <= 0:
        raise ValueError('Positive expected opening cash required')
    findings = []
    def add(code, message, *refs, severity='CRITICAL'):
        findings.append(Finding(code=code, severity=severity, evidence=tuple(str(r) for r in refs),
            explanation=message, action='Investigate and preserve evidence; no automatic repair.' if severity == 'CRITICAL'
            else 'Inspect evidence and resolve or explicitly acknowledge the limitation.'))
    raw = json.loads(snapshot.broker.content)
    tables = raw.get('tables', {})
    required = {'account', 'positions', 'orders', 'fills', 'audit'}
    strict = None
    kill = blocked = cash = None
    reconstructed, counts, gate_counts, runs = {}, {}, {}, []
    financial_complete = evidence_complete = False
    if raw.get('capture_error') or raw.get('integrity') != [['ok']]:
        add('DATABASE_INTEGRITY', 'Database cannot be fully and consistently inspected', snapshot.broker.identity, raw.get('capture_error', raw.get('integrity')))
    if raw.get('foreign_keys'):
        add('FOREIGN_KEY_CONFLICT', 'Broken ledger foreign-key references', raw['foreign_keys'])
    if raw.get('application_id') != BROKER_APP or raw.get('user_version') not in (1, 2, 3, 4):
        add('UNSUPPORTED_LEDGER', 'Invalid broker application/schema identity', snapshot.broker.identity)
    from tools.restore_quarantine import validate_fence
    try:
        if raw.get('user_version') == 4:
            validate_fence(tables.get('restore_fence', []))
        elif 'restore_fence' in tables:
            raise ValueError('Restore schema downgrade')
    except (ValueError, KeyError, TypeError) as exc:
        add('RESTORE_FENCE_INVALID', 'Restore quarantine evidence is missing or inconsistent', str(exc))
    if not required <= tables.keys():
        add('MISSING_LEDGER_TABLE', 'Required financial evidence is missing', sorted(required - tables.keys()))
    else:
        primary_keys = {'account': 'id', 'orders': 'order_id', 'positions': 'ticker', 'fills': 'order_id',
            'audit': 'sequence', 'execution_mode': 'id', 'gate_attempts': 'attempt_id', 'gate_holdings': 'ticker',
            'gate_order_terms': 'order_id', 'operational_control': 'id', 'operational_events': 'sequence',
            'restore_fence': 'id'}
        for table, primary in primary_keys.items():
            if table in tables and [c[1] for c in raw.get('columns', {}).get(table, []) if c[5]] != [primary]:
                add('SCHEMA_CONSTRAINT_MISSING', 'Required primary-key constraint is absent or changed', table, primary)
        required_columns = {
            'account': {'id', 'currency', 'initial_cash', 'cash', 'realized_pnl', 'killed'},
            'orders': {'order_id', 'ticker', 'side', 'quantity', 'status', 'created_at', 'updated_at', 'reason'},
            'positions': {'ticker', 'quantity', 'cost_basis'},
            'fills': {'order_id', 'reference_price', 'execution_price', 'commission', 'slippage_per_share', 'timestamp', 'cash_delta', 'allocated_cost_basis', 'realized_pnl'},
            'audit': {'sequence', 'order_id', 'event', 'timestamp', 'reason'},
            'gate_attempts': {'attempt_id', 'order_id', 'request_sha256', 'outcome', 'record_sha256', 'record_json'},
            'operational_control': {'id', 'blocked', 'block_id', 'report_sha256', 'activated_at'},
            'operational_events': {'sequence', 'event_id', 'request_sha256', 'content_json', 'sha256'},
            'restore_fence': {'id', 'quarantined', 'receipt_json', 'receipt_sha256'},
        }
        for table, columns in required_columns.items():
            if table in tables and not columns <= {c[1] for c in raw.get('columns', {}).get(table, [])}:
                add('SCHEMA_COLUMNS_MISSING', 'Required evidence columns are missing', table)
        if 'gate_attempts' in tables and not any(i['unique'] and i['partial'] and i['columns'] == ['order_id']
                                               for i in raw.get('indexes', {}).get('gate_attempts', [])):
            add('SCHEMA_CONSTRAINT_MISSING', 'Strict successful-fill uniqueness index is absent', 'gate_success')
        strict = raw.get('user_version') in (2, 3, 4)
        strict_tables = {'execution_mode', 'gate_attempts', 'gate_holdings', 'gate_order_terms'}
        if strict and not strict_tables <= tables.keys():
            add('MISSING_STRICT_AUTHORITY', 'Required strict gate evidence tables are absent', sorted(strict_tables - tables.keys()))
        if strict and tables.get('execution_mode') != [{'id': 1, 'mode': 'strict_synthetic'}]:
            add('STRICT_MODE_CONFLICT', 'Persisted strict-mode identity is missing or inconsistent', 'execution_mode')
        if not strict and any(t.startswith(('gate_', 'execution_mode', 'operational_', 'restore_')) for t in tables):
            add('STRICT_DOWNGRADE', 'Legacy version conflicts with persisted strict/control evidence', 'schema')
        try:
            with localcontext(CONTEXT):
                account = tables['account']
                if len(account) != 1 or account[0]['id'] != 1 or account[0]['currency'] != 'EUR':
                    raise ValueError('Exactly one EUR account required')
                a = account[0]
                cash = _decimal(a['cash'])
                if a['killed'] not in (0, 1):
                    raise ValueError('Invalid kill-switch value')
                kill = bool(a['killed'])
                opening = _decimal(a['initial_cash'])
                if opening != policy.expected_opening_cash:
                    add('OPENING_CASH_MISMATCH', 'Stored opening capital differs from independently supplied policy', f'expected={policy.expected_opening_cash}', f'actual={opening}')
                orders, fills = tables['orders'], tables['fills']
                for name, rows, key in (('ORDER', orders, 'order_id'), ('FILL', fills, 'order_id'), ('POSITION', tables['positions'], 'ticker')):
                    for identity, number in Counter(r[key] for r in rows).items():
                        if number != 1:
                            add('DUPLICATE_' + name, 'Duplicate authoritative identity', f'{name}:{identity}', f'count={number}')
                order_map = {o['order_id']: o for o in orders}
                fill_map = {f['order_id']: f for f in fills}
                events = sorted(tables['audit'], key=lambda e: e['sequence'])
                sequences = [e['sequence'] for e in events]
                if sequences != list(range(1, len(sequences) + 1)):
                    add('AUDIT_SEQUENCE_GAP', 'Missing or duplicate sequenced audit evidence', 'audit.sequence', severity='WARNING')
                event_states, filled_ids, killed = {}, [], False
                allowed = {'CREATED': (None,), 'ACCEPTED': ('CREATED',), 'FILLED': ('ACCEPTED',),
                           'CANCELLED': ('CREATED', 'ACCEPTED'), 'REJECTED': ('CREATED',)}
                for event in events:
                    _time(event['timestamp'])
                    identity, kind = event['order_id'], event['event']
                    if kind in ('KILL_ENABLED', 'KILL_DISABLED'):
                        if identity is not None:
                            add('AUDIT_LIFECYCLE_CONFLICT', 'Kill event unexpectedly names an order', event['sequence'])
                        killed = kind == 'KILL_ENABLED'
                    elif kind == 'FILL_BLOCKED':
                        if event_states.get(identity) != 'ACCEPTED':
                            add('AUDIT_LIFECYCLE_CONFLICT', 'Blocked fill lacks accepted lifecycle', identity, event['sequence'])
                    elif kind in allowed:
                        if identity not in order_map or event_states.get(identity) not in allowed[kind]:
                            add('AUDIT_LIFECYCLE_CONFLICT', 'Invalid or missing order lifecycle evidence', identity, kind, event['sequence'])
                        event_states[identity] = kind
                        if kind == 'FILLED':
                            filled_ids.append(identity)
                            if killed:
                                add('FILL_WHILE_KILLED', 'Fill sequence occurred while kill switch was enabled', identity, event['sequence'])
                    else:
                        add('UNKNOWN_AUDIT_EVENT', 'Unrecognized historical event', kind, event['sequence'], severity='WARNING')
                if killed != kill:
                    add('KILL_STATE_CONFLICT', 'Stored kill state differs from sequenced events', f'stored={kill}', f'events={killed}')
                for identity, o in order_map.items():
                    if _time(o['updated_at']) < _time(o['created_at']):
                        add('ORDER_TIME_CONFLICT', 'Order update predates creation', identity)
                    if event_states.get(identity) != o['status']:
                        add('ORDER_STATUS_CONFLICT', 'Current status differs from authoritative lifecycle', identity, o['status'], event_states.get(identity))
                    if (o['status'] == 'FILLED') != (identity in fill_map):
                        add('FILL_STATUS_CONFLICT', 'Fill record and current order status disagree', identity)
                for identity, number in Counter(filled_ids).items():
                    if number != 1:
                        add('DUPLICATE_FILL', 'More than one FILLED audit event', identity, number)
                if set(filled_ids) != set(fill_map):
                    add('INCOMPLETE_FILL_HISTORY', 'Raw fills lack exact FILLED audit sequence coverage', sorted(set(filled_ids) ^ set(fill_map)))
                expected_cash, pnl, held, checkpoints = opening, Decimal(0), {}, {}
                financial_complete = (len(filled_ids) == len(set(filled_ids)) == len(fills)
                    and set(filled_ids) == set(fill_map) and set(fill_map) <= set(order_map))
                if financial_complete:
                    for identity in filled_ids:
                        o, f = order_map[identity], fill_map[identity]
                        fill_time = _time(f['timestamp'])
                        fill_event = next(e for e in events if e['event'] == 'FILLED' and e['order_id'] == identity)
                        if fill_time != _time(fill_event['timestamp']) or fill_time < _time(o['created_at']):
                            add('FILL_TIME_CONFLICT', 'Fill timestamp conflicts with lifecycle evidence', identity)
                        q = o['quantity']
                        if type(q) is not int or q <= 0 or o['side'] not in ('BUY', 'SELL'):
                            raise ValueError('Invalid whole-share fill instruction')
                        reference, fee, slip = (_decimal(f[k]) for k in ('reference_price', 'commission', 'slippage_per_share'))
                        if reference <= 0 or fee < 0 or slip < 0:
                            raise ValueError('Invalid execution price/cost')
                        execution = reference + slip if o['side'] == 'BUY' else reference - slip
                        if execution <= 0:
                            raise ValueError('Nonpositive adverse execution price')
                        prior_q, prior_basis = held.get(o['ticker'], (0, Decimal(0)))
                        before = (expected_cash, pnl, dict(held))
                        if o['side'] == 'BUY':
                            delta, allocated, realized = -(q * execution + fee), Decimal(0), Decimal(0)
                            after_q, after_basis = prior_q + q, prior_basis - delta
                        else:
                            if q > prior_q:
                                raise ValueError('Historical oversell')
                            allocated = prior_basis if q == prior_q else (prior_basis * q / prior_q).quantize(QUANTUM)
                            delta = q * execution - fee
                            realized = delta - allocated
                            after_q, after_basis = prior_q - q, prior_basis - allocated
                        for field, expected in (('execution_price', execution), ('cash_delta', delta),
                                                ('allocated_cost_basis', allocated), ('realized_pnl', realized)):
                            if _decimal(f[field]) != expected:
                                add('FILL_ARITHMETIC_MISMATCH', 'Stored fill arithmetic differs from independent reconstruction', identity, field, f'expected={expected}', f'actual={f[field]}')
                        expected_cash += delta
                        pnl += realized
                        if expected_cash < 0 or after_q < 0 or after_basis < 0 or (not after_q and after_basis != 0):
                            add('NEGATIVE_FINANCIAL_STATE', 'Reconstructed fill violates long-only cash/basis constraints', identity)
                        if after_q:
                            held[o['ticker']] = (after_q, after_basis)
                        else:
                            held.pop(o['ticker'], None)
                        checkpoints[identity] = (before, (expected_cash, pnl, dict(held)))
                    if cash != expected_cash:
                        add('CASH_MISMATCH', 'Materialized cash differs from independently reconstructed cash', f'expected={expected_cash}', f'actual={cash}')
                    if _decimal(a['realized_pnl']) != pnl:
                        add('REALIZED_PNL_MISMATCH', 'Stored realized P&L differs from reconstructed history', f'expected={pnl}', f'actual={a["realized_pnl"]}')
                    stored = {p['ticker']: (p['quantity'], _decimal(p['cost_basis'])) for p in tables['positions']}
                    if {t: v[0] for t, v in stored.items()} != {t: v[0] for t, v in held.items()}:
                        add('HOLDINGS_MISMATCH', 'Materialized share quantities differ from reconstructed history', str(stored), str(held))
                    if {t: v[1] for t, v in stored.items()} != {t: v[1] for t, v in held.items()}:
                        add('COST_BASIS_MISMATCH', 'Materialized cost basis differs from reconstructed history', str(stored), str(held))
                    reconstructed = {'cash_eur': str(expected_cash), 'realized_pnl_eur': str(pnl),
                        'positions': {t: {'quantity': q, 'cost_basis_eur': str(b), 'average_entry_cost_eur': str(b / q)} for t, (q, b) in sorted(held.items())}}
                if strict:
                    _check_gates(tables, order_map, fill_map, checkpoints, add)
                counts = dict(sorted(Counter(o['status'] for o in orders).items()))
                gate_counts = dict(sorted(Counter(g['outcome'] for g in tables.get('gate_attempts', [])).items()))
                blocked = _check_controls(raw, add)
                evidence_complete = financial_complete and not any(f.severity == 'WARNING' for f in findings)
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            financial_complete = evidence_complete = False
            add('MALFORMED_FINANCIAL_EVIDENCE', f'Cannot complete independent reconstruction: {type(exc).__name__}: {exc}', 'broker snapshot')
    for workflow in snapshot.workflows:
        _check_workflow(workflow, snapshot.broker.identity, tables, policy, runs, add)
    if any(g.get('attempt_id', '').startswith('workflow:') for g in tables.get('gate_attempts', [])) and not snapshot.workflows:
        add('WORKFLOW_SCOPE_NOT_INSPECTED', 'Workflow gate attempts exist but no sidecar was supplied', snapshot.broker.identity, severity='WARNING')
    evidence_complete = financial_complete and not findings
    severity = 'CRITICAL' if any(f.severity == 'CRITICAL' for f in findings) else 'WARNING' if findings else 'HEALTHY'
    findings.sort(key=lambda f: (0 if f.severity == 'CRITICAL' else 1, f.code, f.evidence, f.explanation))
    return MonitoringReport(report_id=report_id, reported_at=reported_at.astimezone(timezone.utc), snapshot=snapshot,
        snapshot_sha256=input_hash(snapshot), policy=policy, status=severity, strict=strict, kill_switch=kill,
        operational_block=blocked, cash_eur=cash, holdings_json=stable_json(tables.get('positions', [])),
        order_counts_json=stable_json(counts), gate_counts_json=stable_json(gate_counts), workflow_runs_json=stable_json(runs),
        reconstructed_json=stable_json(reconstructed), financial_reconstruction_complete=financial_complete,
        evidence_complete=evidence_complete, findings=tuple(findings), limitations=(
            'Operational integrity only; cost basis is not market value or investment performance.',
            'Opening cash is checked against supplied policy; no independent signed deposit history exists.',
            'Synthetic/unverified FX provenance is not real-world price or source authority.',
            'Cross-database captures are not atomic; quiescence is a caller assertion.',
            'Legacy ledgers are not operational-latch enforced.',
            'Reports never activate/clear controls, repair records or authorize fills; hashes are not tamper-proof.'),
        engine_sha256=sha256(Path(__file__).read_bytes()).hexdigest())


def _check_gates(tables, orders, fills, checkpoints, add):
    successes = Counter()
    for row in tables.get('gate_attempts', []):
        identity = row['attempt_id']
        try:
            record = ExecutionOutcome.model_validate_json(row['record_json'])
            if (input_hash(record) != row['record_sha256'] or input_hash(record.request) != row['request_sha256']
                    or record.request.attempt_id != identity or record.request.order_id != row['order_id'] or record.status != row['outcome']):
                raise ValueError('Gate envelope/hash identity conflict')
            if record.status == 'REJECTED':
                if record.before != record.after or record.fill_json is not None:
                    add('REJECTION_STATE_MUTATION', 'Rejected gate outcome contains a financial mutation', identity)
            else:
                if row['order_id'] not in fills or record.fill_json is None or record.risk is None or record.risk.decision != 'APPROVED':
                    raise ValueError('Successful gate lacks approved risk or broker fill')
                f, observed = fills[row['order_id']], json.loads(record.fill_json)
                order = orders[row['order_id']]
                if (observed['order_id'], observed['ticker'], observed['side'], observed['quantity']) != (order['order_id'], order['ticker'], order['side'], order['quantity']):
                    raise ValueError('Gate and broker economic instructions conflict')
                for field in ('reference_price', 'execution_price', 'commission', 'slippage_per_share', 'cash_delta', 'allocated_cost_basis', 'realized_pnl'):
                    if _decimal(observed[field]) != _decimal(f[field]):
                        raise ValueError(f'Gate and broker {field} conflict')
                if observed['timestamp'] != f['timestamp']:
                    raise ValueError('Gate and broker fill timestamps conflict')
                if row['order_id'] in checkpoints:
                    for state, expected in zip((record.before, record.after), checkpoints[row['order_id']]):
                        if _view(json.loads(state.content)) != expected:
                            raise ValueError('Gate state conflicts with independently reconstructed timeline')
            if record.execution_source_sha256 != gate_source_hash():
                add('REPLAY_ENVIRONMENT_UNAVAILABLE', 'Historical gate source differs; archived checkout needed for full replay', identity, severity='WARNING')
            else:
                replay_execution_checks(record, expected_sha256=row['record_sha256'])
            if record.status == 'FILLED':
                successes[row['order_id']] += 1
        except Exception as exc:
            add('GATE_AUDIT_CONFLICT', f'Invalid required gate evidence: {type(exc).__name__}: {exc}', identity)
    for identity in fills:
        if successes[identity] != 1:
            add('STRICT_FILL_WITHOUT_GATE', 'Strict fill requires exactly one valid successful gate audit', identity, f'count={successes[identity]}')
    if {h['ticker'] for h in tables.get('gate_holdings', [])} != {p['ticker'] for p in tables['positions']}:
        add('HELD_STOP_PROVENANCE_MISSING', 'Held positions do not have exact persisted stop metadata', 'gate_holdings')


def _check_controls(raw, add):
    tables = raw['tables']
    if raw['user_version'] < 3:
        if raw['user_version'] == 2:
            if {'operational_control', 'operational_events'} & tables.keys():
                add('OPERATIONAL_SCHEMA_CONFLICT', 'Version-2 label conflicts with already persisted operational-control evidence; migration must not reset it', 'schema')
            else:
                add('OPERATIONAL_LATCH_NOT_INSTALLED', 'Version-2 strict ledger needs the explicit supported migration/open path', 'schema', severity='WARNING')
        return None
    if not {'operational_control', 'operational_events'} <= tables.keys():
        add('MISSING_OPERATIONAL_AUTHORITY', 'Version-3 strict ledger lacks required operational latch/audit tables', 'schema')
        return None
    rows = tables.get('operational_control', [])
    if len(rows) != 1 or rows[0].get('id') != 1 or rows[0].get('blocked') not in (0, 1):
        add('OPERATIONAL_CONTROL_INVALID', 'Missing or invalid persisted operational latch', 'operational_control')
        return None
    control = rows[0]
    active, active_event = None, None
    for row in sorted(tables.get('operational_events', []), key=lambda r: r['sequence']):
        try:
            event = json.loads(row['content_json'])
            if sha256(row['content_json'].encode()).hexdigest() != row['sha256'] or event['event_id'] != row['event_id']:
                raise ValueError('Control-event integrity conflict')
            _time(event['timestamp'])
            if not event['operator_id'].strip() or not event['reason'].strip():
                raise ValueError('Control action lacks operator/reason evidence')
            if event['action'] == 'ACTIVATED':
                source = {k: event[k] for k in ('action', 'event_id', 'operator_id', 'reason', 'timestamp', 'report_sha256')}
                if sha256(stable_json(source).encode()).hexdigest() != row['request_sha256'] or active is not None:
                    raise ValueError('Activation request/hash or sequence conflict')
                active, active_event = event['block_id'], event
            elif event['action'] == 'RELEASED':
                if active != event['block_id']: raise ValueError('Recovery names the wrong block')
                active, active_event = None, None
            elif event['action'] != 'DENIED': raise ValueError('Unknown control action')
            if event['action'] in ('RELEASED', 'DENIED'):
                from tools.operational_controls import RecoveryRequest
                request = RecoveryRequest(recovery_id=event['event_id'], block_id=event['block_id'],
                    operator_id=event['operator_id'], authorization_id=event['authorization_id'],
                    reason=event['reason'], timestamp=event['timestamp'], report_sha256=event['report_sha256'])
                if input_hash(request) != row['request_sha256']:
                    raise ValueError('Recovery request/hash conflict')
        except Exception as exc:
            add('OPERATIONAL_AUDIT_CONFLICT', str(exc), row.get('event_id'))
    if bool(control['blocked']) != (active is not None) or control.get('block_id') != active:
        add('OPERATIONAL_STATE_CONFLICT', 'Latch state differs from sequenced activation/recovery evidence', 'operational_control')
    if (active_event is not None and (control.get('report_sha256') != active_event['report_sha256']
            or control.get('activated_at') != active_event['timestamp'])) or (active is None and
            (control.get('report_sha256') is not None or control.get('activated_at') is not None)):
        add('OPERATIONAL_STATE_CONFLICT', 'Latch metadata conflicts with activation/release evidence', 'operational_control')
    return bool(control['blocked'])


def _check_workflow(snapshot, broker_identity, broker_tables, policy, runs, add):
    raw = json.loads(snapshot.content)
    if raw.get('capture_error') or raw.get('application_id') != WORKFLOW_APP or raw.get('user_version') != 1:
        add('WORKFLOW_CAPTURE_INVALID', 'Workflow evidence cannot be inspected', snapshot.identity, severity='WARNING')
        return
    if raw.get('integrity') != [['ok']] or raw.get('foreign_keys'):
        add('WORKFLOW_DATABASE_INTEGRITY', 'Workflow SQLite integrity/foreign-key checks failed', snapshot.identity)
    tables = raw.get('tables', {})
    if not {'previews', 'authorizations', 'steps', 'reports'} <= tables.keys():
        add('WORKFLOW_CAPTURE_INVALID', 'Missing workflow audit tables', snapshot.identity)
        return
    for table, key in (('previews', lambda r: r['run_id']), ('authorizations', lambda r: r['run_id']),
                       ('steps', lambda r: (r['run_id'], r['order_id'])), ('reports', lambda r: r['sha256'])):
        try:
            if any(n != 1 for n in Counter(key(r) for r in tables[table]).values()):
                add('WORKFLOW_AUDIT_CONFLICT', 'Duplicate immutable workflow record identity', snapshot.identity, table)
        except KeyError:
            add('WORKFLOW_CAPTURE_INVALID', 'Required workflow identity columns are missing', snapshot.identity, table)
            return
    from tools.paper_orchestration import WorkflowPreview, Authorization, WorkflowReport
    previews = {}
    authorizations = {}
    for row in tables['previews']:
        try:
            preview = WorkflowPreview.model_validate_json(row['content'])
            if input_hash(preview) != row['sha256'] or preview.input.run_id != row['run_id']:
                raise ValueError('Preview identity/hash mismatch')
            previews[row['run_id']] = preview
            if preview.ledger_identity != broker_identity:
                add('WORKFLOW_LEDGER_MISMATCH', 'Workflow preview belongs to a different ledger', row['run_id'], snapshot.identity, severity='WARNING')
            runs.append({'journal': snapshot.identity, 'run_id': row['run_id'], 'phase': 'PREVIEW'})
        except Exception as exc:
            add('WORKFLOW_AUDIT_CONFLICT', str(exc), snapshot.identity, row['run_id'])
    for row in tables['authorizations']:
        try:
            auth = Authorization.model_validate_json(row['content'])
            if (input_hash(auth) != row['sha256'] or auth.run_id != row['run_id'] or auth.run_id not in previews
                    or auth.preview_sha256 != input_hash(previews[auth.run_id])):
                raise ValueError('Authorization reference/hash mismatch')
            authorizations[auth.run_id] = auth
            runs.append({'journal': snapshot.identity, 'run_id': auth.run_id, 'phase': 'AUTHORIZED'})
        except Exception as exc:
            add('WORKFLOW_AUDIT_CONFLICT', str(exc), snapshot.identity, row['run_id'])
    attempts = {a['attempt_id']: a for a in broker_tables.get('gate_attempts', [])}
    reported_runs, completed_runs, incomplete_reports = set(), set(), []
    for row in tables['steps']:
        try:
            from tools.gated_execution import ExecutionRequest
            request = ExecutionRequest.model_validate_json(row['request_json'])
            if input_hash(request) != row['request_sha256'] or request.order_id != row['order_id']:
                raise ValueError('Prepared request identity/hash mismatch')
            if row['run_id'] not in authorizations:
                raise ValueError('Prepared workflow step has no valid authorization')
            if previews[row['run_id']].ledger_identity != broker_identity:
                continue
            gate = attempts.get(request.attempt_id)
            if gate is None:
                severity = 'CRITICAL' if row['outcome_json'] is not None and policy.cross_database_capture == 'quiescent_asserted' else 'WARNING'
                add('INCOMPLETE_WORKFLOW', 'Prepared step has no observed broker attempt; do not resume automatically', row['run_id'], row['order_id'], severity=severity)
            elif gate['request_sha256'] != row['request_sha256']:
                add('WORKFLOW_OUTCOME_CONFLICT', 'Prepared request conflicts with broker authority', row['run_id'], row['order_id'])
            elif row['outcome_json'] is None:
                add('WORKFLOW_COMMIT_GAP', 'Broker committed; workflow sidecar outcome update is missing', row['run_id'], row['order_id'], severity='WARNING')
            elif row['outcome_sha256'] != gate['record_sha256'] or row['outcome_json'] != gate['record_json']:
                add('WORKFLOW_OUTCOME_CONFLICT', 'Workflow and broker outcomes conflict', row['run_id'], row['order_id'])
        except Exception as exc:
            add('WORKFLOW_AUDIT_CONFLICT', str(exc), snapshot.identity, row.get('run_id'))
    for row in tables['reports']:
        try:
            report = WorkflowReport.model_validate_json(row['content'])
            if input_hash(report) != row['sha256'] or report.run_id != row['run_id']:
                raise ValueError('Report hash/identity conflict')
            if (report.run_id not in previews or report.run_id not in authorizations
                    or report.preview_sha256 != input_hash(previews[report.run_id])
                    or report.authorization != authorizations[report.run_id]
                    or report.authorization_sha256 != input_hash(report.authorization)):
                raise ValueError('Workflow report preview/authorization reference conflict')
            preview = previews[report.run_id]
            if tuple(s.signal_sha256 for s in report.steps) != tuple(s.signal_sha256 for s in preview.steps):
                raise ValueError('Workflow report has incomplete signal coverage')
            for step, original in zip(report.steps, preview.steps):
                if step.status == 'FILLED' and step.outcome is None:
                    raise ValueError('Filled workflow step lacks broker authority')
                if report.status == 'COMPLETED' and original.status == 'PROPOSED' and step.status != 'FILLED':
                    raise ValueError('Completed workflow has uncompleted proposed instructions')
                if step.outcome is not None:
                    if (step.outcome_sha256 != input_hash(step.outcome) or step.order_id != step.outcome.request.order_id
                            or step.status != step.outcome.status):
                        raise ValueError('Workflow step/outcome identity conflict')
                    if preview.ledger_identity == broker_identity:
                        gate = attempts.get(step.outcome.request.attempt_id)
                        if gate is None:
                            add('WORKFLOW_REFERENCE_UNAVAILABLE', 'Reported outcome has no observed broker row; confirm a quiescent capture', report.run_id,
                                step.order_id, severity='CRITICAL' if policy.cross_database_capture == 'quiescent_asserted' else 'WARNING')
                        elif gate['record_sha256'] != step.outcome_sha256:
                            raise ValueError('Reported outcome conflicts with broker audit')
            reported_runs.add(report.run_id)
            if report.status == 'COMPLETED': completed_runs.add(report.run_id)
            runs.append({'journal': snapshot.identity, 'run_id': report.run_id, 'phase': report.status})
            if report.status in ('INTERRUPTED', 'PARTIAL'):
                incomplete_reports.append(report.run_id)
        except Exception as exc:
            add('WORKFLOW_AUDIT_CONFLICT', str(exc), snapshot.identity, row.get('run_id'))
    for identity in sorted(set(incomplete_reports) - completed_runs):
        add('PARTIAL_WORKFLOW', 'Workflow records partial or interrupted batch completion', identity, severity='WARNING')
    for identity in sorted(set(authorizations) - reported_runs):
        add('WORKFLOW_REPORT_MISSING', 'Authorized run has no complete observed batch report', identity, severity='WARNING')


def monitor(broker_path, *, report_id, reported_at, workflow_paths=(), policy=MonitoringPolicy()):
    return reconcile_snapshot(capture_operational_state(broker_path, workflow_paths=workflow_paths),
        report_id=report_id, reported_at=reported_at, policy=policy)


def replay_report(report, *, expected_sha256):
    report = MonitoringReport.model_validate(report.model_dump(mode='json'))
    if input_hash(report) != expected_sha256:
        raise ValueError('Monitoring report integrity mismatch')
    regenerated = reconcile_snapshot(report.snapshot, report_id=report.report_id, reported_at=report.reported_at, policy=report.policy)
    if regenerated != report:
        raise ValueError('Monitoring replay differs from recorded evidence/policy/implementation')
    return regenerated


def human_report(report):
    lines = [f'Operational report {report.report_id}: {report.status}', f'Ledger: {report.snapshot.broker.identity}',
        f'Strict={report.strict}; kill={report.kill_switch}; operational block={report.operational_block}',
        f'Virtual EUR cash={report.cash_eur}; holdings at cost={report.holdings_json}',
        f'Orders={report.order_counts_json}; gate outcomes={report.gate_counts_json}; workflows={report.workflow_runs_json}',
        'Operational integrity only; no market valuation, execution authorization or investment-performance claim.']
    if json.loads(report.snapshot.broker.content).get('user_version') == 4:
        lines.append('RESTORE QUARANTINE: inspection-only ledger; no execution release exists in Sprint 1K.')
    if report.operational_block:
        control = json.loads(report.snapshot.broker.content).get('tables', {}).get('operational_control', [{}])[0]
        lines.append(f'Operational block {control.get("block_id")} remains active; activation report={control.get("report_sha256")}. Investigate durable evidence and use explicit authorized recovery. A healthy report does not clear it.')
    lines += [f'{f.severity} {f.code}: {f.explanation}; evidence={f.evidence}; action={f.action}' for f in report.findings]
    lines += list(report.limitations)
    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Read-only synthetic broker reconciliation; never fills or repairs.')
    parser.add_argument('--broker', required=True)
    parser.add_argument('--workflow', action='append', default=[])
    parser.add_argument('--report-id', required=True)
    parser.add_argument('--at', required=True, help='Explicit timezone-aware ISO timestamp')
    parser.add_argument('--expected-cash', default='10000')
    parser.add_argument('--output', help='New JSON artifact; refuses to overwrite any existing file')
    args = parser.parse_args()
    if args.output and database_identity(args.output) in {database_identity(p) for p in (args.broker, *args.workflow)}:
        parser.error('Report output must be separate from every source database, including a missing source.')
    result = monitor(args.broker, report_id=args.report_id, reported_at=datetime.fromisoformat(args.at),
        workflow_paths=args.workflow, policy=MonitoringPolicy(expected_opening_cash=args.expected_cash))
    if args.output:
        with open(args.output, 'x', encoding='utf-8') as output:
            output.write(canonical_json(result))
    print(human_report(result))
