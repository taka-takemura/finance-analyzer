# -*- coding: utf-8 -*-
"""Streamlit AppTest による全ページのスモークテスト。"""
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]

PAGES = ["🏠 ダッシュボード", "📈 概要", "📋 財務指標", "🌳 DuPont分析",
         "🌲 ROICツリー", "⚖️ CVP分析", "🎛 シミュレーション",
         "🆚 複数社比較", "💰 DCF評価", "📄 レポート"]


@pytest.fixture(scope="module", autouse=True)
def ensure_sample(sample_book):
    """app.py と同じディレクトリに サンプルデータ.xlsx を配置する。"""
    dest = ROOT / "サンプルデータ.xlsx"
    existed = dest.exists()
    if not existed:
        shutil.copy(sample_book, dest)
    yield
    if not existed:
        dest.unlink(missing_ok=True)


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["source"] = "サンプルデータ"
    at.session_state["nav"] = page
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_category_switch_no_error():
    """財務指標ページのカテゴリ切替 (過去に表示崩れを起こした操作)。"""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["source"] = "サンプルデータ"
    at.session_state["nav"] = "📋 財務指標"
    at.run()
    sb = [s for s in at.selectbox if str(s.label) == "カテゴリ"][0]
    sb.set_value("安全性").run()
    assert not at.exception, [e.value for e in at.exception]
