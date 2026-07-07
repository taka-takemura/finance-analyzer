# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

import segments as sg


def _raw():
    """SPEEDAセグメントファイルのレイアウトを模した生データ。"""
    rows = [
        ["テスト社", None, None, None],
        ["9999", None, None, None],
        [None, None, None, None],
        ["事業セグメント", None, None, None],
        [None, None, None, None],
        [None, "決算期", "2024/02期", "2025/02期"],
        [None, "連結／単体", "連結", "連結"],
        ["科目", "現地通貨単位", "日本円", "日本円"],
        ["外部顧客向け売上高 (百万円)", "A事業", 800, 900],
        [None, "B事業", 200, 250],
        [None, "計", 1000, 1150],
        [None, "財務諸表計上額", 1000, 1150],
        [None, None, None, None],
        ["セグメント利益 (百万円)", "A事業", 80, 99],
        [None, "B事業", 10, 15],
        [None, "計", 90, 114],
    ]
    return pd.DataFrame(rows)


def test_parse_segments():
    seg = sg.parse_segments(_raw())
    assert seg["type"] == "事業セグメント"
    assert seg["years"] == ["2024/02期", "2025/02期"]
    assert set(seg["items"]) == {"外部顧客向け売上高", "セグメント利益"}
    s = seg["items"]["外部顧客向け売上高"]
    assert s.loc["A事業", "2025/02期"] == 900
    assert s.loc["財務諸表計上額", "2025/02期"] == 1150


def test_active_segments_excludes_aggregates():
    seg = sg.parse_segments(_raw())
    act = sg.active_segments(seg["items"]["外部顧客向け売上高"])
    assert set(act.index) == {"A事業", "B事業"}


def test_portfolio_map():
    seg = sg.parse_segments(_raw())
    pm = sg.portfolio_map(seg, seg["years"]).set_index("セグメント")
    assert pm.loc["A事業", "CAGR(%)"] == np.float64(900 / 800 - 1) * 100
    assert pm.loc["A事業", "利益率(%)"] == np.float64(99 / 900) * 100
    assert "計" not in pm.index


def test_parse_rejects_non_segment():
    assert sg.parse_segments(pd.DataFrame({"a": [1, 2]})) is None
