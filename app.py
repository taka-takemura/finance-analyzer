# -*- coding: utf-8 -*-
"""財務分析ビジュアライザー — Streamlit アプリ

起動: streamlit run app.py
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analysis as an
import loader

st.set_page_config(page_title="財務分析ビジュアライザー", page_icon="📊", layout="wide")

COLORS = dict(blue="#2563EB", green="#059669", red="#DC2626", orange="#EA580C",
              gray="#6B7280", purple="#7C3AED")


# ---------------------------------------------------------------- helpers
def fmt(v, digits=0, suffix=""):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "―"
    return f"{v:,.{digits}f}{suffix}"


def line_fig(df: pd.DataFrame, title: str, yaxis: str = "", percent=False):
    fig = go.Figure()
    for name, row in df.iterrows():
        fig.add_trace(go.Scatter(x=list(df.columns), y=row.values,
                                 mode="lines+markers", name=str(name)))
    fig.update_layout(title=title, yaxis_title=yaxis, height=380,
                      margin=dict(t=50, b=30), legend=dict(orientation="h", y=-0.2))
    if percent:
        fig.update_yaxes(ticksuffix="%")
    return fig


@st.cache_data(show_spinner=False)
def load_file(data: bytes, name: str):
    buf = io.BytesIO(data)
    buf.name = name
    return loader.load_statements(buf)


# ---------------------------------------------------------------- sidebar
import edinet

st.sidebar.title("📊 財務分析ビジュアライザー")
source = st.sidebar.radio("データソース",
                          ["ファイルアップロード", "サンプルデータ", "EDINETから自動取得"])

stmts = None
if source == "ファイルアップロード":
    uploaded = st.sidebar.file_uploader(
        "財務諸表 (Excel/CSV)", type=["xlsx", "xls", "csv"],
        help="自作テンプレートのほか、SPEEDAのエクスポート"
             " (三表一括・財務諸表サマリー) を自動認識します")
    if uploaded is not None:
        try:
            stmts = load_file(uploaded.getvalue(), uploaded.name)
        except Exception as e:
            st.sidebar.error(f"読み込みエラー: {e}")
elif source == "サンプルデータ":
    sample = Path(__file__).parent / "サンプルデータ.xlsx"
    if sample.exists():
        stmts = load_file(sample.read_bytes(), sample.name)
    else:
        st.sidebar.warning("サンプルデータ.xlsx がありません。`python create_template.py` で生成してください。")
else:  # EDINET
    with st.sidebar:
        api_key = st.text_input("EDINET APIキー", type="password",
                                help="https://api.edinet-fsa.go.jp/ の「APIを利用する」から無料発行できます")
        sec_code = st.text_input("証券コード (4桁)", "3382")
        n_years = st.number_input("取得年数 (有報ベース)", 2, 10, 5)
        st.caption("有報の提出日を日次APIで走査するため、初回取得には1〜3分ほどかかります。")
        if st.button("📡 EDINETから取得", disabled=not (api_key and sec_code)):
            prog = st.progress(0.0, text="検索を開始...")

            def cb(msg, frac):
                prog.progress(min(frac or 0.0, 1.0), text=msg)

            try:
                st.session_state["edinet_data"] = edinet.fetch_financials(
                    sec_code, api_key, int(n_years), cb)
                st.session_state["edinet_label"] = f"{sec_code} (EDINET)"
                prog.empty()
            except edinet.EdinetError as e:
                prog.empty()
                st.error(str(e))
            except Exception as e:
                prog.empty()
                st.error(f"取得失敗: {e}")
        if "edinet_data" in st.session_state:
            st.success(f"取得済み: {st.session_state.get('edinet_label', '')}")
    stmts = st.session_state.get("edinet_data")

tpl = Path(__file__).parent / "テンプレート.xlsx"
if tpl.exists():
    st.sidebar.download_button("📥 入力テンプレートをダウンロード", tpl.read_bytes(),
                               file_name="財務諸表テンプレート.xlsx")

tax_rate = st.sidebar.slider("実効税率 (%)", 0, 50, 30) / 100
unit_label = st.sidebar.text_input("金額単位の表示", "百万円")

if stmts is None:
    st.info("👈 サイドバーから財務諸表をアップロードするか、サンプルデータ / EDINET自動取得を選んでください。\n\n"
            "- **自作テンプレート**: PL / BS / CF の3シート構成 (1列目=科目、2列目以降=年度)\n"
            "- **SPEEDA**: 「三表一括(PL・BS・CF)」または「財務諸表サマリー」のエクスポートをそのままアップロード\n"
            "- **EDINET**: 証券コードを指定して有価証券報告書のXBRLから自動取得 (無料APIキーが必要)\n\n"
            "科目名は日本基準のほか IFRS / US GAAP (Revenue, Cost of sales など) も自動認識します。")
    st.stop()

issues = loader.validate(stmts)
if issues:
    for msg in issues:
        st.warning(msg)
    if stmts["PL"].empty or stmts["BS"].empty:
        st.stop()

pl, bs, cf = stmts["PL"], stmts["BS"], stmts["CF"]
all_years = list(pl.columns)

# --- 分析対象期間の選択 (長期データ対応)
if len(all_years) > 3:
    default_start = all_years[-10] if len(all_years) > 10 else all_years[0]
    y_from, y_to = st.sidebar.select_slider(
        "分析対象期間", options=all_years, value=(default_start, all_years[-1]))
    sel = all_years[all_years.index(y_from):all_years.index(y_to) + 1]
    pl = pl[sel]
    bs = bs[[c for c in sel if c in bs.columns]]
    if not cf.empty:
        cf = cf[[c for c in sel if c in cf.columns]]

years = list(pl.columns)
latest = years[-1]
ratios = an.compute_ratios(pl, bs, cf, tax_rate)

tabs = st.tabs(["📈 概要", "📋 財務指標", "🌳 DuPont分析", "🌲 ROICツリー",
                "⚖️ CVP分析", "🎛 シミュレーション"])

# ================================================================ 概要
with tabs[0]:
    prev = years[-2] if len(years) >= 2 else None

    def metric(col, label, item, df=pl, suffix=""):
        cur = float(df.loc[item, latest]) if item in df.index else np.nan
        delta = None
        if prev and item in df.index:
            pv = float(df.loc[item, prev])
            if pv:
                delta = f"{(cur - pv) / abs(pv) * 100:+.1f}%"
        col.metric(f"{label} ({unit_label})", fmt(cur), delta)

    c1, c2, c3, c4, c5 = st.columns(5)
    metric(c1, "売上高", "売上高")
    metric(c2, "営業利益", "営業利益")
    metric(c3, "当期純利益", "当期純利益")
    roe = ratios.loc[("収益性", "ROE(%)")]
    roic = ratios.loc[("収益性", "ROIC(%)")]
    c4.metric("ROE", fmt(roe[latest], 1, "%"),
              f"{roe[latest] - roe[prev]:+.1f}pt" if prev else None)
    c5.metric("ROIC", fmt(roic[latest], 1, "%"),
              f"{roic[latest] - roic[prev]:+.1f}pt" if prev else None)

    left, right = st.columns(2)
    with left:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=years, y=pl.loc["売上高"], name="売上高",
                             marker_color=COLORS["blue"], opacity=0.7))
        for item, color in [("営業利益", "green"), ("当期純利益", "orange")]:
            if item in pl.index:
                fig.add_trace(go.Scatter(x=years, y=pl.loc[item], name=item,
                                         mode="lines+markers", yaxis="y2",
                                         line=dict(color=COLORS[color], width=3)))
        fig.update_layout(title=f"売上高と利益の推移 ({unit_label})", height=400,
                          yaxis=dict(title="売上高"),
                          yaxis2=dict(title="利益", overlaying="y", side="right"),
                          legend=dict(orientation="h", y=-0.2), margin=dict(t=50))
        st.plotly_chart(fig, width="stretch")
    with right:
        mdf = ratios.loc["収益性"].loc[["売上総利益率(%)", "営業利益率(%)", "当期純利益率(%)"]]
        st.plotly_chart(line_fig(mdf, "利益率の推移", percent=True), width="stretch")

    if not cf.empty:
        left2, right2 = st.columns(2)
        with left2:
            fig = go.Figure()
            for item, color in [("営業活動によるキャッシュ・フロー", "green"),
                                ("投資活動によるキャッシュ・フロー", "red"),
                                ("財務活動によるキャッシュ・フロー", "gray")]:
                if item in cf.index:
                    fig.add_trace(go.Bar(x=years, y=cf.loc[item],
                                         name=item.replace("活動によるキャッシュ・フロー", "CF"),
                                         marker_color=COLORS[color]))
            if ("CF", "フリーCF") in ratios.index:
                fig.add_trace(go.Scatter(x=years, y=ratios.loc[("CF", "フリーCF")],
                                         name="フリーCF", mode="lines+markers",
                                         line=dict(color=COLORS["blue"], width=3)))
            fig.update_layout(title=f"キャッシュ・フロー ({unit_label})", barmode="group",
                              height=400, legend=dict(orientation="h", y=-0.25), margin=dict(t=50))
            st.plotly_chart(fig, width="stretch")
        with right2:
            comp = pd.DataFrame({
                "流動資産": bs.loc["流動資産合計"] if "流動資産合計" in bs.index else 0,
                "固定資産": bs.loc["固定資産合計"] if "固定資産合計" in bs.index else 0,
            }).T
            fig = go.Figure()
            for name, row in comp.iterrows():
                fig.add_trace(go.Bar(x=years, y=row, name=name))
            if "純資産合計" in bs.index:
                fig.add_trace(go.Scatter(x=years, y=bs.loc["純資産合計"], name="純資産",
                                         mode="lines+markers",
                                         line=dict(color=COLORS["purple"], width=3)))
            fig.update_layout(title=f"資産構成と純資産 ({unit_label})", barmode="stack",
                              height=400, legend=dict(orientation="h", y=-0.25), margin=dict(t=50))
            st.plotly_chart(fig, width="stretch")

# ================================================================ 財務指標
with tabs[1]:
    st.subheader("財務指標一覧")
    st.dataframe(ratios.round(2), width="stretch", height=560)

    st.subheader("指標の推移チャート")
    cat = st.selectbox("カテゴリ", ratios.index.get_level_values(0).unique())
    sub = ratios.loc[cat]
    picks = st.multiselect("表示する指標", list(sub.index), default=list(sub.index)[:3])
    if picks:
        st.plotly_chart(line_fig(sub.loc[picks], f"{cat}指標の推移"),
                        width="stretch")

# ================================================================ DuPont
with tabs[2]:
    st.subheader("DuPont分析 — ROEの3分解")
    dp = an.dupont(pl, bs)
    y = st.select_slider("年度", years, value=latest, key="dp_year")

    ni_m, at, lev, roe_v = (dp.loc[k, y] for k in
                            ["当期純利益率(%)", "総資産回転率(回)", "財務レバレッジ(倍)", "ROE(%)"])
    dot = f"""
    digraph {{
      rankdir=LR; bgcolor=transparent;
      node [shape=box, style="rounded,filled", fillcolor="#EFF6FF",
            color="#2563EB", fontname="sans-serif", fontsize=12, margin="0.25,0.15"];
      ROE [label="ROE\\n{fmt(roe_v,1,'%')}", fillcolor="#2563EB", fontcolor=white];
      NPM [label="当期純利益率\\n{fmt(ni_m,1,'%')}"];
      AT  [label="総資産回転率\\n{fmt(at,2,'回')}"];
      LEV [label="財務レバレッジ\\n{fmt(lev,2,'倍')}"];
      NPM -> ROE; AT -> ROE; LEV -> ROE;
      NI [label="当期純利益\\n{fmt(float(pl.loc['当期純利益', y]))}"];
      S1 [label="売上高\\n{fmt(float(pl.loc['売上高', y]))}"];
      S2 [label="売上高\\n{fmt(float(pl.loc['売上高', y]))}"];
      TA1 [label="総資産\\n{fmt(float(bs.loc['資産合計', y]))}"];
      TA2 [label="総資産\\n{fmt(float(bs.loc['資産合計', y]))}"];
      EQ [label="自己資本\\n{fmt(float(an.equity_series(bs)[y]))}"];
      NI -> NPM; S1 -> NPM; S2 -> AT; TA1 -> AT; TA2 -> LEV; EQ -> LEV;
    }}"""
    st.graphviz_chart(dot, width="stretch")

    left, right = st.columns(2)
    with left:
        st.plotly_chart(line_fig(dp.loc[["ROE(%)", "当期純利益率(%)"]], "ROEと純利益率の推移",
                                 percent=True), width="stretch")
    with right:
        st.plotly_chart(line_fig(dp.loc[["総資産回転率(回)", "財務レバレッジ(倍)"]],
                                 "回転率とレバレッジの推移"), width="stretch")

    if len(years) >= 2:
        st.subheader("ROE変化の要因分解 (対前年)")
        y0, y1 = years[-2], years[-1]
        f0 = dp[y0]
        f1 = dp[y1]
        # 対数分解の近似: 各要素の寄与
        base = f0["ROE(%)"]
        c_npm = (f1["当期純利益率(%)"] / f0["当期純利益率(%)"] - 1) * base if f0["当期純利益率(%)"] else 0
        c_at = (f1["総資産回転率(回)"] / f0["総資産回転率(回)"] - 1) * base if f0["総資産回転率(回)"] else 0
        c_lev = (f1["財務レバレッジ(倍)"] / f0["財務レバレッジ(倍)"] - 1) * base if f0["財務レバレッジ(倍)"] else 0
        resid = f1["ROE(%)"] - base - c_npm - c_at - c_lev
        fig = go.Figure(go.Waterfall(
            x=[f"ROE {y0}", "純利益率", "回転率", "レバレッジ", "交差項", f"ROE {y1}"],
            measure=["absolute", "relative", "relative", "relative", "relative", "total"],
            y=[base, c_npm, c_at, c_lev, resid, None],
            text=[fmt(v, 2) for v in [base, c_npm, c_at, c_lev, resid, f1["ROE(%)"]]],
            textposition="outside"))
        fig.update_layout(height=380, yaxis_title="ROE(%)", margin=dict(t=30))
        st.plotly_chart(fig, width="stretch")

# ================================================================ ROICツリー
with tabs[3]:
    st.subheader("ROICツリー")
    y = st.select_slider("年度", years, value=latest, key="roic_year")
    t = an.roic_tree(pl, bs, y, tax_rate)

    dot = f"""
    digraph {{
      rankdir=LR; bgcolor=transparent;
      node [shape=box, style="rounded,filled", fillcolor="#ECFDF5",
            color="#059669", fontname="sans-serif", fontsize=11, margin="0.22,0.12"];
      ROIC [label="ROIC\\n{fmt(t['ROIC(%)'],1,'%')}", fillcolor="#059669", fontcolor=white];
      OPM [label="営業利益率\\n{fmt(t['営業利益率(%)'],1,'%')}", fillcolor="#D1FAE5"];
      TURN [label="投下資本回転率\\n{fmt(t['投下資本回転率(回)'],2,'回')}", fillcolor="#D1FAE5"];
      TAX [label="(1 − 実効税率)\\n税率 {fmt(t['実効税率(%)'],0,'%')}", fillcolor="#D1FAE5"];
      OPM -> ROIC; TURN -> ROIC; TAX -> ROIC;
      COGS [label="売上原価率\\n{fmt(t['売上原価率(%)'],1,'%')}"];
      SGA [label="販管費率\\n{fmt(t['販管費率(%)'],1,'%')}"];
      OP [label="営業利益\\n{fmt(t['営業利益'])}"];
      COGS -> OPM; SGA -> OPM; OP -> OPM;
      WC [label="運転資本\\n{fmt(t['運転資本'])}\\n回転率 {fmt(t['運転資本回転率(回)'],1,'回')}"];
      FA [label="固定資産\\n{fmt(t['固定資産'])}\\n回転率 {fmt(t['固定資産回転率(回)'],1,'回')}"];
      WC -> TURN; FA -> TURN;
      IC [label="投下資本\\n{fmt(t['投下資本'])}", fillcolor="#D1FAE5"];
      DEBT [label="有利子負債\\n{fmt(t['有利子負債'])}"];
      EQ [label="純資産\\n(非支配持分含む)\\n{fmt(t['純資産'])}"];
      DEBT -> IC; EQ -> IC; IC -> TURN [style=dashed];
    }}"""
    st.graphviz_chart(dot, width="stretch")

    st.subheader("ROIC vs 資本コスト")
    wacc = st.number_input("WACC (%) — 比較用のハードルレート", 0.0, 20.0, 6.0, 0.5)
    roic_ts = ratios.loc[("収益性", "ROIC(%)")]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=years, y=roic_ts, name="ROIC",
                         marker_color=[COLORS["green"] if v >= wacc else COLORS["red"]
                                       for v in roic_ts]))
    fig.add_hline(y=wacc, line_dash="dash", line_color=COLORS["gray"],
                  annotation_text=f"WACC {wacc}%")
    fig.update_layout(height=380, yaxis_title="ROIC(%)", margin=dict(t=30))
    st.plotly_chart(fig, width="stretch")
    spread = roic_ts[latest] - wacc
    st.markdown(f"**{latest} の ROICスプレッド: {fmt(spread, 1, 'pt')}** — "
                + ("資本コストを上回り、企業価値を創造しています。" if spread >= 0
                   else "資本コストを下回っています。収益性か資本効率の改善が必要です。"))

# ================================================================ CVP
with tabs[4]:
    st.subheader("CVP分析 (損益分岐点)")
    y = st.select_slider("年度", years, value=latest, key="cvp_year")
    est_vr = an.estimate_variable_ratio(pl)
    st.caption(f"高低点法による変動費率の推定値: {est_vr * 100:.1f}% (スライダーで調整可)")
    vr = st.slider("変動費率 (%)", 5.0, 95.0, round(est_vr * 100, 1), 0.5) / 100
    c = an.cvp(pl, y, vr)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"損益分岐点売上高 ({unit_label})", fmt(c["損益分岐点売上高"]))
    c2.metric("損益分岐点比率", fmt(c["損益分岐点比率(%)"], 1, "%"))
    c3.metric("安全余裕率", fmt(c["安全余裕率(%)"], 1, "%"))
    c4.metric("限界利益率", fmt(c["限界利益率(%)"], 1, "%"))

    max_s = max(c["売上高"], c["損益分岐点売上高"]) * 1.3
    xs = np.linspace(0, max_s, 100)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=xs, name="売上高線", line=dict(color=COLORS["blue"])))
    fig.add_trace(go.Scatter(x=xs, y=c["固定費"] + xs * vr, name="総費用線",
                             line=dict(color=COLORS["red"])))
    fig.add_trace(go.Scatter(x=xs, y=np.full_like(xs, c["固定費"]), name="固定費",
                             line=dict(color=COLORS["gray"], dash="dot")))
    if np.isfinite(c["損益分岐点売上高"]):
        fig.add_vline(x=c["損益分岐点売上高"], line_dash="dash", line_color=COLORS["orange"],
                      annotation_text=f"BEP {fmt(c['損益分岐点売上高'])}")
    fig.add_vline(x=c["売上高"], line_dash="dash", line_color=COLORS["green"],
                  annotation_text=f"実績 {fmt(c['売上高'])}")
    fig.update_layout(title=f"損益分岐点チャート ({y}, {unit_label})",
                      xaxis_title=f"売上高 ({unit_label})", yaxis_title=f"金額 ({unit_label})",
                      height=450, legend=dict(orientation="h", y=-0.2), margin=dict(t=50))
    st.plotly_chart(fig, width="stretch")

    st.dataframe(pd.DataFrame({k: [fmt(v, 1) if "率" in k else fmt(v)]
                               for k, v in c.items()}, index=["値"]).T
                 .rename(columns={"値": f"{y} ({unit_label} / %)"}),
                 width="stretch")

# ================================================================ シミュレーション
with tabs[5]:
    st.subheader("感応度シミュレーション")
    y = st.select_slider("基準年度", years, value=latest, key="sim_year")

    st.markdown("##### ドライバーを調整")
    cols = st.columns(3)
    params = {}
    for i, (key, label, unit, lo, hi, step, default) in enumerate(an.DRIVER_DEFS):
        with cols[i % 3]:
            params[key] = st.slider(f"{label} ({unit})", lo, hi, default, step, key=f"sl_{key}")

    res = an.simulate(pl, bs, y, params, tax_rate)
    base, sim = res["base"], res["sim"]

    st.markdown("##### 変化の結果")
    items = ["売上高", "営業利益", "経常利益", "当期純利益", "営業利益率(%)", "ROE(%)", "ROIC(%)"]
    mcols = st.columns(len(items))
    for col, item in zip(mcols, items):
        b, s = base[item], sim[item]
        is_pct = "%" in item
        col.metric(item, fmt(s, 1 if is_pct else 0, "%" if is_pct else ""),
                   f"{s - b:+,.1f}{'pt' if is_pct else ''}")

    left, right = st.columns(2)
    with left:
        comp = pd.DataFrame({"現状": base, "シミュレーション後": sim}).loc[
            ["売上高", "売上原価", "販管費", "営業利益", "当期純利益"]]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=comp.index, y=comp["現状"], name="現状",
                             marker_color=COLORS["gray"]))
        fig.add_trace(go.Bar(x=comp.index, y=comp["シミュレーション後"], name="シミュレーション後",
                             marker_color=COLORS["blue"]))
        fig.update_layout(title=f"PL比較 ({unit_label})", barmode="group", height=420,
                          legend=dict(orientation="h", y=-0.2), margin=dict(t=50))
        st.plotly_chart(fig, width="stretch")
    with right:
        # 営業利益のブリッジ (要因分解)
        p0 = {}
        steps, labels = [], []
        prev_op = base["営業利益"]
        applied = {}
        for key, label, unit, *_ in an.DRIVER_DEFS:
            if params.get(key):
                applied[key] = params[key]
                op_now = an.simulate(pl, bs, y, applied, tax_rate)["sim"]["営業利益"]
                steps.append(op_now - prev_op)
                labels.append(label)
                prev_op = op_now
        if steps:
            fig = go.Figure(go.Waterfall(
                x=["現状 営業利益"] + labels + ["シミュレーション後"],
                measure=["absolute"] + ["relative"] * len(steps) + ["total"],
                y=[base["営業利益"]] + steps + [None],
                text=[fmt(base["営業利益"])] + [f"{s:+,.0f}" for s in steps] + [fmt(sim["営業利益"])],
                textposition="outside"))
            fig.update_layout(title=f"営業利益ブリッジ ({unit_label})", height=420,
                              margin=dict(t=50))
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("スライダーを動かすと、要因別の営業利益ブリッジが表示されます。")

    st.markdown("##### トルネードチャート — どのドライバーに指標が最も反応するか")
    target = st.radio("対象指標", ["当期純利益", "営業利益", "ROIC(%)"], horizontal=True)
    tor = an.tornado(pl, bs, y, tax_rate, metric=target)
    fig = go.Figure()
    fig.add_trace(go.Bar(y=tor["ドライバー"], x=tor["増加時"], name="ドライバー増加時",
                         orientation="h", marker_color=COLORS["blue"]))
    fig.add_trace(go.Bar(y=tor["ドライバー"], x=tor["減少時"], name="ドライバー減少時",
                         orientation="h", marker_color=COLORS["orange"]))
    fig.update_layout(barmode="overlay", height=420,
                      xaxis_title=f"{target}の変化 ({'pt' if '%' in target else unit_label})",
                      legend=dict(orientation="h", y=-0.2), margin=dict(t=30))
    st.plotly_chart(fig, width="stretch")

st.sidebar.markdown("---")
st.sidebar.caption("残高は期末値ベースで計算しています。シミュレーションは簡易モデルであり、"
                   "実際の意思決定には詳細な検証が必要です。")
