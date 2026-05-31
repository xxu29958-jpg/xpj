# 小票夹项目工作规则

本文件是后续 Codex、Claude Code（经根目录 `CLAUDE.md` 的 `@AGENTS.md` import）、开发者进入本项目时必须优先读取的项目级规则。

## 必读顺序

**第 0 步——先看任务交接**：`.claude/HANDOFF.md` 是跨 session / 跨 AI（codex ↔ claude）的当前任务交接合同。用户说「继续任务」即从它的「下一步」接续；收工 / 换 AI 前更新它。本地文件（git 忽略）；不存在或状态为 IDLE 表示当前无在途任务。

开始任何实现前，先阅读：

1. `docs/rules/ENGINEERING_RULES.md`
2. `docs/architecture/ARCHITECTURE.md`
3. `docs/architecture/PROJECT_STRUCTURE.md`
4. `docs/architecture/API.md`
5. `docs/architecture/SECURITY.md`
6. `docs/rules/REFERENCES.md`
7. 与当前任务相关的 `docs/DECISIONS/*.md`

后端 / Android 任务的具体补充已合并入 `docs/rules/ENGINEERING_RULES.md` §14（项目特定补充）。

第二版、OCR、分类、重复检测、缩略图、图片清理相关任务再阅读：

1. `docs/roadmap/V2_ROADMAP.md`

## 阶段约束

默认先按用户当前明确阶段推进。

如果用户只要求后端，只实现 `backend/`。

如果用户明确要求完整软件、Android App、全部版本或端到端闭环，可以进入 `backend/`、`android/` 和 `docs/`。进入 Android 前仍需遵守 `docs/rules/ENGINEERING_RULES.md` 的 Android 分层规则。

## 规则速查

以下规则的完整详情均在 `docs/rules/ENGINEERING_RULES.md` 中，此处仅列索引：

- 裁决顺序 → §0
- 后端分层（routes → services → models / providers） → §1
- 客户端分层（Screen → ViewModel → Repository → IO） → §1
- 项目结构、命名 → §2
- 数据规范（金额、时间、id） → §3
- 错误码格式 → §4
- 安全 / 鉴权 / 构建分级 → §5
- 持久化 / 同步 / 隔离 → §6
- 依赖治理 → §9
- 测试 / 发布 / 回滚 → §11
- 小票夹项目特定（identity v0.3、OCR provider、UploadLink、Windows BOM、三端 token 同步等） → §14
