# -*- coding: utf-8 -*-
import pandas as pd
import pytest

import edinet
import report
import valuation
import analysis as an

CSV_COLS = ["要素ID", "項目名", "コンテキストID", "相対年度", "連結・個別",
            "期間・時点", "ユニットID", "単位", "値"]


def _row(el, ctx, val):
    return [el, "", ctx, "", "連結", "", "JPY", "円", str(val)]


@pytest.fixture
def xbrl_csv():
    rows = [
        _row("jppfs_cor:NetSales", "CurrentYearDuration", 1_000_000_000),
        _row("jppfs_cor:NetSales", "Prior1YearDuration", 900_000_000),
        _row("jppfs_cor:NetSales", "CurrentYearDuration_NonConsolidatedMember", 1),
        _row("jpigp_cor:RevenueIFRS", "CurrentYearDuration", 2),  # NetSales優先
        _row("jppfs_cor:OperatingIncome", "CurrentYearDuration", 100_000_000),
        _row("jppfs_cor:Assets", "CurrentYearInstant", 2_000_000_000),
        _row("jppfs_cor:NetAssets", "CurrentYearInstant", 800_000_000),
        _row("jppfs_cor:NonControllingInterests", "CurrentYearInstant", 50_000_000),
    ]
    return pd.DataFrame(rows, columns=CSV_COLS)


def test_extract_values(xbrl_csv):
    v = edinet.extract_values(xbrl_csv)
    assert v["cur"][("PL", "売上高")] == 1_000_000_000  # 連結・NetSales優先
    assert v["prior"][("PL", "売上高")] == 900_000_000
    assert v["cur"][("BS", "非支配株主持分")] == 50_000_000


def test_fetch_financials_builds_frames(monkeypatch, xbrl_csv):
    monkeypatch.setattr(edinet, "find_annual_reports",
                        lambda *a, **k: [{"docID": "D1", "periodEnd": "2026-02-28"}])
    monkeypatch.setattr(edinet, "download_csv", lambda doc_id, key: xbrl_csv)
    out = edinet.fetch_financials("9999", "dummy", 1)
    assert list(out["PL"].columns) == ["2025/02期", "2026/02期"]
    assert out["PL"].loc["売上高", "2026/02期"] == 1_000  # 10億円 → 百万円換算
    # 自己資本 = 純資産 - 非支配株主持分 (自動補完)
    assert out["BS"].loc["自己資本", "2026/02期"] == pytest.approx(750.0)


def test_norm_seccode():
    assert edinet._norm_seccode("3382") == "33820"
    assert edinet._norm_seccode("33820") == "33820"


def test_valuation_compute():
    v = valuation.compute(price=2500, shares_mn=100, dps=40,
                          net_income_mn=6879, equity_mn=36103)
    assert v["時価総額(百万円)"] == pytest.approx(250_000)
    assert v["PER(倍)"] == pytest.approx(250_000 / 6879)
    assert v["PBR(倍)"] == pytest.approx(250_000 / 36103)
    assert v["EPS(円)"] == pytest.approx(68.79)
    assert v["配当利回り(%)"] == pytest.approx(1.6)
    # 赤字ならPERはNaN
    import math
    assert math.isnan(valuation.compute(2500, 100, 0, -100, 36103)["PER(倍)"])


def test_report_html(stmts):
    pl, bs, cf = stmts["PL"], stmts["BS"], stmts["CF"]
    ratios = an.compute_ratios(pl, bs, cf, 0.30)
    html = report.build_html("テスト", pl, bs, cf, ratios, "百万円", 0.30)
    assert html.startswith("<html>")
    assert "plotly" in html.lower()
    assert "DuPont" in html
    assert len(html) > 20_000
