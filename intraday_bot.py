import time
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# =====================================================================
# DYNAMIC VOLATILITY-ADAPTIVE SCALPING ENGINE (ATR INTEGRATED)
# =====================================================================
API_KEY = "PKYOYOZ4LXH7YSZ7WFSG4EWT42"
SECRET_KEY = "2WW321eYFNawsrN8ATDKXY1Kr7WLnbHJYjrzN6bGCTY5"

TICKER_SQUAD = ["TSLA", "NVDA", "AMD", "AAPL", "MSFT", "META", "AMZN", "NFLX"]
RISK_PORTFOLIO_PCT = 0.25  

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

    def calculate_atr(self, df):
        """Calculates 14-period Average True Range to measure real-time price variance."""
        if len(df) < 15: 
            return df['Close'].iloc[-1] * 0.005 # Fallback to standard 0.5% buffer if insufficient bars
            
        high = df['High']
        low = df['Low']
        close_prev = df['Close'].shift(1)
        
        # Calculate True Range (TR) matrix components
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean().iloc[-1]
        return atr

    def execute_scalp_pipeline(self):
        now = datetime.now()
        current_time_str = now.strftime('%H:%M:%S')
        print(f"⏱️ Target Scan Initiated: {current_time_str}")
        
        # TIME GUARD CONTROLS (EST)
        market_close_imminent = now.hour == 15 and now.minute >= 45
        emergency_liquidation_zone = now.hour == 15 and now.minute >= 57

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

                # Release sale lock once position officially clears from Alpaca
                if not is_holding and ticker in self.in_flight_sales:
                    self.in_flight_sales.remove(ticker)

                # --- OPEN POSITION EXITS: VOLATILITY-ADJUSTED TARGETS ---
                if is_holding and ticker not in self.in_flight_sales:
                    alpaca_position = next(pos for pos in positions if pos.symbol == ticker)
                    avg_entry_price = float(alpaca_position.avg_entry_price)
                    
                    # Compute dynamic market boundary metrics
                    atr = self.calculate_atr(ticker_df)
                    target_tp = avg_entry_price + (atr * 2.5)  # 2.5x ATR for upside profit capture
                    target_sl = avg_entry_price - (atr * 1.5)  # 1.5x ATR tight stop-loss protection

                    if current_price >= target_tp:
                        print(f"🎯 [ATR PROFIT TARGET MET] {ticker} caught wave at ${current_price:.2f} (Target was ${target_tp:.2f})")
                        self.execute_order(ticker, portfolio[ticker], OrderSide.SELL)
                        self.in_flight_sales.add(ticker)
                        continue
                    elif current_price <= target_sl:
                        print(f"🛑 [ATR RISK FLOOR BREACHED] {ticker} stopped safely at ${current_price:.2f} (Floor was ${target_sl:.2f})")
                        self.execute_order(ticker, portfolio[ticker], OrderSide.SELL)
                        self.in_flight_sales.add(ticker)
                        continue
                        
                    # Secondary momentum velocity speed-bump exit
                    rsi = self.calculate_rsi(ticker_df)
                    if rsi >= 72:
                        print(f"💥 [INDICATOR EXIT] {ticker} hit overbought RSI ceiling at ${current_price:.2f}")
                        self.execute_order(ticker, portfolio[ticker], OrderSide.SELL)
                        self.in_flight_sales.add(ticker)

                # --- FLAT ENTRIES: MOMENTUM SCALP SEARCH ---
                elif not is_holding:
                    if market_close_imminent:
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

# =====================================================================
# MAIN CONTROLLER LOOP WITH LIVE CLOSING TIME BREAKS
# =====================================================================
if __name__ == "__main__":
    bot = AlphaHardTargetScalper()
    print("⚡ Volatility-Adaptive Scalper Engine with Automated Loop Shutdown Initialized.")
    
    while True:
        try:
            clock = bot.client.get_clock()
            
            if not clock.is_open:
                print(f"🛑 [SYSTEM SHUTDOWN] Market is currently closed. Terminating bot process safely.")
                break  # Breaks out of the while loop entirely to finish execution cleanly
                
            bot.execute_scalp_pipeline()
            time.sleep(30)
            
        except Exception as e:
            print(f"⚠️ Main loop exception encountered: {e}")
            time.sleep(30)