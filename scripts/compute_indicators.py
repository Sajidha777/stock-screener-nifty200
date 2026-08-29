"""
compute_indicators.py — Calculate technical indicators

Indicators computed:
  Momentum   : RSI(14), RSI(9)
  Trend      : SMA(10), SMA(20), SMA(50), SMA(200), EMA(21), EMA(50)
  MACD       : MACD line, signal line, histogram
  Volume     : 20-day volume SMA, volume ratio (today / SMA20)
  Volatility : Bollinger Bands(20, 2), ATR(14)
  52W range  : 52-week high, 52-week low, % above 52W low

"""

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pandas_ta as ta

ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH  = DATA_DIR / "screener.duckdb"

TRADING_DAYS_PER_YEAR = 252

def  setup_indicators_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("DROP TABLE IF EXISTS indicators")
    conn.execute("""
        CREATE TABLE indicators (
            ticker            VARCHAR  NOT NULL,
            date              DATE     NOT NULL,
            open              DOUBLE,
            high              DOUBLE,
            low               DOUBLE,
            close             DOUBLE,
            volume            BIGINT,
            -- Momentum
            rsi_14            DOUBLE,
            rsi_9             DOUBLE,
            -- Trend: simple moving averages
            sma_10            DOUBLE,
            sma_20            DOUBLE,
            sma_50            DOUBLE,
            sma_200           DOUBLE,
            -- Trend: exponential moving averages
            ema_21            DOUBLE,
            ema_50            DOUBLE,
            -- MACD (12, 26, 9)
            macd_line         DOUBLE,
            macd_signal       DOUBLE,
            macd_hist         DOUBLE,
            -- Volume
            vol_sma_20        DOUBLE,
            vol_ratio         DOUBLE,
            -- Bollinger Bands (20, 2)
            bb_upper          DOUBLE,
            bb_mid            DOUBLE,
            bb_lower          DOUBLE,
            -- Average True Range
            atr_14            DOUBLE,
            -- 52-week range (rolling 252 trading-day window)
            high_52w          DOUBLE,
            low_52w           DOUBLE,
            pct_from_52w_low  DOUBLE,
            PRIMARY KEY (ticker, date)
        )
    """)
    print("  indicators table created.")



def compute_for_ticker(df: pd.DataFrame) -> pd.DataFrame:

    # pandas-ta can return a DataFrame instead of a Series in edge cases.
    def ta_series(result) -> pd.Series:
        if result is None:
            return pd.Series(np.nan, index=df.index)
        return result.iloc[:, 0] if isinstance(result, pd.DataFrame) else result

    df["rsi_14"] = ta_series(df.ta.rsi(length=14))
    df["rsi_9"]  = ta_series(df.ta.rsi(length=9))

    df["sma_10"]  = df["close"].rolling(10).mean()
    df["sma_20"]  = df["close"].rolling(20).mean()
    df["sma_50"]  = df["close"].rolling(50).mean()
    df["sma_200"] = df["close"].rolling(200).mean()

    # adjust=False = recursive EMA (standard finance convention).
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()

    # MACD returns a 3-column DataFrame: line, histogram, signal.
    macd = df.ta.macd(fast=12, slow=26, signal=9)
    if macd is not None and not macd.empty and macd.shape[1] >= 3:
        df["macd_line"]   = macd.iloc[:, 0]
        df["macd_signal"] = macd.iloc[:, 2]
        df["macd_hist"]   = macd.iloc[:, 1]
    else:
        df["macd_line"] = df["macd_signal"] = df["macd_hist"] = np.nan

    df["vol_sma_20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"]  = df["volume"] / df["vol_sma_20"].replace(0, np.nan)

    # Bollinger Bands returns: BBL (lower), BBM (mid), BBU (upper), BBB, BBP.
    bb = df.ta.bbands(length=20, std=2)
    if bb is not None and not bb.empty and bb.shape[1] >= 3:
        df["bb_lower"] = bb.iloc[:, 0]
        df["bb_mid"]   = bb.iloc[:, 1]
        df["bb_upper"] = bb.iloc[:, 2]
    else:
        df["bb_lower"] = df["bb_mid"] = df["bb_upper"] = np.nan

    df["atr_14"] = ta_series(df.ta.atr(length=14))

    # min_periods=1 gives partial results for early rows instead of NaN.
    df["high_52w"] = df["high"].rolling(TRADING_DAYS_PER_YEAR, min_periods=1).max()
    df["low_52w"]  = df["low"].rolling(TRADING_DAYS_PER_YEAR, min_periods=1).min()

    df["pct_from_52w_low"] = (
        (df["close"] - df["low_52w"]) / df["low_52w"].replace(0, np.nan) * 100
    )

    return df


