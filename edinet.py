# -*- coding: utf-8 -*-
"""EDINET API v2 から有価証券報告書のXBRLデータを取得し、財務諸表に変換する。

- APIキーは https://api.edinet-fsa.go.jp/ で無料発行 (要メール登録)
- 有報1件に当期+前期が含まれるため、N年分は N 件の有報から重複込みで構築
- 日本基準 (jppfs) と IFRS (jpigp) の主要科目に対応 (ベストエフォート)
"""
from __future__ import annotations

import datetime as dt
import io
import zipfile

import pandas as pd
import requests

API = "https://api.edinet-fsa.go.jp/api/v2"
DOC_TYPE_ANNUAL = "120"  # 有価証券報告書


class EdinetError(Exception):
    pass


# canonical科目 → (表, [XBRL要素IDの優先順リスト])
ELEMENT_MAP = {
    # ---------------- PL (Duration)
    "売上高": ("PL", ["jppfs_cor:NetSales", "jpigp_cor:RevenueIFRS",
                       "jpcrp_cor:RevenuesUSGAAPSummaryOfBusinessResults",
                       "jppfs_cor:OperatingRevenue1", "jppfs_cor:OperatingRevenue2",
                       "jpigp_cor:OperatingRevenuesIFRS"]),
    "売上原価": ("PL", ["jppfs_cor:CostOfSales", "jpigp_cor:CostOfSalesIFRS"]),
    "売上総利益": ("PL", ["jppfs_cor:GrossProfit", "jpigp_cor:GrossProfitIFRS"]),
    "販売費及び一般管理費": ("PL", ["jppfs_cor:SellingGeneralAndAdministrativeExpenses",
                                     "jpigp_cor:SellingGeneralAndAdministrativeExpensesIFRS"]),
    "営業利益": ("PL", ["jppfs_cor:OperatingIncome", "jpigp_cor:OperatingProfitLossIFRS"]),
    "営業外収益": ("PL", ["jppfs_cor:NonOperatingIncome", "jpigp_cor:FinanceIncomeIFRS"]),
    "営業外費用": ("PL", ["jppfs_cor:NonOperatingExpenses", "jpigp_cor:FinanceCostsIFRS"]),
    "支払利息": ("PL", ["jppfs_cor:InterestExpensesNOE", "jpigp_cor:InterestExpensesIFRS"]),
    "経常利益": ("PL", ["jppfs_cor:OrdinaryIncome"]),
    "特別利益": ("PL", ["jppfs_cor:ExtraordinaryIncome"]),
    "特別損失": ("PL", ["jppfs_cor:ExtraordinaryLoss"]),
    "税引前当期純利益": ("PL", ["jppfs_cor:IncomeBeforeIncomeTaxes",
                                 "jpigp_cor:ProfitLossBeforeTaxIFRS"]),
    "法人税等": ("PL", ["jppfs_cor:IncomeTaxes", "jpigp_cor:IncomeTaxExpenseIFRS"]),
    "当期純利益": ("PL", ["jppfs_cor:ProfitLossAttributableToOwnersOfParent",
                           "jpigp_cor:ProfitLossAttributableToOwnersOfParentIFRS",
                           "jppfs_cor:ProfitLoss", "jpigp_cor:ProfitLossIFRS"]),
    # ---------------- BS (Instant)
    "現金及び預金": ("BS", ["jppfs_cor:CashAndDeposits", "jpigp_cor:CashAndCashEquivalentsIFRS"]),
    "売上債権": ("BS", ["jppfs_cor:NotesAndAccountsReceivableTrade",
                         "jppfs_cor:NotesAndAccountsReceivableTradeAndContractAssets",
                         "jppfs_cor:AccountsReceivableTrade",
                         "jpigp_cor:TradeAndOtherReceivablesCAIFRS"]),
    "棚卸資産": ("BS", ["jppfs_cor:Inventories", "jppfs_cor:MerchandiseAndFinishedGoods",
                         "jpigp_cor:InventoriesCAIFRS", "jppfs_cor:Merchandise"]),
    "流動資産合計": ("BS", ["jppfs_cor:CurrentAssets", "jpigp_cor:TotalCurrentAssetsIFRS",
                             "jpigp_cor:CurrentAssetsIFRS"]),
    "有形固定資産": ("BS", ["jppfs_cor:PropertyPlantAndEquipment",
                             "jpigp_cor:PropertyPlantAndEquipmentIFRS"]),
    "無形固定資産": ("BS", ["jppfs_cor:IntangibleAssets",
                             "jpigp_cor:IntangibleAssetsIFRS"]),
    "投資その他の資産": ("BS", ["jppfs_cor:InvestmentsAndOtherAssets"]),
    "固定資産合計": ("BS", ["jppfs_cor:NoncurrentAssets", "jpigp_cor:TotalNonCurrentAssetsIFRS",
                             "jpigp_cor:NonCurrentAssetsIFRS"]),
    "資産合計": ("BS", ["jppfs_cor:Assets", "jpigp_cor:TotalAssetsIFRS", "jpigp_cor:AssetsIFRS"]),
    "仕入債務": ("BS", ["jppfs_cor:NotesAndAccountsPayableTrade",
                         "jppfs_cor:AccountsPayableTrade",
                         "jpigp_cor:TradeAndOtherPayablesCLIFRS"]),
    "短期借入金": ("BS", ["jppfs_cor:ShortTermLoansPayable",
                           "jpigp_cor:BorrowingsCLIFRS", "jppfs_cor:ShortTermBorrowings"]),
    "流動負債合計": ("BS", ["jppfs_cor:CurrentLiabilities",
                             "jpigp_cor:TotalCurrentLiabilitiesIFRS",
                             "jpigp_cor:CurrentLiabilitiesIFRS"]),
    "長期借入金": ("BS", ["jppfs_cor:LongTermLoansPayable", "jppfs_cor:BondsPayable",
                           "jpigp_cor:BorrowingsNCLIFRS"]),
    "固定負債合計": ("BS", ["jppfs_cor:NoncurrentLiabilities",
                             "jpigp_cor:TotalNonCurrentLiabilitiesIFRS",
                             "jpigp_cor:NonCurrentLiabilitiesIFRS"]),
    "負債合計": ("BS", ["jppfs_cor:Liabilities", "jpigp_cor:TotalLiabilitiesIFRS",
                         "jpigp_cor:LiabilitiesIFRS"]),
    "純資産合計": ("BS", ["jppfs_cor:NetAssets", "jpigp_cor:TotalEquityIFRS",
                           "jpigp_cor:EquityIFRS",
                           "jpigp_cor:EquityAttributableToOwnersOfParentIFRS"]),
    # ---------------- CF (Duration)
    "営業活動によるキャッシュ・フロー": ("CF", [
        "jppfs_cor:NetCashProvidedByUsedInOperatingActivities",
        "jpigp_cor:NetCashProvidedByUsedInOperatingActivitiesIFRS"]),
    "投資活動によるキャッシュ・フロー": ("CF", [
        "jppfs_cor:NetCashProvidedByUsedInInvestmentActivities",
        "jppfs_cor:NetCashProvidedByUsedInInvestingActivities",
        "jpigp_cor:NetCashProvidedByUsedInInvestingActivitiesIFRS"]),
    "財務活動によるキャッシュ・フロー": ("CF", [
        "jppfs_cor:NetCashProvidedByUsedInFinancingActivities",
        "jpigp_cor:NetCashProvidedByUsedInFinancingActivitiesIFRS"]),
    "現金及び現金同等物の期末残高": ("CF", [
        "jppfs_cor:CashAndCashEquivalents",
        "jpigp_cor:CashAndCashEquivalentsIFRS"]),
}


