# CI 说明

仓库以 **GitHub Actions 云端 CI 为主兜底**，自托管 Gitea Actions（home-server 本机 runner）降级备用。

云端 workflow 文件：

```text
.github/workflows/ci.yml                       # 主 CI：常驻快速合同 + 按域 PostgreSQL/Desktop/Android/Windows packaging
.github/workflows/android-connected-test.yml   # path-filtered 云端模拟器 lane
.github/workflows/codeql.yml                   # GitHub CodeQL 安全扫描
.github/workflows/nvd-database.yml              # main-only Android NVD 数据库生产者
```

本地降级 workflow 文件：

```text
.gitea/workflows/windows-ci.yml          # 四个 job，白名单 push 跑
.gitea/workflows/android-connected.yml   # 模拟器 lane，只在 Android 源变更时跑（path-filtered）
```

触发条件：

- GitHub: push 到 `main`，以及 pull_request 到 `main`。PR 始终跑 Backend 快速合同；PostgreSQL、Desktop、Android、Windows packaging 只在对应路径受影响时跑。`main`、手动运行、未知路径、空 diff 或分类失败均 fail closed 到全量。
- Android NVD producer: 每日 02:17 UTC、相关生产者输入合入 `main` 或手动触发；仅生产者读取 `NVD_API_KEY`。它优先增量复用兼容的旧产物，首次或不兼容时冷启动，离线扫描通过后上传保留 3 天的不可变数据库产物。
- local-Gitea: push 到 `main`、`feat/**`、`fix/**`、`perf/**`、`refactor/**`、`codex/**`
- 默认分支完整资格：`repository_dispatch`，type 为 `qualification`

完整资格用
`gh api --method POST "repos/{owner}/{repo}/dispatches" -f event_type=qualification`
触发。GitHub 将 `repository_dispatch` 固定到默认分支当时的 commit 和 workflow，工作分支不能
自行生成 required-check 资格。`CI scope` 从实际 checkout 选择第一父提交并输出不可变 base
SHA，Backend 与 Android 棘轮只消费该输出；根提交、非默认 ref、非祖先和 `HEAD` 自比较均
fail closed。工作分支仍由 PR merge SHA 验证。连续资格验证必须等本轮 CI、CodeQL 和
Connected 全部结束并核对同一 `head_sha`，再触发下一轮，避免并发组取消前一轮。

GitHub hosted runner 并行执行，是主要合并依据。本地 Gitea runner 是单台 Windows 机器（与生产后端同机），**串行执行**——前一个 run 没结束时排队；只作为云端不可用、发布候选本机验收、或宿主特有 emulator/打包问题的降级确认。Gitea 与 runner 在 home-server 上人工启动；如果本地 push 后 run 一直排队不动，先确认它们活着。

历史：GitHub workflow 曾随 GitHub→Gitea 迁移删除。2026-06-13 起恢复 GitHub 云端 workflow，当前主路径为 `ci.yml`、`android-connected-test.yml`、`codeql.yml` 和 main-only `nvd-database.yml`；本地 `.gitea/workflows/` 保留为降级备用。pytest 覆盖率报告（`--cov=app`，只是报告、无 fail-under 门槛）仍未恢复。

## Job 清单（GitHub 主路径 + local-Gitea 降级）

### ci-scope + backend-contracts + Backend（常驻快速合同）

`ci-scope` 用精确 PR base/head 做 NUL 分隔、禁 rename 推断的路径分类，输出 `postgres / desktop / android / windows` 四个资源域、由发布策略生成的 PostgreSQL matrix 和实际 checkout SHA。路径分类只有 `ci_gap_trigger_scope.py` 一份真源；job 仅在分类器成功且明确输出 `false` 时跳过。分类器无法比较时输出全量；scope job 本身失败时不得静默跳过或汇总为绿色，必需检查直接失败。

```powershell
scripts\check_text_encoding.ps1 + check_dependency_versions.ps1 + 全部 .ps1 的 BOM/语法检查
python -m compileall app scripts tests packaging/tests
ruff check app scripts tests packaging/tests
python scripts\check_api_contract.py
python scripts\release_audit.py        # 自动发现全部 _audit_*.py lane
pip-audit --strict（OSV 库）
```

