# 0005 Room 使用 `(ledgerId, serverId)` 唯一同步

## 决策

Android Room 后续必须让 `(ledgerId, serverId)` 唯一。`serverId`
仍然对应后端 `Expense.id`，但本地缓存 upsert 只能在当前账本作用域内匹配。

同步 confirmed 账单时使用 upsert：

```text
如果当前 ledgerId 下的 serverId 已存在，更新本地记录
如果当前 ledgerId 下的 serverId 不存在，插入本地记录
```

实现时优先显式按 `(ledgerId, serverId)` 查询已有记录，再用已有记录的本地主键 `id` 执行更新。不要把 Room 主键 upsert 行为误当成 `serverId` 唯一 upsert。

## 原因

避免重复同步导致本地账本重复插入，同时避免切换账本、重新绑定或异常后端返回时，单靠全局 `serverId` 把其他账本的本地缓存改写到当前账本。

## 不允许回退

confirmed 同步不得按普通 insert 重复插入，也不得跨账本按 `serverId` 查找旧行后复用本地主键。
