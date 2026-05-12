# Branch / PR Baseline

日期：2026-05-12

本文记录当前 GitHub PR、远端分支、tag 和本地 `main` 的可靠基线，避免后续被 squash merge、过期 PR 和历史分支误导。

## 1. 当前主线

- 当前工作分支：`main`
- 本地工作区：干净
- `main` / `origin/main`：`2660c945c89dbe445dd6581f7fa0a4b77ff8c48b`
- commit subject：`docs: add post-beta capability roadmap`
- tree：`d75e7edf5a9c626a15fc0d9d2e9b1657e20f0e43`

判断是否“内容一致”时优先看 tree / diff；不要只看 Git commit ancestry。项目历史里有 GitHub squash merge 和 cherry-pick，很多分支会显示 `diverged`，但内容可能已经被主线吸收。

## 2. Release tags

| Tag | Tag object | Peeled commit | 说明 |
| --- | --- | --- | --- |
| `v0.2.0-rc1` | `b33705f7ea36aff9546a121466493860791f96d5` | `188e7928e8568e0dcf96d1d972cecf4fbeb57980` | v0.2 RC 发布点，已是 `main` 祖先 |
| `v0.4-alpha3-rc1` | `dbce24aec8606f2bfa01b1fbef42052fa46fb205` | `aa541ce0f335732410ee3efc6b56fc59733ae07c` | alpha3 RC1 发布点，已是 `main` 祖先 |
| `v0.4-beta1` | `4aa390a11460f16e0177ba22084b34b7477499dc` | `cd6aaa5ad6cf61493fa5cd564aef5f0622a06a12` | beta1 发布点，已是当前 `main` 祖先 |

`v0.4-beta1` 是 tag，不是工作分支。当前 post-beta `main` 已在该 tag 之后多两个提交：member/viewer 角色调整 hardening 与 post-beta roadmap。

## 3. 现存远端分支

| 分支 | PR | 状态 | 与 `main` 关系 | 结论 |
| --- | --- | --- | --- | --- |
| `main` | - | baseline | `2660c94` | 当前可靠主线 |
| `v0.4-beta1-family-ledger-foundation` | #17 merged | tree 与 `main` 相同，commit graph 分叉 | 内容已与 `main` 一致；保留为 beta1 工作历史候选 |
| `v0.4-alpha2-tri-surface-ui` | #12 closed obsolete | diverged，branch-only 4 | 过期 PR；能力已被后续主线吸收，不要合并 |
| `v0.4-alpha3-smart-ledger-engine` | #13 closed obsolete | diverged，branch-only 9 | 过期 PR；能力已被 #14-#17 和当前主线吸收，不要合并 |
| `codex/split-large-files` | #7 merged | diverged，branch-only 4 | PR 已合，但分支后续还有未进 `main` 的提交；删前需单独确认 |
| `codex/docs-reality-sync` | #3 merged | behind，ahead 0 | 已进主线，可标历史 |
| `codex/gray-release-tenant-ux` | #2 merged | behind，ahead 0 | 已进主线，可标历史 |
| `codex/readme-gray-baseline` | #4 merged | behind，ahead 0 | 已进主线，可标历史 |
| `codex/sqlite-migration-backup-audit` | 无 PR | behind，ahead 0 | 已被 `main` 包含，可标历史 |
| `copilot/explain-repository-structure` | 无 PR | behind，ahead 0 | 已被 `main` 包含，可标历史 |
| `v0.2-rc` | #5 merged | behind，ahead 0 | 已进主线，可标历史 |

## 4. 已合并但远端分支已不存在

这些 PR 已合并，GitHub heads 已无对应远端分支。本地若还看到 `origin/*`，属于 stale refs，网络恢复后可通过 prune 清理。

| PR | Head branch | 合并方式 | 结论 |
| --- | --- | --- | --- |
| #6 | `fix/v0.3-identity-stabilize` | 2-parent merge | 无远端可删 |
| #8 | `v0.3.2-selfuse-stabilization` | squash-style | 无远端可删 |
| #9 | `v0.3-rc1-preflight` | squash-style | 无远端可删 |
| #10 | `v0.3.3-productization` | squash-style | 无远端可删 |
| #11 | `v0.4-alpha1-multi-ledger-foundation` | squash-style | 无远端可删 |
| #14 | `v0.4-alpha3-slice2-reports-dq-arch` | squash-style | 无远端可删 |
| #15 | `v0.4-alpha3-slice3-android-review-workflow` | squash-style | 无远端可删 |
| #16 | `v0.4-alpha4-mobile-architecture-rc` | squash-style | 无远端可删 |

## 5. 过期 PR 判定

