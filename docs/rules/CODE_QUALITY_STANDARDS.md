# 代码质量门槛

项目采纳的业界规范门槛，按维度列出。新代码符合即可；旧代码超标按"职责拆分"原则收口（[ENGINEERING_RULES.md §3-§4](ENGINEERING_RULES.md)），不必拉清单全改。

## Python（backend）

| 维度 | 门槛 | 工具 |
|---|---|---|
| Rule sets | `E, W, F, I, N, UP, B, C4, SIM, C901` | ruff |
| 行长 | 120（E501 全局 ignore，历史长行按职责拆分收口） | ruff `line-length` |
| Target | Python 3.11 | ruff `target-version` |
| 圈复杂度 | ≤10 推荐 / ≤15 容忍 | ruff `C901` (McCabe) |

配置在 `backend/pyproject.toml` 的 `[tool.ruff]` / `[tool.ruff.lint]` / `[tool.ruff.lint.mccabe]`。`max-complexity = 15` 卡容忍线；历史 `# noqa: C901` 屏蔽已通过职责拆分收口，新代码不得重新引入复杂度屏蔽。

## Kotlin / Android

| 维度 | 门槛 | detekt 规则 |
|---|---|---|
| 函数行数 | 60 | `LongMethod` |
| 类行数 | 600 | `LargeClass` |
| 函数参数 | 5（函数）/ 6（构造） | `LongParameterList` |
| 圈复杂度 | 14 | `CyclomaticComplexMethod` |
| 嵌套深度 | 4 | `NestedBlockDepth` |
| 文件函数数 | 11 | `TooManyFunctions` |

**机器守护（2026-06 接线）**：detekt **1.23.8**（稳定线；2.0 仍 alpha 不入主线，
Apache-2.0，版本进 `android/gradle/libs.versions.toml`）。`:app:detekt` 为 plain
纯语法分析——上表六条全部不需要 type resolution，从而绕开 detekt 1.23 内嵌
Kotlin 2.0 编译器读不了本项目 Kotlin 2.3 metadata 的已知不兼容（detekt#8865，
type-resolving 变体如 `detektMain` 不可用，勿接）。配置 `android/detekt.yml`
**只激活这六条**（`buildUponDefaultConfig=false`，style/naming 等规则集显式关闭——
未经拍板不混入门槛）；接线时存量 344 处违规（178 文件，大头 Compose 长函数/参数表）
冻结在 `android/app/detekt-baseline.xml`，新代码与被改代码必须达标。CI 在
android-unit job 的 lint 之后跑 `:app:detekt`，`_audit_ci_gap.py` 已钉（第 10 个
gradle task）。已知债务：1.23.8 用了 Gradle 10 将废 API（Gradle 9 仅警告），
detekt 2.0 stable 后按 DEPENDENCIES.md 升级流程换代。历史阈值超标按职责拆分
收口（实证：`ExpenseEditViewModel` 曾膨到 815 行，靠手动 region 拆分回 ~470——
正是接线前无机器守护的代价）；baseline 条目是冻结的债，不是许可。Android lane
其余机器门：`lintGrayDebug`、`assertAndroidTestCountEqualsBaseline`（`@Test`
计数 ratchet）、Room schema 漂移门、R8 release 编译、apksigner 指纹钉。

## Pull Request

- **一 PR 一议题**，不混合无关改动；跨面改动按 surface 拆 PR（后端 / Android / /web 的既有先例）。
- **行数不设硬门槛**：「200–400 行 sweet spot」一类数字出自对**人类评审者**缺陷检出率的
  研究（Cisco/SmartBear），本项目的评审机制是 AI 多镜头对抗审 + mutation 验证 + 全量
  套件与 audit lane 门，近期合入的 PR 普遍数百至上千行。约束 PR 尺寸的是「单一议题 +
  基线变更同 diff 声明 + 验证可复算」，不是行数。

## Git Commit

[Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/)：

```
<type>[scope]: <description>
```

`type ∈ { feat, fix, docs, refactor, test, chore, build, ci, perf, style }`。BREAKING 加 `!` 或 footer `BREAKING CHANGE: ...`。

## main 合并纪律（工作流执行，非平台 Branch Protection）

自托管 gitea 上 main **有意不配** branch protection（API 实查零条目，直推物理可行）：
单管理员本地实例，平台级强制审批与 [ENGINEERING_RULES §13](ENGINEERING_RULES.md)
「强制多人 code review = 当前阶段不做」冲突。纪律由工作流执行：

- 代码 / 配置一律走 `fix/** feat/** perf/** refactor/**` 分支 + PR；windows-ci 全
  job 绿（Android 源变更再加 connected lane）才有资格合并。
- **merge 必须由用户显式授权**（gitea 网页或 API），AI 不自行合并默认分支。
- 纯文档改动可直推 main（2026-05-22 授权），推后仍跑 CI 校验。
- RC 发包另有 commit/CI 绑定硬门禁（`accept_gray_release.ps1` 的
  `Assert-ReleaseProvenance`，见 `docs/runbook/RELEASE_PACKAGING.md` §9）。
- merge 后三端同步：local-gitea → 本地 main → gitee。

## 参考来源

- [Ruff configuration handbook](https://pydevtools.com/handbook/how-to/how-to-configure-recommended-ruff-defaults/)
- [Detekt Complexity Rule Set](https://detekt.dev/docs/rules/complexity/)（Kotlin 表数值出处）
- [detekt#8865](https://github.com/detekt/detekt/issues/8865)（1.23.x 对 Kotlin 2.3 metadata 不兼容——plain 模式不受影响的依据）
- [McCabe cyclomatic complexity (Wikipedia)](https://en.wikipedia.org/wiki/Cyclomatic_complexity)
- [Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/)
