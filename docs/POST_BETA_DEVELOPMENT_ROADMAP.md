# v0.4-beta1 后版本开发路线

日期：2026-05-12

本文基于当前文档、`v0.4-beta1-family-ledger-foundation` 分支代码和三路只读梳理结果，整理 `v0.4-beta1` 之后到 `v1.0` 的可执行路线。

它补充 `docs/MONARCH_CAPABILITY_ROADMAP.md`：后者描述 Monarch 对照下的产品能力清单，本文描述按当前代码基线推进时的工程顺序、风险前置项、跨端落点和验收标准。

## 1. 当前基线

已落地能力：

- 身份 / 账本 / 设备 / Pairing / UploadLink / Owner Console 公网边界已经稳定。
- 多账本隔离已进入后端、Android Room v4、`/web` LedgerSelector 和 Owner Console。
- Smart Ledger Engine 已有报表、数据质量、Rules Preview & Apply、Recurring Candidates、Goal MVP 和 Android Review Workflow 拆分。
- `v0.4-beta1` 已有家庭账本基础：邀请创建 / 接受 / 撤销、成员列表、停用成员、`owner` / `member` / `viewer` 三态、member/viewer 角色调整、Android 加入家庭账本、`/web` viewer 只读视图。
- Android 已有待确认、账本、统计、设置四入口；统计页已有 Compose 原生 donut、预算进度、生活统计和 recurring candidates 摘要。
- `/web` 已有 Dashboard、pending Review、confirmed Transaction Center、stats、数据体检、重复、分类、规则、导入导出。
- `/owner` 已有服务、设备、账本、绑定码、上传链接、备份、诊断和家庭账本成员管理。

当前不能假装完成的缺口：

- `POST /api/app/upload-screenshot` 当前仍使用普通 app context，viewer 只读语义需要补 writer guard。
- 分类规则写路径和 `apply-pending` 当前仍使用普通 app context，viewer 只读语义需要补 writer guard。
- 权限错误码存在契约分歧：部分文档写 `viewer_cannot_write`，当前实现和测试更偏 `permission_denied`。v0.5 前必须统一后端、API 文档、Android ErrorMapper 和 runbook。
- Android 版本标识仍有历史 `0.3.3` 痕迹，需要在下一个发布整理版本号策略。
- Android 还没有家庭成员管理页；成员管理主要在 Owner Console。
- `/web` 报表仍偏卡片和表格；Android 已有原生图形，两端统计表达能力不完全对齐。
- `/owner` 视觉仍偏本机后台，尚未完全吸收 `/web` CSS token、状态 chip 和卡片节奏。

## 2. 总原则

- 核心闭环不变：截图上传 -> 识别草稿 -> 人工确认 -> 入账。
- 不做银行聚合、投资净资产、自动入账或 Plaid 替代品。
- 家庭模型反向 Monarch：成员默认拥有独立个人账本，只能看到自己账本和被显式邀请的共享账本。
- 多账本隔离必须在后端按 `ledger_id/account_id/role` 强制，不能靠 UI 隐藏。
- 金额继续使用 `amount_cents`；数据库时间 UTC；统计按 `expense_time`，为空才用 `confirmed_at`。
- `uploads/` 永不公开；图片只走鉴权 API；API 不返回 Windows 真实路径。
- Android 继续遵守 `Screen -> ViewModel -> Repository -> ApiService / Dao / TokenStore` 分层。
- 后端继续遵守 `routes -> services -> database/models` 分层；OCR、分类、重复检测、recurring、规则引擎不写进 route。
- 图表库按 `docs/DECISIONS/0023-chart-library-policy.md` 分阶段受控引入；UI/UX 统一按 `docs/DECISIONS/0024-tri-surface-ui-ux-unification.md` 执行。

## 3. v0.5 Household Hardening

周期：4-6 周。

目标：把 `v0.4-beta1` 的家庭账本基础收口成可信的共享账本权限模型。先修权限缺口，再补 UI 和审计。

### v0.5 必做

