# v0.4-beta1 — Family Ledger Foundation

> 基线：`v0.4-alpha3-rc1` tag (commit `aa541ce`)
> 分支：`v0.4-beta1-family-ledger-foundation`
> 范围：把小票夹从"个人自用 RC"推进到"家庭私有账本 beta 基础"。**不破坏现有 owner pairing / 不引入新依赖 / 不做 v0.5 完整 household / 不动 token 主链路**。

---

## 1. 版本目标

让一个家庭可以**协作维护一本共享账单**，同时保持每个家庭成员的**个人账本完全隐私**。

具体能力：

- Owner 可在 Owner Console / Android 邀请家庭成员加入某个共享账本（生成 invite_token）
- 被邀请人可在 Android 输入 invite_token 加入该共享账本（不会因此让出自己的个人账本）
- Member 可写共享账本、Viewer 只能读
- Owner 可停用成员、撤销未使用的邀请
- 所有权限**在后端强制**，不靠 UI 隐藏
- 所有跨账本访问都会被 `(ledger_id, account_id, role)` 三重过滤

## 2. 不做清单（严格）

- ❌ 不做银行聚合 / 投资净资产
- ❌ 不做完整 recurring（继承 alpha3 候选模型）
- ❌ 不做分类预算
- ❌ 不做 owner 转让（v0.5 候选）
- ❌ 不做邀请通知（邮件/SMS/二维码扫描）—— 明文 token 由 owner 线下传递
- ❌ 不动 schema 中现有表的字段
- ❌ 不动 Room migration（Android 已经 v4，本期不升）
- ❌ 不动 device pairing / upload_link / 主上传链路
- ❌ 不让家庭成员看到他人个人账本
- ❌ 不靠 UI 隐藏代替后端权限

## 3. 能力域 → 任务编号

| 域 | 任务 |
|---|---|
| **A 设计** | T01 design doc + T02 decision doc 0022 |
| **B Schema** | T03 Invitation model + T04 Base.metadata.create_all 兼容路径 |
| **C 权限服务** | T05 permission_service.py + T06 角色谓词 + T07 require() 守卫 |
| **D 邀请 API** | T08 POST /api/ledgers/{lid}/invitations + T09 GET list + T10 POST /api/invitations/accept + T11 POST .../revoke |
| **E 成员 API** | T12 GET members + T13 POST .../disable |
| **F Owner Console** | T14 /owner/ledgers/{lid}/members 页 + T15 模板 + T16 CSS（沿用 tokens） |
| **G /web** | T17 role badge + T18 viewer 隐藏写操作 |
| **H Android** | T19 加入家庭账本入口 + T20 当前角色展示 + T21 viewer 隐藏写 UI |
| **I 测试** | T22 后端 12+ 权限测试 + T23 Android 绑定测试 + T24 no-secret-leak 扩展 |
| **J 文档** | T25 Runbook + T26 截屏索引 + T27 BETA1_REPORT |
| **K hardening** | T28 member/viewer 角色调整 API + Owner Console 表单 |

## 4. PR 拆分

- **PR #17**（本 PR）：完整 v0.4-beta1 实现，按 commit 切片：
  - C1 设计 + 决策（T01-T02）
  - C2 schema + permission service（T03-T07）
  - C3 邀请 + 成员 API（T08-T13）
  - C4 Owner Console 成员管理（T14-T16）
  - C5 /web role badge（T17-T18）
  - C6 Android 加入入口 + 角色 UI（T19-T21）
  - C7 测试（T22-T24）
  - C8 文档 + RC（T25-T27）

整 PR 可以分多次 push、CI 滚动。**只有 C7 全绿才考虑 ready-for-review。**

## 5. 安全不变式（必须保持）

- 公网仅 `/api/*`，`/web` `/owner` 公网 403（继承 alpha2/3）
- 所有新增 API 必须 `get_current_app_context` 或 `_web_require_local`
- `(ledger_id, account_id, role)` 是所有写操作的强制三元组
- `invite_token` 明文只在创建响应中返回一次，不存明文、不入日志
- 失败原因不区分（accept 失败统一 `invitation_invalid`）
- 沿用 `test_*_no_secret_leak` 模式覆盖新路由
- `LedgerRepository.switchLedger` / `ExpenseDao.findAnyByServerIds` 禁止触碰

## 6. 权限矩阵

