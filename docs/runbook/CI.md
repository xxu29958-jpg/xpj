# CI 说明

仓库以 **GitHub Actions 云端 CI 为主兜底**，自托管 Gitea Actions（home-server 本机 runner）降级备用。

云端 workflow 文件：

```text
.github/workflows/ci.yml                       # 主 CI：backend/static、PostgreSQL、desktop、Android unit/build、path-gated release APK
.github/workflows/android-connected-test.yml   # path-filtered 云端模拟器 lane
.github/workflows/codeql.yml                   # GitHub CodeQL 安全扫描
```

本地降级 workflow 文件：

```text
.gitea/workflows/windows-ci.yml          # 四个 job，白名单 push 跑
.gitea/workflows/android-connected.yml   # 模拟器 lane，只在 Android 源变更时跑（path-filtered）
```

触发条件：

- GitHub: push 到 `main`，以及 pull_request 到 `main`。工作分支不再单独触发云端重型 push CI，避免同一 PR head 被 push + pull_request 跑两遍；PR 打开或更新时仍完整跑云端主路径。
- local-Gitea: push 到 `main`、`feat/**`、`fix/**`、`perf/**`、`refactor/**`、`codex/**`
- 手动 `workflow_dispatch`

GitHub hosted runner 并行执行，是主要合并依据。本地 Gitea runner 是单台 Windows 机器（与生产后端同机），**串行执行**——前一个 run 没结束时排队；只作为云端不可用、发布候选本机验收、或宿主特有 emulator/打包问题的降级确认。Gitea 与 runner 在 home-server 上人工启动；如果本地 push 后 run 一直排队不动，先确认它们活着。

历史：GitHub workflow 曾随 GitHub→Gitea 迁移删除。2026-06-13 起恢复 GitHub 云端 workflow，当前主路径为 `ci.yml`、`android-connected-test.yml` 和 `codeql.yml`；本地 `.gitea/workflows/` 保留为降级备用。pytest 覆盖率报告（`--cov=app`，只是报告、无 fail-under 门槛）仍未恢复。

## Job 清单（GitHub 主路径 + local-Gitea 降级）

### backend-full（静态检查）

```powershell
scripts\check_text_encoding.ps1 + check_dependency_versions.ps1 + 全部 .ps1 的 BOM/语法检查
python -m compileall app scripts tests
ruff check app scripts tests
python scripts\run_packaging_tests.py  # Windows 安装/生命周期合同，独立 collection 对账
python scripts\check_api_contract.py
python scripts\release_audit.py        # 自动发现全部 _audit_*.py lane
pip-audit --strict（OSV 库）
```

该 job 没有业务测试数据库；后端业务 pytest / smoke 在 backend-postgres，
Windows packaging 合同则在这里使用宿主 PostgreSQL 运行时完成限时验证。

Packaging 测试以 `packaging_resource(...)` 为唯一调度真源：`hermetic` 项可由
3 个 xdist worker 并行，`windows_fs`、`windows_host`、`postgres_cluster`、
`inno_toolchain` 各自在自己的 `loadgroup` 内串行。runner 仍只执行一次完整
`packaging/tests` 根；独立预收集必须证明 parallel + serial 恰好覆盖全集，
worker 全部干净退出后仅 controller 可以写完成回执。测试名、文件名前缀和
nodeid 子串不参与分类。

### backend-postgres（全量测试）

GitHub 主路径使用 PG17 service container。local-Gitea 要求 Gitea Runner `>=2.0.0`，使用宿主临时目录和专用 `:5433`，执行顺序均为：起库 → smoke → 备份恢复 → parallel → stateful。

- Windows 启停由 lifecycle mutex 串行化；runner、pytest controller/worker、smoke、备份恢复各持 consumer lease。
- `postgres.exe` 由 Job Object 原子创建；只继承显式 stdin/stdout/stderr 句柄，并持有创建时返回的真实进程句柄到 commit。在线身份和数据库准备完成后才提交生命周期，父进程死亡或超时会终止未提交进程树。
- 数据目录先收紧为当前 runner / SYSTEM / Administrators 权威 ACL，并以目录句柄绑定到启动完成；路径替换、宽松继承 ACL 和 reparse tree 均 fail closed。
- parallel lane 的每个 xdist worker 使用独立数据库；migration、恢复、角色、schema 与集群状态测试显式进入串行 lane。
- marker 是分类真源。每条 managed lane 先在无 lane 环境中独立 collection，再把节点数与 SHA-256 摘要交给真实执行对账；collection 前少收、`--collect-only`、`-k/-m` 过滤或 handshake 伪绿都会失败。
- 审计从精确 base 保护 backend 全集、parallel、`real_db`、`stateful_serial`，以及 packaging 全集、parallel、serial 三份节点集合；旧 parallel 测试只允许提升到更保守的串行资源，已登记串行风险不得静默降级。
- local-Gitea lane 为 25 分钟，job 为 50 分钟，并保留 4 分钟 `always()` 清理。覆盖 `XPJ_TEST_DATABASE_URL` 时必须带 `owned-marker` 或 `ephemeral-service` 集群权威，并用实时 `system_identifier` 对账。

