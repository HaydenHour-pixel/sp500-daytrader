import yfinance as yf

# --- 1. PRE-MARKET VOLATILITY SCANNER ---
def get_high_volatility_tickers(ticker_list, window=5):
    """Scans tickers to find those with the highest ATR (Average True Range)."""
    volatility_scores = {}
    for ticker in ticker_list:
        try:
            data = yf.download(ticker, period="1mo", interval="1d", progress=False)
            if not data.empty:
                # Calculate volatility as % change range
                vol = ((data['High'] - data['Low']) / data['Close']).mean()
                volatility_scores[ticker] = vol
        except:
            continue
    # Return top 5 most volatile tickers
    sorted_tickers = sorted(volatility_scores, key=volatility_scores.get, reverse=True)
    return sorted_tickers[:5]

# --- 2. TRAILING STOP LOGIC ---
def calculate_trailing_stop(current_price, entry_price, trailing_percent=0.005):
    """
    Returns the dynamic trailing stop level.
    If price moves up 1%, the stop moves up by 0.5% of current price.
    """
    # Simple trailing logic: stop stays at entry until profit, then moves up
    if current_price > entry_price:
        return current_price * (1 - trailing_percent)
    return entry_price * 0.99  # Static 1% stop if not in profit yet

def should_exit_trade(current_price, trailing_stop_level):
    if current_price <= trailing_stop_level:
        return True
    return False