- `H05-01` 修 viewer 写入口：上传截图、分类规则 create/update/delete、`apply-pending` 全部改 writer/owner guard，并补 viewer 403 测试。
- `H05-02` 统一权限错误契约：决定保留 `permission_denied` 还是新增 `viewer_cannot_write`，同步 API、runbook、Android ErrorMapper 和测试。
- `H05-03` 家庭成员审计：记录邀请创建、接受、撤销、角色调整、停用；不得记录明文 token。
- `H05-04` Owner 转让：单 owner 转让设计、事务、旧 owner 降级、token 行为、回滚方案；不做 co-owner。
- `H05-05` Android 家庭成员页：成员列表、角色、停用状态、当前账本个人/共享 badge。
- `H05-06` Android viewer 只读 UX：待确认、账本、编辑、手动记一笔、规则页写入口禁用或隐藏，统一提示“当前角色为只读，无法修改账本”。
- `H05-07` 邀请体验增强：复制分享 / 二维码 payload 方案、接受前风险确认、失败不覆盖旧绑定的回归测试。
- `H05-08` 数据完整性 hardening：`Invitation.role`、`LedgerMember.role` 的约束策略、迁移兼容测试和老库升级说明。
- `H05-09` 家庭隐私回归套件：成员 A/B 私有账本不可见、共享账本可见、角色调整不扩大账本集合、停用后 token 失效。
- `H05-10` 文档：`docs/V0_5_HOUSEHOLD_MODEL.md`、邀请 / 停用 / 角色调整 / owner 转让流程图。

### v0.5 不做

- 不做 co-owner。
- 不做家庭成员全账户可见。
- 不把 invite token 并入 pairing token。
- 不做完整预算、完整 recurring 或图表库引入。

## 4. v0.6 Recurring + 通知草稿

周期：4 周。

目标：把 `Recurring Candidates` 从只读候选推进到用户确认的固定支出记录，并让 Android 通知只产生 pending 草稿。

任务：

- `R06-01` 后端 `recurring_items` 表：频率、商家归一名、金额基线、上次金额、下次预计日期、状态 `active/paused/archived`。
- `R06-02` candidates -> recurring：用户确认候选后生成正式 recurring 记录。
- `R06-03` Recurring CRUD API：列表、暂停、恢复、归档、下一次日期重算。
- `R06-04` 异常金额检测：固定支出高于历史均值阈值时只提示，不自动改账。
- `R06-05` Android Recurring 列表页：Upcoming / Active / Paused。
- `R06-06` Android 通知偏好页：待确认提醒、大额提醒、固定支出提醒。
- `R06-07` `NotificationListenerService` spike：仅本机解析微信 / 支付宝 / 银行短信，生成 pending 草稿，不上传通知原文，不自动确认。
- `R06-08` 通知草稿幂等：同通知、同商家金额时间窗口不得反复生成 pending。
- `R06-09` `/web` Recurring 页：列表、候选确认、暂停 / 恢复。

红线：

- 通知监听必须用户显式授权，并可一键关闭。
- 不上传通知原文到服务端。
- 通知、OCR、规则只能生成草稿或建议，绝不自动确认。

## 5. v0.7 Rules / Tags / Merchant Governance

周期：3-4 周。

目标：把分类规则从 substring 工具升级为可审计、可回滚、可解释的商家 / 标签 / 规则系统。

任务：

- `G07-01` 商家别名模型：canonical merchant + aliases，账本内隔离。
- `G07-02` Tags 模型：账单多标签，编辑、筛选、导出、统计 DTO。
- `G07-03` 规则增强：金额区间、商家别名、标签、分类组、优先级。
- `G07-04` dry-run：apply pending / confirmed 前返回影响范围和样本，默认不直接改历史。
- `G07-05` 规则应用审计与回滚：记录变更前后，最近 N 条可回滚。
- `G07-06` 分类组和默认分类管理：禁用、自定义展示名 / emoji，不破坏历史分类。
- `G07-07` Android 商家管理页和规则增强 UI。
- `G07-08` `/web` 商家管理页：合并、改名、别名冲突处理。
- `G07-09` 性能索引：tags、canonical merchant、规则匹配字段补索引和分页测试。

红线：

- 自动改商家名 / 分类必须有 audit log。
- 历史账单批量修改默认 dry-run。
- 不让规则系统绕过账本隔离、权限过滤或人工确认。

## 6. v0.8 Budget + 月度可花

周期：3-4 周。

目标：建立预算数据模型和三端预算 / Dashboard 视觉基线。

