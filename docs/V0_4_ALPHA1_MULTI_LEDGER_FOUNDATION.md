# v0.4-alpha1 多账本基础（Multi-Ledger Foundation）

> 状态：**已完成**（PR #11 squash → main，2026-05-10）。本文保留为多账本
> `ledger_id` 隔离模型和 Room v4 迁移的权威参考。

## 范围

本里程碑只处理“多账本基础”：

- 服务端：`/api/ledgers` 列表 / 新建 / 切换；`Pair` 与 `AuthCheck` 返回
  `ledger_id`；`/api/expenses/*` 与 `/api/stats/*` 接受 `?ledger_id=`，
  缺省落在会话当前的 `ledger_id`，**不**在客户端选择。
- Android：Room schema 升级到 v4，新增 `expenses.ledgerId`（Migration 3→4，
  非破坏），登录态保存 `active_ledger_id`、`active_ledger_name`、可见账本
  列表 JSON；新增 `LedgerRepository`，新增“账本”页面用于切换 / 新建。

不在本期：

- 账本归档 / 删除 / 转让
- 跨账本统计 / 跨账本搜索
- 邀请成员 / 角色变更 UI

## 数据模型

服务端模型未改动；只是把已有的 `Ledger / LedgerMember / Account` 暴露
给 Android。`Expense.tenant_id` 仍是物理字段名，对外语义等价 `ledger_id`。

Android 端：

- `expenses.ledgerId TEXT NOT NULL DEFAULT 'legacy'`，Migration 3→4 通过
  `ALTER TABLE` 写入，并补建 `index_expenses_ledgerId`。**禁止**
  `fallbackToDestructiveMigration`。
- 旧版本未带 `ledger_id` 的本地行落到 `'legacy'`，下次同步会被服务端
  权威覆盖。

## 鉴权与会话

- 登录 / 配对成功后，服务端把当前账本 ID 写到响应里（`PairResponseDto.ledger_id`，
  `AuthCheckDto.ledger_id`），Android 持久化为 `active_ledger_id`。
- 切换账本通过 `POST /api/ledgers/{ledger_id}/switch`：
  - 服务端轮换会话 token，旧 token 立刻失效；
  - Android 收到响应后**先**保存新 token，再保存 `active_ledger_id`，
    再 `clearForLedger(targetLedgerId)` 清理目标账本的本地缓存——
    顺序错了就会把旧 token 留在磁盘上。
- 客户端**绝对不**通过 query / body 自带 `ledger_id` 来变更归属，
  只能通过 switch 接口。服务端一切以会话 token 解析出的账本为准。

## 失败语义

- 列表 / 切换返回 4xx 时把 `error / message` 透传给用户；
- 名称为空：`请填写账本名称。`（服务端 + 客户端双校验）；
- 名称过长：`账本名称最多 60 个字。`；
- 切换到无权限账本：`请选择一个有权限的账本。`；
- 网络失败：`网络连接失败，请检查电脑端服务。`。

## UI

- 设置 → 账本（实验）：当前账本卡片 / 列表 / 刷新 / 新建。
- 列表里点“切换”后，Settings 页的 `onSync` 会被触发，重新拉一次确认数据。

## 升级路径

- v0.4-alpha1 → v0.4：增加成员管理、邀请、账本归档；保持 schema v4 不动。
- 旧版客户端：`legacy` 兜底分组保证升级后历史数据仍可见；不会自动清空。

## DAO upsert 的 “legacy claim” 语义

- `expenses.serverId` 在客户端有 `UNIQUE` 索引，对应服务端单一自增主键；
  同一逻辑行升级前可能落在 `ledgerId='legacy'`，升级后第一次同步当前账本
  会再次拉到同样的 `serverId`。
- `ExpenseDao.upsertByServerIdForLedger` / `upsertAllByServerIdForLedger`
  使用 `findAnyByServerIds`（**不**带 `ledgerId` 过滤）做命中判定；命中则
  走 update 路径并把 `ledgerId` 改写为当前账本，等价于一次性把 legacy 行
  “认领”到当前账本，避免插入冲突。
- 由于 serverId 全局唯一，这一行为不会跨账本错配；当一个 serverId 实际
  归属另一个账本时，服务端不会向当前会话返回它。

## 真机灰度验收（v0.4-alpha1）

- 个人 → 家庭账本切换，`/api/expenses/pending` 与 `/api/expenses/confirmed`
  在 token 轮换后立刻按账本隔离；
- Owner 账本 6 张待确认 / 3 笔 ¥3,547.58；家庭账本 0 张 / 0 笔；
- token 表保留所有历史 token 的 `revoked_at`，旧 token 不会复活；
- Android 本地缓存按 `ledgerId` 隔离；强杀 / 重启后仍正确；
- legacy 行在第一次同步时被认领到 owner，不再以 `legacy` 形式残留。
