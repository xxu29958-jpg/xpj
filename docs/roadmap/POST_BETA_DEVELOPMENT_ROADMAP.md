# v0.4-beta1 之后全体开发路线

> **主控文档**：本文是 v0.5→v1.0 的工程执行主控。
> 版本顺序、先修风险、验收闸门和任务清单以本文为准。

日期：2026-05-12（最后更新：2026-05-16）

本文是 `v0.4-beta1` 之后到 `v1.0` 的主开发路线。它不是某一端路线，而是基于当前 `main` 代码、既有文档、分支基线和三路只读梳理结果，按后端契约 / 数据模型、Android、`/web`、`/owner`、UI/UX、测试和发布门禁一起编排。

`docs/roadmap/MONARCH_CAPABILITY_ROADMAP.md` 继续保留 Monarch 对照下的产品能力清单；本文负责回答”按当前代码库怎么推进、每版先修什么、三端怎么一起收口、怎么验收”。

## 1. 当前全量基线

已落地能力：

- 后端已有身份 / 账本 / 设备 / Pairing / UploadLink / Invitation / Owner Console 公网边界，多账本隔离，pending / confirmed CRUD，受保护图片 / 缩略图，OCR provider 管线，分类规则，重复检测，CSV 导出，生活统计，recurring candidates，data-quality，本机 `/web` 和 `/owner`。
- Android 主线是 `TicketboxApp -> ViewModel -> Repository -> ApiService / Room / TokenStore`。Room 当前 schema v4，核心本地表仍是 `expenses`，已含 `ledgerId` 和 server/public id 隔离索引。
- `/web` 和 `/owner` 都在 `backend/app/templates` 与 `backend/app/static` 下，不是独立前端工程。`/web` 已有 Dashboard、pending、confirmed、stats、data-quality、duplicates、rules、import/export；`/owner` 已有服务、设备、账本、绑定码、上传链接、备份、诊断、设置和成员管理。
- 统计现状不均衡：Android 已有 Compose 原生 donut、趋势条、预算提示和 recurring candidates 摘要；`/web` stats 仍主要是卡片和表格；`/owner` 更偏后台管理面板。
- 家庭账本基础已经落地：邀请创建 / 接受 / 撤销、成员列表、停用成员、`owner/member/viewer` 三态、member/viewer 角色调整、Android 加入家庭账本、`/web` viewer badge。

v0.5-v0.8 已完成。当前版本 v0.9.0a1，正在进行 Reports / Goals / Chart UX 收口。后续仍按每版 RC 门禁验证。

v1.0 前仍然不做：大 CSV 10k+ 流式导入、商品级小票拆分和家庭拆账数据模型。

## 2. 不变原则

- 核心闭环不变：截图上传 -> 识别草稿 -> 人工确认 -> 入账。
- 不做银行聚合、投资净资产、自动入账或 Plaid 替代品。
- 家庭模型反向 Monarch：成员默认拥有独立个人账本，只能看到自己账本和被显式邀请的共享账本。
- 多账本隔离必须在后端按 `ledger_id/account_id/role` 强制，不能靠 UI 隐藏。
- 金额继续使用 `amount_cents`；数据库时间 UTC；统计按 `expense_time`，为空才用 `confirmed_at`。
- `uploads/` 永不公开；图片只走鉴权 API；API 不返回 Windows 本机真实路径。
- 后端继续遵守 `routes -> services -> database/models`，不要把 OCR、分类、重复检测、recurring、规则引擎写进 route。
- Android 继续遵守 `Screen -> ViewModel -> Repository -> ApiService / Dao / TokenStore`。
- `/web` 与 `/owner` 可以继续用服务端模板，但 UI token、状态词、错误文案和布局节奏必须逐步统一。
- 每个版本都必须可 RC；不得把下一版 schema、半成品 UI 或未验收依赖提前合入主线。

## 3. 总体版本矩阵

