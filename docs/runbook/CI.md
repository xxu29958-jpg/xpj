# CI 说明

仓库使用自托管 Gitea Actions（home-server 本机 runner），两个 workflow 文件：

```text
.gitea/workflows/windows-ci.yml          # 四个 job，所有 push 都跑
.gitea/workflows/android-connected.yml   # 模拟器 lane，只在 Android 源变更时跑（path-filtered）
```

触发条件：

- push 到 `main`、`feat/**`、`fix/**`、`perf/**`、`refactor/**`
- 手动 `workflow_dispatch`
- **没有 pull_request 触发**：建 PR 本身不跑 CI，推分支才跑；分支命名必须落在上面的 glob 里，否则一条 lane 都不会触发。

runner 是单台 Windows 机器（与生产后端同机），**串行执行**——前一个 run 没结束时排队，勿无谓 re-push。Gitea 与 runner 在 home-server 上人工启动；如果 push 后 run 一直排队不动，先确认它们活着。

历史：GitHub 时代的 `.github/workflows/`（`ci.yml`、`android-connected-test.yml`、`codeql.yml`）随 GitHub→Gitea 迁移死亡，已删除；内容可考 git 历史。随迁移一并消失的 instrumented 模拟器 lane 已于 2026-06-11 在宿主 AVD 上复活（见 android-connected 一节）；pytest 覆盖率报告（`--cov=app`，只是报告、无 fail-under 门槛）仍未恢复。

## Job 清单（windows-ci 四个 + android-connected 一个）

### backend-full（静态检查）

```powershell
scripts\check_text_encoding.ps1 + check_dependency_versions.ps1 + 全部 .ps1 的 BOM/语法检查
python -m compileall app scripts tests
ruff check app scripts tests
python scripts\check_api_contract.py
python scripts\release_audit.py        # 自动发现全部 _audit_*.py lane
pip-audit --strict（OSV 库）
```

PG-only 之后该 job 没有数据库，不跑 pytest / smoke——全量测试都在 backend-postgres。

### backend-postgres（全量测试）

用 runner 本机的 PostgreSQL 安装经 `initdb` 起一次性临时实例（`:5433`，与生产集群 `:5432` 隔离），在**单个 step 的 try/finally 内**完成：起库 → `smoke_test.py` 端到端 → `postgres_backup_drill.py` 备份恢复演练（用真后端备份代码 dump smoke 灌好的库 → 校验归档 → 恢复进 `xpj_restore` → 行数对账；§6「没演练的备份=没备份」）→ 全量 pytest（`xpj_test` 库，与 smoke 的 `xpj_smoke` 分库）→ 按 postmaster PID 定向拆库。teardown 写在 finally 是硬要求，否则 runner 的 post-step I/O drain 会报 `WaitDelay expired`。

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
gradlew :app:assembleGrayRelease :app:assembleInternalRelease   # R8 minify + shrinkResources 保温
# apksigner 校验两个 debug APK = 仓库级稳定 debug 证书（指纹钉自 android/config/debug/README.md）
```

Android SDK 用仓库本地 `.toolchains\android-sdk`（workflow 写 `local.properties` 指过去）。job 有 `timeout-minutes: 40` 上限（单 runner 串行，一次 wedge 不能阻塞全部 CI）。

### android-connected（模拟器，path-filtered）

第二个 workflow 文件 `.gitea/workflows/android-connected.yml`：只在 Android 源（`android/app/src/**`、gradle 配置）或该 workflow 自身变更时触发，backend/docs push 不付模拟器成本。用 runner 主机用户级 Android Studio SDK 的 AVD `ticketbox_api36_host`（headless，`-no-window`），单 step try/finally 内：清残留 → 起模拟器 → 等 boot（5 分钟上限）→ `ANDROID_SERIAL` 钉住本 lane 的设备 → `connectedGrayDebugAndroidTest` → 两段式拆除（`adb emu kill` + launcher PID taskkill 兜底）。`timeout-minutes: 30`。这是 GitHub 时代 `android-connected-test.yml` 的 Gitea 复活版。

`release_audit.py` 的 ci-gap lane 静态扫 `.gitea/workflows/*.yml`（两个文件都扫），钉住 11 个 gradle task（上述清单 + ksp regen + detekt 两变体 + 两个 release assemble + connected）与 10 个 backend 调用（release_audit / 全量 pytest / smoke / 备份恢复演练 / API contract / backend ruff / backend compileall，外加 desktop 三钉：compileall / ruff / pytest——此前整个 desktop job 被删都不会被发现），防止 lane 静默丢失。**改 CI lane 必须同步 `_audit_ci_gap.py` 的 REQUIRED 清单**，否则该 lane 立刻红。

## 安全边界

CI 不需要真实 Token。`backend/.env`、`backend/data/`、`backend/uploads/`、`backend/backups/`、`android/app/build/` 由 `.gitignore` 排除，不进仓库。临时 PG 实例 trust 认证但只 listen localhost，每 run 用完即弃。

## 常见失败点

- run 一直排队：Gitea / runner 没起，先把它们启动。
- pip-audit SSL EOF：网络 flake，rerun 整个 run 即绿。
- `assertAndroidTestCountEqualsBaseline` 红：要么分支基于旧 main（baseline 随 main 演进），rebase 到当前 main；要么本 diff 增删了 Android 测试而没同步 bump `android/audit/test_count_baseline.txt`。
- `WaitDelay expired before I/O complete`：临时 PG 没拆干净，teardown 必须按 postmaster PID 杀进程树（绝不按二进制路径杀——生产 PG 同机共享二进制），详见 workflow 内注释。
- `.ps1` 检查失败：确认仍是 UTF-8 with BOM、无 PS 5.1 语法错误。

## CI 是合并底线

任何后端、Android、release 脚本变更都不能绕过当前 push 触发的全部 job 绿灯（windows-ci 四 job；Android 源变更还会触发 android-connected，按改动面数 run 再判全绿）；merge 前必须等当前 push 的 run 全绿。任何账本隔离、上传、UI 改造或 release 脚本变更，都不能绕过既有后端和 Android 验证。
