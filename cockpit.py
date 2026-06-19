import os
import json
import pandas as pd
import yfinance as yf
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta, time as datetime_time
from alpaca.trading.client import TradingClient
from dotenv import load_dotenv

load_dotenv()

# Set up page configurations
st.set_page_config(page_title="Alpha Volatility Cockpit", layout="wide", page_icon="📊")

st.title("📊 Alpha Volatility Scalper: Trading Cockpit")
st.markdown("Use this visual utility to audit and review the entry and exit execution points captured by your live bot.")

TRADE_FILE = "trade_log.csv"
SUMMARY_FILE = "daily_summary.csv"
STATUS_FILE = "bot_status.json"
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")


@st.cache_resource
def get_alpaca_client():
    return TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

# =====================================================================
# BOT STATUS HEARTBEAT BANNER
# =====================================================================
if os.path.exists(STATUS_FILE):
    try:
        with open(STATUS_FILE, "r") as f:
            bot_status = json.load(f)

        last_scan = datetime.fromisoformat(bot_status["last_scan"])
        seconds_since_scan = (datetime.now() - last_scan).total_seconds()
        is_live = seconds_since_scan < 90

        status_col1, status_col2, status_col3, status_col4, status_col5 = st.columns(5)
        with status_col1:
            st.markdown("🟢 **Bot Live**" if is_live else "🔴 **Bot Offline / Stale**")
        with status_col2:
            st.markdown(f"**Engine:** {bot_status.get('active_engine', 'N/A')}")
        with status_col3:
            st.markdown(f"**Session:** {bot_status.get('daily_wins', 0)}W-{bot_status.get('daily_losses', 0)}L")
        with status_col4:
            st.markdown(f"**Open Positions:** {bot_status.get('open_position_count', 0)}")
        with status_col5:
            st.markdown(f"**Last Scan:** {last_scan.strftime('%H:%M:%S')}")
    except Exception as e:
        st.warning(f"⚠️ Could not parse bot status heartbeat: {e}")
else:
    st.markdown("⚪ No heartbeat yet — bot hasn't run")

# =====================================================================
# LIVE SESSION MONITOR (reads directly from Alpaca, not trade_log.csv)
# =====================================================================
def _render_live_positions():
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        st.error("🔑 Missing Alpaca credentials. Add ALPACA_API_KEY and ALPACA_SECRET_KEY to your .env file to use the Live Session Monitor.")
        return

    client = get_alpaca_client()

    try:
        positions = client.get_all_positions()
    except Exception as e:
        st.error(f"⚠️ Could not fetch positions from Alpaca: {e}")
        return

    if not positions:
        st.info("✅ No open positions right now.")
        return

    rows = []
    total_unrealized_pl = 0.0
    for pos in positions:
        unrealized_pl = float(pos.unrealized_pl)
        total_unrealized_pl += unrealized_pl
        rows.append({
            "Symbol": pos.symbol,
            "Qty": int(pos.qty),
            "Avg Entry Price": float(pos.avg_entry_price),
            "Current Price": float(pos.current_price),
            "Unrealized PnL": unrealized_pl,
            "Unrealized PnL %": float(pos.unrealized_plpc) * 100,
            "Market Value": float(pos.market_value)
        })
    positions_df = pd.DataFrame(rows)

    metric_col1, metric_col2 = st.columns(2)
    with metric_col1:
        st.metric("Total Unrealized PnL", f"${total_unrealized_pl:,.2f}")
    with metric_col2:
        st.metric("Open Positions", len(positions))

    styled = positions_df.style.map(
        lambda v: f"color: {'#10B981' if v >= 0 else '#EF4444'}",
        subset=["Unrealized PnL"]
    ).format({
        "Avg Entry Price": "${:,.2f}",
        "Current Price": "${:,.2f}",
        "Unrealized PnL": "${:,.2f}",
        "Unrealized PnL %": "{:+.2f}%",
        "Market Value": "${:,.2f}"
    })

    st.dataframe(styled, hide_index=True, use_container_width=True)


