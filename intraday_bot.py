import time
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# =====================================================================
# AGGRESSIVE HIGH-ACTIVITY INTEGRATED SCALPING ENGINE
# =====================================================================
API_KEY = "PKYOYOZ4LXH7YSZ7WFSG4EWT42"
SECRET_KEY = "2WW321eYFNawsrN8ATDKXY1Kr7WLnbHJYjrzN6bGCTY5"

# Ultra-liquid, high-beta tech assets optimized for high-frequency scalping
TICKER_SQUAD = ["TSLA", "NVDA", "AMD", "AAPL", "MSFT", "META", "AMZN", "NFLX"]
RISK_PORTFOLIO_PCT = 0.25  # Allocate 25% of total buying power per trade position

class AlphaAggressiveScalper:
    def __init__(self):
        self.client = TradingClient(API_KEY, SECRET_KEY, paper=True)

    def calculate_rsi_signals(self, df):
        """Calculates ultra-fast 14-period RSI windows on 1-minute historical frames."""
        if len(df) < 20:
            return "HOLD"

        # Fast Vectorized RSI Formula
        change = df['Close'].diff()
        gain = change.mask(change < 0, 0)
        loss = -change.mask(change > 0, 0)
        
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        
        # Avoid division by zero anomalies
        rs = avg_gain / np.where(avg_loss == 0, 0.00001, avg_loss)
        df['RSI'] = 100 - (100 / (1 + rs))
        
        current_rsi = df['RSI'].iloc[-1]

        # Aggressive Scalping Boundaries
        if current_rsi <= 32:
            return "BUY"
        elif current_rsi >= 68:
            return "SELL"
            
        return "HOLD"

    def execute_scalp_pipeline(self):
        """Monitors rapid 1-minute movements and dynamically deploys heavy cash buckets."""
        now = datetime.now()
        print(f"⏱️ Aggressive Scan Initiated: {now.strftime('%H:%M:%S')}")
        
        try:
            if not self.client.get_clock().is_open:
                print("🛑 Market Closed.")
                return
        except Exception as e:
            return

        # Fetch active profile updates to calculate dynamic buying power scale
        account = self.client.get_account()
        total_buying_power = float(account.buying_power)
        target_cash_allocation = total_buying_power * RISK_PORTFOLIO_PCT

        positions = self.client.get_all_positions()
        portfolio = {pos.symbol: int(pos.qty) for pos in positions}

        # CONCURRENT HIGH-FREQUENCY DOWNLOAD: 1-minute historical slices
        try:
            shared_data = yf.download(TICKER_SQUAD, period="1d", interval="1m", group_by='ticker', progress=False, timeout=4)
        except Exception:
            return

        for ticker in TICKER_SQUAD:
            try:
                ticker_df = shared_data[ticker].dropna()
                if ticker_df.empty: 
                    continue
                
                signal = self.calculate_rsi_signals(ticker_df)
                is_holding = ticker in portfolio
                current_price = ticker_df['Close'].iloc[-1]

                if signal == "BUY" and not is_holding:
                    # Dynamically compute massive position quantities based on cash profile
                    qty = int(target_cash_allocation // current_price)
                    if qty > 0:
                        print(f"🚀 [SCALP BUY SIGNAL] {ticker} is deeply oversold at ${current_price:.2f}. Allocating ${qty*current_price:,.2f}")
                        self.execute_order(ticker, qty, OrderSide.BUY)
                        
                elif signal == "SELL" and is_holding:
                    qty = portfolio[ticker]
                    print(f"💥 [SCALP EXIT SIGNAL] {ticker} overbought momentum peak at ${current_price:.2f}. Liquidating position...")
                    self.execute_order(ticker, qty, OrderSide.SELL)
                    
            except Exception as e:
                pass

    def execute_order(self, ticker, qty, side):
        try:
            order = MarketOrderRequest(symbol=ticker, qty=qty, side=side, time_in_force=TimeInForce.DAY)
            self.client.submit_order(order)
            print(f"   ✅ DISPATCHED: {side.value.upper()} {qty} shares of {ticker}")
        except Exception as e:
            print(f"   ⚠️ Blocked: {e}")

if __name__ == "__main__":
    bot = AlphaAggressiveScalper()
    print("⚡ Heavy Allocation High-Frequency Scalper Initialized.")
    while True:
        bot.execute_scalp_pipeline()
        time.sleep(30)  # Scan rapidly twice every minute