"""w3bb ("dub-3-b-b") — What Would Warren Buffett Buy?

Daily stock screen over all US-listed stocks, using free data:
  1. SEC "frames" API: 10 years of yearly profits for every US filer (a few big downloads)
  2. SEC submissions API: ticker + exchange for the companies that pass step 1 (cached)
  3. Yahoo Finance (yfinance): 1-year prices, then P/E, market cap, cash and debt

Writes results/YYYY-MM-DD.md + .json and results/latest.json.
Usage:  python w3bb.py [screen-name]      (default: every screen in screens.json)
Not financial advice: the output is a shortlist to research.
"""
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
RESULTS = ROOT / "results"
CONFIG = ROOT / "config.json"  # git-ignored; optional {"sec_user_agent": "..."}

US_EXCHANGES = {"NYSE", "Nasdaq", "NYSE American", "NYSE Arca", "CBOE", "BATS"}
PROFIT_TAGS = ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def sec_session():
    ua = "w3bb stock screener (personal use)"
    if CONFIG.exists():
        ua = json.loads(CONFIG.read_text()).get("sec_user_agent", ua)
    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    return s


def cached_json(session, url, path, max_age_days):
    """Download url to cache/path unless a fresh enough copy exists."""
    path = CACHE / path
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400:
        return json.loads(path.read_text())
    for attempt in range(3):
        r = session.get(url, timeout=60)
        if r.status_code == 404:
            return None
        if r.ok:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(r.text)
            time.sleep(0.12)  # SEC asks for <= 10 requests/second
            return r.json()
        time.sleep(2 * (attempt + 1))
    r.raise_for_status()


def last_full_year(today):
    # A calendar year's annual reports are mostly filed by the end of March.
    return today.year - 1 if today.month >= 4 else today.year - 2


def yearly_profits(session, years):
    """{cik: {"name": str, "profits": {year: value}}} from SEC frames."""
    out = {}
    for year in years:
        # Old years never change; refresh the most recent two each week.
        age = 7 if year >= years[-1] - 1 else 365
        for tag in PROFIT_TAGS:
            data = cached_json(session, f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/CY{year}.json",
                               f"frames/{tag}-CY{year}.json", age)
            for row in (data or {}).get("data", []):
                c = out.setdefault(row["cik"], {"name": row["entityName"], "profits": {}})
                c["profits"].setdefault(year, row["val"])  # first tag in PROFIT_TAGS wins
    return out


def history_filter(companies, years, screen):
    keep = {}
    for cik, c in companies.items():
        p = c["profits"]
        if len(p) < screen["years_of_history"] - 1:  # allow one missing year in the data
            continue
        if sum(1 for y in years if p.get(y, 0) > 0) < screen["min_profitable_years"]:
            continue
        if any(p.get(y, 0) <= 0 for y in screen["must_be_profitable_in"]):
            continue
        if p.get(years[-1], 0) <= 0:  # must still be making money last year
            continue
        keep[cik] = c
    return keep


def tickers_for(session, ciks):
    """{cik: (ticker, exchange)} for US-exchange listings, via SEC submissions (cached 30 days)."""
    out = {}
    for i, cik in enumerate(ciks, 1):
        sub = cached_json(session, f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                          f"submissions/{cik}.json", 30)
        if i % 200 == 0:
            log(f"  tickers {i}/{len(ciks)}")
        if not sub:
            continue
        for t, ex in zip(sub.get("tickers", []), sub.get("exchanges", [])):
            if ex in US_EXCHANGES and t:
                out[cik] = (t.replace(".", "-"), ex)  # Yahoo writes BRK.B as BRK-B
                break
    return out


MARKET_DATE = None


