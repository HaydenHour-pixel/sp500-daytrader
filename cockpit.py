import os
import pandas as pd
import yfinance as yf
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta, time as datetime_time

# Set up page configurations
st.set_page_config(page_title="Alpha Volatility Cockpit", layout="wide", page_icon="📊")

st.title("📊 Alpha Volatility Scalper: Trading Cockpit")
st.markdown("Use this visual utility to audit and review the entry and exit execution points captured by your live bot.")

TRADE_FILE = "trade_log.csv"
SUMMARY_FILE = "daily_summary.csv"

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
        # Sort by exit time to build chronological sequence
        df_closed['Exit_Time'] = pd.to_datetime(df_closed['Exit_Time'])
        df_closed = df_closed.sort_values(by='Exit_Time').reset_index(drop=True)
        
        # Metrics Sidebar
        st.sidebar.header("System Session Performance")
        total_pnl = df_closed['PnL'].sum()
        wins = (df_closed['PnL'] > 0).sum()
        losses = (df_closed['PnL'] <= 0).sum()
        win_rate = (wins / len(df_closed)) * 100 if len(df_closed) > 0 else 0
        
        st.sidebar.metric("Total Session PnL", f"${total_pnl:,.2f}", delta=f"{total_pnl:+.2f}")
        st.sidebar.metric("Win Rate", f"{win_rate:.1f}%", delta=f"{wins}W - {losses}L")
        
        # Mode Selection including our Macro Equity Curve View
        view_mode = st.sidebar.radio(
            "Select Analysis Perspective:",
            ["Single Trade Audit", "All-in-One Asset View", "Macro Equity Curve"]
        )
        
        if view_mode == "Single Trade Audit":
            st.subheader("🔍 Audit Individual Executions")
            st.markdown("Inspect trade execution timelines matched against live minute candles.")
            
            # Form-based filters for fine-tuned view controls
            col_sel1, col_sel2, col_sel3 = st.columns([2, 1, 1])
            with col_sel1:
                # Format a clean dropdown label
                df_closed['dropdown_label'] = df_closed.apply(
                    lambda r: f"{r['Ticker']} | PnL: ${r['PnL']:+.2f} | {r['Entry_Time']}", axis=1
                )
                selected_label = st.selectbox("Select a completed trade to plot:", df_closed['dropdown_label'].tolist())
            with col_sel2:
                buffer_choice = st.selectbox(
                    "Visual Zoom Level:",
                    ["Tight Zoom (15m context)", "Standard Zoom (45m context)", "Wide Zoom (2h context)", "Show Full Day (Market Hours)"],
                    index=1
                )
            with col_sel3:
                chart_style = st.selectbox(
                    "Chart Representation:",
                    ["Buy/Sell Arrows Only", "Stock Graph Only", "Both (Stock Graph + Arrows)"],
                    index=2  # Default to Both (Stock Graph + Arrows)
                )
                
            selected_trade = df_closed[df_closed['dropdown_label'] == selected_label].iloc[0]
            
            # Parsing entry and exit timestamps
            entry_dt = pd.to_datetime(selected_trade['Entry_Time'])
            exit_dt = selected_trade['Exit_Time']
            ticker = selected_trade['Ticker']
            
            # Translate the context selection into standard datetimes
            if buffer_choice == "Tight Zoom (15m context)":
                start_buffer = entry_dt - timedelta(minutes=15)
                end_buffer = exit_dt + timedelta(minutes=15)
            elif buffer_choice == "Standard Zoom (45m context)":
                start_buffer = entry_dt - timedelta(minutes=45)
                end_buffer = exit_dt + timedelta(minutes=45)
            elif buffer_choice == "Wide Zoom (2h context)":
                start_buffer = entry_dt - timedelta(minutes=120)
                end_buffer = exit_dt + timedelta(minutes=120)
            else:
                # Set bounds to standard market hours (09:30 - 16:00 EST) for the day of the trade
                start_buffer = datetime.combine(entry_dt.date(), datetime_time(9, 30))
                end_buffer = datetime.combine(entry_dt.date(), datetime_time(16, 0))
            
            st.info(f"⏳ Pulling historical 1-minute candlesticks for **{ticker}** on {entry_dt.strftime('%Y-%m-%d')}...")
            
            try:
                stock_data = yf.download(
                    ticker, 
                    start=start_buffer.strftime('%Y-%m-%d'),
                    end=(end_buffer + timedelta(days=1)).strftime('%Y-%m-%d'),
                    interval="1m",
                    progress=False
                )
                if not stock_data.empty:
                    # COLLAPSE MULTIINDEX COLUMNS: Safely flattens ('Close', 'TSLA') -> 'Close'
                    if isinstance(stock_data.columns, pd.MultiIndex):
                        stock_data.columns = stock_data.columns.droplevel(1)
                        
                    if stock_data.index.tz is not None:
                        stock_data.index = stock_data.index.tz_localize(None)
                    
                    # Restrict data to calculated boundaries
                    stock_data = stock_data.loc[start_buffer:end_buffer]
            except Exception as e:
                st.error(f"Failed to fetch market data: {e}")
                stock_data = pd.DataFrame()

            if stock_data.empty:
                st.error("❌ Unable to load historical intervals for this specific window. Ensure market hours are correct.")
            else:
                fig = go.Figure()
                
                # 1. Base Price Line Trace (if Stock Graph is enabled)
                if chart_style in ["Stock Graph Only", "Both (Stock Graph + Arrows)"]:
                    fig.add_trace(go.Scatter(
                        x=stock_data.index, y=stock_data['Close'], mode="lines",
                        line=dict(color="#3B82F6", width=2), name=f"{ticker} Close Price"
                    ))

                # 2. Buy/Sell Arrows (if Arrows are enabled)
                if chart_style in ["Buy/Sell Arrows Only", "Both (Stock Graph + Arrows)"]:
                    # Buy Point Trace Marker
                    fig.add_trace(go.Scatter(
                        x=[entry_dt], y=[selected_trade['Entry_Price']], mode="markers+text",
                        marker=dict(symbol="triangle-up", color="#10B981", size=15, line=dict(color="white", width=1)),
                        name="Buy Entry", text=[f"Buy Entry (${selected_trade['Entry_Price']:.2f})"], textposition="bottom center"
                    ))
                    
                    # Sell Point Trace Marker
                    fig.add_trace(go.Scatter(
                        x=[exit_dt], y=[selected_trade['Exit_Price']], mode="markers+text",
                        marker=dict(symbol="triangle-down", color="#EF4444", size=15, line=dict(color="white", width=1)),
                        name="Sell Exit", text=[f"Sell Exit (${selected_trade['Exit_Price']:.2f})"], textposition="top center"
                    ))
                
                fig.update_layout(
                    title=f"{ticker} Trade Audit Chart", yaxis_title="Stock Price ($)",
                    template="plotly_dark", height=650, xaxis_rangeslider_visible=False
                )
                st.plotly_chart(fig, use_container_width=True)
                
                col1, col2, col3, col4 = st.columns(4)
                with col1: st.metric("Shares Traded", f"{selected_trade['Qty']} shares")
                with col2:
                    holding_time = exit_dt - entry_dt
                    st.metric("Holding Duration", f"{holding_time.seconds // 60}m {holding_time.seconds % 60}s")
                with col3:
                    engine_val = selected_trade['Engine'] if 'Engine' in selected_trade and pd.notna(selected_trade['Engine']) else "Legacy (N/A)"
                    st.metric("Trade Engine", str(engine_val))
                with col4: st.metric("Net Gain/Loss", f"${selected_trade['PnL']:+.2f}")

        elif view_mode == "All-in-One Asset View":
            st.subheader("📈 All-in-One Asset View")
            st.markdown("Track continuous performance and asset execution vectors over a customizable historical horizon.")
            
            # Interactive horizon selectors
            col_sel1, col_sel2, col_sel3 = st.columns([2, 1, 1])
            with col_sel1:
                unique_tickers = sorted(df_closed['Ticker'].unique())
                selected_ticker = st.selectbox("Select a Stock to Analyze:", unique_tickers)
            with col_sel2:
                period_choice = st.selectbox(
                    "Historical Chart Horizon:",
                    ["1 Day (1m intervals)", "5 Days (5m intervals)", "1 Month (15m intervals)", "3 Months (1h intervals)", "6 Months (Daily intervals)"],
                    index=1  # Default to 5 Days
                )
            with col_sel3:
                all_chart_style = st.selectbox(
                    "Chart Representation:",
                    ["Buy/Sell Arrows Only", "Stock Graph Only", "Both (Stock Graph + Arrows)"],
                    index=2,  # Default to Both (Stock Graph + Arrows)
                    key="all_in_one_chart_style"
                )
            
            ticker_trades = df_closed[df_closed['Ticker'] == selected_ticker].copy()
            
            # Map time translation config variables
            if period_choice == "1 Day (1m intervals)":
                yf_period, yf_interval = "1d", "1m"
            elif period_choice == "5 Days (5m intervals)":
                yf_period, yf_interval = "5d", "5m"
            elif period_choice == "1 Month (15m intervals)":
                yf_period, yf_interval = "1mo", "15m"
            elif period_choice == "3 Months (1h intervals)":
                yf_period, yf_interval = "3mo", "60m"
            else:
                yf_period, yf_interval = "6mo", "1d"
            
            # Performance statistics
            ticker_pnl = ticker_trades['PnL'].sum()
            ticker_wins = (ticker_trades['PnL'] > 0).sum()
            ticker_losses = (ticker_trades['PnL'] <= 0).sum()
            ticker_win_rate = (ticker_wins / len(ticker_trades)) * 100 if len(ticker_trades) > 0 else 0
            
            stat_col1, stat_col2, stat_col3 = st.columns(3)
            with stat_col1: st.metric(f"Total {selected_ticker} PnL", f"${ticker_pnl:,.2f}", delta=f"{ticker_pnl:+.2f}")
            with stat_col2: st.metric(f"Completed Trades", f"{len(ticker_trades)}")
            with stat_col3: st.metric(f"Win Rate", f"{ticker_win_rate:.1f}%", delta=f"{ticker_wins}W - {ticker_losses}L")
                
            st.info(f"⏳ Pulling continuous historical {yf_period} market candles for **{selected_ticker}**...")
            
            try:
                stock_data = yf.download(selected_ticker, period=yf_period, interval=yf_interval, progress=False)
                if not stock_data.empty:
                    # COLLAPSE MULTIINDEX COLUMNS: Safely flattens ('Close', 'TSLA') -> 'Close'
                    if isinstance(stock_data.columns, pd.MultiIndex):
                        stock_data.columns = stock_data.columns.droplevel(1)
                        
                    if stock_data.index.tz is not None:
                        stock_data.index = stock_data.index.tz_localize(None)
            except Exception as e:
                st.error(f"Failed to fetch market data: {e}")
                stock_data = pd.DataFrame()

            if stock_data.empty:
                st.error(f"❌ Unable to load historical market structure for {selected_ticker}.")
            else:
                fig = go.Figure()
                
                # 1. Base Price Line Trace (if Stock Graph is enabled)
                if all_chart_style in ["Stock Graph Only", "Both (Stock Graph + Arrows)"]:
                    fig.add_trace(go.Scatter(
                        x=stock_data.index, y=stock_data['Close'], mode="lines",
                        line=dict(color="#3B82F6", width=2), name="Close Price Line", opacity=0.8
                    ))

                # 2. Buy/Sell Arrows and Connection Vectors (if Arrows are enabled)
                if all_chart_style in ["Buy/Sell Arrows Only", "Both (Stock Graph + Arrows)"]:
                    buy_x, buy_y, buy_text = [], [], []
                    sell_x, sell_y, sell_text = [], [], []

                    # Find earliest date of downloaded stock data to filter trade mapping index
                    min_market_date = stock_data.index.min()

                    for i, trade in ticker_trades.iterrows():
                        t_entry = pd.to_datetime(trade['Entry_Time'])
                        t_exit = pd.to_datetime(trade['Exit_Time'])
                        
                        # Only map trade lines if they fall within the selected zoom timeframe
                        if t_entry < min_market_date:
                            continue
                            
                        trade_id = trade['Trade_ID'] if 'Trade_ID' in trade else f"Legacy_{i}"
                        p_entry, p_exit, pnl = float(trade['Entry_Price']), float(trade['Exit_Price']), float(trade['PnL'])
                        
                        buy_x.append(t_entry)
                        buy_y.append(p_entry)
                        buy_text.append(f"Buy #{trade_id} @ ${p_entry:.2f}")

                        sell_x.append(t_exit)
                        sell_y.append(p_exit)
                        sell_text.append(f"Sell #{trade_id} @ ${p_exit:.2f}<br>PnL: ${pnl:+.2f}")

                        fig.add_trace(go.Scatter(
                            x=[t_entry, t_exit], y=[p_entry, p_exit], mode="lines",
                            line=dict(color="#10B981" if pnl > 0 else "#EF4444", width=2, dash="dash"),
                            hoverinfo="text", hovertext=f"Trade {trade_id}<br>PnL: ${pnl:+.2f}", showlegend=False
                        ))

                    if buy_x:
                        fig.add_trace(go.Scatter(x=buy_x, y=buy_y, mode="markers", marker=dict(symbol="triangle-up", color="#10B981", size=12, line=dict(color="white", width=1)), name="Buy Entries", hoverinfo="text", hovertext=buy_text))
                        fig.add_trace(go.Scatter(x=sell_x, y=sell_y, mode="markers", marker=dict(symbol="triangle-down", color="#EF4444", size=12, line=dict(color="white", width=1)), name="Sell Exits", hoverinfo="text", hovertext=sell_text))
                
                fig.update_layout(title=f"Continuous Visual for {selected_ticker}", yaxis_title="Stock Price ($)", template="plotly_dark", height=700, xaxis_rangeslider_visible=True)
                st.plotly_chart(fig, use_container_width=True)

        elif view_mode == "Macro Equity Curve":
            st.subheader("📉 Strategy Account Equity Curve")
            st.markdown("Monitor the cumulative capital performance of your deployment over time.")
            
            # Compute a continuous cumulative sum of PnL from closed trades
            df_closed['Cumulative_PnL'] = df_closed['PnL'].cumsum()
            
            # Construct Equity Curve Line Plot
            fig = go.Figure()
            
            # Fill under the line color dynamically (Green if overall winning, Red if overall losing)
            fill_color = "rgba(16, 185, 129, 0.15)" if total_pnl >= 0 else "rgba(239, 68, 68, 0.15)"
            line_color = "#10B981" if total_pnl >= 0 else "#EF4444"
            
            fig.add_trace(go.Scatter(
                x=df_closed['Exit_Time'],
                y=df_closed['Cumulative_PnL'],
                mode='lines+markers',
                name='Cumulative Performance',
                line=dict(color=line_color, width=3),
                fill='tozeroy',
                fillcolor=fill_color,
                hovertemplate="<b>Time:</b> %{x}<br><b>Net Profit:</b> $%{y:,.2f}<extra></extra>"
            ))
            
            # Reference benchmark line at $0.00 profit
            fig.add_shape(
                type="line", x0=df_closed['Exit_Time'].min(), x1=df_closed['Exit_Time'].max(),
                y0=0, y1=0, line=dict(color="rgba(255,255,255,0.3)", width=1, dash="dot")
            )
            
            fig.update_layout(
                title="Account Capital Growth Curve (Net Cumulative Return)",
                yaxis_title="Total Profits / Losses ($)",
                xaxis_title="Execution Timeline",
                template="plotly_dark",
                height=600
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Additional Analytical Insight Box
            st.markdown("### 📊 Portfolio Metrics Dashboard")
            m_col1, m_col2, m_col3 = st.columns(3)
            with m_col1:
                largest_win = df_closed['PnL'].max()
                st.metric("Best Single Trade", f"${largest_win:,.2f}")
            with m_col2:
                largest_loss = df_closed['PnL'].min()
                st.metric("Worst Single Trade", f"${largest_loss:,.2f}")
            with m_col3:
                avg_trade = df_closed['PnL'].mean()
                st.metric("Expectancy (Avg/Trade)", f"${avg_trade:+.2f}")