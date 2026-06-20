# CI 工具坑（Gradle daemon / trigger / GitHub Actions / flake / gitea API）

> 把反复踩中的 CI 工具坑固化成一篇查得到的 runbook。**做这几类活前先读**：跑本地重型 Gradle 验证（`--stop` / classes.jar 锁）、起或改 CI lane、判一条 CI run 是真红还是良性、合 PR（`gh pr merge` / gitea `merge`）、连发合并后核验、三端同步。
>
> 本仓 CI 真相：**主 CI 在 GitHub Actions（origin `xxu29958-jpg/xpj`，云端）**，三条 workflow `.github/workflows/{ci,android-connected-test,codeql}.yml`；自托管 **gitea（`localhost:3000/codex/xiaopiaojia`）是次要兜底**，两条 workflow `.gitea/workflows/{windows-ci,android-connected}.yml`，常没起。两套 workflow 的分支 trigger / job 结构刻意对齐（`_audit_ci_gap.py` 联合扫 `.github` + `.gitea`），但**运行环境、merge API、日志拿法不同**——别把 gitea 的事实套到 GitHub 上，反之亦然。

---

## 坑 1：本地 `gradlew --stop` 杀死 CI 在飞的 Android job（gitea 自托管 runner）

**症状（怎么踩中）**：本地为清 `classes.jar` / transforms 锁跑了 `gradlew --stop`，同一秒 gitea 的 android job 死在 `Gradle build daemon has been stopped: stop command received`，job 红。被红的内容与已绿 run 逐字节相同——纯无辜。

**根因**：gitea `act_runner` 与开发环境在**同一台 Windows 机、同一用户**，共享 `~/.gradle`（daemon 注册表 + caches）。CI android job 即便 `--no-daemon`，Gradle 9 在 JVM 设置不匹配时仍 fork 一个 "single-use Daemon" 并登记进共享注册表。本地 `--stop` 把 CI 那个一起停了。（注：GitHub Actions 用 hosted runner，**不共享本机 daemon**，此坑只对 gitea 自托管 runner 成立。）

**正确做法**：
- gitea 有 android job running / queued 时，本地**禁止 `gradlew --stop`**。遇锁先查 gitea 队列，等它过去再 stop，或直接重试别的命令。
- CI 日志见 `daemon has been stopped: stop command received` = 此碰撞，**不是代码问题**：按全文搜定性后等下一个 main head run 重验即可，**不修、不 rerun**。
- 本地重型 gradle 验证尽量避开 CI android job 时窗（runner 串行，android job 通常在 run 后段）。

**铁律**：gitea android job 在飞时，本地不碰 `gradlew --stop`。

---

## 坑 2：CI trigger 是 push（无强制 `pull_request`）+ 分支白名单，`chore/**`/`docs/**` 不触发

**症状**：清理/重构类 PR 用了 `chore/ui-xxx` 分支名，push 后 CI 没跑（无该分支 run、commit checks=0、纯建 PR 也不触发），误以为卡住。

**根因**：分支 pattern 是白名单，`chore/**` / `docs/**` / `test/**` **不在其中**。两套 workflow 的 push 分支白名单：

```
# GitHub .github/workflows/ci.yml        →  main, feat/**, fix/**, perf/**, refactor/**, codex/**
# GitHub android-connected-test.yml      →  同上 + paths 过滤(android 源/gradle 配置/workflow 自身)
# GitHub codeql.yml                       →  push: main, codex/**  +  schedule cron "37 3 * * 1"
# gitea  .gitea/workflows/windows-ci.yml →  main, feat/**, fix/**, perf/**, refactor/**   (无 codex/**)
# gitea  android-connected.yml            →  同 windows-ci + paths 过滤
```

注意三处差异：① **GitHub 三条 workflow 都额外带 `pull_request: branches: [main]` trigger**（gitea 两条**只有 push + workflow_dispatch，无 pull_request**）；② GitHub 分支白名单含 `codex/**`，gitea 不含；③ CodeQL 的 push trigger **只有 `main` + `codex/**`**（feat/fix/perf/refactor 分支的 push 不单独触发 CodeQL，靠它们的 PR `pull_request` 事件触发）。

**正确做法**：
- 起清理 / 重构 PR 分支优先 `refactor/**`（在所有白名单内），别用 `chore/**`。
- 发现 PR 无 CI run，先核分支名是否在 trigger pattern；在 gitea 上对 `chore/` 分支补救用 workflow_dispatch：

```
# gitea 手动触发(workflow_dispatch)
POST /api/v1/repos/codex/xiaopiaojia/actions/workflows/windows-ci.yml/dispatches
body: { "ref": "<分支名>" }
```

