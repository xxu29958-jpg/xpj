# 往来持续使用：完整历史与关系续办

Authority：当前完整 Goal、用户“由你主导、能力只能加强”、最终产品合同 Rev2 §6.4。
起点 `46973e27c8ff7d5d4a51fd4039e1b7921ccdda31`，依赖更新至
`3df32f34b8ff967151dbf98d775bf8094f68b390`，包含尚未合入的 #424/#425；
主线资格不能由这个依赖关系替代。本文件记录当前施工，不替代总目标和最终合同。

## 当前可独立交付的结果

参与者在 Web/Desktop 与 Android 的往来详情可以连续查看建立、还款、调整、
撤销还款、免除、整笔作废、申报发起与处理历史，并翻页到旧记录。
“申报 100、确认 40”分别显示申报与实际确认金额，关联同一还款，不重复算账。
来源退款后的已接受拆账提示保留双方约定，并可以继续到相应往来。

使用现有事实表、proposal latch、participant resolver 和 debt fold。
不新增事件存储、不让客户端根据时间线重新算余额；已有命令、外币原值、付款时间、
单笔撤销、整笔作废、双方确认、债权人免除、原提交/Outbox 与失败恢复全部承接。
现有还款 API 保留兼容读者；真实详情迁移到完整历史，避免两个相互遗漏的历史区。

## 时间线读契约

`GET /api/debts/{public_id}/activity?page=1&page_size=50`，上限 100；
服务 owner `debt_service.list_debt_activity`。同账本 viewer 可读，真实跨账本对方可读，
其他人得到与不存在相同的 404。结果没有私有账本、内部账户 ID、幂等键和他人流水路径。
可选 `focus_repayment` 在同一授权往来内定位实际还款所在页，用于申报与还款的跨页跳转；
不存在或属于其他往来的还款同样返回 `repayment_not_found`，不扩大授权范围。

`DebtActivityListResponse` 保留 debt public ID、home currency、items、page/page_size/total。
每项以 `(kind, public_id)` 为身份，`recorded_at` 是记录/处理时间，付款日期仍在
`repayment.paid_at` / `proposal.paid_at`；按记录时间、固定种类顺序、内部序号倒序分页。
`amount_cents` 仅用于建立本金、signed adjustment、forgiveness；撤销整债没有伪造金额。
repayment 和 repayment_void 携带已有 `RepaymentFactResponse`；proposal_created /
proposal_resolved 携带已有 `MemberRepaymentProposalResponse`（包含当前状态与事实链接）。
只有真实 resolved_at 生成处理事件；不以当前时钟伪造过期事实。申报不是财务事实。
actor 只提供既有公开显示名与是否本人，不泄露内部身份。

当前余额始终使用 canonical Debt；单页是重新查询，不把分页拼成同一历史快照。
Android 绑定切换丢弃旧请求，加载失败保留已读内容和重试。申报成功未必改变 Debt
rowVersion，因此该成功也必须刷新历史；成功后刷新失败不得把已接受命令报为失败。
重新进入同一往来也读取远端申报变化，普通页面重组不重复读取；离页不清除已读历史。
本机未提交意图继续显示在自己的原提交区，不冒充服务器历史。

## 关系续办边界

退款/冲正保留原事实和已接受约定；未接受邀请按现有 owner 取消。
补来源与往来入口不等于完成退款后的关系重议。必须继续完成部分未还、部分已还、
已结清等情况下双方能解释并处理差额的产品结果；不得以伪还款、删除旧约定、
静默修改本金或自动免除实现。已有单方债权免除继续可用。
只能打开当前身份获准读取的来源流水；共享关系不授予对方私有账本权限。

## 影响与验证

入口：API 详情、Web 往来、Android 欠款/应收/目标详情、原单退款提示。
消费者：旧 repayment/proposal 读契约、全部既有写命令与单笔撤销控件、Android
绑定/刷新/分页、Web 历史及 CSRF/OCC/幂等表单；Owner 保持管理职责。
事实/存储/writer/Outbox 不迁移，无数据库迁移。Shortcut 不消费往来历史。

先用真实事实混合、相同时间分页、partial confirm、撤销保留、权限与旧功能反例建立测试，
再接真实消费者。短本地验证覆盖查询、渲染、状态机和 OpenAPI；真实 PostgreSQL、
Connected 和 exact candidate 资格按既有云端门执行。仅合入时读资格，具体失败才诊断。
总地图中的计划历史、储蓄安排、日常工作、Backstage、美术与最终 RC 继续施工。

## 本轮实际检查

- 后端先得到缺少 activity owner 的 RED，混合事实与真实 SELECT 的 12 项短测通过。
  其中交错插入曾使 focus 目标掉到下一页，已改为同一 SQL 定位并取页；
  直接投影简单事实、批量补充 repayment/proposal，取消逐类型重复读取。
- Web 42 项不同短测通过，真实 PostgreSQL 路径仅收集；原单/拆账入口均经参与者校验。
  复核用 open/cleared/voided 三态实际渲染反例修正整笔已作废仍显示单笔撤销入口；
  已结清往来仍能撤销错误还款并重新打开，相关 11 项短测通过。
- Android 147 项定向单测通过，AndroidTest 已编译；Connected 尚未运行。
  后续真实 Compose 重入反例先 RED（远端申报已变，历史只读一次），最小修复后
  14 项直接回归、AndroidTest 编译与 detekt 通过；保留原页、重试和已接受命令结果。
  内部旧 repayment query owner、旧历史 UI 已退役，原有 API/嵌套事实与全部命令保留。
- 用真实 route/template 和虚构数据在 IAB 360/1440 查看页面；无页面横溢，
  部分确认、原币/汇率/撤销、分页可见。此证据属于渲染，不冒称 PostgreSQL 业务实测。
- Backend Ruff、OpenAPI 与代码硬债务检查通过；候选 exact 云端及集成资格仍待取得。

## 已核实的下一段业务关系

源 offset 不改已接受邀请、received Expense 或 Debt；接收账本却已有独立 received
offset 入口，它也不改 Debt。后续双方重议必须先读取两边已发生的变化，不能重复减账。
实际已还、免除和新承担分别保留；例如原份额 40，重议为 20：未还时剩余 20，
已还 10 时剩余 10，已还 30 时需另解释应返 10；有过免除时不能直接套用这组无免除算例。
若采用关联的正金额返还债权，必须同时承接跨账本应付发现、关系身份/唯一性、
双方权限与原提交续办，不得产生一方看不见的待还事项。

合并收口修复：loopback 中账本可见但无法解析 active owner 时，原退款事实页继续可读，
仅省略无法授权的可选往来链接。已发拆账页的往来链接一次加载候选，复用现有
`participant_can_access` 边界，不再为每条链接计算完整余额和名称。两条反例先失败，
修复后 39 项直接回归、Ruff 与 diff 检查通过。

当前共同流水读取主要合并根 Expense 与 offsets；源账本净额和接收账本记录有各自口径，
不能直接相加称为跨账本经济总额。后续从同一 source–invitation–received 关系建立
经济事件归属和约定修订，明确商家净额、个人承担与资金结算的区别；已有财务记录、
分析能力和历史不能因新投影被隐藏或删除。这些是后续必须交付的关系闭环，非本片已完成项。
