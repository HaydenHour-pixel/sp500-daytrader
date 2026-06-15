import os
import time
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# =====================================================================
# HARDENED VOLATILITY-ADAPTIVE SCALPER ENGINE WITH SEQUENTIAL RISK GUARD
# =====================================================================
API_KEY = "PKYOYOZ4LXH7YSZ7WFSG4EWT42"
SECRET_KEY = "2WW321eYFNawsrN8ATDKXY1Kr7WLnbHJYjrzN6bGCTY5"

TICKER_SQUAD = ["TSLA", "NVDA", "AMD", "AAPL", "MSFT", "META", "AMZN", "NFLX"]
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
        """Ensures both sheets exist with clean structural headers and explicit types."""
        if not os.path.exists(SUMMARY_FILE):
            headers = ["Date"] + [f"{t}_PnL" for t in TICKER_SQUAD] + ["Total_PnL", "Wins", "Losses"]
            pd.DataFrame(columns=headers).to_csv(SUMMARY_FILE, index=False)
            
        if not os.path.exists(TRADE_FILE):
            headers = ["Trade_ID", "Ticker", "Type", "Qty", "Entry_Time", "Entry_Price", "Exit_Time", "Exit_Price", "PnL", "Status"]
            df = pd.DataFrame(columns=headers)
            df = df.astype({"Entry_Time": str, "Exit_Time": str, "Status": str, "Trade_ID": str})
            df.to_csv(TRADE_FILE, index=False)

    def _hydrate_state_from_csv(self):
        """Reads ledger entries to recover state parameters on mid-day restart."""
        if not os.path.exists(TRADE_FILE): return
        
        df = pd.read_csv(TRADE_FILE, dtype={"Entry_Time": str, "Exit_Time": str, "Status": str, "Trade_ID": str})
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

    def _log_trade_entry(self, trade_id, ticker, qty, price):
        """Appends a new pending LONG sequence row to the CSV file safely."""
        df = pd.read_csv(TRADE_FILE, dtype={"Entry_Time": str, "Exit_Time": str, "Status": str, "Trade_ID": str})
        new_row = {
            "Trade_ID": str(trade_id), "Ticker": ticker, "Type": "LONG", "Qty": int(qty),
            "Entry_Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "Entry_Price": float(price),
            "Exit_Time": "", "Exit_Price": "", "PnL": 0.0, "Status": "OPEN"
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(TRADE_FILE, index=False)

    def _log_trade_exit(self, ticker, qty, price):
        """Locates the oldest open position row for an asset, closes it, and recalibrates summaries."""
        df = pd.read_csv(TRADE_FILE, dtype={"Entry_Time": str, "Exit_Time": str, "Status": str, "Trade_ID": str})
        open_mask = (df['Ticker'] == ticker) & (df['Status'] == 'OPEN')
        
        if not open_mask.any(): return
            
        idx = df[open_mask].index[0]
        entry_price = float(df.loc[idx, 'Entry_Price'])
        trade_pnl = round((float(price) - entry_price) * int(qty), 2)
        
        df.at[idx, 'Exit_Time'] = str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        df.at[idx, 'Exit_Price'] = float(price)
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
        print(f"⏱️ Target Scan Initiated: {now.strftime('%H:%M:%S')}")
        
        market_close_imminent = now.hour == 15 and now.minute >= 45
        emergency_liquidation_zone = now.hour == 15 and now.minute >= 57

        # --- RATE LIMIT GUARD ---
        try:
            positions = self.client.get_all_positions()
            portfolio = {pos.symbol: int(pos.qty) for pos in positions}
        except Exception as e:
            print(f"⚠️ Alpaca connection throttled: {e}. Bypassing this scan loop.")
            return

        # --- EMERGENCY END OF DAY CASH-OUT OUTLET ---
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

        # --- WARM-UP BUFFER: Fetch 2 days of history to seed indicators ---
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

                # --- OPEN POSITION EXITS ---
                if is_holding and ticker not in self.in_flight_sales:
                    alpaca_position = next(pos for pos in positions if pos.symbol == ticker)
                    avg_entry_price = float(alpaca_position.avg_entry_price)
                    
                    atr = self.calculate_atr(ticker_df)
                    target_tp = avg_entry_price + (atr * 2.5)
                    target_sl = avg_entry_price - (atr * 1.5)

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

                # --- FLAT ENTRIES WITH SEQUENTIAL BUYING POWER GUARD ---
                elif not is_holding:
                    if market_close_imminent: continue
                        
                    rsi = self.calculate_rsi(ticker_df)
                    if rsi <= 30:
                        # Fetch live available cash allocation inside the loop right before buying
                        try:
                            current_account = self.client.get_account()
                            live_buying_power = float(current_account.buying_power)
                        except Exception:
                            print(f"⚠️ Account snapshot skipped for {ticker} due to connection delay.")
                            continue

                        allocated_cash = live_buying_power * RISK_PORTFOLIO_PCT
                        qty = int(allocated_cash // current_price)
                        
                        if qty > 0 and allocated_cash <= live_buying_power:
                            trade_id = f"tr_{int(time.time())}"
                            if self.execute_order(ticker, qty, OrderSide.BUY):
                                self._log_trade_entry(trade_id, ticker, qty, current_price)
                    
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