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
PALETTE = ["#2563EB", "#EA580C", "#059669", "#7C3AED", "#DC2626", "#0891B2"]

# ---------------------------------------------------------------- テーマ
import plotly.io as pio

pio.templates["fin"] = go.layout.Template(layout=dict(
    font=dict(family="'Helvetica Neue', 'Hiragino Sans', 'Noto Sans JP', sans-serif",
              color="#1F2937", size=13),
    colorway=PALETTE,
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(gridcolor="#EEF2F7", zerolinecolor="#E5E7EB"),
    yaxis=dict(gridcolor="#EEF2F7", zerolinecolor="#E5E7EB"),
    hoverlabel=dict(bgcolor="white", font_size=13),
))
pio.templates.default = "plotly_white+fin"

st.markdown("""<style>
h1, h2, h3 {font-weight: 700; letter-spacing: -0.01em;}
[data-testid="stMetric"] {
    background: #F8FAFC; border: 1px solid #E5E7EB;
    border-radius: 12px; padding: 12px 14px;
}
[data-testid="stMetricLabel"] {color: #6B7280;}
div[data-testid="stExpander"] {border-radius: 12px;}
div[data-testid="stDataFrame"] {border: 1px solid #E5E7EB; border-radius: 12px;}
button[data-baseweb="tab"] {font-weight: 600;}
</style>""", unsafe_allow_html=True)


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


@st.cache_data(show_spinner=False)
def load_info(data: bytes):
    return loader.load_company_info(io.BytesIO(data))


# ---------------------------------------------------------------- sidebar
import edinet

st.sidebar.title("📊 財務分析ビジュアライザー")
source = st.sidebar.radio("データソース",
                          ["ファイルアップロード", "サンプルデータ", "EDINETから自動取得"],
                          key="source")

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

# --- 企業データ (従業員数・株式数・配当) の追加読み込み
info_df = pd.DataFrame()
info_up = st.sidebar.file_uploader(
    "企業データを追加 (任意)", type=["xlsx", "xls"], key="info_file",
    help="SPEEDAの「企業データ (CompanyInfo)」ファイル。従業員数から生産性指標を計算し、"
         "発行済株式数・1株配当をバリュエーションに自動入力します")
if info_up is not None:
    try:
        info_df = load_info(info_up.getvalue())
        if info_df.empty:
            st.sidebar.warning("企業データとして認識できませんでした")
        else:
            st.sidebar.success(f"企業データ取込: {', '.join(info_df.index[:4])} 等")
    except Exception as e:
        st.sidebar.error(f"企業データ読み込みエラー: {e}")

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
if not info_df.empty:
    prod = an.productivity(pl, bs, info_df)
    if not prod.empty:
        ratios = pd.concat([ratios, prod])

# ナビゲーション: st.tabsは全タブをDOMに描画するため、ウィジェット操作の再実行で
# 全タブが同時表示される既知の不具合がある。選択ページのみ描画する方式に変更。
PAGES = ["🏠 ダッシュボード", "📈 概要", "📋 財務指標", "🌳 DuPont分析",
         "🌲 ROICツリー", "⚖️ CVP分析", "🎛 シミュレーション",
         "🆚 複数社比較", "💰 DCF評価", "📄 レポート"]
try:
    page = st.segmented_control("ページ", PAGES, default=PAGES[0],
                                label_visibility="collapsed", key="nav")
except (AttributeError, TypeError):  # 古いStreamlit向けフォールバック
    page = st.radio("ページ", PAGES, horizontal=True,
                    label_visibility="collapsed", key="nav")
if page is None:
    page = PAGES[0]
st.markdown("---")


# ================================================================ ダッシュボード
def fmt_jpy(v: float) -> str:
    """百万円単位の値を 兆/億 表記に変換 (単位表示が百万円のときのみ)。"""
    if not np.isfinite(v):
        return "―"
    if unit_label == "百万円":
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:,.2f}兆円"
        if abs(v) >= 10_000:
            return f"{v / 10_000:,.0f}億円"
        return f"{v:,.0f}百万円"
    return f"{v:,.0f}{unit_label}"


