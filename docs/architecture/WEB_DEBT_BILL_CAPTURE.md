# Web 从票据创建往来：后端与前端合同

G4 复用 `DebtBillCapture`、原件 resolver、`debt_bill_source_parse`、已有幂等回执和 `create_debt_idempotently`。Web 只增加会话适配；没有第二解析器、附件库、队列或财务 writer。Claude 负责入口、文案、布局和交互，Codex 负责这些接口、领域合同及合并。

## 已实现接口

全部路径使用当前 `/web` 会话与原有 CSRF 边界，支持普通 Web 和 Desktop bridge。读取必须传明确 `ledger_id`，按账本及创建人隔离；写入携带原草稿 `draft_scope`，身份/账本变化不能接管旧任务。没有会话的开发兼容页面不获得新的票据写权限。

| 方法与路径 | 请求与结果 |
| --- | --- |
| `POST /web/debt-bills` | multipart：`file`、`ledger_id`、`draft_scope`、`creation_key`、`idempotency_key` 和 CSRF。复用原图片来源头校验；返回原 `DebtBillCaptureReceipt`。 |
| `GET /web/debt-bills` | `ledger_id`、`creation_key` 查询该原创建任务的 captures。 |
| `GET /web/debt-bills/by-key/{capture_key}` | `ledger_id`；丢上传回执后按原 key 读取当前 source。 |
| `GET /web/debt-bills/{public_id}` | `ledger_id`；返回原 `DebtBillCaptureResponse`，含状态、原件完整性、解析结果、采用它的往来 ID。 |
| `GET /web/debt-bills/{public_id}/original` | `ledger_id`；受保护的原件快照，private/no-store。 |
| `POST /web/debt-bills/{public_id}/parse` | JSON：`ledger_id`、`draft_scope`、`idempotency_key`、`expected_row_version`；带 `X-CSRF-Token`。返回原 `DebtBillParseOutcome`。 |
| `GET /web/debt-bills/{public_id}/parse-attempts/{attempt_key}` | `ledger_id`；读取原尝试回执，不重新解析。 |
| `POST /web/debt-bills/{public_id}/discard` | 与 parse 相同的 JSON 形状，独立原操作 key；返回原 capture 状态。 |

`creation_key` 必须等于最终 `POST /web/debts` 的原 `idempotency_key`，与上传、解析、丢弃的各自 key 分开。回执丢失时保留原 key、正文、版本和绑定，通过读取或原提交重放核实；不能生成新 key 来猜测之前是否成功。

最终创建沿用现有往来表单，新增两个可选字段：`bill_source_public_id`、`bill_source_row_version`。同时为空时手工创建的旧 payload/fingerprint 不变；使用来源时将两者转成原 `DebtBillSourceReference`，由既有同一事务提交往来事实、source adoption 和首份回执。原 `source_type=manual`、币种/时间/权限/OCC/余额语义不变。

## Claude 前端接入要求

在现有新建往来与 `TicketboxPlanEntry` / `TicketboxDraftStore` 责任内增加入口；沿用当前草稿、租约和接受回执，不另建提交队列。原 `draft_scope`、creation key、capture key/ID、source row version 和解析 attempt key 必须可以回读/续办。新字段加入持久化时承接已有手工草稿；不能因字段升级抹掉原稿。

后端错误重渲染的 `values` 保留两个来源字段；前端模板也须将它们作为原值带回，增强和原生表单都不能在错误/汇率返回后丢掉附件关联。JS 未接入前，这个后端 PR 不表示普通用户入口已交付。

原件先保存，解析只给建议，仍由用户核对最终往来字段。`status=failed` 的解析回执可以继续手工填写并采用原件；默认债务 provider 为手动录入也不能吞掉来源。已解析/已丢弃后使用最新 source version 发起新的明确动作；重放原动作仍使用原版本。丢弃的 source 不可用于创建，但原件和历史继续按原保留策略保存；它不是“删除原图”。

权限拒绝、错账本、未知回执和冲突必须保留原输入，不能默认为新建或成功。服务端接受后可由 Web 详情和 Android 既有 API 读取同一往来/source。来源仅创建者可读，不能因为债务参与人能读债务而扩大其原件权限。

## 验证与回退

后端测试 `test_web_debt_bill_capture.py` 经真实 Web 登录、CSRF、PostgreSQL 验证 capture→parse→create→Android API 一致、重复提交、接受后丢回复、重新打开 HTTP 消费者、拒权、身份/账本错配、OCC、原任务错配及丢弃。解析使用确定性测试 provider；这里不声称真实模型效果、OS 重启或真实浏览器操作通过。

最终仍需 Claude 前端接入后的真实浏览器/安装消费者旅程和适用重启恢复。回退只移除 Web 适配与两个可选表单字段，现有 capture、原件、原生 API、事实和回执保持原 owner；没有数据迁移。
