# 小票夹 vs Monarch 能力路线图

版本范围：`v0.4-alpha3-rc1 -> v1.0`

本文记录小票夹从 `v0.4-alpha3-rc1` 到 `v1.0` 的结构化能力规划。Monarch Money 只作为成熟个人财务产品的信息架构参考，不复制其银行聚合、投资净资产、品牌视觉、专有文案或家庭共享权限模型。

基于当前 `v0.4-beta1-family-ledger-foundation` 代码基线继续排期时，以 `docs/POST_BETA_DEVELOPMENT_ROADMAP.md` 作为后续开发顺序、先修风险和验收闸门。

## 1. 设计原则

- 不抄银行聚合 / 不抄投资净资产：小票夹的核心是"截图 -> 识别 -> 人工确认"，不是 Plaid 替代品。
- 隐私隔离比 Monarch 更强：Monarch household 成员倾向看到全部账户；小票夹相反，成员默认拥有完全独立账本，只能看到自己账本和被显式邀请的共享账本。
- 本地优先：读路径尽量离线可用；写路径里新建账本、切换账本、上传和跨端同步需要联网。
- 每个版本都要可 RC：不允许跨版本未完成态，也不允许把下一版 schema 或 UI 半成品提前合入主线。
- 图表库受控引入：`v0.4-alpha3 GA` 到 `v0.7` 不引入图表库；`v0.8` 可开始评估；`v0.9` 报表增强阶段允许经过依赖审计和 ADR 后引入一个展示层图表库。后端仍只返回结构化统计数据，不承担图表渲染。
- 统计图美化是产品能力：预算、趋势、排行和目标图表必须有清楚的信息层级、深色模式配色、空状态、加载态、错误态、长标签处理和移动端布局，不把"能画出来"当完成。
- 三端 UI/UX 统一是产品能力：Android、`/web`、`/owner` 不强行做成同一布局，但必须共享信息结构、状态词、颜色语义、卡片节奏、空状态、加载态、错误态和用户可读文案。
- 新依赖默认不引入：任何 Android / Web 新依赖都必须先查官方资料或一手元数据，记录到 `docs/REFERENCES.md` 或 `docs/DECISIONS/`，并通过完整验证矩阵。

图表库具体政策见 `docs/DECISIONS/0023-chart-library-policy.md`。

三端 UI/UX 统一政策见 `docs/DECISIONS/0024-tri-surface-ui-ux-unification.md`。

## 2. 已完成

### v0.3 身份系统重做

账号 / 账本 / 设备 / Pairing / Owner Console / UploadLink / 公网边界，验收 35/35。

### v0.4-alpha1 多账本地基

PR #11：

- `/api/ledgers`
- Room v4 `expenses.ledgerId`
- 设置 -> 账本（实验）切换页

### v0.4-alpha2 Tri-Surface UI/UX

PR #12 / #13：

- Android 生活流
- `/web` 桌面账本流
- `/owner` 本机管理流
- 三端信息架构统一

### v0.4-alpha3 Smart Ledger Engine

PR #14 / #15：

- 报表
- 数据质量
- Rules Preview & Apply
- Recurring Candidates
- Goal MVP
- Android Review Workflow 拆分：QuickCategory / QuickMerchant / MissingAmount / BulkConfirm / DuplicateConfirm
- `ExpenseEditScreen` / `LedgerScreen` 拆分

### v0.4-alpha4 Mobile Architecture Stabilization

PR #16：

- `PendingReviewActions` 接口
- 14 个 ViewModel review actions 单测

### v0.4-alpha3-rc1

基线：`aa541ce`

状态：RC1 验收完成，已 tag。

### v0.4-beta1 Family Ledger Foundation

分支：`v0.4-beta1-family-ledger-foundation`

状态：家庭账本基础已落地，详见 `docs/V0_4_BETA1_REPORT.md`。

- 新增 `Invitation` 表、邀请创建 / 接受 / 撤销 API。
- Owner Console 成员 / 邀请页，邀请明文只显示一次。
- Android 设置 -> 加入家庭账本入口。
- `/web` 角色 chip + viewer 只读视图。
- 20 个家庭权限 / 邀请后端测试，覆盖成员看不到他人个人账本的隐私不变式。

## 3. v0.4-alpha3-ga

周期：1-2 周

目标：把 RC1 推进到 GA。零新功能，纯打磨。

当前状态：历史计划项。当前分支已经进入 `v0.4-beta1-family-ledger-foundation`，后续 GA 打磨只在需要补发 alpha3 GA 时回看。

任务：

- T01 修复 `KNOWN_ISSUES` 中 P2-1：`test_admin_devices_and_upload_links.py` 排序 flake（fixture isolation）。
- T02 修复 P2-4：`check_public_boundary.ps1` / `check_selfuse_health.ps1` 默认 `BaseUrl` 不再用占位符，改为必填并提供友好报错。
- T03 `docs/CLOUDFLARE_TUNNEL.md` runbook 顶部增加"重启后检查任务状态"。
- T04 新增 `scripts\daily_health.ps1`，每天自动运行 selfuse health + boundary 并写日志。
- T05 GA tag `v0.4-alpha3` + GitHub Release notes。