INDICATOR_COLUMNS = [
    "ticker", "date", "open", "high", "low", "close", "volume",
    "rsi_14", "rsi_9",
    "sma_10", "sma_20", "sma_50", "sma_200",
    "ema_21", "ema_50",
    "macd_line", "macd_signal", "macd_hist",
    "vol_sma_20", "vol_ratio",
    "bb_upper", "bb_mid", "bb_lower",
    "atr_14",
    "high_52w", "low_52w", "pct_from_52w_low",
]


def main() -> None:
    print("=" * 60)
    print("Step 2: Computing technical indicators")
    print("=" * 60)

    conn = duckdb.connect(str(DB_PATH), config={"memory_limit": "1GB"})

    print("\nSetting up indicators table...")
    setup_indicators_table(conn)

    print("\nLoading OHLCV data...")
    ohlcv = conn.execute("""
        SELECT ticker, date, open, high, low, close, volume
        FROM ohlcv
        ORDER BY ticker, date
    """).df()
    ticker_count = ohlcv["ticker"].nunique()
    print(f"  {len(ohlcv):,} rows | {ticker_count} tickers")

    tickers = sorted(ohlcv["ticker"].unique())

    print(f"\nComputing indicators for {len(tickers)} tickers...")
    results = []

    for i, ticker in enumerate(tickers, 1):
        df = ohlcv[ohlcv["ticker"] == ticker].copy().reset_index(drop=True)
        df = compute_for_ticker(df)
        results.append(df[INDICATOR_COLUMNS])

        if i % 50 == 0 or i == len(tickers):
            print(f"  [{i:>3}/{len(tickers)}] processed")

    print("\nCombining results...")
    final = pd.concat(results, ignore_index=True)

    final["ticker"] = final["ticker"].astype(object)
    final["date"]   = pd.to_datetime(final["date"]).dt.normalize()

    print("Writing to DuckDB...")
    conn.execute("INSERT INTO indicators SELECT * FROM final")


    row_count  = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
    date_range = conn.execute("SELECT MIN(date), MAX(date) FROM indicators").fetchone()
    null_check = conn.execute("""
        SELECT COUNT(*) FROM indicators WHERE rsi_14 IS NOT NULL
    """).fetchone()[0]

    print("\n" + "─" * 60)
    print(f"  Rows written       : {row_count:,}")
    print(f"  Rows with RSI(14)  : {null_check:,}  (rest are warm-up rows)")
    print(f"  Date range         : {date_range[0]} → {date_range[1]}")
    print(f"  Database           : {DB_PATH}")

    print("\nSample (RELIANCE.NS, latest 3 rows):")
    sample = conn.execute("""
        SELECT date, open, high, low, close, volume, rsi_14, sma_20, vol_ratio, pct_from_52w_low
        FROM indicators
        WHERE ticker = 'RELIANCE.NS'
        ORDER BY date DESC
        LIMIT 3
    """).fetchall()
    print(f"  {'date':<12} {'open':>8} {'high':>8} {'low':>8} {'close':>8} {'volume':>12} {'rsi_14':>8} {'sma_20':>8} {'vol_ratio':>10} {'pct_52w_low':>12}")
    for row in sample:
        print(f"  {str(row[0]):<12} {(row[1] or 0):>8.2f} {(row[2] or 0):>8.2f} {(row[3] or 0):>8.2f} {(row[4] or 0):>8.2f} {(row[5] or 0):>12,} {(row[6] or 0):>8.2f} {(row[7] or 0):>8.2f} {(row[8] or 0):>10.2f} {(row[9] or 0):>12.2f}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
