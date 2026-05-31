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

## 当前任务交接（易变，git 忽略）

`.claude/HANDOFF.md` 是跨 session / 跨 AI（codex ↔ claude）的**任务交接合同**真相源。用户说
「继续任务」时，从它的「下一步」接续；收工 / 换 AI 前更新它。codex 经 `AGENTS.md` 必读、claude
经下面的 `@import` 自动加载（`@import` 不展开 markdown 文本路径，所以这里必须显式写）。

它在 `.claude/`（已被 `.git/info/exclude` 忽略）：纯本地工作态，不进历史、不进 worktree、不跨
机器——**不是项目规则，别当成两份漂移清理掉**。文件不存在或状态为 IDLE 即表示当前无在途任务。

@.claude/HANDOFF.md