红线：

- 不动 schema。
- 不动 token。
- 不动新功能。
- 本阶段不引入图表库或任何 UI 依赖。

## 4. v0.5 Household & 家庭协作收口

周期：4-6 周

对应 Monarch：Household + Shared Views，但隐私模型相反。

| Monarch | 小票夹 |
| --- | --- |
| household 成员共享全部账户 | 成员默认独立账本，仅显式分享 |
| 单一 Budget 页 | 每成员独立预算 + 可选家庭共享预算 |
| 成员可看全部 connected accounts | 成员只能看自己账本 + 被邀请的共享账本 |

任务：

- T10 基于 beta1 邀请模型补齐 member/viewer 角色调整，不引入 co-owner。
- T11 多账本 owner 转让设计与实现；默认不做多 owner。
- T12 Android 设置 -> 家庭成员管理页：查看成员、角色、停用状态。
- T13 Owner Console 家庭成员审计：邀请创建 / 接受 / 撤销 / 成员禁用记录。
- T14 ledger 共享状态显式化：个人账本 / 共享账本文案与 badge，不改变账本隔离模型。
- T15 家庭共享预算接入前置：只允许共享账本启用，个人账本保持独立预算。
- T16 隐私不变式测试继续扩展：成员 A 无法访问成员 B 私有账本，角色调整不扩大可见账本。
- T17 文档：`docs/V0_5_HOUSEHOLD_MODEL.md` + 邀请 / 停用 / 角色调整流程图。

红线：

- 不动现有 device / pairing 协议。
- 继续沿用 beta1 的 `invite_token` 独立体系；不把 invite 并入 pairing token。
- 不引入图表库。
- 不做 Monarch 式 household 全账户可见。

## 5. v0.6 Recurring + Android 通知草稿

周期：4 周

对应 Monarch：Recurring + Bills + Notifications。

任务：

- T20 v0.4-alpha3 已有 Recurring Candidates API -> 用户可"确认候选"形成正式 Recurring 记录。
- T21 后端 `recurring_items` 表：频率 / 上次金额 / 下次预计日期。
- T22 Android Recurring 列表页：Upcoming / Active / Paused 三态。
- T23 异常金额检测：本月固定支出比平均高 30% -> 标记提醒。
- T24 Android `NotificationListenerService`：仅生成 pending，不自动 confirm；支持微信 / 支付宝 / 银行短信。
- T25 通知偏好开关：待确认提醒 / 大额提醒 / 固定支出提醒。
- T26 `/web` Recurring 页。

红线：

- 通知监听必须用户显式授权。
- 必须可一键关闭。
- 不上传通知原文到服务端。
- 不引入图表库。

## 6. v0.7 Rules / Tags / Merchant 系统

周期：3-4 周

对应 Monarch：Rules + Tags + Merchant management + Categories。

任务：

- T30 商家别名表：`美团` / `美团外卖` / `Meituan` -> 统一显示名。
- T31 Tags：已有分类外增加自由 tag，多对多。
- T32 规则增强：金额区间 / 账户 / 标签匹配，目前只有 substring。
- T33 规则排序 + 优先级。
- T34 "应用到历史账单"按钮：已有 apply-pending，新增 apply-confirmed，默认 dry-run。
- T35 Category Group：食 / 行 / 住 / 娱。
- T36 默认分类可禁用 / 自定义 emoji。
- T37 `/web` 商家管理页。

红线：

- 自动改商家名 / 分类要有 audit log。
- 用户可一键回滚最近 N 条规则应用。
- 不引入图表库。

## 7. v0.8 Budget + 月度可花

周期：3-4 周

对应 Monarch：Category Budget + Flex Budget + Rollover。

任务：

- T40 分类预算（基础）。
- T41 Flex Budget 简化版：Fixed（v0.6 recurring）+ Non-monthly（季节性）+ Flex（其他）。
- T42 "本月可花"卡片：Android 首页 + `/web` Dashboard。
- T43 超支提醒：Push + Android 通知。
- T44 Rollover 简化版：未花完 = 下月可用余额；不做按分类 rollover。
- T45 预算排除分类：投资 / 转账不算预算。
- T46 家庭共享预算：v0.5 共享账本下生效。
- T47 预算与统计卡片 UI/UX 基线：统一金额层级、进度条样式、分类颜色、图例、空状态、加载态和超支提示文案。
- T48 三端 Dashboard UI/UX 基线：Android 首页、`/web` Dashboard、`/owner` 状态首页统一卡片节奏、状态颜色、空状态和错误态。

图表策略：

- 默认继续用 Compose Canvas / Web SVG 或 Canvas 做基础预算展示。
- 可以开始调研图表库，但不在预算主线中直接合入依赖。
- 如果确需 spike，必须单独分支、单独 ADR，不得阻塞 v0.8 RC。
- 先沉淀图表视觉规范，再决定是否需要引入库；不要把选型当作美化本身。

