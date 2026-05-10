# v0.3 账号 / 账本 / 设备身份模型（当前版本：v0.3.3；阶段：v0.3.3-productization）

v0.3 把旧 `APP_TOKEN` / `UPLOAD_TOKEN` / `TENANTS_JSON` 运行时模型切换为账号、账本、设备和可撤销凭证。

## 核心对象

- `Account`：可恢复身份。第一版默认 owner 账号显示名为 `我`。
- `Ledger`：账本。旧 `tenant_id` 的值迁移为 `ledger_id` 语义；`expenses.tenant_id`、`category_rules.tenant_id`、`duplicate_ignores.tenant_id` 字段名暂时保留。
- `LedgerMember`：账号在账本里的角色。第一版只有 `owner` 和 `member`。
- `Device`：同一账号下的具体设备，用于区分双机和重装后的重新绑定。
- `AuthToken`：Android / admin 会话凭证，只保存 `token_hash`。
- `UploadLink`：iOS 快捷指令上传凭证，只能创建 pending，不能读账本、确认入账、导出、统计或读图片。
- `PairingCode`：Android 一次性绑定码，只保存 `code_hash`，有过期时间，用后即废；消费时原子标记 `used_at`，短时间失败过多会限流。

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
