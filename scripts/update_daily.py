"""
update_daily.py — Incremental nightly data update

"""

import time

import duckdb

from load_lib import (
    DATA_DIR, DB_PATH, SLEEP_BETWEEN_TICKERS, check_failure_threshold,
    fetch_and_store, get_nifty200_tickers, setup_database,
)

UPDATE_PERIOD = "1mo"


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    print("Step 1: Fetching Nifty 200 ticker list...")
    tickers = get_nifty200_tickers()

    print(f"\nStep 2: Connecting to DuckDB at {DB_PATH}")
    conn = duckdb.connect(str(DB_PATH), config={"memory_limit": "1GB"})
    setup_database(conn)

    print(f"\nStep 3: Fetching last {UPDATE_PERIOD} of OHLCV for {len(tickers)} stocks...")

    failed = []

    for i, ticker in enumerate(tickers, start=1):
        print(f"  [{i:>3}/{len(tickers)}] {ticker}", end="  ")
        try:
            fetch_and_store(conn, ticker, period=UPDATE_PERIOD)
            print("✓")
        except Exception as e:
            print(f"✗  ERROR: {e}")
            failed.append((ticker, str(e)))

        time.sleep(SLEEP_BETWEEN_TICKERS)

    print("\n" + "─" * 60)
    row_count    = conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
    ticker_count = conn.execute("SELECT COUNT(DISTINCT ticker) FROM ohlcv").fetchone()[0]
    date_range   = conn.execute("SELECT MIN(date), MAX(date) FROM ohlcv").fetchone()

    print(f"  Rows in table : {row_count:,}")
    print(f"  Tickers       : {ticker_count}")
    print(f"  Date range    : {date_range[0]} → {date_range[1]}")
    print(f"  Database file : {DB_PATH}")

    if failed:
        print(f"\n  Failed tickers ({len(failed)}):")
        for ticker, err in failed:
            print(f"    {ticker}: {err}")

    conn.close()
    check_failure_threshold(failed, len(tickers))
    print("\nDone. Run compute_indicators.py next to refresh derived indicators.")


if __name__ == "__main__":
    main()
