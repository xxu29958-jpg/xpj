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

单测源集通过 `android/detekt-tests.yml` 后置覆盖：`@Test` 场景不计入函数数量，
线性测试正文不受函数行数限制，fixture 参数只计必填项。辅助函数仍检查数量与长度；
所有测试仍检查圈复杂度、嵌套和类大小。不得为容纳独立场景而拆散合同断言。
生产源集继续使用上表全部门槛，测试断言和既有 baseline 不变。

**机器守护（2026-06 接线）**：detekt **2.0.0-alpha.3**（plugin id `dev.detekt`，
Apache-2.0，版本进 `android/gradle/libs.versions.toml`）。**预发布版本是 owner
显式拍板的例外**（2026-06-12「内嵌的去更新掉」）：理由 = 2.0 内嵌 Kotlin 与本项目
2.3.21 完全一致，消除 1.23 稳定线「内嵌 Kotlin 2.0 编译器读不了项目 2.3 metadata」
（detekt#8865）的结构性债；暴露面窄（仅六条 complexity 规则、开发期工具不进产品）；
回收条件 = **2.0 stable 发布即升正式版**（按 DEPENDENCIES.md 升级流程）。CI 跑
**type-resolving 变体任务 `:app:detektGrayDebug` + `:app:detektGrayDebugUnitTest`**
（main + 单测源集），不是 plain `:app:detekt`——2.x 的 `LongParameterList` 只在
full analysis 下运行，plain 会**静默跳过它**（实验实证：plain 下阈值压 0 仍零命中），
勿换回。配置 `android/detekt.yml` **只激活六条**（`buildUponDefaultConfig=false`，
2.0 schema 的 `allowed*` 属性族，style/naming 等规则集显式关闭——未经拍板不混入
门槛）；接线时存量违规冻结在 per-variant baseline（`detekt-baseline-grayDebug.xml`
232 条 + `detekt-baseline-grayDebugUnitTest.xml` 45 条，大头 Compose 长函数/参数表），
新代码与被改代码必须达标。`_audit_ci_gap.py` 钉两个 task（gradle 钉 9→11）。
已知 alpha 毛边：分析 classpath 缺 AGP 生成的 `BuildConfig`（35 条 unresolved
警告）——六条规则全是语法级计数，报告精度不受影响。历史阈值超标按职责拆分收口
（实证：`ExpenseEditViewModel` 曾膨到 815 行，靠手动 region 拆分回 ~470——正是
接线前无机器守护的代价）；baseline 条目是冻结的债，不是许可。Android lane 其余
机器门：`lintGrayDebug`、`assertAndroidTestCountEqualsBaseline`（Gradle 实际
JUnit XML 结果、零 skipped 与双 lane baseline ratchet）、Room schema 漂移门、
R8 release 编译、apksigner 指纹钉。

## 全仓工程地图（CI）

`Backend contracts` 的 release audit 必须包含 `_audit_repository_weight.py`。同一次 Git base/head 测量写入 CI Summary 和 `repository-codebase-weight` JSON artifact，不另维护一份数字 baseline。开发时按需查看当前 exact SHA 的报告，从模块/语言进入目录、文件、函数热点；文件内容改变但 LOC 不变也会列入变更清单。历史数字不能替当前版本背书。

- Production、Test、Tooling 分开；migrations 单列且纳入 Production；可选 Public edge Worker 运行源码也属于 Production，其部署配置属于 Tooling。
- LOC 是物理源码行数，并提供 code/comment-only/blank 组成。每个文件只有一个模块、角色和主语言；HTML 内嵌 JS 的函数分析不重复增加 LOC。常用活动配置计入工具规模；文档、图片/字体/二进制、lockfile、generated/vendor/build output、Room schema JSON 和 analyzer baseline XML 不计 LOC。baseline XML 仍作为债务元数据读取。
- 总 LOC 只看趋势；硬门比较大文件 `>500/>800/>1000` 数量、实际 Ruff C901 数量/超额、Android 已登记 Detekt 债务与既有规则、源代码新 suppression，以及各语言/模块/角色的函数复杂度超额和长函数数量。门禁本身也受约束，不得增债后抬高 baseline。
- 函数导航：Lizard 的 Python/Kotlin/Java/JS/TS（含 HTML JS）CCN **估计值**；PowerShell 原生 AST 的决策计数；Inno 的例程词法分支计数。后两者不冒充统一 CFG 圈复杂度；分别显示热点。新增导航指标的债务阈值为复杂度 `>15`、物理函数跨度 `>80`，不放宽已有 Ruff/Detekt 更严格的门。
- CSS/XML/声明式配置不编造函数圈复杂度；模板渲染、动态字符串/嵌入代码、Inno 预处理与嵌套例程的语义不在这些估计的证明范围。分析器版本、覆盖边界与具体文件/行号随报告提供。数字不能自动证明架构健康、旧 writer 已退役或产品已完成。

日常使用云端报告。需要定向复算时，在已有开发依赖、Git 和 PowerShell 的环境使用明确提交：

```powershell
python backend/scripts/_audit_repository_weight.py --base BASE_SHA --head HEAD_SHA --json weight.json
```

脚本只读提交中的源码，不执行被测代码，也不计本机 dirty/untracked 文件。无法完成分析时退出 2；债务回归退出 1；测量范围内没有回归退出 0。报告的健康判定不取代原生编译、测试、审查或最终 RC 验收。

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

main 合并不依赖平台 Branch Protection 作为唯一强制（历史上的自托管 gitea main 也有意不配
branch protection，API 实查零条目）：单管理员项目里，平台级强制审批与
[ENGINEERING_RULES §13](ENGINEERING_RULES.md)「强制多人 code review = 当前阶段不做」冲突。
纪律由工作流执行：

- 代码 / 配置一律走 `codex/**` 或 `fix/** feat/** perf/** refactor/**` 工作分支 + PR；
  GitHub PR 云端主路径全绿（Android 源变更再加 connected lane）才有资格合并，local-Gitea
  作为降级备用。
- **merge 必须由用户显式授权**（GitHub 网页、`gh` 或 API；local-Gitea 仅降级备用），AI 不自行合并默认分支。
- 纯文档改动可直推 main（2026-05-22 授权），推后仍跑 CI 校验。
- RC 发包另有 commit/CI 绑定硬门禁（`accept_gray_release.ps1` 的
  `Assert-ReleaseProvenance`，见 `docs/runbook/RELEASE_PACKAGING.md` §9）。
- merge 后三端同步：GitHub origin → 本地 main → gitee；local-Gitea 启动后再补降级面同步。

## 参考来源

- [Ruff configuration handbook](https://pydevtools.com/handbook/how-to/how-to-configure-recommended-ruff-defaults/)
- [Detekt Complexity Rule Set](https://detekt.dev/docs/rules/complexity/)（Kotlin 表数值出处）
- [detekt#8865](https://github.com/detekt/detekt/issues/8865)（1.23.x 对 Kotlin 2.3 metadata 不兼容——plain 模式不受影响的依据）
- [McCabe cyclomatic complexity (Wikipedia)](https://en.wikipedia.org/wiki/Cyclomatic_complexity)
- [Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/)
