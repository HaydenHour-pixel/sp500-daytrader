import os
import time
from datetime import datetime, time as datetime_time
import pandas as pd
import numpy as np
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from dotenv import load_dotenv

# Load credentials from .env file
load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    raise ValueError("❌ CRITICAL ERROR: Alpaca API credentials missing. Check your local .env file.")

# UNIFIED CONFIGURATION (No curve-fitting)
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
        if not os.path.exists(SUMMARY_FILE):
            headers = ["Date"] + [f"{t}_PnL" for t in TICKER_SQUAD] + ["Total_PnL", "Wins", "Losses"]
            pd.DataFrame(columns=headers).to_csv(SUMMARY_FILE, index=False)
            
        if not os.path.exists(TRADE_FILE):
            headers = ["Trade_ID", "Ticker", "Type", "Qty", "Entry_Time", "Entry_Price", "Exit_Time", "Exit_Price", "PnL", "Status", "Engine"]
            pd.DataFrame(columns=headers).to_csv(TRADE_FILE, index=False)

    def _hydrate_state_from_csv(self):
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
        print(f"🔄 State Recovery: Record: {self.daily_wins}W-{self.daily_losses}L")

    def get_active_engine(self) -> str:
        current_time = datetime.now().time()
        lull_start, lull_end = datetime_time(11, 30), datetime_time(13, 30)
        return "ENGINE_B" if lull_start <= current_time < lull_end else "ENGINE_A"

    def check_buy_signal(self, current_rsi: float) -> bool:
        rsi_threshold = 27.0
        if self.get_active_engine() == "ENGINE_B":
            rsi_threshold -= 3.0
        return current_rsi <= rsi_threshold

    def _log_trade_entry(self, trade_id, ticker, qty, price, engine_used):
        df = pd.read_csv(TRADE_FILE)
        new_row = {"Trade_ID": trade_id, "Ticker": ticker, "Type": "LONG", "Qty": qty,
                   "Entry_Time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "Entry_Price": round(float(price), 2),
                   "Status": "OPEN", "Engine": engine_used}
        pd.concat([df, pd.DataFrame([new_row])], ignore_index=True).to_csv(TRADE_FILE, index=False)

    def _log_trade_exit(self, ticker, qty, price):
        df = pd.read_csv(TRADE_FILE)
        idx = df[(df['Ticker'] == ticker) & (df['Status'] == 'OPEN')].index[0]
        trade_pnl = round((float(price) - float(df.loc[idx, 'Entry_Price'])) * int(qty), 2)
        df.loc[idx, ['Exit_Time', 'Exit_Price', 'PnL', 'Status']] = [datetime.now().strftime('%Y-%m-%d %H:%M:%S'), price, trade_pnl, "CLOSED"]
        df.to_csv(TRADE_FILE, index=False)
        self.ticker_pnl[ticker] += trade_pnl
        self.daily_wins += 1 if trade_pnl > 0 else 0
        self.daily_losses += 1 if trade_pnl <= 0 else 0
        self._update_daily_summary()

    def _update_daily_summary(self):
        df = pd.read_csv(SUMMARY_FILE)
        summary_row = {"Date": self.today_str, **{f"{t}_PnL": self.ticker_pnl[t] for t in TICKER_SQUAD},
                       "Total_PnL": sum(self.ticker_pnl.values()), "Wins": self.daily_wins, "Losses": self.daily_losses}
        if self.today_str in df['Date'].values:
            df.loc[df['Date'] == self.today_str, summary_row.keys()] = list(summary_row.values())
        else:
            df = pd.concat([df, pd.DataFrame([summary_row])], ignore_index=True)
        df.to_csv(SUMMARY_FILE, index=False)

    def calculate_indicators(self, df):
        change = df['Close'].diff()
        gain, loss = change.clip(lower=0), -change.clip(upper=0)
        avg_gain, avg_loss = gain.rolling(14).mean(), loss.rolling(14).mean()
        rs = avg_gain / np.where(avg_loss == 0, 0.00001, avg_loss)
        rsi = 100 - (100 / (1 + rs))
        high, low, close_prev = df['High'], df['Low'], df['Close'].shift(1)
        tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(axis=1)
        return rsi.iloc[-1], tr.rolling(14).mean().iloc[-1]

    def execute_scalp_pipeline(self):
        active_engine = self.get_active_engine()
        positions = {pos.symbol: int(pos.qty) for pos in self.client.get_all_positions()}
        shared_data = yf.download(TICKER_SQUAD, period="2d", interval="1m", group_by='ticker', progress=False)
        
        for ticker in TICKER_SQUAD:
            ticker_df = shared_data[ticker].dropna()
            if ticker_df.empty: continue
            current_price = ticker_df['Close'].iloc[-1]
            rsi, atr = self.calculate_indicators(ticker_df)

            if ticker in positions:
                avg_entry = float(next(p.avg_entry_price for p in self.client.get_all_positions() if p.symbol == ticker))
                mult = 1.5 if active_engine == "ENGINE_A" else 1.0
                if current_price >= avg_entry + (atr * mult * 2.0) or current_price <= avg_entry - (atr * mult) or rsi >= 72:
                    if self.client.submit_order(MarketOrderRequest(symbol=ticker, qty=positions[ticker], side=OrderSide.SELL, time_in_force=TimeInForce.DAY)):
                        self._log_trade_exit(ticker, positions[ticker], current_price)
            elif self.check_buy_signal(rsi):
                allocated = (float(self.client.get_account().buying_power) * TICKER_CONFIGS[ticker]["max_share_allocation"]) // current_price
                if allocated > 0:
                    if self.client.submit_order(MarketOrderRequest(symbol=ticker, qty=int(allocated), side=OrderSide.BUY, time_in_force=TimeInForce.DAY)):
                        self._log_trade_entry(f"tr_{int(time.time())}", ticker, int(allocated), current_price, active_engine)

if __name__ == "__main__":
    bot = AlphaHardTargetScalper()
    while bot.client.get_clock().is_open:
        bot.execute_scalp_pipeline()
        time.sleep(30)