def price_drops(tickers, min_drop):
    """{ticker: (price_now, price_52w_ago, drop_pct)} for stocks down at least min_drop %."""
    out = {}
    tickers = sorted(set(tickers))
    for i in range(0, len(tickers), 200):
        batch = tickers[i:i + 200]
        df = yf.download(batch, period="13mo", interval="1d", auto_adjust=True,
                         progress=False, threads=True, group_by="column")["Close"]
        if isinstance(df, pd.Series):
            df = df.to_frame(batch[0])
        global MARKET_DATE  # the trading day these prices are from (the pretend buys use it)
        MARKET_DATE = max(MARKET_DATE or df.index[-1], df.index[-1])
        cutoff = df.index[-1] - pd.Timedelta(days=365)
        for t in df.columns:
            s = df[t].dropna()
            if len(s) < 200:
                continue
            old = s[s.index <= cutoff]
            if old.empty:
                continue
            now, then = float(s.iloc[-1]), float(old.iloc[-1])
            drop = (then - now) / then * 100
            if drop >= min_drop:
                out[t] = (now, then, drop)
    return out


_FX = {"USD": 1.0}


def fx_to_usd(cur):
    if cur not in _FX:
        try:
            _FX[cur] = float(yf.Ticker(f"{cur}USD=X").history(period="5d")["Close"].dropna().iloc[-1])
        except Exception:
            _FX[cur] = float("nan")  # unknown currency: comparisons fail, stock is skipped
    return _FX[cur]


def run_screen(name, screen, today):
    session = sec_session()
    end = last_full_year(today)
    years = list(range(end - screen["years_of_history"] + 1, end + 1))
    log(f"{screen['title']}: profits {years[0]}-{years[-1]} from SEC")
    companies = yearly_profits(session, years)
    steady = history_filter(companies, years, screen)
    log(f"  {len(companies)} companies -> {len(steady)} with a long, profitable history")

    tick = tickers_for(session, list(steady))
    log(f"  {len(tick)} trade on a US exchange")
    by_ticker = {t: cik for cik, (t, _) in tick.items()}

    drops = price_drops(by_ticker, screen["min_drop_52w_pct"])
    log(f"  {len(drops)} are down {screen['min_drop_52w_pct']}%+ from a year ago")

    picks = []
    for t, (now, then, drop) in drops.items():
        try:
            info = yf.Ticker(t).info
        except Exception as e:  # Yahoo hiccup: skip this one
            log(f"  skip {t}: {e}")
            continue
        pe = info.get("trailingPE")
        cap = info.get("marketCap") or 0
        # Cash/debt come in the company's reporting currency (e.g. yuan); market cap is in dollars.
        rate = fx_to_usd(info.get("financialCurrency") or "USD")
        cash = (info.get("totalCash") or 0) * rate
        debt = (info.get("totalDebt") or 0) * rate
        if not pe or not (0 < pe <= screen["max_pe"]):
            continue
        if cap < screen["min_market_cap"]:
            continue
        pct = screen.get("min_cash_pct_of_cap")  # null = cash must beat debt, no exceptions
        if not (cash > debt or (pct and cash >= cap * pct / 100)):
            continue
        cik = by_ticker[t]
        p = steady[cik]["profits"]
        picks.append({
            "ticker": t, "name": info.get("longName") or steady[cik]["name"],
            "sector": info.get("sector"), "industry": info.get("industry"),
            "price": round(now, 2), "price_52w_ago": round(then, 2), "drop_pct": round(drop, 1),
            "pe": round(pe, 1), "market_cap": cap, "cash": cash, "debt": debt,
            "profitable_years": sum(1 for y in years if p.get(y, 0) > 0), "years_checked": len(years),
        })
    picks.sort(key=lambda x: -x["drop_pct"])
    log(f"  {len(picks)} picks")
    return picks


def money(x):
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(x) >= size:
            return f"${x / size:.1f}{unit}"
    return f"${x:,.0f}"


