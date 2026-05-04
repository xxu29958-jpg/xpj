# 0005 Room 使用 serverId 唯一同步

## 决策

Android Room 后续必须让 `serverId` 唯一。

同步 confirmed 账单时使用 upsert：

```text
如果 serverId 已存在，更新本地记录
如果 serverId 不存在，插入本地记录
```

实现时优先显式按 `serverId` 查询已有记录，再用已有记录的本地主键 `id` 执行更新。不要把 Room 主键 upsert 行为误当成 `serverId` 唯一 upsert。

## 原因

避免重复同步导致本地账本重复插入。

## 不允许回退

confirmed 同步不得按普通 insert 重复插入。
