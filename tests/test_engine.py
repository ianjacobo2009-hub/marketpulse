import numpy as np
import pandas as pd
import pytest

from marketpulse.engine import ASSETS, VIX, analyse, build_quotes
from marketpulse.summary import local_summary


@pytest.fixture(scope="module")
def frame():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range(end="2026-11-13", periods=260)
    cols = {}
    for t, _, g in ASSETS:
        vol = 0.04 if g == "crypto" else 0.012
        cols[t] = 100 * np.exp(np.cumsum(rng.normal(0.0003, vol, len(idx))))
    cols[VIX] = 15 + 5 * np.abs(np.sin(np.arange(len(idx)) / 20))
    df = pd.DataFrame(cols, index=idx)
    df.iloc[-1, df.columns.get_loc("SPY")] = df["SPY"].iloc[-2]          # one exactly flat asset
    df.iloc[-1, df.columns.get_loc("BTC-USD")] = df["BTC-USD"].iloc[-2] * 0.85   # a crash
    return df


def test_counts_add_up_and_no_duplicates(frame):
    q = build_quotes(frame)
    p = analyse(frame, q)
    assert p.gainers + p.losers + p.unchanged == len(ASSETS)
    assert len({x.ticker for x in p.quotes}) == len(p.quotes)
    assert p.unchanged >= 1


def test_sentiment_in_range(frame):
    p = analyse(frame, build_quotes(frame))
    assert 0 <= p.sentiment <= 100
    assert p.sentiment_label in {"Extreme fear", "Fear", "Neutral", "Greed", "Extreme greed"}


def test_crash_is_flagged(frame):
    p = analyse(frame, build_quotes(frame))
    btc = next(x for x in p.quotes if x.ticker == "BTC-USD")
    assert btc.z < -2
    outl = next(s for s in p.signals if s.key == "outliers")
    assert "Bitcoin" in outl.detail
    crypto = next(s for s in p.signals if s.key == "crypto")
    assert crypto.stance == "bearish"


def test_seven_signals_and_net(frame):
    p = analyse(frame, build_quotes(frame))
    assert len(p.signals) == 7
    assert p.net in {"NET BULLISH", "NET BEARISH", "MIXED"}


@pytest.mark.parametrize("lang", ["en", "es"])
def test_local_summary(frame, lang):
    p = analyse(frame, build_quotes(frame))
    s = local_summary(p, lang)
    assert str(p.sentiment) in s and "Bitcoin" in s
