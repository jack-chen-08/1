#!/usr/bin/env python
"""比对两个数据库的模式：Alembic 迁移建出的库 vs ORM create_all 建出的库。

只比业务表（排除 alembic_version），逐列比 类型 / 可空 / 长度，并比索引名集合。
任一处不一致即退出码非 0。

用法：
    python scripts/verify_schema_parity.py --left kb_mig1925 --right kb_test
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text

BUSINESS_TABLES = ("app_user", "kb_document", "kb_chunk")

COLUMNS_SQL = """
select table_name, column_name, data_type, udt_name, is_nullable,
       coalesce(character_maximum_length, -1) as max_len,
       coalesce(numeric_precision, -1) as num_precision
from information_schema.columns
where table_schema = 'public' and table_name = any(:tables)
order by table_name, column_name
"""

INDEXES_SQL = """
select tablename, indexname
from pg_indexes
where schemaname = 'public' and tablename = any(:tables)
order by tablename, indexname
"""


def dsn(db_name: str) -> str:
    user = os.environ["KB_DB_USER"]
    password = os.environ["KB_DB_PASSWORD"]
    host = os.environ.get("KB_DB_HOST", "localhost")
    port = os.environ.get("KB_DB_PORT", "55433")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db_name}"


def snapshot(db_name: str):
    engine = create_engine(dsn(db_name), future=True)
    with engine.connect() as conn:
        cols = conn.execute(
            text(COLUMNS_SQL), {"tables": list(BUSINESS_TABLES)}
        ).all()
        idx = conn.execute(text(INDEXES_SQL), {"tables": list(BUSINESS_TABLES)}).all()
    engine.dispose()
    return cols, idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--left", required=True, help="迁移建出的库名")
    ap.add_argument("--right", required=True, help="ORM create_all 建出的库名")
    args = ap.parse_args()

    left_cols, left_idx = snapshot(args.left)
    right_cols, right_idx = snapshot(args.right)

    ok = True

    lset = {(r.table_name, r.column_name, r.udt_name, r.is_nullable, r.max_len, r.num_precision) for r in left_cols}
    rset = {(r.table_name, r.column_name, r.udt_name, r.is_nullable, r.max_len, r.num_precision) for r in right_cols}

    print(f"列数：{args.left}={len(lset)}  {args.right}={len(rset)}")
    for item in sorted(lset - rset):
        print(f"  只在 {args.left}：{item}")
        ok = False
    for item in sorted(rset - lset):
        print(f"  只在 {args.right}：{item}")
        ok = False

    lidx = {(r.tablename, r.indexname) for r in left_idx}
    ridx = {(r.tablename, r.indexname) for r in right_idx}
    print(f"索引数：{args.left}={len(lidx)}  {args.right}={len(ridx)}")
    for item in sorted(lidx - ridx):
        print(f"  只在 {args.left}：{item}")
        ok = False
    for item in sorted(ridx - lidx):
        print(f"  只在 {args.right}：{item}")
        ok = False

    print("结论：模式一致。" if ok else "结论：存在差异，见上。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
