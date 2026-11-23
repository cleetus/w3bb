"""Pretend portfolio: $10 into every w3bb pick on every trading day, starting 2026-11-23.

For comparison, the same dollars go into the S&P 500 (SPY) on the same day, the way
Buffett tells most people to invest. Results go to results/portfolio.json for the site.

Rules:
- One round of buys per trading day (re-runs and market holidays don't buy twice).
- Bought at that day's closing price; fractional shares are fine.
- Stock splits are handled. Dividends are not counted (for either side).
"""
import datetime as dt
import json

import pandas as pd
import yfinance as yf

DOLLARS = 10
BENCH = "SPY"


def _download(tickers, start):
    df = yf.download(sorted(tickers), start=str(start - dt.timedelta(days=7)), interval="1d",
                     auto_adjust=False, actions=True, progress=False, threads=True)
    if not isinstance(df.columns, pd.MultiIndex):  # single ticker comes back flat
        df.columns = pd.MultiIndex.from_product([df.columns, sorted(tickers)])
    return df


def _value(lot, close, splits):
    """Today's value of one buy: shares x (any splits since) x latest price."""
    s = close[lot["ticker"]].dropna() if lot["ticker"] in close else pd.Series(dtype=float)
    price = float(s.iloc[-1]) if len(s) else lot["price"]  # no quote (e.g. delisted): last known
    factor = 1.0
    if lot["ticker"] in splits:
        sp = splits[lot["ticker"]]
        for ratio in sp[(sp.index.date > dt.date.fromisoformat(lot["date"])) & (sp > 0)]:
            factor *= float(ratio)
    return lot["shares"] * factor * price, price


def update(results, market_date, path, log=print):
    pf = json.loads(path.read_text()) if path.exists() else {
        "start": None, "dollars_per_pick": DOLLARS, "benchmark": BENCH, "buys": [], "bench_buys": [], "history": []}
    picks = [(screen, p) for screen, ps in results.items() for p in ps]
    already = market_date is None or str(market_date) in {b["date"] for b in pf["buys"] + pf["bench_buys"]}

    tickers = {b["ticker"] for b in pf["buys"]} | {p["ticker"] for _, p in picks} | {BENCH}
    first = min([dt.date.fromisoformat(b["date"]) for b in pf["buys"]] + [market_date or dt.date.today()])
    df = _download(tickers, first)
    close, splits = df["Close"], df["Stock Splits"]

    if not already and picks:
        for screen, p in picks:
            pf["buys"].append({"date": str(market_date), "ticker": p["ticker"], "name": p["name"], "screen": screen,
                               "price": p["price"], "dollars": DOLLARS, "shares": DOLLARS / p["price"]})
        spy = close[BENCH].dropna()
        spy_price = float(spy[spy.index.date <= market_date].iloc[-1])
        total = DOLLARS * len(picks)
        pf["bench_buys"].append({"date": str(market_date), "ticker": BENCH, "price": round(spy_price, 2),
                                 "dollars": total, "shares": total / spy_price})
        pf["start"] = pf["start"] or str(market_date)
        log(f"  bought ${total} of picks ({len(picks)} x ${DOLLARS}) and ${total} of {BENCH} on {market_date}")
    elif already:
        log(f"  already bought for {market_date}; just updating values")

    # Value every holding at the latest price.
    holdings = {}
    for lot in pf["buys"]:
        v, price = _value(lot, close, splits)
        h = holdings.setdefault(lot["ticker"], {"ticker": lot["ticker"], "name": lot["name"], "buys": 0,
                                                "invested": 0.0, "value": 0.0, "first_bought": lot["date"]})
        h["buys"] += 1
        h["invested"] += lot["dollars"]
        h["value"] += v
        h["price"] = round(price, 2)
    for h in holdings.values():
        h["gain_pct"] = round((h["value"] / h["invested"] - 1) * 100, 1)
        h["invested"], h["value"] = round(h["invested"], 2), round(h["value"], 2)
    bench_value = sum(_value(lot, close, splits)[0] for lot in pf["bench_buys"])

    priced_on = close.dropna(how="all").index[-1].date()
    invested = sum(b["dollars"] for b in pf["buys"])
    value = sum(h["value"] for h in holdings.values())
    if invested:
        pf["history"] = [h for h in pf["history"] if h["date"] != str(priced_on)]
        pf["history"].append({"date": str(priced_on), "invested": round(invested, 2), "value": round(value, 2),
                              "bench_value": round(bench_value, 2)})
        pf["history"].sort(key=lambda h: h["date"])
    pf["holdings"] = sorted(holdings.values(), key=lambda h: -h["value"])
    pf["updated"] = str(priced_on)
    path.write_text(json.dumps(pf, indent=1))
    return pf