`Backend contracts` 没有数据库，不跑业务 pytest / smoke；它保持每个 PR 都可达，并有 12 分钟硬上限，负责验证分类器接线、CI 聚合器、PostgreSQL job 拓扑、CI gap、API 与静态合同。既有分支保护名 `Backend` 汇总 scope、静态合同和按需 Windows packaging，并逐项核对实际 checkout SHA。Windows 域为 `true` 时必须成功且 SHA 一致；明确为 `false` 时才接受无 SHA 的 `skipped`。

### windows-packaging（按域）

仅 Windows 宿主、安装器、冻结构建依赖、发布版本、migration 或 Desktop 产物合同变化时运行 packaging tests、PS5.1/PS7 preflight、冻结 Backend/Desktop 构建、Inno 编译和上传后字节回验。普通 Backend `app/` 与测试变更只进入 PostgreSQL/快速合同；`requirements-dev.txt`、测试 PostgreSQL 跨运行时合同和 Windows runtime-tree helper 同时触发其真实消费者。共享的 `windows-release-config.json` 同时触发 PostgreSQL、Desktop 与 Windows 三个消费者域。`main`、手动运行和未知影响仍 fail closed 到包含 Windows 产物的全量。整个 provenance 链必须位于同一 scoped job，不能把上传后字节回验拆成另一份权威；GitHub 重型发布 job 的硬上限为 20 分钟，是否达标仍以 exact-head 实际耗时为准。

安装器测试数量由 `backend/packaging/audit/test_count_baseline.txt` 归 Windows 域维护；增加 packaging 测试不会反向触发 Android/Desktop。Windows 句柄绑定删除和临时 PostgreSQL 生命周期行为也在该 lane 真正执行，不以 Linux 上的 skip 代替证明。

### backend-postgres（按域全量测试）

GitHub 是发布验收与合并权威；Gitea 是离线镜像和自检后备，Gitea-only 失败不阻断 GitHub 合并。后端运行时、测试、迁移相关路径变化或全量 fallback 时，ordinary、`real_db`、smoke + recovery 三个独立 job 各自使用隔离的 PostgreSQL service container；三个责任域保持显式 job。当前只支持安装器钉住的单一 PostgreSQL major，matrix 从发布配置和固定 service image 动态生成；未来扩展多个 major 前，必须先为每个 major 提供独立固定镜像。稳定汇总检查 `Backend (PostgreSQL)` 必须核对三个结果和实际 checkout SHA。

ordinary lane 执行完整测试树中所有未标记 `real_db` 的用例，并为每个 xdist worker 动态创建独立数据库、文件根和租约；`real_db` lane 串行执行显式标记的真实提交、跨连接、DDL 与 migration 测试；smoke + recovery lane 执行真实 `pg_dump` / restore drill。分类权威只有测试源码 marker，禁止维护 nodeid、文件名、目录或字符串名单；新增、移动、重命名、参数化及删除测试不需要同步第二份“分类清单”。

后端测试数量只在 `backend/audit/test_count_baseline.txt` 维护。它是严格对账信号，不是覆盖率或分类权威：新增测试与源码同 commit 提高基线；base ratchet 同时阻止一个 PR 删除测试并下调自己的可编辑基线。测试整合必须先保留或补上独立风险证明，不能为了变绿改小数字。总数仍不能证明语义质量，因为“删除高价值测试、补同数量低价值参数化用例”也能骗过它，所以机器计数与代码审计缺一不可。该文件与测试源码同属 PostgreSQL 域；`codebase_audit_gate.py` 只保留政策，不再因正常增测把 PR 放大成全端构建。

