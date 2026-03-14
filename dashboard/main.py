# dashboard/main.py
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger

from src.engine import engine
from src.social_signals import fetch_memecoin_signals, get_cached_signal_count, get_last_fetch_time, get_social_intelligence_summary
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


@app.get("/api/setup-profitability")
async def setup_profitability_endpoint():
    """v3: Setup profitability stats (Section 13)."""
    return engine.get_setup_profitability()


@app.get("/api/position-details")
async def position_details_endpoint():
    """v3: Open position details with v3 metrics (Section 13)."""
    return engine.get_open_position_details()


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


@app.get("/api/social-intelligence")
async def social_intelligence_endpoint():
    """v4: Social intelligence summary across all signal sources."""
    return get_social_intelligence_summary()


@app.get("/api/v5/signal-scores")
async def v5_signal_scores_endpoint():
    """v5: Current signal scoring engine state."""
    from src.signal_scoring import get_signal_scoring_engine
    scoring = get_signal_scoring_engine()
    return {
        "recent_scores": scoring.get_recent_scores(),
        "active_signals": scoring.get_active_signal_count(),
    }


@app.get("/api/v5/runner-detection")
async def v5_runner_detection_endpoint():
    """v5: Runner detection state for all open positions."""
    from src.runner_detection import get_runner_detector
    detector = get_runner_detector()
    runners = []
    for pid, pos in engine.positions.items():
        if pos.status.value != "OPEN":
            continue
        state = detector.get_runner_state(pid)
        runners.append({
            "position_id": pid,
            "symbol": pos.token.symbol,
            "v5_runner_mode": pos.v5_runner_mode,
            "is_runner": state.is_runner if state else False,
            "trailing_stop_level": state.trailing_stop_level if state else 0.0,
            "stop_at_entry": state.stop_at_entry_active if state else False,
            "v5_signal_score": pos.v5_signal_score,
        })
    return runners


@app.get("/api/v5/liquidity-spikes")
async def v5_liquidity_spikes_endpoint():
    """v5: Recent liquidity spike events."""
    from src.liquidity_detector import get_liquidity_detector
    detector = get_liquidity_detector()
    return {
        "spike_events": [e.model_dump(mode="json") for e in detector.get_recent_events()],
        "tokens_monitored": detector.get_monitored_token_count(),
    }


@app.get("/api/v5/volume-acceleration")
async def v5_volume_acceleration_endpoint():
    """v5: Recent volume acceleration events."""
    from src.volume_detector import get_volume_detector
    detector = get_volume_detector()
    return {
        "spike_events": [e.model_dump(mode="json") for e in detector.get_recent_events()],
        "tokens_monitored": detector.get_monitored_token_count(),
    }


@app.get("/api/v5/holder-growth")
async def v5_holder_growth_endpoint():
    """v5: Recent holder growth momentum events."""
    from src.holder_tracker import get_holder_tracker
    tracker = get_holder_tracker()
    return {
        "momentum_events": [e.model_dump(mode="json") for e in tracker.get_recent_events()],
        "tokens_monitored": tracker.get_monitored_token_count(),
    }


@app.get("/api/v5/smart-wallet-clusters")
async def v5_smart_wallet_clusters_endpoint():
    """v5: Smart wallet cluster events and tracked wallets."""
    from src.smart_wallet_intelligence import get_smart_wallet_intelligence
    intel = get_smart_wallet_intelligence()
    return {
        "wallets_tracked": intel.get_tracked_wallet_count(),
        "cluster_events": [e.model_dump(mode="json") for e in intel.get_recent_cluster_events()],
        "recent_signals": intel.get_signal_count(),
    }