| 版本 | 状态 | 全体目标 | 先修门禁 | 主要跨层交付 | RC 必过 |
| --- | --- | --- | --- | --- | --- |
| v0.5 | ✅ 已完成 | Household 权限与家庭协作收口 | viewer 全写入口后端拦截、权限错误契约统一 | 后端权限 / 审计 / owner 转让，Android 家庭成员页，`/web` 只读强约束，`/owner` 成员审计 | 家庭隐私不变式、viewer 403、跨端只读 UX |
| v0.6 | ✅ 已完成 | Recurring 正式化 + Android 通知草稿 | recurring 持久模型、通知原文不上云 | recurring API / 状态机，Android Recurring 与通知偏好，`/web` Recurring，`/owner` 运维状态 | 幂等草稿、不自动确认、授权可关闭 |
| v0.7 | ✅ 已完成 | Rules / Tags / Merchant 治理 | audit + dry-run + rollback 先于批量历史改动 | MerchantAlias、Tag 多对多、规则增强，Android / `/web` 管理 UI，`/owner` 审计入口 | 批量 dry-run、回滚、分页和账本隔离 |
| v0.8 | ✅ 已完成 | Budget + 月度可花 + Dashboard 基线 | v0.6 recurring 与 v0.7 分类治理稳定 | 服务端预算模型，Android 预算页，`/web` Budget/Dashboard，`/owner` 状态卡统一 | 预算只提示、共享账本权限、UI 截图基线 |
| v0.9 | 🔄 进行中 | Reports / Goals / Chart UX Polish | 报表聚合不得全表扫，图表库必须 ADR | 趋势、排行、分类组、Goals、Dashboard 自定义，三端 UI/UX polish | 大数据聚合、导出、深色/窄屏/空态、可回退图表 |
| v1.0 | 📋 计划中 | 家庭私有账本中枢稳定版 | v0.5-v0.9 无跨版未完成态 | 商品级 OCR、家庭拆账、10k CSV、迁移工具、i18n、完整文档 | 50+ e2e、迁移/回滚实测、隐私和数据可携性 |

## 4. v0.5 Household Hardening（已完成）

周期：4-6 周。

目标：把 beta1 家庭账本基础收口成可信的共享账本权限模型。先修安全和契约，再做家庭协作 UI。

后端 / API / 数据：

- `H05-01` 修 viewer 写入口：Android 上传、规则 create/update/delete、`apply-pending`、`/web` save/confirm/reject/bulk/rules/import confirm 全部改 writer/owner guard。
- `H05-02` 统一权限错误契约：保留当前实现里的 `permission_denied`，同步 `docs/architecture/API.md`、beta1 runbook、Android ErrorMapper 和测试。
- `H05-03` 家庭成员审计：邀请创建、接受、撤销、角色调整、停用；不得记录明文 token、UploadLink 或本机路径。
- `H05-04` Owner 转让：保持单 owner，不做 co-owner；事务内完成新 owner 提升、旧 owner 降级、审计和失败回滚。
- `H05-05` export/import 权限决策：明确 viewer 是否可批量导出；CSV import confirm 必须 writer guard。
- `H05-06` 邀请 / 成员约束迁移：`Invitation.role`、`LedgerMember.role` 约束策略、老库兼容、回滚说明。

Android：

- `H05-07` 设置 -> 家庭成员管理页：成员列表、角色、停用状态、当前账本个人/共享 badge。
- `H05-08` Viewer 只读 UX：上传、手动记账、待确认确认/拒绝、账单编辑、规则页写入口禁用或隐藏，统一提示“当前角色为只读，无法修改账本”。
- `H05-09` `permission_denied` ErrorMapper 和离线/弱网回退文案；角色撤销后重新校验 token 和 ledger 可见性。
- `H05-10` 接受邀请防误绑定：接受前展示账本名、邀请角色、当前账号；失败不覆盖旧绑定。

`/web`：

- `H05-11` viewer badge、只读提示和写按钮状态保持一致；直接 POST 必须由后端拒绝，模板隐藏只做体验。
- `H05-12` rules、import/export、pending bulk、confirmed edit 的权限文案统一。

`/owner`：

