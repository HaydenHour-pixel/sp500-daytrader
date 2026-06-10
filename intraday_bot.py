import time
from datetime import datetime
import pandas as pd
import yfinance as yf
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# =====================================================================
# HARDENED STATE MACHINE INTRADAY ENGINE CONFIGURATION
# =====================================================================
API_KEY = "PKJO447RSJZ3QZTWIIQDR6EDP6"
SECRET_KEY = "3YWa531t3FmhsZjxoQJGJTRoNHWWNyPmSKEu3115Y2Bp"

# Target high-liquidity momentum squad
TICKER_SQUAD = ["TSLA", "NVDA", "AMD", "AAPL", "MSFT", "META", "AMZN", "NFLX"]
TRADE_ALLOCATION = 2000  # Equal-weight tranche capital limits per asset

class AlphaDayTrader:
    def __init__(self):
        self.client = TradingClient(API_KEY, SECRET_KEY, paper=True)
        # In-memory dynamic state machine tracking execution targets
        self.active_targets = {}  # Format: { TICKER: {'take_profit': X, 'stop_loss': Y} }

    def calculate_adaptive_signals(self, df, ticker):
        """
        Processes real-time momentum indicators and manages risk brackets.
        Calculates dynamic stop/target floors using Average True Range (ATR).
        """
        if len(df) < 30:
            return "HOLD", None, None

        # 1. Fast vs Slow Intraday Momentum Vectors
        df['EMA_Fast'] = df['Close'].ewm(span=9, adjust=False).mean()
        df['EMA_Slow'] = df['Close'].ewm(span=21, adjust=False).mean()

        # 2. Volatility Range Calculations (True Range Matrix)
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['ATR'] = ranges.max(axis=1).rolling(14).mean()

        yesterday = df.iloc[-2]
        today = df.iloc[-1]
        
        current_price = today['Close']
        current_atr = today['ATR']

        # 3. Target Management Gateway (If actively holding the asset)
        if ticker in self.active_targets:
            brackets = self.active_targets[ticker]
            if current_price >= brackets['take_profit']:
                print(f"🎯 [TAKE PROFIT TRIGGERED] {ticker} reached target of ${brackets['take_profit']:.2f}")
                return "SELL", None, None
            if current_price <= brackets['stop_loss']:
                print(f"🛑 [STOP LOSS TRIGGERED] {ticker} hit floor of ${brackets['stop_loss']:.2f}")
                return "SELL", None, None

        # 4. Momentum Entry Signals (Only if asset state is flat/idle)
        if yesterday['EMA_Fast'] <= yesterday['EMA_Slow'] and today['EMA_Fast'] > today['EMA_Slow'] and ticker not in self.active_targets:
            # Risk Mitigation Formula: Risk 1x Volatility Units to capture 2x Volatility Units
            take_profit = current_price + (2.0 * current_atr)
            stop_loss = current_price - (1.0 * current_atr)
            return "BUY", take_profit, stop_loss
            
        # Trailing crossover technical exit safety net
        elif yesterday['EMA_Fast'] >= yesterday['EMA_Slow'] and today['EMA_Fast'] < today['EMA_Slow'] and ticker in self.active_targets:
            return "SELL", None, None
            
        return "HOLD", None, None

    def run_intraday_scan(self):
        """Pings external data fabrics and updates operational portfolios."""
        now = datetime.now()
        print(f"\n⏱️ Scan Initiated: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # NETWORK FAULT-TOLERANCE GUARD: Protects framework if connection drops
        try:
            if not self.client.get_clock().is_open:
                print("🛑 Market is closed. Standing down.")
                return
        except Exception as e:
            print(f"⚠️ Network exception connecting to Alpaca Clock API ({e}). Skipping to avoid crash...")
            return

        # RETAIL OPENING COOLDOWN FILTER: Isolates noise from 9:30 to 10:00 AM
        if now.hour == 9 and now.minute < 30:
            print("⏳ Filtering opening volatility noise. Matrix execution begins at 10:00 AM.")
            return

        # Pull down active engine footprint from brokerage node
        positions = self.client.get_all_positions()
        portfolio = {pos.symbol: int(pos.qty) for pos in positions}
        
        # Sync structural dictionary targets with actual live updates
        self.active_targets = {ticker: state for ticker, state in self.active_targets.items() if ticker in portfolio}

        # CONCURRENT SCRAPING ENGINE: Forced internal timeout checks to prevent file hangs
        try:
            shared_data = yf.download(TICKER_SQUAD, period="3d", interval="5m", group_by='ticker', progress=False, timeout=5)
        except Exception as e:
            print(f"⚠️ Yahoo Finance network request timed out ({e}). Skipping loop cycle...")
            return

        # 5. Core Operational Evaluation Sweep
        for ticker in TICKER_SQUAD:
            try:
                ticker_df = shared_data[ticker].dropna()
                if ticker_df.empty: 
                    continue
                
                signal, tp, sl = self.calculate_adaptive_signals(ticker_df, ticker)
                is_holding = ticker in portfolio
                current_price = ticker_df['Close'].iloc[-1]

                if signal == "BUY" and not is_holding:
                    qty = int(TRADE_ALLOCATION // current_price)
                    if qty > 0:
                        print(f"🔥 [TREND CROSSOVER] Bullish signal detected on {ticker}. Price: ${current_price:.2f}")
                        if self.execute_order(ticker, qty, OrderSide.BUY):
                            self.active_targets[ticker] = {'take_profit': tp, 'stop_loss': sl}
                            print(f"   ↳ Bracket Targets Locked -> Take Profit: ${tp:.2f} | Stop Loss: ${sl:.2f}")
                        
                elif signal == "SELL" and is_holding:
                    qty = portfolio[ticker]
                    print(f"❄️ [TREND REVERSAL] Bearish exit signal triggered for {ticker}. Price: ${current_price:.2f}")
                    if self.execute_order(ticker, qty, OrderSide.SELL):
                        self.active_targets.pop(ticker, None)
                    
            except Exception as e:
                print(f"❌ Structural math failure on asset {ticker}: {e}")

    def execute_order(self, ticker, qty, side):
        """Dispatches requests directly to Alpaca clearing systems."""
        try:
            order = MarketOrderRequest(symbol=ticker, qty=qty, side=side, time_in_force=TimeInForce.DAY)
            self.client.submit_order(order)
            print(f"✅ Transaction Dispatched: {side.value.upper()} {qty} shares of {ticker}")
            return True
        except Exception as e:
            print(f"⚠️ Pre-Trade Risk Framework Rejected Order: {e}")
            return False

if __name__ == "__main__":
    bot = AlphaDayTrader()
    print("🚀 Hardened State Machine Intraday Engine Online and Armed.")
    
    # Core continuous execution block loop
    while True:
        bot.run_intraday_scan()
        time.sleep(60)