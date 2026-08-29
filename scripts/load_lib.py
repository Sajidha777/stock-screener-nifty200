"""
load_lib.py — Shared OHLCV loading logic
"""

import sys
from pathlib import Path

import duckdb
import pandas as pd
import yfinance as yf

ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH  = DATA_DIR / "screener.duckdb"

# https://www.nseindia.com/products-services/indices-nifty200-index
NIFTY200_CSV = ROOT_DIR / "data" / "nifty200.csv"

SLEEP_BETWEEN_TICKERS = 0.5 

FAILURE_THRESHOLD_PCT = 0.05


def check_failure_threshold(failed: list, total: int) -> None:
    if len(failed) > total * FAILURE_THRESHOLD_PCT:
        print(f"\n  ERROR: {len(failed)}/{total} tickers failed — exceeds the "
              f"{FAILURE_THRESHOLD_PCT:.0%} threshold. Failing the run.")
        sys.exit(1)


def get_nifty200_tickers() -> list[str]:
    if not NIFTY200_CSV.exists():
        raise FileNotFoundError(
            f"Nifty 200 list not found at {NIFTY200_CSV}\n"
            "Download it from: https://www.nseindia.com/products-services/indices-nifty200-index\n"
            "and save it as data/nifty200.csv"
        )
    df = pd.read_csv(NIFTY200_CSV)
    tickers = [f"{symbol.strip()}.NS" for symbol in df["Symbol"]]
    print(f"  Read {len(tickers)} tickers from {NIFTY200_CSV.name}")
    return tickers


def setup_database(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            ticker  VARCHAR  NOT NULL,
            date    DATE     NOT NULL,
            open    DOUBLE,
            high    DOUBLE,
            low     DOUBLE,
            close   DOUBLE,
            volume  BIGINT,
            PRIMARY KEY (ticker, date)
        )
    """)


def fetch_and_store(conn: duckdb.DuckDBPyConnection, ticker: str, period: str = "2y") -> None:
    # auto_adjust=True applies split/dividend adjustments to historical prices.
    df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)

    if df.empty:
        print(f"    [WARN] No data returned — skipping")
        return

    df = df.reset_index()

    # yfinance column names are tuples for multi-ticker downloads; flatten them.
    df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower()
                  for col in df.columns]

    df["ticker"] = ticker
    df = df[["ticker", "date", "open", "high", "low", "close", "volume"]]
    df["date"]   = pd.to_datetime(df["date"]).dt.normalize()
    df["ticker"] = df["ticker"].astype(object)  # DuckDB needs object dtype, not StringDtype

    # Yahoo sometimes publishes a session's volume before its close is
    # finalized (usually resolves within the same day) — skip incomplete
    # rows rather than storing a partial candle; the next run's overlapping
    # window will pick it up once it's complete.
    incomplete = df[["open", "high", "low", "close", "volume"]].isna().any(axis=1)
    if incomplete.any():
        print(f"    [WARN] {incomplete.sum()} incomplete row(s) skipped (pending EOD data)")
        df = df[~incomplete]

    if df.empty:
        return

    conn.execute("""
        INSERT OR REPLACE INTO ohlcv
        SELECT ticker, date, open, high, low, close, volume
        FROM df
    """)
