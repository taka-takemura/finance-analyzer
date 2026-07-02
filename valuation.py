# -*- coding: utf-8 -*-
"""株価取得 (ベストエフォート) とバリュエーション計算。

Yahoo Finance (非公式API) → Stooq の順に試行。失敗時は None を返し、
アプリ側で手入力にフォールバックする。
"""
from __future__ import annotations

import io

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def fetch_price(code: str) -> dict | None:
    """証券コード4桁から現在株価を取得する。失敗時 None。"""
    code = str(code).strip()

    # --- 1) Yahoo Finance chart API (東証: {code}.T)
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.T",
            params={"range": "5d", "interval": "1d"},
            headers=HEADERS, timeout=10)
        if r.ok:
            meta = r.json()["chart"]["result"][0]["meta"]
            p = meta.get("regularMarketPrice") or meta.get("previousClose")
            if p and float(p) > 0:
                return {"price": float(p), "source": "Yahoo Finance",
                        "name": meta.get("shortName", "")}
    except Exception:
        pass

    # --- 2) Stooq CSV ({code}.jp)
    try:
        r = requests.get(
            "https://stooq.com/q/l/",
            params={"s": f"{code}.jp", "f": "sd2t2ohlcv", "h": "", "e": "csv"},
            headers=HEADERS, timeout=10)
        if r.ok and "," in r.text:
            df = pd.read_csv(io.StringIO(r.text))
            if "Close" in df.columns:
                c = pd.to_numeric(df.iloc[0]["Close"], errors="coerce")
                if pd.notna(c) and c > 0:
                    return {"price": float(c), "source": "Stooq", "name": ""}
    except Exception:
        pass

    return None


def compute(price: float, shares_mn: float, dps: float,
            net_income_mn: float, equity_mn: float) -> dict:
    """バリュエーション指標を計算する。

    price: 株価(円) / shares_mn: 発行済株式数(百万株) / dps: 1株配当(円)
    net_income_mn, equity_mn: 百万円
    """
    mcap_mn = price * shares_mn  # 円×百万株 = 百万円
    eps = net_income_mn / shares_mn if shares_mn else float("nan")
    bps = equity_mn / shares_mn if shares_mn else float("nan")
    return {
        "時価総額(百万円)": mcap_mn,
        "PER(倍)": mcap_mn / net_income_mn if net_income_mn > 0 else float("nan"),
        "PBR(倍)": mcap_mn / equity_mn if equity_mn > 0 else float("nan"),
        "EPS(円)": eps,
        "BPS(円)": bps,
        "配当利回り(%)": dps / price * 100 if price else float("nan"),
        "配当性向(%)": dps / eps * 100 if eps and eps > 0 else float("nan"),
    }
