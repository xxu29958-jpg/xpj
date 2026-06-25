# ADR-0051: 统一回收站（设计先行，待 owner 拍板）

- 状态：proposed（2026-06-25，回应用户「为啥没有清理旧账本/旧设置/旧设备的按钮，没有回收吗」之缺口；HANDOFF 切片 B「设计先行」的落点）
- 关联：ENGINEERING_RULES §6（持久化/同步/恢复）/ §12（保留天数预算）/ §13（反扩）、[[0038]]（`deleted_at` 软删 tombstone）、[[0043]]（tag mutation-undo）、[[0046]]（Android 周期 worker 边界）、[[0049]]（债务域 append-only，**排除在回收站外**）

## 背景与问题

用户问「没有回收吗」，指向一个真实缺口：当前删除/恢复是**碎片化、按实体各自实现**的，无统一回收站。现状三种正交「软删」语义并存：

- **`deleted_at` 短窗软删**（merchant_alias / category_rule / tag，[[0038]]）：5 分钟保留窗后被 `soft_delete_purge_scheduler` 永久 purge；
- **`archived_at` 永久归档**（recurring / goal / income_plan / ledger）：永不清理；
- **`status='rejected'`**（expense，复用同一 5min undo 窗）。

不对称与硬缺口：income_plan 有 archive+restore，但 **recurring / goal 只能单向归档、无 restore 路由**；**category / budget / merchant master 完全没有删除入口**；ledger archive 仅 owner console。无共享的 tenant-scoped 软删查询层。结果：用户看不到「已删/已归档」的统一面，也恢复不了大多数东西。

## 决策驱动

- 真实用户缺口（删不掉旧分类/预算/商家；多数删除无恢复面）。
- §6：保留/恢复要有显式策略与回滚；新增非空列三步走。
- §13：不为此上后台任务框架（Celery/RQ）；窄用途调度复用既有能力。
- §0 数据正确性：恢复涉及唯一键/外键/server_id 冲突，必须原子 + OCC。
- 项目形态：single-process FastAPI + PG17 + 三端 token + Windows 任务计划部署 + 离线优先（无编排器）。
- [[0049]]：债务 void/forgive 是 append-only 事实、非「删除」，**不进回收站**。

## 待 owner 拍板的四个决策（每轴给选项 + 推荐）

**① retention 语义（核心，决定是否动 §6）**
- (a) 维持各自短窗，回收站只是「当前可恢复项」的统一只读视图，不改 retention（零架构改动）。
- (b) 把 `SOFT_DELETE_RETENTION_MINUTES` 抬到天级（牵动 alias/rule/tag purge 时机，§6 改动，要回滚演练）。
- (c) **回收站自带独立 retention（天级），与 5min undo 窗解耦**——undo banner 仍即时 5min，回收站另设 N 天保留。
- **推荐 (c)**：undo banner（临时悬浮）与回收站（显式可浏览）是两种 UX，各服其用；天级 retention 借鉴既有 `delete_image_after_days` / `device_cleanup_retention_days=180` 参数惯例。

**② scope（哪些实体可进回收站）**
- (a) 仅现有可恢复的软删/归档（alias/rule/tag/income_plan/recurring/goal），并**补 recurring/goal 的 restore**。
- (b) (a) + 给 master（category/budget/merchant）加软删字段 + 删除路由（新 surface，更大）。
- **推荐 (a) 先**；master 删除作为后续 ADR/切片；**债务 void/forgive 按 [[0049]] 排除**（voided debt 可见但只读，不当「可恢复删除」）。

**③ 恢复 UX 落点**
- (a) 三端各加用户级统一回收站入口（Android nav 二级页 / web 单页 / owner 单页）。
- (b) **owner console 先**（loopback、owner 已有 ledger archive/unarchive 现成模式、风险最低、可验证闭环），web/Android 后续。
- **推荐 (b) 先**：owner 现成参照 + 内网收敛，先把后端 retention+restore 跑通，再铺三端（工作量不对称：web 从零、Android 加二级页、owner 最接近）。

**④ purge 机制**
- **复用 `soft_delete_purge_scheduler`**（in-process `threading.Thread` daemon + scheduler lease 单实例，opt-in 默认 off）扩展覆盖 retention 到期项，**不引 Celery/RQ**（守 §13）。

## 后果

- **好**：补上「回收/恢复」体验缺口；recurring/goal restore 对称化；统一「已删/已归档」可浏览面。
- **代价**：retention 若选 (c) 要新增字段（§6 三步走迁移）+ purge 扩展；三端铺面工作量不对称；恢复 collision 规则要逐实体定。
- **中性**：先 owner-only 落地，再扩三端，分多片渐进。

## 切片划分 + 回收条件

1. 本 ADR（owner 拍板 ①②③④）。2. 后端 retention 字段（若选 (c)）+ recurring/goal restore API（对称化，走 add-mutating-route skill）。3. owner console 回收站页（loopback）。4. web + Android 回收站二级页（三端同步）。5.（独立 ADR）master 软删 + voided debt 只读展示。

回收条件：任一轴落地后若 retention/scope 判断变化，回此 ADR 修订；master 删除与债务展示须各自新开 ADR，不在本 scope 隐式扩张。
