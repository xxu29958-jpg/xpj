# 小票夹项目工作规则

本文件是后续 Codex/开发者进入本项目时必须优先读取的项目级规则。

## 必读顺序

开始任何实现前，先阅读：

1. `docs/ENGINEERING_RULES.md`
2. `docs/ARCHITECTURE.md`
3. `docs/PROJECT_STRUCTURE.md`
4. `docs/API.md`
5. `docs/SECURITY.md`
6. `docs/REFERENCES.md`
7. 与当前任务相关的 `docs/DECISIONS/*.md`

后端实现相关任务再阅读：

1. `docs/BACKEND_RULES.md`

Android 实现相关任务再阅读：

1. `docs/ANDROID_RULES.md`

第二版、OCR、分类、重复检测、缩略图、图片清理相关任务再阅读：

1. `docs/V2_ROADMAP.md`

## 阶段约束

默认先按用户当前明确阶段推进。

如果用户只要求后端，只实现 `backend/`。

如果用户明确要求完整软件、Android App、全部版本或端到端闭环，可以进入 `backend/`、`android/` 和 `docs/`。进入 Android 前仍需遵守 `docs/ENGINEERING_RULES.md` 的 Android 分层规则。

## 规则速查

以下规则的完整详情均在 `docs/ENGINEERING_RULES.md` 中，此处仅列索引：

- 后端技术栈 → §1
- 不可回退决定 → §23
- 后端分层（routes → services → models） → §3-4
- Android 分层（Screen → ViewModel → Repository → DAO） → §12
- 代码质量与依赖管理 → §2
- Windows UTF-8 → §9
