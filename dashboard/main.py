# dashboard/main.py
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger

from src.engine import engine
from src.storage import load_engine_state, load_recent_audit_records, load_recent_trades, summarize_audit_records


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
    ok = state.status != "ERROR"
    return {
        "ok": ok,
        "status": state.status,
        "mode": state.mode,
        "last_heartbeat": state.last_heartbeat,
        "last_scan_at": state.last_scan_at,
        "halted_reason": state.halted_reason,
        "last_error": state.last_error,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/status")
async def status():
    state = load_engine_state()
    records = load_recent_audit_records(limit=500)
    summary = summarize_audit_records(records)
    return {
        "mode": state.mode,
        "engine_status": state.status,
        "last_scan_at": state.last_scan_at,
        "last_heartbeat": state.last_heartbeat,
        "last_decision": summary["last_decision"],
        "accepted_count": summary["accepted_count"],
        "rejected_count": summary["rejected_count"],
        "top_rejection_reasons": summary["top_rejection_reasons"],
    }


@app.get("/trades")
async def trades():
    entries = load_recent_trades(limit=200)
    return [e.model_dump(mode="json") for e in entries]


@app.get("/positions")
async def positions():
    pos_list = []
    for pid, pos in engine.positions.items():
        d = pos.model_dump(mode="json")
        d.pop("token", None)
        d["symbol"] = pos.token.symbol
        d["token_address"] = pos.token.token_address
        pos_list.append(d)
    return pos_list


@app.get("/")
async def root():
    state = load_engine_state()
    recent_trades = load_recent_trades(limit=50)

    buy_trades = [t for t in recent_trades if t.side == "BUY"]
    sell_trades = [t for t in recent_trades if t.side == "SELL"]
    total_pnl = sum(t.realized_pnl_sol for t in sell_trades)
    wins = sum(1 for t in sell_trades if t.realized_pnl_sol >= 0)
    losses = sum(1 for t in sell_trades if t.realized_pnl_sol < 0)

    trade_rows = ""
    for t in reversed(recent_trades):
        side_color = "#6ee7b7" if t.side == "BUY" else ("#f87171" if t.realized_pnl_sol < 0 else "#6ee7b7")
        pnl_display = f"{t.realized_pnl_sol:+.6f}" if t.side == "SELL" else "—"
        ts = t.timestamp.strftime("%m/%d %H:%M") if t.timestamp else "—"
        trade_rows += f"""
            <tr>
              <td style="color:{side_color};font-weight:600">{t.side}</td>
              <td><a href="https://dexscreener.com/solana/{t.token_address}" target="_blank"
                     style="color:#93c5fd;text-decoration:none">{t.token_address[:8]}...</a></td>
              <td>{t.size_sol:.6f}</td>
              <td style="color:{'#6ee7b7' if t.realized_pnl_sol >= 0 else '#f87171'}">{pnl_display}</td>
              <td>{t.note or '—'}</td>
              <td style="color:#9ca3af">{ts}</td>
            </tr>"""

    open_pos_rows = ""
    for pid, pos in engine.positions.items():
        if pos.status.value != "OPEN":
            continue
        age_min = (datetime.utcnow() - pos.opened_at.replace(tzinfo=None)).total_seconds() / 60
        open_pos_rows += f"""
            <tr>
              <td><a href="https://dexscreener.com/solana/{pos.token.token_address}" target="_blank"
                     style="color:#93c5fd;text-decoration:none">{pos.token.symbol}</a></td>
              <td>{pos.size_sol:.6f}</td>
              <td>${pos.entry_price_usd:.8f}</td>
              <td>{age_min:.0f}m</td>
              <td style="color:#fbbf24">OPEN</td>
            </tr>"""

    if not open_pos_rows:
        open_pos_rows = '<tr><td colspan="5" style="color:#6b7280;text-align:center;padding:1rem">No open positions</td></tr>'
    if not trade_rows:
        trade_rows = '<tr><td colspan="6" style="color:#6b7280;text-align:center;padding:1rem">No trades yet — waiting for qualifying tokens</td></tr>'

    pnl_color = "#6ee7b7" if total_pnl >= 0 else "#f87171"

    html = f"""
    <html>
      <head>
        <title>MEMESNIPR v1</title>
        <meta http-equiv="refresh" content="15">
        <style>
          body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #050816;
            color: #e5e7eb;
            padding: 2rem;
            margin: 0;
          }}
          .container {{ max-width: 960px; margin: 0 auto; }}
          .card {{
            background: radial-gradient(circle at top left, #111827, #020617);
            border-radius: 1.5rem;
            padding: 2rem;
            box-shadow: 0 20px 45px rgba(0,0,0,0.6);
            border: 1px solid rgba(148, 163, 184, 0.35);
            margin-bottom: 1.5rem;
          }}
          h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; }}
          h2 {{ font-size: 1.2rem; margin: 0 0 1rem 0; color: #cbd5e1; }}
          .badge {{
            display: inline-block; padding: 0.15rem 0.55rem;
            border-radius: 999px; font-size: 0.75rem;
            letter-spacing: 0.04em; text-transform: uppercase; margin-left: 0.5rem;
          }}
          .badge-ok {{ background: rgba(52,211,153,0.15); color: #6ee7b7; border: 1px solid rgba(52,211,153,0.3); }}
          .badge-error {{ background: rgba(248,113,113,0.1); color: #fecaca; border: 1px solid rgba(248,113,113,0.3); }}
          .label {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: #9ca3af; margin-bottom: 0.25rem; }}
          .value {{ font-size: 0.95rem; color: #e5e7eb; }}
          .grid {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 1rem; margin-top: 1.5rem;
          }}
          .pill {{
            padding: 0.75rem 0.9rem; border-radius: 0.9rem;
            background: rgba(15,23,42,0.9); border: 1px solid rgba(31,41,55,0.9);
          }}
          table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
          th {{ text-align: left; padding: 0.5rem 0.75rem; color: #9ca3af; font-weight: 500;
               font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em;
               border-bottom: 1px solid rgba(31,41,55,0.8); }}
          td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid rgba(31,41,55,0.4); }}
          .muted {{ color: #6b7280; font-size: 0.8rem; margin-top: 1.2rem; }}
        </style>
      </head>
      <body>
        <div class="container">
          <div class="card">
            <h1>MEMESNIPR v1
              <span class="badge {'badge-ok' if state.status.value != 'ERROR' else 'badge-error'}">{state.status.value}</span>
            </h1>
            <div class="grid">
              <div class="pill">
                <div class="label">Mode</div>
                <div class="value">{state.mode.value}</div>
              </div>
              <div class="pill">
                <div class="label">Last Scan</div>
                <div class="value">{state.last_scan_at.strftime('%H:%M:%S') if state.last_scan_at else '—'}</div>
              </div>
              <div class="pill">
                <div class="label">Daily Trades</div>
                <div class="value">{state.daily_trades}</div>
              </div>
              <div class="pill">
                <div class="label">Realized PnL</div>
                <div class="value" style="color:{pnl_color}">{total_pnl:+.6f} SOL</div>
              </div>
              <div class="pill">
                <div class="label">Wins / Losses</div>
                <div class="value" style="color:#6ee7b7">{wins}W</div>
                <div class="value" style="color:#f87171">{losses}L</div>
              </div>
            </div>
          </div>

          <div class="card">
            <h2>Open Positions</h2>
            <table>
              <thead><tr>
                <th>Token</th><th>Size (SOL)</th><th>Entry $</th><th>Age</th><th>Status</th>
              </tr></thead>
              <tbody>{open_pos_rows}</tbody>
            </table>
          </div>

          <div class="card">
            <h2>Recent Trades</h2>
            <table>
              <thead><tr>
                <th>Side</th><th>Token</th><th>Size (SOL)</th><th>PnL (SOL)</th><th>Note</th><th>Time</th>
              </tr></thead>
              <tbody>{trade_rows}</tbody>
            </table>
          </div>

          <p class="muted" style="text-align:center">
            Auto-refreshes every 15s &bull; Scanning real Solana tokens via DexScreener
          </p>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
