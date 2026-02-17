# dashboard/main.py
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger

from src.engine import engine
from src.storage import load_engine_state, load_recent_audit_records, summarize_audit_records


def _to_display(value: object) -> str:
    if isinstance(value, Enum):
        return value.value
    return str(value)


def _fmt_datetime(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MEMESNIPR dashboard + engine")
    await engine.start()
    yield


app = FastAPI(title="MEMESNIPR v1", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    state = load_engine_state()
    status = _to_display(state.status)
    return {
        "ok": status != "ERROR",
        "status": status,
        "mode": _to_display(state.mode),
        "last_heartbeat": state.last_heartbeat,
        "last_scan_at": state.last_scan_at,
        "halted_reason": state.halted_reason,
        "last_error": state.last_error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/status")
async def status():
    state = load_engine_state()
    records = load_recent_audit_records(limit=500)
    summary = summarize_audit_records(records)
    return {
        "mode": _to_display(state.mode),
        "engine_status": _to_display(state.status),
        "last_scan_at": state.last_scan_at,
        "last_heartbeat": state.last_heartbeat,
        "last_decision": summary["last_decision"],
        "accepted_count": summary["accepted_count"],
        "rejected_count": summary["rejected_count"],
        "top_rejection_reasons": summary["top_rejection_reasons"],
    }


@app.get("/")
async def root():
    state = load_engine_state()
    summary = summarize_audit_records(load_recent_audit_records(limit=500))

    status = _to_display(state.status)
    mode = _to_display(state.mode)
    top_reasons = summary["top_rejection_reasons"][:3]
    top_reasons_display = ", ".join(f"{k}:{v}" for k, v in top_reasons) if top_reasons else "None"

    html = f"""
    <html>
      <head>
        <title>MEMESNIPR v1</title>
        <style>
          body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #050816;
            color: #e5e7eb;
            padding: 2rem;
          }}
          .card {{
            max-width: 860px;
            margin: 0 auto;
            background: radial-gradient(circle at top left, #111827, #020617);
            border-radius: 1.5rem;
            padding: 2rem;
            box-shadow: 0 20px 45px rgba(0,0,0,0.6);
            border: 1px solid rgba(148, 163, 184, 0.35);
          }}
          h1 {{
            font-size: 1.8rem;
            margin-bottom: 0.5rem;
          }}
          .badge {{
            display: inline-block;
            padding: 0.15rem 0.55rem;
            border-radius: 999px;
            font-size: 0.75rem;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            margin-left: 0.5rem;
          }}
          .badge-ok {{
            background: rgba(52, 211, 153, 0.15);
            color: #6ee7b7;
            border: 1px solid rgba(52, 211, 153, 0.3);
          }}
          .badge-error {{
            background: rgba(248, 113, 113, 0.1);
            color: #fecaca;
            border: 1px solid rgba(248, 113, 113, 0.3);
          }}
          .label {{
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #9ca3af;
            margin-bottom: 0.25rem;
          }}
          .value {{
            font-size: 0.95rem;
            color: #e5e7eb;
            word-break: break-word;
          }}
          .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-top: 1.2rem;
          }}
          .pill {{
            padding: 0.75rem 0.9rem;
            border-radius: 0.9rem;
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid rgba(31, 41, 55, 0.9);
          }}
          .muted {{
            color: #93a3b8;
            font-size: 0.9rem;
            margin-top: 1rem;
          }}
          code {{
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
                         "Liberation Mono", "Courier New", monospace;
            background: rgba(15,23,42,0.95);
            padding: 0.2rem 0.4rem;
            border-radius: 0.4rem;
            font-size: 0.75rem;
          }}
        </style>
      </head>
      <body>
        <div class="card">
          <h1>MEMESNIPR v1
            <span class="badge {'badge-ok' if status != 'ERROR' else 'badge-error'}">{status}</span>
          </h1>
          <p class="muted">Safety-first sniper runtime overview with explicit decision telemetry.</p>

          <div class="grid">
            <div class="pill"><div class="label">Mode</div><div class="value">{mode}</div></div>
            <div class="pill"><div class="label">Last heartbeat</div><div class="value">{_fmt_datetime(state.last_heartbeat)}</div></div>
            <div class="pill"><div class="label">Last scan</div><div class="value">{_fmt_datetime(state.last_scan_at)}</div></div>
            <div class="pill"><div class="label">Last decision</div><div class="value">{summary['last_decision'] or 'None'}</div></div>
          </div>

          <div class="grid">
            <div class="pill"><div class="label">Daily trades</div><div class="value">{state.daily_trades}</div></div>
            <div class="pill"><div class="label">Accepted / Rejected</div><div class="value">{summary['accepted_count']} / {summary['rejected_count']}</div></div>
            <div class="pill"><div class="label">Wins / Losses</div><div class="value">{state.daily_wins} / {state.daily_losses}</div></div>
            <div class="pill"><div class="label">Loss streak</div><div class="value">{state.loss_streak}</div></div>
          </div>

          <div class="grid">
            <div class="pill"><div class="label">Realized PnL (SOL)</div><div class="value">{state.daily_realized_pnl_sol:.6f}</div></div>
            <div class="pill"><div class="label">Halted reason</div><div class="value">{state.halted_reason or 'None'}</div></div>
            <div class="pill"><div class="label">Engine error</div><div class="value">{state.last_error or 'None'}</div></div>
            <div class="pill"><div class="label">Top rejection reasons</div><div class="value">{top_reasons_display}</div></div>
          </div>

          <p class="muted">
            Data sources and executors are swappable behind interfaces. Keep <code>MODE=TEST</code>
            until live execution adapters pass deterministic integration checks.
          </p>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
