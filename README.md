# w3bb — What Would Warren Buffett Buy?

Say it "dub-3-b-b". A daily Buffett-style stock screen over every US-listed stock.

**See today's picks:** https://cleetus.github.io/w3bb/

## Screen: Beaten-down bargains

Solid, cheap, cash-rich companies that bad news knocked down:

1. P/E between 0 and 15
2. At least 10 years of SEC filings
3. Profitable in at least 8 of the last 10 years, including 2020
4. More cash than debt
5. Price down at least 25% from 52 weeks ago
6. Company worth at least $300 million

The rules live in `screens.json`, and the prompts for digging into the picks live in `prompts/`.

## Pretend portfolio

What if you put $10 into every pick on every trading day, starting 2026-11-23? `portfolio.py` keeps score in `results/portfolio.json`:

- Each pick is bought at that day's closing price, once per trading day (holidays and re-runs don't buy twice).
- The same dollars go into the S&P 500 (SPY) as the yardstick.
- Stock splits are counted; dividends aren't, for either side.

The site shows money put in, what it's worth now, gain or loss over time vs the S&P 500, and every stock owned.

## How it works

`w3bb.py` uses only free data:

1. The **SEC frames API** gives yearly profits for every US filer.
2. The **SEC submissions API** gives tickers for the companies that pass.
3. **Yahoo Finance** (via yfinance) gives prices, P/E, market value, cash and debt.

It writes `results/YYYY-MM-DD.json` + `.md`, and `index.html` shows them. `run-daily.ps1` runs the screen on weekday mornings and pushes the results, which updates the site.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python w3bb.py
```

*A shortlist to research, not financial advice.*
