import os
import time
import sys
import requests
from datetime import datetime, time as datetime_time, timedelta
import pandas as pd
import numpy as np
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from dotenv import load_dotenv
from bot_enhancements import get_high_volatility_tickers, calculate_trailing_stop, should_exit_trade

# Load secure environment configurations
load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
SLACK_URL = os.getenv("SLACK_WEBHOOK_URL")

# Strict pre-flight sanity checks
if not API_KEY or not SECRET_KEY:
    raise ValueError("❌ CRITICAL ERROR: Alpaca API credentials missing. Check your local .env file.")

# UNIFIED ASSET PROFILES (Standardized Baseline to prevent strategy overfitting)
TICKER_CONFIGS = {
    "TSLA": {"max_share_allocation": 0.12, "engine_b_allocation": 0.06},
    "NVDA": {"max_share_allocation": 0.12, "engine_b_allocation": 0.06},
    "AMD":  {"max_share_allocation": 0.10, "engine_b_allocation": 0.05},
    "NFLX": {"max_share_allocation": 0.10, "engine_b_allocation": 0.05},
    "META": {"max_share_allocation": 0.10, "engine_b_allocation": 0.05},
    "MSFT": {"max_share_allocation": 0.10, "engine_b_allocation": 0.05},
    "AMZN": {"max_share_allocation": 0.10, "engine_b_allocation": 0.05},
    "AAPL": {"max_share_allocation": 0.10, "engine_b_allocation": 0.05}
}

TICKER_SQUAD = list(TICKER_CONFIGS.keys())
SUMMARY_FILE = "daily_summary.csv"
TRADE_FILE = "trade_log.csv"

def send_slack_alert(message: str):
    """Dispatches a structured message payload directly to your Slack workspace."""
    if not SLACK_URL:
        return  # Fail silently if notifications are unconfigured
    try:
        response = requests.post(SLACK_URL, json={"text": message}, timeout=5)
        if response.status_code != 200:
            print(f"⚠️ Slack alert dispatch failed: {response.text}")
    except Exception as e:
        print(f"⚠️ Slack integration connection error: {e}")

