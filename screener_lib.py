"""
screener_lib.py — Shared screener logic: strategy definitions and query helpers

"""

from pathlib import Path

import duckdb
import pandas as pd

ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH  = DATA_DIR / "screener.duckdb"

TRADING_DAYS_PER_YEAR = 252

SIGNALS_CTE = """
    WITH signals AS (
        SELECT
            ticker, date, close, rsi_14, sma_50, sma_200, vol_ratio, pct_from_52w_low, high_52w,
            MAX(high) OVER w20 AS high_20d,
            LAG(rsi_14) OVER w AS rsi_14_prev,
            LAG(close)  OVER w AS close_prev,
            LAG(sma_50) OVER w AS sma_50_prev
        FROM indicators
        WINDOW w   AS (PARTITION BY ticker ORDER BY date),
               w20 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
    )
"""


def near_52w_low_condition(pct_from_low: float = 20.0) -> str:
    return f"pct_from_52w_low < {pct_from_low}"


def near_52w_high_condition(pct_from_high: float = 20.0) -> str:
    return f"(high_52w - close) / NULLIF(high_52w, 0) * 100 < {pct_from_high}"


def oversold_recovery_condition(rsi_min: float = 25.0, rsi_max: float = 40.0,
                                 max_pct_vs_sma200: float = -10.0) -> str:
    # % from 52-week low dropped entirely — the table already has a
    # pct_from_52w_low column to see/sort that number directly. SMA200 is now
    # the sole drawdown check instead of a "min N of 2" score.
    return f"""
        rsi_14 BETWEEN {rsi_min} AND {rsi_max}
        AND close > close_prev
        AND (close - sma_200) / NULLIF(sma_200, 0) * 100 < {max_pct_vs_sma200}
    """


def pullback_condition(pullback_min: float = 10.0, pullback_max: float = 25.0) -> str:
    # No SMA50>SMA200 trend-filter option here (unlike momentum_entry) — tested
    # and found to make results worse, not better: 47.1% win rate on a thin,
    # concentrated 37-ticker sample when stacked on, vs 54.7% without it on 82
    # tickers. Unlike momentum_entry's version of this same checkbox (which
    # measurably helped, if only a little), there's no case where turning this
    # on is the right call, so it isn't offered as an option at all.
    return f"""
        close > sma_50
        AND (high_20d - close) / NULLIF(high_20d, 0) * 100 BETWEEN {pullback_min} AND {pullback_max}
        AND rsi_14 > rsi_14_prev
    """


def momentum_entry_condition(vol_multiplier: float = 1.0, require_trend_filter: bool = True) -> str:
    # RSI fixed at 55-65 rather than "crosses above a threshold" slider — tested
    # against real history: this range beat every crossing variant and every
    # wider/narrower range (55.2% win rate, z=1.58, vs. z<=0.23 elsewhere).
    sql = f"""
        rsi_14 BETWEEN 55 AND 65
        AND close > sma_50 AND close_prev < sma_50_prev
        AND vol_ratio > {vol_multiplier}
    """
    if require_trend_filter:
        sql += " AND sma_50 > sma_200"
    return sql


STRATEGY_BUILDERS = {
    "near_52w_low": near_52w_low_condition,
    "near_52w_high": near_52w_high_condition,
    "oversold_recovery": oversold_recovery_condition,
    "momentum_entry": momentum_entry_condition,
    "pullback": pullback_condition,
}

# Display name + plain-English description per screener — shown in the
# dashboard since the actual SQL condition isn't. Descriptions state
# mechanics only (what's being checked), not a quality/performance verdict —
# that context lives in code comments and conversation history, not the UI.
STRATEGY_DISPLAY = {
    "near_52w_low": {
        "label": "Near 52-Week Low",
        "description": "Stocks trading within a chosen % of their 52-week low.",
    },
    "near_52w_high": {
        "label": "Near 52-Week High",
        "description": "Stocks trading within a chosen % of their 52-week high.",
    },
    "oversold_recovery": {
        "label": "Oversold Recovery",
        "description": "RSI in a recovering 25-40 zone on an up day, scored against being "
                        "near the 52-week low and well below the 200-day average.",
    },
    "momentum_entry": {
        "label": "Momentum Entry",
        "description": "RSI in the 55-65 zone with price crossing above its 50-day average, "
                        "confirmed by above-average volume.",
    },
    "pullback": {
        "label": "Pullback",
        "description": "A short-term dip within a broader uptrend — retraced 10-25% from the "
                        "20-day high, with RSI turning back up.",
    },
}

# Numeric slider metadata: {strategy: {param_name: {label, options, default}}}
STRATEGY_PARAMS = {
    "near_52w_low": {
        "pct_from_low": {"label": "% from 52-week low", "options": [5.0, 10.0, 20.0, 30.0, 40.0], "default": 20.0},
    },
    "near_52w_high": {
        "pct_from_high": {"label": "% from 52-week high", "options": [5.0, 10.0, 20.0, 30.0, 40.0], "default": 20.0},
    },
    "oversold_recovery": {
        "rsi_min": {"label": "RSI min", "options": [20.0, 25.0, 30.0, 35.0], "default": 25.0},
        "rsi_max": {"label": "RSI max", "options": [35.0, 40.0, 45.0, 50.0], "default": 40.0},
        "max_pct_vs_sma200": {
            "label": "Max % vs SMA200 (more negative = deeper drawdown required)",
            "options": [-30.0, -20.0, -10.0, 0.0], "default": -10.0,
        },
    },
    "momentum_entry": {
        "vol_multiplier": {"label": "Volume multiplier", "options": [1.0, 1.5, 2.0, 3.0], "default": 1.5},
    },
    "pullback": {
        "pullback_min": {"label": "Min % retraced from 20-day high", "options": [3.0, 5.0, 8.0, 10.0], "default": 10.0},
        "pullback_max": {"label": "Max % retraced from 20-day high", "options": [10.0, 15.0, 20.0, 25.0], "default": 25.0},
    },
}