- 改 Android 源时，**会同时触发两条 run**（regular android-unit + path-filtered connected/emulator lane），单 runner 串行总排队变长——判「该 PR 全绿」前先按改动面想清楚应有几条 run，别把「connected 还没跑」当卡住。

**铁律**：分支名不在 trigger 白名单 = CI 静默不跑；清理活走 `refactor/**`。

---

## 坑 3：GitHub 每 commit 双 run + concurrency 取消旧 run 的「fail」是良性

**症状**：`gh pr checks N` 里看到一个 Android job 显示 `fail`，常是跑 ~40min 后在 OWASP 步报 `##[error]The operation was canceled.`，误判真红。

**根因**：GitHub 上 push 事件 + pull_request 事件各触发一遍 ci.yml → **每 commit 两套 Backend/Android/Desktop job**。workflow 的 `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }` 会**取消被超越的那个 run**；被取消的 job 在 `gh pr checks` 显示 `fail` = **良性，非真红**。authoritative run = 最新 / 未被取消 / 跑完 pass 的那个。本仓**无强制 branch protection**，所以 `mergeStateStatus=UNSTABLE` + `mergeable=MERGEABLE` 即可合。

**正确做法**：
- 盯 CI 用**后台轮询脚本**（bash `run_in_background`，`gh pr checks N` 轮到 pending==0 再数 fail），别死等、别信 `gh pr checks --watch`。
- 红 triage：先 `gh run view --job <id>` 看哪步 ✗，再 `gh run view --job <id> --log` 全日志搜 `^e: `(detekt finding)/ `FAILED` / `failures="[1-9]` / `error:` 定位文件:行。别被被取消 run 的「fail」唬住，也别把 workflow 里 `echo "::error::..."` 的守卫定义文本当真错。
- GitHub 实质门（authoritative，须真绿）：`Backend` / `Backend (PostgreSQL)` / `Desktop manager` / `Android` / CodeQL 四条 `Analyze (actions|javascript-typescript|python|java-kotlin)`。emulator `Connected (emulator)` 与 OWASP flake **非 required、不挡合**。

**铁律**：被 concurrency 取消的旧 run 的 `fail` 是噪声；只认最新 head 那条 run。

---

## 坑 4：`gh pr merge N --auto` 在本仓 = 立即合，不等绿

**症状**：想「等 CI 绿了自动合」用了 `--auto`，结果 checks 全 pending 时 PR **当即被 merge**（2026-06-20 实测）。

**根因**：`--auto` 依赖 **required status checks** 来「等」；本仓**无强制 branch protection / 无 required check**，没有可等的对象 → PR 一 `MERGEABLE` 就立刻合。

**正确做法**：
- 要「等绿再合」**别用 `--auto`**：后台 `gh pr checks N --watch` settle 后，亲自核实实质门（坑 3 那串）真绿，再手动：

```
gh pr merge N --merge --delete-branch
```

- `--auto` 只在「确信代码已验过、只差形式跑完」时当快捷方式用（如干净 rebase replay）。
- merge 需用户显式「合并」授权。

**铁律**：本仓 `--auto` ≠ 等绿；想等绿就 watch settle 后手动 `gh pr merge`。

---

## 坑 5：连发合并后历史 commit 的 main run ratchet 假红

**症状**：几分钟内先后 merge 两个 PR，第一个 merge commit 的 main 校验 run 红在 test-count ratchet「跌」（如 base 585 > current 581），其 commit 又不是当前 main HEAD。

**根因**：push-CI 下 test-count UP-ratchet 的 base 取 fetch 时的**动态** `refs/heads/main`，checkout 的却是历史 `GITHUB_SHA`。第二个 PR 已把 main 推进 → base baseline 比 checkout 的 current 新 → 误判「测试消失」FAIL。`ci.yml` 用 `fetch-depth: 0` 正是为让 ratchet 的 `git show <base_ref>:...` 够得着 base baseline。

**正确做法**：
- 连发 merge 后**只盯最新 head 的那条 main run**（其 checkout==base，才是有效校验）。
- 识别假红特征：红 run 的 commit ≠ 当前 main HEAD + 失败是 ratchet 方向倒挂（base > current，差值恰为后续 PR 的增量）。**这种红不修不 rerun**（rerun 仍红：checkout/base 都不变）。
- 另一种同源：你的 feature 分支 off **旧 main**，base slice 合并后 baseline 升，Android job 红在 `Android verification (count baseline + lint + detekt)` 且 ratchet「跌」→ **rebase onto 新 main**，不是真测试少了。

**铁律**：历史 commit 的 ratchet 倒挂红是时序假象；只信最新 head run。

---

## 坑 6：OWASP / NVD dependency-check 步在 NVD 网关超时上 flake

