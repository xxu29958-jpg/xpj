# ADR-0052: 主数据删除与回收站边界

- 状态：accepted / partially implemented（2026-06-30；Slice 2 月度预算配置归档/恢复、Slice 3 自定义分类偏好已落地）
- 关联：ENGINEERING_RULES §0（裁决顺序）/ §6（持久化、同步、隔离）/ §13（反扩）、[[0013]]（分类目录与旧分类兼容）、[[0038]]（软删 tombstone）、[[0041]]（Postgres + row_version）、[[0043]]（标签管理）、[[0049]]（债务 append-only）、[[0051]]（统一回收站）、[[0053]]（商家目录与删除边界）

## 背景

ADR-0051 已经把现有可恢复项集中到 owner / web / Android 回收站，并把普通撤销 5 分钟窗口与显式回收站 30 天窗口解耦。剩余问题是用户能感知到的「旧分类 / 旧预算 / 旧商家删不掉」，但当前模型并不是三张同构 master 表：

- `category` 现在主要是 `Expense.category`、`CategoryRule.category`、`BudgetCategory.category`、目标等处的字符串；`category_service` 用默认目录 + 已使用分类生成选项，没有持久化 category master 行。
- `budget` 是按月配置：`Budget(tenant_id, month)` 加 `BudgetCategory(tenant_id, month, category)` 子项，不是可复用主数据。
- `merchant` 现在没有 master 表；只有 `MerchantAlias` 作为商家别名管理面，且别名已经软删并纳入回收站。

因此不能把「删除主数据」简单理解成批量改历史账单字段。历史消费里的分类和商家是事实快照，删除 / 隐藏管理项默认不得改写已经确认的账本事实。

## 决策

**1. 事实字段不跟随主数据删除批量重写**

`Expense.category`、`Expense.merchant`、债务还款事实和已确认账单仍是事实记录。删除、隐藏或恢复 category / merchant 管理项时，默认不批量改历史 expense；需要改历史账单时，只能走单笔编辑或未来单独的「合并 / 重命名」批处理契约。

**2. Category 先做账本级偏好 / 目录，不做破坏式删除**

未来若新增 `category_catalog` / `category_preferences` 一类表，只表达当前账本的分类选项偏好，推荐字段包括：`tenant_id`、`name`、`key`、`kind=default|custom`、`deleted_at` 或 `hidden_at`、`row_version`、`created_at`、`updated_at`。

- 默认分类首片不可删除；如需隐藏默认分类，另开 UI/契约切片，避免把系统目录和用户自定义目录混成一种语义。
- 自定义分类删除 = 从选项、配置入口和新建流里隐藏 / 软删；恢复 = 重新回到选项。
- 历史 expense 引用该分类不阻止删除，也不被改写。
- 若仍有 active `CategoryRule`、预算分类配置、目标配置等会继续产生该分类的配置引用，删除应返回 `state_conflict` / `category_in_use`，要求用户先处理配置或走未来 merge/rename 流程。
- 分类 merge/rename 不是本 ADR 首片：它会跨 expense、rule、budget、goal 批量改写，必须另做 OCC、审计、回滚和三端 UX。
- 2026-06-30 落地形态：新增 `category_preferences`（当前仅 `kind=custom`），账单创建 / 编辑使用非默认分类时自动物化 active 偏好；`GET /api/expenses/categories` 返回默认目录 + active custom preferences + 历史已用兜底；软删 custom preference 后从选项中隐藏并压住同 key 的历史兜底，但不改写历史 `Expense.category`。删除 / 恢复走 `expected_row_version`，并接入普通 / owner 回收站 `category_preference`。

**3. Budget 删除按「月度预算配置归档」处理**

预算不是 master catalog，而是某账本某月份的配置。第一片可实现为给 `Budget` 增加 `archived_at` 或 `deleted_at`，父行归档后对应 `BudgetCategory` 子行保留但不参与当前预算视图。

- `DELETE /api/budgets/monthly/{month}` 的语义是归档该月预算配置，不清除历史消费。
- Dashboard / budget 读取默认只看未归档预算；已归档月份在普通回收站和 owner 回收站以 `monthly_budget` 类 item 展示。
- 恢复预算只清父行归档标记，原 category budget 子项原样恢复。
- 对已归档月份再次 `PUT /api/budgets/monthly/{month}` 应返回 `409 state_conflict` 并提示先恢复，避免静默覆盖回收站里的配置快照。
- 月度预算配置轻量且会影响历史复盘，先按长期保留项处理，不进入 30 天 purge。
- 2026-06-29 落地形态：`Budget` 增加 `row_version` 与 `archived_at`；`GET /api/budgets/monthly` 只读取未归档配置并返回归档所需 `row_version`；`DELETE /api/budgets/monthly/{month}` 用 `expected_row_version` 归档；`/api/recycle-bin/restore` 与 `/owner/recycle-bin/restore` 通过 `monthly_budget` 恢复。

**4. Merchant master 删除暂不实现**

当前没有 merchant master 行，只有 `MerchantAlias`。别名删除 / 恢复已经由 ADR-0051 回收站覆盖；历史 `Expense.merchant` 仍是事实字符串。

真正的商家 master 需要另一个设计：`merchant_catalog` 的 canonical key 来源、别名归属、合并冲突、商家统计回填、历史 expense 是否重写等都必须一起定义。ADR-0053 已定义该边界：merchant catalog 是账本级目录行，删除只隐藏 / 软删目录，不批量改写历史 `Expense.merchant`；merge 另片实现。在该运行时代码落地前，不提供「删除商家」入口，也不把 expense merchant 字符串塞进回收站。

**5. 回收站只接入真实可恢复行**

回收站 item 必须指向真实可恢复行，并沿用 `expected_row_version`：

- 可接入：未来自定义 category catalog / preference 软删行、月度预算归档行。
- 已接入：merchant alias、category rule、tag undo group、income / recurring / goal / ledger 等 ADR-0051 既有项。
- 不接入：历史 expense 分类 / 商家字符串、债务还款事实、merchant master（尚不存在）、category merge/rename 批任务（尚未定义）。

权限沿用 ADR-0051：`viewer` 可读不可恢复，`owner/member` 可恢复；owner console 仍只走 loopback 管理面。

## 切片

1. 本 ADR：定边界，不改运行时代码。
2. Budget 月度配置归档 / 恢复：已完成；已有真实 `Budget` 行和稳定月度 API，归档父行并保留 `BudgetCategory` 子项。
3. Category 自定义目录 / 偏好：已完成；新增轻量表与迁移，分类选项改为默认目录 + active custom preferences + 历史已用兜底，custom 偏好软删后纳入回收站。
4. Merchant catalog：边界已由 [[0053]] 定义；运行时代码仍另片实现，不与别名软删混在同片。

## 后果

- 好处：删除语义从一开始就避开历史事实批量改写，恢复行为可审计、可 OCC、可逐实体测试。
- 代价：用户看到的「删掉旧分类 / 商家」会分阶段落地；第一片只会真正解决预算归档和自定义分类偏好，不会魔法般清洗历史账单。
- 回滚：本 ADR 只是契约；后续 schema 片必须按 §6 三步迁移，并提供恢复 / 回滚测试。
