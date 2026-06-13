import os
import time
from datetime import datetime, time as datetime_time
import pandas as pd
import numpy as np
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# =====================================================================
# HARDENED DUAL-ENGINE VOLATILITY SCALPER ENGINE WITH ASSET PROFILES
# =====================================================================
API_KEY = "PKYOYOZ4LXH7YSZ7WFSG4EWT42"
SECRET_KEY = "2WW321eYFNawsrN8ATDKXY1Kr7WLnbHJYjrzN6bGCTY5"

# Multi-Engine Asset Profiles (The AAPL Filter Fix)
TICKER_CONFIGS = {
    "TSLA": {"rsi_buy_floor": 33, "max_share_allocation": 0.15},
    "NVDA": {"rsi_buy_floor": 32, "max_share_allocation": 0.15},
    "AMD":  {"rsi_buy_floor": 30, "max_share_allocation": 0.10},
    "NFLX": {"rsi_buy_floor": 30, "max_share_allocation": 0.10},
    "META": {"rsi_buy_floor": 30, "max_share_allocation": 0.10},
    "MSFT": {"rsi_buy_floor": 28, "max_share_allocation": 0.10},
    "AMZN": {"rsi_buy_floor": 28, "max_share_allocation": 0.10},
    "AAPL": {"rsi_buy_floor": 24, "max_share_allocation": 0.10}  # Fixed over-trading noise
}

TICKER_SQUAD = list(TICKER_CONFIGS.keys())
RISK_PORTFOLIO_PCT = 0.25  

SUMMARY_FILE = "daily_summary.csv"
TRADE_FILE = "trade_log.csv"

