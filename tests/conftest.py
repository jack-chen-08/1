"""pytest 共享夹具：真库（PostgreSQL 16）建库建表 + 基线数据 + 各角色客户端。

库名默认 crm_test（可用 CRM_TEST_DB_NAME 覆盖），首次运行自动创建；
连接参数复用 crm.config.build_dsn() 的离散环境变量。
"""

from __future__ import annotations

import os
import uuid

# 必须在导入 crm.* 之前落定库名
TEST_DB_NAME = os.getenv("CRM_TEST_DB_NAME", "crm_test")
os.environ["CRM_DB_NAME"] = TEST_DB_NAME

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from crm.config import build_dsn  # noqa: E402
from crm.db import Base, get_engine, get_sessionmaker, reset_engine  # noqa: E402
from crm.main import app  # noqa: E402
from crm.models import AppUser, Opportunity, OpportunityStageHistory  # noqa: E402


def _ensure_database() -> None:
    """连到维护库建测试库（幂等）。"""
    import psycopg

    user = os.getenv("CRM_DB_USER", "crm")
    password = os.getenv("CRM_DB_PASSWORD", "")
    host = os.getenv("CRM_DB_HOST", "127.0.0.1")
    port = int(os.getenv("CRM_DB_PORT", "55432"))
    with psycopg.connect(
        host=host, port=port, user=user, password=password, dbname="postgres", autocommit=True
    ) as conn:
        exists = conn.execute(
            "select 1 from pg_database where datname = %s", (TEST_DB_NAME,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')


@pytest.fixture(scope="session", autouse=True)
def _schema():
    _ensure_database()
    reset_engine()
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    reset_engine()


# --------------------------------------------------------------------------- #
# 基线数据
# --------------------------------------------------------------------------- #
ORG_A = uuid.UUID("11111111-0000-0000-0000-00000000aaaa")
ORG_B = uuid.UUID("22222222-0000-0000-0000-00000000bbbb")
S1 = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000a1")
S2 = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000a2")
T1 = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")

USERS = [
    # id, org, role, sites, name
    ("admin_a", ORG_A, "org_admin", [str(S1), str(S2)], "组织管理员A"),
    ("ops_a", ORG_A, "ops_manager", [str(S1)], "运营经理A"),
    ("lead_a", ORG_A, "sales_lead", [str(S1)], "销售主管A"),
    ("sales1", ORG_A, "sales", [str(S1)], "业务员一"),
    ("sales2", ORG_A, "sales", [str(S1)], "业务员二"),
    ("fin_a", ORG_A, "finance", [str(S1)], "财务A"),
    ("view_a", ORG_A, "viewer", [str(S1)], "观察者A"),
    ("admin_b", ORG_B, "org_admin", [str(T1)], "组织管理员B"),
]

# label, org, site, owner, stage, first_year_fen, weighted_fen, company, space
OPPS = [
    ("o_s1_new", ORG_A, S1, "sales1", "new", 100_000, 30_000, "甲科技", None),
    ("o_s1_qual", ORG_A, S1, "sales1", "qualified", 200_000, 80_000, "乙数据", "300㎡标准间"),
    ("o_s1_prop", ORG_A, S1, "sales1", "proposal", 300_000, 180_000, "丙智造", None),
    ("o_s1_new2", ORG_A, S1, "sales2", "new", 400_000, 120_000, "丁物流", None),
    ("o_s1_qual2", ORG_A, S1, "sales2", "qualified", 500_000, 200_000, "戊生物", "800㎡研发"),
    ("o_s1_prop2", ORG_A, S1, "sales2", "proposal", 600_000, 360_000, "己新材", None),
    ("o_s1_won", ORG_A, S1, "sales2", "won", 700_000, 700_000, "庚能源", None),
    ("o_s2_qual", ORG_A, S2, "sales2", "qualified", 900_000, 360_000, "辛环保", None),
    ("o_orgb_new", ORG_B, T1, "admin_b", "new", 700_000, 210_000, "壬文旅", None),
]


@pytest.fixture(autouse=True)
def seed():
    """每个用例前清库并灌基线数据。"""
    reset_engine()
    engine = get_engine()
    with engine.begin() as conn:
        for table in (
            "opportunity_merge_log",
            "opportunity_field_history",
            "opportunity_stage_history",
            "opportunity",
            "app_user",
        ):
            conn.execute(text(f"DELETE FROM {table}"))

    Session = get_sessionmaker()
    db = Session()
    try:
        for uid, org, role, sites, name in USERS:
            db.add(
                AppUser(id=uid, org_id=org, role=role, site_ids=sites, display_name=name)
            )
        ids: dict[str, uuid.UUID] = {}
        for label, org, site, owner, stage, amount, weighted, company, space in OPPS:
            opp = Opportunity(
                org_id=org,
                site_id=site,
                company_name=company,
                stage=stage,
                owner_id=owner,
                expected_first_year_amount_fen=amount,
                weighted_amount_fen=weighted,
                space_requirement=space,
                created_by=owner,
            )
            db.add(opp)
            db.flush()
            ids[label] = opp.id
            db.add(
                OpportunityStageHistory(
                    opportunity_id=opp.id,
                    org_id=org,
                    site_id=site,
                    from_stage=None,
                    to_stage=stage,
                    changed_by=owner,
                    note="created",
                )
            )
        db.commit()
    finally:
        db.close()

    return {"ids": ids, "org_a": ORG_A, "org_b": ORG_B, "s1": S1, "s2": S2, "t1": T1}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def as_user(client):
    """as_user("sales1") -> 带 X-User-Id 的请求器。"""

    def _make(user_id: str):
        return _UserClient(client, user_id)

    return _make


class _UserClient:
    def __init__(self, client: TestClient, user_id: str) -> None:
        self._c = client
        self.user_id = user_id

    def _h(self, extra=None):
        headers = {"X-User-Id": self.user_id}
        if extra:
            headers.update(extra)
        return headers

    def get(self, url, **kw):
        return self._c.get(url, headers=self._h(kw.pop("headers", None)), **kw)

    def post(self, url, **kw):
        return self._c.post(url, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url, **kw):
        return self._c.patch(url, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self._c.delete(url, headers=self._h(kw.pop("headers", None)), **kw)


@pytest.fixture()
def db():
    Session = get_sessionmaker()
    session = Session()
    try:
        yield session
    finally:
        session.close()
