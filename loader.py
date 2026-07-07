# -*- coding: utf-8 -*-
"""財務諸表ローダー: Excel/CSV を読み込み、勘定科目を正規化する。

日本基準・IFRS・US GAAP の科目名エイリアスに対応。
"""
from __future__ import annotations

import io
import re
import unicodedata

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- シート名
SHEET_ALIASES = {
    "PL": ["pl", "損益計算書", "is", "incomestatement", "profitandloss", "連結損益計算書"],
    "BS": ["bs", "貸借対照表", "balancesheet", "sofp", "財政状態計算書", "連結貸借対照表"],
    "CF": ["cf", "キャッシュフロー計算書", "キャッシュ・フロー計算書", "cashflow",
           "cashflowstatement", "連結キャッシュフロー計算書"],
}

# ------------------------------------------------------- 勘定科目エイリアス
# canonical名: [別名リスト] (日本基準 / IFRS / US GAAP)
PL_ALIASES = {
    "売上高": ["売上収益", "営業収益", "収益", "revenue", "revenues", "netsales",
               "sales", "totalrevenue", "netrevenue",
               "売上高合計", "営業収益合計"],  # SPEEDA
    "売上原価": ["costofsales", "costofrevenue", "cogs", "costofgoodssold",
                  "売上原価合計"],  # SPEEDA
    "売上総利益": ["grossprofit", "grossmargin", "売上総利益又は損失"],
    "販売費及び一般管理費": ["販管費", "販売費・一般管理費", "販売費および一般管理費",
                              "sga", "sganda", "sellinggeneralandadministrativeexpenses",
                              "operatingexpenses", "販売費及び一般管理費等"],
    "人件費": ["personnelexpenses", "laborcost", "うち人件費", "人件費合計"],
    "減価償却費": ["depreciationandamortization", "da", "うち減価償却費", "減価償却費及び償却費"],
    "営業利益": ["operatingincome", "operatingprofit", "事業利益", "営業損益"],
    "営業外収益": ["nonoperatingincome", "金融収益", "financeincome", "その他の収益"],
    "営業外費用": ["nonoperatingexpenses", "金融費用", "financecosts", "financeexpenses",
                    "その他の費用"],
    "支払利息": ["interestexpense", "うち支払利息", "支払利息割引料"],
    "経常利益": ["ordinaryincome", "ordinaryprofit", "経常損益"],
    "特別利益": ["extraordinaryincome", "extraordinarygains"],
    "特別損失": ["extraordinaryloss", "extraordinarylosses"],
    "税引前当期純利益": ["税金等調整前当期純利益", "profitbeforetax", "incomebeforeincometaxes",
                          "pretaxincome", "税引前利益", "税引前当期利益"],
    "法人税等": ["incometaxes", "incometaxexpense", "法人税、住民税及び事業税",
                  "法人所得税費用", "法人税等合計"],
    "当期純利益": ["netincome", "profitfortheyear", "親会社株主に帰属する当期純利益",
                    "親会社の所有者に帰属する当期利益", "当期利益", "netincomeattributabletoparent"],
}

BS_ALIASES = {
    "現金及び預金": ["現金及び現金同等物", "cashandcashequivalents", "cashanddeposits", "現金預金"],
    "売上債権": ["受取手形及び売掛金", "売掛金", "受取手形、売掛金及び契約資産",
                  "tradereceivables", "accountsreceivable", "営業債権", "売上債権及びその他の債権",
                  "営業債権及びその他の債権"],
    "棚卸資産": ["inventories", "inventory", "商品及び製品", "たな卸資産"],
    "その他流動資産": ["othercurrentassets", "その他の流動資産"],
    "流動資産合計": ["流動資産", "totalcurrentassets", "currentassets"],
    "有形固定資産": ["propertyplantandequipment", "ppe", "有形固定資産合計"],
    "無形固定資産": ["intangibleassets", "のれん及び無形固定資産", "無形固定資産合計",
                      "goodwillandintangibles"],
    "投資その他の資産": ["investmentsandotherassets", "その他の非流動資産", "その他固定資産",
                          "investmentsandothernoncurrentassets"],
    "固定資産合計": ["固定資産", "非流動資産合計", "非流動資産", "totalnoncurrentassets",
                      "noncurrentassets"],
    "資産合計": ["totalassets", "総資産", "資産の部合計"],
    "仕入債務": ["支払手形及び買掛金", "買掛金", "tradepayables", "accountspayable",
                  "営業債務", "仕入債務及びその他の債務", "営業債務及びその他の債務",
                  "買入債務"],  # SPEEDA
    "短期借入金": ["shorttermborrowings", "shorttermdebt", "1年内返済予定の長期借入金を含む短期借入金",
                    "短期有利子負債", "短期借入債務"],  # SPEEDA
    "その他流動負債": ["othercurrentliabilities", "その他の流動負債"],
    "流動負債合計": ["流動負債", "totalcurrentliabilities", "currentliabilities"],
    "長期借入金": ["longtermborrowings", "longtermdebt", "社債及び長期借入金", "社債",
                    "長期有利子負債", "bondsandborrowings", "長期借入債務"],  # SPEEDA
    "その他固定負債": ["othernoncurrentliabilities", "その他の固定負債", "その他非流動負債"],
    "固定負債合計": ["固定負債", "非流動負債合計", "非流動負債", "totalnoncurrentliabilities"],
    "負債合計": ["totalliabilities", "負債の部合計"],
    "純資産合計": ["純資産", "totalequity", "netassets", "資本合計", "負債純資産合計"],
    "自己資本": ["株主資本等合計", "株主資本合計", "株主資本", "親会社の所有者に帰属する持分",
                  "親会社株主に帰属する持分", "自己資本合計",
                  "equityattributabletoownersofparent", "totalshareholdersequity",
                  "shareholdersequity"],
    "非支配株主持分": ["少数株主持分", "noncontrollinginterests", "minorityinterests"],
}

