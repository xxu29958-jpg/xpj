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

| 维度 | 默认门槛 | 工具 |
|---|---|---|
| 函数行数 | 60 | detekt `LongMethod` |
| 类行数 | 600 | detekt `LargeClass` |
| 函数参数 | 5（函数）/ 6（构造） | detekt `LongParameterList` |
| 圈复杂度 | 14 | detekt `CyclomaticComplexMethod` |
| 嵌套深度 | 4 | detekt `NestedBlockDepth` |
| 文件函数数 | 11 | detekt `TooManyFunctions` |

配置在 `android/detekt.yml`。

## Pull Request

- 理想 ≤50 行，sweet spot 200-400 行（Cisco 研究 70-90% 缺陷检出率）
- >400 行评审质量显著下降；>1000 行检出率从 87% 跌到 28%
- 一 PR 一议题，不混合无关改动

## Git Commit

[Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/)：

```
<type>[scope]: <description>
```

`type ∈ { feat, fix, docs, refactor, test, chore, build, ci, perf, style }`。BREAKING 加 `!` 或 footer `BREAKING CHANGE: ...`。

## Branch Protection（main）

- 必须 CI status check 通过
- ≥1 reviewer approve
- Require branches up-to-date before merging

## 参考来源

- [Ruff configuration handbook](https://pydevtools.com/handbook/how-to/how-to-configure-recommended-ruff-defaults/)
- [Detekt Complexity Rule Set](https://detekt.dev/docs/rules/complexity/)
- [McCabe cyclomatic complexity (Wikipedia)](https://en.wikipedia.org/wiki/Cyclomatic_complexity)
- [Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/)
- [GitHub branch protection docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [PR size impact (Graphite)](https://graphite.com/blog/the-ideal-pr-is-50-lines-long)