def dash_card(col, title: str, series: pd.Series, kind: str = "money", key: str = ""):
    """バフェットコード風の指標カード (値+前年差+年次ミニチャート)。"""
    s = series.dropna() if isinstance(series, pd.Series) else pd.Series(dtype=float)
    with col.container(border=True):
        st.markdown(f"<div style='font-size:0.78rem;color:#6B7280'>{title}</div>",
                    unsafe_allow_html=True)
        if s.empty:
            st.markdown("―")
            return
        v = float(s.iloc[-1])
        txt = {"money": fmt_jpy(v), "pct": f"{v:,.1f}%", "times": f"{v:,.2f}倍",
               "turn": f"{v:,.2f}回", "days": f"{v:,.1f}日",
               "yen": f"{v:,.1f}円", "people": f"{v:,.0f}人"}.get(kind, f"{v:,.1f}")
        delta_html = ""
        if len(s) >= 2 and np.isfinite(s.iloc[-2]) and s.iloc[-2] != 0:
            if kind in ("money", "yen"):
                d = (v - s.iloc[-2]) / abs(s.iloc[-2]) * 100
                dtxt = f"{d:+.1f}%"
            elif kind == "people":
                d = v - s.iloc[-2]
                dtxt = f"{d:+,.0f}人"
            else:
                d = v - s.iloc[-2]
                dtxt = f"{d:+.2f}pt" if kind == "pct" else f"{d:+.2f}"
            c = "#059669" if d >= 0 else "#DC2626"
            delta_html = (f"<span style='font-size:0.75rem;color:{c};"
                          f"margin-left:6px'>{dtxt}</span>")
        st.markdown(f"<div><span style='font-size:1.4rem;font-weight:700;"
                    f"color:#1E3A8A'>{txt}</span>{delta_html}</div>",
                    unsafe_allow_html=True)
        if len(s) >= 2:
            colors = ["#BFDBFE"] * (len(s) - 1) + ["#2563EB"]
            fig = go.Figure(go.Bar(x=[str(i) for i in s.index], y=s.values,
                                   marker_color=colors))
            fig.update_layout(height=64, margin=dict(l=0, r=0, t=4, b=0),
                              showlegend=False, xaxis=dict(visible=False),
                              yaxis=dict(visible=False),
                              paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, width="stretch", key=f"spark_{key}",
                            config={"displayModeBar": False, "staticPlot": True})