- `H05-13` 成员管理改为统一状态 chip、角色调整确认、停用确认、一次性邀请码明文区和长文本不溢出。
- `H05-14` 成员审计页或审计区：按账本展示操作时间、动作、操作者、目标成员和结果。

UI/UX：

- `H05-15` 三端统一角色词：拥有者、成员、只读；统一个人账本 / 共享账本 badge。
- `H05-16` 覆盖空家庭、只有 owner、viewer、停用成员、邀请过期、网络失败、长中文账本名。

文档 / 验收：

- `H05-17` 文档：邀请、停用、角色调整、owner 转让、viewer export 决策、回滚方案（v0.5 已收口，详细见 `docs/current/CHANGELOG.md` v0.5 段）。
- 必跑后端权限回归：`test_family_ledger_permissions.py`、`test_tenant_isolation.py`、`test_web_role_badge.py`、`test_import_export.py`、`test_alpha3_engine.py`。
- 必跑 Android：viewer 登录、角色撤销、弱网、离线 Room 回退、长中文和空状态。

红线：

- 不做 co-owner。
- 不把 invite token 并入 pairing token。
- 不做 Monarch 式 household 全账户可见。
- 不引入图表库或预算主模型。

## 5. v0.6 Recurring + 通知草稿（已完成）

周期：4 周。

目标：把 recurring candidates 变成用户确认后的固定支出记录，并让 Android 通知只生成待确认草稿。

后端 / API / 数据：

- `R06-01` 新增 `recurring_items`：频率、商家归一名、金额基线、上次金额、下次预计日期、状态 `active/paused/archived`、账本隔离字段。
- `R06-02` candidates -> recurring：用户确认候选后生成正式 recurring 记录。
- `R06-03` Recurring CRUD API：列表、详情、暂停、恢复、归档、下一次日期重算。
- `R06-04` 异常金额检测：固定支出高于历史均值阈值时只提示，不自动改账。
- `R06-05` 通知草稿幂等键：同来源、同商家金额时间窗口不得反复生成 pending。

Android：

- `R06-06` 拆 `RecurringRepository`，新增 `RecurringItem` DTO/domain。
- `R06-07` Recurring 页面：Upcoming / Active / Paused 三态、候选确认、暂停 / 恢复。
- `R06-08` 通知偏好页：待确认提醒、大额提醒、固定支出提醒。
- `R06-09` `NotificationListenerService` spike：用户显式授权、本机解析微信 / 支付宝 / 银行短信、可一键关闭。
- `R06-10` 只上传结构化草稿字段，不上传通知原文；通知草稿只能进入 pending，不能 confirm。

`/web`：

- `R06-11` Recurring 页：候选、正式记录、暂停 / 恢复、异常金额提示。
- `R06-12` stats/Dashboard 中把 recurring candidates 与正式 recurring 区分展示。

`/owner`：

- `R06-13` 仅展示服务状态、最近 recurring 任务统计和错误计数；不做普通账本 recurring 操作入口。

UI/UX：

- `R06-14` 固定支出状态、异常提示、通知授权说明三端文案一致；Android 授权页不能暗示自动入账。

文档 / 验收：

- 新增 recurring API、状态机、幂等和通知隐私说明。
- 测试覆盖候选确认、状态转换、异常金额、幂等、viewer 只读、账本隔离。

红线：

- 通知监听必须用户显式授权，并可一键关闭。
- 不上传通知原文。
- OCR、通知、规则、recurring 都只能生成草稿或建议，绝不自动确认。

## 6. v0.7 Rules / Tags / Merchant Governance（已完成）

周期：3-4 周。

目标：把分类规则从 substring 工具升级为可审计、可回滚、可解释的商家 / 标签 / 规则系统。

后端 / API / 数据：

