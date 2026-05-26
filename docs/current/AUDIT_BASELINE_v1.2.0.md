# v1.2.0 Release Audit Baseline

收尾时刻的 `release_audit.py` 快照。后续跑出来的差异 = 真实回归（新真问题 或 新 false-positive 类别），不是 baseline 自然漂移。

- commit: [`1487c39c`](https://github.com/zhe9898/7/commit/1487c39c) — release_audit residual cleanup ([#143](https://github.com/zhe9898/7/pull/143))
- date: 2026-05-26
- command: `python scripts/release_audit.py`（在 `backend/` 下执行）
- result: PASS — 全部 5 个 lane（ci-gap / codebase / csrf-dual-mode / route-test-matrix / service-graph）通过

## Curated counts

| Audit | Baseline | Notes |
|---|---:|---|
| A2 files >500L | 9 | 全仓 Python 文件口径；其中 `app/` 只有 `learning_service/__init__.py` (613L, v1.2 cohesive service) + `receipt_parse_merchant.py` (506L)，其余是 scripts/tests。informational only，项目内存约定（feedback_short_code_no_padding）：不为行数硬拍门槛 |
| A4 functions >=80L | 34 | 残留是 deliberately linear 事务体：`apply_csv_import_batch` happy-path、`_migrate_expenses_columns`、`accept_invitation`、`get_settings` 等。继续拆边际收益小 |
| A5 nesting >=5 | 6 | 全部在 `scripts/_audit_codebase.py`（audit 自身）+ `tests/`；`app/` clean |
| B3 routes → models/db | 64 | 全部是 false positive：`get_db` Depends 注入 + `if TYPE_CHECKING:` 块的 type-hint import；真违反 §1 的 9 routes 全清 |
| F2 broad catch | 24 | audit 已配置跳过带 `# noqa: BLE001` 的 broad catches；这 24 是其它**没**标 `BLE001` 的 broad catches（事务回滚 + raise / 后台任务 catch-all / migration error handler 等），按个例审过都合理 |
| F3 swallowed | 0 | clean — PR #143 让 audit 跳过 specific-exception fallback（如 `except ValueError: pass` 是项目惯用降级），只报 `except Exception: pass` / 裸 `except: pass` |
| G6 N+1 | 2 | `_seed.py:87` one-shot init + `_aliases.py:133` IntegrityError fallback 路径——bounded retry / 非热路径，accepted noise |
| G7 untested modules | 226/275 | 文件名 string-match 启发式；很多是 indirect-tested，需要单独治理 |

## PR 收尾对应表

release_audit cleanup batch — [PR #132](https://github.com/zhe9898/7/pull/132) 到 [PR #143](https://github.com/zhe9898/7/pull/143)。每个 finding 类别都有 PR 或 rationale 兜底：

- B3 真违反 9 routes 全清：PR-A / PR-B / PR-E / PR-F / PR-G
- G6 真 N+1 4 处全清：PR-A / PR-B / PR-C / PR-D
- A4 抽 helper：PR-H / PR-I / 本地 d257fd2 + 10bae67（待 PR #143 合并）
- A5 深嵌套：PR-J
- audit 自身降噪：PR-L + 本地 27474ee（待 PR #143 合并）

## 怎么用这个 baseline

下次跑 `release_audit.py`，对照本表数字。任意一行 ≠ baseline：

- **变小**：好事（修了一类真问题或新降噪），update baseline + 在 PR description 解释
- **变大**：要分情况：
  - 新加的代码引入真问题 → 修
  - 引入了 audit 不识别的新模式 → 评估给 audit 加规则（[scripts/_audit_codebase.py](../../backend/scripts/_audit_codebase.py)）或在本表 Notes 列加 rationale
  - 既不是真问题也不是新模式 → audit 自己 bug，去查 _audit_codebase.py

## Related

- [ADR-0036](../DECISIONS/0036-v1.1-ai-budget-provider-privacy-boundary.md) — v1.1 AI provider 隐私边界
- [ADR-0037](../DECISIONS/0037-v1.2-learning-feedback-dual-tables.md) — v1.2 learning feedback 三表
- [ADR-0038](../DECISIONS/0038-v1.3-multi-surface-sync.md) — v1.3 多端同步协议
- 项目内存约定 `feedback_short_code_no_padding` — 不为行数硬拍门槛
- 项目内存约定 `feedback_release_changelog_walk_history` — release 文档起草前先 `git log <prev-tag>..HEAD --no-merges`