class AlphaHardTargetScalper:
    def __init__(self):
        self.client = TradingClient(API_KEY, SECRET_KEY, paper=True)
        self.in_flight_sales = set()  
        self.today_str = datetime.now().strftime('%Y-%m-%d')
        self.ticker_pnl = {ticker: 0.0 for ticker in TICKER_SQUAD}
        self.daily_wins = 0
        self.daily_losses = 0
        self.last_trade_results = {} # Tracks {ticker: {"time": datetime, "pnl": float}}
        self.volatility_base = 0.005 # Baseline 0.5% ATR target
        
        self._initialize_csv_files()
        self._hydrate_state_from_csv()
        
        # Announce bot initialization on startup
        send_slack_alert(f"🟢 *System Initialized & Recovered*\n• Today's Baseline Record: {self.daily_wins}W-{self.daily_losses}L\n• Active Tracking Assets: {', '.join(TICKER_SQUAD)}")

    def _initialize_csv_files(self):
        """Creates output tracking sheets locally if missing."""
        if not os.path.exists(SUMMARY_FILE):
            headers = ["Date"] + [f"{t}_PnL" for t in TICKER_SQUAD] + ["Total_PnL", "Wins", "Losses"]
            pd.DataFrame(columns=headers).to_csv(SUMMARY_FILE, index=False)
            
        if not os.path.exists(TRADE_FILE):
            headers = ["Trade_ID", "Ticker", "Type", "Qty", "Entry_Time", "Entry_Price", "Exit_Time", "Exit_Price", "PnL", "Status", "Engine", "RSI_At_Entry"]
            pd.DataFrame(columns=headers).to_csv(TRADE_FILE, index=False)

    def _hydrate_state_from_csv(self):
        """Loads today's history from trade sheets to maintain state consistency across restarts."""
        if not os.path.exists(TRADE_FILE): return
        df = pd.read_csv(TRADE_FILE, dtype={"Entry_Time": str, "Exit_Time": str, "Status": str, "Trade_ID": str, "Engine": str})
        if df.empty: return
        
        today_trades = df[df['Entry_Time'].str.contains(self.today_str)]
        closed_today = today_trades[today_trades['Status'] == 'CLOSED']
        
        for ticker in TICKER_SQUAD:
            ticker_trades = closed_today[closed_today['Ticker'] == ticker]
            self.ticker_pnl[ticker] = float(ticker_trades['PnL'].sum())
            
        self.daily_wins = int((closed_today['PnL'] > 0).sum())
        self.daily_losses = int((closed_today['PnL'] <= 0).sum())
        print(f"🔄 State Recovery: Hydrated {len(closed_today)} past entries. Session: {self.daily_wins}W-{self.daily_losses}L")

    def get_active_engine(self) -> str:
        """Determines active time windows to adapt entry behaviors."""
        current_time = datetime.now().time()
        lull_start = datetime_time(11, 30)
        lull_end = datetime_time(13, 30)
        return "ENGINE_B" if lull_start <= current_time < lull_end else "ENGINE_A"

    def check_buy_signal(self, current_rsi: float, current_atr: float, current_price: float) -> bool:
        """Adaptive RSI entry with volatility filter for ENGINE_B."""
        active_engine = self.get_active_engine()

        if active_engine == "ENGINE_A":
            rsi_threshold = 32.0
        else:  # ENGINE_B
            rsi_threshold = 45.0
            # During lull, only enter if volatility has DROPPED relative to morning
            baseline_atr = 0.01  # RELAXED from 0.015 to 1.0% (was 1.5%)
            atr_pct = current_atr / current_price
            if atr_pct > baseline_atr:
                # Volatility still elevated, skip entry
                return False

        return current_rsi <= rsi_threshold

    def _log_trade_entry(self, trade_id, ticker, qty, price, engine_used, rsi_at_entry):
        """Saves a pending position entry along with the decision context (RSI/Engine) for future AI training."""
        # Ensure the header includes RSI_At_Entry if creating the file for the first time
        df = pd.read_csv(TRADE_FILE)
        
        new_row = {
            "Trade_ID": str(trade_id), 
            "Ticker": ticker, 
            "Type": "LONG", 
            "Qty": int(qty),
            "Entry_Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
            "Entry_Price": round(float(price), 2),
            "RSI_At_Entry": round(float(rsi_at_entry), 2), # New AI Context
            "Engine": engine_used,                         # New AI Context
            "Exit_Time": "", 
            "Exit_Price": "", 
            "PnL": 0.0, 
            "Status": "OPEN"
        }
        
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(TRADE_FILE, index=False)

    def _get_open_trade_id(self, ticker):
        """Looks up the Trade_ID of the current OPEN position for a ticker."""
        df = pd.read_csv(TRADE_FILE, dtype={"Trade_ID": str})
        open_mask = (df['Ticker'] == ticker) & (df['Status'] == 'OPEN')
        if not open_mask.any():
            return None
        return str(df.loc[df[open_mask].index[0], 'Trade_ID'])

    def _log_trade_exit(self, ticker, qty, price, trade_id=None):
        """Appends a new CLOSED exit-leg row, updates stats, and sends context-aware Slack alerts."""
        df = pd.read_csv(TRADE_FILE, dtype={"Trade_ID": str, "Status": str, "Entry_Time": str})

        # 1. Locate the corresponding OPEN trade
        if trade_id is not None:
            open_mask = (df['Ticker'] == ticker) & (df['Trade_ID'] == trade_id) & (df['Status'] == 'OPEN')
        else:
            open_mask = (df['Ticker'] == ticker) & (df['Status'] == 'OPEN')

        if not open_mask.any():
            print(f"⚠️ Warning: Attempted to log exit for {ticker} but no OPEN position found.")
            return
            
        idx = df[open_mask].index[0]
        trade_id = str(df.loc[idx, 'Trade_ID'])
        entry_price = float(df.loc[idx, 'Entry_Price'])

        # 2. Calculate PnL for this specific leg
        leg_pnl = round((round(float(price), 2) - entry_price) * int(qty), 2)

        # 3. Create a NEW row for this Exit
        exit_row = {
            "Trade_ID": trade_id,
            "Ticker": ticker,
            "Type": "LONG",
            "Qty": int(qty),
            "Entry_Time": "",
            "Entry_Price": "",
            "Exit_Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "Exit_Price": round(float(price), 2),
            "PnL": float(leg_pnl),
            "Status": "CLOSED",
            "Engine": df.loc[idx, 'Engine']
        }
        
        df = pd.concat([df, pd.DataFrame([exit_row])], ignore_index=True)
        df.to_csv(TRADE_FILE, index=False)
        
        # 4. Update bot memory
        self.last_trade_results[ticker] = {"time": datetime.now(), "pnl": float(leg_pnl)}
        self.ticker_pnl[ticker] += leg_pnl
        
        # 5. Determine if this is the final closing exit
        is_final_exit = True
        
        # Calculate total trade PnL for the final alert (single exit leg now, so it equals leg_pnl)
        all_exits_pnl = leg_pnl

        # Track result for cooldown decision
        self.last_trade_results[ticker] = {
            "time": datetime.now(),
            "pnl": float(all_exits_pnl),
            "is_loss": all_exits_pnl <= 0
        }

        # 6. Update status to CLOSED if final exit, then trigger summary refresh
        if is_final_exit:
            df.at[idx, 'Status'] = "CLOSED"
            df.to_csv(TRADE_FILE, index=False)
            
            outcome_emoji = "🟢 *WIN*" if all_exits_pnl > 0 else "🔴 *LOSS*"

            if all_exits_pnl > 0:
                self.daily_wins += 1
            else:
                self.daily_losses += 1

            message = (f"⚖️ *Position Closed ({ticker})*\n"
                       f"• Result: {outcome_emoji}\n"
                       f"• Trade PnL: *${all_exits_pnl:+.2f}*\n"
                       f"• Executed Price: ${price:.2f} (Avg Entry: ${entry_price:.2f})\n"
                       f"• Current Session Record: {self.daily_wins}W-{self.daily_losses}L")

        send_slack_alert(message)
        self._update_daily_summary()

    def _update_daily_summary(self):
        """Refreshes summary metrics by reading the source-of-truth trade log."""
        if not os.path.exists(TRADE_FILE): return

        df = pd.read_csv(TRADE_FILE, dtype={"Trade_ID": str, "Status": str, "Entry_Time": str})

        # Step 1: find Trade_IDs entered today that are fully CLOSED
        today_closed_ids = df[
            df['Entry_Time'].str.contains(self.today_str, na=False) &
            (df['Status'] == 'CLOSED')
        ]['Trade_ID'].unique()

        # Step 2: sum PnL from exit-leg rows only (identified by a blank Entry_Time; entry rows carry 0.0)
        exit_rows = df[(df['Trade_ID'].isin(today_closed_ids)) & (df['Entry_Time'].isna())]
        trade_summary = exit_rows.groupby('Trade_ID')['PnL'].sum()

        total_pnl = round(trade_summary.sum(), 2)
        wins = int((trade_summary > 0).sum())
        losses = int((trade_summary <= 0).sum())

        # Update summary file
        summary_df = pd.read_csv(SUMMARY_FILE)
        summary_row = {
            "Date": self.today_str,
            **{f"{t}_PnL": round(exit_rows[exit_rows['Ticker'] == t]['PnL'].sum(), 2) for t in TICKER_SQUAD},
            "Total_PnL": total_pnl,
            "Wins": wins,
            "Losses": losses
        }
        
        if not summary_df.empty and self.today_str in summary_df['Date'].values:
            idx = summary_df[summary_df['Date'] == self.today_str].index[0]
            for col, val in summary_row.items():
                summary_df.at[idx, col] = val
        else:
            summary_df = pd.concat([summary_df, pd.DataFrame([summary_row])], ignore_index=True)
            
        summary_df.to_csv(SUMMARY_FILE, index=False)
        print(f"📊 Summary Sheet Synced | Total PnL: ${total_pnl:.2f} | {wins}W-{losses}L")

    def calculate_rsi(self, df):
        if len(df) < 20: return 50
        change = df['Close'].diff()
        gain = change.mask(change < 0, 0)
        loss = -change.mask(change > 0, 0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / np.where(avg_loss == 0, 0.00001, avg_loss)
        df['RSI'] = 100 - (100 / (1 + rs))
        return df['RSI'].iloc[-1]

    def calculate_atr(self, df):
        if len(df) < 15: 
            return df['Close'].iloc[-1] * 0.005
        high, low, close_prev = df['High'], df['Low'], df['Close'].shift(1)
        tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(axis=1)
        return tr.rolling(window=14).mean().iloc[-1]

    def execute_scalp_pipeline(self):
        now = datetime.now()
        print(f"⏱️ Target Scan Initiated: {now.strftime('%H:%M:%S')}")

        active_engine = self.get_active_engine()
        market_close_imminent = now.hour == 15 and now.minute >= 45

        # 2. Fetch Portfolio and Market Data
        try:
            positions = self.client.get_all_positions()
            portfolio = {pos.symbol: int(pos.qty) for pos in positions}
        except Exception as e:
            print(f"⚠️ Position fetch failed: {e}")
            return

        # Emergency Liquidation Zone: force-close everything before market close
        emergency_liquidation_zone = now.hour == 15 and now.minute >= 57

        if emergency_liquidation_zone and len(positions) > 0:
            print(f"🚨 [E-STOP TRIGGERED] {len(positions)} open positions detected at {now.strftime('%H:%M:%S')}")
            send_slack_alert(f"🚨 *Power Hour E-Stop: Liquidating {len(positions)} position(s) before close.*")
            for pos in positions:
                print(f"   Liquidating {pos.symbol}: {int(pos.qty)} shares @ ${pos.current_price}")
                if pos.symbol not in self.in_flight_sales:
                    if self.execute_order(pos.symbol, int(pos.qty), OrderSide.SELL):
                        print(f"   ✅ Order accepted for {pos.symbol}")
                        self.in_flight_sales.add(pos.symbol)
                        try:
                            latest_price = float(pos.current_price)
                        except Exception:
                            latest_price = float(pos.avg_entry_price)
                        trade_id = self._get_open_trade_id(pos.symbol)
                        self._log_trade_exit(pos.symbol, int(pos.qty), latest_price, trade_id)
                    else:
                        print(f"   ❌ Order REJECTED for {pos.symbol}")
            return

        try:
            shared_data = yf.download(TICKER_SQUAD, period="2d", interval="1m", group_by='ticker', progress=False, timeout=5)
        except Exception as e:
            print(f"⚠️ yfinance download failed: {e}")
            return

        loaded = [t for t in TICKER_SQUAD if t in shared_data and not shared_data[t].dropna().empty]
        print(f"   📊 Data loaded for {len(loaded)}/{len(TICKER_SQUAD)} tickers")

        for ticker in TICKER_SQUAD:
            try:
                ticker_df = shared_data[ticker].dropna()
                if ticker_df.empty:
                    print(f"   ⏭️ {ticker}: no data this cycle")
                    continue
                
                current_price = ticker_df['Close'].iloc[-1]
                is_holding = ticker in portfolio

                # --- PASS 1: EXIT LOGIC ---
                if is_holding:
                    # Hard lull close fires regardless of in_flight_sales state
                    if now.hour == 13 and now.minute < 5:
                        if ticker not in self.in_flight_sales:
                            alpaca_position = next(pos for pos in positions if pos.symbol == ticker)
                            qty = int(alpaca_position.qty)
                            current_price_val = float(alpaca_position.current_price)
                            if self.execute_order(ticker, qty, OrderSide.SELL):
                                trade_id = self._get_open_trade_id(ticker)
                                self._log_trade_exit(ticker, qty, current_price_val, trade_id)
                                send_slack_alert(f"🏁 *Lull Close ({ticker})*: Position liquidated at 13:00.")
                                self.in_flight_sales.add(ticker)
                        continue

                    if ticker not in self.in_flight_sales:
                        alpaca_position = next(pos for pos in positions if pos.symbol == ticker)
                        avg_entry = float(alpaca_position.avg_entry_price)
                        qty = int(alpaca_position.qty)

                        # GUARD: Close entire position if qty is too small to split (prevents "dust" trades)
                        if qty < 5:
                            if self.execute_order(ticker, qty, OrderSide.SELL):
                                self._log_trade_exit(ticker, qty, current_price)
                            continue

                        atr = self.calculate_atr(ticker_df)

                        if active_engine == "ENGINE_A":
                            target_tp_final = avg_entry + (atr * 3.0)
                            trailing_multiplier = 1.5
                        else:  # ENGINE_B
                            target_tp_final = avg_entry + (atr * 1.0)
                            trailing_multiplier = 0.3

                        # Single exit: trailing stop OR take-profit target reached
                        trailing_level = calculate_trailing_stop(current_price, avg_entry, atr, trailing_multiplier)

                        if current_price >= target_tp_final or should_exit_trade(current_price, trailing_level):
                            if self.execute_order(ticker, qty, OrderSide.SELL):
                                self.in_flight_sales.add(ticker)
                                trade_id = self._get_open_trade_id(ticker)
                                self._log_trade_exit(ticker, qty, current_price, trade_id)
                                time.sleep(30)
                            continue

                # --- PASS 2: ADAPTIVE ENTRY ---
                elif not is_holding and not market_close_imminent:
                    # Guard: use local trade log as authoritative source to prevent ghost re-entries
                    try:
                        open_trades_df = pd.read_csv(TRADE_FILE, dtype={"Status": str})
                        already_open = not open_trades_df[
                            (open_trades_df['Ticker'] == ticker) &
                            (open_trades_df['Status'] == 'OPEN')
                        ].empty
                        if already_open:
                            continue
                    except Exception:
                        pass  # If log unreadable, allow the trade to proceed

                    # COOLDOWN: Wait longer after a loss than after a win
                    if ticker in self.last_trade_results:
                        is_loss = self.last_trade_results[ticker].get('is_loss', False)
                        cooldown_minutes = 30 if is_loss else 10
                        elapsed = (datetime.now() - self.last_trade_results[ticker]['time']).total_seconds() / 60
                        if elapsed < cooldown_minutes:
                            continue

                    rsi = self.calculate_rsi(ticker_df)
                    current_atr = self.calculate_atr(ticker_df)
                    
                    if self.check_buy_signal(rsi, current_atr, current_price):
                        # Dynamic Sizing
                        buy_power = float(self.client.get_account().buying_power)
                        config = TICKER_CONFIGS.get(ticker, {"max_share_allocation": 0.05})
                        if active_engine == "ENGINE_B":
                            allocation = config.get("engine_b_allocation", 0.05)
                        else:
                            allocation = config["max_share_allocation"]
                        qty = int((buy_power * allocation) // current_price)
                        
                        if qty > 0 and (qty * current_price) <= buy_power:
                            if self.execute_order(ticker, qty, OrderSide.BUY):
                                self._log_trade_entry(f"tr_{int(time.time())}", ticker, qty, current_price, active_engine, rsi)
                                send_slack_alert(
                                    f"🚀 *Position Opened ({ticker})*\n"
                                    f"• Action: *BUY (Trend-Aware)*\n"
                                    f"• Shares: {qty}\n"
                                    f"• Price: ${current_price:.2f}\n"
                                    f"• RSI at Entry: {rsi:.1f}\n"
                                    f"• Engine: {active_engine}"
                                )
                                time.sleep(60) # Cool down after entry to let trend develop

            except Exception as e:
                print(f"❌ Execution error on {ticker}: {e}")

    def execute_order(self, ticker, qty, side, tif=None):
        try:
            if tif is None:
                tif = TimeInForce.IOC if datetime.now().hour >= 15 and datetime.now().minute >= 55 else TimeInForce.DAY
            order = MarketOrderRequest(symbol=ticker, qty=qty, side=side, time_in_force=tif)
            self.client.submit_order(order)
            print(f"   ✅ DISPATCHED: {side.value.upper()} {qty} shares of {ticker}")
            return True
        except Exception as e:
            print(f"   ❌ Order REJECTED ({ticker}): {e}")
            return False

if __name__ == "__main__":
    bot = AlphaHardTargetScalper()
    print(f"🚀 Bot armed and monitoring {len(TICKER_SQUAD)} assets...")
    
    # 09:30 AM to 04:00 PM EST market window
    market_open = datetime_time(9, 30)
    market_close = datetime_time(16, 0)

    while True:
        now = datetime.now().time()

        # Check if we are inside market hours
        if market_open <= now <= market_close:
            try:
                bot.execute_scalp_pipeline()
            except Exception as e:
                print(f"⚠️ Loop interruption: {e}. Resuming in 60s...")

            # Throttle the loop to prevent excessive API hits
            time.sleep(30)
        else:
            if now > market_close:
                print("🛑 Market closed. Shutting down.")
                send_slack_alert("🛑 *Market closed. Bot shutting down cleanly.*")
                break
            else:
                time.sleep(300)  # Pre-market, wait 5 min