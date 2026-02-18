# MEMESNIPR Runbook

## 1) Local startup
```bash
cp .env.example .env
pip install -r requirements.txt
MODE=TEST KILL_SWITCH=false uvicorn dashboard.main:app --host 0.0.0.0 --port 8000
```

Environment validation is fail-fast on startup:
- `MODE` must be `TEST` or `LIVE`
- `SOL_RPC_URL` must be set
- if `MODE=LIVE`, both `LIVE_WALLET_PRIVATE_KEY` and `LIVE_WALLET_PUBLIC_KEY` are required

Check health:
```bash
curl -s http://localhost:8000/health
```

Expected fields include `ok`, `mode`, and `last_scan_at`.

Check status summary:
```bash
curl -s http://localhost:8000/status
```

Expected fields include `last_decision`, `accepted_count`, `rejected_count`, and `top_rejection_reasons`.

## 2) Render deployment
Use `render.yaml` start command:
```bash
uvicorn dashboard.main:app --host 0.0.0.0 --port $PORT
```

Set env vars in Render dashboard:
- `MODE=TEST` (recommended initially)
- `KILL_SWITCH=false`
- `SOL_RPC_URL=...`
- if switching to `MODE=LIVE`, you must also set:
  - `LIVE_WALLET_PRIVATE_KEY`
  - `LIVE_WALLET_PUBLIC_KEY`
- Optional storage paths:
  - `ENGINE_STATE_PATH=data/engine_state.json`
  - `TRADES_LOG_PATH=data/trades_log.jsonl`
  - `AUDIT_LOG_PATH=data/audit_log.jsonl`

## 3) Emergency stop (no redeploy)
Set:
- `KILL_SWITCH=true`

Engine will halt new trading decisions on next tick.

## 4) Default trading gates
- `MIN_SCORE_TO_TRADE=85` (confidence must be >= 85/100)
- `MAX_RISK_SCORE_TO_TRADE=20` (risk must be <= 20/100)
- Hard blocks include active mint/freeze authority, low liquidity, honeypot/cannot-sell, bad deployer, and suspicious early holder concentration.


## 5) Audit verification
Audit log file (JSONL): `AUDIT_LOG_PATH`
Each record includes:
- timestamp
- chain
- token_address / token_symbol
- reason_codes
- scores
- thresholds
- decision
- next_actions

## 6) Data/execution integration guidance
Current code uses an internal simulation scanner/execution path.
Recommended next modular interfaces:
- **Data providers**: DexScreener + Solscan/RPC for token metadata + pool/liquidity checks.
- **Execution adapter (future)**: Jupiter/Raydium interface behind a provider abstraction.
- Keep LIVE mode fail-closed until adapters have deterministic integration tests.

## 7) Module architecture (swappable interfaces)
- `src/ingestion.py`: scanner/ingestion providers (`MockScanner` default)
- `src/features.py`: feature extraction
- `src/scorer.py`: confidence scoring
- `src/risk_checks.py`: risk gate checks (exposure checker)
- `src/execution.py` + `src/broker.py`: execution abstraction and paper/live send behavior
- `src/persistence.py` + `src/storage.py`: persistence interface + JSONL/file backend

`MemeSniprEngine` accepts custom scanner/executor/scorer/risk components via constructor for integration and strategy swaps.


## 8) Merge-conflict playbook (GitHub “This branch has conflicts”)
If GitHub shows conflict markers like merge-marker blocks (`<`/`=`/`>` marker lines) (for example in `app.py`), resolve locally and push the branch.

```bash
git fetch origin
git checkout <your-branch>
git merge origin/main
# edit conflicted files, remove markers, keep the intended final code
git add <resolved-files>
git commit -m "Resolve merge conflicts with main"
git push origin <your-branch>
```


Quick local resolver (use carefully, then review the diff):
```bash
python scripts/resolve_merge_markers.py path/to/conflicted_file.py --strategy both --write
# or choose one side:
# python scripts/resolve_merge_markers.py path/to/conflicted_file.py --strategy current --write
# python scripts/resolve_merge_markers.py path/to/conflicted_file.py --strategy incoming --write
```

Safety checks before pushing conflict resolutions:
```bash
python scripts/check_merge_markers.py
python -m pytest -q
python -m compileall -q src dashboard
```

If the conflicted file is outside this repo (for example a different project with `app.py`), you must run the same flow in that repository/branch because conflicts are repository-specific.

If GitHub shows markers like `<<<<<<< codex/...` in the web conflict editor, those are unresolved merge markers from Git.
You must pick the final code, then delete **all three marker lines** (`<<<<<<<`, `=======`, `>>>>>>>`) before committing the resolution.

