# 0044 Android UI 字符串外置到 strings.xml（resourcing，非翻译）

- Status: accepted
- Date: 2026-06-06
- Decision makers: 项目维护者（用户 2026-06-06 下达）

## Context and Problem Statement

Android Compose 当前在 30+ 文件里直接写 `Text("中文字面量")`、placeholder、label、`contentDescription`、Toast/Snackbar，`strings.xml` 仅 `app_name`（架构债登记 #6）。ENGINEERING_RULES §14 此前明文：「不准备做翻译，也不预留部分资源化通道；要重新引入必须先开 ADR」。本 ADR 即该「先开 ADR」前置——记录把**用户可见**中文字面量外置到 `strings.xml` + `stringResource(R.string.xxx)` 的决定。

关键区分：**本决定是 string-resourcing（外置 + 集中），不是 i18n（翻译 / 第二语言）**。§13「当前阶段不做：完整 i18n」**仍然成立**——`strings.xml` 只放中文，不建 `values-xx/`，不做翻译。所以本 ADR 反转的是 §14「不预留部分资源化通道」这一条，**不**触碰 §13「完整 i18n 不做」。

## Decision Drivers

§0 #5 可维护 / 可测试（散落字面量难统一改写、难审、易重复）；用户明确请求；为未来真要做 i18n 留地基（但本轮不做翻译）；纯重构、零行为变化、可分批可回滚。

## Considered Options

- **A 维持现状**（否：债越积越大，与模板 §10「UI 字符串走资源文件」长期背离）。
- **B 完整 i18n（外置 + 翻译 + `values-xx/` + locale 切换）**（否：超出本轮范围，是 §13「完整 i18n」的 MAJOR 反转，没需求驱动）。
- **C string-resourcing-without-translation（选）**：只把用户可见中文外置到单一 `values/strings.xml`，代码走 `stringResource`，不翻译、不建第二语言文件。

## Decision Outcome

选 C。范围 = 所有 Composable 里**用户可见**的硬编码中文（`Text`、placeholder、label、`contentDescription`、Toast/Snackbar）→ `res/values/strings.xml`，代码换 `stringResource(R.string.xxx)`。

**红线（纯重构契约）**：① 功能 / UI 零变化；② `strings.xml` 只放中文，不建第二语言文件；③ 不动 `app_name`；④ 日志 / 调试用中文不动，只动用户可见的。

**命名**：`模块_位置_用途`（如 `home_total_label`、`entry_save_button`、`dialog_delete_confirm_title`），不缩写，宁长别撞车。

**执行**：按 screen/module 分 PR（改炸好定位），每批 `testGrayDebugUnitTest` + 主流程核对。

**SemVer**：规则侧 = §14 该条修订（「不预留资源化通道」→「做 resourcing、仍不翻译」），属**澄清 / 收紧已列项的具体落法**，记 ENGINEERING_RULES **MINOR**（v1.4.0→v1.5.0）。**不**触发 §13「不做完整 i18n → 做完整 i18n」的 MAJOR，因为完整 i18n（翻译 / 多 locale）仍是「不做」。App/代码侧是纯重构，无破坏性变更。

## Consequences

Good：字面量集中可审 / 可统一改 / 去重；真要 i18n 时地基已在（只需加 `values-xx/`）；与模板 §10 收敛。
Bad/成本：30+ 文件批量改，PR 多；命名规范要纪律（不撞车）；`stringResource` 需 `@Composable` 上下文，非 Composable 处（如 VM 里拼消息）要传 `Context` 或保留并在 UI 层取——这类边界按 screen 处理时具体判。
回收：若未来要真 i18n（翻译），在本地基上另开 ADR（那才是 §13 的 MAJOR）。

## Confirmation

每批验收：① 编译过；② 全 `testGrayDebugUnitTest` 过；③ 代码 grep 不到用户可见中文字面量（日志除外）；④ 主流程 UI 走一遍与改前一致。全部迁完后全仓 grep 复核（排除 log / 注释）。

## More Information

- 架构债登记 #6（`.claude/HANDOFF.md`）即此任务。
- ENGINEERING_RULES §10（模板要求资源化）、§13（完整 i18n 仍不做）、§14（本 ADR 修订其资源化条）。
- 与 [[0024]] 三端视觉统一无冲突（仅 Android 侧字符串组织，不动 token / 文案内容）。
