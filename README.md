# AlphaHardTargetScalper

An intraday RSI/ATR scalping bot built on Alpaca paper trading, designed to exploit short-lived momentum dislocations across 8 high-volatility S&P 500 names. Built as a hands-on quant finance learning project while studying CS at UMass Amherst.

---

## Why I Built This

I'm a CS major interested in where software engineering meets quantitative finance. Building a live trading bot felt like the most direct path to understanding how real market microstructure behaves — not from a textbook, but from watching a system I wrote win and lose real (paper) money in real time. The engineering problems turned out to be as interesting as the finance ones.

---

## What It Does

The bot runs a dual-engine scan loop across 8 tickers every 30 seconds during market hours, routing entry and exit logic based on the time of day:

**ENGINE_A** (9:30–11:30 and 13:30–16:00) — targets open and close momentum. Enters on RSI ≤ 32, holds with 12% portfolio allocation, and exits via a 1.5×/3.0× ATR trailing stop or take-profit.

**ENGINE_B** (11:30–13:30) — adapts to midday chop. Enters on RSI ≤ 45 with a volatility contraction filter (ATR/price < 1.0%), uses tighter 6% allocation and 0.3×/1.0× ATR exits to scalp sideways drift. (Currently looking to improve or get rid of)

**Asset universe:** TSLA, NVDA, AMD, NFLX, META, MSFT, AMZN, AAPL (Looking to expand upon)

---

## Architecture

```
intraday_bot.py        Core loop — entry/exit logic, order execution, CSV logging
bot_enhancements.py    ATR volatility scanner, trailing stop calculations
cockpit.py             Streamlit dashboard — trade audit, equity curve, live positions
backtester.py          Offline simulation on 5-day 1m data with same dual-engine rules
```

### Key Engineering Decisions

**Atomic CSV writes** — all trade log updates use `tempfile` + `os.replace()` to prevent race conditions between the bot loop and the cockpit reading the same file.

**State hydration on restart** — the bot re-reads today's closed trades from `trade_log.csv` on startup, rebuilding win/loss counters and cooldown timers so a crash doesn't lose session context.

**in-flight sale guard** — a `set()` tracks symbols with pending sell orders to prevent duplicate liquidation attempts during the 30s loop cycle.

**IOC fallback after 15:55** — switches from `TimeInForce.DAY` to `TimeInForce.IOC` near close to prevent order rejections from Alpaca's end-of-day restrictions.

**Emergency liquidation at 15:57** — a hard E-Stop bypasses all normal exit logic and force-closes every open position before market close.

**Asymmetric cooldowns** — after a loss on a ticker, the bot waits 30 minutes before re-entering. After a win, only 10 minutes.

---

## Streamlit Cockpit

Run with `streamlit run cockpit.py`. Three analysis views:

**Single Trade Audit** — plots any completed trade against live 1-minute candles with entry/exit arrows, RSI at entry, holding time, and engine used.

**All-in-One Asset View** — continuous price chart overlaid with all buy/sell vectors for a selected ticker across any time horizon. Includes a full leaderboard with profit factor, expectancy, and win/loss records per asset.

**Macro Equity Curve** — cumulative PnL line with an underwater drawdown panel and per-engine performance breakdown.

A live heartbeat banner reads from `bot_status.json` (written each scan cycle) and shows bot state, active engine, and open position count in real time. The Live Session Monitor tab pulls directly from the Alpaca API and auto-refreshes every 30 seconds.

---

## Setup

**Prerequisites:** Python 3.11+, an [Alpaca paper trading account](https://alpaca.markets)

```bash
git clone https://github.com/HaydenHour-pixel/sp500-daytrader.git
cd sp500-daytrader
pip install alpaca-py yfinance pandas numpy streamlit plotly python-dotenv requests
```

Create a `.env` file in the project root:

```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
SLACK_WEBHOOK_URL=your_webhook_here   # optional
```

**Run the bot:**
```bash
python intraday_bot.py
```

**Run the backtester:**
```bash
python backtester.py
```

**Open the cockpit:**
```bash
streamlit run cockpit.py
```

---

## Tech Stack

| Layer | Tools |
|---|---|
| Language | Python 3.11+ |
| Market Data | yfinance |
| Brokerage | Alpaca Paper Trading API (`alpaca-py`) |
| Dashboard | Streamlit + Plotly |
| Alerts | Slack Webhooks |
| Data | pandas, NumPy |

---

## What I've Learned

Building and running this live revealed things backtests never show. A 68-trade clean run exposed that the scalping architecture was structurally fighting transaction costs — profit factor landed at 0.97, with ENGINE_B being a consistent drag. That empirical finding pushed the project toward researching statistical arbitrage as a more cost-viable edge.

On the engineering side: a single uncleared `in_flight_sales` set caused what looked like five separate liquidation bugs. Deep root-cause diagnosis before patching symptoms turned out to matter a lot.

---

## Status

Active development. Currently paper trading on Alpaca while researching pairs trading strategies (cointegration-based stat arb) as a next-phase edge to layer in alongside or replace the scalping approach. Furthermore looking into natural language processing and news sentiment analysis to improve current bot.

---

*Built by Hayden Hour — CS @ UMass Amherst*