# Checkbox metadata: {strategy: {param_name: {label, default}}}
STRATEGY_BOOL_PARAMS = {
    "momentum_entry": {
        "require_trend_filter": {"label": "Require SMA50 > SMA200 (avoid choppy markets)", "default": True},
    },
}

def default_params(strategy: str) -> dict:
    numeric = {name: meta["default"] for name, meta in STRATEGY_PARAMS.get(strategy, {}).items()}
    boolean = {name: meta["default"] for name, meta in STRATEGY_BOOL_PARAMS.get(strategy, {}).items()}
    return {**numeric, **boolean}


def get_connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=True)


def get_latest_date(conn: duckdb.DuckDBPyConnection):
    return conn.execute("SELECT MAX(date) FROM indicators").fetchone()[0]


def get_todays_screener(conn: duckdb.DuckDBPyConnection, strategy: str, params: dict) -> pd.DataFrame:
    """All tickers that meet the strategy's conditions on the latest date."""
    condition = STRATEGY_BUILDERS[strategy](**params)
    nifty200_csv = str(DATA_DIR / "nifty200.csv")
    return conn.execute(f"""
        {SIGNALS_CTE},
        companies AS (
            SELECT Symbol || '.NS' AS ticker, "Company Name" AS company_name
            FROM read_csv_auto('{nifty200_csv}')
        )
        SELECT c.company_name, s.ticker, s.close,
               ROUND((s.close - s.close_prev) / NULLIF(s.close_prev, 0) * 100, 2) AS pct_change,
               s.pct_from_52w_low, s.vol_ratio,
               s.rsi_14,
               ROUND((s.high_52w - s.close) / NULLIF(s.high_52w, 0) * 100, 1) AS pct_from_52w_high,
               ROUND((s.close - s.sma_200) / NULLIF(s.sma_200, 0) * 100, 1) AS pct_vs_sma200
        FROM signals s
        JOIN companies c ON s.ticker = c.ticker
        WHERE ({condition})
        AND s.date = (SELECT MAX(date) FROM indicators)
        ORDER BY s.ticker
    """).df()


def get_ohlcv(conn: duckdb.DuckDBPyConnection, ticker: str, days: int = 2 * TRADING_DAYS_PER_YEAR) -> pd.DataFrame:
    return conn.execute("""
        SELECT date, open, high, low, close, volume
        FROM ohlcv
        WHERE ticker = ?
        ORDER BY date DESC
        LIMIT ?
    """, [ticker, days]).df().sort_values("date")


def get_all_tickers(conn: duckdb.DuckDBPyConnection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM ohlcv ORDER BY ticker").fetchall()]


# Lookback options for the leading-sectors list — 30/60 days tested strongest
SECTOR_LOOKBACK_OPTIONS = [30, 60, 90, 120]
SECTOR_LOOKBACK_DEFAULT = 60


def get_leading_sectors(conn: duckdb.DuckDBPyConnection, lookback_days: int = 60) -> pd.DataFrame:
    nifty200_csv = str(DATA_DIR / "nifty200.csv")
    return conn.execute(f"""
        WITH returns AS (
            SELECT ticker, date, close,
                   LAG(close, {lookback_days}) OVER (PARTITION BY ticker ORDER BY date) AS close_lb_ago
            FROM indicators
        ),
        latest_returns AS (
            SELECT ticker, (close - close_lb_ago) / NULLIF(close_lb_ago, 0) * 100 AS return_pct
            FROM returns
            WHERE date = (SELECT MAX(date) FROM indicators) AND close_lb_ago IS NOT NULL
        ),
        industries AS (
            SELECT Symbol || '.NS' AS ticker, Industry AS industry
            FROM read_csv_auto('{nifty200_csv}')
        )
        SELECT i.industry AS industry, COUNT(*) AS n_stocks,
               ROUND(AVG(r.return_pct), 2) AS avg_return,
               ROUND(MEDIAN(r.return_pct), 2) AS median_return
        FROM latest_returns r
        JOIN industries i ON r.ticker = i.ticker
        GROUP BY i.industry
        ORDER BY avg_return DESC
    """).df()


def get_stocks_in_sector(conn: duckdb.DuckDBPyConnection, industry: str, lookback_days: int = 60) -> pd.DataFrame:
    nifty200_csv = str(DATA_DIR / "nifty200.csv")
    return conn.execute(f"""
        WITH returns AS (
            SELECT ticker, date, close,
                   LAG(close, {lookback_days}) OVER (PARTITION BY ticker ORDER BY date) AS close_lb_ago
            FROM indicators
        ),
        latest_returns AS (
            SELECT ticker, close,
                   ROUND((close - close_lb_ago) / NULLIF(close_lb_ago, 0) * 100, 2) AS return_pct
            FROM returns
            WHERE date = (SELECT MAX(date) FROM indicators) AND close_lb_ago IS NOT NULL
        ),
        industries AS (
            SELECT Symbol || '.NS' AS ticker, "Company Name" AS company_name, Industry AS industry
            FROM read_csv_auto('{nifty200_csv}')
        )
        SELECT i.company_name, r.ticker, r.close, r.return_pct
        FROM latest_returns r
        JOIN industries i ON r.ticker = i.ticker
        WHERE i.industry = ?
        ORDER BY r.return_pct DESC
    """, [industry]).df()