if hasattr(st, "fragment"):
    @st.fragment(run_every="30s")
    def render_live_session_monitor():
        st.caption(f"Auto-refreshing every 30s · Last refresh: {datetime.now().strftime('%H:%M:%S')}")
        _render_live_positions()
else:
    def render_live_session_monitor():
        refresh_container = st.empty()
        if st.button("🔄 Refresh"):
            pass  # button press alone triggers a rerun of this script
        with refresh_container.container():
            st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')} (manual refresh — st.fragment unavailable)")
            _render_live_positions()

# =====================================================================
# INITIALIZE PERSISTENT STATE VARS (Unlinked to Widget Keys to Prevent Streamlit Deletion)
# =====================================================================
if "stored_single_selected_label" not in st.session_state:
    st.session_state.stored_single_selected_label = None
if "stored_single_buffer_choice" not in st.session_state:
    st.session_state.stored_single_buffer_choice = "Standard Zoom (45m context)"
if "stored_single_chart_style" not in st.session_state:
    st.session_state.stored_single_chart_style = "Buy/Sell Arrows Only"

if "stored_all_selected_ticker" not in st.session_state:
    st.session_state.stored_all_selected_ticker = None
if "stored_all_period_choice" not in st.session_state:
    st.session_state.stored_all_period_choice = "5 Days (5m intervals)"
if "stored_all_chart_style" not in st.session_state:
    st.session_state.stored_all_chart_style = "Buy/Sell Arrows Only"

# Persistent toggle state for the Ticker Leaderboard Expander
if "stored_leaderboard_expanded" not in st.session_state:
    st.session_state.stored_leaderboard_expanded = True

# Mode Selection including our Macro Equity Curve View and Live Session Monitor
# Defined up-front so "Live Session Monitor" is reachable even when trade_log.csv is empty/missing
view_mode = st.sidebar.radio(
    "Select Analysis Perspective:",
    ["Single Trade Audit", "All-in-One Asset View", "Macro Equity Curve", "Live Session Monitor"]
)

if view_mode == "Live Session Monitor":
    st.subheader("📡 Live Session Monitor")
    st.markdown("Real-time positions pulled directly from your Alpaca paper account.")
    render_live_session_monitor()
# Check if trade log exists
elif not os.path.exists(TRADE_FILE) or os.stat(TRADE_FILE).st_size == 0:
    st.info("ℹ️ No trade data found yet. Your cockpit will automatically populate once `trade_log.csv` records its first closed positions on Monday!")