| 操作 | owner | member | viewer |
|------|:---:|:---:|:---:|
| 查看账单 | ✅ | ✅ | ✅ |
| 创建账单（确认 pending） | ✅ | ✅ | ❌ |
| 编辑账单 | ✅ | ✅ | ❌ |
| 删除账单 | ✅ | ✅ | ❌ |
| 上传截图 | ✅ | ✅ | ❌ |
| 创建分类规则 | ✅ | ✅ | ❌ |
| 创建/旋转/撤销 UploadLink | ✅ | ❌ | ❌ |
| 邀请成员 | ✅ | ❌ | ❌ |
| 停用成员 | ✅ | ❌ | ❌ |
| 撤销邀请 | ✅ | ❌ | ❌ |
| 删除账本 | ✅ | ❌ | ❌ |
| 切换账本 | ✅ | ✅ | ✅ |
| 查看其他成员 | ✅ | ✅ | ✅ |
| 看自己个人账本 | ✅（自己是 owner）| ✅（自己是 owner）| ✅（自己是 owner）|
| 看其他成员个人账本 | **❌** | **❌** | **❌** |

> 最后一行是隐私不变式核心：你在家庭账本里是 owner 不代表你在我的个人账本里也是 owner。

## 7. Schema 变更

新增表 `invitations`：

```python
class Invitation(Base):
    __tablename__ = "invitations"
    id: int PK
    public_id: str UUID (exposed in API)
    ledger_id: str FK ledgers.ledger_id (index)
    token_hash: str 64 unique (sha256 of plain token)
    role: str ("member" | "viewer", CHECK 表达式)
    created_by_account_id: int FK accounts.id
    note: str | None 80 chars
    expires_at: datetime (default now+7d, index)
    created_at: datetime
    used_at: datetime | None
    used_by_account_id: int | None FK accounts.id
    revoked_at: datetime | None
```

不改任何现有表。

### Migration / Rollback

- 启动时 `Base.metadata.create_all(bind=engine)` 自动建表（与项目现有模式一致，无 alembic）。
- 老库启动：自动建 `invitations`，所有现有 LedgerMember / AuthToken 不变。
- 回滚：`DROP TABLE invitations;` 即可；现有功能不依赖此表。
- 应用降级：旧应用见到 `invitations` 表会忽略，老 owner 流程不变。

## 8. 测试矩阵

### 后端（`backend/tests/test_family_ledger_permissions.py` 新增）

1. owner 创建邀请成功，token 只在响应里返回一次，不入库明文
2. member 创建邀请 → 403
3. viewer 创建邀请 → 403
4. accept 邀请：合法 token 成功，签发 app-scope AuthToken，写入 LedgerMember(role=invite.role)
5. accept 已用邀请 → 400 invitation_invalid
6. accept 已撤销邀请 → 400 invitation_invalid
7. accept 已过期邀请 → 400 invitation_invalid
8. accept 不存在 token → 400 invitation_invalid
9. viewer 尝试 PATCH 账单 → 403
10. member 尝试 disable 其他成员 → 403
11. 停用 member：其 token 立即失效（next API call → 401）
12. 成员 A 看不到成员 B 的个人账本（B 的 ledger_id 不在 A 的 list_ledgers 结果里）
13. 成员加入家庭账本后，其个人账本 owner 角色不变
14. invite_token 明文 sha256 与库中 token_hash 匹配；明文不可反查
15. 公网 POST /api/invitations/accept 同样要求 device_name 正确签发

### Android 单测（`InvitationViewModelTest.kt` 新增）

- accept 成功 → session_token 写入 SecureTokenStore
- accept 失败 → ErrorMessage 走 ErrorMapper
- 输入 token 校验本地格式（长度 / 字符集）

### 真机

- Owner Console → 创建 member 邀请 → 复制 token
- Android（被邀请人设备）→ 设置 → 加入家庭账本 → 粘贴 token → 进入家庭账本
- 切回个人账本仍正常
- Owner disable 该 member → Android 下次 API 调用 401 → 引导重新 pair

## 9. 验收闸门

完成下列才允许 mark ready：

```text
backend: compileall / ruff / pytest / smoke
android: testGrayDebugUnitTest / assembleGrayDebug / assembleInternalDebug / lintGrayDebug
root:    verify_project.ps1 / git diff --check / check_text_encoding.ps1
public:  check_public_boundary.ps1 -BaseUrl https://api.zen70.cn (35/35)
```

## 10. 回滚

- 单 PR `git revert` 即可
- DROP TABLE invitations 即可，无 schema 破坏
- 老 owner pairing 流程完全保留

## 11. v0.5 后续（不做但记录）

- Owner 转让
- 邀请二维码生成 + Android 扫码
- 家庭"共同空间"信息流（不仅是账单）
- 多 owner 模式（co-owner）
