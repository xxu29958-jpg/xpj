# 小票夹文档导览

按"读者意图"分到 5 个子目录 + 2 个常驻目录。先选你今天的角色，再翻对应入口。

| 你想 | 进哪个目录 |
|---|---|
| 开始写代码前必读规则 | [rules/](rules/) |
| 理解系统怎么搭、API 长什么样 | [architecture/](architecture/) |
| 部署 / 备份 / 排障 / 升级 | [runbook/](runbook/) |
| 看产品路线、设计参考、未来能力 | [roadmap/](roadmap/) |
| 查当前版本（v1.2）的设计资产和收口报告 | [current/](current/) |
| 看某个具体技术选型为什么这么定 | [DECISIONS/](DECISIONS/)（人读索引见 [DECISIONS/README.md](DECISIONS/README.md)，机器状态/关系查询见 [adr-registry.json](current/adr-registry.json)）|
| 拿设计稿原图与色板预览 | [design_reference/](design_reference/) |

## 渐进阅读（与 [AGENTS.md](../AGENTS.md) 一致）

先恢复用户当前 Goal、Owner 裁决和任务专属合同，再按责任选读项目文档；不要为机械合规而每次通读整本
ARCHITECTURE / API。先用目录、版本 / 最近变更和搜索定位，随后完整读取当前责任实际依赖的章节：

1. [rules/ENGINEERING_RULES.md](rules/ENGINEERING_RULES.md) — 定位后完整读取当前责任章节及其明确引用；后端 / Android 补充见 §14
2. [architecture/](architecture/) — 当前任务涉及的架构、结构、API 或安全章节
3. [rules/REFERENCES.md](rules/REFERENCES.md) — 当前机制对应的官方资料和依赖来源
4. [DECISIONS/](DECISIONS/) — 用 [adr-registry.json](current/adr-registry.json) 和索引定位；选中后完整读取并复核真实代码
5. [rules/ADR_CONTRACT_STANDARD.md](rules/ADR_CONTRACT_STANDARD.md) — 仅在修改 ADR / 治理工具时完整读取

只有任务横跨整份文档、修改文档本身或上位合同明确要求时才整本读取。历史文档与旧实现都是审计对象，
不能覆盖当前 Goal、Owner 裁决、官方语义和真实运行事实。OCR / 分类 / 重复检测 / 缩略图任务追加读取
[roadmap/V2_ROADMAP.md](roadmap/V2_ROADMAP.md) 的相关章节。

## 版本真值源

[architecture/VERSION.md](architecture/VERSION.md) 是后端 / Android 版本号的唯一权威。任何文档、CI、脚本里的版本字符串必须与这份对齐。当前 `v1.2.0`。

## 目录约定

- **rules/**：约束类。改动需要谨慎，常引用为"必读"。
- **architecture/**：契约类。改动等于改契约，要同步代码。
- **runbook/**：操作类。读者多是运维角色，步骤要可粘贴执行。
- **roadmap/**：规划类。多是规划、对照、参考；落地后逐步沉到 architecture/。
- **current/**：版本资产。每发布一个 minor 就替换；过期内容直接删除（git 历史里仍可追溯）。
- **DECISIONS/**：ADR。已接受的决策本体保留历史；schema-v2 用 front matter，legacy 正文由 hash baseline
  冻结、当前符合性由 calibration overlay 表达。方向改变写新 ADR 并声明 `amends` / `supersedes`。
- **design_reference/**：设计稿。`thumbnails/*.png` 是真值，文字说明在该目录的 README.md。

## 这次重组的范围

参见根目录 [CHANGELOG](current/CHANGELOG.md)。简言之：把 v0.9 之前的扁平 70+ 文档按上面五分类重排；删除已过时的 DESIGN_TARGETS.md、ANDROID_AUTO_CAPTURE.md 与 v0.4/v0.5/v0.8 历史收口快照（git 历史里仍可追溯）；把 ROLLBACK.md 从"v0.3 一次性迁移"重写为通用版本回滚 runbook。