def _norm_seccode(code: str) -> str:
    """証券コード4桁 → EDINETの5桁表記 (末尾0)。"""
    c = str(code).strip()
    return c + "0" if len(c) == 4 else c


def _get(url: str, params: dict, key: str, timeout=30) -> requests.Response:
    params = dict(params, **{"Subscription-Key": key})
    try:
        r = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        raise EdinetError(f"通信エラー: {e}") from e
    if r.status_code == 401:
        raise EdinetError("認証エラー (401): APIキーを確認してください")
    if r.status_code != 200:
        raise EdinetError(f"APIエラー (HTTP {r.status_code})")
    return r


def list_docs(date: dt.date, key: str) -> list[dict]:
    r = _get(f"{API}/documents.json", {"date": date.isoformat(), "type": 2}, key)
    return r.json().get("results") or []


def _is_target(doc: dict, sec5: str) -> bool:
    return (doc.get("secCode") == sec5 and doc.get("docTypeCode") == DOC_TYPE_ANNUAL
            and doc.get("xbrlFlag") == "1" and doc.get("csvFlag") == "1"
            and str(doc.get("withdrawalStatus", "0")) == "0")


def find_annual_reports(sec_code: str, key: str, num_years: int = 5,
                        progress=None) -> list[dict]:
    """直近の有報を日付走査で発見し、以降は提出周年±の窓で過去分を探す。"""
    sec5 = _norm_seccode(sec_code)
    today = dt.date.today()

    def report(msg, frac):
        if progress:
            progress(msg, frac)

    # --- 1) 直近の有報 (最大450日さかのぼる)
    latest = None
    d = today
    steps = 0
    while d > today - dt.timedelta(days=450) and latest is None:
        if d.weekday() < 5:  # 平日のみ
            steps += 1
            if steps % 5 == 0:
                report(f"直近の有価証券報告書を検索中... ({d.isoformat()})",
                       min(steps / 320, 0.5))
            for doc in list_docs(d, key):
                if _is_target(doc, sec5):
                    latest = (d, doc)
                    break
        d -= dt.timedelta(days=1)
    if latest is None:
        raise EdinetError(f"証券コード {sec_code} の有価証券報告書が過去450日に見つかりません")

    found = [latest[1]]
    anchor = latest[0]

    # --- 2) 過去分: 提出日の1年前±40日の窓を新しい側から走査
    for k in range(1, num_years):
        target = anchor - dt.timedelta(days=365 * k)
        got = None
        for off in range(-15, 41):
            d = target + dt.timedelta(days=off)
            if d.weekday() >= 5 or d >= today:
                continue
            for doc in list_docs(d, key):
                if _is_target(doc, sec5):
                    got = doc
                    break
            if got:
                break
        report(f"{k + 1}期分の有報を検索中...", 0.5 + 0.4 * k / max(num_years - 1, 1))
        if got:
            found.append(got)
        # 見つからない年はスキップ (前期データで補完される)
    return found


