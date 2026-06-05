# 0040 outbox 子资源 target_id 锚定 + 子资源 undo 契约

- Status: accepted
- Date: 2026-06-05
- Decision makers: 项目维护者
- 说明: 本 ADR 记录 [[0038]]/[[0041]]/[[0042]] 落地过程中**已存在**的不变量，承重事实已回代码核实（见 Confirmation）。它替换 `expense_service/_update.py::undo_reject_expense` docstring 里「owned by ADR-0040 when landed」的临时占位，把那条占位从「待决」变「已记录」。不引入新行为。

## Context and Problem Statement

两个相邻的子资源（items / splits / suggestion 决策 / bill_split 邀请）边界一直靠散在注释的隐式约定支撑，没有契约文档：

- **子资源没有自己的 CAS token。** [[0041]] 把 OCC 升为 `row_version` 时，items / splits 的响应 DTO（`ExpenseItemResponse` / `ExpenseSplitResponse`）刻意**不带** `row_version`——它们的「替换」操作（`PUT .../items`、`PUT .../splits`）的并发保护与 [[0042]] 的请求幂等都锚在**父 Expense** 的 `row_version` 上。那么 Android outbox 一条 replace-items mutation 到底用什么 `target_id` 定位、cascade 给谁、幂等键 fingerprint 算在谁身上——这些都没写下来，只能从 dispatcher 代码反推。

- **undo 对子资源做什么没定义。** `undo_reject_expense` 的 docstring 明文写「undo ONLY flips the parent」，但把「完整语义（bill_split 邀请该不该重新激活？item 级 acknowledge-mismatch 该不该 persist？）owned by ADR-0040 when landed」——而 ADR-0040 不存在。这是一条悬空引用：reviewer 读到这里无处可查，也无法判断当前「只翻父行」是有意契约还是未完成的 TODO。

问题：这两条都是**已实现**的不变量，但缺正式契约 → 后续改 outbox / 改 undo 的 PR 没有可引用的边界，容易各自重新发明或误以为「子资源没跟着动」是 bug。

## Decision Drivers

- §0 #1 数据正确 / #2 边界清晰：子资源跟随父行的规则必须显式，否则 cascade / undo 行为靠记忆。
- §6 服务端权威 + §7 版本号保护：CAS 锚点必须单一、确定，不能 items 一套 splits 一套。
- [[0042]] 已把「离线边界判据」从隐式注释升为契约；本 ADR 对「子资源锚定 + undo」做同样的升格。
- 复用已有机制：不为子资源新设 token / 新设 undo 路径，沿用父 Expense 锚点。
- 记录已落地的真值，不开新设计（对照 [[0039]] 校准方法）。

## Considered Options

- **A. 维持现状**——子资源边界继续散在 docstring，`_update.py` 的 ADR-0040 占位长期悬空。否：悬空引用本身是债，且 reviewer 无处查证「只翻父行」是契约还是 bug。
- **B. 给子资源各发自己的 `row_version` + 独立 undo**——items / splits 各自 CAS、各自 soft-delete restore。否：违反 §0 #5，给单服务器单家庭场景过设计；且 replace 操作天然是「整组替换」，父行版本已足够表达「这组子资源变了」，再加一层 token 只会让 cascade 锚点二义。
- **C. 形式化已落地的不变量（本 ADR 选）**——把「子资源锚父 Expense `row_version` / outbox target_id = 父 expense / undo 只翻父行」写成契约，替换临时 docstring。

## Decision Outcome

Chosen: **C**。两条不变量升为契约：

**① 子资源锚定父 Expense（outbox target_id 契约）**：items / splits 的 replace 操作没有自己的 CAS token；其 OCC 谓词与 [[0042]] 请求幂等 fingerprint 都锚在**父 Expense `row_version`** 上。一次成功的子资源替换原子地 `bump` 父 `row_version`，响应 wrapper（`ExpenseItemsResponse` / `ExpenseSplitsResponse`）回传父行的 post-mutation `row_version`，让 outbox 把新 token cascade 给同一父 expense 的后续 mutation。Android outbox row 对子资源 mutation 用**父 expense 的 target**（`expense:<parent_id>`）作 `target_id`——因此「替换 items」与「编辑同一 expense」天然 same-target serial 串行，同一父行的多条 mutation 不会乱序。子资源**不**在 outbox 里独立寻址。

