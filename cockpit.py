import os
import pandas as pd
import yfinance as yf
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta

# Set up page configurations
st.set_page_config(page_title="Alpha Volatility Cockpit", layout="wide", page_icon="📊")

st.title("📊 Alpha Volatility Scalper: Trading Cockpit")
st.markdown("Use this visual utility to audit and review the entry and exit execution points captured by your live bot.")

TRADE_FILE = "trade_log.csv"

# Check if trade log exists
if not os.path.exists(TRADE_FILE) or os.stat(TRADE_FILE).st_size == 0:
    st.info("ℹ️ No trade data found yet. Your cockpit will automatically populate once `trade_log.csv` records its first closed positions on Monday!")
else:
    # Read the local trade history ledger
    df_trades = pd.read_csv(TRADE_FILE)
    
    # Filter to only show closed trades that have an entry and exit
    df_closed = df_trades[df_trades['Status'] == 'CLOSED'].copy()
    
    if df_closed.empty:
        st.warning("⚠️ Found a trade log, but there are no completed (CLOSED) trades to visualize yet.")
    else:
        # Metrics Sidebar
        st.sidebar.header("System Session Performance")
        total_pnl = df_closed['PnL'].sum()
        wins = (df_closed['PnL'] > 0).sum()
        losses = (df_closed['PnL'] <= 0).sum()
        win_rate = (wins / len(df_closed)) * 100 if len(df_closed) > 0 else 0
        
        st.sidebar.metric("Total Session PnL", f"${total_pnl:,.2f}", delta=f"{total_pnl:+.2f}")
        st.sidebar.metric("Win Rate", f"{win_rate:.1f}%", delta=f"{wins}W - {losses}L")
        
        # Select trade to analyze
        st.subheader("🔍 Audit Individual Executions")
        
        # Format a clean dropdown label
        df_closed['dropdown_label'] = df_closed.apply(
            lambda r: f"{r['Ticker']} | PnL: ${r['PnL']:+.2f} | {r['Entry_Time']}", axis=1
        )
        
        selected_label = st.selectbox("Select a completed trade to plot:", df_closed['dropdown_label'].tolist())
        selected_trade = df_closed[df_closed['dropdown_label'] == selected_label].iloc[0]
        
        # Parsing entry and exit timestamps (tz-naive by default)
        entry_dt = pd.to_datetime(selected_trade['Entry_Time'])
        exit_dt = pd.to_datetime(selected_trade['Exit_Time'])
        ticker = selected_trade['Ticker']
        
        # Buffer historical pull window to give context on chart
        start_buffer = entry_dt - timedelta(minutes=45)
        end_buffer = exit_dt + timedelta(minutes=45)
        
        st.info(f"⏳ Pulling historical 1-minute candlesticks for **{ticker}** on {entry_dt.strftime('%Y-%m-%d')}...")
        
        # Fetch matching 1-minute historical bars
        try:
            stock_data = yf.download(
                ticker, 
                start=start_buffer.strftime('%Y-%m-%d'),
                end=(end_buffer + timedelta(days=1)).strftime('%Y-%m-%d'),
                interval="1m",
                progress=False
            )
            
            if not stock_data.empty:
                # STRIP TIMEZONE INFO: Convert from tz-aware (America/New_York) to tz-naive
                if stock_data.index.tz is not None:
                    stock_data.index = stock_data.index.tz_localize(None)
                
                # Now we can safely compare naive timestamps without errors!
                stock_data = stock_data.loc[start_buffer:end_buffer]
        except Exception as e:
            st.error(f"Failed to fetch market data: {e}")
            stock_data = pd.DataFrame()

        if stock_data.empty:
            st.error("❌ Unable to load historical intervals for this specific window. Make sure yfinance has data for this day.")
        else:
            # Main chart construction
            fig = go.Figure()

            # 1. Base Candlestick Trace
            fig.add_trace(go.Candlestick(
                x=stock_data.index,
                open=stock_data['Open'],
                high=stock_data['High'],
                low=stock_data['Low'],
                close=stock_data['Close'],
                name=f"{ticker} 1m Price"
            ))

            # 2. Buy Point Trace Marker
            fig.add_trace(go.Scatter(
                x=[entry_dt],
                y=[selected_trade['Entry_Price']],
                mode="markers+text",
                marker=dict(symbol="triangle-up", color="#10B981", size=15),
                name="Buy Entry",
                text=[f"Buy Entry (${selected_trade['Entry_Price']:.2f})"],
                textposition="bottom center"
            ))

            # 3. Sell Point Trace Marker
            fig.add_trace(go.Scatter(
                x=[exit_dt],
                y=[selected_trade['Exit_Price']],
                mode="markers+text",
                marker=dict(symbol="triangle-down", color="#EF4444", size=15),
                name="Sell Exit",
                text=[f"Sell Exit (${selected_trade['Exit_Price']:.2f})"],
                textposition="top center"
            ))

            # Update layout aesthetics for a premium dark mode feel
            fig.update_layout(
                title=f"{ticker} Trade Audit Chart (Captured on {entry_dt.strftime('%m/%d/%Y')})",
                yaxis_title="Stock Price ($)",
                xaxis_title="Time",
                template="plotly_dark",
                height=650,
                xaxis_rangeslider_visible=False
            )

            # Updated parameter to avoid streamlit deprecation warnings
            st.plotly_chart(fig, use_container_width=True)
            
            # Display Trade Highlights Table
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Shares Traded", f"{selected_trade['Qty']} shares")
            with col2:
                holding_time = exit_dt - entry_dt
                st.metric("Holding Duration", f"{holding_time.seconds // 60}m {holding_time.seconds % 60}s")
            with col3:
                # Handle cases where older log logs do not have the 'Engine' column
                engine_val = selected_trade['Engine'] if 'Engine' in selected_trade and pd.notna(selected_trade['Engine']) else "Legacy (N/A)"
                st.metric("Trade Engine", str(engine_val))
            with col4:
                st.metric("Net Gain/Loss", f"${selected_trade['PnL']:+.2f}")