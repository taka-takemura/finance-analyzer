# -*- coding: utf-8 -*-
"""財務分析エンジン: 指標計算 / DuPont / ROIC / CVP / シミュレーション"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _g(df: pd.DataFrame, item: str, default: float = 0.0) -> pd.Series:
    """科目を取得。無ければ default で埋めた Series。"""
    if item in df.index:
        return df.loc[item].astype(float)
    cols = df.columns if not df.empty else []
    return pd.Series(default, index=cols, dtype=float)


def _div(a, b):
    """ゼロ除算を NaN にする安全な除算。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        r = a / b
    return r.replace([np.inf, -np.inf], np.nan) if isinstance(r, pd.Series) else \
        (np.nan if not np.isfinite(r) else r)


def equity_series(bs: pd.DataFrame) -> pd.Series:
    """自己資本(親会社株主帰属)。無い年度は純資産合計で補完。

    ROE・DuPont等の分子が親会社帰属利益のため、分母もこれに揃える。
    """
    net = _g(bs, "純資産合計")
    if "自己資本" in bs.index:
        return bs.loc["自己資本"].astype(float).combine_first(net)
    return net


# ================================================================ 財務指標
def compute_ratios(pl: pd.DataFrame, bs: pd.DataFrame, cf: pd.DataFrame,
                   tax_rate: float = 0.30) -> pd.DataFrame:
    """カテゴリ別の財務指標を年度ごとに計算する。"""
    sales = _g(pl, "売上高")
    debt = _g(bs, "短期借入金") + _g(bs, "長期借入金")
    equity = equity_series(bs)           # 自己資本(親会社帰属)ベース
    net_assets = _g(bs, "純資産合計")     # 少数株主持分込み
    assets = _g(bs, "資産合計")
    nopat = _g(pl, "営業利益") * (1 - tax_rate)
    invested = net_assets + debt         # 投下資本は純資産全体+有利子負債

    r = {}
    # --- 収益性
    r[("収益性", "売上総利益率(%)")] = _div(_g(pl, "売上総利益"), sales) * 100
    r[("収益性", "営業利益率(%)")] = _div(_g(pl, "営業利益"), sales) * 100
    r[("収益性", "経常利益率(%)")] = _div(_g(pl, "経常利益"), sales) * 100
    r[("収益性", "当期純利益率(%)")] = _div(_g(pl, "当期純利益"), sales) * 100
    r[("収益性", "ROE(%)")] = _div(_g(pl, "当期純利益"), equity) * 100
    r[("収益性", "ROA(%)")] = _div(_g(pl, "当期純利益"), assets) * 100
    r[("収益性", "ROIC(%)")] = _div(nopat, invested) * 100
    # --- 効率性
    r[("効率性", "総資産回転率(回)")] = _div(sales, assets)
    r[("効率性", "売上債権回転期間(日)")] = _div(_g(bs, "売上債権"), sales) * 365
    r[("効率性", "棚卸資産回転期間(日)")] = _div(_g(bs, "棚卸資産"), sales) * 365
    r[("効率性", "仕入債務回転期間(日)")] = _div(_g(bs, "仕入債務"), sales) * 365
    r[("効率性", "CCC(日)")] = (r[("効率性", "売上債権回転期間(日)")]
                                + r[("効率性", "棚卸資産回転期間(日)")]
                                - r[("効率性", "仕入債務回転期間(日)")])
    # --- 安全性
    r[("安全性", "流動比率(%)")] = _div(_g(bs, "流動資産合計"), _g(bs, "流動負債合計")) * 100
    r[("安全性", "自己資本比率(%)")] = _div(equity, assets) * 100
    r[("安全性", "D/Eレシオ(倍)")] = _div(debt, equity)
    r[("安全性", "固定比率(%)")] = _div(_g(bs, "固定資産合計"), equity) * 100
    icr_base = _g(pl, "支払利息")
    if (icr_base == 0).all():
        icr_base = _g(pl, "営業外費用")
    r[("安全性", "インタレスト・カバレッジ(倍)")] = _div(_g(pl, "営業利益"), icr_base)
    # --- 成長性 (前年比)
    r[("成長性", "売上高成長率(%)")] = sales.pct_change() * 100
    r[("成長性", "営業利益成長率(%)")] = _g(pl, "営業利益").pct_change() * 100
    r[("成長性", "純利益成長率(%)")] = _g(pl, "当期純利益").pct_change() * 100
    # --- キャッシュフロー
    if not cf.empty:
        ocf = _g(cf, "営業活動によるキャッシュ・フロー")
        icf = _g(cf, "投資活動によるキャッシュ・フロー")
        r[("CF", "営業CFマージン(%)")] = _div(ocf, sales) * 100
        r[("CF", "フリーCF")] = ocf + icf

    out = pd.DataFrame(r).T
    out.index = pd.MultiIndex.from_tuples(out.index, names=["カテゴリ", "指標"])
    return out


