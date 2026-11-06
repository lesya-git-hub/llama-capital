# Reproducing V1 offline research

Use an existing configured project environment. Do not use the legacy download
scripts for offline reproduction. No market access or dependency synchronization
is required.

## Regression and release checks (PowerShell)

```powershell
$env:UV_NO_SYNC = '1'
uv run pytest -q
uv run pytest tests/test_release_gate.py -q
```

The gates exercise deterministic replay, identity/provenance rejection,
calendar/currency compatibility, reconciliation, invalid evaluation boundaries,
and future-suffix perturbation tests. The fixtures are synthetic and their
returns are not historical investment results.

## Replay a previously frozen portfolio experiment

Keep the experiment JSON and its independently recorded expected SHA-256.
Use the recorded Git checkout, matching execution-source fingerprint, Python
patch version and recorded dependency versions. Do not silently regenerate the
experiment under a new commit or replace its expected hash to bypass a mismatch.

```python
from tools.historical_snapshot import canonical_json
from tools.portfolio_research import load_portfolio_experiment, replay_portfolio_experiment
from tools.release_gate import check_portfolio_release_gate

expected = "<the separately recorded experiment SHA-256>"
experiment = load_portfolio_experiment("portfolio_experiment.json", expected_sha256=expected)
gate = check_portfolio_release_gate(experiment, expected_sha256=expected)
report = replay_portfolio_experiment(experiment, expected_sha256=expected)
print(canonical_json(gate))
print(canonical_json(report))
```

Gate success is scoped to software invariants for that experiment. It does not
prove that signals were generated causally, vendor data are accurate, or a
strategy has an edge. The code validates causal behavior on test fixtures;
arbitrary externally supplied frozen signals remain the producer's responsibility.

For new frozen inputs, follow [snapshot v1](historical_snapshot_v1.md) and
[portfolio integration](offline_portfolio_research_v1.md). Preserve the original
signal provenance, effective parameters, experiment file/hash and report/hash.
New input or settings produce a new experiment, never a rewrite of old results.

## Check an evaluation boundary without running market data

```python
from datetime import date
from tools.release_gate import validate_holdout_boundary

dates = tuple(bar.date for bar in experiment.snapshot.tickers[0].bars)
signal_row, end_row = validate_holdout_boundary(
    dates, training_start=date(2020, 1, 1), training_end=date(2025, 1, 1),
    holdout_start=date(2025, 1, 1), holdout_end=date(2026, 11, 1),
    minimum_history=200,
)
```

This check requires the full history, including warmup, and returns the preceding
signal row and exclusive evaluation end row. It does not slice/rebase a frozen
experiment or certify that its reported curve is holdout-only. That requires an
explicit separately frozen evaluation artifact. It does not change the fact that
2025–2026 was previously inspected. No such historical artifact is manufactured
by the release audit.