if page == "🏠 ダッシュボード":
    import valuation

    debt_s = (bs.loc["短期借入金"] if "短期借入金" in bs.index else 0) + \
             (bs.loc["長期借入金"] if "長期借入金" in bs.index else 0)
    if not isinstance(debt_s, pd.Series):
        debt_s = pd.Series(np.nan, index=years)
    eq_s = an.equity_series(bs)

    st.markdown("##### 業績")
    cols = st.columns(4)
    dash_card(cols[0], f"売上高 ({latest})", pl.loc["売上高"], "money", "sales")
    dash_card(cols[1], "営業利益", pl.loc["営業利益"], "money", "op")
    dash_card(cols[2], "当期純利益", pl.loc["当期純利益"], "money", "ni")
    dash_card(cols[3], "営業利益率", ratios.loc[("収益性", "営業利益率(%)")], "pct", "opm")

    st.markdown("##### 収益性・効率性")
    cols = st.columns(4)
    dash_card(cols[0], "ROE (自己資本ベース)", ratios.loc[("収益性", "ROE(%)")], "pct", "roe")
    dash_card(cols[1], "ROA", ratios.loc[("収益性", "ROA(%)")], "pct", "roa")
    dash_card(cols[2], "ROIC", ratios.loc[("収益性", "ROIC(%)")], "pct", "roic")
    dash_card(cols[3], "CCC", ratios.loc[("効率性", "CCC(日)")], "days", "ccc")

    st.markdown("##### 財務・キャッシュフロー")
    cols = st.columns(4)
    dash_card(cols[0], "総資産", bs.loc["資産合計"], "money", "assets")
    dash_card(cols[1], "自己資本比率", ratios.loc[("安全性", "自己資本比率(%)")], "pct", "eqr")
    dash_card(cols[2], "有利子負債", debt_s, "money", "debt")
    if not cf.empty and ("CF", "フリーCF") in ratios.index:
        dash_card(cols[3], "フリーCF", ratios.loc[("CF", "フリーCF")], "money", "fcf")
    else:
        dash_card(cols[3], "D/Eレシオ", ratios.loc[("安全性", "D/Eレシオ(倍)")], "times", "de")

    # ---------------- 生産性 (従業員1人あたり)
    if ("生産性", "1人あたり売上高") in ratios.index:
        st.markdown("##### 生産性 (従業員1人あたり)")
        cols = st.columns(4)
        dash_card(cols[0], "期末従業員数", ratios.loc[("生産性", "従業員数(人)")],
                  "people", "emp")
        dash_card(cols[1], "1人あたり売上高", ratios.loc[("生産性", "1人あたり売上高")],
                  "money", "emp_sales")
        dash_card(cols[2], "1人あたり営業利益", ratios.loc[("生産性", "1人あたり営業利益")],
                  "money", "emp_op")
        if ("生産性", "労働分配率(%)") in ratios.index:
            dash_card(cols[3], "労働分配率 (人件費÷粗利)",
                      ratios.loc[("生産性", "労働分配率(%)")], "pct", "labor_share")
        else:
            dash_card(cols[3], "1人あたり当期純利益",
                      ratios.loc[("生産性", "1人あたり当期純利益")], "money", "emp_ni")
        st.caption("従業員数は期末値 (臨時・パートを除く)。1人あたり指標の単位は"
                   f"{unit_label}/人。")

    # ---------------- バリュエーション
    st.markdown("##### バリュエーション")
    with st.expander("💹 株価・株式数の設定", expanded="price" not in st.session_state):
        st.session_state.setdefault("price", 0.0)
        c1, c2, c3, c4 = st.columns(4)
        code_in = c1.text_input("証券コード (4桁)", st.session_state.get("val_code", ""))
        if c1.button("株価を自動取得", disabled=not code_in):
            q, fetch_log = valuation.fetch_price(code_in)
            if q:
                st.session_state["price"] = q["price"]
                st.session_state["val_code"] = code_in
                st.success(f"{q['price']:,.1f}円 ({q['source']})")
            else:
                st.error("自動取得できませんでした。株価を手入力してください。")
                for line in fetch_log:
                    st.caption(f"・{line}")
                st.caption("※ Streamlit Cloud等のクラウド環境ではYahooにブロックされる"
                           "ことがあります。ローカル実行では成功する場合があります。")
        shares_default, dps_default = 0.0, 0.0
        if not info_df.empty:
            if "発行済株式数" in info_df.index:
                sh = info_df.loc["発行済株式数"].dropna()
                if len(sh):
                    shares_default = float(sh.iloc[-1]) / 1e6  # 株 → 百万株
            if "1株配当" in info_df.index:
                dv = info_df.loc["1株配当"].dropna()
                if len(dv):
                    dps_default = float(dv.iloc[-1])
        price = c2.number_input("株価 (円)", 0.0, step=1.0, key="price")
        shares = c3.number_input("発行済株式数 (百万株)", 0.0, step=1.0,
                                 value=round(shares_default, 1),
                                 help="自己株式控除後。企業データ読込時は自動入力")
        dps = c4.number_input("1株配当 (円/年)", 0.0, step=1.0, value=dps_default)
        if shares_default:
            st.caption("発行済株式数・1株配当は企業データ (最新期) から自動入力済み。")
        st.caption("財務データの単位が百万円であることを前提に計算します。")

    if price > 0 and shares > 0:
        ni_latest = float(pl.loc["当期純利益", latest])
        eq_latest = float(eq_s[latest])
        val = valuation.compute(price, shares, dps, ni_latest, eq_latest)
        cols = st.columns(6)
        specs = [("時価総額", "時価総額(百万円)", "money"),
                 ("PER", "PER(倍)", "times"), ("PBR", "PBR(倍)", "times"),
                 ("EPS", "EPS(円)", "yen"), ("BPS", "BPS(円)", "yen"),
                 ("配当利回り", "配当利回り(%)", "pct")]
        for col, (label, k, kind) in zip(cols, specs):
            dash_card(col, label, pd.Series([val[k]], index=[latest]), kind,
                      f"val_{k}")
    else:
        st.info("株価と発行済株式数を入力すると、時価総額・PER・PBR・EPS・BPS・配当利回りを表示します。")

