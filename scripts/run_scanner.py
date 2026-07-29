"""
run_scanner.py — Print today's screener list to the terminal

"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from screener_lib import STRATEGY_PARAMS, default_params, get_connection, get_latest_date, get_todays_screener


def main() -> None:
    conn = get_connection()
    latest_date = get_latest_date(conn)
    print(f"Screener results for {latest_date}\n")

    for strategy in STRATEGY_PARAMS:
        params = default_params(strategy)
        df = get_todays_screener(conn, strategy, params)
        print(f"── {strategy} ({params}) — {len(df)} stocks ──")
        if not df.empty:
            print(df.to_string(index=False))
        print()

    conn.close()


if __name__ == "__main__":
    main()
