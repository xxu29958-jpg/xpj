# 小票夹文档导览

按"读者意图"分到 5 个子目录 + 2 个常驻目录。先选你今天的角色，再翻对应入口。

| 你想 | 进哪个目录 |
|---|---|
| 开始写代码前必读规则 | [rules/](rules/) |
| 理解系统怎么搭、API 长什么样 | [architecture/](architecture/) |
| 部署 / 备份 / 排障 / 升级 | [runbook/](runbook/) |
| 看产品路线、设计参考、未来能力 | [roadmap/](roadmap/) |
| 查当前版本（v1.2）的设计资产和收口报告 | [current/](current/) |
| 看某个具体技术选型为什么这么定 | [DECISIONS/](DECISIONS/)（0001–0045，0018 已撤回，索引见 [DECISIONS/README.md](DECISIONS/README.md)）|
| 拿设计稿原图与色板预览 | [design_reference/](design_reference/) |

## 必读顺序（与 [AGENTS.md](../AGENTS.md) 一致）

1. [rules/ENGINEERING_RULES.md](rules/ENGINEERING_RULES.md) — 工程规范，单一权威
2. [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) — 完整架构
3. [architecture/PROJECT_STRUCTURE.md](architecture/PROJECT_STRUCTURE.md) — 项目结构
4. [architecture/API.md](architecture/API.md) — 后端 API 契约
5. [architecture/SECURITY.md](architecture/SECURITY.md) — 安全说明
6. [rules/REFERENCES.md](rules/REFERENCES.md) — 官方资料与依赖来源
7. 与当前任务相关的 [DECISIONS/](DECISIONS/)

后端 / Android 任务的具体补充已合并入 [rules/ENGINEERING_RULES.md](rules/ENGINEERING_RULES.md) §14。
OCR / 分类 / 重复检测 / 缩略图任务追加：[roadmap/V2_ROADMAP.md](roadmap/V2_ROADMAP.md)

## 版本真值源

[architecture/VERSION.md](architecture/VERSION.md) 是后端 / Android 版本号的唯一权威。任何文档、CI、脚本里的版本字符串必须与这份对齐。当前 `v1.2.0`。

## 目录约定

- **rules/**：约束类。改动需要谨慎，常引用为"必读"。
- **architecture/**：契约类。改动等于改契约，要同步代码。
- **runbook/**：操作类。读者多是运维角色，步骤要可粘贴执行。
- **roadmap/**：规划类。多是规划、对照、参考；落地后逐步沉到 architecture/。
- **current/**：版本资产。每发布一个 minor 就替换；过期内容直接删除（git 历史里仍可追溯）。
- **DECISIONS/**：ADR。编号一旦下发不再修改；如方向变了写新的 ADR 标 supersedes。
- **design_reference/**：设计稿。`thumbnails/*.png` 是真值，文字说明在该目录的 README.md。

## 这次重组的范围

参见根目录 [CHANGELOG](current/CHANGELOG.md)。简言之：把 v0.9 之前的扁平 70+ 文档按上面五分类重排；删除已过时的 DESIGN_TARGETS.md、ANDROID_AUTO_CAPTURE.md 与 v0.4/v0.5/v0.8 历史收口快照（git 历史里仍可追溯）；把 ROLLBACK.md 从"v0.3 一次性迁移"重写为通用版本回滚 runbook。