# ================================================================ 概要
if page == "📈 概要":
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
if page == "📋 財務指標":
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
if page == "🌳 DuPont分析":
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
if page == "🌲 ROICツリー":
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
if page == "⚖️ CVP分析":
    st.subheader("CVP分析 (損益分岐点)")
    y = st.select_slider("年度", years, value=latest, key="cvp_year")
    est_vr = an.estimate_variable_ratio(pl)
    reg = an.regression_cvp(pl)

    method = st.radio("変動費率の推定方法",
                      ["散布図法 (回帰)", "高低点法", "手動"], horizontal=True,
                      help="散布図法: 各期の売上高と営業利益を回帰 (バフェットコード方式)。"
                           "高低点法: 売上最大期と最小期の2点から推定。")
    if method == "散布図法 (回帰)":
        if reg is None:
            st.warning("散布図法には3期以上のデータが必要です。高低点法を使用します。")
            vr = est_vr
        elif not (0 < reg["変動費率"] < 1) or reg["固定費"] <= 0:
            st.warning(f"回帰結果が経済的に不安定です (限界利益率 {reg['限界利益率(%)']:.1f}%、"
                       f"固定費 {reg['固定費']:,.0f}{unit_label})。事業構造が期間中に変化して"
                       "いる可能性があります。分析対象期間を狭めるか、高低点法/手動をご利用"
                       "ください。ここでは高低点法の値を使用します。")
            vr = est_vr
        else:
            vr = reg["変動費率"]
            note = " ⚠️ R²が低く、費用構造が期間中に変化している可能性があります。" \
                if reg["R2"] < 0.7 else ""
            st.caption(f"限界利益率 {reg['限界利益率(%)']:.2f}% / "
                       f"通期固定費 {reg['固定費']:,.0f}{unit_label} / "
                       f"R² = {reg['R2']:.2f} (対象: {years[0]}〜{years[-1]}){note}")
    elif method == "高低点法":
        vr = est_vr
        st.caption(f"高低点法による変動費率: {est_vr * 100:.1f}%")
    else:
        vr = st.slider("変動費率 (%)", 5.0, 95.0, round(est_vr * 100, 1), 0.5) / 100

    # --- 散布図法の回帰チャート
    if reg is not None:
        with st.expander("📉 散布図法の回帰チャート (売上高 × 営業利益)",
                         expanded=(method == "散布図法 (回帰)")):
            labels, xs_pt, ys_pt = zip(*reg["点"])
            x_max = max(xs_pt) * 1.15
            line_x = np.array([0, x_max])
            line_y = reg["傾き"] * line_x + reg["切片"]
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=list(xs_pt), y=list(ys_pt), mode="markers", name="実績 (各期)",
                marker=dict(size=10, color=COLORS["blue"]),
                text=list(labels),
                hovertemplate="%{text}<br>売上高 %{x:,.0f}<br>営業利益 %{y:,.0f}<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=line_x, y=line_y, mode="lines", name="回帰直線",
                line=dict(color=COLORS["blue"], width=2)))
            fig.add_annotation(
                xref="paper", yref="paper", x=0.99, y=0.98, showarrow=False,
                align="right",
                text=(f"限界利益率 = {reg['限界利益率(%)']:.3f}%<br>"
                      f"通期固定費 = {reg['固定費']:,.0f}{unit_label}<br>"
                      f"R² = {reg['R2']:.2f}"))
            fig.update_layout(height=420,
                              xaxis_title=f"売上高 ({unit_label})",
                              yaxis_title=f"営業利益 ({unit_label})",
                              legend=dict(orientation="h", y=-0.25),
                              margin=dict(t=30))
            st.plotly_chart(fig, width="stretch")

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
if page == "🎛 シミュレーション":
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

    # ---------------- シナリオ保存
    st.markdown("##### シナリオ保存・比較")
    sc1, sc2 = st.columns([2, 5])
    with sc1:
        scen_name = st.text_input("シナリオ名", placeholder="例: 楽観 / 悲観 / 値上げ実施")
        if st.button("💾 現在の設定を保存", disabled=not scen_name):
            st.session_state.setdefault("scenarios", {})[scen_name] = dict(params)
            st.success(f"「{scen_name}」を保存しました")
        if st.session_state.get("scenarios") and st.button("🗑 全シナリオを削除"):
            st.session_state["scenarios"] = {}
            st.rerun()
    scenarios = st.session_state.get("scenarios", {})
    if scenarios:
        rows = {"現状 (ベース)": base}
        for nm, ps in scenarios.items():
            rows[nm] = an.simulate(pl, bs, y, ps, tax_rate)["sim"]
        scen_df = pd.DataFrame(rows).loc[
            ["売上高", "営業利益", "当期純利益", "営業利益率(%)", "ROE(%)", "ROIC(%)"]]
        with sc2:
            st.dataframe(scen_df.round(1), width="stretch")
        fig = go.Figure()
        for i, nm in enumerate(scen_df.columns):
            fig.add_trace(go.Bar(x=["営業利益", "当期純利益"],
                                 y=[scen_df.loc["営業利益", nm], scen_df.loc["当期純利益", nm]],
                                 name=nm, marker_color=PALETTE[i % len(PALETTE)]))
        fig.update_layout(title=f"シナリオ別の利益比較 ({unit_label})", barmode="group",
                          height=380, legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, width="stretch")
        import json
        st.download_button("⬇️ シナリオをJSON保存",
                           json.dumps(scenarios, ensure_ascii=False, indent=2),
                           file_name="scenarios.json", mime="application/json")

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

