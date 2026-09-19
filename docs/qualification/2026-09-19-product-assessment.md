# 2026-09-19 产品摸排事实记录

本记录固定本次核实对象和证据范围，供[当前产品地图与规划](../current/TICKETBOX_CURRENT_PRODUCT_ATLAS.md)复查。它不替代 Goal/合同，不是新架构或新的资格门。没有以最近几个 PR 代表全产品，也没有重新启动全仓长测试。

## 依据与阶段

已读取当前任务 Goal 全文。目标仍为五域 + Backstage 的完整产品、能力加强、单一事实/命令/查询责任、真实多端连续性、消费级体验及 exact Internal Beta RC；Codex 主导设计、施工和集成。用户本次再次明确由 Codex 主导、只能加强能力。Goal 的 9 月 13 日接续信息作为历史状态核对，不覆盖后来实现。

读取 Gmail 原始完整邮件 `1a03f06d8496e545`（2026-08-26 17:03 UTC），核对本地附件包及 SHA256 清单：

| 源 | 版本 / SHA-256 |
|---|---|
| 最终三合同 ZIP | `0763580e2be2d522eb26a3eaf12626f6fce194999a11c64a5a17ec23603a4eb3` |
| Ticketbox_产品与全系统架构合同_当前版_2026-08-26.md | Rev 2.0；`8f15bce99e8dbd939742e6bd6cd7f0b84ca0c30de1ad0ff0f650c5188e88c4d6` |
| Ticketbox_Windows与数据生命周期架构合同_当前版_2026-08-26.md | Rev 2.0；`a725ba8be79d7e0fd1c13a27403f970cea764f2104f2535bac4bb69e37a6f36b` |
| Ticketbox_G2后产品完整化与Internal_Beta施工合同_2026-08-26.md | 当前阶段执行合同；`c2631bfb6c5644e90a19ad8528cb5cc4bad3def4c778f14d9ce57c610352c628` |

邮件明确：两份顶层架构正式继承 8.17；8.24 归入 Windows Fresh profile；G2 后合同是执行阶段。产品合同 §6/§9/§10/§11/§18 定义领域、离线、时间/金额、端侧分工和不变量；阶段合同 §5/§8 定义完整产品、P1/P2/P3；Windows §18 明确 Internal Beta Host 的诊断/导出/冷备与未资格化 action 边界。

读取后续公网连接邮件 `1a05a22ed7a61a46`（2026-09-01）：Stage 1 只读开放，Stage 2 宿主 mutation 受明确条件约束。检索 8 月 26 日之后与 Ticketbox 合同/裁决有关邮件及相关任务，未发现替代上述架构的新版本；助手评议和历史路线没有上升为 authority。该结论限于本次可访问和所检索来源。

## 精确基线与未合并候选

| 对象 | 实际身份及边界 |
|---|---|
| 当前 origin/main | `8e1aa2281cca684cfdc01541892ad4c0f9fdd81d`，tree `95707f802fe400ab37f281bb2a6f5fbf9ffa08ef`；本次 fetch 后读取，最新合并 #420。 |
| 摸排分支 | 从上述 main 建立隔离 `codex/product-assessment-20260919`；只修改产品地图、事实记录及旧路线导航声明。 |
| 日常安装源身份 | artifact identity 记录为 `0ac2703217ceb38ec84e38e7a8a332459aa58672`（#419）。实际安装 release-manifest 的 SHA-256 与该记录匹配：`8050bce188feb786f2f0bf388ff79f895327f90a4ad5237c6b62ca53ad3e4e39`。未逐个重验全部安装 payload，不把 manifest 匹配扩大为完整二进制资格。 |
| 日常构建记录 | CI `35301042897`、Connected `35301042931`；历史安装记录不能代替本次运行观察。 |
| 开放 #415 | head `14c9eca8cf6a301a6f0d9c7a7c8dfb0227c424b9`。对其 8 个改动文件比较 current-main/head blob，7 个完全相同，覆盖全部生产改动。唯一差异是 `RecurringEditorRestorationTest.kt` 中 CNY 入口选 JPY 后恢复的测试。产品实现已被 #416 吸收；这是候选去重，不是外币能力删除。 |
| 草稿 #372 | head `fb490a7cae27f9b8a0e9a903d236bfcd316408da`，债务录入键盘下操作区候选；没有把该旧 head 合入或安装。 |

