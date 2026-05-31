"""F1 回归:owner_ledgers 页面必须注入 CSRF token。

codex P1:owner_ledgers 自建 Jinja2Templates 漏了 ``context_processors=[csrf_context]``,
真实浏览器下本页 POST 表单(建账本 / 改成员角色 / 转移 / 归档)拿不到
``<meta name="csrf-token">``,会被 /owner CSRF 中间件 403。TestClient 豁免 CSRF,所以
旧测试没暴露。这里直接断言渲染输出含**非空** token,不依赖中间件放行——锁住
"owner 页面渲染出 csrf token"这个不变量,防止再有人自建 templates 时漏掉 processor。
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import owner_ledgers

_CSRF_META = re.compile(r'<meta name="csrf-token" content="([^"]*)"')


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    # /owner/ledgers 走 owner_ledgers 模块自己的 _require_local(不是 owner_console 的),
    # 必须 override 这一个才能绕过 loopback 限制进入页面渲染。
    app.dependency_overrides[owner_ledgers._require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(owner_ledgers._require_local, None)


def test_owner_ledgers_index_injects_csrf_token(local_client: TestClient) -> None:
    resp = local_client.get("/owner/ledgers")
    assert resp.status_code == 200
    match = _CSRF_META.search(resp.text)
    assert match is not None, "/owner/ledgers 缺 <meta name=csrf-token>"
    assert match.group(1).strip() != "", "csrf-token content 为空(csrf_context 未注入)"