class AlphaHardTargetScalper:
    def __init__(self):
        self.client = TradingClient(API_KEY, SECRET_KEY, paper=True)
        self.in_flight_sales = set()  
        
        self.today_str = datetime.now().strftime('%Y-%m-%d')
        self.ticker_pnl = {ticker: 0.0 for ticker in TICKER_SQUAD}
        self.daily_wins = 0
        self.daily_losses = 0
        
        self._initialize_csv_files()
        self._hydrate_state_from_csv()

    def _initialize_csv_files(self):
        """Ensures both sheets exist with clean structural headers including Engine tracking."""
        if not os.path.exists(SUMMARY_FILE):
            headers = ["Date"] + [f"{t}_PnL" for t in TICKER_SQUAD] + ["Total_PnL", "Wins", "Losses"]
            pd.DataFrame(columns=headers).to_csv(SUMMARY_FILE, index=False)
            
        if not os.path.exists(TRADE_FILE):
            # Added "Engine" tracking column explicitly matching requirements
            headers = ["Trade_ID", "Ticker", "Type", "Qty", "Entry_Time", "Entry_Price", "Exit_Time", "Exit_Price", "PnL", "Status", "Engine"]
            df = pd.DataFrame(columns=headers)
            df = df.astype({"Entry_Time": str, "Exit_Time": str, "Status": str, "Trade_ID": str, "Engine": str})
            df.to_csv(TRADE_FILE, index=False)

    def _hydrate_state_from_csv(self):
        """Reads ledger entries to recover state parameters on mid-day restart."""
        if not os.path.exists(TRADE_FILE): return
        
        df = pd.read_csv(TRADE_FILE, dtype={"Entry_Time": str, "Exit_Time": str, "Status": str, "Trade_ID": str, "Engine": str})
        if df.empty: return
        
        df['Entry_Time'] = df['Entry_Time'].astype(str)
        today_trades = df[df['Entry_Time'].str.contains(self.today_str)]
        closed_today = today_trades[today_trades['Status'] == 'CLOSED']
        
        for ticker in TICKER_SQUAD:
            ticker_trades = closed_today[closed_today['Ticker'] == ticker]
            self.ticker_pnl[ticker] = float(ticker_trades['PnL'].sum())
            
        self.daily_wins = int((closed_today['PnL'] > 0).sum())
        self.daily_losses = int((closed_today['PnL'] <= 0).sum())
        print(f"🔄 State Recovery Complete: Loaded {len(closed_today)} entries. Today's Record: {self.daily_wins}W-{self.daily_losses}L")

    def get_active_engine(self) -> str:
        """Evaluates time blocks to route structural execution parameters."""
        current_time = datetime.now().time()
        lull_start = datetime_time(11, 30)
        lull_end = datetime_time(13, 30)
        
        if lull_start <= current_time < lull_end:
            return "ENGINE_B"  # Midday Conservative Mean-Reversion
        return "ENGINE_A"      # High-Velocity Momentum Run

    def check_buy_signal(self, ticker: str, current_rsi: float) -> bool:
        """Determines entry conditions adjusting dynamically for asset profile and engine."""
        if ticker not in TICKER_CONFIGS:
            rsi_threshold = 30.0
        else:
            rsi_threshold = TICKER_CONFIGS[ticker]["rsi_buy_floor"]

        current_engine = self.get_active_engine()
        
        # Midday Lull Engine (Engine B) drops thresholds further to avoid fakeouts
        if current_engine == "ENGINE_B":
            rsi_threshold -= 2.0
            
        return current_rsi <= rsi_threshold

    def _log_trade_entry(self, trade_id, ticker, qty, price, engine_used):
        """Appends a new pending LONG sequence row to the CSV file safely with active engine profile."""
        df = pd.read_csv(TRADE_FILE, dtype={"Entry_Time": str, "Exit_Time": str, "Status": str, "Trade_ID": str, "Engine": str})
        new_row = {
            "Trade_ID": str(trade_id), "Ticker": ticker, "Type": "LONG", "Qty": int(qty),
            "Entry_Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "Entry_Price": round(float(price), 2),
            "Exit_Time": "", "Exit_Price": "", "PnL": 0.0, "Status": "OPEN", "Engine": engine_used
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(TRADE_FILE, index=False)

    def _log_trade_exit(self, ticker, qty, price):
        """Locates the oldest open position row for an asset, closes it, and recalibrates summaries."""
        df = pd.read_csv(TRADE_FILE, dtype={"Entry_Time": str, "Exit_Time": str, "Status": str, "Trade_ID": str, "Engine": str})
        open_mask = (df['Ticker'] == ticker) & (df['Status'] == 'OPEN')
        
        if not open_mask.any(): return
            
        idx = df[open_mask].index[0]
        entry_price = float(df.loc[idx, 'Entry_Price'])
        trade_pnl = round((round(float(price), 2) - entry_price) * int(qty), 2)
        
        df.at[idx, 'Exit_Time'] = str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        df.at[idx, 'Exit_Price'] = round(float(price), 2)
        df.at[idx, 'PnL'] = float(trade_pnl)
        df.at[idx, 'Status'] = "CLOSED"
        df.to_csv(TRADE_FILE, index=False)
        
        self.ticker_pnl[ticker] += trade_pnl
        if trade_pnl > 0:
            self.daily_wins += 1
        else:
            self.daily_losses += 1
            
        self._update_daily_summary()

    def _update_daily_summary(self):
        """Overwrites or inserts today's aggregated dashboard stats line."""
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
        print(f"📊 Dashboard Sync: Day PnL: ${total_pnl:.2f} | Record: {self.daily_wins}W-{self.daily_losses}L")

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
        print(f"⏱️ Target Scan Initiated: {now.strftime('%H:%M:%S')} | Engine Profile: {active_engine}")
        
        market_close_imminent = now.hour == 15 and now.minute >= 45
        emergency_liquidation_zone = now.hour == 15 and now.minute >= 57

        try:
            positions = self.client.get_all_positions()
            portfolio = {pos.symbol: int(pos.qty) for pos in positions}
        except Exception as e:
            print(f"⚠️ Alpaca connection throttled: {e}. Bypassing this scan loop.")
            return

        if emergency_liquidation_zone and len(positions) > 0:
            print("🚨 [POWER HOUR E-STOP] Forcing total portfolio liquidation.")
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
        except Exception: return

        for ticker in TICKER_SQUAD:
            try:
                ticker_df = shared_data[ticker].dropna()
                if ticker_df.empty: continue
                
                current_price = ticker_df['Close'].iloc[-1]
                is_holding = ticker in portfolio

                if not is_holding and ticker in self.in_flight_sales:
                    self.in_flight_sales.remove(ticker)

                # =========================================================
                # PASS 1: OPEN POSITION RISKS AND TRACKING EXITS
                # =========================================================
                if is_holding and ticker not in self.in_flight_sales:
                    alpaca_position = next(pos for pos in positions if pos.symbol == ticker)
                    avg_entry_price = float(alpaca_position.avg_entry_price)
                    
                    atr = self.calculate_atr(ticker_df)
                    
                    # Engine Routing Risk Modifiers
                    atr_multiplier = 1.5 if active_engine == "ENGINE_A" else 1.0
                    
                    target_tp = avg_entry_price + (atr * atr_multiplier * 2.0)
                    target_sl = avg_entry_price - (atr * atr_multiplier)

                    if current_price >= target_tp or current_price <= target_sl:
                        if self.execute_order(ticker, portfolio[ticker], OrderSide.SELL):
                            self.in_flight_sales.add(ticker)
                            self._log_trade_exit(ticker, portfolio[ticker], current_price)
                        continue
                        
                    rsi = self.calculate_rsi(ticker_df)
                    if rsi >= 72:
                        if self.execute_order(ticker, portfolio[ticker], OrderSide.SELL):
                            self.in_flight_sales.add(ticker)
                            self._log_trade_exit(ticker, portfolio[ticker], current_price)

                # =========================================================
                # PASS 2: FLAT ENTRIES WITH THE UPGRADED DUAL SIGNAL ENGINE
                # =========================================================
                elif not is_holding:
                    if market_close_imminent: continue
                        
                    rsi = self.calculate_rsi(ticker_df)
                    
                    # Linked direct to asset-customized routing logic function
                    if self.check_buy_signal(ticker, rsi):
                        try:
                            current_account = self.client.get_account()
                            live_buying_power = float(current_account.buying_power)
                        except Exception:
                            print(f"⚠️ Account snapshot skipped for {ticker} due to connection delay.")
                            continue

                        # Sizing adjusted safely against distinct capital allocations
                        config = TICKER_CONFIGS.get(ticker, {"max_share_allocation": 0.10})
                        allocated_cash = live_buying_power * config["max_share_allocation"]
                        qty = int(allocated_cash // current_price)
                        
                        if qty > 0 and allocated_cash <= live_buying_power:
                            trade_id = f"tr_{int(time.time())}"
                            if self.execute_order(ticker, qty, OrderSide.BUY):
                                # Added engine execution tracking parameters cleanly to log history rows
                                self._log_trade_entry(trade_id, ticker, qty, current_price, active_engine)
                    
            except Exception as e:
                print(f"❌ Core processing error on asset {ticker}: {e}")

    def execute_order(self, ticker, qty, side):
        try:
            order = MarketOrderRequest(symbol=ticker, qty=qty, side=side, time_in_force=TimeInForce.DAY)
            self.client.submit_order(order)
            print(f"   ✅ DISPATCHED: {side.value.upper()} {qty} shares of {ticker}")
            return True
        except Exception as e:
            print(f"   ⚠️ Blocked/Rejected by Alpaca: {e}")
            return False

if __name__ == "__main__":
    bot = AlphaHardTargetScalper()
    print("⚡ Volatility-Adaptive Fault-Tolerant Scalper Engine Active.")
    
    while True:
        try:
            clock = bot.client.get_clock()
            if not clock.is_open:
                print("🛑 [SYSTEM SHUTDOWN] Market is currently closed.")
                break
                
            bot.execute_scalp_pipeline()
            time.sleep(30)
        except Exception as e:
            print(f"⚠️ Main loop exception: {e}")
            time.sleep(30)