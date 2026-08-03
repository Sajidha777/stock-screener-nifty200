# Nifty 200 Swing Screener

A daily stock screener for the Nifty 200 universe, backtester to follow. 
[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://stock-screener-nifty200.streamlit.app/)

## Features

- **5 screener strategies**, each with adjustable parameters via sliders:
  - **Near 52-Week Low / Near 52-Week High** — simple proximity-to-range filters
  - **Oversold Recovery** — RSI recovering off a low, well below its 200-day average.
  - **Momentum Entry** — RSI in a specific range with price crossing above its 50-day average, confirmed by volume
  - **Pullback** — a short-term dip within a broader uptrend
- **Leading Sectors** — industries ranked by average return over a selectable lookback window, with drill-down into each sector's individual stocks
- **Candlestick Charts** 

## Tech stack

- **DuckDB** — embedded analytical database for OHLCV and indicator data
- **pandas / pandas-ta** — indicator computation (RSI, SMA, MACD, etc.)
- **Streamlit** — the dashboard
- **yfinance** — data source
- **GitHub Actions** — daily data refresh

## Running it locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# One-time: pull 2 years of history and compute indicators
.venv/bin/python scripts/load_historical.py
.venv/bin/python scripts/compute_indicators.py

# Launch the dashboard
.venv/bin/streamlit run app.py
```

To pick up the latest data pulled by the daily pipeline instead of your own local copy:

```bash
git pull
.venv/bin/streamlit run app.py
```