# ================================================================ DuPont
def dupont(pl: pd.DataFrame, bs: pd.DataFrame) -> pd.DataFrame:
    """ROE = 純利益率 × 総資産回転率 × 財務レバレッジ

    分子(親会社株主帰属利益)に合わせ、分母も自己資本(親会社帰属)を使う。
    """
    sales = _g(pl, "売上高")
    ni = _g(pl, "当期純利益")
    assets = _g(bs, "資産合計")
    equity = equity_series(bs)
    return pd.DataFrame({
        "当期純利益率(%)": _div(ni, sales) * 100,
        "総資産回転率(回)": _div(sales, assets),
        "財務レバレッジ(倍)": _div(assets, equity),
        "ROE(%)": _div(ni, equity) * 100,
    }).T


# ================================================================ ROICツリー
def roic_tree(pl: pd.DataFrame, bs: pd.DataFrame, year: str,
              tax_rate: float = 0.30) -> dict:
    """ROICツリーの各ノード値を dict で返す。"""
    def v(df, item):
        return float(df.loc[item, year]) if item in df.index else 0.0

    sales = v(pl, "売上高")
    op = v(pl, "営業利益")
    nopat = op * (1 - tax_rate)
    debt = v(bs, "短期借入金") + v(bs, "長期借入金")
    net_assets = v(bs, "純資産合計")  # 投下資本は少数株主持分込みの純資産で計算
    invested = net_assets + debt
    wc = v(bs, "売上債権") + v(bs, "棚卸資産") - v(bs, "仕入債務")
    fixed = v(bs, "固定資産合計")

    def pct(a, b):
        return a / b * 100 if b else float("nan")

    return {
        "ROIC(%)": pct(nopat, invested),
        "NOPAT": nopat,
        "投下資本": invested,
        "営業利益率(%)": pct(op, sales),
        "投下資本回転率(回)": sales / invested if invested else float("nan"),
        "売上高": sales,
        "営業利益": op,
        "売上原価率(%)": pct(v(pl, "売上原価"), sales),
        "販管費率(%)": pct(v(pl, "販売費及び一般管理費"), sales),
        "運転資本": wc,
        "運転資本回転率(回)": sales / wc if wc else float("nan"),
        "固定資産": fixed,
        "固定資産回転率(回)": sales / fixed if fixed else float("nan"),
        "有利子負債": debt,
        "純資産": net_assets,
        "実効税率(%)": tax_rate * 100,
    }


# ================================================================ CVP分析
def estimate_variable_ratio(pl: pd.DataFrame) -> float:
    """高低点法で変動費率を推定する(データ2期以上が必要)。"""
    sales = _g(pl, "売上高")
    total_cost = _g(pl, "売上原価") + _g(pl, "販売費及び一般管理費")
    valid = sales.notna() & total_cost.notna()
    s, c = sales[valid], total_cost[valid]
    if len(s) < 2 or s.max() == s.min():
        return 0.60
    hi, lo = s.idxmax(), s.idxmin()
    vr = (c[hi] - c[lo]) / (s[hi] - s[lo])
    return float(np.clip(vr, 0.05, 0.95))


