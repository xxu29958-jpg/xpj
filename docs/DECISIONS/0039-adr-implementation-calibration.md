# 0039 ADR Implementation Calibration

- 状态: accepted
- 日期: 2026-05-27
- 决策人: 项目维护者

## Context and Problem Statement

ADR-0001..0038 已覆盖金额、时间、身份、权限、图表、AI provider、学习反馈、v1.3 多端同步等核心边界。v1.2.0 release 之后，项目进入高密度清债和 v1.3 同步增强阶段：多个 PR 同时修改 backend、Android、`/web`、release audit 和 OpenAPI contract。

问题不是"ADR 方向是否整体错误"。当前代码审查结论是：大多数 ADR 方向仍正确，但部分 ADR 出现三类漂移：

- 原始决策正确，落地实现比 ADR 更细或略有不同。
- ADR 文字仍按旧阶段描述，后续 ADR 或代码已经收窄 / 替换了局部边界。
- ADR 是计划型决策，部分实现已经落地，但不能被当作完成态文档读取。

`docs/DECISIONS/README.md` 明确要求：ADR 一旦下发不再重写；方向变更写新 ADR。校准必须保留旧 ADR 的历史权威，同时把当前实现状态和后续验收点显式记录，避免后续 reviewer 在旧文字和新代码之间反复拉扯。

本 ADR 的校准基线是 git `54c21841`（2026-05-27 当前 `origin/main`）。如果后续 PR 修复了本文列出的实现 gap，应该在对应 PR description / CHANGELOG / 新 ADR 中关闭条目，不回改本 ADR 为"从来没有 gap"。

## Decision Drivers

- `ENGINEERING_RULES` §0：数据正确、安全边界、稳定运行优先于文档漂亮。
- `ENGINEERING_RULES` §13：没有可执行检查的规范，只算文档；文档不得声明未实现能力。
- ADR 历史不可抹平：旧 ADR 是当时决策记录，不应为了显得整齐而删除 Bad consequence 或重写原始判断。
- 代码 / OpenAPI / 测试 / release audit 是当前状态真值；ADR 是决策真值。
- 校准要能指导下一步 PR，而不是制造一批没有验收标准的文字债。

## Considered Options

- 选项 A：逐份修改旧 ADR，把文字直接改成当前实现。
- 选项 B：**新增一份校准 ADR，按实现状态分桶，并把后续验收写入 Confirmation**（本 ADR 选）。
- 选项 C：每个漂移点都新开独立 ADR。
- 选项 D：不写校准文档，只在 review 对话里记住。

## Decision Outcome

Chosen: **B — 新增校准 ADR，不重写旧 ADR**。

本 ADR 不 supersede ADR-0001..0038；它是当前实现审计后的校准索引。后续处理规则：

- 原 ADR 决策仍绑定，除非新的 ADR 明确 `Supersedes`。
- 纯文字路径 / 阶段描述 / cross-reference 漂移，可以在低风险 docs PR 中追加 Errata 或由本 ADR 统一记录。
- 发现真实功能 bug，优先修代码和测试，不用文档解释掉。
- 计划型 ADR 的未完成部分必须继续留在 roadmap / PR 拆分里，不得因为部分落地而改成完成态。

### Still Binding and Current

以下 ADR 与当前实现主干一致，可继续作为 review 标准使用：

`0001`, `0002`, `0003`, `0004`, `0005`, `0007`, `0009`, `0010`, `0011`, `0013`, `0014`, `0015`, `0016`, `0020`, `0023`, `0025`, `0028`, `0030`, `0035`。

### Binding with Implementation Notes

以下 ADR 方向正确，但读取时必须带当前实现注记：

- `0006`：Windows PowerShell + UTF-8 BOM 决策正确；脚本真实路径已经收敛到 `backend/scripts/setup_backend.ps1` 等分层路径，不能再按早期 root-level 路径理解。
- `0008`：`public_id` / theme JSON 边界仍正确；普通 UI copy 仍需持续避免把内部 ID 暴露成工程术语。
- `0012` / `0017`：错误文案与灰度边界仍正确；普通 UI 中出现 `OCR`、接口名、诊断词时应按文案债处理，不代表 ADR 放宽。
- `0019`：自定义背景本地-only 仍正确；实现已包含原图 + 裁剪图两个本地文件，不应按"单一 background file"理解。
- `0021`：OCR draft provenance 仍正确；v1.2 OCR single-source 迁移后，legacy 判断不再要求 `expenses.raw_text` 非空，`ocr_facts` 是新事实源。
- `0022`：家庭账本权限模型仍正确；owner transfer、邀请和 audit log 已扩展，不应只按 v0.5 起草时的最小权限说明理解。
- `0024`：三端 UI/UX 统一仍正确；`/web` 公网边界已由 `0028` 收窄为 session-gated public web，旧的 loopback-only 描述只适用于 `/owner`。
- `0027`：backend authoritative FX 仍正确；"fixed CNY" 应读作当前默认 home currency，不应阻止后续可配置 home currency 的实现。
- `0029`：拆账隐私分桶仍正确；文档中的 `[[0019]]` 通知草稿交叉引用属于文档引用债，不改变拆账隐私决策。
- `0036`：AI budget privacy 边界仍正确；实现增加了 `MockBudgetAdvisor` 作为 dev/test provider，隐私边界仍由 allowed-fields contract 约束。
- `0037`：学习反馈三表决策仍正确；当前 `algorithm_decisions` 状态机已扩展到 `accepted` / `dismissed`，模型 docstring 中"two append-only tables"等早期措辞应以后续实现为准。

