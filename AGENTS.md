# 小票夹项目工作规则

本文件是后续 Codex、Claude Code（经根目录 `CLAUDE.md` 的 `@AGENTS.md` import）、开发者进入本项目时必须优先读取的项目级规则。

## 控制面与渐进阅读

**第 0 步——先恢复当前任务控制面**：用户当前 Goal、Owner 裁决和任务专属合同优先于本文件。
如任务声明了主合同、当前裁决、短交接或目标模式合同，按其自带顺序完整读取；发生上下文压缩后，
在继续修改前重新完整读取这些控制面合同。`.claude/HANDOFF.md` 是跨 session / 跨 AI
（codex ↔ claude）的短交接入口；用户说「继续任务」即从它的「下一步」接续，收工 / 换 AI 前更新它；
不存在或状态为 IDLE 表示无在途交接。

项目文档采用渐进发现，不再要求每个任务机械通读整本架构和 API 文档：

1. 先用目录和搜索定位 `docs/rules/ENGINEERING_RULES.md` 中与任务责任相关的规则；选中规则后完整读取其
   所属责任章节及明确引用的约束，后端 / Android 任务必须覆盖 §14 的相关项目补充。
2. 先检查 `docs/architecture/ARCHITECTURE.md`、`PROJECT_STRUCTURE.md`、`API.md`、`SECURITY.md`
   和 `docs/rules/REFERENCES.md` 的目录、版本 / 最近变更与相关章节，再完整读取当前责任实际依赖的章节和链接资料。
3. 用 `docs/current/adr-registry.json`、`docs/DECISIONS/README.md` 和代码搜索定位相关 Decision；
   一旦选中某个 Decision，完整读取其正文，并以真实代码、运行事实和当前上位合同复核。
4. 只有任务横跨整份文档的责任面、修改该文档本身或上位合同明确要求时，才整本读取。
5. 修改 ADR / 治理工具时，再完整读取 `docs/rules/ADR_CONTRACT_STANDARD.md`。
6. 第二版、OCR、分类、重复检测、缩略图、图片清理相关任务，再读取
   `docs/roadmap/V2_ROADMAP.md` 的相关责任章节。

历史实现、旧文档、旧 ADR、旧测试和旧工作流都是审计对象，不因存在时间长或写在项目级文件中就自动成为
当前 authority；它们必须接受用户当前 Goal、Owner 裁决、任务合同、官方语义和真实运行事实的共同裁决。
若发现缺失语义，先补责任拓扑：阻碍当前退出门的缺口在当前纵向 PR 内实现并验证；不阻碍者不提前并入
当前 PR。仅当当前任务合同指定外部 issue 或禁止本地台账时，才按该合同路由登记。

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
