import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, time as datetime_time

# =====================================================================
# STANDARDIZED DUAL-ENGINE BACKTESTER (ANTI-OVERFITTING VERSION)
# =====================================================================

# Unified allocations. No custom RSI tracking floors allowed here.
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
STARTING_CASH = 100000.0  # Simulated Base Capital

def get_active_engine(timestamp) -> str:
    """Routes engine rules based on the historical timestamp's time."""
    current_time = timestamp.time()
    lull_start = datetime_time(11, 30)
    lull_end = datetime_time(13, 30)
    if lull_start <= current_time < lull_end:
        return "ENGINE_B"
    return "ENGINE_A"

def calculate_rsi_series(df, period=14):
    """Vectorized RSI calculation for historical dataframes."""
    change = df['Close'].diff()
    gain = change.clip(lower=0)
    loss = -change.clip(upper=0)
    
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    
    rs = avg_gain / np.where(avg_loss == 0, 0.00001, avg_loss)
    return 100 - (100 / (1 + rs))

def calculate_atr_series(df, period=14):
    """Vectorized ATR calculation for historical dataframes."""
    high = df['High']
    low = df['Low']
    close_prev = df['Close'].shift(1)
    
    tr = pd.concat([
        high - low, 
        (high - close_prev).abs(), 
        (low - close_prev).abs()
    ], axis=1).max(axis=1)
    
    return tr.rolling(window=period, min_periods=period).mean()

def run_backtest(ticker, df):
    """Simulates trading logic tick-by-tick using standardized systemic constants."""
    df = df.copy()
    df['RSI'] = calculate_rsi_series(df)
    df['ATR'] = calculate_atr_series(df)
    df = df.dropna()

    cash = STARTING_CASH
    position_qty = 0
    entry_price = 0.0
    trades = []

    for idx, row in df.iterrows():
        timestamp = idx
        current_price = row['Close']
        current_rsi = row['RSI']
        current_atr = row['ATR']
        
        market_close_imminent = timestamp.hour == 15 and timestamp.minute >= 45
        emergency_liquidation_zone = timestamp.hour == 15 and timestamp.minute >= 57
        
        active_engine = get_active_engine(timestamp)

        # -----------------------------------------------------------------
        # EXITS SEQUENCE (IF HOLDING ASSET)
        # -----------------------------------------------------------------
        if position_qty > 0:
            atr_multiplier = 1.5 if active_engine == "ENGINE_A" else 1.0
            target_tp = entry_price + (current_atr * atr_multiplier * 2.0)
            target_sl = entry_price - (current_atr * atr_multiplier)

            hit_tp = current_price >= target_tp
            hit_sl = current_price <= target_sl
            hit_overbought = current_rsi >= 72
            
            if hit_tp or hit_sl or hit_overbought or emergency_liquidation_zone:
                pnl = round((current_price - entry_price) * position_qty, 2)
                cash += (position_qty * current_price)
                
                reason = "TP" if hit_tp else ("SL" if hit_sl else ("RSI_EXIT" if hit_overbought else "E-STOP"))
                trades.append({
                    "Ticker": ticker, "Type": "SELL", "Qty": position_qty, 
                    "Price": round(current_price, 2), "Time": timestamp, 
                    "PnL": pnl, "Reason": reason, "Engine": active_engine
                })
                position_qty = 0
                entry_price = 0.0
            continue

        # -----------------------------------------------------------------
        # ENTRIES SEQUENCE (STANDARDIZED EDGE)
        # -----------------------------------------------------------------
        if position_qty == 0 and not market_close_imminent:
            # Strict un-tweaked systemic rules
            rsi_floor = 27.0
            if active_engine == "ENGINE_B":
                rsi_floor -= 3.0  # Sharp Midday Sniper Compression (24.0)

            if current_rsi <= rsi_floor:
                config = TICKER_CONFIGS[ticker]
                allocated_cash = cash * config["max_share_allocation"]
                qty = int(allocated_cash // current_price)

                if qty > 0:
                    position_qty = qty
                    entry_price = current_price
                    cash -= (position_qty * current_price)
                    trades.append({
                        "Ticker": ticker, "Type": "BUY", "Qty": qty, 
                        "Price": round(current_price, 2), "Time": timestamp, 
                        "PnL": 0.0, "Reason": "RSI_ENTRY", "Engine": active_engine
                    })

    # Clear out remnants at the absolute tail of data series arrays
    if position_qty > 0:
        final_price = df['Close'].iloc[-1]
        pnl = round((final_price - entry_price) * position_qty, 2)
        trades.append({
            "Ticker": ticker, "Type": "SELL", "Qty": position_qty, 
            "Price": round(final_price, 2), "Time": df.index[-1], 
            "PnL": pnl, "Reason": "FORCE_END", "Engine": "SYSTEM"
        })

    return pd.DataFrame(trades)

# =====================================================================
# LIVE EXECUTOR LOOP
# =====================================================================
if __name__ == "__main__":
    print("⏳ Downloading past 5 days of 1-minute interval market structures...")
    data = yf.download(TICKER_SQUAD, period="5d", interval="1m", group_by='ticker', progress=False)
    
    all_trade_ledgers = []

    print("\n🚀 Beginning Standardized Vectorized Runs (No Curve-Fitting)...")
    print("-" * 75)
    
    for ticker in TICKER_SQUAD:
        ticker_df = data[ticker].dropna()
        if ticker_df.empty: 
            continue
            
        trade_log = run_backtest(ticker, ticker_df)
        if not trade_log.empty:
            all_trade_ledgers.append(trade_log)
            
        sells = trade_log[trade_log['Type'] == "SELL"]
        ticker_net = sells['PnL'].sum()
        total_wins = (sells['PnL'] > 0).sum()
        total_losses = (sells['PnL'] <= 0).sum()
        win_rate = (total_wins / len(sells) * 100) if len(sells) > 0 else 0.0
        
        print(f"📈 {ticker:<5} Net PnL: ${ticker_net:>7.2f} | Record: {total_wins}W-{total_losses}L | Win Rate: {win_rate:.1f}%")

    print("-" * 75)
    if all_trade_ledgers:
        master_ledger = pd.concat(all_trade_ledgers)
        master_sells = master_ledger[master_ledger['Type'] == "SELL"]
        grand_pnl = master_sells['PnL'].sum()
        
        print(f"🏆 BACKTEST COMPLETE. COMBINED OVERALL STRATEGY PnL: ${grand_pnl:.2f}")
        print(f"📊 Total Completed System Trades: {len(master_sells)}")
        
        engine_a_pnl = master_sells[master_sells['Engine'] == "ENGINE_A"]['PnL'].sum()
        engine_b_pnl = master_sells[master_sells['Engine'] == "ENGINE_B"]['PnL'].sum()
        print(f"   ↳ Engine A (Momentum) Performance: ${engine_a_pnl:.2f}")
        print(f"   ↳ Engine B (Midday Lull) Performance: ${engine_b_pnl:.2f}")
    else:
        print("❌ No trades executed. The system baseline parameters are heavily restrictive.")