### Priority Calibration Work

以下条目不是文档措辞问题，而是需要后续 PR 用代码 / 测试 / 浏览器验证收口：

1. `0026` `/web` ECharts wiring：`reports.js` 查找 `reports-overview-data`、`reports-trend-chart`、`reports-merchant-chart`、`reports-category-chart`；模板当前渲染 `chart-trend` / `chart-category` 等 ID。该 ADR 只有在真实浏览器看到 ECharts 容器渲染，或模板 / JS / 测试 contract 对齐后，才能算完全闭环。
2. `0031` v1 cut-over atomicity：`v1_migration_service` 走 snapshot + app_meta 写入的简化路径是正确方向；但 `app_meta_service.mark_v1_cut_over_completed()` 的 docstring 声称 single transaction，而 helper `set_value()` 自带 commit。调用方应继续使用 `v1_migration_service` 的受控路径，后续可把 app_meta 写入改成真正单事务 helper，或把 docstring 改到不误导维护者。
3. `0038` Android outbox：backend mutate-token coverage 已进入 `release_audit.py`，Room outbox / WorkManager / drain engine 也已落地；但截至本基线，production mutation call site 还未 enqueue 到 outbox，dispatcher 仍只有 `PatchExpenseDispatcher` reference implementation。PR-2g.3+ 必须继续把 16 个 mutation call site 和剩余 dispatcher 逐个接入。
4. `0038` Undo：soft-delete + `POST /api/<resource>/{id}/undo` + 三端 undo banner + `ledger_audit_logs action='undo'` 尚未完成。现有 `image_deleted_at` / `thumbnail_deleted_at` 只是图片清理字段，不等于业务 undo。

## Consequences

Good:

- 保留旧 ADR 的历史决策，不把原始 tradeoff 擦掉。
- reviewer 可以把"方向错了"、"实现未完成"、"文档措辞滞后"三类问题分开处理。
- v1.3 剩余 PR 有清晰顺序：先修真实功能验证 gap，再做低风险文字校准。

Bad:

- 多一份 ADR 需要维护；如果后续 PR 修了 gap 但不更新 CHANGELOG / Confirmation，本文会变成新的状态债。
- 本 ADR 是基于 `54c21841` 的快照，不替代未来逐 PR review。

## Confirmation

本 ADR 的有效性靠以下检查维持：

- ADR index check：`docs/DECISIONS/README.md` 必须列出 `0039`，下一编号改为 `0040`。
- Backend audit：运行 `backend/scripts/release_audit.py`，其中 mutate-token coverage 必须继续显示 0 known gaps。
- Web chart verification：修 `0026` 时必须有模板 / JS contract 测试，最好补真实浏览器或 screenshot 验证 `/web/reports` ECharts 非空渲染。
- v1 cut-over verification：修 `0031` 时必须证明 app_meta 三键写入在一个事务里，或明确把 service docstring 降为"受控 cut-over path"而非"atomic helper"。
- Outbox verification：完成 `0038` PR-2g.3+ 时，grep 应能看到 mutation call sites 调用 `outboxRepository.enqueue(...)`，并且每个 `PendingMutationType` 都有对应 dispatcher 或明确的 not-yet-wired test guard。
- Undo verification：完成 `0038` Undo 时，OpenAPI / tests 必须能找到 `POST /api/<resource>/{id}/undo`，并有 `ledger_audit_logs` `action='undo'` 断言。

## More Information

- [[0036]] 是本 ADR 的结构模板：Context / Drivers / Options / Outcome / Consequences / Confirmation。
- [[0038]] v1.3 Multi-Surface Sync 是当前最重要的计划型 ADR；本文只校准完成度，不改变其方向。
- `docs/rules/ENGINEERING_RULES.md` §0 / §13 / §14：文档、实现、验收冲突时的裁决顺序。