**症状**：Android job 红在 `Dependency vulnerability scan (OWASP dependency-check)` 步（`./gradlew dependencyCheckAnalyze`），日志 `NvdApiException: Status Code 520/524`，NVD 服务抖动时一天复发数次。

**根因**：该步下载 NVD 漏洞库，撞 NVD API 网关超时即 flake。它是 Android job 的**最后一个大步**——能跑到 OWASP，说明 compile / unit test / lint / detekt×2 / count baseline / debug+release APK 全已过。

**正确做法**：
- **OWASP 红、其余全绿 = 凭实质门合**（同 [坑 3/坑 4] 的实质门判据）；OWASP 非 required、不挡合。
- **别提议加 `continue-on-error`**：跳过机制已内建——步带 `if: ${{ env.NVD_API_KEY != '' }}`，配对一个「scan skipped」warning 步处理空 key。要强制跳过得删 `NVD_API_KEY` repo secret，**但该值 write-only、删了只有用户能重加**，先确认。
- 缓存修复已落地（main@`9d627e02`）：`android/build.gradle.kts` `nvd.validForHours=24` + `data.directory = Gradle user home`；`ci.yml` android job 用 `actions/cache@v4` 缓存 `~/.gradle/dependency-check-data`（UTC-day key + `restore-keys`）。**warm cache（<24h）让插件整个 SKIP NVD 调用** → rerun / 同日 run 零 NVD I/O。缓存按 GitHub Actions scope 规则：**main 的 cache 才能惠及其它 PR**，需一次成功完整下载 bootstrap。NVD 真宕机时缓存也救不了，得等 NVD 恢复一次下载。
- 改 `build.gradle.kts` 的 dependencyCheck 配置块，本地用 `./gradlew help` 验（求值 block 不跑 OWASP）。

**铁律**：OWASP 520/524 是 NVD 抖动 flake，real-gates 全绿即合；别加 `continue-on-error`，跳过分支已内建。

---

## 坑 7：pip-audit SSL EOF 是瞬时网络 flake

**症状**：backend job 的 `Dependency vulnerability scan (pip-audit)` 步红，日志撞 `api.osv.dev` / `pypi.org` SSL EOF。

**根因**：`pip_audit --strict --vulnerability-service osv` 走公网 OSV / PyPI，瞬时网络 flake。

**正确做法**：改动零依赖 + 其余 job 绿即判噪声。GitHub 上靠 push/PR 重跑（或 concurrency 自然新 run）；gitea 上 `POST .../actions/runs/{id}/rerun`（重跑整 run）即绿。

**铁律**：pip-audit 的 SSL EOF + 没动依赖 = 网络噪声，rerun 即绿。

---

## 坑 8：gitea API 操作事实集（查 run / merge / rerun / push / 起服务）

**症状**：用 GitHub 的肌肉记忆操作 gitea——匿名查 run 拿 404、merge 用 PUT 拿 405、job 日志 API 404、非交互 merge 报 NonInteractive 假错——以为坏了。

**根因**：gitea（`localhost:3000/codex/xiaopiaojia`，admin=codex，token 指针在 `D:\selfhost\gitea-win\admin-credentials.txt`）的 API 语义与 GitHub 不同。

**正确做法**：
- **查 CI**：`GET /api/v1/repos/codex/xiaopiaojia/actions/tasks?limit=N` **必带 token**（匿名 404）；返回项 `id`=task id，`run_number`=run id。**job 日志 API 全 404，但日志在磁盘可直读**：`D:\selfhost\gitea-win\data\actions_log\codex\xiaopiaojia\{2位hex}\{task_id}.log.zst`（zstd 解压；`zstandard` wheel 在 `E:\projects\xiaopiaojia\.claude\tmp_pylibs`，脚本 `.claude\tmp_read_zst.py`）。CI 红先拿磁盘日志全文搜 `FAILED|failures="[1-9]` 定性。
- **merge PR**：`POST /api/v1/.../pulls/{n}/merge` body `{"Do":"merge"}`——**是 POST 不是 PUT**（PUT 返 405，Allow: GET/POST/DELETE）。非交互 PS 下可能报「NonInteractive mode」**假错但实际已 merged**——权威信号=随后 GET 的 `merged=True` + `merge_commit_sha`，别因假错重试。另一种 405：连发 merge 时上一个刚动过 main，下一个的 mergeability 在重算窗口内，POST 返 405 且 `merged=False`——GET 确认 `mergeable=True && merged=False` 后重试一次即成（间隔几秒发可避开）。需用户显式「合并」授权。
- **重跑 flake**：`POST .../actions/runs/{id}/rerun`（带 token，重跑**整 run**；job 级 rerun 与 run cancel 本版 404）。
- **单 runner 串行**：只有一个 act_runner，re-push 同分支**不会**自动取消旧 run，stale run 白占队列——分支没 merge 尽量一次推完整。
- **push**：cached cred 会失效，用显式 basic auth：`git -c http.extraheader="AUTHORIZATION: basic <base64(codex:codex1234)>" push local-gitea <branch>`。
- **agent 起不了 gitea / runner**：非交互起 `gitea.exe` 被 Windows Application Control 拦；只能等用户在交互终端跑 `D:\selfhost\gitea-win\scripts\Start-Gitea-CI.ps1`，`/api/healthz` 返「Local Gitea CI」后再 push / 查 CI。

