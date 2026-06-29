# ADR-0051: 统一回收站

- 状态：accepted / partially implemented（2026-06-29：Owner Console `/owner/recycle-bin`；普通 web/Android 当前账本回收站；短窗软删的回收站天级 retention；ADR-0052 月度预算配置归档/恢复）
- 关联：ENGINEERING_RULES §6（持久化/同步/恢复）/ §12（保留天数预算）/ §13（反扩）、[[0038]]（`deleted_at` 软删 tombstone）、[[0043]]（tag mutation-undo）、[[0046]]（Android 周期 worker 边界）、[[0049]]（债务域 append-only，**排除在回收站外**）、[[0052]]（主数据删除边界）

## 2026-06-29 首片落地

首片选择低风险路径：**不新增 retention 字段、不改 purge 语义、不扩 master 删除面**，先在本机 Owner Console 提供统一可浏览/可恢复入口。

- 入口：`GET /owner/recycle-bin`、`POST /owner/recycle-bin/restore`，沿用 `/owner` loopback-only 边界。
- 长期归档项：账本、收入计划、固定支出、目标；ADR-0052 Slice 2 后增加月度预算配置。
- 短窗恢复项：分类规则、商家别名、标签 undo group；仅在现有 undo 窗内展示。
- 恢复逻辑：复用各实体既有 service restore/undo 能力，保留 OCC / row_version 校验。
- 明确排除：已确认账单、债务还款事实、category/merchant master 删除、债务 void/forgive 事实。

## 2026-06-29 普通端当前账本页

第二片继续维持同一低风险边界：新增当前账本维度 `GET /api/recycle-bin`、`POST /api/recycle-bin/restore`，并在 `/web/recycle-bin` 与 Android 设置二级页展示/恢复。

- 普通端只看当前 session token 对应账本，不列已归档账本本身；已归档账本仍只在 owner console 恢复。
- 纳入实体同首片中“账本以外”的可恢复项：收入记录、固定支出、目标、分类规则、商家别名、标签 undo group；ADR-0052 Slice 2 后增加月度预算配置 `monthly_budget`。
- `viewer` 可读不可恢复；恢复仍要求 `owner/member`，并委托各实体既有 restore/undo service。
- 该片当时尚未新增天级 retention、不改 purge、不做 master 删除；第三片见下方 retention 解耦。

## 2026-06-29 后端 retention 解耦

第三片选择决策轴 ①(c)：**普通撤销条仍是 5 分钟，显式回收站默认保留 30 天**。

- 新增配置 `RECYCLE_BIN_RETENTION_DAYS`（默认 30，最小 1），作为分类规则、商家别名、标签 delete/merge undo group 的回收站保留窗口。
- `SOFT_DELETE_RETENTION_MINUTES=5` 继续只代表原撤销 API / banner 的短窗；`/api/*/undo` 与 `/web/*/undo` 默认不放宽，超过 5 分钟仍返回原来的 not_found。
- `/owner/recycle-bin/restore` 与 `/api/recycle-bin/restore` 显式使用回收站窗口，可恢复已超过 5 分钟但未超过 `RECYCLE_BIN_RETENTION_DAYS` 的软删项。
- `soft_delete_purge_scheduler` 继续 opt-in 且复用既有清理路径，但默认硬删 cutoff 改为回收站天级窗口；仍可通过函数参数覆盖分钟窗口用于测试/手动定向清理。
- 本片不新增 per-row retention 字段：当前三类短窗实体已有 `deleted_at` / `created_at` 作为 retention 锚点，且窗口是全局产品策略；master 删除边界见 [[0052]]。

## 背景与问题

用户问「没有回收吗」，指向一个真实缺口：当前删除/恢复是**碎片化、按实体各自实现**的，无统一回收站。现状三种正交「软删」语义并存：

- **`deleted_at` 软删**（merchant_alias / category_rule / tag，[[0038]]）：普通撤销条 5 分钟；显式回收站默认 30 天，过期后由 `soft_delete_purge_scheduler` 永久 purge；
- **`archived_at` 永久归档**（recurring / goal / income_plan / ledger）：永不清理，可从 owner 回收站集中恢复；
- **`status='rejected'`**（expense，复用同一 5min undo 窗）。

