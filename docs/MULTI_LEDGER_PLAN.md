# 多账本规划（Multi-Ledger Plan）

> 状态：**v0.3.1 不实现，仅设计**。本文记录多账本拆分的契约和迁移计划，供
> v0.4 / v0.5 落地参考。任何 v0.3.x 提交都不应该直接修改 `tenant_id` 字段
> 名称或在 Android 端缓存多个账本的支出。

## 当前现实

- 后端模型已经是多账本友好的：`Ledger`、`LedgerMember`、`Account` 三张表已
  存在，`Expense.tenant_id` 字段在语义上等价于 `ledger_id`。
- bootstrap 流程只创建一个默认账本（`owner` / "我的小票夹"），且所有 admin
  与 app session 绑定到这个单一账本。
- Android 端 `ExpenseEntity` 没有 `ledgerId` 列，只有 `serverId`。同步、
  pending、stats、settings 等 UI 都假设"当前账本 == 唯一账本"。
- `/api/auth/check` 返回的 `ledger_name` 当前等于"我的小票夹"。

## 目标（v0.4 起）

1. Account 可以同时是多个 Ledger 的成员，且具备 `activeLedgerId`。
2. 任何 Android 端读取的支出条目都必须能追溯到一个明确的 `ledgerId`，并且
   切换账本不会"看到"另一个账本的条目。
3. UploadLink 永远绑定到一个 ledger，切换账本不会改写已有 UploadLink。
4. 历史 v0.3 数据全部归到 `owner` 账本，不丢失。

## 后端契约

- 不重命名 `Expense.tenant_id` 字段（避免破坏式迁移），但所有新接口的 JSON
  字段名改为 `ledger_id`。
- 新增 `GET /api/account/ledgers`，返回当前账户可访问的账本列表。
- 新增 `POST /api/account/active-ledger`，写 server side `Account.active_ledger_id`。
- 所有 `/api/expenses/*` 与 `/api/stats/*` 增加 `?ledger_id=` 过滤；缺省回
  落到 `Account.active_ledger_id`。

## Android Room 迁移计划

```
Migration 7 -> 8:
  ALTER TABLE expense_entity ADD COLUMN ledgerId TEXT NOT NULL DEFAULT 'owner';
  CREATE UNIQUE INDEX idx_expense_ledger_server
    ON expense_entity(ledgerId, serverId) WHERE serverId IS NOT NULL;
  DROP INDEX IF EXISTS idx_expense_serverId;  -- 旧的全局唯一约束
```

- 所有 DAO 查询都必须加 `WHERE ledgerId = :ledgerId` 过滤。
- `SyncRepository` 在拉取 `/api/expenses` 时把响应的 `ledger_id` 写入本地。
- 新增 `SettingsViewModel.activeLedgerId: StateFlow<String>`。

## 防混账测试

- `LedgerIsolationInstrumentedTest`（v0.4 新增）：登录账户 A 拿到账本 1 与
  账本 2，切换 active 后 pending、stats、settings 都不能出现另一账本的
  条目。
- 后端 `test_multi_ledger_isolation.py`：列表接口必须按 ledger 过滤；
  cross-ledger 读取应返回 404。

## 回滚

- v0.4 只需删除 Migration 8，并把 `expense_entity.ledgerId` 字段忽略即可
  回到 v0.3.x。
- 后端无破坏式 schema 变更，可以任意来回切换。