# ================================================================ 複数社比較
if page == "🆚 複数社比較":
    st.subheader("複数社比較")
    cmp_files = st.file_uploader(
        "比較する会社の財務諸表を追加 (複数選択可)", type=["xlsx", "xls", "csv"],
        accept_multiple_files=True, key="cmp_files",
        help="SPEEDAエクスポートや自作テンプレートをそのまま追加できます")

    companies: dict = {}
    main_name = st.text_input("現在読み込み中のデータの表示名", "メイン", max_chars=20)
    companies[main_name] = (pl, bs, cf)
    for f in cmp_files or []:
        try:
            s = load_file(f.getvalue(), f.name)
            if loader.validate(s):
                st.warning(f"{f.name}: 必須科目が不足しています (読み込みはスキップ)")
                continue
            cname = f.name.rsplit(".", 1)[0][:25]
            companies[cname] = (s["PL"], s["BS"], s["CF"])
        except Exception as e:
            st.warning(f"{f.name}: 読み込みエラー ({e})")

    if len(companies) < 2:
        st.info("2社以上になるとレーダーチャート・推移比較・比較表を表示します。"
                "上のアップローダーに他社のファイルを追加してください。")
    else:
        all_ratios = {n: an.compute_ratios(p, b, c, tax_rate)
                      for n, (p, b, c) in companies.items()}

        # --- 最新期の比較表
        st.markdown("##### 最新期の主要指標比較")
        key_metrics = [("収益性", "営業利益率(%)"), ("収益性", "ROE(%)"),
                       ("収益性", "ROIC(%)"), ("効率性", "総資産回転率(回)"),
                       ("安全性", "自己資本比率(%)"), ("成長性", "売上高成長率(%)"),
                       ("効率性", "CCC(日)")]
        comp_table = pd.DataFrame({
            n: {m[1]: r.loc[m].dropna().iloc[-1] if not r.loc[m].dropna().empty else np.nan
                for m in key_metrics if m in r.index}
            for n, r in all_ratios.items()})
        st.dataframe(comp_table.round(2), width="stretch")

        # --- レーダーチャート (0-1正規化)
        left, right = st.columns(2)
        with left:
            radar_metrics = ["営業利益率(%)", "ROE(%)", "ROIC(%)",
                             "総資産回転率(回)", "自己資本比率(%)", "売上高成長率(%)"]
            norm = comp_table.loc[[m for m in radar_metrics if m in comp_table.index]]
            rng = norm.max(axis=1) - norm.min(axis=1)
            norm01 = norm.sub(norm.min(axis=1), axis=0).div(rng.replace(0, 1), axis=0)
            fig = go.Figure()
            for i, n in enumerate(norm01.columns):
                fig.add_trace(go.Scatterpolar(
                    r=list(norm01[n]) + [norm01[n].iloc[0]],
                    theta=list(norm01.index) + [norm01.index[0]],
                    name=n, fill="toself", opacity=0.55,
                    line=dict(color=PALETTE[i % len(PALETTE)])))
            fig.update_layout(title="総合バランス (各指標を社間で0-1正規化)",
                              height=430, polar=dict(radialaxis=dict(visible=False)),
                              legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, width="stretch")
        with right:
            cats = all_ratios[main_name].index.tolist()
            sel = st.selectbox("推移を比較する指標",
                               [f"{c} | {m}" for c, m in cats],
                               index=cats.index(("収益性", "ROE(%)")))
            cat, met = sel.split(" | ")
            fig = go.Figure()
            for i, (n, r) in enumerate(all_ratios.items()):
                if (cat, met) in r.index:
                    s = r.loc[(cat, met)].dropna().tail(10)
                    fig.add_trace(go.Scatter(
                        x=list(range(-len(s) + 1, 1)), y=s.values,
                        mode="lines+markers", name=n, text=list(s.index),
                        line=dict(color=PALETTE[i % len(PALETTE)], width=3),
                        hovertemplate="%{text}<br>%{y:.2f}<extra>" + n + "</extra>"))
            fig.update_layout(title=f"{met} の推移 (直近10期・0=最新期)",
                              height=430, xaxis_title="期 (相対)",
                              legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, width="stretch")
        st.caption("決算期が異なる会社は「最新期を0」とする相対軸で重ねています。")