- `G07-01` `merchant_aliases`：canonical merchant + aliases，账本内隔离，冲突检测。
- `G07-02` `tags` 与账单多对多关系：编辑、筛选、导出、统计 DTO；若 Android 缓存 tags，需要 Room v5 migration。
- `G07-03` 规则增强：金额区间、账户/来源、商家别名、标签、分类组、优先级和排序。
- `G07-04` dry-run：apply pending / confirmed 前返回影响范围、样本、冲突和不可改原因。
- `G07-05` 规则应用审计与回滚：记录变更前后，最近 N 条可回滚。
- `G07-06` 分类组和默认分类管理：禁用、自定义展示名 / emoji，不破坏历史分类。
- `G07-07` 性能索引：tags、canonical merchant、规则匹配字段、批量应用分页和超时。

Android：

- `G07-08` 商家管理、规则增强、tag 编辑与筛选 UI。
- `G07-09` dry-run 预览、影响数量、样本列表、确认应用、回滚入口。
- `G07-10` 长商家名、别名冲突、标签过多、空规则、规则失败态。

`/web`：

- `G07-11` 商家管理页：合并、改名、别名冲突处理。
- `G07-12` Rules 页升级为条件编辑、dry-run、apply-confirmed、审计和回滚。

`/owner`：

- `G07-13` 只提供审计查询和异常概览，不做普通商家治理主入口。

UI/UX：

- `G07-14` 商家、分类、标签、规则状态词跨端统一；批量操作必须先展示影响范围。

文档 / 验收：

- 新增规则审计、回滚、tag/merchant API、迁移兼容说明。
- 测试覆盖 tag filter/export、merchant merge 冲突、dry-run、apply-confirmed、rollback、viewer 只读、分页性能。

红线：

- 历史账单批量修改默认 dry-run。
- 自动改商家名 / 分类必须有 audit log。
- 不让规则系统绕过账本隔离、权限过滤或人工确认。

## 7. v0.8 Budget + 月度可花（已完成）

周期：3-4 周。

目标：建立服务端预算数据模型和三端 Dashboard 视觉基线。

后端 / API / 数据：

- `B08-01` 分类预算模型：分类额度、周期、剩余、超支提示、账本隔离。
- `B08-02` Flex Budget 简化版：Fixed（来自 v0.6 recurring）+ Non-monthly（季节性）+ Flex（其他）。
- `B08-03` 月度可花 API：Dashboard DTO 明确 fixed、flex、spent、remaining、excluded。
- `B08-04` Rollover 简化版：未花完进入下月可用余额；不做按分类 rollover。
- `B08-05` 预算排除分类：投资 / 转账等不参与预算。
- `B08-06` 家庭共享预算：仅共享账本可启用，权限沿用 v0.5。

Android：

- `B08-07` 从本机 `monthlyBudgetCents` 迁移到服务端账本预算：明确旧本地预算是个人本机提示还是迁为当前 ledger 草稿。
- `B08-08` 预算页、本月可花卡片、分类预算、共享账本权限提示。
- `B08-09` 首页 / 统计页接入预算 DTO，覆盖空态、加载、错误、深色模式和窄屏。

`/web`：

- `B08-10` Budget 页和 Dashboard 预算卡：预算进度、分类预算、共享账本提示、超支提醒。

`/owner`：

- `B08-11` 统一状态首页卡片节奏和状态语义；不做普通用户预算操作。

UI/UX：

- `B08-12` 三端 Dashboard 基线：金额层级、进度条样式、分类颜色、图例、空状态、加载态和超支提示文案一致。

图表策略：

- 主线继续用 Compose Canvas、Web SVG 或 Canvas 原生绘制。
- 可以单独 spike 图表库，但不进入 v0.8 主线依赖，不阻塞 RC。
- 先沉淀图表视觉规范，再决定是否引入库。

文档 / 验收：

- 新增预算模型、权限、口径、迁移和回滚说明。
- 测试覆盖跨月 rollover、预算排除、共享账本权限、统计口径、旧本地预算迁移。

红线：

- 预算只提示，不阻塞用户操作。
- 不改变 `amount_cents` 和统计时间口径。
- 图表库不能进入统计口径、预算规则或后端服务层。

## 8. v0.9 Reports / Goals / Chart UX Polish

周期：3 周。

目标：把报表、目标、Dashboard 自定义和统计图美化推进到可对外展示的成熟度。

后端 / API / 数据：

