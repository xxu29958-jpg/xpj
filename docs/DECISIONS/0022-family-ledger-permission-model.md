# 0022 — Family Ledger Permission Model

- 状态：accepted
- 日期：2026-05-11
- 上下文：v0.4-beta1 家庭账本基础（branch `v0.4-beta1-family-ledger-foundation`）
- 决策人：项目维护者

## 背景

v0.4-alpha 已落地多账本（`ledger_id` 隔离 + `LedgerMember(role, disabled_at)` 多对多关系 + `switch_ledger` token 轮换）。但目前实际只有 owner 角色被签发：所有 `_ensure_membership` 调用都写 `"owner"`，没有任何"邀请家庭成员加入既有账本"的入口。

要把"个人 RC1"推进到"家庭 beta"，需要：

1. 一个**邀请流转模型**（owner 签发 → 接受方手机扫码/输入 → 服务端校验 → 写 LedgerMember）。
2. 一个**权限模型**：明确每个角色能/不能做什么，以及后端如何强制（**不靠 UI 隐藏**）。
3. **隐私不变式**：成员加入"共享家庭账本"不会破坏其"个人账本"隔离。

## 决策

### 角色三态（不再扩展）

| 角色 | 写账单 | 看账单 | 管成员 | 切账本 | 删账本 | UploadLink |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| `owner` | ✅ | ✅ | ✅ | ✅ | ✅ | 创建/旋转/撤销 |
| `member` | ✅ | ✅ | ❌ | ✅ | ❌ | 仅查看自己的 |
| `viewer` | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ |

> 决定不引入第四级 `admin` / `co-owner` / `editor`——三态够覆盖"我 + 配偶 + 父母"全部场景。Monarch household 全员等权太宽，预算合算工具 YNAB 太严，这里取中。

### 隐私不变式（**家庭模型核心**）

**成员加入家庭账本 ≠ 共享其个人账本。** 每个账户 (Account) 可同时是：
- 自己个人账本的 `owner`
- 一个或多个家庭/共享账本的 `member` / `viewer`

成员 A 看不到成员 B 的个人账本，即使两人都在同一家庭账本里。隔离仍然在 `(ledger_id, account_id)` 维度，**不在 household 维度做账户聚合**。

→ 与 Monarch 的"household 看全部 connected accounts"模型相反。

### 邀请流转

```
[Owner Console / Android Settings → 邀请成员]
   ↓ POST /api/ledgers/{ledger_id}/invitations
   ← invite_token (one-time, hash stored, 7d expiry, single-use)
   ↓ owner 通过线下渠道（微信/口头/二维码）分享给被邀请人
[被邀请人 Android App → 加入家庭账本 → 扫码/输入]
   ↓ POST /api/invitations/accept {invite_token, device_name}
   ← {session_token, ledger_id, role}
   → LedgerMember(account_id=邀请方接受者, role=invite.role) 写入
   → 邀请记录 mark used
   → 签发 app-scope AuthToken
```

**邀请记录字段**：
- `id` / `public_id` (UUID, 暴露给 owner UI)
- `ledger_id` FK
- `token_hash` (SHA-256, **明文 token 仅在创建响应里返回一次**)
- `role` (`member` / `viewer`，不能创建 `owner` 邀请——owner 必须显式转让)
- `created_by_account_id` FK
- `created_at` / `expires_at` / `used_at` / `used_by_account_id` / `revoked_at`
- `note` (owner 标注，可选，最多 60 字)

**约束**：
- 邀请单次使用：`used_at IS NULL AND revoked_at IS NULL AND expires_at > now()` 才有效
- 默认 7 天过期
- 同一 (ledger, role) 可同时存在多个有效邀请，由 owner 自行管理

### 权限强制点（**纵深防御**）

1. **`AuthContext.role`** — 已落地，每个请求随 token 解出 role。
2. **`permission_service.py`** — 新增，提供 `can_write_expense(ctx)` / `can_manage_members(ctx)` / `can_invite(ctx)` 等谓词。所有路由必须显式调用，不允许"路由层无校验、ORM 层兜底"。
3. **Service 层 ledger_id 过滤** — 已落地（所有查询 where ledger_id=ctx.ledger_id），不变。
4. **`_web_require_local`** — `/web` 和 `/owner` 公网继续 403，不在本期改动。

### 邀请安全要点

- `invite_token` **明文绝不入库**，只存 `token_hash = sha256(token)`。
- `invite_token` 明文**绝不写日志**（沿用现有 `test_*_no_secret_leak` 测试覆盖到新路由）。
- accept 接口必须**不响应明文 token**，即使是创建立刻就 fetch 也只有创建时那一次能拿到。
- accept 失败（过期/已用/被撤销）一律返回 `{"error": "invitation_invalid"}`，**不区分原因**（避免侧信道）。
- accept 必须绑定 `device_name`，与 pairing 流程一致；新设备需要重新 pair 才能用。

### 旧库兼容

`LedgerMember` 已存在于 alpha1。**唯一新增 schema 是 `invitations` 表**，老库启动时 `Base.metadata.create_all` 自动建表（无破坏性变更）。

`AuthContext.role` 老 token 是 `"owner"`（默认账本 owner），新流程不影响存量行为。

## 替代方案（已否决）

- **共享账户模型（Monarch 同款）**：成员能看全部账户。否决理由：与"私有账本"产品定位冲突，且需要在数据层做 account → ledger 映射的视图聚合，复杂度爆炸。
- **5 级角色**（owner / admin / editor / member / viewer）：否决，三态够用，更多角色 = 更多 bug。
- **基于角色的 column-level 隐私**：否决，过早优化，账单全字段都已经按 ledger_id 隔离了。

## 后果

- 所有写路径必须 `permission_service.require(...)` 显式校验。
- 旧测试如果绕过 AuthContext 直接 mock 出 `role="owner"`，行为不变。
- v0.5/v0.6 可在此基础上加邀请 QR 码 / 二维码扫描 / Owner Console 邀请审计。

## 不做

- 不做邀请二维码生成（明文 token + 复制按钮够用）。
- 不做邀请通知/Email/SMS（明文 token 由 owner 线下传递）。
- 不做角色变更（member → viewer / viewer → member），第一版只能 disable 后重新邀请。
- 不做 owner 转让（v0.5 候选）。
