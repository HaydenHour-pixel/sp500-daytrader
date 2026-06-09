import time
from datetime import datetime
import pandas as pd
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# =====================================================================
# CONFIGURATION (NEW DAY TRADING ENGINE)
# =====================================================================
API_KEY = "PKGLJLDAHO6WQN45EP7LE3IRVF"
SECRET_KEY = "7bSv7qea6x5odDp1heHLBdNx2M1GppPjtqyvjfkCEF8j"

# Day trading needs highly liquid, high-volatility targets. 
# We trade a small, hyper-focused squad instead of the entire S&P 500.
TICKER_SQUAD = ["TSLA", "NVDA", "AMD", "AAPL", "MSFT", "META", "AMZN", "NFLX"]
TRADE_ALLOCATION = 2000  # Smaller size appropriate for 4x intraday leverage scaling

class AlphaDayTrader:
    def __init__(self):
        self.client = TradingClient(API_KEY, SECRET_KEY, paper=True)
        
    def calculate_adaptive_signals(self, df):
        """
        Adaptive Quant Strategy: Combines an Exponential Moving Average (EMA) 
        crossover with an Average True Range (ATR) Volatility band.
        """
        if len(df) < 30:
            return "HOLD", None

        # 1. Fast vs Slow Intraday Momentum
        df['EMA_Fast'] = df['Close'].ewm(span=9, adjust=False).mean()
        df['EMA_Slow'] = df['Close'].ewm(span=21, adjust=False).mean()

        # 2. ATR (Average True Range) - Measures absolute asset volatility
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df['ATR'] = true_range.rolling(14).mean()

        yesterday = df.iloc[-2]
        today = df.iloc[-1]
        
        current_price = today['Close']
        current_atr = today['ATR']

        # 3. Execution Signal Logic
        # BUY Signal: Bullish EMA cross
        if yesterday['EMA_Fast'] <= yesterday['EMA_Slow'] and today['EMA_Fast'] > today['EMA_Slow']:
            # Adaptive Profit Target: Entry + (2 * Volatility)
            profit_target = current_price + (2 * current_atr)
            return "BUY", profit_target
            
        # SELL Signal: Bearish EMA cross
        elif yesterday['EMA_Fast'] >= yesterday['EMA_Slow'] and today['EMA_Fast'] < today['EMA_Slow']:
            return "SELL", None
            
        return "HOLD", None

    def run_intraday_scan(self):
        """Fetches granular 5-minute bars and executes instant decisions."""
        print(f"\n⏱️ Scan Initiated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Guard clause: Check Alpaca's live clock API
        if not self.client.get_clock().is_open:
            print("🛑 Market is closed. Standing down.")
            return

        # Fetch active internal portfolio allocations
        positions = self.client.get_all_positions()
        portfolio = {pos.symbol: int(pos.qty) for pos in positions}
        
        # Batch download short-interval chunks for our target squad
        # Fetching 5 days of 5-minute intervals keeps the data frame fast and clean
        shared_data = yf.download(TICKER_SQUAD, period="5d", interval="5m", group_by='ticker', progress=False)

        for ticker in TICKER_SQUAD:
            try:
                ticker_df = shared_data[ticker].dropna()
                signal, target = self.calculate_adaptive_signals(ticker_df)
                
                is_holding = ticker in portfolio
                current_price = ticker_df['Close'].iloc[-1]

                if signal == "BUY" and not is_holding:
                    qty = int(TRADE_ALLOCATION // current_price)
                    if qty > 0:
                        print(f"🔥 [STRATEGY MATCH] Bullish momentum on {ticker}. Price: ${current_price:.2f}")
                        self.execute_order(ticker, qty, OrderSide.BUY)
                        
                elif signal == "SELL" and is_holding:
                    qty = portfolio[ticker]
                    print(f"❄️ [STRATEGY MATCH] Bearish exit triggered for {ticker}. Price: ${current_price:.2f}")
                    self.execute_order(ticker, qty, OrderSide.SELL)
                    
            except Exception as e:
                print(f"❌ Execution error on {ticker}: {e}")

    def execute_order(self, ticker, qty, side):
        """Dispatches lightning orders directly to Alpaca's matching engine."""
        try:
            order = MarketOrderRequest(
                symbol=ticker,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.DAY
            )
            self.client.submit_order(order)
            print(f"✅ Order Successfully Dispatched: {side.value.upper()} {qty} shares of {ticker}")
        except Exception as e:
            print(f"⚠️ Pre-Trade Check Rejected Order: {e}")

if __name__ == "__main__":
    bot = AlphaDayTrader()
    print("🚀 Intraday Adaptive Engine Loaded. Entering continuous loop mode...")
    
    # Continuous Intraday Loop Engine
    # Wakes up every 60 seconds to evaluate 5-minute trend updates
    while True:
        bot.run_intraday_scan()
        time.sleep(60)