剩余不对称与硬缺口：**category / merchant master 完全没有删除入口**；budget 已按 ADR-0052 处理为月度配置归档/恢复。结果：owner 端与普通 web/Android 已有统一「已删/已归档」面，短窗软删项也已从 5 分钟撤销条解耦为默认 30 天回收站保留。

## 决策驱动

- 真实用户缺口（删不掉旧分类/预算/商家；多数删除无恢复面）。
- §6：保留/恢复要有显式策略与回滚；新增非空列三步走。
- §13：不为此上后台任务框架（Celery/RQ）；窄用途调度复用既有能力。
- §0 数据正确性：恢复涉及唯一键/外键/server_id 冲突，必须原子 + OCC。
- 项目形态：single-process FastAPI + PG17 + 三端 token + Windows 任务计划部署 + 离线优先（无编排器）。
- [[0049]]：债务 void/forgive 是 append-only 事实、非「删除」，**不进回收站**。

## 决策轴与当前选择

**① retention 语义（核心，决定是否动 §6）**
- (a) 维持各自短窗，回收站只是「当前可恢复项」的统一只读视图，不改 retention（零架构改动）。
- (b) 把 `SOFT_DELETE_RETENTION_MINUTES` 抬到天级（牵动 alias/rule/tag purge 时机，§6 改动，要回滚演练）。
- (c) **回收站自带独立 retention（天级），与 5min undo 窗解耦**——undo banner 仍即时 5min，回收站另设 N 天保留。
- **首片选择 (a)**：先不动 retention / purge / schema；第三片已落地 (c)。undo banner（临时悬浮）与回收站（显式可浏览）现在按两个窗口长期解耦。

**② scope（哪些实体可进回收站）**
- (a) 仅现有可恢复的软删/归档（alias/rule/tag/income_plan/recurring/goal），并**补 recurring/goal 的 restore**。
- (b) (a) + 给 master（category/budget/merchant）加软删字段 + 删除路由（新 surface，更大）。
- **首片选择 (a) 先**，并额外纳入账本归档恢复；master 删除边界见 [[0052]]，其中月度预算配置归档/恢复已作为真实可恢复行接入；**债务 void/forgive 按 [[0049]] 排除**（voided debt 可见但只读，不当「可恢复删除」）。

**③ 恢复 UX 落点**
- (a) 三端各加用户级统一回收站入口（Android nav 二级页 / web 单页 / owner 单页）。
- (b) **owner console 先**（loopback、owner 已有 ledger archive/unarchive 现成模式、风险最低、可验证闭环），web/Android 后续。
- **首片选择 (b)**：owner 现成参照 + 内网收敛，先把统一入口和 restore 闭环跑通，再铺三端（工作量不对称：web 从零、Android 加二级页、owner 最接近）。

**④ purge 机制**
- **首片不改 purge；第三片扩展 purge cutoff**：继续复用现有 `soft_delete_purge_scheduler`，默认 cutoff 改为 `RECYCLE_BIN_RETENTION_DAYS`，不引 Celery/RQ（守 §13）。

## 后果

- **好**：补上「回收/恢复」体验缺口；recurring/goal restore 对称化；统一「已删/已归档」可浏览面。
- **代价**：retention 选择 (c) 后，purge 与 restore 需要区分 undo 短窗/回收站窗口；三端铺面工作量不对称；恢复 collision 规则要逐实体定。
- **中性**：先 owner-only 落地，再扩三端，分多片渐进。

## 切片划分 + 回收条件

1. 本 ADR + owner console 首片（已完成）。2. 普通 web + Android 当前账本回收站二级页（已完成）。3. 后端 retention 解耦（已完成：配置型全局窗口，未新增 per-row 字段）。4. master 删除边界见 [[0052]]；其中预算月度配置归档/恢复已完成，分类偏好目录和 merchant catalog 后续另片；债务 voided 只读展示如需要另开债务展示 ADR。

回收条件：任一轴落地后若 retention/scope 判断变化，回此 ADR 修订；master 删除以 [[0052]] 为准，债务展示另开 ADR，不在本 scope 隐式扩张。
