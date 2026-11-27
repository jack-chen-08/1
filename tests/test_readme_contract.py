"""AC4：README 必须列出飞书后台要开通的权限与重定向 URL 配置。

用一个契约测试把文档要求固定住，避免以后改 README 时把配置说明删掉。
"""

from __future__ import annotations

from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_documents_console_setup():
    text = README.read_text(encoding="utf-8")

    # 重定向 URL 配置
    assert "重定向" in text
    assert "redirect_uri" in text or "REDIRECT" in text
    assert "/api/auth/feishu/callback" in text

    # 需要开通的权限
    assert "权限" in text
    for scope in ("contact:user.base:readonly", "contact:user.employee_id:readonly"):
        assert scope in text, scope

    # 环境变量三件套
    for var in ("APP_FEISHU_APP_ID", "APP_FEISHU_SECRET_NAME", "APP_FEISHU_TENANT_KEY"):
        assert var in text, var

    # 明确写出不用 open_id 的原因
    assert "open_id" in text and "user_id" in text
