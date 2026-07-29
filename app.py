"""
app.py — Nifty 200 Swing Screener dashboard

"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from screener_lib import (
    SECTOR_LOOKBACK_DEFAULT, SECTOR_LOOKBACK_OPTIONS, STRATEGY_BOOL_PARAMS, STRATEGY_DISPLAY,
    STRATEGY_PARAMS, TRADING_DAYS_PER_YEAR, get_connection, get_latest_date, get_leading_sectors,
    get_ohlcv, get_stocks_in_sector, get_todays_screener,
)

st.set_page_config(page_title="Nifty 200 Swing Screener", layout="wide")

conn = get_connection()
latest_date = get_latest_date(conn)

# Values are trading days, not calendar days (same convention as TRADING_DAYS_PER_YEAR
# elsewhere) — 1M/6M are fractions of it, not separately-guessed numbers, so they can't
# drift out of sync with 1Y/2Y the way calendar-day math did before.
TIME_RANGE_OPTIONS = {
    "5D": 5,
    "1M": TRADING_DAYS_PER_YEAR // 12,
    "6M": TRADING_DAYS_PER_YEAR // 2,
    "1Y": TRADING_DAYS_PER_YEAR,
    "2Y": 2 * TRADING_DAYS_PER_YEAR,
}


def build_candlestick_figure(ohlcv_df: pd.DataFrame, ticker_name: str) -> go.Figure:
    """Kept separate from show_chart_popup for readability — it's the only
    caller now that the inline chart section was removed."""
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=ohlcv_df["date"], open=ohlcv_df["open"], high=ohlcv_df["high"],
        low=ohlcv_df["low"], close=ohlcv_df["close"], name=ticker_name,
        # Line color set equal to fillcolor so candles render as solid blocks,
        # not fill+contrasting-border — same colors TradingView uses by default.
        increasing=dict(line=dict(color="#26A69A"), fillcolor="#26A69A"),
        decreasing=dict(line=dict(color="#EF5350"), fillcolor="#EF5350"),
    ))
    fig.update_layout(
        xaxis_rangeslider_visible=False, height=600, legend=dict(orientation="h"),
        yaxis=dict(side="right"),  # matches standard trading-platform convention (TradingView, broker apps)
        hovermode="x unified",     # shows info for the nearest day anywhere on the chart, not just on a candle
    )
    # Crosshair: vertical + horizontal lines that follow the cursor, snapped to
    # the nearest actual trading day (not raw pixel position) — same behavior
    # as TradingView/broker platforms.
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="data", spikecolor="grey", spikethickness=1)
    fig.update_yaxes(showspikes=True, spikemode="across", spikesnap="data", spikecolor="grey", spikethickness=1)

    # Compress out non-trading days (weekends + NSE holidays) rather than just
    # weekends, so the chart shows trading sessions back-to-back with no blank
    # gaps — matches TradingView/broker platforms. Computed from the data itself
    # (whichever weekdays have no row) instead of a hardcoded holiday calendar,
    # so it stays correct without needing manual upkeep.
    all_days = pd.date_range(start=ohlcv_df["date"].min(), end=ohlcv_df["date"].max(), freq="D")
    missing_days = all_days[~all_days.isin(ohlcv_df["date"])]
    fig.update_xaxes(rangebreaks=[dict(values=missing_days)])
    return fig


def _handle_stock_click(table_event, source_df: pd.DataFrame, session_key: str) -> None:
    # Shared by every clickable stock table (screener results, sector drill-down)
    # so the same "only open on a genuinely new click" dedup logic isn't
    # duplicated — table selection persists across reruns, so without the
    # session_state check the popup would reopen on any unrelated widget change.
    clicked_ticker = source_df.iloc[table_event.selection.rows[0]]["ticker"] if table_event.selection.rows else None
    if clicked_ticker:
        if clicked_ticker != st.session_state.get(session_key):
            st.session_state[session_key] = clicked_ticker
            show_chart_popup(clicked_ticker)
    else:
        st.session_state[session_key] = None


@st.dialog(" ", width="large")
def show_chart_popup(default_ticker: str) -> None:
    # Own connection, not the outer script's `conn` — st.dialog reruns only
    # this function (not the full script) when its own widgets are used, and
    # by then the outer script's connection may already be out of scope from
    # a prior full run. Self-contained avoids depending on that lifecycle.
    popup_conn = get_connection()
    tickers = popup_conn.execute("SELECT DISTINCT ticker FROM ohlcv ORDER BY ticker").df()["ticker"].tolist()

    ticker = st.selectbox(
        "Select a stock", tickers, index=tickers.index(default_ticker),
        key="popup_ticker", label_visibility="collapsed",
        format_func=lambda t: t.removesuffix(".NS"),  # display only — ticker itself stays the full DB symbol
    )
    time_range = st.radio(
        "Time range", list(TIME_RANGE_OPTIONS.keys()), index=3, horizontal=True,
        key="popup_time_range", label_visibility="collapsed",
    )
    ohlcv_popup = get_ohlcv(popup_conn, ticker, days=TIME_RANGE_OPTIONS[time_range])
    st.plotly_chart(build_candlestick_figure(ohlcv_popup, ticker.removesuffix(".NS")), width="stretch")
    popup_conn.close()


st.title("Nifty 200 Swing Screener")
st.caption(f"Data as of {latest_date}")

section = st.radio(
    "Section", ["Screener", "Leading Sectors"], horizontal=True, label_visibility="collapsed",
)

if section == "Screener":
    strategy = st.selectbox("Screener", list(STRATEGY_PARAMS.keys()))

    display = STRATEGY_DISPLAY[strategy]
    st.subheader(display["label"])
    st.caption(display["description"])

    params = {}
    for name, meta in STRATEGY_PARAMS[strategy].items():
        params[name] = st.select_slider(meta["label"], options=meta["options"], value=meta["default"])
    for name, meta in STRATEGY_BOOL_PARAMS.get(strategy, {}).items():
        params[name] = st.checkbox(meta["label"], value=meta["default"])

    results = get_todays_screener(conn, strategy, params)


    def _color_pct_change(value: float) -> str:
        if pd.isna(value) or value == 0:
            return ""
        return f"color: {'#26A69A' if value > 0 else '#EF5350'}"  # same greens/reds as the chart


    st.subheader(f"Stocks flagged today — {len(results)}")

    # Display-only copy with the .NS suffix stripped — selection below is by row
    # position, so `results` (with the full symbol) stays the source of truth for
    # looking up which ticker was clicked.
    display_results = results.copy()
    display_results["ticker"] = display_results["ticker"].str.removesuffix(".NS")

    table_event = st.dataframe(
        display_results.style.map(_color_pct_change, subset=["pct_change"]), width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        # Only these show by default — the rest stay in the dataframe and reachable
        # via the table's own "Show/hide columns" toolbar button, not dropped.
        column_order=["company_name", "ticker", "close", "pct_change", "pct_from_52w_low", "vol_ratio"],
        column_config={
            "company_name": st.column_config.TextColumn("Company Name"),
            "ticker": st.column_config.TextColumn("Symbol"),
            "close": st.column_config.NumberColumn("Close", format="%.2f"),
            "pct_change": st.column_config.NumberColumn("% Change", format="%.2f"),
            "pct_from_52w_low": st.column_config.NumberColumn("% from 52W Low", format="%.2f"),
            "vol_ratio": st.column_config.NumberColumn("Vol Ratio", format="%.2f"),
            "rsi_14": st.column_config.NumberColumn("RSI (14)", format="%.2f"),
            "pct_from_52w_high": st.column_config.NumberColumn("% from 52W High", format="%.1f"),
            "pct_vs_sma200": st.column_config.NumberColumn("% vs SMA200", format="%.1f"),
        },
    )
    _handle_stock_click(table_event, results, "last_popup_ticker_screener")

else:
    st.subheader("Leading Sectors")
    sector_lookback = st.select_slider(
        "Lookback (trading days)", options=SECTOR_LOOKBACK_OPTIONS, value=SECTOR_LOOKBACK_DEFAULT,
    )
    sectors = get_leading_sectors(conn, sector_lookback)
    sectors_event = st.dataframe(
        sectors, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
    )

    if sectors_event.selection.rows:
        selected_industry = sectors.iloc[sectors_event.selection.rows[0]]["industry"]
        st.subheader(selected_industry)

        sector_stocks = get_stocks_in_sector(conn, selected_industry, sector_lookback)
        display_sector_stocks = sector_stocks.copy()
        display_sector_stocks["ticker"] = display_sector_stocks["ticker"].str.removesuffix(".NS")

        sector_stocks_event = st.dataframe(
            display_sector_stocks, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                "company_name": st.column_config.TextColumn("Company Name"),
                "ticker": st.column_config.TextColumn("Symbol"),
                "close": st.column_config.NumberColumn("Close", format="%.2f"),
                "return_pct": st.column_config.NumberColumn(f"Return ({sector_lookback}d)", format="%.2f"),
            },
        )
        _handle_stock_click(sector_stocks_event, sector_stocks, "last_popup_ticker_sectors")