CF_ALIASES = {
    "営業活動によるキャッシュ・フロー": ["営業活動によるキャッシュフロー", "営業cf",
                                            "operatingcashflow", "cashflowfromoperatingactivities",
                                            "netcashprovidedbyoperatingactivities"],
    "投資活動によるキャッシュ・フロー": ["投資活動によるキャッシュフロー", "投資cf",
                                            "investingcashflow", "cashflowfrominvestingactivities",
                                            "netcashusedininvestingactivities"],
    "財務活動によるキャッシュ・フロー": ["財務活動によるキャッシュフロー", "財務cf",
                                            "financingcashflow", "cashflowfromfinancingactivities",
                                            "netcashusedinfinancingactivities"],
    "現金及び現金同等物の期末残高": ["期末現金残高", "cashatendofperiod",
                                       "cashandcashequivalentsatendofperiod",
                                       "現金及び現金同等物期末残高"],  # SPEEDA
    "設備投資額": ["capex", "capitalexpenditures", "有形固定資産の取得による支出",
                    "有形固定資産の取得"],  # SPEEDA
    "フリーキャッシュフロー": ["freecashflow", "fcf", "フリーcf"],
}

# 企業データ (SPEEDA CompanyInfo 等)
INFO_ALIASES = {
    "従業員数": ["期末従業員数", "従業員数連結", "employees", "numberofemployees",
                  "期末従業員数連結"],
    "臨時従業員数": ["期末臨時従業員数", "臨時雇用者数", "平均臨時雇用人員"],
    "発行済株式数": ["期末発行済株式数普通株自己株除く", "発行済株式総数自己株式を除く",
                      "期末発行済株式数自己株除く", "sharesoutstanding"],
    "1株配当": ["一株当たり年間配当金", "1株当たり年間配当金", "年間配当金", "dps",
                 "dividendpershare"],
    "配当総額": ["totaldividends"],
    "EPS": ["一株当たり当期純利益", "時系列調整前eps"],
    "BPS": ["一株当たり純資産"],
}

ALL_ALIASES = {"PL": PL_ALIASES, "BS": BS_ALIASES, "CF": CF_ALIASES,
               "INFO": INFO_ALIASES}


def _norm(s: str) -> str:
    """科目名の正規化: NFKC、空白・記号除去、小文字化。"""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\s　・,、.。()（）\-_&/]", "", s)
    return s.lower()


def _build_lookup(aliases: dict) -> dict:
    lookup = {}
    for canon, alist in aliases.items():
        lookup[_norm(canon)] = canon
        for a in alist:
            lookup[_norm(a)] = canon
    return lookup


LOOKUPS = {k: _build_lookup(v) for k, v in ALL_ALIASES.items()}
SHEET_LOOKUP = {_norm(a): k for k, alist in SHEET_ALIASES.items() for a in alist + [k]}


def _identify_sheet(name: str) -> str | None:
    n = _norm(name)
    if n in SHEET_LOOKUP:
        return SHEET_LOOKUP[n]
    for key, canon in SHEET_LOOKUP.items():
        if key and key in n:
            return canon
    return None


def _clean_frame(df: pd.DataFrame, stype: str) -> pd.DataFrame:
    """1列目=科目、以降=年度 の表を canonical index の数値表へ。"""
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.empty:
        return pd.DataFrame()
    df = df.set_index(df.columns[0])
    lookup = LOOKUPS[stype]
    rows, seen = {}, set()
    for raw_name, row in df.iterrows():
        canon = lookup.get(_norm(raw_name))
        if canon and canon not in seen:
            vals = pd.to_numeric(
                row.astype(str).str.replace(",", "").str.replace("△", "-")
                .str.replace("▲", "-"), errors="coerce")
            if vals.notna().any():  # 全空行(セクション見出し等)はスキップ
                rows[canon] = vals
                seen.add(canon)
    out = pd.DataFrame(rows).T
    out.columns = [str(c).strip() for c in out.columns]
    # 全てNaNの列(空年度)を除去
    out = out.dropna(axis=1, how="all")
    return out


