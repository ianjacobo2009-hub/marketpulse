"""Market Pulse engine: prices, breadth, sentiment and quantitative signals.

Prices and news come from Yahoo Finance (no API key). Every number is computed from a year of daily closes, so the
signals compare today with each asset's own history instead of using fixed thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ASSETS = [
    # ticker,   name,                 group
    ("SPY",     "S&P 500",            "index"),
    ("QQQ",     "Nasdaq 100",         "index"),
    ("DIA",     "Dow Jones",          "index"),
    ("BTC-USD", "Bitcoin",            "crypto"),
    ("ETH-USD", "Ethereum",           "crypto"),
    ("NVDA",    "Nvidia",             "tech"),
    ("AAPL",    "Apple",              "tech"),
    ("MSFT",    "Microsoft",          "tech"),
    ("GOOGL",   "Alphabet",           "tech"),
    ("AMZN",    "Amazon",             "tech"),
    ("META",    "Meta",               "tech"),
    ("TSLA",    "Tesla",              "tech"),
    ("NFLX",    "Netflix",            "consumer"),
    ("DIS",     "Disney",             "consumer"),
    ("WMT",     "Walmart",            "defensive"),
    ("JNJ",     "Johnson & Johnson",  "defensive"),
    ("JPM",     "JPMorgan",           "financials"),
    ("GS",      "Goldman Sachs",      "financials"),
    ("V",       "Visa",               "financials"),
    ("XOM",     "Exxon",              "energy"),
]
VIX = "^VIX"
FLAT = 0.0005          # moves smaller than ±0.05% count as unchanged


@dataclass
class Quote:
    ticker: str
    name: str
    group: str
    price: float
    change: float          # last session, fraction
    change_5d: float
    change_1m: float
    vol_20d: float         # annualised realised volatility
    z: float               # today's move in units of its own 60-day daily volatility
    spark: list            # last 30 closes


@dataclass
class SignalResult:
    key: str
    title: str
    stance: str            # bullish / bearish / neutral
    detail: str


@dataclass
class Pulse:
    asof: datetime
    quotes: list
    gainers: int
    losers: int
    unchanged: int
    avg_change: float
    sentiment: int                     # 0 fear ... 100 greed
    sentiment_label: str
    sentiment_parts: dict
    vix: float | None
    vix_pct: float | None              # percentile of today's VIX in the last year
    signals: list
    net: str                           # NET BULLISH / NET BEARISH / MIXED
    stats: dict
    news: list = field(default_factory=list)


def _price_frame(period="1y") -> pd.DataFrame:
    import yfinance as yf
    tickers = [a[0] for a in ASSETS] + [VIX]
    df = yf.download(tickers, period=period, interval="1d", progress=False, auto_adjust=True, threads=True)["Close"]
    if df.empty:
        raise RuntimeError("Yahoo Finance returned no prices. Check the internet connection.")
    return df


def _series(df, t) -> pd.Series:
    return df[t].dropna() if t in df else pd.Series(dtype=float)


def build_quotes(df: pd.DataFrame) -> list[Quote]:
    out = []
    for t, name, group in ASSETS:
        s = _series(df, t)
        if len(s) < 25:
            continue
        r = np.log(s).diff().dropna()
        sd = r.iloc[-61:-1].std() or 1e-9
        ch = s.iloc[-1] / s.iloc[-2] - 1
        ann = 365 if group == "crypto" else 252
        out.append(Quote(t, name, group, float(s.iloc[-1]), float(ch),
                         float(s.iloc[-1] / s.iloc[-6] - 1), float(s.iloc[-1] / s.iloc[-22] - 1),
                         float(r.iloc[-20:].std() * np.sqrt(ann)), float(np.log1p(ch) / sd),
                         [float(x) for x in s.iloc[-30:]]))
    return out


def _avg(qs, groups):
    v = [q.change for q in qs if q.group in groups]
    return float(np.mean(v)) if v else 0.0


def analyse(df: pd.DataFrame, quotes: list[Quote]) -> Pulse:
    ch = np.array([q.change for q in quotes])
    gain = int((ch > FLAT).sum()); lose = int((ch < -FLAT).sum()); flat = len(ch) - gain - lose
    spy = _series(df, "SPY"); vix = _series(df, VIX)
    r_spy = np.log(spy).diff().dropna()

    # ---- sentiment (0-100), average of four parts that each map to 0-100
    parts = {}
    parts["Breadth"] = 100 * gain / max(1, gain + lose)
    z_spy = float(r_spy.iloc[-1] / (r_spy.iloc[-61:-1].std() or 1e-9))
    parts["S&P 500 move vs normal"] = float(100 / (1 + np.exp(-1.2 * z_spy)))
    ma50 = spy.iloc[-50:].mean()
    parts["Trend (vs 50-day average)"] = float(np.clip(50 + 50 * (spy.iloc[-1] / ma50 - 1) / 0.05, 0, 100))
    vix_now = vix_pct = None
    if len(vix) > 30:
        vix_now = float(vix.iloc[-1]); vix_pct = float((vix.iloc[-252:] < vix_now).mean())
        parts["Fear gauge (VIX, inverted)"] = 100 * (1 - vix_pct)
    score = int(round(np.mean(list(parts.values()))))
    label = ("Extreme fear" if score < 20 else "Fear" if score < 40 else "Neutral" if score <= 60
             else "Greed" if score <= 80 else "Extreme greed")

    sig = []
    # 1 risk appetite: financials vs defensives
    fin, dfn = _avg(quotes, {"financials"}), _avg(quotes, {"defensive"})
    gap = fin - dfn
    st = "bullish" if gap > 0.003 else "bearish" if gap < -0.003 else "neutral"
    sig.append(SignalResult("risk", "Risk appetite", st,
               f"Financials {fin:+.2%} vs defensives {dfn:+.2%}. "
               + ("Money is moving into risk." if st == "bullish" else "Investors are playing it safe." if st == "bearish"
                  else "No clear preference.")))
    # 2 dispersion vs its own history
    rets = pd.DataFrame({q.ticker: np.log(_series(df, q.ticker)).diff() for q in quotes if q.group != "crypto"}).dropna(how="all")
    disp = rets.std(axis=1).dropna()
    d_now = float(disp.iloc[-1]); d_avg = float(disp.iloc[-61:-1].mean())
    st = "neutral"
    sig.append(SignalResult("dispersion", "Dispersion", st,
               f"Stocks spread {d_now:.2%} apart today vs {d_avg:.2%} normally. "
               + ("High: company news is driving prices, a stock-picker's day." if d_now > 1.3 * d_avg
                  else "Low: stocks are moving together, macro is in charge." if d_now < 0.8 * d_avg
                  else "Normal spread.")))
    # 3 volatility
    rv = float(r_spy.iloc[-20:].std() * np.sqrt(252)); rv_1y = float(r_spy.iloc[-252:].std() * np.sqrt(252))
    if vix_now is not None:
        st = "bearish" if vix_pct > 0.8 else "bullish" if vix_pct < 0.3 else "neutral"
        txt = f"VIX {vix_now:.1f}, higher than {vix_pct:.0%} of the past year. S&P 500 realised vol {rv:.1%} (1-year {rv_1y:.1%})."
    else:
        st = "bearish" if rv > 1.3 * rv_1y else "bullish" if rv < 0.8 * rv_1y else "neutral"
        txt = f"S&P 500 realised vol {rv:.1%} vs {rv_1y:.1%} over the year."
    sig.append(SignalResult("vol", "Volatility", st, txt))
    # 4 outliers
    outl = sorted([q for q in quotes if abs(q.z) >= 2], key=lambda q: -abs(q.z))
    if outl:
        neg = sum(q.z < 0 for q in outl)
        st = "bearish" if neg > len(outl) / 2 else "bullish" if neg < len(outl) / 2 else "neutral"
        txt = "Unusual moves: " + ", ".join(f"{q.name} {q.change:+.1%} ({q.z:+.1f}σ)" for q in outl[:4]) + "."
    else:
        st, txt = "neutral", "No asset moved more than 2 standard deviations from its normal day."
    sig.append(SignalResult("outliers", "Unusual moves", st, txt))
    # 5 tech leadership
    tech = _avg(quotes, {"tech"}); spy_ch = next((q.change for q in quotes if q.ticker == "SPY"), 0.0)
    lead = tech - spy_ch
    st = "bullish" if lead > 0.003 and tech > 0 else "bearish" if lead < -0.003 and tech < 0 else "neutral"
    sig.append(SignalResult("tech", "Tech leadership", st,
               f"Big tech {tech:+.2%} vs S&P 500 {spy_ch:+.2%} ({lead:+.2%}). "
               + ("Growth stocks are leading." if lead > 0.003 else "Growth stocks are lagging." if lead < -0.003 else "In line with the market.")))
    # 6 crypto and equities
    btc = _series(df, "BTC-USD")
    both = pd.concat([np.log(btc).diff(), r_spy], axis=1, keys=["btc", "spy"]).dropna().iloc[-60:]
    corr = float(both.corr().iloc[0, 1]) if len(both) > 20 else float("nan")
    cry = _avg(quotes, {"crypto"})
    st = "bearish" if cry < -0.03 else "bullish" if cry > 0.03 else "neutral"
    sig.append(SignalResult("crypto", "Crypto", st,
               f"Bitcoin/Ether {cry:+.2%} today. 60-day correlation of Bitcoin with the S&P 500: {corr:+.2f} "
               + ("(they move together, so crypto is a risk-mood signal)." if corr > 0.3 else "(weakly linked to stocks).")))
    # 7 trend
    ma200 = spy.iloc[-200:].mean()
    above50, above200 = spy.iloc[-1] > ma50, spy.iloc[-1] > ma200
    st = "bullish" if above50 and above200 else "bearish" if not above50 and not above200 else "neutral"
    sig.append(SignalResult("trend", "Trend", st,
               f"S&P 500 is {spy.iloc[-1] / ma50 - 1:+.1%} from its 50-day and {spy.iloc[-1] / ma200 - 1:+.1%} from its 200-day average."))

    b = sum(s.stance == "bullish" for s in sig); br = sum(s.stance == "bearish" for s in sig)
    net = "NET BULLISH" if b > br else "NET BEARISH" if br > b else "MIXED"
    stats = {"avg_change": float(ch.mean()), "advance_decline": gain / max(1, lose), "spy_realised_vol": rv,
             "dispersion": d_now, "bullish": b, "bearish": br, "neutral": len(sig) - b - br}
    last = max(_series(df, q.ticker).index[-1] for q in quotes)
    return Pulse(last.to_pydatetime(), quotes, gain, lose, flat, float(ch.mean()), score, label, parts, vix_now,
                 vix_pct, sig, net, stats)


def fetch_news(limit=8) -> list[dict]:
    import yfinance as yf
    seen, items = set(), []
    for t in ("SPY", "QQQ", "NVDA", "BTC-USD", "JPM", "AAPL"):
        try:
            for n in yf.Ticker(t).news or []:
                c = n.get("content", n)
                title = c.get("title")
                if not title or title in seen:
                    continue
                seen.add(title)
                prov = (c.get("provider") or {}).get("displayName") or c.get("publisher") or "Yahoo Finance"
                url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
                       or c.get("link") or "")
                when = c.get("pubDate") or c.get("displayTime") or ""
                items.append({"title": title, "source": prov, "url": url, "summary": (c.get("summary") or "")[:280],
                              "time": when})
        except Exception:
            continue
    items.sort(key=lambda x: x["time"], reverse=True)
    return items[:limit]


def get_pulse() -> Pulse:
    df = _price_frame()
    p = analyse(df, build_quotes(df))
    p.news = fetch_news()
    return p
