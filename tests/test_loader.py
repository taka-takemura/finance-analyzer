# -*- coding: utf-8 -*-
import pandas as pd
import pytest

import loader


def test_norm_and_aliases():
    lk = loader.LOOKUPS["PL"]
    assert lk[loader._norm("Revenue")] == "売上高"
    assert lk[loader._norm("売上収益")] == "売上高"
    assert lk[loader._norm("売上高合計")] == "売上高"        # SPEEDA
    assert lk[loader._norm("Cost of sales")] == "売上原価"
    bs = loader.LOOKUPS["BS"]
    assert bs[loader._norm("株主資本等合計")] == "自己資本"
    assert bs[loader._norm("買入債務")] == "仕入債務"
    assert bs[loader._norm("純資産")] == "純資産合計"


def test_template_roundtrip(stmts):
    pl, bs, cf = stmts["PL"], stmts["BS"], stmts["CF"]
    assert loader.validate(stmts) == []
    assert list(pl.columns) == list(bs.columns)
    assert "売上高" in pl.index and "自己資本" in bs.index
    # B/S: 資産 = 負債 + 純資産 (サンプル生成時の丸め誤差を許容)
    diff = (bs.loc["資産合計"] - bs.loc["負債合計"] - bs.loc["純資産合計"]).abs()
    assert (diff <= 3).all()


def test_fill_derived():
    pl = pd.DataFrame({"2024": [1000.0, 600.0, 250.0]},
                      ).set_index(pd.Index(["売上高", "売上原価", "販売費及び一般管理費"]))
    stmts = {"PL": pl, "BS": pd.DataFrame(), "CF": pd.DataFrame()}
    loader._fill_derived(stmts)
    out = stmts["PL"]
    assert out.loc["売上総利益", "2024"] == 400.0
    assert out.loc["営業利益", "2024"] == 150.0
    assert out.loc["当期純利益", "2024"] == 150.0  # 税・営業外ゼロ扱い


def test_speeda_detection():
    raw = pd.DataFrame([
        ["三表一括（PL/BS/CF）", None, None],
        ["決算期", "2024/02期", "2025/02期"],
        ["損益計算書", None, None],
        ["売上高合計", 1000, 1100],
        ["売上原価合計", 600, 650],
        ["販売費及び一般管理費", 250, 260],
        ["貸借対照表", None, None],
        ["資産合計", 2000, 2100],
        ["負債合計", 800, 820],
        ["純資産合計", 1200, 1280],
    ])
    assert loader._is_speeda(raw)
    out = loader._parse_speeda(raw)
    assert out["PL"].loc["売上高", "2025/02期"] == 1100
    assert out["PL"].loc["営業利益", "2024/02期"] == 150  # 自動補完
    assert out["BS"].loc["資産合計", "2024/02期"] == 2000


def test_all_nan_rows_skipped():
    """セクション見出し「(発行済株式数)」等の空行が科目登録されないこと。"""
    df = pd.DataFrame({"科目": ["(発行済株式数)", "期末発行済株式数 - 普通株，自己株除く"],
                       "2024": [None, 1_000_000]})
    out = loader._clean_frame(df, "INFO")
    assert out.loc["発行済株式数", "2024"] == 1_000_000