def write_report(today, results):
    RESULTS.mkdir(exist_ok=True)
    screens = json.loads((ROOT / "screens.json").read_text())
    lines = [f"# w3bb — What Would Warren Buffett Buy? ({today:%a %b %d, %Y})", "",
             "_A shortlist to research, not financial advice. Prices are the last market close._", ""]
    for name, picks in results.items():
        s = screens[name]
        lines += [f"## {s['title']} — {len(picks)} picks", "", s["why"], ""]
        if picks:
            lines += ["| # | Stock | Down 1 yr | P/E | Value | Cash | Debt | Profitable yrs | Sector |",
                      "|---|---|---|---|---|---|---|---|---|"]
            for i, p in enumerate(picks, 1):
                lines.append(f"| {i} | **{p['ticker']}** {p['name']} | -{p['drop_pct']}% | {p['pe']} | "
                             f"{money(p['market_cap'])} | {money(p['cash'])} | {money(p['debt'])} | "
                             f"{p['profitable_years']}/{p['years_checked']} | {p['sector'] or ''} |")
            prompt = (ROOT / s["prompt"]).read_text().split("## Ask about today's picks", 1)[-1].strip()
            top = ", ".join(p["ticker"] for p in picks[:5])
            lines += ["", "**Paste into Claude to dig in:**", "", "> " + prompt.replace("{TICKERS}", top).replace("\n", "\n> "), ""]
        else:
            lines += ["Nothing passed every rule today.", ""]
    md = "\n".join(lines)
    (RESULTS / f"{today}.md").write_text(md, encoding="utf-8")
    info = {}
    for name in results:
        s = screens[name]
        text = (ROOT / s["prompt"]).read_text(encoding="utf-8")
        find = text.split("## Find your own (paste into Claude or ChatGPT)", 1)[-1].split("## Ask about today's picks")[0]
        info[name] = {"title": s["title"], "why": s["why"], "rules": rules_text(s),
                      "find_prompt": find.strip(),
                      "picks_prompt": text.split("## Ask about today's picks", 1)[-1].strip()}
    data = {"date": str(today), "screens": results, "info": info}
    (RESULTS / f"{today}.json").write_text(json.dumps(data, indent=2))
    (RESULTS / "latest.json").write_text(json.dumps(data, indent=2))
    (RESULTS / "latest.md").write_text(md, encoding="utf-8")
    # The web page reads this list to offer past days.
    dates = sorted((p.stem for p in RESULTS.glob("20??-??-??.json")), reverse=True)
    (RESULTS / "index.json").write_text(json.dumps(dates))
    return md


def rules_text(s):
    cash = "More cash than debt"
    if s.get("min_cash_pct_of_cap"):
        cash += f", or cash at least {s['min_cash_pct_of_cap']}% of the company's value"
    return [
        f"P/E between 0 and {s['max_pe']} (real profits, cheap price)",
        f"At least {s['years_of_history']} years of SEC filings",
        f"Profitable in at least {s['min_profitable_years']} of the last {s['years_of_history']} years, "
        f"including {', '.join(map(str, s['must_be_profitable_in']))}",
        cash,
        f"Price down at least {s['min_drop_52w_pct']}% from 52 weeks ago",
        f"Company worth at least {money(s['min_market_cap'])}",
    ]


def main():
    today = dt.date.today()
    screens = json.loads((ROOT / "screens.json").read_text())
    names = sys.argv[1:] or list(screens)
    results = {n: run_screen(n, screens[n], today) for n in names}
    write_report(today, results)
    log(f"wrote {RESULTS / f'{today}.md'}")
    import portfolio
    pf = portfolio.update(results, MARKET_DATE.date() if MARKET_DATE is not None else None,
                          RESULTS / "portfolio.json", log)
    h = pf["history"][-1] if pf["history"] else None
    if h:
        log(f"portfolio: ${h['invested']:,.2f} in, worth ${h['value']:,.2f} (S&P 500 would be ${h['bench_value']:,.2f})")


if __name__ == "__main__":
    main()
