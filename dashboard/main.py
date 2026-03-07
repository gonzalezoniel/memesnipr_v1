# dashboard/main.py
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger

from src.engine import engine
from src.social_signals import fetch_memecoin_signals, get_cached_signal_count, get_last_fetch_time
from src.storage import load_engine_state, load_recent_audit_records, load_recent_trades, summarize_audit_records


app = FastAPI(title="MEMESNIPR v2", version="2.0.0")

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


@app.get("/api/strategy-metrics")
async def strategy_metrics_endpoint():
    """v2: Strategy performance metrics (Section 13)."""
    return engine.get_strategy_metrics()


@app.get("/api/live-metrics")
async def live_metrics_endpoint():
    """v2: Live system metrics (Section 13)."""
    return engine.get_live_system_metrics()


@app.get("/api/wallet-intelligence")
async def wallet_intelligence_endpoint():
    """v2: Wallet intelligence summary (Section 13)."""
    from src.wallet_tracker import get_wallet_intelligence_summary
    from src.smart_wallet_engine import get_smart_wallet_engine
    wallet_engine = get_smart_wallet_engine()
    return get_wallet_intelligence_summary(wallet_engine)


@app.get("/api/social-signals")
async def social_signals_endpoint():
    """Fetch latest memecoin social signals from the centralized Signal Engine."""
    signals = await fetch_memecoin_signals()
    last_fetch = get_last_fetch_time()
    return {
        "status": "ok",
        "signals": signals,
        "count": len(signals),
        "cached_count": get_cached_signal_count(),
        "last_fetch": last_fetch.isoformat() if last_fetch else None,
    }


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
            <h1>MEMESNIPR v2
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

          <!-- v2: Strategy Metrics Section (Section 13) -->
          <div class="card">
            <h2>Strategy Metrics</h2>
            <div id="strat-metrics" class="grid"></div>
          </div>

          <!-- v2: Live System Metrics Section (Section 13) -->
          <div class="card">
            <h2>Live System Metrics</h2>
            <div id="live-metrics" class="grid"></div>
          </div>

          <!-- v2: Wallet Intelligence Section (Section 13) -->
          <div class="card">
            <h2>Wallet Intelligence</h2>
            <div id="wallet-intel" class="grid"></div>
          </div>

          <div class="card">
            <h2>Social Signals Intelligence</h2>
            <p style="color:#9ca3af;font-size:0.85rem;margin-bottom:1rem;">
              Live memecoin sentiment from the Social Signal Engine &mdash; influences confidence scoring and position sizing.
            </p>
            <div id="ss-meta" style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem;">
              <span style="font-size:0.8rem;padding:4px 10px;border-radius:999px;background:rgba(30,64,175,0.18);color:#bfdbfe;border:1px solid rgba(59,130,246,0.35);" id="ss-count">Signals: loading...</span>
              <span style="font-size:0.8rem;padding:4px 10px;border-radius:999px;background:rgba(30,64,175,0.18);color:#bfdbfe;border:1px solid rgba(59,130,246,0.35);" id="ss-updated">Updated: ...</span>
            </div>
            <button onclick="refreshSocial()" style="padding:8px 16px;border-radius:999px;border:none;background:linear-gradient(135deg,#4f46e5,#6366f1);color:white;font-size:0.85rem;cursor:pointer;margin-bottom:1rem;">Refresh Social Signals</button>
            <div id="ss-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;"></div>

            <div style="margin-top:1.2rem;padding-top:0.8rem;border-top:1px solid rgba(31,41,55,0.6);">
              <div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.08em;color:#9ca3af;margin-bottom:0.5rem;">HOW SIGNALS AFFECT DECISIONS</div>
              <div style="font-size:0.82rem;color:#9ca3af;line-height:1.6;">
                <strong style="color:#e5e7eb;">Scoring Boost (up to +8 pts):</strong>
                Mentions (&ge;10: +3, &ge;5: +2, &ge;2: +1) + Sentiment (&gt;0.3: +2, &gt;0.1: +1.5) + Trend (rising: +2, stable: +1) + Engagement (+1)<br/>
                <strong style="color:#e5e7eb;">Position Size Boost:</strong>
                Social score scales position size up to +30% larger when signals are strong.<br/>
                <strong style="color:#e5e7eb;">Net Effect:</strong>
                Tokens with high social buzz get higher confidence scores AND bigger positions.
              </div>
            </div>
          </div>

          <p class="muted" style="text-align:center">
            Auto-refreshes every 15s &bull; Scanning real Solana tokens via DexScreener
          </p>
        </div>
        <script>
          async function refreshSocial() {{
            try {{
              const resp = await fetch('/api/social-signals');
              const data = await resp.json();
              const signals = data.signals || [];
              document.getElementById('ss-count').textContent = 'Signals: ' + (data.count || 0);
              document.getElementById('ss-updated').textContent = data.last_fetch
                ? 'Updated: ' + new Date(data.last_fetch).toLocaleTimeString()
                : 'Updated: never';
              const grid = document.getElementById('ss-grid');
              if (!signals.length) {{
                grid.innerHTML = '<div style="color:#6b7280;">No social signals available yet. Engine fetches data each tick.</div>';
                return;
              }}
              grid.innerHTML = signals.map(sig => {{
                const token = sig.token || '???';
                const mentions = sig.mentions || 0;
                const sentiment = parseFloat(sig.sentiment || 0);
                const trend = sig.trend || 'unknown';
                const engagement = parseFloat(sig.engagement || 0);
                const sources = (sig.sources || []).join(', ') || 'N/A';

                const sentColor = sentiment > 0.3 ? '#4ade80' : sentiment > 0.1 ? '#facc15' : sentiment > 0 ? '#9ca3af' : '#f87171';
                const trendColor = trend === 'rising' ? '#4ade80' : trend === 'stable' ? '#facc15' : '#9ca3af';

                let scoreEst = 0;
                if (mentions >= 10) scoreEst += 3;
                else if (mentions >= 5) scoreEst += 2;
                else if (mentions >= 2) scoreEst += 1;
                if (sentiment > 0.3) scoreEst += 2;
                else if (sentiment > 0.1) scoreEst += 1.5;
                else if (sentiment > 0) scoreEst += 1;
                if (trend === 'rising') scoreEst += 2;
                else if (trend === 'stable') scoreEst += 1;
                if (engagement > 0) scoreEst += 1;
                scoreEst = Math.min(scoreEst, 8);
                const scorePct = Math.round((scoreEst / 8) * 100);
                const barColor = scoreEst >= 6 ? '#22c55e' : scoreEst >= 3 ? '#eab308' : '#6b7280';

                let influence = '';
                if (scoreEst >= 6) {{
                  influence = '<div style="margin-top:8px;padding:6px 10px;border-radius:8px;font-size:0.78rem;background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.25);color:#86efac;">Strong signal &mdash; +' + Math.round(30 * scoreEst / 8) + '% position size boost + score boost</div>';
                }} else if (scoreEst >= 3) {{
                  influence = '<div style="margin-top:8px;padding:6px 10px;border-radius:8px;font-size:0.78rem;background:rgba(234,179,8,0.08);border:1px solid rgba(234,179,8,0.25);color:#fde68a;">Moderate signal &mdash; +' + Math.round(30 * scoreEst / 8) + '% position size boost</div>';
                }} else if (scoreEst > 0) {{
                  influence = '<div style="margin-top:8px;padding:6px 10px;border-radius:8px;font-size:0.78rem;background:rgba(107,114,128,0.1);border:1px solid rgba(107,114,128,0.25);color:#9ca3af;">Weak signal &mdash; minimal impact on sizing</div>';
                }}

                return `
                  <div style="background:rgba(10,18,36,0.85);border:1px solid rgba(148,163,184,0.18);border-radius:14px;padding:14px;">
                    <div style="font-size:1rem;font-weight:700;color:#f9fafb;margin-bottom:6px;">${{token}}</div>
                    <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#9ca3af;"><span>Social Score</span><span style="color:#e5e7eb;font-weight:500">${{scoreEst.toFixed(1)}} / 8.0</span></div>
                    <div style="height:5px;border-radius:999px;background:rgba(148,163,184,0.15);margin-top:3px;overflow:hidden;"><div style="height:100%;width:${{scorePct}}%;border-radius:999px;background:${{barColor}};"></div></div>
                    <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#9ca3af;margin-top:5px;"><span>Mentions</span><span style="color:#e5e7eb;font-weight:500">${{mentions}}</span></div>
                    <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#9ca3af;margin-top:3px;"><span>Sentiment</span><span style="color:${{sentColor}};font-weight:500">${{sentiment.toFixed(2)}}</span></div>
                    <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#9ca3af;margin-top:3px;"><span>Trend</span><span style="color:${{trendColor}};font-weight:500">${{trend}}</span></div>
                    <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#9ca3af;margin-top:3px;"><span>Engagement</span><span style="color:#e5e7eb;font-weight:500">${{engagement.toFixed(1)}}</span></div>
                    <div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#9ca3af;margin-top:3px;"><span>Sources</span><span style="color:#e5e7eb;font-weight:500">${{sources}}</span></div>
                    ${{influence}}
                  </div>
                `;
              }}).join('');
            }} catch(e) {{
              document.getElementById('ss-grid').innerHTML = '<div style="color:#6b7280;">Error loading social signals.</div>';
            }}
          }}
          refreshSocial();
          setInterval(refreshSocial, 15000);

          // v2: Strategy Metrics
          async function refreshStratMetrics() {{
            try {{
              const resp = await fetch('/api/strategy-metrics');
              const d = await resp.json();
              const el = document.getElementById('strat-metrics');
              el.innerHTML = `
                <div class="pill"><div class="label">Win Rate</div><div class="value">${{d.win_rate}}%</div></div>
                <div class="pill"><div class="label">Avg Win</div><div class="value" style="color:#6ee7b7">${{d.average_win}} SOL</div></div>
                <div class="pill"><div class="label">Avg Loss</div><div class="value" style="color:#f87171">${{d.average_loss}} SOL</div></div>
                <div class="pill"><div class="label">Profit Factor</div><div class="value">${{d.profit_factor}}</div></div>
                <div class="pill"><div class="label">Total PnL</div><div class="value" style="color:${{d.total_pnl >= 0 ? '#6ee7b7' : '#f87171'}}">${{d.total_pnl}} SOL</div></div>
                <div class="pill"><div class="label">Largest Win</div><div class="value" style="color:#6ee7b7">${{d.largest_win}} SOL</div></div>
                <div class="pill"><div class="label">Largest Loss</div><div class="value" style="color:#f87171">${{d.largest_loss}} SOL</div></div>
              `;
            }} catch(e) {{ console.error('Strategy metrics error', e); }}
          }}
          refreshStratMetrics();
          setInterval(refreshStratMetrics, 15000);

          // v2: Live System Metrics
          async function refreshLiveMetrics() {{
            try {{
              const resp = await fetch('/api/live-metrics');
              const d = await resp.json();
              const el = document.getElementById('live-metrics');
              el.innerHTML = `
                <div class="pill"><div class="label">Tokens Scanned</div><div class="value">${{d.tokens_scanned}}</div></div>
                <div class="pill"><div class="label">Tokens Rejected</div><div class="value">${{d.tokens_rejected}}</div></div>
                <div class="pill"><div class="label">Smart Wallets</div><div class="value">${{d.smart_wallets_detected}}</div></div>
                <div class="pill"><div class="label">Active Positions</div><div class="value">${{d.active_positions}}</div></div>
              `;
            }} catch(e) {{ console.error('Live metrics error', e); }}
          }}
          refreshLiveMetrics();
          setInterval(refreshLiveMetrics, 15000);

          // v2: Wallet Intelligence
          async function refreshWalletIntel() {{
            try {{
              const resp = await fetch('/api/wallet-intelligence');
              const d = await resp.json();
              const el = document.getElementById('wallet-intel');
              el.innerHTML = `
                <div class="pill"><div class="label">Smart Wallets Tracked</div><div class="value">${{d.smart_wallets_tracked}}</div></div>
                <div class="pill"><div class="label">Suspicious Wallets</div><div class="value" style="color:#f87171">${{d.suspicious_wallets}}</div></div>
                <div class="pill"><div class="label">Wallet Signals</div><div class="value">${{d.wallet_driven_trade_signals}}</div></div>
              `;
            }} catch(e) {{ console.error('Wallet intel error', e); }}
          }}
          refreshWalletIntel();
          setInterval(refreshWalletIntel, 15000);
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