**铁律**：gitea 查 run 必带 token、merge 用 POST `{"Do":"merge"}`、merged 字段是权威信号、单 runner 串行别乱 re-push。

---

## 坑 9：三端同步顺序（merge 后）

**症状**：merge 后忘了同步镜像，或对 `origin`（死 GitHub）乱 fetch。

**根因**：本仓有多个远端，权威性不同：`origin` = GitHub `xxu29958-jpg/xpj`（云端主 CI，merge 在此发生）；`gitee` = cloud mirror `xygr/small-ticket-holder`；`local-gitea`（:3000）= 次要兜底，服务常没起。

**正确做法**（GitHub merge 后）：

```
git fetch origin
git merge --ff-only origin/main      # 本地 main 跟上
git push gitee main                  # 推 cloud mirror
```

- `local-gitea` 没起就跳过（origin + gitee 权威，非阻塞）；起来后补 `git merge --ff-only local-gitea/main`。
- `gh pr merge --delete-branch` 会顺手删本地+远端 feature 分支并切回 main，后续 `git branch -D` 报 not found 是良性。
- 每步结果用 `git rev-parse` 验证，**别靠 `$?` 链**（PS 下 git stderr 会污染 `$?`，ff 静默跳过）。

**铁律**：merge 后 fetch origin → 本地 main `--ff-only` → push gitee；local-gitea 没起就跳，别 fetch 死 origin。

---

## 记忆勘误

逐站点核验 workflow 文件后，以下记忆陈述与真实文件不符，文中已按真实事实修正：

1. **`project_github_actions_ci_behavior.md` 把分支 trigger 指向 gitea**，并称「GitHub Actions 的 trigger 见 `project_ci_branch_trigger` 那条（讲 gitea）」。实际 `.github/workflows/ci.yml` 自带 push 白名单 **`main, feat/**, fix/**, perf/**, refactor/**, codex/**`**（比 gitea 多 `codex/**`）**且三条 GitHub workflow 都带 `pull_request: branches: [main]`**。gitea 两条 workflow 才是「无 pull_request、无 codex/**」。两者不可混用。

2. **`project_ci_branch_trigger.md` 整篇以 `.gitea/workflows/windows-ci.yml` 为「the」trigger 真相**。该描述对 gitea 准确，但本仓**主 CI 是 GitHub Actions**——GitHub 侧有 `pull_request` trigger（纯建 PR 会触发，与该记忆「没 pull_request trigger，纯建 PR 不触发」相反）。文档已分两套列清。

3. **backend-postgres 运行环境**：`project_github_actions_ci_behavior.md` / HANDOFF 未区分。真实情况——**GitHub `ci.yml` 的 `Backend (PostgreSQL)` 跑在 `ubuntu-latest` + PG17 service 容器（:5432，tmpfs）**；**gitea `windows-ci.yml` 的同名 job 跑在 windows-latest + initdb 起的 ephemeral 集群（:5433）**。HANDOFF 提到的 `:5433` 仅属 gitea 侧，GitHub 侧是 service 容器 :5432。

4. **CodeQL trigger**：记忆只笼统说「Analyze×4」。真实 `codeql.yml` 的 **push 只触发 `main` + `codex/**`**，外加 `schedule: cron "37 3 * * 1"`；feat/fix 等分支靠 PR 的 `pull_request` 事件触发 CodeQL。4 条 Analyze job 名核实无误：`actions` / `javascript-typescript` / `python` / `java-kotlin`。

5. **emulator AVD/路径**：gitea `android-connected.yml` 用 runner 宿主用户级 AVD `ticketbox_api36_host`（与记忆一致）；但 **GitHub `android-connected-test.yml` 用 `reactivecircus/android-emulator-runner@v2` 动态起 pixel_6 / api-36，无 `ticketbox_api36_host`**。HANDOFF 把宿主 AVD 当成两端通用，实为 gitea 专属。

（其余记忆陈述——Gradle daemon 共享、OWASP `if NVD_API_KEY != ''` 跳过分支 + `actions/cache@v4` + `validForHours=24`、pip-audit OSV flake、gitea merge=POST / 日志在磁盘 / 单 runner 串行、三端同步顺序——均与真实文件一致。）