近期实际整合包括 #404 外币账单、#407 冻结 FX 导出、#409/#413 占用释放、#412/#414/#416 期间付款及身份续办、#417 Host 收敛、#419 原意图 A 成功后新草稿 B 的可达性。#405/#411 已关闭未合并，不能当待合并队列重复施工。

检查了现有 37 个工作树状态，发现的是若干既存未跟踪证据、临时目录及 Android 崩溃/回放日志；未覆盖、清理或挪动。摸排起点的隔离树干净。

## 已有 exact-main 云端结果

本次查询均已到终态，head 均为 `8e1aa2281cca684cfdc01541892ad4c0f9fdd81d`：

- [CI 35446861486](https://github.com/xxu29958-jpg/xpj/actions/runs/35446861486)：completed / success。
- [CodeQL 35446861489](https://github.com/xxu29958-jpg/xpj/actions/runs/35446861489)：completed / success。
- [Android Connected 35446861481](https://github.com/xxu29958-jpg/xpj/actions/runs/35446861481)：completed / success；日志的 checkout/source SHA 对齐。

下载并读取已有 `repository-codebase-weight`：identity 为 direct_head、source/measurement SHA 均为上述 main、base 为 `0ac27032`；verdict 为 `NO DEBT REGRESSION`，failures 为空。它用于源码导航，不能证明用户任务完整或产品 RC。

读取同 head 的 `consumer-art-previews`，实际查看了 `debt-create-editing.png`、`inbox-paper-writer.png`。前者有真实 Android 数字键盘、下方动作未在该帧显示；这是继续核实键盘可达性的证据，不单凭截图断言所有滚动路径失败。后者显示真实收件空态及上传入口。未把这组截图当全产品视觉验收。

## 多端运行观察

### Windows 安装与 Web / Owner

本次对当前安装只读观察，另在新建的 Edge 摸排标签中完成了一次本地用户确认登录，建立浏览器会话。没有修改财务记录、识别配置、身份绑定、安装或导入数据。

- TicketboxBackend、TicketboxPg 实际处于 Running。
- 安装健康接口以有效 challenge 返回 200，backend version 1.2.0、runtime available、owner configured；公网 endpoint、Android、iPhone 相关状态仍为 configured_unverified。配置存在不等于本次完整跨端任务已通过。
- Web 待处理可进入，显示真实空态、上传/CSV/手工记录和快捷入口；确认列表可见原币、冻结 FX、本位金额、原单及冲正。
- 总览、预算、流水可对照同月实际净额。往来是诚实空态；recurring 存在外币 series，创建表单实际提供币种选择。
- occurrence 页区分义务月份与付款月份，提供记录缺失付款、回原期及显式关联；未点击财务提交。
- Web 数据健康显示“良好”，同时存在无图确认记录；页面解释手工录入/清理可能性，不能据此判断 bytes 完整或数据损坏。
- 总览没有备份发布记录。9 月 18 日存在历史冷归档记录，但未验证它覆盖此后日常新增数据，也不能据此宣称当前完全没有任何保护。
- Owner 可看到账本/设备/上传入口的实际状态，当前没有活动上传链接；零链接是当前配置情况，不是 UploadLink 功能缺失。
- Owner 识别设置和诊断能显示选中 provider、自动运行等配置，却没有最近实际识别结果和关联任务续办。未执行新的 OCR 调用来覆盖该观察。

本次没有直连日常 PostgreSQL 做全表盘点，没有绕过数据目录 ACL 或枚举所有原件。业务读取走实际鉴权页面，结构及关联读取 current-main 模型/服务，风险反例使用合成输入。报告不保存真实商家、金额、token、上传凭据或诊断原始秘密。

本次浏览器是宽屏实际窗口。一次设置 360 宽 viewport 的尝试没有改变目标标签的实际宽度，已复位；**不计为窄屏测试**。Web 360/768/1440 全覆盖仍属于后续真实验收。

### Android 与 iPhone

ADB 只发现本机 emulator-5554；实体 Android 不在线，iPhone 不可访问。模拟器现有 internal 包最后更新于 9 月 4 日，保留了本地数据库/WAL，因此未覆盖安装、清空、重绑或把它当 9 月 19 日 main。当前 Android 运行证据采用上述 exact-main 云端 Connected，严格限定于其实际测试和截图范围。

Shortcut 当前端到端上传、token 撤销、重复提交、4xx/失败展示没有在 iPhone 重跑；[现有文档](../runbook/IOS_SHORTCUT.md)的首次使用说明及分支行为要与当前 Desktop/Owner 配对流程核对。不能在未演练前宣布它已经误报成功。

## 两个实际执行的最小反例

使用 current-main 的生产函数，在短时独立 Python 进程中传入合成记录；数据库连接数为 0，没有启动本地长测试、修改日常库或创建真实导入。

### 退款导出再预览会变成正向支出

执行 [stats_service.export_confirmed_csv](../../backend/app/services/stats_service.py) → [import_service.parse_csv_preview](../../backend/app/services/import_service.py)。仅把前者的事实查询替换为合成 projection；导出器与导入解析器均为原生产实现。

合成场景为 CNY 原单 10000 minor、退款 2000 minor、剩余 8000 minor。实际结果：

```text
export_entry_kind = offset
export_offset_kind = refund
export_signed_minor = -2000
preview_valid_count = 1
imported_amount_minor = 2000
imported_original_minor = 2000
parsed_has_event_kind = false
error = null
```

[import_money](../../backend/app/services/import_money.py)按 amount 等字段取正向金额；预览未承接 entry_kind/offset_kind/root identity/stream direction。[batch apply](../../backend/app/services/csv_import_batch_service/_apply.py)随后创建 Pending Expense。已证明生产 serializer/parser 的错误解释路径；实际入库并确认的后果来自调用链，**本次未执行真实入库/确认，也没有确认用户已受影响**。

### 已确认根流水会随查询时区跨月

把 `expense_time = 2026-08-31T16:30:00Z` 的同一合成已确认记录传给 [spending_contract_service.stat_month_label](../../backend/app/services/spending_contract_service.py)：

```text
UTC -> 2026-08
Asia/Shanghai -> 2026-09
```

编译实际 confirmed-stream PostgreSQL 查询：根记录的日期来自 query timezone，offset 分支读取持久 accounting_date。对应 [Expense](../../backend/app/models/expense.py) 与 [ExpenseOffsetFact](../../backend/app/models/expense_offset.py) 的差异真实存在；所有依赖共享 stream/period 的消费者属于影响范围。这证明语义缺口，不代表日常用户的历史记录已经被本次改变。

## 其余结论的源码依据与证明强度

| 结论 | current-main 依据 / 本次证明范围 |
|---|---|
| 附件零件充足，在线完整性仍局部 | [file_service](../../backend/app/services/file_service.py)保存 digest，但读取主要做受限 resolve/is_file；[data_quality_service](../../backend/app/services/data_quality_service.py)缺图判定主要看路径和删除标记；[dataset_originals_adapter](../../backend/app/services/dataset_originals_adapter.py)已有原件 hash 校验。源码确认；未损坏日常原件做实验。 |
| 关系事实不应重造 | [debt fold](../../backend/app/services/debt_service/_fold.py)、[split transitions](../../backend/app/services/bill_split_service/_transitions.py)已有 append-only 推导及接受关联；[repayment activity](../../backend/app/services/debt_service/_repayment_activity.py)只合成 Repayment/RepaymentVoid。完整关系时间线是消费缺口，不等于调整/免除事实没实现。 |
| 部分退款后的双方续办不足 | [成员债务 guards](../../backend/app/services/debt_service/_guards.py)保护直接调整边界，[forgive](../../backend/app/services/debt_service/_forgive.py)为整笔剩余免除；Android [FactOffsetsSection](../../android/app/src/main/java/com/ticketbox/ui/screens/expense/fact/FactOffsetsSection.kt)主要展示原约定/净额差异。源码路径确认，尚未在日常真实成员间做修改。 |
| 计划历史不完整 | [budget command](../../backend/app/services/budget_command_service.py)、[goal_service](../../backend/app/services/goal_service.py)、[recurring item command](../../backend/app/services/recurring_item_command_service.py)主要更新当前行；已有 [IncomePlanRevision](../../backend/app/models/income_plan_revision.py) 和 [OccurrenceRevision](../../backend/app/models/recurring_occurrence.py)必须保留。row_version/通用审计字段不等于完整前后计划历史。 |
| “存”不能算完整 | [Budget/Goal 模型](../../backend/app/models/budget.py)的 Goal type 仅 spending_limit/debt_repayment；[Web budget advise](../../backend/app/routes/web_budget_advise.py)从 query/form 读取 savings_target/reserved_buffer，[模板](../../backend/app/templates/web/budget_advise.html)确有可用试算；没有据此假定存在实际存款事实。 |
| 不能重复迁移 pending 命令 | [ExpensePendingRepository](../../android/app/src/main/java/com/ticketbox/data/repository/ExpensePendingRepository.kt)的保存、确认、拒绝、撤销、重识别已由 ExpenseBatch/Outbox 承接。#413/#419 的失败丢弃与新草稿继续等增强也已进入 main。 |
| 冲正后固定支出预留已有正确基础 | [recurring_occurrence_query](../../backend/app/services/recurring_occurrence_query.py)排除有效 reversal，已关联付款失效时给 needs_review 并恢复 reserved amount；[现有测试](../../backend/tests/test_recurring_occurrences.py)有真实 API 路径断言。本次核源码及已有云端结果，不在日常库重做。 |
| 通知能力须保留 | [NotificationListenerService](../../android/app/src/main/java/com/ticketbox/notification/TicketboxNotificationListenerService.kt)先检查开关、权限、账本绑定和包白名单，再分流消费/还款草稿并沿投递身份去重；还款草稿暂不发消费待处理深链通知。通知是已有采集能力，不因地图改写遗漏；本次未重新授权或投递实机通知。 |
| 持久读取与原始草稿是不同缺口 | [GoalQueryReader](../../android/app/src/main/java/com/ticketbox/data/repository/GoalQueryReader.kt)已有缓存绑定；[BudgetDraftStore](../../android/app/src/main/java/com/ticketbox/viewmodel/BudgetDraftStore.kt)已有预算草稿。Budget/Debt 等 repository 的查询和 [IncomePlanEditViewModel](../../android/app/src/main/java/com/ticketbox/viewmodel/IncomePlanEditViewModel.kt)、[CreateSpendingGoalViewModel](../../android/app/src/main/java/com/ticketbox/viewmodel/CreateSpendingGoalViewModel.kt)的原始输入不因此得到持久化。 |
| 保存视图尚缺 | 当前模型有 DashboardCardPreference，主要是卡片显示偏好；未找到持久命名查询条件与跨端重开消费者。结论为当前扫描范围内的产品缺口，不新造通用报告平台。 |
| 资料库需补引用治理并去重 | [category_preference_service](../../backend/app/services/category_preference_service.py)主要管理分类选项/排序；[merchant_catalog_service](../../backend/app/services/merchant_catalog_service.py)及标签/规则 owner 已有治理；[Owner tag cleanup](../../backend/app/routes/owner_console/_tag_cleanup.py)与 Web 标签页有重复产品入口。迁移独有孤立删除保护/撤销后才删。 |
| OCR 状态未贯通结果 | [Owner diagnostics](../../backend/app/routes/owner_console/_diagnostics.py)和 [runtime settings](../../backend/app/services/runtime_settings_service.py)主要传配置；BackgroundTask 及原单续办已有责任点。源码与本次运行观察一致。 |
| 备份不可按文件名宣称产品完成 | [backup_service](../../backend/app/services/backup_service.py)要求离线 writer fence、显式权限、数据库/原件、持久发布及 inventory；[dataset backup action](../../backend/app/database/_dataset_backup_action.py)已有 adapter。HTTP 是发布结果的只读消费者；本次没有运行 held 生命周期 action。 |
| recurring 建议可能绕开更正事实 | [insights_service._confirmed_expenses_for_recurring](../../backend/app/services/insights_service.py)直接查 confirmed Expense，后续分组读原金额；需对退款/冲正影响写实际反例。**仅源码疑点，未执行证伪，不按已确认财务故障处理。** |

对具体代码改变，应沿实际调用链完成影响闭合，不能把上表当永久完整路由清单或自动扩大测试范围。未知版本拒绝/隔离、跨端撤权、系统中断和完整 RC 继续使用既有协议、Outbox、角色及 release owner 验证。

## 本次交付范围与后续动作

已完成依据校准、current-main/安装/候选分离、真实页面和云端 Android 证据核对、业务关系及风险反例检查；修改同一份 atlas，标记三个旧 roadmap 的历史地位。未改运行时产品、数据库或日常设备。

规划由当前 Codex 主导落实，既有授权继续有效。先完成自身 CSV 的正确事件解释及续办，紧接账务日期跨域一致性，再按地图完成关系/计划、资料库/跨端/Backstage、消费级体验和 exact RC。不得以这两个先手代替完整目标，不以文档完成宣布产品完成，不额外增加逐片审批或停工条件。
