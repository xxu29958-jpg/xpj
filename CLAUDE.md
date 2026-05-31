# 小票夹 — Claude Code 入口

Claude Code 读 `CLAUDE.md`、Codex 读 `AGENTS.md`。为了两个 agent 读**同一套**项目规则、
不分叉，本文件用 `@import` 引入规则真相源。

注意：Claude Code 的 `@import` **不会**自动展开被 import 文件里用普通 markdown 文本列出的
路径——所以除了入口 `AGENTS.md`，规则主体 `ENGINEERING_RULES.md` 也在此显式 import。其余
`docs/architecture/*`、`docs/DECISIONS/*` 按 `AGENTS.md` 的「必读顺序」在相关任务时主动读
（全部 import 会撑爆每个 session 的 context）。

改规则请改 `AGENTS.md` / `docs/`，**不要**在这里复制规则，避免两份漂移。

@AGENTS.md
@docs/rules/ENGINEERING_RULES.md