GitHub PostgreSQL service container 按共享 matrix 的受支持 major 启动，并接收本次运行派生的密码；建库前还读取真实 `server_version_num`，同时验证 matrix major 与发布策略的完整版本区间。runner 侧只有 passfile 生成 step 接收原始密码，后续测试进程只消费短命 passfile并要求 SCRAM-SHA-256；密码不得进入 URL、命令参数或日志。local-Gitea 的 Windows 测试簇也从 `initdb --pwfile` 直接建立 SCRAM，受保护凭据文件是簇生命周期内的权威，测试、smoke 和备份恢复只消费受保护 passfile。每个 GitHub PostgreSQL job 的目标门槛是 runner elapsed time 不超过 12 分钟；最终以 exact-head 云端记录为准，`timeout-minutes` 不是达标证据。

测试 PG 的数据库名、marker、密钥文件名、固定 `gitea/local` 端口和宿主禁用端口只从 `test_postgres_contract.json` 读取。GitHub 按官方 service-container 合同把容器内 PostgreSQL 端口映射到 runner 随机空闲端口，并从 `job.services.postgres.ports` 动态注入；它不是第三个固定宿主端口 profile。Windows 临时 PG 只接受 OS 临时目录下以 `xpj_pg_` 开头的目录；start/stop 共同消费宿主与数据目录双所有权标记、端口级跨会话 lease、精确进程代际和句柄绑定删除。新簇只从同一发布策略允许的本机 binary 中选择，并用 `postgres --version` 校验完整版本区间；marker 记录实际 binary root，因此安装新大版本后，旧测试簇仍由原版本安全停止，不会交给新 major 误接管。Gitea 使用稳定的端口级 DataDir；前一 run 异常退出后，新 run 在持有同一 lease 时清理已证明归属的遗留实例再重建。无标记目录、文件、junction/reparse point 或无法证明归属的 PostgreSQL 进程均 fail closed。

### desktop-manager（按域）

`desktop/`：compileall + ruff + pytest。

### android-unit（按域）

```powershell
# 删最新 Room schema JSON + 强制 KSP 重生（漂移检测前置，--rerun-tasks 防 FROM-CACHE 跳过）
gradlew :app:kspGrayDebugKotlin --rerun-tasks
gradlew :app:compileGrayDebugKotlin :app:testGrayDebugUnitTest
# 校验重生的 schema 与 committed 文件一致（entity 改了没提交 schema diff 就红）
git status --porcelain android/app/schemas
gradlew :app:assertAndroidTestCountEqualsBaseline   # ADR-0038 测试计数门
gradlew :app:lintGrayDebug
gradlew :app:detektGrayDebug :app:detektGrayDebugUnitTest   # Kotlin 复杂度门（六阈值；type-resolving——plain :app:detekt 会静默跳过 LongParameterList；存量冻结 per-variant baseline）
gradlew :app:assembleGrayDebug
gradlew :app:assembleInternalDebug
gradlew --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease   # R8 minify + shrinkResources；PR 仅 Android/CI 相关变更跑，main/manual 必跑
# apksigner 校验两个 debug APK = 仓库级稳定 debug 证书（指纹钉自 android/config/debug/README.md）
```

GitHub 云端 Android 资格链按责任并行：`Android fast` 跑编译、单测、计数、lint、detekt 与 Room schema；`Android APK debug` / `release` 分别构建 Gray/Internal；`Android SCA` 使用 main 分支生产的可信 NVD 产物做离线扫描。四条 lane 均为 15 分钟上限，稳定的 `Android` 聚合检查验证结果与同一资格 SHA。local-Gitea Android job 使用仓库本地 `.toolchains\android-sdk`，有 40 分钟上限；它是降级备用，不是 GitHub 合并阻断项。

### android-connected（模拟器，path-filtered）

云端 connected workflow `.github/workflows/android-connected-test.yml` 只在 Android 源（`android/app/src/**`、gradle 配置、CI 入口脚本）或该 workflow 自身变更时触发，backend/docs push 不付模拟器成本。单个 API 36 emulator job 执行完整 instrumentation suite；test APK 排除只服务发布安装的 ProfileInstaller，避免其 Startup provider 在独立测试进程中形成绿色崩溃和逐项超时。emulator action 只执行一条 timeout 包裹的 Gradle 命令：3 分钟 boot 上限、14 分钟 Gradle watchdog、20 分钟 action 上限和 30 分钟 job cap 逐层给环境准备、验证与失败报告留出余量；connected Gradle task 自身仍以 10 分钟为内层上限。