# ================================================================ DCF評価
if page == "💰 DCF評価":
    st.subheader("DCF簡易企業価値評価")
    st.caption("FCFを予測してWACCで割り引く2段階モデル。教育・スクリーニング用の簡易版です。")

    fcf_default = 0.0
    if ("CF", "フリーCF") in ratios.index:
        s = ratios.loc[("CF", "フリーCF")].dropna()
        if len(s) >= 3:
            fcf_default = float(s.tail(3).mean())  # 直近3期平均でならす
        elif len(s):
            fcf_default = float(s.iloc[-1])

    debt_latest = float((bs.loc["短期借入金", latest] if "短期借入金" in bs.index else 0)
                        + (bs.loc["長期借入金", latest] if "長期借入金" in bs.index else 0))
    cash_latest = float(bs.loc["現金及び預金", latest]) if "現金及び預金" in bs.index else 0.0

    c1, c2, c3 = st.columns(3)
    base_fcf = c1.number_input(f"基準FCF ({unit_label}/年)", value=round(fcf_default),
                               step=1000, help="デフォルトは直近3期平均のフリーCF")
    g1 = c1.slider("予測期間の成長率 (%/年)", -10.0, 20.0, 3.0, 0.5)
    n_years = c2.slider("予測期間 (年)", 3, 10, 5)
    g2 = c2.slider("永久成長率 (%)", -1.0, 3.0, 0.5, 0.25)
    wacc = c3.slider("WACC (%)", 3.0, 15.0, 6.0, 0.25)
    net_debt = c3.number_input(f"ネット有利子負債 ({unit_label})",
                               value=round(debt_latest - cash_latest), step=1000,
                               help="有利子負債 − 現金及び預金 (自動計算値を修正可)")

    if wacc / 100 <= g2 / 100:
        st.error("WACCは永久成長率より大きい必要があります。")
    elif base_fcf <= 0:
        st.warning("基準FCFがゼロ以下です。FCFがプラスの企業向けの手法のため、値を調整してください。")
    else:
        w, gg1, gg2 = wacc / 100, g1 / 100, g2 / 100
        fcfs = [base_fcf * (1 + gg1) ** t for t in range(1, n_years + 1)]
        pvs = [f / (1 + w) ** t for t, f in enumerate(fcfs, 1)]
        tv = fcfs[-1] * (1 + gg2) / (w - gg2)
        pv_tv = tv / (1 + w) ** n_years
        ev = sum(pvs) + pv_tv
        eq_val = ev - net_debt

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("事業価値 (EV)", fmt_jpy(ev))
        m2.metric("ネット有利子負債", fmt_jpy(net_debt))
        m3.metric("株主価値", fmt_jpy(eq_val))
        shares_dcf = st.session_state.get("dcf_shares", 0.0)
        with m4:
            shares_dcf = st.number_input("発行済株式数 (百万株)", 0.0, step=1.0,
                                         key="dcf_shares")
        if shares_dcf > 0:
            st.metric("理論株価", f"{eq_val / shares_dcf:,.0f}円",
                      help="株主価値 ÷ 発行済株式数")

        left, right = st.columns(2)
        with left:
            fig = go.Figure()
            xs = [f"{t}年後" for t in range(1, n_years + 1)]
            fig.add_trace(go.Bar(x=xs, y=fcfs, name="予測FCF",
                                 marker_color="#BFDBFE"))
            fig.add_trace(go.Bar(x=xs, y=pvs, name="現在価値",
                                 marker_color=COLORS["blue"]))
            fig.update_layout(title=f"FCF予測と現在価値 ({unit_label})",
                              barmode="group", height=400,
                              legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, width="stretch")
        with right:
            waccs = [w * 100 + d for d in (-2, -1, -0.5, 0, 0.5, 1, 2)]
            gs = [g2 + d for d in (-1, -0.5, 0, 0.5, 1)]
            mat = pd.DataFrame(
                [[(base_fcf * (1 + gg1) ** n_years * (1 + gv / 100) / (wv / 100 - gv / 100)
                   / (1 + wv / 100) ** n_years
                   + sum(base_fcf * (1 + gg1) ** t / (1 + wv / 100) ** t
                         for t in range(1, n_years + 1)) - net_debt)
                  if wv / 100 > gv / 100 else np.nan for gv in gs] for wv in waccs],
                index=[f"WACC {v:.1f}%" for v in waccs],
                columns=[f"g {v:.2f}%" for v in gs])
            st.markdown(f"**株主価値の感応度 ({unit_label})**")
            try:
                st.dataframe(mat.style.format("{:,.0f}").background_gradient(
                    cmap="RdYlGn", axis=None), width="stretch")
            except (AttributeError, ImportError):  # jinja2/matplotlib欠如時
                st.dataframe(mat.round(0), width="stretch")

# ================================================================ レポート
if page == "📄 レポート":
    st.subheader("分析レポート出力")
    st.caption("チャートと指標表を1つのHTMLにまとめます。ブラウザで開き、印刷 (⌘P) から"
               "PDFとして保存できます。")
    rep_name = st.text_input("レポートの表題 (会社名など)", "財務分析レポート")
    if st.button("📄 レポートを生成", type="primary"):
        import report
        html = report.build_html(rep_name, pl, bs, cf, ratios, unit_label, tax_rate)
        st.download_button("⬇️ HTMLレポートをダウンロード", html.encode("utf-8"),
                           file_name=f"{rep_name}.html", mime="text/html")
        st.success("生成しました。ダウンロード後、ブラウザで開いて印刷からPDF保存できます。")

st.sidebar.markdown("---")
st.sidebar.caption("残高は期末値ベースで計算しています。シミュレーションは簡易モデルであり、"
                   "実際の意思決定には詳細な検証が必要です。")