@app.get("/api/v5/signal-performance")
async def v5_signal_performance_endpoint():
    """v5: Per-signal performance stats and dynamic weights."""
    from src.trade_memory import get_trade_memory
    memory = get_trade_memory()
    return {
        "signal_performance": memory.get_v5_signal_performance(),
        "current_weights": memory.get_v5_signal_weights().model_dump(),
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

          <!-- v3: Setup Profitability Section (Section 13) -->
          <div class="card">
            <h2>Setup Profitability Stats</h2>
            <p style="color:#9ca3af;font-size:0.85rem;margin-bottom:1rem;">
              Self-learning trade memory &mdash; tracks win rate, profit factor, and expectancy per setup type.
            </p>
            <div id="setup-stats"></div>
          </div>

          <!-- v3: Position Details Section (Section 13) -->
          <div class="card">
            <h2>Open Position Details (v3)</h2>
            <div id="pos-details"></div>
          </div>

          <!-- v5: Signal Scoring & Runner Detection Section -->
          <div class="card">
            <h2>v5 Signal Intelligence</h2>
            <p style="color:#9ca3af;font-size:0.85rem;margin-bottom:1rem;">
              Composite signal scoring, runner detection, smart wallet clusters, volume/liquidity/holder momentum.
            </p>
            <div id="v5-signals" class="grid"></div>
          </div>

          <!-- v5: Runner Mode Trades -->
          <div class="card">
            <h2>v5 Runner Detection</h2>
            <p style="color:#9ca3af;font-size:0.85rem;margin-bottom:1rem;">
              Positions in runner mode with trailing stops. Runners are held until trailing stop triggers.
            </p>
            <div id="v5-runners"></div>
          </div>

          <!-- v5: Signal Performance & Dynamic Weights -->
          <div class="card">
            <h2>v5 Signal Performance</h2>
            <p style="color:#9ca3af;font-size:0.85rem;margin-bottom:1rem;">
              Per-signal win rate, profit factor, and dynamically adjusted weights.
            </p>
            <div id="v5-perf"></div>
          </div>

          <!-- v4: Social Intelligence Overview Section (Section 11) -->
          <div class="card">
            <h2>Social Intelligence Overview</h2>
            <p style="color:#9ca3af;font-size:0.85rem;margin-bottom:1rem;">
              v4 multi-source social engine &mdash; Twitter, Telegram, DexScreener, Birdeye, Pump Platform, sentiment analysis, and spam filtering.
            </p>
            <div id="social-intel" class="grid"></div>
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
                <div class="pill"><div class="label">Consec. Losses</div><div class="value" style="color:${{d.consecutive_losses > 2 ? '#f87171' : '#6ee7b7'}}">${{d.consecutive_losses || 0}}</div></div>
                <div class="pill"><div class="label">Pause Until</div><div class="value" style="color:#fbbf24">${{d.pause_until || 'None'}}</div></div>
              `;
            }} catch(e) {{ console.error('Live metrics error', e); }}
          }}
          refreshLiveMetrics();
          setInterval(refreshLiveMetrics, 15000);

          // v3: Setup Profitability
          async function refreshSetupStats() {{
            try {{
              const resp = await fetch('/api/setup-profitability');
              const data = await resp.json();
              const el = document.getElementById('setup-stats');
              if (!data.length) {{
                el.innerHTML = '<div style="color:#6b7280;text-align:center;padding:1rem;">No setup data yet. Trades will be analyzed as they complete.</div>';
                return;
              }}
              let html = '<table><thead><tr><th>Setup</th><th>Trades</th><th>Win Rate</th><th>PF</th><th>Expectancy</th><th>Avg Hold</th><th>Adj</th></tr></thead><tbody>';
              data.forEach(s => {{
                const wrColor = s.win_rate >= 50 ? '#6ee7b7' : '#f87171';
                const pfColor = s.profit_factor >= 1.5 ? '#6ee7b7' : s.profit_factor >= 1.0 ? '#fbbf24' : '#f87171';
                const adjColor = s.score_adjustment < 1.0 ? '#f87171' : s.score_adjustment > 1.0 ? '#6ee7b7' : '#e5e7eb';
                html += `<tr>
                  <td style="font-size:0.8rem;">${{s.setup_type}}</td>
                  <td>${{s.trades}}</td>
                  <td style="color:${{wrColor}}">${{s.win_rate}}%</td>
                  <td style="color:${{pfColor}}">${{s.profit_factor}}</td>
                  <td>${{s.expectancy}}</td>
                  <td>${{s.avg_hold_min}}m</td>
                  <td style="color:${{adjColor}}">${{s.score_adjustment}}x</td>
                </tr>`;
              }});
              html += '</tbody></table>';
              el.innerHTML = html;
            }} catch(e) {{ console.error('Setup stats error', e); }}
          }}
          refreshSetupStats();
          setInterval(refreshSetupStats, 15000);

          // v3: Position Details
          async function refreshPosDetails() {{
            try {{
              const resp = await fetch('/api/position-details');
              const data = await resp.json();
              const el = document.getElementById('pos-details');
              if (!data.length) {{
                el.innerHTML = '<div style="color:#6b7280;text-align:center;padding:1rem;">No open positions</div>';
                return;
              }}
              let html = '<table><thead><tr><th>Symbol</th><th>Confidence</th><th>Phase</th><th>Trap</th><th>Cluster</th><th>Size</th><th>Setup</th></tr></thead><tbody>';
              data.forEach(p => {{
                const trapColor = p.trap_score > 40 ? '#f87171' : p.trap_score > 20 ? '#fbbf24' : '#6ee7b7';
                html += `<tr>
                  <td style="font-weight:600">${{p.symbol}}</td>
                  <td>${{p.confidence.toFixed(1)}}</td>
                  <td style="font-size:0.8rem;">${{p.launch_phase || '—'}}</td>
                  <td style="color:${{trapColor}}">${{p.trap_score.toFixed(1)}}</td>
                  <td>${{p.wallet_cluster ? 'Yes' : '—'}}</td>
                  <td>${{p.size_sol.toFixed(6)}} (${{p.size_multiplier.toFixed(2)}}x)</td>
                  <td style="font-size:0.8rem;">${{p.setup_type || '—'}}</td>
                </tr>`;
              }});
              html += '</tbody></table>';
              el.innerHTML = html;
            }} catch(e) {{ console.error('Position details error', e); }}
          }}
          refreshPosDetails();
          setInterval(refreshPosDetails, 15000);

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

          // v5: Signal Intelligence
          async function refreshV5Signals() {{
            try {{
              const [scoresResp, clustersResp, liqResp, volResp, holderResp] = await Promise.all([
                fetch('/api/v5/signal-scores'),
                fetch('/api/v5/smart-wallet-clusters'),
                fetch('/api/v5/liquidity-spikes'),
                fetch('/api/v5/volume-acceleration'),
                fetch('/api/v5/holder-growth'),
              ]);
              const scores = await scoresResp.json();
              const clusters = await clustersResp.json();
              const liq = await liqResp.json();
              const vol = await volResp.json();
              const holder = await holderResp.json();
              const el = document.getElementById('v5-signals');
              el.innerHTML = `
                <div class="pill"><div class="label">Smart Wallets</div><div class="value" style="color:#a78bfa">${{clusters.wallets_tracked}}</div></div>
                <div class="pill"><div class="label">Cluster Events</div><div class="value" style="color:#c084fc">${{clusters.cluster_events.length}}</div></div>
                <div class="pill"><div class="label">Wallet Signals</div><div class="value">${{clusters.recent_signals}}</div></div>
                <div class="pill"><div class="label">Liq Spikes</div><div class="value" style="color:#22d3ee">${{liq.spike_events.length}}</div></div>
                <div class="pill"><div class="label">Vol Spikes</div><div class="value" style="color:#fb923c">${{vol.spike_events.length}}</div></div>
                <div class="pill"><div class="label">Holder Momentum</div><div class="value" style="color:#34d399">${{holder.momentum_events.length}}</div></div>
                <div class="pill"><div class="label">Active Signals</div><div class="value">${{scores.active_signals}}</div></div>
              `;
            }} catch(e) {{ console.error('V5 signals error', e); }}
          }}
          refreshV5Signals();
          setInterval(refreshV5Signals, 15000);

          // v5: Runner Detection
          async function refreshV5Runners() {{
            try {{
              const resp = await fetch('/api/v5/runner-detection');
              const data = await resp.json();
              const el = document.getElementById('v5-runners');
              if (!data.length) {{
                el.innerHTML = '<div style="color:#6b7280;text-align:center;padding:1rem;">No open positions to monitor</div>';
                return;
              }}
              let html = '<table><thead><tr><th>Symbol</th><th>Signal Score</th><th>Runner Mode</th><th>Is Runner</th><th>Trail Stop</th><th>Stop@Entry</th></tr></thead><tbody>';
              data.forEach(r => {{
                const runnerColor = r.is_runner ? '#22c55e' : r.v5_runner_mode ? '#fbbf24' : '#6b7280';
                const runnerLabel = r.is_runner ? 'CONFIRMED' : r.v5_runner_mode ? 'MONITORING' : 'OFF';
                html += `<tr>
                  <td style="font-weight:600">${{r.symbol}}</td>
                  <td>${{r.v5_signal_score.toFixed(1)}}</td>
                  <td style="color:${{runnerColor}};font-weight:600">${{runnerLabel}}</td>
                  <td>${{r.is_runner ? 'Yes' : 'No'}}</td>
                  <td>${{r.trailing_stop_level > 0 ? '$' + r.trailing_stop_level.toFixed(6) : '—'}}</td>
                  <td>${{r.stop_at_entry ? 'Active' : '—'}}</td>
                </tr>`;
              }});
              html += '</tbody></table>';
              el.innerHTML = html;
            }} catch(e) {{ console.error('V5 runners error', e); }}
          }}
          refreshV5Runners();
          setInterval(refreshV5Runners, 15000);

          // v5: Signal Performance
          async function refreshV5Perf() {{
            try {{
              const resp = await fetch('/api/v5/signal-performance');
              const data = await resp.json();
              const el = document.getElementById('v5-perf');
              const perf = data.signal_performance || [];
              const weights = data.current_weights || {{}};
              if (!perf.length) {{
                el.innerHTML = '<div style="color:#6b7280;text-align:center;padding:1rem;">No v5 signal performance data yet</div>';
                return;
              }}
              let html = '<div style="margin-bottom:0.8rem;"><span style="font-size:0.78rem;color:#9ca3af;">Current Weights: ';
              Object.entries(weights).forEach(([k, v]) => {{
                html += `<span style="margin-right:0.7rem;">${{k}}: <strong style="color:#e5e7eb">${{v}}</strong></span>`;
              }});
              html += '</span></div>';
              html += '<table><thead><tr><th>Signal</th><th>Trades</th><th>Win Rate</th><th>Profit Factor</th><th>Weight</th></tr></thead><tbody>';
              perf.forEach(p => {{
                const wrColor = p.win_rate >= 50 ? '#6ee7b7' : '#f87171';
                const pfColor = p.profit_factor >= 1.5 ? '#6ee7b7' : p.profit_factor >= 1.0 ? '#fbbf24' : '#f87171';
                html += `<tr>
                  <td style="font-size:0.8rem;">${{p.signal}}</td>
                  <td>${{p.trades}}</td>
                  <td style="color:${{wrColor}}">${{p.win_rate}}%</td>
                  <td style="color:${{pfColor}}">${{p.profit_factor}}</td>
                  <td>${{p.current_weight}}</td>
                </tr>`;
              }});
              html += '</tbody></table>';
              el.innerHTML = html;
            }} catch(e) {{ console.error('V5 perf error', e); }}
          }}
          refreshV5Perf();
          setInterval(refreshV5Perf, 15000);

          // v4: Social Intelligence Overview
          async function refreshSocialIntel() {{
            try {{
              const resp = await fetch('/api/social-intelligence');
              const d = await resp.json();
              const el = document.getElementById('social-intel');
              el.innerHTML = `
                <div class="pill"><div class="label">Signal Engine</div><div class="value" style="font-size:0.75rem;word-break:break-all">${{d.signal_engine_url || 'N/A'}}</div></div>
                <div class="pill"><div class="label">Cached Signals</div><div class="value">${{d.cached_signals || 0}}</div></div>
                <div class="pill"><div class="label">Twitter Signals</div><div class="value" style="color:#1d9bf0">${{d.twitter_signals_cached || 0}}</div></div>
                <div class="pill"><div class="label">Telegram Signals</div><div class="value" style="color:#26a5e4">${{d.telegram_signals_cached || 0}}</div></div>
                <div class="pill"><div class="label">Birdeye Signals</div><div class="value" style="color:#f59e0b">${{d.birdeye_signals_cached || 0}}</div></div>
                <div class="pill"><div class="label">Pump Signals</div><div class="value" style="color:#a855f7">${{d.pump_signals_cached || 0}}</div></div>
                <div class="pill"><div class="label">Spam Tokens Tracked</div><div class="value">${{d.spam_tokens_tracked || 0}}</div></div>
                <div class="pill"><div class="label">Last Fetch</div><div class="value" style="font-size:0.75rem">${{d.last_fetch ? new Date(d.last_fetch).toLocaleTimeString() : 'Never'}}</div></div>
              `;
            }} catch(e) {{ console.error('Social intel error', e); }}
          }}
          refreshSocialIntel();
          setInterval(refreshSocialIntel, 15000);
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
