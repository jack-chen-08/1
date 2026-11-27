# -*- coding: utf-8 -*-
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gen_import_samples as gen  # noqa: E402


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    """按默认 seed 生成一份样例，供全部测试共享。"""
    out = str(tmp_path_factory.mktemp("samples"))
    data = gen.build(gen.DEFAULT_SEED)
    gen.write_all(data, out)
    return out, data
