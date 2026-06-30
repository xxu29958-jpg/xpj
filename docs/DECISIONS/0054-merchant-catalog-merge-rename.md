# ADR-0054: 商家目录合并与重命名契约

- 状态：accepted target contract
- 关联：[[0038]]、[[0041]]、[[0042]]、[[0051]]、[[0053]]

## 背景

ADR-0053 已经把 merchant catalog 定义成账本级目录行，并明确删除、隐藏、回收站都不能批量改写历史 `Expense.merchant`。当前运行时已经有目录的 list/create/patch/delete/restore；剩下的高风险点是用户自然会期待的“重命名”和“合并”。

这两个动作不能混在一起：

- 重命名是改同一个目录行的当前显示身份，可能会改变 `merchant_key`。
- 合并是把 source merchant 归并到 target merchant，可能会影响 alias-driven 报表折叠。
- 两者都不能默认重写历史账单事实。
- 两者都必须保护启用别名、固定支出等未来生产者，避免后续流水继续落到用户以为已经处理掉的商家。

标签管理 ADR-0043 提供了一个负面边界：标签 merge 会级联重写账单标签镜像，所以需要快照和 undo；merchant catalog merge 第一版不做这种级联，才能把风险控制在目录行和 alias 层。

## 决策

**1. `PATCH /api/merchants/catalog/{public_id}` 是目录行 rename，不是历史修正**

目录 PATCH 已经存在，继续作为重命名入口。它的语义是“更新当前目录行显示身份”，不是修订已确认账单。

如果新的 `display_name` 归一后 `merchant_key` 不变，这是显示名微调，可以按现有 OCC 更新。

如果新的 `display_name` 归一后 `merchant_key` 改变，这是 key-changing rename。后续运行时必须加上这些保护后才能把它作为完整重命名能力对外承诺：

- 请求必须带 `expected_row_version`。
- 目标 key 若已被同账本任何 catalog 行占用，返回 `409 state_conflict`；响应应尽量带 `conflict_merchant_public_id` 和 `conflict_merchant_row_version`，让客户端引导用户改走 merge。
- 如果当前 key 被 enabled `MerchantAlias.canonical_key` 使用，返回 `409 state_conflict`。
- 如果当前 key 被 active/paused `RecurringItem.merchant_key` 使用，返回 `409 state_conflict`。
- 不改写 `Expense.merchant`、OCR facts、CSV snapshots、debt snapshots 或历史 recurring rows。

这个保护是 delete 边界的同源规则：历史事实不阻塞，仍会继续生产未来事实的配置才阻塞。

**2. Merge 使用独立端点，不能由 rename 冲突自动触发**

未来 runtime slice 使用独立端点：

```http
POST /api/merchants/catalog/{source_public_id}/merge
```

请求体：

```json
{
  "expected_row_version": 3,
  "target_public_id": "target-public-id",
  "target_row_version": 7,
  "alias_policy": "create_source_alias",
  "rewrite_historical_expenses": false
}
```

`alias_policy` 必须显式传入：

- `none`：只把 source catalog 标记为 merged，不新增 alias。
- `create_source_alias`：在 source key 没有 live/soft-deleted alias 冲突时，新增 enabled alias，将 source merchant 指向 target merchant。

`rewrite_historical_expenses` 在第一版只能是 `false` 或省略；传 `true` 返回 `422 invalid_request`。这不是功能缺口，而是 ADR-0053 的事实边界。

**3. Merge 的事务和并发规则**

merge 必须在一个事务中完成：

- ledger-scoped 读取 source 和 target；跨账本表现为 `404 not_found`。
- source 必须是 live 且 status 为 `active` 或 `hidden`。
- target 必须是 live 且 status 为 `active`。
- source 和 target 相同返回 `422 invalid_request`。
- 同时用 `expected_row_version` 和 `target_row_version` claim 两行；任一陈旧返回 `409 state_conflict`。
- 成功后 source 变为 `status='merged'`，`merged_into_public_id=target.public_id`，并 bump source row version。
- target 可以只 bump row version 用于证明 target token 被消费；如果实现选择不 bump target，则必须用等价的锁/claim 证明 target token 参与了并发判定，并用测试覆盖任一 token 陈旧都会 409。

