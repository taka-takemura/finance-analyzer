# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def sample_book(tmp_path_factory):
    """サンプルデータ.xlsx を一時ディレクトリに生成してパスを返す。"""
    tmp = tmp_path_factory.mktemp("data")
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        import create_template
        create_template.make_sample()
        create_template.make_template()
    finally:
        os.chdir(cwd)
    return tmp / "サンプルデータ.xlsx"


@pytest.fixture(scope="session")
def stmts(sample_book):
    import loader
    return loader.load_statements(str(sample_book))