- `P09-01` 趋势报表：按日 / 周 / 月支出曲线，数据库层聚合，不做 Python 全表扫描。
- `P09-02` 商家排行：top 10 / top 商家分类切换；修正 `/web` 先取全局 top 再按月份过滤的统计风险。
- `P09-03` 分类组对比：环比 / 同比。
- `P09-04` Goals 模型：支出目标、节省目标、进度、状态、账本隔离。
- `P09-05` Dashboard 卡片顺序：Android 和 `/web` 独立保存。
- `P09-06` 导出：结构化 CSV，PNG 导出由展示层完成；后端不渲染图表主路径。

Android：

- `P09-07` 趋势、排行、分类组、Goals、Dashboard 自定义。
- `P09-08` 图表交互：tooltip / 点击态、图例、长标签、深色模式、空数据、加载、错误。

`/web`：

- `P09-09` Reports 页：趋势、排行、分类组、Sankey 简化版、导出预览。
- `P09-10` Dashboard 卡片库：待确认、本月支出、最近上传、Recurring、Goals、预算、备份状态、设备状态；净资产只能是占位或说明，不做真实投资聚合。

`/owner`：

- `P09-11` 视觉 polish：导航命名、状态 badge、表格密度、空态、错误态、长文本处理；保持运维定位，不扩成普通账本应用。

UI/UX：

- `P09-12` 统计图美化：颜色语义、图例、tooltip / 点击态、长标签截断、深色模式对比度、空数据、导出预览、移动端布局。
- `P09-13` 三端 UI/UX polish：交易字段顺序、状态词、主次按钮层级、卡片密度、表格空态和错误文案。

图表库条件：

- 允许经过依赖审计和 ADR 后引入一个展示层图表库。
- Android 依赖必须进入 `android/gradle/libs.versions.toml`。
- Web 依赖必须限定在 `/web` 展示层，不使用 CDN，不引入 React/Vue/Svelte/Node 构建体系，除非另开架构 ADR。
- 后端仍只返回结构化统计数据，不返回图表库私有格式，不承担 PNG 渲染。
- 选型失败必须可回退到原生 Canvas / SVG。

文档 / 验收：

- 新增报表 API、Goals 模型、导出契约、图表库 ADR 或原生图表实现说明。
- 测试覆盖大数据聚合、分页、权限隔离、导出契约、深色/窄屏/长文本/空态截图。

红线：

- 不引入银行聚合或投资净资产真实能力。
- 图表库不得用于替代分页、聚合、权限过滤或统计口径校验。

## 9. v1.0 家庭私有账本中枢

目标：把 v0.5 到 v0.9 收口成稳定可用、可迁移、可验证、可对外推荐的 1.0。

后端 / API / 数据：

- `V10-01` Receipt scanning 增强：OCR 商品级拆分，一张超市小票拆成多项。
- `V10-02` Bill Split：一张小票按家庭成员拆账，沿用家庭权限和审计。
- `V10-03` 大 CSV 导入：10k+ 行流式，分页预览、批处理、失败报告、可重试。
- `V10-04` 数据迁移工具：v0.x -> v1.0 一键升级、备份、回滚说明和实库演练。

Android：

- `V10-05` 商品级小票确认、家庭拆账、导入进度、迁移提示、中文主界面和英文 fallback。

`/web`：

- `V10-06` 大 CSV 导入、商品级条目查看、家庭拆账管理、导出和数据可携性入口。

`/owner`：

- `V10-07` 迁移 / 备份 / 健康检查 / 数据导出状态可视化；不暴露普通用户不需要的 token、路径、端口和脚本细节。

UI/UX：

- `V10-08` 三端 UI 一致性回归：Compose + `/web` + `/owner` 截图基线、发布级 UI/UX checklist。
- `V10-09` 完整空态、错误态、加载态、长文本、深色模式、窄屏和管理表格密度检查。

文档 / 验收：

- `V10-10` 不少于 50 个真实路径 e2e。
- `V10-11` v1.0 文档全套：用户手册、部署指南、隐私白皮书、数据可携性说明。
- `V10-12` 迁移 / 回滚实库演练和 10k CSV 流式测试。

