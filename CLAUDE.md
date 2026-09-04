# 小票夹 — Claude Code 入口

Claude Code 与 Codex 使用同一份常驻施工合同：

@AGENTS.md

不要在本文件复制规则，也不要默认导入整本 `docs/rules/ENGINEERING_RULES.md`。按照 `AGENTS.md` 的责任路由，只在当前任务确实涉及对应范围时读取相关章节、架构文档和 ADR。

## 当前任务短交接（本机工作态）

`.claude/HANDOFF.md` 用于跨 session / 跨 AI 续接；不存在或状态为 `IDLE` 表示没有在途交接。它不是仓库规则或历史权威，不应提交到版本库。

@.claude/HANDOFF.md