红线：

- 预算不绑定具体金额阈值阻塞操作，只做提示。
- 不让图表库进入统计口径、预算规则或后端服务层。

## 8. v0.9 Reports & Goals 增强

周期：3 周

对应 Monarch：Reports + Goals + Dashboard customization。

任务：

- T50 趋势报表：按日 / 周 / 月支出曲线。
- T51 商家排行报表：top 10 / top 商家分类切换。
- T52 分类组对比：环比 / 同比。
- T53 Sankey 简化版：收入入账 -> 分类 -> 商家，仅 `/web`。
- T54 报表保存 / 分享：导出 PNG / CSV。
- T55 Goals：支出目标，例如"本月外卖 < 800 元" + 节省目标。
- T56 Dashboard 卡片自定义顺序：Android + `/web` 独立。
- T57 卡片库：净资产占位 / 待确认 / 本月支出 / 最近上传 / 备份状态 / 设备状态 / Recurring / Goals。
- T58 统计图 UI/UX 美化：趋势线、柱状图、排行图、目标进度、图例、tooltip / 点击态、长商家名截断、深色模式对比度、空数据和导出预览。
- T59 三端 UI/UX polish：统一导航命名、交易卡字段顺序、状态 badge、主次按钮层级、卡片密度、表格空态和错误文案。

图表策略：

- 允许经过 ADR 和依赖审计后引入一个展示层图表库。
- Android 依赖必须进入 `android/gradle/libs.versions.toml`。
- Web 依赖必须限定在 `/web` 展示层，不得使用外部 CDN，不得进入公网普通 API。
- 后端 API 仍返回结构化统计数据，不返回图表专用私有格式，不承担 PNG 渲染。
- 图表库不得用于替代分页、聚合、权限过滤或统计口径校验。
- UI/UX polish 必须同时覆盖 Android 和 `/web`，但允许两端实现方式不同；同一统计含义、颜色语义和空状态文案必须一致。
- 三端 polish 必须同时覆盖 Android、`/web` 和 `/owner`；`/owner` 可以更偏运维密度，但不能像割裂的脚本面板。

红线：

- 不引入银行聚合或投资净资产真实能力。
- 所有报表仍以 `amount_cents`、UTC 时间和账本隔离为底线。
- 图表库引入失败时，必须能回退到原生 Canvas / SVG 展示。

## 9. v1.0 家庭私有账本中枢

目标：把 v0.5 / v0.6 / v0.7 / v0.8 / v0.9 收口成一个稳定可用、可对外推荐的 1.0。

任务：

- T60 Receipt scanning 增强：OCR 商品级拆分，一张超市小票拆成多项。
- T61 Bill Split：一张小票按家庭成员拆账。
- T62 大 CSV 导入：10k+ 行流式。
- T63 数据迁移工具：v0.x -> v1.0 一键升级。
- T64 三端 UI 一致性回归：Compose + Web + Owner Console 视觉对齐，形成发布级截图基线和 UI/UX 检查清单。
- T65 完整 e2e 测试套件：不少于 50 个真实路径。
- T66 国际化基础：中文为主 + 英文 fallback。
- T67 v1.0 文档全套：用户手册 / 部署指南 / 隐私白皮书 / 数据可携性说明。

红线：

- 不以图表、预算或家庭协作破坏"截图 -> 草稿 -> 人工确认 -> 入账"核心闭环。
- 不暴露 uploads、真实本机路径、token、UploadLink 或普通用户不需要的运维细节。
- 不把任何家庭共享权限做成前端过滤。

## 10. 验收节奏

每个版本至少需要：

- 后端：`compileall` / `ruff` / `pytest` / smoke。
- Android：unit test / gray debug build / internal debug build / lint。
- 全局：`scripts\verify_project.ps1` / `scripts\check_text_encoding.ps1` / `git diff --check`。
- 安全：账本隔离、图片保护、token 不泄漏、公网边界回归。
- 文档：新增能力必须有 API、数据模型、回滚或兼容说明。

图表库引入版本还必须额外验证：

- 依赖元数据、许可证和维护状态。
- Android release 包体积和启动影响。
- Web 离线 / 本机可用性，不依赖 CDN。
- 深色模式、空状态、加载中、错误态和长文本布局。
- 图表颜色语义、图例、触摸/鼠标交互、长标签截断、窄屏布局和导出预览。
- 导出 PNG / CSV 的降级行为。

三端 UI/UX 统一版本还必须额外验证：

- Android、`/web`、`/owner` 的首页 / 列表 / 详情 / 空状态 / 错误态截图。
- 交易卡字段顺序、状态词、颜色语义、按钮层级和中文文案一致。
- Android 窄屏、桌面常规宽度和 Owner Console 管理表格都不重叠、不截断关键信息。
- 普通用户 UI 不暴露服务器地址、token、UploadLink、Cloudflare、端口、接口名、脚本名、日志路径或本机真实路径。