else:
    # Read the local trade history ledger
    # Read and sanitize immediately
    df_raw = pd.read_csv(TRADE_FILE)
    
    # Force conversion with coerce to turn parsing errors into NaT/NaN
    df_raw['Entry_Time'] = pd.to_datetime(df_raw['Entry_Time'], errors='coerce')
    df_raw['Exit_Time'] = pd.to_datetime(df_raw['Exit_Time'], errors='coerce')
    df_raw['PnL'] = pd.to_numeric(df_raw['PnL'], errors='coerce')
    
    # Only drop rows that are missing the critical identifiers (Trade_ID and Ticker)
    # We keep Entry_Time and Exit_Time as they are, even if one is empty
    df_clean = df_raw.dropna(subset=['Trade_ID', 'Ticker'])
    
    # Add this helper function before your groupby block
    def get_final_status(series):
        # If any leg is marked CLOSED, the whole trade is considered CLOSED
        if 'CLOSED' in series.values:
            return 'CLOSED'
        return series.iloc[0]

    # Now update your aggregation to use this function
    trade_summary = df_clean.groupby('Trade_ID').agg({
        'PnL': 'sum',
        'Ticker': 'first',
        'Status': get_final_status, # Use the helper function here
        'Entry_Time': 'first',
        'Exit_Time': 'max',
        'Qty': 'sum',
        'Entry_Price': 'mean',
        'Exit_Price': 'mean',
        'Engine': 'first'
    }).reset_index()
    

    # Filter 'trade_summary' (the collapsed version), NOT 'df_clean' (the raw version)
    df_closed = trade_summary[trade_summary['Status'] == 'CLOSED'].copy()
    
    if df_closed.empty:
        st.warning("⚠️ No valid, completed (CLOSED) trades to visualize.")
    else:
        # Sort and proceed...
        df_closed = df_closed.sort_values(by='Exit_Time').reset_index(drop=True)
        
        # Metrics Sidebar
        st.sidebar.header("System Session Performance")
        total_pnl = df_closed['PnL'].sum()
        wins = (df_closed['PnL'] > 0).sum()
        losses = (df_closed['PnL'] <= 0).sum()
        win_rate = (wins / len(df_closed)) * 100 if len(df_closed) > 0 else 0
        
        st.sidebar.metric("Total Session PnL", f"${total_pnl:,.2f}", delta=f"{total_pnl:+.2f}")
        st.sidebar.metric("Win Rate", f"{win_rate:.1f}%", delta=f"{wins}W - {losses}L")

        if view_mode == "Single Trade Audit":
            st.subheader("🔍 Audit Individual Executions")
            st.markdown("Inspect trade execution timelines matched against live minute candles.")
            
            # Form dropdown helper lists
            df_closed['dropdown_label'] = df_closed.apply(
                lambda r: f"{r['Ticker']} | PnL: ${r['PnL']:+.2f} | {r['Entry_Time']}", axis=1
            )
            trade_labels = df_closed['dropdown_label'].tolist()
            zoom_options = ["Tight Zoom (15m context)", "Standard Zoom (45m context)", "Wide Zoom (2h context)", "Show Full Day (Market Hours)"]
            style_options = ["Buy/Sell Arrows Only", "Stock Graph Only", "Both (Stock Graph + Arrows)"]
            
            # Resolve State Defaults
            if st.session_state.stored_single_selected_label not in trade_labels:
                st.session_state.stored_single_selected_label = trade_labels[0]
                
            idx_label = trade_labels.index(st.session_state.stored_single_selected_label)
            idx_zoom = zoom_options.index(st.session_state.stored_single_buffer_choice)
            idx_style = style_options.index(st.session_state.stored_single_chart_style)

            # Form-based filters with custom indexing and unique widget keys to prevent bleed-through
            col_sel1, col_sel2, col_sel3 = st.columns([2, 1, 1])
            with col_sel1:
                selected_label = st.selectbox(
                    "Select a completed trade to plot:", 
                    trade_labels, 
                    index=idx_label,
                    key="single_trade_label_widget"
                )
                st.session_state.stored_single_selected_label = selected_label
            with col_sel2:
                buffer_choice = st.selectbox(
                    "Visual Zoom Level:", 
                    zoom_options, 
                    index=idx_zoom,
                    key="single_zoom_widget"
                )
                st.session_state.stored_single_buffer_choice = buffer_choice
            with col_sel3:
                chart_style = st.selectbox(
                    "Chart Representation:", 
                    style_options, 
                    index=idx_style,
                    key="single_style_widget"
                )
                st.session_state.stored_single_chart_style = chart_style
                
            # Extract the ID from the selected trade summary
            target_trade_id = df_closed[df_closed['dropdown_label'] == selected_label].iloc[0]['Trade_ID']

            # Fetch ALL raw legs for this trade ID from the clean (raw) data
            trade_legs = df_clean[df_clean['Trade_ID'] == target_trade_id]

            selected_trade = trade_legs.iloc[0]

            # Use the first/last of the raw legs for setting chart boundaries
            entry_dt = trade_legs['Entry_Time'].min()
            exit_dt = trade_legs['Exit_Time'].max()
            ticker = trade_legs['Ticker'].iloc[0]
            
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

                # 2. Buy/Sell Arrows (Explicit Entry + Multiple Exits)
                if chart_style in ["Buy/Sell Arrows Only", "Both (Stock Graph + Arrows)"]:
                    trade_legs = df_clean[df_clean['Trade_ID'] == target_trade_id].copy()
                    
                    # Plot Entry (Only 1 row will have an Entry_Time)
                    entry_df = trade_legs[trade_legs['Entry_Time'].notna()]
                    if not entry_df.empty:
                        entry_row = entry_df.iloc[0]
                        fig.add_trace(go.Scatter(
                            x=[entry_row['Entry_Time']], y=[entry_row['Entry_Price']],
                            mode="markers+text",
                            marker=dict(symbol="triangle-up", color="#10B981", size=14, line=dict(color="white", width=2)),
                            name="Buy Entry", text=[f"Buy {entry_row['Qty']}"],
                            textposition="bottom center", showlegend=False
                        ))

                    # Plot Exits (All rows that have an Exit_Time)
                    exit_df = trade_legs[trade_legs['Exit_Time'].notna()]
                    for _, row in exit_df.iterrows():
                        fig.add_trace(go.Scatter(
                            x=[row['Exit_Time']], y=[row['Exit_Price']],
                            mode="markers+text",
                            marker=dict(symbol="triangle-down", color="#EF4444", size=14, line=dict(color="white", width=2)),
                            name="Sell Exit", text=[f"Exit {row['Qty']}<br>PnL: {row['PnL']}"],
                            textposition="top center", showlegend=False
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
            
            # =====================================================================
            # 🏆 TICKER LEADERBOARD TRACKER COMPONENT
            # =====================================================================
            # Master Toggle Switch to programmatically freeze/restore the expanded state of the expander
            leaderboard_expanded = st.toggle(
                "Show Performance Leaderboard", 
                value=st.session_state.stored_leaderboard_expanded,
                help="Toggle to expand or collapse the performance leaderboard statistics grid below."
            )
            st.session_state.stored_leaderboard_expanded = leaderboard_expanded

            with st.expander("🏆 Ticker Performance Leaderboard Tracker", expanded=leaderboard_expanded):
                leaderboard_rows = []
                for ticker in df_closed['Ticker'].unique():
                    ticker_trades = df_closed[df_closed['Ticker'] == ticker]
                    t_pnl = ticker_trades['PnL'].sum()
                    t_count = len(ticker_trades)
                    t_wins = (ticker_trades['PnL'] > 0).sum()
                    t_losses = (ticker_trades['PnL'] <= 0).sum()
                    t_wr = (t_wins / t_count) * 100 if t_count > 0 else 0.0
                    t_expectancy = ticker_trades['PnL'].mean()
                    
                    # Ultra Statistics Calculations
                    best_trade = ticker_trades['PnL'].max()
                    worst_trade = ticker_trades['PnL'].min()
                    
                    avg_win = ticker_trades[ticker_trades['PnL'] > 0]['PnL'].mean() if t_wins > 0 else 0.0
                    avg_loss = ticker_trades[ticker_trades['PnL'] <= 0]['PnL'].mean() if t_losses > 0 else 0.0
                    
                    gross_wins = ticker_trades[ticker_trades['PnL'] > 0]['PnL'].sum()
                    gross_losses = abs(ticker_trades[ticker_trades['PnL'] < 0]['PnL'].sum())
                    profit_factor = gross_wins / gross_losses if gross_losses > 0 else (gross_wins if gross_wins > 0 else 1.0)
                    
                    leaderboard_rows.append({
                        "Ticker": ticker,
                        "Total PnL": t_pnl,
                        "Trades": t_count,
                        "Win Rate": t_wr,
                        "Win/Loss Record": f"{t_wins}W - {t_losses}L",
                        "Best Trade": best_trade,
                        "Worst Trade": worst_trade,
                        "Avg Win": avg_win,
                        "Avg Loss": avg_loss,
                        "Profit Factor": profit_factor,
                        "Expectancy (Avg/Trade)": t_expectancy
                    })
                
                # Sort descending by absolute PnL to establish competitive leaderboard ranks
                df_leaderboard = pd.DataFrame(leaderboard_rows)
                df_leaderboard = df_leaderboard.sort_values(by="Total PnL", ascending=False).reset_index(drop=True)
                
                # Format rankings with custom leaderboard trophies
                df_leaderboard.insert(0, "Rank", "")
                for idx in range(len(df_leaderboard)):
                    rank_pos = idx + 1
                    if rank_pos == 1:
                        df_leaderboard.at[idx, "Rank"] = "🥇 1st"
                    elif rank_pos == 2:
                        df_leaderboard.at[idx, "Rank"] = "🥈 2nd"
                    elif rank_pos == 3:
                        df_leaderboard.at[idx, "Rank"] = "🥉 3rd"
                    else:
                        df_leaderboard.at[idx, "Rank"] = f"   {rank_pos}th"
                
                st.dataframe(
                    df_leaderboard,
                    column_config={
                        "Rank": st.column_config.TextColumn("Leaderboard Rank", help="Performance placement based on total net profits."),
                        "Ticker": st.column_config.TextColumn("Stock Ticker"),
                        "Total PnL": st.column_config.NumberColumn("Total Net PnL", format="$%,.2f", help="Sum of all closed trade net gains or losses."),
                        "Trades": st.column_config.NumberColumn("Completed Trades"),
                        "Win Rate": st.column_config.NumberColumn("Win Rate", format="%.1f%%"),
                        "Win/Loss Record": st.column_config.TextColumn("Record (W - L)"),
                        "Best Trade": st.column_config.NumberColumn("🔥 Best Trade", format="$%,.2f", help="The largest single winning trade on this asset."),
                        "Worst Trade": st.column_config.NumberColumn("❄️ Worst Trade", format="$%,.2f", help="The deepest single losing trade on this asset."),
                        "Avg Win": st.column_config.NumberColumn("📈 Avg Win", format="$%,.2f", help="The average payout for winning trades."),
                        "Avg Loss": st.column_config.NumberColumn("📉 Avg Loss", format="$%,.2f", help="The average cost for losing trades."),
                        "Profit Factor": st.column_config.NumberColumn("📊 Profit Factor", format="%.2f", help="Gross Wins divided by Gross Losses. A value > 1.0 is historically profitable."),
                        "Expectancy (Avg/Trade)": st.column_config.NumberColumn("Avg Return/Trade", format="$%,.2f")
                    },
                    hide_index=True,
                    use_container_width=True
                )
            
            # Form options lists
            unique_tickers = sorted(df_closed['Ticker'].unique())
            horizon_options = ["1 Day (1m intervals)", "5 Days (5m intervals)", "1 Month (15m intervals)", "3 Months (1h intervals)", "6 Months (Daily intervals)"]
            style_options = ["Buy/Sell Arrows Only", "Stock Graph Only", "Both (Stock Graph + Arrows)"]
            
            # Resolve State Defaults
            if st.session_state.stored_all_selected_ticker not in unique_tickers:
                st.session_state.stored_all_selected_ticker = unique_tickers[0]
                
            idx_ticker = unique_tickers.index(st.session_state.stored_all_selected_ticker)
            idx_horizon = horizon_options.index(st.session_state.stored_all_period_choice)
            idx_all_style = style_options.index(st.session_state.stored_all_chart_style)

            # Interactive horizon selectors with strict widget key configurations to isolate views
            col_sel1, col_sel2, col_sel3 = st.columns([2, 1, 1])
            with col_sel1:
                selected_ticker = st.selectbox(
                    "Select a Stock to Analyze:", 
                    unique_tickers, 
                    index=idx_ticker,
                    key="all_ticker_widget"
                )
                st.session_state.stored_all_selected_ticker = selected_ticker
            with col_sel2:
                period_choice = st.selectbox(
                    "Historical Chart Horizon:", 
                    horizon_options, 
                    index=idx_horizon,
                    key="all_horizon_widget"
                )
                st.session_state.stored_all_period_choice = period_choice
            with col_sel3:
                all_chart_style = st.selectbox(
                    "Chart Representation:", 
                    style_options, 
                    index=idx_all_style,
                    key="all_style_widget"
                )
                st.session_state.stored_all_chart_style = all_chart_style
            
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
            df_closed['Running_Peak'] = df_closed['Cumulative_PnL'].cummax()
            df_closed['Drawdown'] = df_closed['Cumulative_PnL'] - df_closed['Running_Peak']

            # Construct Equity Curve Line Plot with an underwater drawdown panel beneath it
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.7, 0.3], vertical_spacing=0.08
            )

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
            ), row=1, col=1)

            # Reference benchmark line at $0.00 profit
            fig.add_shape(
                type="line", x0=df_closed['Exit_Time'].min(), x1=df_closed['Exit_Time'].max(),
                y0=0, y1=0, line=dict(color="rgba(255,255,255,0.3)", width=1, dash="dot"),
                row=1, col=1
            )

            # Underwater drawdown area
            fig.add_trace(go.Scatter(
                x=df_closed['Exit_Time'],
                y=df_closed['Drawdown'],
                mode='lines',
                name='Drawdown',
                line=dict(color="#EF4444", width=2),
                fill='tozeroy',
                fillcolor="rgba(239, 68, 68, 0.2)",
                hovertemplate="<b>Time:</b> %{x}<br><b>Drawdown:</b> $%{y:,.2f}<extra></extra>"
            ), row=2, col=1)

            fig.update_layout(
                title="Account Capital Growth Curve (Net Cumulative Return)",
                template="plotly_dark",
                height=600
            )
            fig.update_xaxes(title_text="Execution Timeline", row=2, col=1)
            fig.update_yaxes(title_text="Total Profits / Losses ($)", row=1, col=1)
            fig.update_yaxes(title_text="Drawdown ($)", row=2, col=1)

            st.plotly_chart(fig, use_container_width=True)

            # Additional Analytical Insight Box
            st.markdown("### 📊 Portfolio Metrics Dashboard")
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            with m_col1:
                largest_win = df_closed['PnL'].max()
                st.metric("Best Single Trade", f"${largest_win:,.2f}")
            with m_col2:
                largest_loss = df_closed['PnL'].min()
                st.metric("Worst Single Trade", f"${largest_loss:,.2f}")
            with m_col3:
                avg_trade = df_closed['PnL'].mean()
                st.metric("Expectancy (Avg/Trade)", f"${avg_trade:+.2f}")
            with m_col4:
                max_drawdown = df_closed['Drawdown'].min()
                st.metric("Max Drawdown", f"${max_drawdown:,.2f}")

            # Engine Comparison Breakdown
            st.markdown("### ⚙️ Engine Comparison")
            df_closed['Engine'] = df_closed['Engine'].fillna("Legacy")

            def _profit_factor(pnl_series):
                gross_win = pnl_series[pnl_series > 0].sum()
                gross_loss = pnl_series[pnl_series < 0].sum()
                return gross_win / abs(gross_loss) if gross_loss != 0 else float('inf')

            engine_stats = df_closed.groupby('Engine').apply(lambda g: pd.Series({
                'Trade Count': len(g),
                'Total PnL': g['PnL'].sum(),
                'Win Rate': (g['PnL'] > 0).mean() * 100,
                'Avg PnL/Trade': g['PnL'].mean(),
                'Profit Factor': _profit_factor(g['PnL'])
            }), include_groups=False).reset_index()

            st.dataframe(
                engine_stats,
                column_config={
                    "Engine": st.column_config.TextColumn("Engine"),
                    "Trade Count": st.column_config.NumberColumn("Trade Count", format="%d"),
                    "Total PnL": st.column_config.NumberColumn("Total PnL", format="$%.2f"),
                    "Win Rate": st.column_config.NumberColumn("Win Rate", format="%.1f%%"),
                    "Avg PnL/Trade": st.column_config.NumberColumn("Avg PnL/Trade", format="$%.2f"),
                    "Profit Factor": st.column_config.NumberColumn("Profit Factor", format="%.2f"),
                },
                hide_index=True,
                use_container_width=True
            )
            st.caption("This tells you whether ENGINE_A and ENGINE_B are both pulling their weight, or if one is carrying (or dragging) the account.")