#!/usr/bin/env python
"""变异测试：故意破坏每一道权限闸门，确认对应用例会变红。

「测试全绿」本身不证明测试有效——如果某道闸门删掉后测试依然全绿，
说明那条规则根本没有被覆盖。本脚本逐个闸门做一次外科式破坏：

  备份 → 改源码 → 跑指定用例 → 还原 → sha256 校验还原是否无损

任何一轮「期望变红却没红」都记为失败，退出码非 0。

用法：python scripts/mutation_check.py [--only M3]
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


MUTATIONS = [
    {
        "id": "M1",
        "name": "去掉 audience 闸门（会员将看到 internal 切片）",
        "file": "kb/visibility.py",
        "old": "        chunk.audience.in_(tuple(sorted(pol.audiences))),",
        "new": "        # [MUTATION M1] audience 闸门已移除",
        "tests": ["tests/test_member_isolation.py"],
    },
    {
        "id": "M2",
        "name": "去掉岗位交集闸门（visibility_roles 失效）",
        "file": "kb/visibility.py",
        "old": """        conditions.append(
            _array_empty_or_overlaps(chunk.visibility_roles, (ctx.role,))
        )""",
        "new": "        # [MUTATION M2] 岗位闸门已移除",
        "tests": ["tests/test_scope.py::test_role_scoped_chunk_invisible_to_other_roles"],
    },
    {
        "id": "M3",
        "name": "去掉会所交集闸门（visibility_sites 失效）",
        "file": "kb/visibility.py",
        "old": "            _array_empty_or_overlaps(chunk.visibility_sites, tuple(pol.site_ids))",
        "new": "            chunk.id.is_not(None),  # [MUTATION M3] 会所闸门已移除（恒真占位）",
        "tests": [
            "tests/test_scope.py::test_site_scoped_chunk_invisible_to_other_site",
            "tests/test_scope.py::test_member_site_isolation",
        ],
        "replace_all": True,
    },
    {
        "id": "M4",
        "name": "去掉类别白名单（价格与政策不再限主管及以上）",
        "file": "kb/visibility.py",
        "old": "        chunk.category.in_(tuple(sorted(pol.categories))),",
        "new": "        # [MUTATION M4] 类别闸门已移除",
        "tests": ["tests/test_visibility_matrix.py"],
    },
    {
        "id": "M5",
        "name": "去掉 published 状态闸门（下线文档仍可读）",
        "file": "kb/visibility.py",
        "old": '        document.status == "published",',
        "new": "        # [MUTATION M5] 下线闸门已移除",
        "tests": ["tests/test_source_404.py::test_offline_document_is_indistinguishable"],
    },
    {
        "id": "M6",
        "name": "切片同步写错范围（文档改了、切片没改）",
        "file": "kb/api/documents.py",
        "old": "            .where(KbChunk.doc_id == doc.id)",
        "new": "            .where(KbChunk.doc_id != doc.id)  # [MUTATION M6]",
        "tests": ["tests/test_visibility_sync.py::test_sync_updates_every_chunk"],
    },
    {
        "id": "M7",
        "name": "前后文查询不过滤（从上下文绕过可见范围）",
        "file": "kb/api/sources.py",
        "old": """            KbChunk.chunk_index == chunk_index,
            build_visibility_filter(ctx),""",
        "new": """            KbChunk.chunk_index == chunk_index,""",
        "tests": ["tests/test_scope.py::test_context_never_leaks_invisible_neighbour"],
    },
]


def run_tests(node_ids: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *node_ids],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode != 0, output


def tail(text: str, lines: int = 6) -> str:
    return "\n".join([ln for ln in text.strip().splitlines() if ln.strip()][-lines:])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="只跑某一个变异编号，如 M3")
    args = parser.parse_args()

    selected = [m for m in MUTATIONS if args.only is None or m["id"] == args.only]
    if not selected:
        print(f"没有匹配的变异编号：{args.only}")
        return 2

    failures: list[str] = []

    for mut in selected:
        path = ROOT / mut["file"]
        original = path.read_bytes()
        original_hash = sha256(path)
        text = original.decode("utf-8")

        if mut["old"] not in text:
            print(f"[✗ {mut['id']}] 锚点未找到，脚本需更新：{mut['file']}")
            failures.append(mut["id"])
            continue

        mutated = text.replace(mut["old"], mut["new"], -1 if mut.get("replace_all") else 1)
        if mutated == text:
            print(f"[✗ {mut['id']}] 替换未发生：{mut['file']}")
            failures.append(mut["id"])
            continue

        path.write_text(mutated, encoding="utf-8")
        try:
            went_red, output = run_tests(mut["tests"])
        finally:
            path.write_bytes(original)
            restored = sha256(path) == original_hash
            if not restored:
                print(f"[!! {mut['id']}] 源文件还原校验失败！{mut['file']}")
                failures.append(mut["id"])
                continue

        status = "RED  ✔" if went_red else "GREEN ✗（该闸门无有效覆盖）"
        print(f"[{mut['id']}] {mut['name']} → {status}")
        print("      " + tail(output, 3).replace("\n", "\n      "))
        if not went_red:
            failures.append(mut["id"])

    print()
    if failures:
        print(f"失败 {len(failures)} 项：{', '.join(failures)}")
        return 1
    print(f"全部 {len(selected)} 项变异均按预期变红，源文件已无损还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
