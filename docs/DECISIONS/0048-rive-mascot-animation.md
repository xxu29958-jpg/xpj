# ADR-0048: 吉祥物动画技术栈采用 Rive

- 状态：**rejected / 放弃（2026-06-25，用户拍板）** —— Rive 的 `.riv` **导出被付费墙挡死**（Rive 编辑器 `Publish → To .riv` 要 `Cadet $9/seat/mo` 订阅；运行时虽 MIT 免费，但**没有 `.riv` 就没东西可运行**）。为一只吉祥物的导出包月 + 按座位收费 + 绑一个 SaaS 创作工具，不值。吉祥物动画改走**原生 Compose**（见下「撤回」段）。曾短暂 accepted（2026-06-25）、原 proposed（2026-06-13）。
- 关联：[MASCOT_BRIEF.md](../roadmap/MASCOT_BRIEF.md)（角色「夹夹」设计真相源——**角色设计仍有效**，仅 §8 Rive 绑骨清单作废）、[[0044]]、ENGINEERING_RULES §9 / §14 / §13

## 撤回（2026-06-25）

> 决策反转。本 ADR 正文（采用 Rive）连同「实施补充」自此**仅作历史记录**，不再执行。

- **为什么放弃**：实操踩到本 ADR 写作时未知的硬约束——Rive 编辑器**导出 `.riv` 是订阅付费功能**（$9/seat/mo 起）。Codex 已在 Rive 桌面正式版把夹夹完整做出（artboard `JiajiaMascot` 512×512、12+ 部件、`JiajiaStateMachine` 11 态 / 362 关键帧、`JiajiaMascatModel` Data Binding 28 色节点、`milestone_celebrate`=3.6s、Problems 面板 0 报错）——但 `Publish → To .riv` 撞 `Upgrade to export`，**导不出来**。MCP 也无本地保存 `.riv` 接口。这份 Rive 工作量因付费墙**搁浅、不可取回**（除非付费），不作为仓库资产依赖。
- **改走什么**：吉祥物动画用**原生 Jetpack Compose Canvas**（已落地 PR [#108](https://github.com/xxu29958-jpg/xpj/pull/108) `f2d13875`：占位画布加呼吸脉动 + 打盹 zzz）。本 ADR 当初否决「Compose 原生」的理由是「10 态难手写 + 三端各写一份」——但那是相对 Rive 的取舍；Rive 既因付费墙出局，**原生 Compose 成为最优可行解**：零依赖、零订阅、离线、运行时换色随手（直接喂 `MascotPalette` 的 Compose `Color`，无需 `.riv` 色属性那套）、完全自控、可真机眼验。代价 = 富动画要手写、web/owner 端动画另写（CSS/SVG）——接受。
- **保留有效的部分**：① 角色设计真相源 MASCOT_BRIEF §1-§7（夹夹造型、可爱公式、三主题 token 映射、10 态语义）**仍是设计准绳**；② 本 ADR「为什么不是 Lottie / 静态 SVG」的横向比较仍可参考；③ `MascotStateMachine`（11 态纯 Kotlin）+ `mascotPalette`（三主题单源）+ `MascotPlaceholder`（现在是**正式渲染器**不再是占位）继续用。
- **作废的部分**：rive-android / `@rive-app/canvas` 依赖（不引入）、`res/raw/mascot.riv`（不会有）、`.gitattributes *.riv binary`（不需要）、MASCOT_BRIEF §8 Rive 绑骨交付清单。
- **后续若要更丰富的吉祥物动画**：原生 Compose 扩展事件态（confirm 蹦 / milestone 撒花等），不另开付费工具;真要换动画运行时须新开 ADR。

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

## 实施补充（2026-06-25，穷尽调查后定稿）

进场时把当初 proposed 留的技术不确定性钉死，并确立分期。每条都是落地约束，不是另起决策。

- **依赖版本**：`app.rive:rive-android`（Maven Central，MIT，整条 11.x 线 `prerelease=false`）。进场时 pin **当前 stable（≥11.6.2）**，**不要** pin 旧地板版——Data Binding/ViewModelInstance（运行时换色靠它）在旧版未必有。伴随 `androidx.startup:startup-runtime`。走 §9 三件套（`check_dependency_versions.ps1` → release notes → `verify_project.ps1`）。web 端 `@rive-app/canvas` 同理 pin stable。
- **运行时换色（支柱已证可行）**：stable 经 **Data Binding** 支持运行时覆盖部件色：`vmi.getColorProperty("槽位路径").value = 0xAARRGGBB`（单个 `Int`），**经 View API 也能用**（`controller.stateMachines.first().viewModelInstance = vmi`），颜色不烤进 `.riv`，下一帧 advance 生效。`MascotPalette` 的 11 个 `Color` 槽位 → `Color.toArgb()` 转 `Int` 喂入（一次机械转换，渲染层做）。`.riv` 必须按 brief §7.1 的 `mascot.*` 语义名建可覆盖色属性——这是 app↔`.riv` 的颜色契约（见 brief §8）。
- **API 选型（前提已变，重新裁决）**：Rive 现已把 **View/XML API 标为 Legacy**（将来废弃、几乎不加新功能），**Compose API 虽挂 beta 但官方称 production-ready / 新项目推荐**。本 ADR **维持 View API**（守 §9 不引 beta 进主线的字面红线），但**新增回收条件**：Rive Compose API GA（去 beta 标签）后重评迁移；若 View API 公布确切废弃时间表早于 Compose GA，提前开 follow-up ADR 重裁。不再把 View 当永久安全默认。
- **实施分期（关键，且这是「现在不加 native 依赖」的理由）**：`.riv` 资产是**人在 Rive 编辑器的手工产物**，工程无法绕开、当前**无排期**。故依赖 + `RiveAnimationView` wrapper + `res/raw/mascot.riv` + `.gitattributes *.riv binary` **一起、待 `.riv` 到位时作为一个可眼验切片落**，**不提前**单独加 native 依赖——否则是 §13「为以后上框架」：多 ABI `.so` 即时增大 APK（**仓内无 APK-size 门**）、拖慢已 ~28-29min 逼近 40min 超时的 Android lane、且集成码在无资产时**不可眼验**，换来零可见收益。纯 Kotlin 状态机 / `mascotPalette` 单源 / 画布兜底**已就绪且已单测**，无需提前动。
- **接线形态**：在 `MascotPlaceholder(state, palette, modifier, size)` **内部分流**（有 `.riv` 走 Rive、无/加载失败回 `drawJiajiaPlaceholder`），5 个调用点零改动，天然满足本 ADR 的优雅降级契约。wrapper 放 `ui/mascot/`（避开从 Backend lane 扫 `ui/components`+`ui/screens` 的 `android-alpha-ratchet`）。**画布兜底即降级**——ADR 上文「静态主题化 SVG 空态」是措辞，Compose Canvas 等价，不必另出 SVG。
- **状态机覆盖**：代码有 **11** 态（比 brief 表的 10 态多一个 `Neutral→idle_awake` 隐式睁眼基线）。产 `.riv` 时这个 state 也要在 Rive 状态机里有，否则绑定层喂不进（见 brief §8）。
- **动画时长隐式契约**：庆祝浮层把 `visible` 窗口硬绑 `ONE_SHOT_DURATION_MS.getValue(Celebrating)=3600ms`，**无机器门守护**。`.riv` 的 `milestone_celebrate` 动画时长须对齐此常量，否则浮层提前/滞后消失。
- **三端同步缺口**：web/owner 端**当前零吉祥物、`tokens.css` 零 `mascot.*` token**。`_audit_token_parity.py` **不覆盖** `mascot.*`、`ui/mascot/` 也在 alpha-ratchet 扫描外——web 接 Rive 时新增 `mascot.*` 而 Android 无对应**机器门抓不到**，三端同步（§14）此处只能人工守或扩 parity 表。
- **emulator 前提**：connected-emulator lane 跑 x86_64；stable 11.x 的 AAR 须含 x86_64 `.so`（README 列了 4 ABI，高置信），否则任何实例化 `RiveAnimationView` 的 instrumented test 抛 `UnsatisfiedLinkError`——集成时核 AAR。