**② undo 只翻父行（子资源 undo 契约）**：`POST /api/expenses/{id}/undo` 是 reject 的对称恢复（[[0038]]）；它**只**把父 Expense 的 `status` / `rejected_at` / `row_version` 翻回可编辑态，**不**重放任何子资源状态。具体地：splits、line items、suggestion 决策保留 reject 期间的现状；bill_split 邀请**不**重新激活；item 级 acknowledge-mismatch 的 `items_sum_status` **不**回滚。这是**确定性显式行为**，不是 undefined——undo 的语义是「把这一行拉回 reject 前最普通的可编辑状态」，而非「时光倒流整棵子树」。merchant_alias / rule 的 undo 同构：清 `deleted_at` 恢复该行本身，不反向重建它曾清除过的 duplicate 指针等旁路状态（与 `undo_reject_expense` 已记录的 duplicate-reference 限制一致）。

边界口径：若未来真需要「undo 连子资源一起恢复」（例如拆账邀请回滚），那是**新行为**，须新开 ADR + 设计子资源快照/恢复，不在本契约内悄悄扩。本 ADR 只钉死当前实现 = parent-only。

## Consequences

Good：
- `_update.py` 的悬空 ADR-0040 占位关闭——reviewer 有据可查，「只翻父行」确认为契约而非 TODO。
- 子资源 cascade 锚点单一（父 `row_version`），改 outbox / 加新子资源 replace 时有明确锚定规则，不二义。
- undo 的子资源边界显式，避免后续把「子资源没回滚」当 bug 修出新的不一致。

Bad / 成本：
- undo 是非对称恢复：reject 若有清除旁路状态的副作用（如 clear duplicate references），undo 不反向重建——这条限制现在写进契约，意味着「完整对称 undo」永远是显式新决策，不是默认期望。
- 子资源无独立 token：极端下「父行版本变了但只动了无关子资源」也会让持旧父 token 的并发写撞 409——这是 OCC 锚点单一化的已知代价，对单家庭场景可接受。

回收条件：本契约记录既有实现。若同步模型变化（子资源需独立寻址 / undo 需子资源快照），另写 ADR 重评，不回改本文为「从来 parent-only」。

## Confirmation

- **子资源 wrapper 回传父 `row_version`**：`ExpenseItemsResponse` / `ExpenseSplitsResponse` 带 `row_version`（= 父 expense post-mutation 值），契约测试断言 `== before + 1`；item 响应体本身不含 `row_version`（核对 `expense_service/_expense.py`）。
- **outbox same-target serial**：Android 对同一父 expense 的「replace items」与「patch expense」走同一 `target_id`，drain 顺序串行（[[0038]] outbox 顺序测试 + [[0042]] cascade 测试）。
- **undo parent-only**：`undo_reject_expense` 后断言子资源状态未变——`test_undo_does_not_restore_cleared_duplicate_references` 已钉死 duplicate 指针停在 `None`；splits / items / `items_sum_status` 不被 undo 触碰。
- **ledger_audit_logs**：undo 写 `action='undo'`、`resource_type='expense'`，不破坏既有 audit query。

## More Information

- [[0038]] Multi-Surface Sync——undo（soft-delete + restore window）与 outbox 的源头；本 ADR 把它留的「子资源 undo 完整语义」占位正式关闭。
- [[0041]] PostgreSQL + row_version——子资源锚定的 `row_version` token 来源；items/splits 无自有 token 即此 ADR 的契约前提。
- [[0042]] 离线可用性 + 请求幂等键——子资源 mutation 的 outbox 入队 / 幂等键 fingerprint 锚父 expense，本 ADR 与之同一锚点。
- 替换点：`backend/app/services/expense_service/_update.py::undo_reject_expense` docstring 原「owned by ADR-0040 when landed」段，改为指向本 ADR。
- `docs/rules/ENGINEERING_RULES.md` §0 / §6 / §7。
