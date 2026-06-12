# ADR-0048: 吉祥物动画技术栈采用 Rive

- 状态：proposed（2026-06-13，用户拍板「Rive + ADR-0048」）
- 关联：[MASCOT_BRIEF.md](../roadmap/MASCOT_BRIEF.md)（角色「夹夹」设计真相源）、[[0044]]（string-resourcing）、ENGINEERING_RULES §9 依赖治理 / §14 三端视觉同步 / §13 反扩

## 背景与问题

UIUX 第四波要给三端（Android / `/web` / `/owner`）引入一只**可爱、专业、有记忆点且会交互**的吉祥物「夹夹」（拟人长尾夹，见 brief）。它要对约 10 个 app 事件做反应（确认一笔→蹦、目标达成→撒花、空闲→打盹、下拉→伸懒腰…），并随 **paper / mono / midnight** 三主题自动换色。

静态 SVG 插画已被产品否决（不可爱、无交互）。需要一套**状态机驱动 + 运行时换色**的动画运行时。约束：① 离线优先 / 自托管 / 零 telemetry（[[project_deployment_state]]）；② §9 不引 alpha/beta 进主线；③ §14 三端共用一套视觉、不分叉；④ §13 不为「以后可能用」上大框架——只服务吉祥物这一窄用途。

## 决策

采用 **Rive** 作为吉祥物动画运行时：

- **运行时（只用稳定版）**：Android 用 `rive-android` 的 **View API**（`RiveAnimationView` 经 `AndroidView` 包进 Compose）；web 用 `@rive-app/canvas`。**不采用 Rive 的 Compose API（当前 beta）**，待其 GA 再评估迁移（守 §9）。
- **单一 artboard + 状态机喂三端**：同一个 `.riv` 文件 + 同一套状态机，Android 与 web 共用（对上 §14 三端同步）。app 把事件映射成状态机 **input**（trigger / boolean / number），吉祥物只**读** app 状态、绝不回写业务（纯表现层）。
- **运行时绑色**：颜色全部 runtime 绑定到主题 token，**不在 `.riv` 里烤死颜色**，三主题自动换。
- **资产入库**：`.riv` 为二进制，加 `.gitattributes` 标记 `*.riv binary`；体积小（Rive 比等价 Lottie 小 10–15×）。原画经 AI 出图/插画师 → Rive 编辑器绑骨 → 导出 `.riv`。**Rive 编辑器是 SaaS 创作工具，但运行时与 `.riv` 全本地、无联网无 telemetry**——只把导出的 `.riv` + 开源 runtime 打进发行物。
- **范围限定**：仅一只吉祥物 artboard + 空态/事件反应；**不**作为通用动画框架推广，新增动画面须回看本 ADR 范围。

## 为什么是 Rive（而非备选）

- **Lottie**：颜色烤死在文件里、运行时改不动 → 三主题直接出局；纯播放无状态机、不能对事件反应；文件大 10×。
- **Compose 原生 + web CSS/SVG（无依赖兜底）**：不动依赖树，但①复杂状态机封顶（10 态事件反应难手写到位）；②三端各写一份动画 = 违背 §14 单一真相源精神；③人力成本高。仅作 Rive 被否时的降级方案。
- **静态 SVG / GIF / 视频**：SVG 已被产品否决；GIF/视频无主题换色、无交互、体积重。
- Rive：MIT、离线、状态机、运行时换色、小、一套喂三端——且是 Duolingo 同款管线，正对本场景。

## 后果

- **好**：可爱 + 可交互吉祥物可落地；顺带补上「里程碑庆祝」缺口（[[project_milestone_feedback_gap]]，撒花态）；三端单一资产真相源；体积小；离线 + MIT 干净。
- **代价**：新增两个依赖（`rive-android`、`@rive-app/canvas`）须集中 pin + 纳入 §9 升级流程；git 多一类二进制资产（`.riv`）；多一个 SaaS 创作工具（仅创作，非运行时）；View API 经 `AndroidView` 包，略不如原生 Compose 顺手，需 lifecycle/recomposition 护栏。
- **中性**：美术管线 = AI 出图/插画师 → Rive 绑骨 → `.riv`；设计真相在 MASCOT_BRIEF.md。

## 回收条件 / 降级

吉祥物是**叠加层**——拿掉 Rive 不破坏任何业务闭环。若 Rive runtime 出现稳定性/维护问题，吉祥物优雅降级为**静态主题化 SVG 空态**（保留空态文案与引导，仅失去动效）。运行时版本 pin 死；Compose API GA 后重评迁移。

## 验证

- 依赖在版本目录集中 pin，跑 §9 升级三件套（单测 / 关键构建 / lint+审计）。
- `.riv` 本地 raw 加载，Android **不新增联网权限**；release/encoding 审计仍绿。
- 三主题下吉祥物配色经 runtime 绑定正确切换（无烤死色）。
- Rive 层纯表现：审查确认它只读 app 状态、不写任何业务/服务端状态（§5 / §8 AI/动画不改用户数据的同源精神）。
