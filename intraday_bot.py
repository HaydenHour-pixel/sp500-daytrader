import time
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# =====================================================================
# UPGRADED HIGH-FREQUENCY SCALPING ENGINE WITH TIME & LOCK GUARDS
# =====================================================================
API_KEY = "PKYOYOZ4LXH7YSZ7WFSG4EWT42"
SECRET_KEY = "2WW321eYFNawsrN8ATDKXY1Kr7WLnbHJYjrzN6bGCTY5"

TICKER_SQUAD = ["TSLA", "NVDA", "AMD", "AAPL", "MSFT", "META", "AMZN", "NFLX"]
RISK_PORTFOLIO_PCT = 0.25  

# Structural risk matrices for pinning high-capital intraday wins
TAKE_PROFIT_PCT = 0.005    # Lock in wins at +0.5%
STOP_LOSS_PCT = 0.007      # Cut losses quickly at -0.7%

class AlphaHardTargetScalper:
    def __init__(self):
        self.client = TradingClient(API_KEY, SECRET_KEY, paper=True)
        self.in_flight_sales = set()  # Local state lock to prevent duplicate order routing

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

    def execute_scalp_pipeline(self):
        now = datetime.now()
        current_time_str = now.strftime('%H:%M:%S')
        print(f"⏱️ Target Scan Initiated: {current_time_str}")
        
        # TIME GUARD CONTROLS (EST)
        # 15:45 (3:45 PM) - No more new positions allowed to avoid overnight exposure
        # 15:57 (3:57 PM) - Hard E-Stop liquidation phase to go to 100% cash
        market_close_imminent = now.hour == 15 and now.minute >= 45
        emergency_liquidation_zone = now.hour == 15 and now.minute >= 57

        try:
            if not self.client.get_clock().is_open: return
        except Exception: return

        # Live cloud-syncing of open execution positions
        positions = self.client.get_all_positions()
        portfolio = {pos.symbol: int(pos.qty) for pos in positions}
        
        # --- EMERGENCY END OF DAY CASH-OUT OUTLET ---
        if emergency_liquidation_zone and len(positions) > 0:
            print("🚨 [POWER HOUR E-STOP] Market close imminent. Forcing total portfolio liquidation.")
            for pos in positions:
                if pos.symbol not in self.in_flight_sales:
                    self.execute_order(pos.symbol, int(pos.qty), OrderSide.SELL)
                    self.in_flight_sales.add(pos.symbol)
            return

        account = self.client.get_account()
        target_cash_allocation = float(account.buying_power) * RISK_PORTFOLIO_PCT

        try:
            shared_data = yf.download(TICKER_SQUAD, period="1d", interval="1m", group_by='ticker', progress=False, timeout=4)
        except Exception: return

        for ticker in TICKER_SQUAD:
            try:
                ticker_df = shared_data[ticker].dropna()
                if ticker_df.empty: continue
                
                current_price = ticker_df['Close'].iloc[-1]
                is_holding = ticker in portfolio

                # Garbage collection: Release the sale lock once the position is officially cleared from Alpaca
                if not is_holding and ticker in self.in_flight_sales:
                    self.in_flight_sales.remove(ticker)

                # --- OPEN POSITION EXITS: HARD TARGET EVALUATION ---
                if is_holding and ticker not in self.in_flight_sales:
                    alpaca_position = next(pos for pos in positions if pos.symbol == ticker)
                    avg_entry_price = float(alpaca_position.avg_entry_price)
                    
                    target_tp = avg_entry_price * (1.0 + TAKE_PROFIT_PCT)
                    target_sl = avg_entry_price * (1.0 - STOP_LOSS_PCT)

                    # Guard Checkpoint Evaluation
                    if current_price >= target_tp:
                        print(f"🎯 [TAKE PROFIT LOCKED] {ticker} hit target boundary at ${current_price:.2f} (Bought at ${avg_entry_price:.2f})")
                        self.execute_order(ticker, portfolio[ticker], OrderSide.SELL)
                        self.in_flight_sales.add(ticker)
                        continue
                    elif current_price <= target_sl:
                        print(f"🛑 [SAFETY STOP TRIGGERED] {ticker} breached risk floor at ${current_price:.2f} (Bought at ${avg_entry_price:.2f})")
                        self.execute_order(ticker, portfolio[ticker], OrderSide.SELL)
                        self.in_flight_sales.add(ticker)
                        continue
                        
                    # Backup technical exit loop
                    rsi = self.calculate_rsi(ticker_df)
                    if rsi >= 70:
                        print(f"💥 [INDICATOR EXIT] {ticker} hit overbought RSI ceiling at ${current_price:.2f}")
                        self.execute_order(ticker, portfolio[ticker], OrderSide.SELL)
                        self.in_flight_sales.add(ticker)

                # --- FLAT ENTRIES: MOMENTUM SCALP SEARCH ---
                elif not is_holding:
                    if market_close_imminent:
                        # Skip processing new signals if we are too close to the closing bell
                        continue
                        
                    rsi = self.calculate_rsi(ticker_df)
                    if rsi <= 30:
                        qty = int(target_cash_allocation // current_price)
                        if qty > 0:
                            print(f"🚀 [SCALP ENTRY] Buying {qty} shares of {ticker} at oversold ${current_price:.2f}")
                            self.execute_order(ticker, qty, OrderSide.BUY)
                    
            except Exception as e:
                print(f"❌ Core processing error on asset {ticker}: {e}")

    def execute_order(self, ticker, qty, side):
        try:
            order = MarketOrderRequest(symbol=ticker, qty=qty, side=side, time_in_force=TimeInForce.DAY)
            self.client.submit_order(order)
            print(f"   ✅ DISPATCHED: {side.value.upper()} {qty} shares of {ticker}")
        except Exception as e:
            print(f"   ⚠️ Blocked: {e}")

if __name__ == "__main__":
    bot = AlphaHardTargetScalper()
    print("⚡ Heavy Allocation Scalper with Multi-Order Locks and Time Controls Active.")
    while True:
        bot.execute_scalp_pipeline()
        time.sleep(30)