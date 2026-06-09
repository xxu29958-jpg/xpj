# OCC 乐观并发 token：row_version（ADR-0041）

> 实现参考 + 不变量清单。改任何「带 token 的写操作」前先读这页——这套 token 摊在三端
> 几十个站点，改一处容易留暗伤（Slice B 静默 rowcount=0、Slice C 漏一个共享 guard，都栽在
> 没按这清单走）。决策记录见 `docs/DECISIONS/`（ADR-0041）；本页只讲「现状怎么连、不许破坏什么」。

## 一句话
每个 OCC 行带一个 **server 端单调整数 `row_version`**（`server_default=1`，每次 mutate `+1`）。
客户端发请求时带上「自己最后看到的 `row_version`」，后端 `UPDATE ... WHERE row_version =
expected`，rowcount=0 → `409 state_conflict`。**`row_version` 取代了旧的「拿 `updated_at`
当 CAS token」**——`updated_at` 现在**只是展示字段**，不再参与并发控制。

## Token 数据流（端到端）
```
backend Expense.row_version (mutate 时 +1)
  → Response.row_version (int)                     [响应 additively 带]
  → Android XxxDto.rowVersion: Long                [@Json("row_version")]
  → domain Xxx.rowVersion: Long
  → ExpenseEntity.rowVersion (Room 缓存列, DEFAULT 1)
  → (用户改动) 请求 XxxRequest.expectedRowVersion: Long   [@Json("expected_row_version")]
  → 离线时 PendingMutationEntity.expectedRowVersion: Long (DEFAULT 0) / OutboxRow
  → dispatcher 重放 → ApiService → backend CAS
```
`/web`、`/owner` 同理（hidden form 字段渲染整数 `row_version`，`parse_form_row_version_token`
解析 int）。三端共用这一套语义，不接受端内分叉。

## 不变量（破坏 = bug，多半静默）

1. **哪些模型有 row_version**：6 个 OCC model —— `Expense / CategoryRule / MerchantAlias /
   IncomePlan(MonthlyIncomePlan) / RecurringItem / Goal`。**`ExpenseItem` / `ExpenseSplit`
   没有自己的 row_version**：它们的 replace 是对**父 Expense** 做 CAS。父的新 row_version 由
   items/splits/ack 的 **wrapper 响应**（`ExpenseItemsResponse` / `ExpenseSplitsResponse`）
   带出来（自描述契约，ADR-0041 follow-up），供 outbox cascade——别再让客户端二次 GET。

2. **「无 token」哨兵**：非空 `Long` 字段用 `0L`（server row_version 从 1 起，0 永不匹配真行）；
   唯一可空的请求 token 是 `ExpenseUpdateRequest.expectedRowVersion: Long?`（create 复用同一
   DTO，null → Moshi 省略键）。**不要把这个 `Long?` 统一成 `0L`**——create 路径会发
   `expected_row_version: 0`、被后端拒。判断「有没有真 token」：可空处 `== null || == 0L`，
   非空处 `== 0L`。

3. **「value 不只 key」陷阱**（栽过两次）：给请求/cascade 接 token 时，**字段名和值都要翻**。
   重命名 `expectedUpdatedAt`→`expectedRowVersion` 只改 key 不够——喂它的值若还是
   `x.updatedAt`（旧的展示字符串）就错了，要 `x.rowVersion`。**判断条件同理**：gate「这行有没有
   token」必须读 `x.rowVersion`，**不能读还存在的旧字段 `x.updatedAt.isEmpty()`**——后者类型
   合法、编译器不报、且真实数据里两字段同时存在使测试照过，静默漂移（Slice C 的
   `ExpenseRepositoryCore.enqueueStateTransition` 就这么漏的）。

4. **后端 bump 规则**（精确版见 memory / `receipt`、`expense` services）：全新 insert 不 bump
   （`server_default=1` 够）；mutate 现有行 `row_version + 1`；helper claim 后同一 flush 的
   post-claim 属性 set **不再** bump（否则 +2 误触 409）；incidental 改 `updated_at` 的非 helper
   路径（cleanup / 缩略图 / enrich / reactivate / undo）也要 bump，否则行为回退。

5. **`updated_at` 只剩展示**：不许任何 CAS / cascade / 「有无 token」判断读它。

## 改动时的自查（grep 清单）
- 翻/加 token 字段后：`grep "expectedRowVersion =.*updatedAt"`、`grep "updatedAt\.isEmpty\|updatedAt =="`
  （在 token 操作附近的赋值/条件里），逐个确认值/判断读的是 `rowVersion`。
- 加新「带 token 的写」路径：响应要能喂 cascade（要么响应带 `row_version`，要么 dispatcher
  best-effort 重读父）；离线 enqueue 的 payload strip 用 `0L`（非空）/ `null`（可空），dispatcher
  重放前用 `row.expectedRowVersion` 覆盖。
- 加列 / 改 Room schema：Alembic（后端）、Room migration +
  `exportSchema` 的 `NN.json`（Android）三处对齐；Android 迁移由两层守护：
  `AppDatabaseMigrationSqlTest`（JVM/sqlite-jdbc，跑真迁移 SQL，快、本地可验）+
  `AppDatabaseMigrationTest`（instrumented MigrationTestHelper，按导出的 `NN.json` 校验，
  CI 模拟器 lane 跑——依赖的 kotlinx-serialization 已 force 对齐到 1.10.0 解锁）。

## 验证锚点
- 后端：`expected_row_version` 请求字段 + `row_version` 响应字段的契约测试、two-session 409 gate
  （PG lane）、OpenAPI snapshot。
- Android：DTO contract 测试断言 `row_version` 非空 Long 线格；outbox/dispatcher 测试断言
  cascade 用父 row_version；`AppDatabaseMigrationSqlTest` 验 v10→v11；`assertAndroidTestCountEqualsBaseline`。
