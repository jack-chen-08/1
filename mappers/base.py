# -*- coding: utf-8 -*-
"""映射器公共件：问题对象、CSV/XLSX 读取、通用校验规则。"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

CC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
CC_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]
MEMBER_STATUS_ALLOWED = {"active", "suspended", "expired"}

RE_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_MOBILE = re.compile(r"^1[3-9]\d{9}$")
RE_SCIENTIFIC = re.compile(r"^[+-]?\d(?:\.\d+)?[eE][+-]?\d+$")
RE_FULLWIDTH = re.compile(r"[\u3000\uff01-\uff5e]")
RE_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

SEVERITY = {"TITLE_ROW": "warning", "BLANK_ROW": "warning", "MERGED_CELL": "warning"}


@dataclass(frozen=True)
class Issue:
    code: str
    file: str
    rows: Tuple[int, ...]
    field: str = "-"
    detail: str = ""
    severity: str = "error"

    def key(self) -> Tuple[str, str, Tuple[int, ...]]:
        return (self.code, self.file, self.rows)

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "file": self.file, "rows": list(self.rows),
                "field": self.field, "detail": self.detail, "severity": self.severity}


def make(code: str, file: str, rows: Sequence[int], field: str = "-", detail: str = "") -> Issue:
    return Issue(code, file, tuple(int(r) for r in rows), field, detail, SEVERITY.get(code, "error"))


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def read_csv(path: str, encoding: str = "utf-8", expect_first_col: Optional[str] = None
             ) -> Tuple[List[str], List[Tuple[int, Dict[str, str]]], List[Issue]]:
    """返回（表头、[(物理行号, 行字典)]、结构问题）。自动识别标题行与空白行。"""
    issues: List[Issue] = []
    with open(path, "r", encoding=encoding, newline="") as f:
        raw = list(csv.reader(f))

    header_idx = None
    for i, row in enumerate(raw):
        if expect_first_col and row and row[0].strip() == expect_first_col:
            header_idx = i
            break
    if header_idx is None:
        header_idx = 0
        while header_idx < len(raw) and not any(c.strip() for c in raw[header_idx]):
            header_idx += 1

    # 表头之前的行：非空 = 标题行，空 = 空白行
    for i in range(header_idx):
        row = raw[i]
        if any(c.strip() for c in row):
            issues.append(make("TITLE_ROW", _base(path), [i + 1], "-", "表头之前多出标题行：%s" % " ".join(c for c in row if c.strip())))
        else:
            issues.append(make("BLANK_ROW", _base(path), [i + 1], "-", "表头之前的空白行"))

    header = [h.strip() for h in raw[header_idx]]
    rows: List[Tuple[int, Dict[str, str]]] = []
    for i in range(header_idx + 1, len(raw)):
        row = raw[i]
        if not any(c.strip() for c in row):
            issues.append(make("BLANK_ROW", _base(path), [i + 1], "-", "数据区空白行"))
            continue
        rows.append((i + 1, {header[j]: (row[j] if j < len(row) else "") for j in range(len(header))}))
    return header, rows, issues


def read_xlsx(path: str) -> Tuple[List[str], List[Tuple[int, Dict[str, str]]], List[Issue], List[Tuple[int, int]]]:
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    issues: List[Issue] = []
    grid = [[("" if c is None else str(c)) for c in row] for row in ws.iter_rows(values_only=True)]
    header_idx = 0
    for i, row in enumerate(grid):
        if row and row[0].strip() == "lease_id":
            header_idx = i
            break
    for i in range(header_idx):
        if any(c.strip() for c in grid[i]):
            issues.append(make("TITLE_ROW", _base(path), [i + 1], "-", "表头之前多出标题行"))
        else:
            issues.append(make("BLANK_ROW", _base(path), [i + 1], "-", "表头之前的空白行"))
    header = [h.strip() for h in grid[header_idx]]
    rows: List[Tuple[int, Dict[str, str]]] = []
    for i in range(header_idx + 1, len(grid)):
        row = grid[i]
        if not any(c.strip() for c in row):
            issues.append(make("BLANK_ROW", _base(path), [i + 1], "-", "数据区空白行"))
            continue
        rows.append((i + 1, {header[j]: (row[j] if j < len(row) else "") for j in range(len(header))}))
    merges = [(r.min_row, r.max_row) for r in ws.merged_cells.ranges]
    return header, rows, issues, merges


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# 通用校验
# ---------------------------------------------------------------------------
def check_fullwidth(file: str, rows: List[Tuple[int, Dict[str, str]]]) -> List[Issue]:
    out = []
    for rn, row in rows:
        for col, val in row.items():
            if isinstance(val, str) and RE_FULLWIDTH.search(val):
                out.append(make("FULLWIDTH_CHAR", file, [rn], col, "含全角字符：%r" % val))
    return out


def check_mobile(file: str, rows: List[Tuple[int, Dict[str, str]]], col: str = "mobile") -> List[Issue]:
    out = []
    for rn, row in rows:
        val = row.get(col) or ""
        if not val:
            continue
        if RE_SCIENTIFIC.match(val):
            out.append(make("PHONE_SCIENTIFIC", file, [rn], col, "科学计数法：%s" % val))
        elif not RE_MOBILE.match(val):
            out.append(make("PHONE_FORMAT_VARIANT", file, [rn], col, "非标准 11 位：%r" % val))
    return out


def cc_check_char(body17: str) -> str:
    total = sum(CC_CHARS.index(c) * w for c, w in zip(body17, CC_WEIGHTS))
    return CC_CHARS[(31 - total % 31) % 31]


def check_credit_code(file: str, rows: List[Tuple[int, Dict[str, str]]], col: str = "credit_code") -> List[Issue]:
    out = []
    for rn, row in rows:
        val = (row.get(col) or "").strip().upper()
        if len(val) != 18 or any(c not in CC_CHARS for c in val):
            out.append(make("CREDIT_CODE_CHECKSUM", file, [rn], col, "长度或字符集非法：%s" % val))
            continue
        if cc_check_char(val[:17]) != val[17]:
            out.append(make("CREDIT_CODE_CHECKSUM", file, [rn], col, "校验位应为 %s，实为 %s" % (cc_check_char(val[:17]), val[17])))
    return out


def check_enum(file: str, rows: List[Tuple[int, Dict[str, str]]], col: str,
               allowed: Iterable[str]) -> List[Issue]:
    allowed = set(allowed)
    out = []
    for rn, row in rows:
        val = (row.get(col) or "")
        if val not in allowed:
            out.append(make("UNKNOWN_ENUM", file, [rn], col, "非允许枚举值：%r" % val))
    return out


def check_iso_date(file: str, rows: List[Tuple[int, Dict[str, str]]], col: str) -> List[Issue]:
    out = []
    for rn, row in rows:
        val = (row.get(col) or "").strip()
        if val and not RE_ISO_DATE.match(val):
            out.append(make("MIXED_DATE_FORMAT", file, [rn], col, "非 ISO 日期：%r" % val))
    return out


def check_duplicates(file: str, rows: List[Tuple[int, Dict[str, str]]]) -> List[Issue]:
    seen: Dict[Tuple[str, ...], List[int]] = {}
    for rn, row in rows:
        key = tuple(sorted((k, str(v)) for k, v in row.items()))
        seen.setdefault(key, []).append(rn)
    out = []
    for key, rns in seen.items():
        if len(rns) > 1:
            out.append(make("DUPLICATE_ROW_IN_FILE", file, sorted(rns), "整行",
                            "%d 行内容完全相同" % len(rns)))
    return out
