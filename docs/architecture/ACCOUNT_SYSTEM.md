# v0.3+ 账号 / 账本 / 设备身份模型（当前基线：v0.9.0a1，`identity_schema=v0.3` 不变）

> 身份契约自 v0.3 起未变更；v0.4 / v0.5 / v0.6-v0.8 / v0.9 的能力演进均建立在该契约之上。版本真值源见 [docs/architecture/VERSION.md](VERSION.md)。

v0.3 把旧 `APP_TOKEN` / `UPLOAD_TOKEN` / `TENANTS_JSON` 运行时模型切换为账号、账本、设备和可撤销凭证。

## 核心对象

- `Account`：可恢复身份。第一版默认 owner 账号显示名为 `我`。
- `Ledger`：账本。旧 `tenant_id` 的值迁移为 `ledger_id` 语义；`expenses.tenant_id`、`category_rules.tenant_id`、`duplicate_ignores.tenant_id` 字段名暂时保留。
- `LedgerMember`：账号在账本里的角色。v0.3 第一版只有 `owner` 和 `member`；v0.4-beta1 家庭账本基础扩展为 `owner` / `member` / `viewer`。
- `Device`：同一账号下的具体设备，用于区分双机和重装后的重新绑定。
- `AuthToken`：Android / admin 会话凭证，只保存 `token_hash`。
- `UploadLink`：iOS 快捷指令上传凭证，只能创建 pending，不能读账本、确认入账、导出、统计或读图片。
- `PairingCode`：Android 一次性绑定码，只保存 `code_hash`，有过期时间，用后即废；消费时原子标记 `used_at`，短时间失败过多会限流。
- `Invitation`：家庭账本邀请。高熵 `invite_token`（明文只在创建响应里出现一次，库内只存 hash），`role` 只接受 `member` / `viewer`（owner 走显式 owner-transfer），带 TTL 与可选备注，可撤销。
- `LedgerAuditLog`：账本内安全/成员变更动作的审计记录（邀请、角色调整、停用、转让等）。

## AuthContext

业务接口使用新的上下文：

```text
account_id
account_name
ledger_id
ledger_name
device_id
device_name
role
scope
```

所有账单、图片、统计、分类规则和重复检测仍按数据库里的 `tenant_id` 字段过滤，但该字段从 v0.3 起表示 `ledger_id`。

## 旧配置迁移

- 没有 `TENANTS_JSON` 时创建默认 `Ledger(ledger_id="owner", name="我的小票夹")`。
- 有 `TENANTS_JSON` 时，每个旧 tenant 创建一个 Ledger，名称沿用旧 tenant name。
- 所有 Ledger 挂到默认 owner account 下；旧 tenant 不自动变成真实朋友账号。
- 旧 `APP_TOKEN` 和旧 `UPLOAD_TOKEN` 只用于识别并返回 `legacy_auth_removed`，不再作为运行时凭证。

## 家庭邀请流（Invitation）

成员入伙不经 PairingCode（那是 owner 自己设备的绑定通道），走独立的邀请链：

```text
owner/管理员：POST /api/ledgers/{ledger_id}/invitations  (role=member|viewer, ttl_days, note)
  -> 响应一次性给出 invite_token 明文（之后只能看摘要/撤销，拿不回明文）
  -> 带外交给家人（口头/微信等，App 不代发）

家人（可以是全新设备，无需先有账号）：
  POST /api/invitations/preview  (invite_token)        # 无鉴权；回账本名/角色/有效期，供确认
  POST /api/invitations/accept   (invite_token, account_name, device_name, platform)
    -> 返回新 session_token + 账本/角色信息，直接入伙
    -> 请求头可带旧 session（可选）：已有账号的设备接受邀请时并入现有 Account

owner/管理员维护：GET 列表 / POST {public_id}/revoke
```

- Android 入口：绑定页「我有家庭邀请」冷启动动线（无需先当一次 owner），以及设置 → 家庭成员页。
- 安全边界：invite_token 为 128 位级高熵随机串，暴力枚举不可行；`preview` 不暴露账本以外的信息；同 token 只能被 accept 一次（原子翻转，并发竞争输者得 409）。`/api/invitations/accept` 当前不在边缘 worker 的限流保护面内（ops 观察项，后端侧高熵 token 已是主防线）。
- 角色语义与 viewer 写入 403 见上文身份模型；全部成员变更动作落 `LedgerAuditLog`。

## Android 恢复

Room 是本机缓存。卸载重装后：

```text
重新安装 App
-> 输入 Pairing Code
-> 后端识别同一 Account / Ledger
-> 生成新 Device 和 session token
-> 本地保存 session token 和账号 / 账本 / 设备信息
-> App 用新 session 执行 syncConfirmed()
-> Room 替换并重建 confirmed 缓存
```

绑定成功后必须先保存 session 和身份，再恢复 confirmed。`syncConfirmed()` 失败时绑定仍然成立，App 提示"已绑定，但历史账本恢复失败，可稍后在账本页更新"，用户可进入账本页手动更新；绑定码不能因为恢复失败而让用户失去重试入口。

这条链路是 v0.3 的核心验收项。