def regression_cvp(pl: pd.DataFrame) -> dict | None:
    """散布図法: 営業利益 = 限界利益率 × 売上高 − 固定費 を最小二乗で推定。

    バフェットコード等で用いられる方式。データ3期以上が必要。
    """
    sales = _g(pl, "売上高")
    op = _g(pl, "営業利益")
    valid = sales.notna() & op.notna()
    s, o = sales[valid].values.astype(float), op[valid].values.astype(float)
    if len(s) < 3 or np.std(s) == 0:
        return None
    m, b = np.polyfit(s, o, 1)
    pred = m * s + b
    ss_res = float(((o - pred) ** 2).sum())
    ss_tot = float(((o - o.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    return {
        "限界利益率(%)": m * 100,
        "固定費": -b,          # 切片の符号反転 = 通期固定費
        "R2": r2,
        "変動費率": 1 - m,
        "点": list(zip(list(sales[valid].index), s, o)),
        "傾き": m, "切片": b,
    }


def cvp(pl: pd.DataFrame, year: str, variable_ratio: float) -> dict:
    """指定年度のCVP分析。"""
    sales = float(pl.loc["売上高", year])
    total_cost = float(_g(pl, "売上原価")[year] + _g(pl, "販売費及び一般管理費")[year])
    var_cost = sales * variable_ratio
    fixed_cost = max(total_cost - var_cost, 0.0)
    cmr = 1 - variable_ratio  # 限界利益率
    bep = fixed_cost / cmr if cmr > 0 else float("nan")
    return {
        "売上高": sales,
        "変動費": var_cost,
        "固定費": fixed_cost,
        "限界利益": sales - var_cost,
        "限界利益率(%)": cmr * 100,
        "損益分岐点売上高": bep,
        "損益分岐点比率(%)": bep / sales * 100 if sales else float("nan"),
        "安全余裕率(%)": (sales - bep) / sales * 100 if sales else float("nan"),
        "営業利益": sales - var_cost - fixed_cost,
    }


# ================================================================ シミュレーション
DRIVER_DEFS = [
    # (キー, 表示名, 単位, min, max, step, default)
    ("sales_chg", "売上高の増減", "%", -30.0, 30.0, 1.0, 0.0),
    ("cogs_ratio_chg", "売上原価率の増減", "pt", -10.0, 10.0, 0.5, 0.0),
    ("sga_chg", "販管費の増減", "%", -20.0, 20.0, 1.0, 0.0),
    ("receivable_days_chg", "売上債権回転期間の増減", "日", -30.0, 30.0, 1.0, 0.0),
    ("inventory_days_chg", "棚卸資産回転期間の増減", "日", -30.0, 30.0, 1.0, 0.0),
    ("debt_chg", "有利子負債の増減", "%", -50.0, 50.0, 5.0, 0.0),
]


def simulate(pl: pd.DataFrame, bs: pd.DataFrame, year: str,
             params: dict, tax_rate: float = 0.30) -> dict:
    """ドライバー変化後のPL・BS・主要指標を計算する。

    params: {"sales_chg": %, "cogs_ratio_chg": pt, "sga_chg": %,
             "receivable_days_chg": 日, "inventory_days_chg": 日, "debt_chg": %}
    """
    def v(df, item):
        return float(df.loc[item, year]) if item in df.index else 0.0

    p = {k: params.get(k, 0.0) for k, *_ in DRIVER_DEFS}

    # --- ベース値
    sales0 = v(pl, "売上高")
    cogs0 = v(pl, "売上原価")
    sga0 = v(pl, "販売費及び一般管理費")
    noi0 = v(pl, "営業外収益")
    noe0 = v(pl, "営業外費用")
    debt0 = v(bs, "短期借入金") + v(bs, "長期借入金")
    net0 = v(bs, "純資産合計")            # ROIC用 (少数株主込み)
    eqs = equity_series(bs)
    equity0 = float(eqs[year]) if year in eqs.index and np.isfinite(eqs[year]) else net0  # ROE用
    assets0 = v(bs, "資産合計")
    recv0 = v(bs, "売上債権")
    inv0 = v(bs, "棚卸資産")

    # --- シミュレーション後
    sales1 = sales0 * (1 + p["sales_chg"] / 100)
    cogs_ratio1 = (cogs0 / sales0 if sales0 else 0) + p["cogs_ratio_chg"] / 100
    cogs1 = sales1 * cogs_ratio1
    sga1 = sga0 * (1 + p["sga_chg"] / 100)
    op1 = sales1 - cogs1 - sga1

    debt1 = debt0 * (1 + p["debt_chg"] / 100)
    # 営業外費用は有利子負債に比例すると仮定(金利負担)
    noe1 = noe0 * (debt1 / debt0) if debt0 else noe0
    ord1 = op1 + noi0 - noe1
    ni1 = ord1 * (1 - tax_rate)

    recv1 = (recv0 / sales0 * 365 + p["receivable_days_chg"]) / 365 * sales1 if sales0 else recv0
    inv1 = (inv0 / sales0 * 365 + p["inventory_days_chg"]) / 365 * sales1 if sales0 else inv0
    # 資産合計は運転資本と負債の増減を反映
    assets1 = assets0 + (recv1 - recv0) + (inv1 - inv0) + (debt1 - debt0)
    invested1 = net0 + debt1
    nopat1 = op1 * (1 - tax_rate)

    op0 = sales0 - cogs0 - sga0
    ord0 = op0 + noi0 - noe0
    ni0 = ord0 * (1 - tax_rate)
    invested0 = net0 + debt0

    def pct(a, b):
        return a / b * 100 if b else float("nan")

    base = {
        "売上高": sales0, "売上原価": cogs0, "販管費": sga0, "営業利益": op0,
        "経常利益": ord0, "当期純利益": ni0,
        "営業利益率(%)": pct(op0, sales0),
        "ROE(%)": pct(ni0, equity0),
        "ROIC(%)": pct(op0 * (1 - tax_rate), invested0),
        "総資産": assets0,
    }
    sim = {
        "売上高": sales1, "売上原価": cogs1, "販管費": sga1, "営業利益": op1,
        "経常利益": ord1, "当期純利益": ni1,
        "営業利益率(%)": pct(op1, sales1),
        "ROE(%)": pct(ni1, equity0),
        "ROIC(%)": pct(nopat1, invested1),
        "総資産": assets1,
    }
    return {"base": base, "sim": sim}


def tornado(pl: pd.DataFrame, bs: pd.DataFrame, year: str,
            tax_rate: float = 0.30, shock: float = 10.0,
            metric: str = "当期純利益") -> pd.DataFrame:
    """各ドライバーを±shock 動かしたときの指標(metric)への影響(感応度)。"""
    rows = []
    base_v = simulate(pl, bs, year, {}, tax_rate)["base"][metric]
    for key, label, unit, lo, hi, step, default in DRIVER_DEFS:
        if unit == "%":
            d = shock
        elif unit == "pt":
            d = 2.0
        else:  # 日
            d = 10.0
        up = simulate(pl, bs, year, {key: +d}, tax_rate)["sim"][metric]
        dn = simulate(pl, bs, year, {key: -d}, tax_rate)["sim"][metric]
        rows.append({"ドライバー": f"{label} ±{d:g}{unit}",
                     "増加時": up - base_v, "減少時": dn - base_v})
    df = pd.DataFrame(rows)
    df["幅"] = (df["増加時"] - df["減少時"]).abs()
    return df.sort_values("幅", ascending=True).drop(columns="幅")