def download_csv(doc_id: str, key: str) -> pd.DataFrame:
    """XBRL-CSV (type=5) をダウンロードして結合したDataFrameを返す。"""
    r = _get(f"{API}/documents/{doc_id}", {"type": 5}, key, timeout=90)
    frames = []
    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for name in z.namelist():
                if name.lower().endswith(".csv") and "jpcrp" in name.lower():
                    with z.open(name) as fh:
                        frames.append(pd.read_csv(fh, sep="\t", encoding="utf-16",
                                                  dtype=str))
    except zipfile.BadZipFile:
        raise EdinetError(f"書類 {doc_id} のCSVを取得できませんでした")
    if not frames:
        raise EdinetError(f"書類 {doc_id} にCSVデータが含まれていません")
    return pd.concat(frames, ignore_index=True)


def extract_values(csv_df: pd.DataFrame) -> dict[str, dict]:
    """CSVから当期(cur)・前期(prior)の科目値を抽出する。"""
    df = csv_df
    if "要素ID" not in df.columns or "値" not in df.columns:
        raise EdinetError("CSVのフォーマットが想定と異なります")
    ctx_col = "コンテキストID"
    out = {"cur": {}, "prior": {}}
    for canon, (stype, elements) in ELEMENT_MAP.items():
        kind = "Instant" if stype == "BS" else "Duration"
        for period, ctx_prefix in [("cur", "CurrentYear"), ("prior", "Prior1Year")]:
            ctx = f"{ctx_prefix}{kind}"
            for el in elements:
                rows = df[(df["要素ID"] == el) & (df[ctx_col] == ctx)]
                if rows.empty:
                    continue
                try:
                    val = float(str(rows.iloc[0]["値"]).replace(",", ""))
                except (ValueError, TypeError):
                    continue
                out[period][(stype, canon)] = val
                break
    return out


def _year_label(period_end: str, offset: int = 0) -> str:
    d = dt.date.fromisoformat(period_end)
    return f"{d.year - offset}/{d.month:02d}期"


def fetch_financials(sec_code: str, key: str, num_years: int = 5,
                     progress=None) -> dict[str, pd.DataFrame]:
    """有報N年分からPL/BS/CFのDataFrame (loader互換形式) を構築する。"""
    def report(msg, frac):
        if progress:
            progress(msg, frac)

    docs = find_annual_reports(sec_code, key, num_years, progress)
    data: dict[str, dict] = {}  # year_label -> {(stype, item): val}
    for i, doc in enumerate(docs):
        report(f"XBRLデータをダウンロード中... ({i + 1}/{len(docs)})",
               0.9 + 0.1 * i / len(docs))
        period_end = doc.get("periodEnd")
        if not period_end:
            continue
        vals = extract_values(download_csv(doc["docID"], key))
        for period, offset in [("cur", 0), ("prior", 1)]:
            label = _year_label(period_end, offset)
            if vals[period]:
                merged = data.setdefault(label, {})
                for k, v in vals[period].items():
                    merged.setdefault(k, v)

    if not data:
        raise EdinetError("財務データを抽出できませんでした")

    years = sorted(data.keys())
    result = {"PL": {}, "BS": {}, "CF": {}}
    for label in years:
        for (stype, item), val in data[label].items():
            result[stype].setdefault(item, {})[label] = val
    out = {}
    for stype in ["PL", "BS", "CF"]:
        df = pd.DataFrame(result[stype]).T
        if not df.empty:
            df = df.reindex(columns=years)
        out[stype] = df

    # 単位: 円 → 百万円へ変換
    for stype, df in out.items():
        if not df.empty:
            out[stype] = df / 1_000_000

    import loader
    loader._fill_derived(out)
    report("完了", 1.0)
    return out
