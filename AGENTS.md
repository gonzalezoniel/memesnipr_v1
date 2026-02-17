# MEMESNIPR Engineering Guide

## Mission priorities
1. Safety first (fail closed).
2. Paper-trade determinism before live execution.
3. Decision auditability for every candidate.

## Setup steps
1. Use Python 3.12+.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Bootstrap environment file:
   - `cp .env.example .env`
4. Start in safe mode first:
   - `MODE=TEST KILL_SWITCH=false uvicorn dashboard.main:app --host 0.0.0.0 --port 8000`

## Environment variables
### Required for all modes
- `MODE` (`TEST` or `LIVE`)
- `SOL_RPC_URL`
- `KILL_SWITCH` (`true/false`, optional, default `false`)
- `CHAIN` (default `solana`)
- `ENGINE_STATE_PATH` (optional, default `data/engine_state.json`)
- `TRADES_LOG_PATH` (optional, default `data/trades_log.jsonl`)
- `AUDIT_LOG_PATH` (optional, default `data/audit_log.jsonl`)

### Required only when `MODE=LIVE`
- `LIVE_WALLET_PRIVATE_KEY`
- `LIVE_WALLET_PUBLIC_KEY`

### Optional paper-trading controls
- `PAPER_BROKER_SEED`
- `PAPER_BASE_PRICE`
- `PAPER_FEE_BPS`
- `PAPER_MAX_SLIPPAGE_BPS`
- `PAPER_FILL_PROBABILITY`

## How to run locally
- Start app:
  - `uvicorn dashboard.main:app --reload`
- Health check:
  - `curl -s http://localhost:8000/health`
- Status summary:
  - `curl -s http://localhost:8000/status`

## How to run on Render
- Use `render.yaml` service definition.
- Start command:
  - `uvicorn dashboard.main:app --host 0.0.0.0 --port $PORT`
- Configure env vars in Render dashboard (start with `MODE=TEST`).
- Emergency stop without redeploy:
  - Set `KILL_SWITCH=true`
- Keep durable storage for state/audit logs (persistent disk or external storage).

## Test + lint commands
### Tests
- Full suite:
  - `python -m pytest -q`
- Targeted integration:
  - `python -m pytest -q tests/test_integration_pipeline.py`

### Lint/static checks
- Bytecode/compile sanity:
  - `python -m compileall -q src dashboard`
- Optional style checks (if Ruff is installed):
  - `ruff check src tests dashboard`

## Coding conventions
- Keep architecture modular and swappable via interfaces (`src/interfaces.py`).
- Route decisions through the shared pipeline:
  - safety -> features -> scoring -> risk checks -> execution -> persistence
- Fail closed on unknown or risky signals.
- Never hardcode secrets/private keys.
- Preserve TEST mode as non-custodial simulation only.
- Emit structured audit records for scans and token decisions.
- Add/maintain deterministic tests when execution/scoring behavior changes.
- Keep changes small, typed, and covered by tests.