### PR #12 `v0.4-alpha2-tri-surface-ui`

结论：已关闭为 obsolete，不要 merge，不要 cherry-pick。

当前 `main` 已包含并扩展 #12 的目标能力：

- Tri-Surface 文档：`docs/TRI_SURFACE_INFORMATION_ARCHITECTURE.md`
- alpha2 合同文档：`docs/V0_4_ALPHA2_TRI_SURFACE_UI.md`
- `/web` 桌面账本流和拆分路由：`backend/app/routes/web_*.py`
- `/owner/ledgers` 与 `/web` 入口：`backend/app/routes/owner_ledgers.py`
- Android Needs Review：`android/app/src/main/java/com/ticketbox/ui/screens/pending/`

直接合并 #12 会把当前拆分后的 `/web`、Android review workflow、家庭账本能力拉回旧形态或制造冲突。

### PR #13 `v0.4-alpha3-smart-ledger-engine`

结论：已关闭为 obsolete，不要 merge，不要 cherry-pick。

当前 `main` 已包含并扩展 #13 的目标能力：

- Rules preview/apply：`backend/app/routes/rules.py`
- Recurring candidates：`backend/app/routes/insights.py`、`backend/app/services/insights_service.py`
- `/web/rules`、`/web/stats`、`/web/data-quality`：`backend/app/routes/web_rules.py`、`web_stats.py`、`web_data_quality.py`
- Data Quality：`backend/app/services/data_quality_service.py`
- Android Reports 和 recurring 卡片：`android/app/src/main/java/com/ticketbox/ui/screens/stats/`

PR #13 的后续能力已经由 #14、#15、#16、#17 和当前 post-beta main 吸收。直接合并 #13 同样会回退当前代码形态。

## 6. v0.4-beta1 分支判定

- `v0.4-beta1-family-ledger-foundation` 当前 SHA：`d5b3e26bcc2dc12b936d1fe84e1e0736008e6bdd`
- tree：`d75e7edf5a9c626a15fc0d9d2e9b1657e20f0e43`
- 与 `main` tree 相同，`git diff --stat main v0.4-beta1-family-ledger-foundation` 无输出。
- 与 `main` commit history 不同：`main` 含 #17 squash commit 与两个 post-beta commits；该分支保留 beta1 切片提交历史，再追加两个同内容提交。

后续判断：

- 内容基线看 `main`。
- 发布说明需要引用 beta1 切片历史时，可看 `v0.4-beta1-family-ledger-foundation`。
- 不要为了“Git 显示 diverged”再把该分支 merge 到 `main`。

## 7. 清理建议

安全可标历史 / 可删除远端分支：

- `codex/docs-reality-sync`
- `codex/gray-release-tenant-ux`
- `codex/readme-gray-baseline`
- `codex/sqlite-migration-backup-audit`
- `copilot/explain-repository-structure`
- `v0.2-rc`

不要直接删除 / 需要先处理：

- `v0.4-alpha2-tri-surface-ui`：PR #12 已关闭为 obsolete；删分支前确认不需要保留历史分支名。
- `v0.4-alpha3-smart-ledger-engine`：PR #13 已关闭为 obsolete；删分支前确认不需要保留历史分支名。
- `codex/split-large-files`：PR #7 已合，但当前分支还有 4 个 branch-only commits；需确认这些 commit 是否已经另路合入或确实废弃。
- `v0.4-beta1-family-ledger-foundation`：内容等同 `main`，但可能仍有发布/回溯价值；删前确认没有依赖分支名的流程。

## 8. Git 网络说明

当前环境里普通 HTTPS Git 访问 `github.com:443` 不稳定或不可用；`gh api` 可用，SSH 端口可达。此前同步 `main` 与 `v0.4-beta1-family-ledger-foundation` 时使用了一次临时 repo deploy key 走 SSH push，并已删除该 key。

本文不记录任何 token、私钥、临时 key 路径或本机敏感路径。

网络恢复后建议运行：

```powershell
git fetch --tags --prune origin
git status --short --branch
git branch -r --merged origin/main
git branch -r --no-merged origin/main
```

再复核本文中的 branch SHA、tag 和 PR 状态。

## 9. 验证来源

本基线来自下列只读检查：

- `git status --short --branch`
- `git rev-parse main origin/main`
- `git for-each-ref refs/tags`
- `git diff --stat main <branch>`
- `git rev-list --left-right --count main...<branch>`
- `git merge-base --is-ancestor`
- `git rev-parse <ref>^{tree}`
- `gh pr list --state all`
- `gh api repos/zhe9898/7/branches`
- `gh api repos/zhe9898/7/compare/main...<branch>`
