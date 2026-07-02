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


def fetch_price(code: str) -> tuple[dict | None, list[str]]:
    """証券コード4桁から現在株価を取得する。(結果, 診断ログ) を返す。"""
    code = str(code).strip()
    log: list[str] = []

    # --- 1) Yahoo Finance chart API (東証: {code}.T)
    for host in ("query1", "query2"):
        try:
            sess = requests.Session()
            sess.headers.update(HEADERS)
            r = sess.get(
                f"https://{host}.finance.yahoo.com/v8/finance/chart/{code}.T",
                params={"range": "5d", "interval": "1d"}, timeout=10)
            if r.ok:
                result = (r.json().get("chart") or {}).get("result")
                if result:
                    meta = result[0].get("meta", {})
                    p = meta.get("regularMarketPrice") or meta.get("previousClose")
                    if p and float(p) > 0:
                        return {"price": float(p), "source": "Yahoo Finance",
                                "name": meta.get("shortName", "")}, log
                log.append(f"Yahoo({host}): 応答に価格なし")
            else:
                log.append(f"Yahoo({host}): HTTP {r.status_code}"
                           + (" (クラウドIPのブロックの可能性)" if r.status_code in (401, 403, 429) else ""))
        except requests.RequestException as e:
            log.append(f"Yahoo({host}): {type(e).__name__}")

    # --- 2) Stooq CSV ({code}.jp)
    try:
        r = requests.get(
            "https://stooq.com/q/l/",
            params={"s": f"{code}.jp", "f": "sd2t2ohlcv", "h": "", "e": "csv"},
            headers=HEADERS, timeout=10)
        if r.ok and "," in r.text and "N/D" not in r.text:
            df = pd.read_csv(io.StringIO(r.text))
            if "Close" in df.columns:
                c = pd.to_numeric(df.iloc[0]["Close"], errors="coerce")
                if pd.notna(c) and c > 0:
                    return {"price": float(c), "source": "Stooq", "name": ""}, log
        log.append(f"Stooq: HTTP {r.status_code}, 応答: {r.text[:60]!r}")
    except requests.RequestException as e:
        log.append(f"Stooq: {type(e).__name__}")

    return None, log


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
