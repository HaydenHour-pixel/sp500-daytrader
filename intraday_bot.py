import os
import time
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
    "TSLA": {"max_share_allocation": 0.12},  
    "NVDA": {"max_share_allocation": 0.12},  
    "AMD":  {"max_share_allocation": 0.10},  
    "NFLX": {"max_share_allocation": 0.10},  
    "META": {"max_share_allocation": 0.10},  
    "MSFT": {"max_share_allocation": 0.10},  
    "AMZN": {"max_share_allocation": 0.10},  
    "AAPL": {"max_share_allocation": 0.10}   
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
            headers = ["Trade_ID", "Ticker", "Type", "Qty", "Entry_Time", "Entry_Price", "Exit_Time", "Exit_Price", "PnL", "Status", "Engine"]
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

    def check_buy_signal(self, current_rsi: float) -> bool:
        """Unified, standardized rsi floor logic."""
        rsi_threshold = 40.0
        if self.get_active_engine() == "ENGINE_B":
            rsi_threshold -= 3.0  # Dynamic midday lull tightening (24.0)
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

    def _log_trade_exit(self, ticker, qty, price):
        """Locates open trade, closes it out, logs statistics, and triggers alert updates."""
        df = pd.read_csv(TRADE_FILE, dtype={"Entry_Time": str, "Exit_Time": str, "Status": str, "Trade_ID": str, "Engine": str})
        open_mask = (df['Ticker'] == ticker) & (df['Status'] == 'OPEN')
        
        if not open_mask.any(): return
            
        idx = df[open_mask].index[0]
        entry_price = float(df.loc[idx, 'Entry_Price'])
        trade_pnl = round((round(float(price), 2) - entry_price) * int(qty), 2)
        
        # --- NEW: TRACK RESULT FOR COOLDOWN LOGIC ---
        self.last_trade_results[ticker] = {
            "time": datetime.now(),
            "pnl": float(trade_pnl)
        }
        
        df.at[idx, 'Exit_Time'] = str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        df.at[idx, 'Exit_Price'] = round(float(price), 2)
        df.at[idx, 'PnL'] = float(trade_pnl)
        df.at[idx, 'Status'] = "CLOSED"
        df.to_csv(TRADE_FILE, index=False)
        
        self.ticker_pnl[ticker] += trade_pnl
        if trade_pnl > 0:
            self.daily_wins += 1
            outcome_emoji = "🟢 *WIN*"
        else:
            self.daily_losses += 1
            outcome_emoji = "🔴 *LOSS*"
            
        self._update_daily_summary()
        
        send_slack_alert(
            f"⚖️ *Position Closed ({ticker})*\n"
            f"• Result: {outcome_emoji}\n"
            f"• Trade PnL: *${trade_pnl:+.2f}*\n"
            f"• Executed Price: ${price:.2f} (Avg Entry: ${entry_price:.2f})\n"
            f"• Current Session Record: {self.daily_wins}W-{self.daily_losses}L"
        )

    def _update_daily_summary(self):
        """Saves current totals to local aggregated metrics dashboard sheets."""
        df = pd.read_csv(SUMMARY_FILE)
        total_pnl = round(sum(self.ticker_pnl.values()), 2)
        
        summary_row = {
            "Date": self.today_str,
            **{f"{t}_PnL": round(self.ticker_pnl[t], 2) for t in TICKER_SQUAD},
            "Total_PnL": total_pnl,
            "Wins": self.daily_wins,
            "Losses": self.daily_losses
        }
        
        if not df.empty and self.today_str in df['Date'].values:
            idx = df[df['Date'] == self.today_str].index[0]
            for col, val in summary_row.items():
                df.at[idx, col] = val
        else:
            df = pd.concat([df, pd.DataFrame([summary_row])], ignore_index=True)
            
        df.to_csv(SUMMARY_FILE, index=False)
        print(f"📊 Summary Sheet Synced | Session PnL: ${total_pnl:.2f} | {self.daily_wins}W-{self.daily_losses}L")

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
        active_engine = self.get_active_engine()
        
        market_close_imminent = now.hour == 15 and now.minute >= 45
        emergency_liquidation_zone = now.hour == 15 and now.minute >= 57

        try:
            positions = self.client.get_all_positions()
            portfolio = {pos.symbol: int(pos.qty) for pos in positions}
        except Exception as e:
            print(f"⚠️ Alpaca connection throttled: {e}. Bypassing this loop.")
            return

        # Power hour emergency safety stop
        if emergency_liquidation_zone and len(positions) > 0:
            send_slack_alert("🚨 *Power Hour Emergency Stop triggered. Clearing all outstanding risk positions.*")
            for pos in positions:
                if pos.symbol not in self.in_flight_sales:
                    if self.execute_order(pos.symbol, int(pos.qty), OrderSide.SELL):
                        self.in_flight_sales.add(pos.symbol)
                        try:
                            latest_price = float(self.client.get_stock_latest_bar(pos.symbol).close)
                        except Exception:
                            latest_price = float(pos.current_price) 
                        self._log_trade_exit(pos.symbol, int(pos.qty), latest_price)
            return

        try:
            shared_data = yf.download(TICKER_SQUAD, period="2d", interval="1m", group_by='ticker', progress=False, timeout=4)
        except Exception as e:
            print(f"⚠️ Yahoo Finance historical payload delayed: {e}")
            return

        for ticker in TICKER_SQUAD:
            try:
                ticker_df = shared_data[ticker].dropna()
                if ticker_df.empty: continue
                
                current_price = ticker_df['Close'].iloc[-1]
                is_holding = ticker in portfolio

                if not is_holding and ticker in self.in_flight_sales:
                    self.in_flight_sales.remove(ticker)

                # =========================================================
                # PASS 1: EXITS WITH TRAILING STOP AND PROFIT TARGET
                # =========================================================
                if is_holding and ticker not in self.in_flight_sales:
                    alpaca_position = next(pos for pos in positions if pos.symbol == ticker)
                    avg_entry_price = float(alpaca_position.avg_entry_price)
                    
                    trailing_level = calculate_trailing_stop(current_price, avg_entry_price)
                    atr = self.calculate_atr(ticker_df)
                    target_tp = avg_entry_price + (atr * 2.0) 

                    if current_price >= target_tp or should_exit_trade(current_price, trailing_level):
                        if self.execute_order(ticker, portfolio[ticker], OrderSide.SELL):
                            self.in_flight_sales.add(ticker)
                            self._log_trade_exit(ticker, portfolio[ticker], current_price)
                        continue
                        
                    rsi = self.calculate_rsi(ticker_df)
                    if rsi >= 72:
                        if self.execute_order(ticker, portfolio[ticker], OrderSide.SELL):
                            self.in_flight_sales.add(ticker)
                            self._log_trade_exit(ticker, portfolio[ticker], current_price)

                # --- PASS 2: ENTRY WITH COOL-DOWN AND VOLATILITY SIZING ---
                elif not is_holding:
                    if market_close_imminent: continue

                    # 1. COOL-DOWN CHECK (Penalty Box)
                    if ticker in self.last_trade_results:
                        last_trade = self.last_trade_results[ticker]
                        if last_trade['pnl'] < 0: # Only cooldown on losses
                            if datetime.now() - last_trade['time'] < timedelta(minutes=15):
                                continue 

                    # 2. CALCULATE ATR FOR SIZING
                    rsi = self.calculate_rsi(ticker_df)
                    current_atr = self.calculate_atr(ticker_df)
                    short_ma = ticker_df['Close'].rolling(window=5).mean().iloc[-1]
                    
                    if rsi <= 50.0 and current_price > short_ma:
                        try:
                            # 3. VOLATILITY-ADJUSTED SIZING
                            # If ATR is high (high volatility), reduce position size
                            atr_ratio = (current_atr / current_price) / self.volatility_base
                            vol_adjustment = min(1.0, 1.0 / atr_ratio) 
                            
                            current_account = self.client.get_account()
                            live_buying_power = float(current_account.buying_power)
                            
                            config = TICKER_CONFIGS.get(ticker, {"max_share_allocation": 0.10})
                            allocated_cash = live_buying_power * (config["max_share_allocation"] * vol_adjustment)
                            
                            qty = int(allocated_cash // current_price)
                            
                            if qty > 0 and allocated_cash <= live_buying_power:
                                trade_id = f"tr_{int(time.time())}"
                                if self.execute_order(ticker, qty, OrderSide.BUY):
                                    self._log_trade_entry(trade_id, ticker, qty, current_price, active_engine, rsi)
                                    send_slack_alert(
                                        f"🚀 *Position Opened ({ticker})*\n"
                                        f"• Action: *BUY (Trend-Aware)*\n"
                                        f"• Shares: {qty}\n"
                                        f"• Price: ${current_price:.2f}\n"
                                        f"• RSI at Entry: {rsi:.1f}\n"
                                        f"• Engine: {active_engine}"
                                    )
                        except Exception as e:
                            print(f"❌ Processing error on asset {ticker}: {e}")
                            
            except Exception as e:
                print(f"❌ Critical loop error on asset {ticker}: {e}")

    def execute_order(self, ticker, qty, side):
        try:
            order = MarketOrderRequest(symbol=ticker, qty=qty, side=side, time_in_force=TimeInForce.DAY)
            self.client.submit_order(order)
            print(f"   ✅ DISPATCHED: {side.value.upper()} {qty} shares of {ticker}")
            return True
        except Exception as e:
            print(f"   ⚠️ Order rejected: {e}")
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
            time.sleep(60) 
        else:
            # Outside hours, wait 5 minutes before checking if market is open
            time.sleep(300)