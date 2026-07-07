# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import pytest

import analysis as an

TAX = 0.30


@pytest.fixture(scope="module")
def data(stmts):
    return stmts["PL"], stmts["BS"], stmts["CF"]


def test_dupont_identity(data):
    """ROE = 純利益率 × 回転率 × レバレッジ が成立すること。"""
    pl, bs, _ = data
    dp = an.dupont(pl, bs)
    for y in pl.columns:
        prod = (dp.loc["当期純利益率(%)", y] / 100
                * dp.loc["総資産回転率(回)", y]
                * dp.loc["財務レバレッジ(倍)", y] * 100)
        assert abs(prod - dp.loc["ROE(%)", y]) < 1e-6


def test_dupont_uses_owner_equity(data):
    """分母が自己資本(親会社帰属)であること。"""
    pl, bs, _ = data
    dp = an.dupont(pl, bs)
    y = pl.columns[-1]
    expect = pl.loc["当期純利益", y] / bs.loc["自己資本", y] * 100
    assert abs(dp.loc["ROE(%)", y] - expect) < 1e-9


def test_roic_tree_reconciles(data):
    pl, bs, _ = data
    y = pl.columns[-1]
    t = an.roic_tree(pl, bs, y, TAX)
    recon = t["営業利益率(%)"] / 100 * t["投下資本回転率(回)"] * (1 - TAX) * 100
    assert abs(recon - t["ROIC(%)"]) < 1e-6
    assert t["投下資本"] == pytest.approx(t["有利子負債"] + t["純資産"])


def test_ratios_basic(data):
    pl, bs, cf = data
    r = an.compute_ratios(pl, bs, cf, TAX)
    y = pl.columns[-1]
    assert r.loc[("収益性", "営業利益率(%)"), y] == pytest.approx(
        pl.loc["営業利益", y] / pl.loc["売上高", y] * 100)
    ccc = (r.loc[("効率性", "売上債権回転期間(日)"), y]
           + r.loc[("効率性", "棚卸資産回転期間(日)"), y]
           - r.loc[("効率性", "仕入債務回転期間(日)"), y])
    assert r.loc[("効率性", "CCC(日)"), y] == pytest.approx(ccc)


def test_cvp(data):
    pl, _, _ = data
    y = pl.columns[-1]
    vr = an.estimate_variable_ratio(pl)
    assert 0.05 <= vr <= 0.95
    c = an.cvp(pl, y, vr)
    # 変動費+固定費+営業利益 = 売上高
    assert c["売上高"] == pytest.approx(c["変動費"] + c["固定費"] + c["営業利益"])
    # BEP点では利益ゼロ: BEP×(1-vr) = 固定費
    assert c["損益分岐点売上高"] * (1 - vr) == pytest.approx(c["固定費"])


def test_regression_cvp_known_line():
    """完全な直線データなら傾き・切片を厳密に復元できること。"""
    sales = pd.Series([100.0, 200, 300, 400], index=list("ABCD"))
    op = 0.3 * sales - 50  # 限界利益率30%, 固定費50
    pl = pd.DataFrame({"売上高": sales, "営業利益": op}).T
    reg = an.regression_cvp(pl)
    assert reg["限界利益率(%)"] == pytest.approx(30.0)
    assert reg["固定費"] == pytest.approx(50.0)
    assert reg["R2"] == pytest.approx(1.0)


def test_simulate_directions(data):
    pl, bs, _ = data
    y = pl.columns[-1]
    up = an.simulate(pl, bs, y, {"sales_chg": 10}, TAX)
    assert up["sim"]["営業利益"] > up["base"]["営業利益"]
    worse = an.simulate(pl, bs, y, {"cogs_ratio_chg": 2}, TAX)
    assert worse["sim"]["営業利益"] < worse["base"]["営業利益"]
    # ゼロ変化なら一致
    same = an.simulate(pl, bs, y, {}, TAX)
    assert same["sim"]["営業利益"] == pytest.approx(same["base"]["営業利益"])


def test_tornado_symmetry(data):
    pl, bs, _ = data
    y = pl.columns[-1]
    tor = an.tornado(pl, bs, y, TAX, metric="営業利益")
    row = tor[tor["ドライバー"].str.startswith("売上高の増減")].iloc[0]
    assert row["増加時"] == pytest.approx(-row["減少時"], rel=1e-6)


def test_productivity(data):
    pl, bs, _ = data
    info = pd.DataFrame({c: [1000.0] for c in pl.columns}, index=["従業員数"])
    prod = an.productivity(pl, bs, info)
    y = pl.columns[-1]
    assert prod.loc[("生産性", "1人あたり売上高"), y] == pytest.approx(
        pl.loc["売上高", y] / 1000)


def test_equity_series_fallback(data):
    """自己資本行が無い場合は純資産合計にフォールバック。"""
    _, bs, _ = data
    bs2 = bs.drop(index=["自己資本"])
    assert (an.equity_series(bs2) == bs.loc["純資産合計"]).all()