Gradle 在测试前后各采集一次 `ApplicationExitInfo`，并在 action teardown 前保留 APK，避免 UTP 卸载清除退出历史；每次 adb 取证各有 30 秒上限。`connectedGrayDebugAndroidTest` 在同一任务内读取 AGP 生成的 connected JUnit XML、对账 instrumentation 基线，再从实际 APK manifest 动态读取目标包、测试包及其进程名，要求本轮至少产生一条目标进程退出记录，并拒绝 Java crash、native crash、ANR 和初始化失败；logcat 只作为诊断附件。证据缺失、畸形或被卸载清空时一律 fail closed。JVM 计数同样读取 Gradle `Test` 任务的真实 JUnit XML；`android/audit/test_count_baseline.txt` 分别锁住两条 lane，源码注解、注释、字符串和文件布局不再充当执行事实。

local-Gitea 的 `.gitea/workflows/android-connected.yml` 是同一门禁的本机降级版，用 runner 主机用户级 Android Studio SDK 的 AVD `ticketbox_api36_host`（headless，`-no-window`），单 step try/finally 内：清残留 → 起模拟器 → 等 boot（5 分钟上限）→ `ANDROID_SERIAL` 钉住本 lane 的设备 → `connectedGrayDebugAndroidTest` → 两段式拆除（`adb emu kill` + launcher PID taskkill 兜底）。它保持单设备串行执行，不作为 GitHub 合并阻断项。

`release_audit.py` 的 ci-gap lane 静态扫两套 workflow，钉住 Gradle、后端、Desktop 与安装器数据流。scoped job 只有在完整 checkout、唯一分类输出、fail-closed 条件和无软失败均成立时才被计入；任意普通 `if` 不能冒充覆盖。安装器哈希、上传、下载和回验仍作为同一 Windows job 的有序原子链检查。

## 安全边界

CI 不需要真实 Token。`backend/.env`、`backend/data/`、`backend/uploads/`、`backend/backups/`、`android/app/build/` 由 `.gitignore` 排除，不进仓库。GitHub 与 local-Gitea 的临时 PG 都强制 SCRAM；Windows 侧凭据和 passfile 只存在于受保护的临时测试簇生命周期内。

## 常见失败点

- run 一直排队：Gitea / runner 没起，先把它们启动。
- pip-audit SSL EOF：网络 flake，rerun 整个 run 即绿。
- Android SCA 找不到新鲜可信 NVD 产物：不要反复重跑 PR；在 main 上手动运行 `Android NVD Database` workflow，等 producer 成功上传产物后再重跑 PR。摘要不符、产物损坏、真实 CVE 或离线扫描失败都必须保持红灯，不能旁路。
- `assertAndroidTestCountEqualsBaseline` 红：要么分支基于旧 main（baseline 随 main 演进），rebase 到当前 main；要么本 diff 增删了 Android JVM / instrumentation 测试而没同步 bump `android/audit/test_count_baseline.txt`。
- `backend_pytest_count` / `installer_pytest_count` 红：分别更新 `backend/audit/test_count_baseline.txt` / `backend/packaging/audit/test_count_baseline.txt`；不要改 gate 代码里的数字。
- `WaitDelay expired before I/O complete`：临时 PG 没拆干净；teardown 先要求 `pg_ctl` 成功且已固定的进程句柄全部退出，超时后只处理同一已验证进程代际，绝不按二进制路径批量杀，详见 workflow 内注释。
- `.ps1` 检查失败：确认仍是 UTF-8 with BOM、无 PS 5.1 语法错误。

## CI 是合并底线

任何后端、Android、release 脚本变更都不能绕过当前 GitHub PR / main-push 云端 job 绿灯；Android 源变更还会在 PR 或 main push 上触发 connected lane。local-Gitea CI 是降级备用和本机验收，不再作为主路径排队瓶颈。任何账本隔离、上传、UI 改造或 release 脚本变更，都不能绕过既有后端和 Android 验证。
