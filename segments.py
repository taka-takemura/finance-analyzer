# -*- coding: utf-8 -*-
"""SPEEDAのセグメントエクスポート (事業セグメント/地域セグメント) のパーサー。"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

# 集計行 (チャートからは除外し、検証用に保持)
AGG_ROWS = {"計", "消去又は全社", "財務諸表計上額", "調整額", "全社", "消去"}


def parse_segments(raw: pd.DataFrame) -> dict | None:
    """SPEEDAセグメントシート(生DataFrame)をパースする。

    返り値: {"type": 種別名, "years": [...],
             "items": {科目名: DataFrame(index=セグメント, columns=年度)}}
    """
    if raw.empty or raw.shape[1] < 3:
        return None
    col1 = raw.iloc[:, 1].astype(str).str.strip()
    hdr_idx = col1[col1 == "決算期"].index
    if len(hdr_idx) == 0:
        return None
    hdr = hdr_idx[0]
    year_cols = [i for i in range(2, raw.shape[1]) if pd.notna(raw.iloc[hdr, i])]
    years = [str(raw.iloc[hdr, i]).strip() for i in year_cols]
    if not years:
        return None

    # 種別名 (ヘッダー部の「事業セグメント」「地域セグメント（所在地）」等)
    stype = "セグメント"
    for i in range(min(hdr, 10)):
        v = str(raw.iloc[i, 0])
        if pd.notna(raw.iloc[i, 0]) and "セグメント" in v and "※" not in v:
            stype = v.strip()

    col0 = raw.iloc[:, 0]
    item_rows = [(i, str(v).strip()) for i, v in col0.items()
                 if i > hdr and pd.notna(v)]
    items: dict[str, pd.DataFrame] = {}
    for n, (start, label) in enumerate(item_rows):
        end = item_rows[n + 1][0] if n + 1 < len(item_rows) else len(raw)
        item = re.sub(r"\s*[(（].*?[)）]\s*$", "", label).strip()  # 単位表記を除去
        segs = {}
        for ri in range(start, end):
            name = raw.iloc[ri, 1]
            if pd.isna(name):
                continue
            vals = pd.Series([raw.iloc[ri, c] for c in year_cols], index=years)
            vals = pd.to_numeric(vals.astype(str).str.replace(",", "")
                                 .str.replace("△", "-"), errors="coerce")
            segs[str(name).strip()] = vals
        if segs:
            df = pd.DataFrame(segs).T.dropna(how="all")
            if not df.empty:
                items[item] = df
    if not items:
        return None
    return {"type": stype, "years": years, "items": items}


def load_segments(file) -> dict | None:
    """Excelファイルからセグメントデータを読み込む (最初に見つかったシート)。"""
    xl = pd.ExcelFile(file)
    for sheet in xl.sheet_names:
        if "詳細" in str(sheet):
            continue
        parsed = parse_segments(xl.parse(sheet, header=None))
        if parsed:
            return parsed
    return None


def active_segments(df: pd.DataFrame) -> pd.DataFrame:
    """集計行を除いたセグメント行のみ返す。"""
    return df.loc[[i for i in df.index if i not in AGG_ROWS]]


def portfolio_map(seg: dict, window_years: list[str]) -> pd.DataFrame:
    """ポートフォリオマップ用データ: 売上CAGR × 利益率 × 規模 (最新期)。"""
    sales_key = "外部顧客向け売上高" if "外部顧客向け売上高" in seg["items"] else "売上高"
    sales = active_segments(seg["items"][sales_key])[window_years]
    profit = seg["items"].get("セグメント利益")
    rows = []
    latest = window_years[-1]
    for name, s in sales.iterrows():
        s = s.dropna()
        if len(s) < 2 or latest not in s.index or s.iloc[0] <= 0 or s[latest] <= 0:
            continue
        n = list(s.index).index(latest) - 0  # 期間数
        first = s.iloc[0]
        cagr = (s[latest] / first) ** (1 / max(len(s) - 1, 1)) - 1
        margin = np.nan
        if profit is not None and name in profit.index and pd.notna(profit.loc[name, latest]):
            margin = profit.loc[name, latest] / s[latest] * 100
        rows.append({"セグメント": name, "売上高": s[latest],
                     "CAGR(%)": cagr * 100, "利益率(%)": margin})
    return pd.DataFrame(rows)