红线：

- 不以图表、预算或家庭协作破坏核心确认闭环。
- 不把家庭权限做成前端过滤。
- 不暴露 uploads、真实本机路径、token、UploadLink 或普通用户不需要的运维细节。

## 10. 图表库与统计图策略

- `v0.5-v0.7`：不引入图表库。主要风险是权限、数据模型、审计和批量安全，不应把复杂度放到展示依赖。
- `v0.8`：允许单独 spike，不进入主线、不阻塞 RC。主线用 Compose Canvas、Web SVG 或 Canvas。
- `v0.9`：允许引入一个展示层图表库，但必须先补 ADR 和依赖审计：官方资料、一手元数据、许可证、维护状态、包体积、离线能力、深色模式、无障碍、导出、失败回退。
- 后端 API 永远只返回结构化统计数据，不返回图表库私有格式，不承担图表渲染主路径。
- 图表美化不是“换库”：颜色语义、图例、tooltip、长标签、空态、加载态、错误态、导出预览和移动端布局都必须验收。

## 11. 三端 UI/UX 统一策略

- Android、`/web`、`/owner` 不强行同布局，但必须共享信息结构、状态词、颜色语义、字段顺序、按钮层级、空态、加载态、错误态和中文文案。
- `/owner` 保持本机管理流定位，不能变成普通账本应用；但视觉上要吸收 `/web` 的 token、状态 chip、卡片节奏和长文本处理。
- `/web` 是桌面账本流，报表和预算应比 Android 更适合表格、导出和管理；Android 优先日常录入、确认、提醒和扫视。
- 所有 UI 功能都必须覆盖 secondary pages、empty/loading/error states、长中文商家名、长账本名、金额极值、无数据月份、深色模式和窄屏。
- 普通用户 UI 不暴露服务器地址、接口名、Cloudflare、端口、日志路径、脚本名、本机真实路径、token 或 UploadLink。

## 12. 每版验收矩阵

每个版本至少完成：

- 后端：`compileall`、`ruff`、`pytest`、smoke。
- Android：`testGrayDebugUnitTest`、`assembleGrayDebug`、`assembleInternalDebug`、`lintGrayDebug`。
- 全局：`scripts\verify_project.ps1`、`scripts\check_text_encoding.ps1`、`git diff --check`。
- 安全：账本隔离、viewer 只读、图片保护、token 不泄漏、公网边界回归。
- 文档：API、数据模型、回滚或兼容说明、runbook。

涉及 UI/UX 的版本额外检查：

- Android、`/web`、`/owner` 首页 / 列表 / 详情 / 空状态 / 错误态截图。
- 深色模式、长中文商家名、长账本名、金额极值、无数据月份。
- 交易字段顺序、状态词、颜色语义、按钮层级和中文文案一致。
- `/web` 和 `/owner` 公网仍 403；普通用户 UI 不暴露服务器地址、接口名、Cloudflare、端口、日志路径或本机真实路径。

涉及数据 / 权限 / 迁移的版本额外检查：

- 兼容老库启动、升级、回滚。
- 账本隔离在后端查询和 service 层同时生效。
- 批量操作有分页、dry-run、审计和回滚。
- 新索引、批处理、超时、幂等和资源释放策略有测试或明确验收。

## 13. 长期方向（v1.0 之后）

### 运维稳定化

- Windows 计划任务稳定化和 Tunnel 在线检查。
- 后端日志轮转和上传目录占用预警。
- 数据库备份和恢复自动化。
- release APK 版本、签名和发布记录。
- GitHub Release 自动附带 APK 和校验摘要。
- Cloudflare Access 保护 Web 管理页。

### 插拔智能层

- OCR / 本地大模型 / 分类 / 重复检测 / 图片压缩 provider 可配置切换。
- provider 通过配置切换，失败必须 fallback 到规则或空实现。
- 不把模型调用写死进 route，不让模型自动确认账单。
- 不把用户截图发到第三方服务，除非用户明确配置并理解风险。

