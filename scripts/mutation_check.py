"""变异测试：故意破坏每道权限闸门，确认对应用例会红。

用途：证明测试不是「恒真断言」。任何一轮若 0 失败，说明该闸门没有被覆盖。
每轮改动前先备份，跑完立即还原，最终校验文件 sha256 与原始一致。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = os.environ.get("PYTHON", str(ROOT.parent / ".venv-2917" / "bin" / "python"))

SCOPE = ROOT / "crm/permissions/scope.py"
MATRIX = ROOT / "crm/permissions/matrix/opportunity.yaml"

# (名字, 文件, 原文, 改成, 期望红在哪)
MUTATIONS = [
    (
        "M1 跨 org 隔离失效",
        SCOPE,
        "Opportunity.org_id == user.org_id,",
        "Opportunity.org_id == Opportunity.org_id,",
        "test_scope_lifecycle / 跨 org 用例",
    ),
    (
        "M2 site 范围失效",
        SCOPE,
        'if pol.site_scope == "own_sites":',
        "if False:",
        "本场地范围用例",
    ),
    (
        "M3 sales owner 范围失效",
        SCOPE,
        'if pol.owner_scope == "own" and not ignore_owner_scope:',
        "if False:",
        "AC2 本人商机汇总",
    ),
    (
        "M4 金额可见性失效",
        SCOPE,
        "    if pol.amounts_visible:\n        return out",
        "    if True:\n        return out",
        "AC3 viewer 金额",
    ),
    (
        "M5 汇总金额对 viewer 下发",
        SCOPE,
        "    if summary_amount_visible(user, m):",
        "    if True:",
        "AC3 summary 不返回金额键",
    ),
    (
        "M6 撞单最小投影失效",
        MATRIX,
        "  minimal_roles: [sales]",
        "  minimal_roles: []",
        "AC4 sales 撞单不含金额",
    ),
    (
        "M7 阶段过滤失效",
        SCOPE,
        "    if pol.stage_in and not ignore_stage_filter:",
        "    if False:",
        "finance 只读 won",
    ),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_pytest() -> tuple[int, str]:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    proc = subprocess.run(
        [PY, "-m", "pytest", "--color=no", "-q", "--tb=no", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    before = {p: sha(p) for p in (SCOPE, MATRIX)}
    rows = []
    ok = True
    for name, path, old, new, expect in MUTATIONS:
        src = path.read_text(encoding="utf-8")
        if old not in src:
            rows.append((name, "SKIP", "锚点未找到", expect))
            ok = False
            continue
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        try:
            path.write_text(src.replace(old, new, 1), encoding="utf-8")
            code, out = run_pytest()
            fails = len(re.findall(r"^FAILED ", out, re.M))
            m = re.search(r"(\d+) failed", out)
            nfail = int(m.group(1)) if m else len(re.findall(r"\bF\b", out))
            verdict = "RED(符合预期)" if code != 0 else "GREEN(测试没抓住!)"
            if code == 0:
                ok = False
            rows.append((name, verdict, f"失败用例 {nfail if nfail else fails} 个", expect))
        finally:
            shutil.copy2(backup, path)
            backup.unlink()

    after = {p: sha(p) for p in (SCOPE, MATRIX)}
    intact = before == after

    print("\n变异测试结果")
    print("-" * 92)
    for name, verdict, detail, expect in rows:
        print(f"{name:<22} {verdict:<18} {detail:<18} 期望落点: {expect}")
    print("-" * 92)
    print("源文件还原校验:", "一致（未被我改坏）" if intact else "不一致！需人工检查")
    if not intact:
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
