# Local 1-Year Historical Backtest

This is a **local-machine version** of your 5-year GitHub Actions historical
backtest, refined to run 1 year of history with `python run_local_backtest.py`
on your own computer — no GitHub, no CI, no secrets needed.

It uses the **exact same strategy engine** as your live scanner
(`signal_engine.py` + `indicators.py` + `pivot_detection.py` + `config.py`) —
nothing about the Fibonacci/OTE logic, scoring weights, stop-loss/target
calculation, or fees/slippage model was changed. Only the *orchestration*
around it is new/fixed for local, 1-year use.

## What was fixed vs. the original 5-year `hist_backtester.py`

The original month-by-month engine restarted its swing-structure "memory"
(`swing_state`) at the start of every calendar month — carrying over only
`last_recorded_zone_price`, and only if a zone had already been recorded.
The live scanner never does this; it keeps one continuous state per
(coin, timeframe) forever. This mismatch could:
- **Miss zones entirely** — if a swing structure formed near the end of one
  month but only became a *confirmed* pivot a few candles into the next
  month, the new month's stricter "structure must be new" gate would reject
  it, even though nothing about the market changed.
- **Mis-detect swings** — with `swing_high`/`swing_low` wiped every month,
  the very first candles of each month could pick a different swing than
  the live system would have "remembered."

`local_backtester.py` replaces this with **one continuous candle-by-candle
replay per (coin, timeframe) across the full year** (mirroring
`scanner.py`'s `process_coin_timeframe()` state handling exactly). Months
are only used afterwards to *group* the resulting trades for reporting —
they never affect what gets detected. This was verified with a dedicated
regression test that reproduces the exact scenario above and confirms the
old approach drops the trade while the new one catches it.

## Folder layout

This folder must sit **next to** your existing project files — it imports
`signal_engine.py`, `config.py`, `indicators.py`, and `pivot_detection.py`
from the parent folder (same as the original `historical_backtest/` folder
did):

```
trading_scanner/
├── config.py                 ← used as-is, unchanged
├── indicators.py              ← used as-is, unchanged
├── pivot_detection.py         ← used as-is, unchanged
├── signal_engine.py           ← used as-is, unchanged
├── ...(your other live-system files, untouched)...
└── local_backtest/            ← this new folder
    ├── local_config.py
    ├── local_data_fetcher.py
    ├── local_backtester.py
    ├── local_reporter.py
    ├── run_local_backtest.py
    ├── requirements.txt
    ├── .env.example
    └── output/                ← created automatically on first run
```

**Important:** `signal_engine.py` and `pivot_detection.py` both do
`import config` internally — they always read strategy parameters
(`TF_SETTINGS`, `CONFLUENCE_WEIGHTS`, `MIN_RR`, `STOP_LOSS_ATR_MULT`, etc.)
from `config.py` in the parent folder, **not** from `local_config.py`. So if
you ever want to tune the strategy itself, edit `config.py` — editing
`local_config.py` only changes which coins/dates/output-location the local
backtest uses, not how signals are generated.

## Step-by-step setup (Windows / Mac / Linux)

### 1. Install Python
You need Python 3.10 or newer. Check with:
```bash
python3 --version
```
If you don't have it, download from https://www.python.org/downloads/
(Windows users: tick "Add Python to PATH" during install.)

### 2. Get the files onto your machine
Put all your existing files (`config.py`, `signal_engine.py`,
`indicators.py`, `pivot_detection.py`, etc.) in one folder, e.g.
`trading_scanner/`, and put this `local_backtest/` folder inside it, exactly
as shown in the layout above.

### 3. Create a virtual environment (recommended, keeps things clean)
```bash
cd trading_scanner
python3 -m venv venv
```
Activate it:
- **Mac/Linux:** `source venv/bin/activate`
- **Windows (cmd):** `venv\Scripts\activate.bat`
- **Windows (PowerShell):** `venv\Scripts\Activate.ps1`

You'll know it worked because your terminal prompt now starts with `(venv)`.

### 4. Install dependencies
```bash
cd local_backtest
pip install -r requirements.txt
```
This installs `ccxt` (exchange connectivity), `pandas`/`numpy` (data
processing), and `python-dotenv` (optional `.env` file support).

### 5. (Optional) Configure settings
```bash
cp .env.example .env      # Windows: copy .env.example .env
```
Open `.env` in any text editor. Everything is optional:
- `BACKTEST_DAYS=365` — change this if you want e.g. 180 days instead of a
  full year.
- Leave `SEND_EMAIL=false` unless you want an email sent when it's done —
  the full report is always saved locally either way.
- If you *do* want email, fill in `SMTP_USER`/`SMTP_PASSWORD` (for Gmail,
  use an **App Password**, not your normal password) and
  `REPORT_EMAIL_TO`, then set `SEND_EMAIL=true`.

If you skip this step entirely, it still runs fine with sensible defaults
(365 days, no email).

### 6. Run it
```bash
python run_local_backtest.py
```
You'll see live progress in the terminal as it:
1. Finds a working exchange (tries kucoin, okx, bybit, gate, mexc, binance
   in order — same fallback logic as your live system).
2. Downloads a year+ of 4h/1h candles for each of the 20 coins (this is the
   slow part — expect anywhere from ~10 minutes to over an hour depending
   on your connection and how many coins/timeframes you keep in
   `local_config.py`).
3. Replays the strategy candle-by-candle for each coin/timeframe.
4. Writes your results to `local_backtest/output/`.

### 7. Check your results
Inside `local_backtest/output/` you'll find:
- **`backtest_report.txt`** — full readable report: overall 1-year summary
  (win rate, net P&L in R, profit factor, max drawdown, streaks), then a
  month-by-month breakdown with day-by-day tables, best/worst trades, and
  market condition per month.
- **`backtest_zones.csv`** — every single trade as one row (coin,
  timeframe, entry/stop/target, score, R:R, status, timestamps) — open this
  directly in Excel/Google Sheets for your own pivot tables/charts.
- **`local_backtest.log`** — full run log, useful if something errors out
  partway through (data-gap coins are also summarized at the end of the
  console output).

## Tips for a faster local run

- **Trim the coin list.** Open `local_config.py` and shorten
  `COIN_UNIVERSE` to just the coins you actually care about — 5 coins runs
  roughly 4x faster than 20.
- **Drop the 1h timeframe.** Set `TIMEFRAMES = ["4h"]` in `local_config.py`
  if you only want the 4h signals — 1h has ~4x more candles to replay per
  coin.
- **Re-runs are independent.** Each run re-downloads fresh data and starts
  clean — there's no local database to reset or worry about (unlike the
  live scanner's `trading_system.db`).

## Troubleshooting

- **"Koi bhi exchange... accessible nahi"** — your network/VPN is blocking
  every exchange in the priority list. Try a different network, or check if
  a firewall/antivirus is blocking outbound HTTPS.
- **A specific coin shows 0 candles / fetch errors** — some smaller
  exchanges don't have a full year of history for every coin/timeframe;
  this is logged as a data gap and that coin/timeframe is simply skipped
  for that period, the run continues normally.
- **It's very slow** — see "Tips for a faster local run" above. Downloading
  is the bottleneck, not the strategy replay itself.