任务：

- `B08-01` 分类预算基础：分类额度、剩余、超支提示。
- `B08-02` Flex Budget 简化版：Fixed（来自 recurring）+ Non-monthly（季节性）+ Flex（其他）。
- `B08-03` “本月可花”卡片：Android 首页 / 统计页 + `/web` Dashboard。
- `B08-04` Rollover 简化版：未花完进入下月可用余额；不做按分类 rollover。
- `B08-05` 预算排除分类：投资 / 转账等不参与预算。
- `B08-06` 家庭共享预算：仅共享账本可启用，沿用 v0.5 权限模型。
- `B08-07` Android 预算页：空态、加载、错误、长商家名、窄屏、深色模式。
- `B08-08` `/web` Budget / Dashboard：预算进度、分类预算、共享账本提示。
- `B08-09` `/owner` 状态首页视觉基线：不做普通用户预算功能，只统一卡片节奏和状态语义。

图表策略：

- 主线继续用 Compose Canvas、Web SVG 或 Canvas 原生绘制。
- 可单独 spike 图表库，但不作为 v0.8 主线依赖，不阻塞 RC。
- 先沉淀图表视觉规范，再决定是否引入库。

红线：

- 预算只提示，不阻塞用户操作。
- 图表库不能进入统计口径、预算规则或后端服务层。

## 7. v0.9 Reports / Goals / Chart UX Polish

周期：3 周。

目标：把报表、目标、Dashboard 自定义和统计图美化推进到可对外展示的成熟度。

任务：

- `P09-01` 趋势报表：按日 / 周 / 月支出曲线。
- `P09-02` 商家排行报表：top 10 / top 商家分类切换。
- `P09-03` 分类组对比：环比 / 同比。
- `P09-04` Sankey 简化版：收入入账 -> 分类 -> 商家，仅 `/web`。
- `P09-05` 报表保存 / 分享：导出 PNG / CSV。
- `P09-06` Goals：支出目标、节省目标和目标进度。
- `P09-07` Dashboard 卡片自定义顺序：Android 和 `/web` 独立保存。
- `P09-08` 统计图美化：图例、tooltip / 点击态、颜色语义、长标签截断、深色模式对比度、空数据、导出预览。
- `P09-09` 三端 UI/UX polish：导航命名、交易字段顺序、状态 badge、主次按钮层级、卡片密度、表格空态和错误文案。

图表库条件：

- 允许经过依赖审计和 ADR 后引入一个展示层图表库。
- Android 依赖必须进入 `android/gradle/libs.versions.toml`。
- Web 依赖必须限定在 `/web` 展示层，不使用 CDN。
- 后端仍只返回结构化统计数据，不返回图表库私有格式，不做 PNG 渲染。
- 选型失败必须可回退到原生 Canvas / SVG。

## 8. v1.0 家庭私有账本中枢

目标：把 v0.5 到 v0.9 收口成稳定、可迁移、可验证、可推荐的 1.0。

任务：

- `V10-01` Receipt scanning 增强：OCR 商品级拆分，一张超市小票拆成多项。
- `V10-02` Bill Split：一张小票按家庭成员拆账。
- `V10-03` 大 CSV 导入：10k+ 行流式，避免一次性全量入内存。
- `V10-04` 数据迁移工具：v0.x -> v1.0 一键升级、备份、回滚说明。
- `V10-05` 三端 UI 一致性回归：Compose + Web + Owner Console 截图基线。
- `V10-06` 完整 e2e 测试套件：不少于 50 个真实路径。
- `V10-07` 国际化基础：中文为主 + 英文 fallback。
- `V10-08` v1.0 文档全套：用户手册、部署指南、隐私白皮书、数据可携性说明。

红线：

- 不以图表、预算或家庭协作破坏核心确认闭环。
- 不把家庭权限做成前端过滤。
- 不暴露 uploads、真实本机路径、token、UploadLink 或普通用户不需要的运维细节。

## 9. 跨版本验收矩阵

每个版本必须至少完成：

- 后端：`compileall`、`ruff`、`pytest`、smoke。
- Android：unit test、gray debug build、internal debug build、lint。
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
- 新索引、批处理、超时和资源释放策略有测试或明确验收。

