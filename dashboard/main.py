# dashboard/main.py
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger

from src.engine import engine
from src.storage import load_engine_state


app = FastAPI(title="MEMESNIPR v1", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """
    Start the MEMESNIPR engine when the FastAPI app starts.

    IMPORTANT:
    We await engine.start() here so the engine's own background task
    is registered cleanly on the event loop. We do NOT wrap it in an
    extra asyncio.create_task(), because engine.start() already does that.
    """
    logger.info("Starting MEMESNIPR dashboard + engine")
    await engine.start()


@app.get("/health")
async def health():
    state = load_engine_state()
    return {
        "status": state.status,
        "mode": state.mode,
        "last_heartbeat": state.last_heartbeat,
        "last_error": state.last_error,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/")
async def root():
    state = load_engine_state()
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
            max-width: 720px;
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
          }}
          .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-top: 1.5rem;
          }}
          .pill {{
            padding: 0.75rem 0.9rem;
            border-radius: 0.9rem;
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid rgba(31, 41, 55, 0.9);
          }}
          .muted {{
            color: #6b7280;
            font-size: 0.8rem;
            margin-top: 1.2rem;
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
            <span class="badge {'badge-ok' if state.status != 'ERROR' else 'badge-error'}">
              {state.status}
            </span>
          </h1>
          <p class="muted">
            Solana meme sniper &amp; safety-first engine
            (structure online, logic ready to wire to DEX).
          </p>
          <div class="grid">
            <div class="pill">
              <div class="label">Mode</div>
              <div class="value">{state.mode}</div>
            </div>
            <div class="pill">
              <div class="label">Last heartbeat</div>
              <div class="value">{state.last_heartbeat or '—'}</div>
            </div>
            <div class="pill">
              <div class="label">Daily trades</div>
              <div class="value">{state.daily_trades}</div>
            </div>
            <div class="pill">
              <div class="label">Realized PnL (SOL)</div>
              <div class="value">{state.daily_realized_pnl_sol:.6f}</div>
            </div>
          </div>
          <div class="grid" style="margin-top: 1rem;">
            <div class="pill">
              <div class="label">Wins / Losses</div>
              <div class="value">{state.daily_wins} / {state.daily_losses}</div>
            </div>
            <div class="pill">
              <div class="label">Loss streak</div>
              <div class="value">{state.loss_streak}</div>
            </div>
            <div class="pill">
              <div class="label">Engine error</div>
              <div class="value">{state.last_error or 'None'}</div>
            </div>
          </div>
          <p class="muted">
            Engine runs as a background loop. Start simple by leaving
            <code>scan_candidates()</code> in simulation mode (no live trades),
            then wire in Solana DEX + wallet calls once you like the behavior.
          </p>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