返回体建议包含：

```json
{
  "source": { "public_id": "...", "status": "merged" },
  "target": { "public_id": "...", "status": "active" },
  "created_alias_public_id": "..."
}
```

在 runtime 未落地前，这个端点不得加入 `docs/architecture/API.md` 或 OpenAPI snapshot。

**4. Merge 第一版只处理目录和可选 alias，不迁移未来生产者**

merge 第一版如果发现这些引用 source key 的 active future producers，直接返回 `409 state_conflict`：

- enabled `MerchantAlias.canonical_key == source.merchant_key`
- active/paused `RecurringItem.merchant_key == source.merchant_key`
- 未来新增的任何 active config binding source catalog public id 或 source key

`alias_policy=create_source_alias` 只创建“source key 作为 alias 指向 target”的新关系，不迁移既有 alias，也不修改 recurring 配置。既有 alias 迁移和 recurring rebind 是后续单独切片，因为它们会改变未来自动入账行为。

**5. Merge 不进回收站，也不提供第一版 undo**

merged source 不是 soft-delete：

- `deleted_at` 保持 `NULL`。
- 普通 suggestions/autocomplete 默认不返回 `merged`。
- 管理页可以展示 `merged`，但必须显示它指向的 target。
- `/api/recycle-bin` 不列 merged source。
- 第一版不做 undo。若后续要 unmerge，必须另写 ADR 或扩展本 ADR，定义 alias 回滚、future producer rebind 和并发规则。

这与 tag merge 不同：tag merge 会重写账单标签镜像，所以需要快照 undo；merchant catalog merge 第一版不重写历史事实，也不重写 future producer config，所以先不引入 snapshot 表。

**6. Alias policy 对报表的影响必须是显式用户选择**

`create_source_alias` 会让 enabled alias 在读报表时把历史 source merchant 文本折叠到 target 下。这仍然不是历史账单改写，因为 `Expense.merchant` 原值不变；但用户可见的统计会变化，所以必须由用户明确选择。

客户端文案必须避免“修正历史商家”这类说法，应表达为“以后在统计里归到目标商家”或等价含义。

**7. 幂等边界**

merge 第一版是 online-only mutate surface，不进入 Android persistent outbox；因此可以只依赖 OCC，不强制 `Idempotency-Key`。

如果未来要把 merge 接入离线 outbox 或可重放队列，必须按 ADR-0042 在 OCC claim 之前声明并 claim `Idempotency-Key`，且请求体必须包含 source token、target token、target id、alias policy 和 rewrite flag 的稳定哈希。

## 后果

- Benefit: rename 冲突不会静默变 merge，用户必须明确选择合并。
- Benefit: merge 可以先服务统计折叠和目录清理，不碰历史事实，也不迁移自动入账配置。
- Cost: active alias/recurring 引用 source key 时第一版 merge 会被挡住，用户需要先处理这些配置。
- Cost: merged source 会保留 key 占用；这是为了防止同一 source key 被重新创建后与 alias/reporting 语义打架。
- Rollback: 可以隐藏 merge UI/API；已经 merged 的 source 行保留为目录 tombstone，历史账单无需回滚。

## 切片

1. 本 ADR：定义 rename/merge 的并发、冲突、alias policy 和回收站边界。
2. Backend rename tightening：key-changing PATCH 增加 enabled alias / active recurring blocker，并补冲突测试。
3. Backend merge API：新增 merge schema/service/route/tests，覆盖双 token stale、self merge、target inactive、alias policy、producer blocker、viewer 403、ledger isolation。
4. Web / Android surface：rename 冲突引导 merge；merge 对话框要求显式 alias policy。
5. 后续可选：existing alias migration、recurring rebind、unmerge/undo，均需单独契约。
