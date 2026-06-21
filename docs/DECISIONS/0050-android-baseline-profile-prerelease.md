# ADR-0050: Android Baseline Profile 采用 benchmark/baselineprofile 预发布 1.5.0-alpha06

- 状态：accepted（2026-06-22，用户显式拍板「签 — 采 alpha06」；§9 预发布例外 owner 拍板）
- 关联：[[0011]]（AGP 9.2 / Gradle 9.4.1 / Kotlin 2.3 工具链）、[[0009]]（version catalog）、[[0010]]（依赖审计）、[[0016]]（性能与稳定性基线）、ENGINEERING_RULES §9 依赖治理 / §13 反扩、[rules/DEPENDENCIES.md](../rules/DEPENDENCIES.md)（默认稳定版，预发布须明确理由 + ADR）、`docs/rules/CODE_QUALITY_STANDARDS.md`「机器守护」段（detekt 2.0.0-alpha.3 = 同形预发布例外先例）；GitHub Issue #64 A1

## 背景与问题

Issue #64 A1 要给 Android 加 Baseline Profile + ProfileInstaller，优化冷启动与首屏滚动 jank（不动业务逻辑）。所需工具：Jetpack 的 `androidx.baselineprofile` Gradle 插件（生成 `baseline-prof.txt`）+ `benchmark-macro-junit4`（生成器 + 启动基准）+ 运行时 `androidx.profileinstaller`。

§9 / DEPENDENCIES.md 默认只用稳定版。但本项目工具链是 **AGP 9.2.0 / Gradle 9.4.1 / Kotlin 2.3.21**（[[0011]]），而 benchmark/baselineprofile **稳定线 1.4.1（2025-09-10）在 AGP 9.2 上直接报废**：

- 本地 spike 实证（2026-06-22）：`androidx.baselineprofile:1.4.1` 应用到 `:app` 即抛
  `Failed to apply plugin class 'BaselineProfileAppTargetPlugin' > Module ':app' is not a supported android module`。
- 根因：1.4.x 用旧 AGP 变体 API 识别模块类型，AGP 9 默认新 DSL 移除了这些 API；让插件兼容 AGP 9（免 `android.newDsl=false`）的修复**只落在 1.5.0-alpha01+，从未回灌 1.4.x**。
- 唯一能让 1.4.1 在 AGP 9 上勉强跑的办法是 `android.newDsl=false` —— 而 AGP 自身在 **10.0（2026 年中）移除该开关**，是付负利息的死路。

即：在 AGP 9.2.0 上**没有能用的稳定版**；稳定线反而是更不稳定的选择。这与 detekt 2.0.0-alpha.3 的处境同形（稳定线与项目现代工具链结构性不兼容，owner 拍板采预发布）。

## 决策

采用 **`androidx.benchmark` / `androidx.baselineprofile` 1.5.0-alpha06** 作为 A1 的构建期工具，按 owner 显式拍板的预发布例外：

- **范围限定**：仅构建期 + 测试期工具，**不进产品运行时**。生成器 + 启动基准放独立 `:macrobenchmark`（`com.android.test`）模块；`:app` 只应用 consumer 插件消费生成的 profile。`automaticGenerationDuringBuild` 默认关 → 普通 debug/release/CI 构建不起设备、零行为变化。
- **运行时依赖 `androidx.profileinstaller:1.4.1` 是稳定版**，不在本例外内（独立版本线，恰好也是 1.4.1）。
- 版本集中 pin 在 `android/gradle/libs.versions.toml`（[[0009]]）；`benchmark` 与 baselineprofile 插件共用同一版本号。
- 本地实证（2026-06-22）：alpha06 在 AGP 9.2 上插件干净 apply、gray/internal 变体与生成任务正常，**无 `maxAgpVersion` 警告**，故无需抑制 DSL。

## 依赖审计

一手来源（recon 2026-06-22，官方）：
- benchmark / baselineprofile release notes：`https://developer.android.com/jetpack/androidx/releases/benchmark`
- profileinstaller release notes：`https://developer.android.com/jetpack/androidx/releases/profileinstaller`
- AGP 9.0 release notes（移除旧变体 API）：`https://developer.android.com/build/releases/agp-9-0-0-release-notes`
- Baseline Profile 配置：`https://developer.android.com/topic/performance/baselineprofiles/configure-baselineprofiles`

审计结论：
- 稳定最新 = 1.4.1，但其支持的 AGP 上界封在 `< 9.0.0-alpha01`，对 AGP 9.2 不可用（本地 spike 已实证 apply 失败）。
- AGP-9 兼容修复在 1.5.0-alpha01（2025-12-17）；alpha05（2026-03-25）补 AGP/R8 9.1+ 处理；**alpha06（2026-05-06）为当前最新 alpha**，对 AGP 9.2 选最新。
- License = Apache-2.0；artifact 在 Google Maven（`dl.google.com`）。
- 仅用于 Android 构建/测试期，不进后端、Repository 统计口径、权限、账本隔离、DB 模型；运行时只多一个稳定 `profileinstaller`。

## 后果

- **好**：A1 可落地（生成 `baseline-prof.txt` + 冷启动前后对比）；冷启动 / 首屏 AOT 优化。
- **代价**：主线多一个预发布构建工具 + 项目首个第二 Gradle 模块（`:macrobenchmark`）；预发布须纳入 §9 升级流程 + 本 ADR 跟踪。运行时 `profileinstaller` 经 `check_dependency_versions` 审计；OWASP dep-check 按现有 root-only 扫描范围运行，`:macrobenchmark` 的 test 期依赖覆盖有限（既有行为，非本片引入）。
- **中性**：CI `android` lane 的 `assembleGrayRelease` 构建图因 consumer 插件略变（无 profile 时不失败）。

## 回收条件

benchmark/baselineprofile **1.5.0 stable 发布即升正式版**（按 DEPENDENCIES.md 升级流程，同 detekt「2.0 stable 即升正式」）。届时本例外回收，状态改 superseded/closed。

## 验证

- 稳定版死路已实证：1.4.1 在 AGP 9.2 apply 失败（见背景，本地 spike 2026-06-22）。
- alpha06 在 AGP 9.2 应用/配置/编译通过：本地 Gradle（`:macrobenchmark:tasks` + `:app:compileGrayDebugKotlin` + `:app:assembleGrayRelease`）+ CI `android` lane 验证（本地首验若受 `dl.google.com` 瞬态中断阻塞，以 CI 的 GitHub runner 为准）。
- 跑 §9 升级三件套：`check_dependency_versions.ps1` + `check_text_encoding.ps1` + Android CI lanes（compile / unit / lint / detekt / assemble）。
- `baseline-prof.txt` 生成 + 冷启动 TTID 前后对比须实机 / 模拟器跑 Macrobenchmark（A1 验收项，落 owner 设备）。
