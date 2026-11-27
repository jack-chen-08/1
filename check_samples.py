#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_samples.py —— 用五个映射器预演样例文件，与 answer_key.json 逐条比对。

退出码：0 = 完全一致；1 = 有漏检/误报/数量不符。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mappers  # noqa: E402


def norm(items: List[dict]) -> List[Tuple[str, str, Tuple[int, ...]]]:
    return sorted((d["code"], d["file"], tuple(sorted(d["rows"]))) for d in items)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="samples")
    ap.add_argument("--answer", default=None)
    args = ap.parse_args()

    answer_path = args.answer or os.path.join(args.samples, "answer_key.json")
    with open(answer_path, encoding="utf-8") as f:
        key = json.load(f)

    detected = [i.as_dict() for i in mappers.run_all(args.samples)]
    exp = norm(key["defects"])
    got = norm(detected)

    exp_set, got_set = set(exp), set(got)
    missed = sorted(exp_set - got_set)
    extra = sorted(got_set - exp_set)

    print("answer_key 预埋：%d 条 / 映射器检出：%d 条" % (len(exp), len(got)))
    print("漏检：%d 条   误报：%d 条" % (len(missed), len(extra)))

    exp_c = Counter(c for c, _, _ in exp)
    got_c = Counter(c for c, _, _ in got)
    print("\n%-26s %6s %6s" % ("问题代码", "答案", "检出"))
    for code in sorted(set(exp_c) | set(got_c)):
        flag = "" if exp_c[code] == got_c[code] else "  <<<"
        print("%-26s %6d %6d%s" % (code, exp_c[code], got_c[code], flag))

    for title, items in (("漏检明细", missed), ("误报明细", extra)):
        if items:
            print("\n%s：" % title)
            for code, file, rows in items[:40]:
                print("  %-24s %-16s %s" % (code, file, list(rows)))

    ok = not missed and not extra
    print("\n结论：%s" % ("全部命中且无误报（AC4 达成）" if ok else "不一致，需修"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
