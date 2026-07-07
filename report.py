# -*- coding: utf-8 -*-
"""分析レポート (自己完結HTML) の生成。ブラウザの印刷機能でPDF化できる。"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.graph_objects as go

import analysis as an

PALETTE = ["#2563EB", "#EA580C", "#059669", "#7C3AED", "#DC2626", "#0891B2"]

CSS = """
body {font-family: 'Helvetica Neue','Hiragino Sans','Noto Sans JP',sans-serif;
      color:#1F2937; max-width: 1000px; margin: 24px auto; padding: 0 16px;}
h1 {border-bottom: 3px solid #2563EB; padding-bottom: 8px;}
h2 {color:#1E3A8A; margin-top: 36px;}
table {border-collapse: collapse; width: 100%; font-size: 13px;}
th, td {border: 1px solid #E5E7EB; padding: 6px 10px; text-align: right;}
th {background: #F3F6FB;}
td:first-child, th:first-child {text-align: left;}
.meta {color:#6B7280; font-size: 13px;}
.chart {margin: 12px 0;}
@media print {.chart {break-inside: avoid;}}
"""


def _fig_html(fig, first=False):
    fig.update_layout(paper_bgcolor="white", plot_bgcolor="white",
                      font=dict(family="'Hiragino Sans','Noto Sans JP',sans-serif"))
    return f"<div class='chart'>{fig.to_html(full_html=False, include_plotlyjs='cdn' if first else False, config={'displayModeBar': False})}</div>"


def build_html(title: str, pl: pd.DataFrame, bs: pd.DataFrame, cf: pd.DataFrame,
               ratios: pd.DataFrame, unit_label: str, tax_rate: float) -> str:
    years = list(pl.columns)
    latest = years[-1]
    parts = [f"<html><head><meta charset='utf-8'><title>{title}</title>"
             f"<style>{CSS}</style></head><body>",
             f"<h1>{title}</h1>",
             f"<p class='meta'>作成日: {dt.date.today().isoformat()} / 対象期間: "
             f"{years[0]}〜{latest} / 単位: {unit_label} / 実効税率: {tax_rate*100:.0f}%</p>"]

    # --- 売上高と利益
    fig = go.Figure()
    fig.add_trace(go.Bar(x=years, y=pl.loc["売上高"], name="売上高",
                         marker_color="#BFDBFE"))
    for item, c in [("営業利益", PALETTE[2]), ("当期純利益", PALETTE[1])]:
        if item in pl.index:
            fig.add_trace(go.Scatter(x=years, y=pl.loc[item], name=item,
                                     mode="lines+markers", yaxis="y2",
                                     line=dict(color=c, width=3)))
    fig.update_layout(title=f"売上高と利益の推移 ({unit_label})", height=420,
                      yaxis2=dict(overlaying="y", side="right"),
                      legend=dict(orientation="h", y=-0.2))
    parts.append("<h2>業績推移</h2>")
    parts.append(_fig_html(fig, first=True))

    # --- 利益率とROE/ROIC
    fig = go.Figure()
    for (cat, met) in [("収益性", "営業利益率(%)"), ("収益性", "当期純利益率(%)"),
                       ("収益性", "ROE(%)"), ("収益性", "ROIC(%)")]:
        if (cat, met) in ratios.index:
            fig.add_trace(go.Scatter(x=years, y=ratios.loc[(cat, met)],
                                     mode="lines+markers", name=met))
    fig.update_layout(title="収益性指標の推移 (%)", height=420,
                      legend=dict(orientation="h", y=-0.2))
    parts.append(_fig_html(fig))

    # --- キャッシュフロー
    if not cf.empty:
        fig = go.Figure()
        for item in ["営業活動によるキャッシュ・フロー", "投資活動によるキャッシュ・フロー",
                     "財務活動によるキャッシュ・フロー"]:
            if item in cf.index:
                fig.add_trace(go.Bar(x=years, y=cf.loc[item],
                                     name=item.replace("活動によるキャッシュ・フロー", "CF")))
        fig.update_layout(title=f"キャッシュ・フロー ({unit_label})", barmode="group",
                          height=400, legend=dict(orientation="h", y=-0.2))
        parts.append("<h2>キャッシュ・フロー</h2>")
        parts.append(_fig_html(fig))

    # --- DuPont
    dp = an.dupont(pl, bs)
    parts.append("<h2>DuPont分解 (ROE)</h2>")
    parts.append(dp.round(2).to_html())

    # --- 指標一覧
    parts.append("<h2>財務指標一覧</h2>")
    flat = ratios.copy()
    flat.index = [f"{c} | {m}" for c, m in flat.index]
    parts.append(flat.round(2).to_html())

    # --- 主要財務諸表
    parts.append(f"<h2>損益計算書 ({unit_label})</h2>")
    parts.append(pl.round(0).to_html())
    parts.append(f"<h2>貸借対照表 ({unit_label})</h2>")
    parts.append(bs.round(0).to_html())

    parts.append("<p class='meta'>本レポートは簡易分析ツールによる自動生成であり、"
                 "投資判断等は自己責任で行ってください。</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