### desktop-manager

`desktop/`：compileall + ruff + pytest。

### android-unit

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
gradlew --max-workers=2 :app:assembleGrayRelease :app:assembleInternalRelease   # GitHub 与 local-Gitea；PR 仅 Android/CI 相关变更跑
# apksigner 校验两个 debug APK = 仓库级稳定 debug 证书（指纹钉自 android/config/debug/README.md）
```

GitHub 云端 Android job 使用 hosted runner 的 Android SDK，并按需安装 `platforms;android-36` / `build-tools;36.0.0`。local-Gitea Android job 使用仓库本地 `.toolchains\android-sdk`（workflow 写 `local.properties` 指过去）。云端 Android job 有 `timeout-minutes: 45` 上限；local-Gitea Android job 有 `timeout-minutes: 40` 上限（本地单 runner 串行，一次 wedge 不能阻塞全部本地队列）。

### android-connected（模拟器，path-filtered）

云端 connected workflow `.github/workflows/android-connected-test.yml` 只在 Android 源（`android/app/src/**`、gradle 配置）或该 workflow 自身变更时触发，backend/docs push 不付模拟器成本。local-Gitea 的 `.gitea/workflows/android-connected.yml` 是同一门禁的本机降级版，用 runner 主机用户级 Android Studio SDK 的 AVD `ticketbox_api36_host`（headless，`-no-window`），单 step try/finally 内：清残留 → 起模拟器 → 等 boot（5 分钟上限）→ `ANDROID_SERIAL` 钉住本 lane 的设备 → `connectedGrayDebugAndroidTest` → 两段式拆除（`adb emu kill` + launcher PID taskkill 兜底）。`timeout-minutes: 30`。

`release_audit.py` 的 ci-gap lane 静态扫 `.github/workflows/*.yml` 和 `.gitea/workflows/*.yml`，钉住 11 个 gradle task 和 15 个 backend/desktop/installer 调用，其中 PostgreSQL 全量必须同时包含 parallel 与 stateful 两条 lane；任一 lane 被删、过滤或吞错都会失败。它还钉住 GitHub Android release APK 必须同一次 Gradle 调用构建 gray/internal 两个 release 变体、不得插入 `gradlew --stop`，且 PR release APK 必须按 Android/CI 相关路径 gate。**改 CI lane 必须同步 `_audit_ci_gap.py` 的 REQUIRED 清单 / policy pins**，否则该 lane 立刻红。

## 安全边界

CI 不需要真实 Token。`backend/.env`、`backend/data/`、`backend/uploads/`、`backend/backups/`、`android/app/build/` 由 `.gitignore` 排除，不进仓库。临时 PostgreSQL 使用 SCRAM-SHA-256；受保护的凭据文件是唯一耐久真源，`initdb` bootstrap 文件和 libpq passfile 只作为短命派生物，用后销毁。

## 常见失败点

- run 一直排队：Gitea / runner 没起，先把它们启动。
- pip-audit SSL EOF：网络 flake，rerun 整个 run 即绿。
- OWASP dependency-check NVD 超时：`ci.yml` 先跑 `dependencyCheckUpdate`，只有这个独立 NVD 更新阶段超时才降级为 warning，并删除半成品缓存；`dependencyCheckAnalyze -PdependencyCheckAutoUpdate=false` 离线扫描阶段超时或失败仍按真实 CVE、腐坏缓存或未知 scanner fatal 处理。
- `assertAndroidTestCountEqualsBaseline` 红：要么分支基于旧 main（baseline 随 main 演进），rebase 到当前 main；要么本 diff 增删了 Android 测试而没同步 bump `android/audit/test_count_baseline.txt`。
- 临时 PG 未清理：确认 lane 的 `finally` 与 `always()` backstop 均执行；只允许共享 stop 脚本在完整身份验证后调用 `pg_ctl`，绝不 `taskkill` 或按二进制路径杀进程。
- `.ps1` 检查失败：确认仍是 UTF-8 with BOM、无 PS 5.1 语法错误。

## CI 是合并底线

任何后端、Android、release 脚本变更都不能绕过当前 GitHub PR / main-push 云端 job 绿灯；Android 源变更还会在 PR 或 main push 上触发 connected lane。local-Gitea CI 是降级备用和本机验收，不再作为主路径排队瓶颈。任何账本隔离、上传、UI 改造或 release 脚本变更，都不能绕过既有后端和 Android 验证。