# ---------------------------------------------------------- SPEEDA形式
SPEEDA_SECTIONS = {"損益計算書": "PL", "貸借対照表": "BS",
                   "キャッシュフロー計算書": "CF", "キャッシュ・フロー計算書": "CF"}


def _is_speeda(raw: pd.DataFrame) -> bool:
    """1列目に「決算期」行とセクション見出しがあれば SPEEDA 形式とみなす。"""
    col0 = raw.iloc[:30, 0].astype(str).str.strip()
    return (col0 == "決算期").any() and \
        col0.isin(list(SPEEDA_SECTIONS) + ["(財務諸表サマリー)"]).any()


def _parse_speeda(raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """SPEEDAエクスポート(三表一括/財務諸表サマリー)をパースする。"""
    col0 = raw.iloc[:, 0].astype(str).str.strip()
    hdr = col0[col0 == "決算期"].index[0]
    year_cells = raw.iloc[hdr, 1:]
    year_cols = [i + 1 for i, v in enumerate(year_cells) if pd.notna(v)]
    years = [str(raw.iloc[hdr, i]).strip() for i in year_cols]

    # セクション境界を検出
    marks = [(i, SPEEDA_SECTIONS[c]) for i, c in col0.items() if c in SPEEDA_SECTIONS]
    result = {"PL": pd.DataFrame(), "BS": pd.DataFrame(), "CF": pd.DataFrame()}
    for n, (start, stype) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(raw)
        block = raw.iloc[start + 1:end, [0] + year_cols].copy()
        block.columns = ["科目"] + years
        parsed = _clean_frame(block, stype)
        if result[stype].empty:
            result[stype] = parsed
        else:  # 同種セクションが複数ある場合は不足科目のみ追加
            add = parsed.loc[[i for i in parsed.index if i not in result[stype].index]]
            result[stype] = pd.concat([result[stype], add])

    # 年度列を全表で揃える(全表で共通して値のある列のみ残す)
    _fill_derived(result)
    return result


def load_company_info(file) -> pd.DataFrame:
    """SPEEDAの企業データ (CompanyInfo) ファイルから従業員数等を抽出する。

    返り値: index=正規化科目 (従業員数, 発行済株式数, 1株配当 など), columns=年度。
    """
    xl = pd.ExcelFile(file)
    for sheet in xl.sheet_names:
        raw = xl.parse(sheet, header=None)
        if raw.empty:
            continue
        col0 = raw.iloc[:, 0].astype(str).str.strip()
        hdr_idx = col0[col0 == "決算期"].index
        if len(hdr_idx) == 0:
            continue
        hdr = hdr_idx[0]
        year_cells = raw.iloc[hdr, 1:]
        year_cols = [i + 1 for i, v in enumerate(year_cells) if pd.notna(v)]
        years = [str(raw.iloc[hdr, i]).strip() for i in year_cols]
        block = raw.iloc[hdr + 1:, [0] + year_cols].copy()
        block.columns = ["科目"] + years
        info = _clean_frame(block, "INFO")
        if not info.empty:
            return info
    return pd.DataFrame()


def load_statements(file) -> dict[str, pd.DataFrame]:
    """Excel(複数シート) または CSV(区分列つき) を読み込む。

    返り値: {"PL": df, "BS": df, "CF": df} — index=正規化科目, columns=年度。
    """
    name = getattr(file, "name", str(file))
    result = {"PL": pd.DataFrame(), "BS": pd.DataFrame(), "CF": pd.DataFrame()}

    if name.lower().endswith(".csv"):
        raw = file.read() if hasattr(file, "read") else open(file, "rb").read()
        for enc in ("utf-8-sig", "cp932", "utf-8"):
            try:
                df = pd.read_csv(io.BytesIO(raw), encoding=enc)
                break
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        else:
            raise ValueError("CSVの文字コードを判定できませんでした")
        first = df.columns[0]
        if _norm(first) in (_norm("区分"), _norm("statement"), _norm("シート")):
            for key, g in df.groupby(first):
                stype = _identify_sheet(str(key))
                if stype:
                    result[stype] = _clean_frame(g.drop(columns=[first]), stype)
        else:  # 区分列なし → PLのみとみなす
            result["PL"] = _clean_frame(df, "PL")
    else:
        xl = pd.ExcelFile(file)
        # --- SPEEDA形式の自動検出 (シート名によらず全シートを確認)
        for sheet in xl.sheet_names:
            raw = xl.parse(sheet, header=None)
            if not raw.empty and _is_speeda(raw):
                return _parse_speeda(raw)
        for sheet in xl.sheet_names:
            stype = _identify_sheet(sheet)
            if stype:
                result[stype] = _clean_frame(xl.parse(sheet, header=0), stype)

    _fill_derived(result)
    return result


def _get(df: pd.DataFrame, item: str) -> pd.Series | None:
    return df.loc[item] if item in df.index else None


def _fill_derived(stmts: dict) -> None:
    """欠けている小計・合計科目を可能な範囲で自動補完する。"""
    pl, bs = stmts["PL"], stmts["BS"]

    def ensure(df, item, calc):
        if df.empty:
            return
        if item not in df.index:
            try:
                v = calc()
                if v is not None:
                    df.loc[item] = v
            except (KeyError, TypeError):
                pass

    if not pl.empty:
        z = pd.Series(0.0, index=pl.columns)
        g = lambda i: pl.loc[i] if i in pl.index else None
        gz = lambda i: pl.loc[i] if i in pl.index else z
        ensure(pl, "売上総利益",
               lambda: g("売上高") - g("売上原価") if g("売上高") is not None and g("売上原価") is not None else None)
        ensure(pl, "営業利益",
               lambda: g("売上総利益") - g("販売費及び一般管理費")
               if g("売上総利益") is not None and g("販売費及び一般管理費") is not None else None)
        ensure(pl, "経常利益",
               lambda: g("営業利益") + gz("営業外収益") - gz("営業外費用")
               if g("営業利益") is not None else None)
        ensure(pl, "税引前当期純利益",
               lambda: g("経常利益") + gz("特別利益") - gz("特別損失")
               if g("経常利益") is not None else None)
        ensure(pl, "当期純利益",
               lambda: g("税引前当期純利益") - gz("法人税等")
               if g("税引前当期純利益") is not None else None)

    if not bs.empty:
        z = pd.Series(0.0, index=bs.columns)
        g = lambda i: bs.loc[i] if i in bs.index else None
        gz = lambda i: bs.loc[i] if i in bs.index else z
        ensure(bs, "流動資産合計",
               lambda: gz("現金及び預金") + gz("売上債権") + gz("棚卸資産") + gz("その他流動資産")
               if any(i in bs.index for i in ["現金及び預金", "売上債権", "棚卸資産"]) else None)
        ensure(bs, "固定資産合計",
               lambda: gz("有形固定資産") + gz("無形固定資産") + gz("投資その他の資産")
               if any(i in bs.index for i in ["有形固定資産", "無形固定資産"]) else None)
        ensure(bs, "資産合計",
               lambda: g("流動資産合計") + g("固定資産合計")
               if g("流動資産合計") is not None and g("固定資産合計") is not None else None)
        ensure(bs, "流動負債合計",
               lambda: gz("仕入債務") + gz("短期借入金") + gz("その他流動負債")
               if any(i in bs.index for i in ["仕入債務", "短期借入金"]) else None)
        ensure(bs, "固定負債合計",
               lambda: gz("長期借入金") + gz("その他固定負債")
               if "長期借入金" in bs.index else None)
        ensure(bs, "負債合計",
               lambda: g("流動負債合計") + g("固定負債合計")
               if g("流動負債合計") is not None and g("固定負債合計") is not None else None)
        ensure(bs, "純資産合計",
               lambda: g("資産合計") - g("負債合計")
               if g("資産合計") is not None and g("負債合計") is not None else None)
        # 自己資本(親会社帰属) = 純資産 − 非支配株主持分
        ensure(bs, "自己資本",
               lambda: g("純資産合計") - gz("非支配株主持分")
               if g("純資産合計") is not None and "非支配株主持分" in bs.index else None)


def validate(stmts: dict) -> list[str]:
    """最低限必要な科目のチェック。問題点のリストを返す。"""
    issues = []
    req_pl = ["売上高", "営業利益", "当期純利益"]
    req_bs = ["資産合計", "純資産合計"]
    if stmts["PL"].empty:
        issues.append("損益計算書(PL)シートが見つかりません")
    else:
        for i in req_pl:
            if i not in stmts["PL"].index:
                issues.append(f"PL: 「{i}」が見つかりません(自動補完も不可)")
    if stmts["BS"].empty:
        issues.append("貸借対照表(BS)シートが見つかりません")
    else:
        for i in req_bs:
            if i not in stmts["BS"].index:
                issues.append(f"BS: 「{i}」が見つかりません(自動補完も不可)")
    if not stmts["PL"].empty and not stmts["BS"].empty:
        if list(stmts["PL"].columns) != list(stmts["BS"].columns):
            issues.append("PLとBSの年度列が一致していません")
    return issues
