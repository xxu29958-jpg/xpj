# B05 Web 草稿与恢复入口（AUDIT_BASE `c34efb40`）

扫描：TRACED
当前能力：REGRESSED（相对 #405 草稿 return_* 字段）
修复：PROPOSED（恢复 drafts 中的 return_to / series / period / payment id，shelf 重开带 origin）
证据等级：源码。未跑 BFCache/多标签实机。

## 链

1. 存储 owner：`manual-drafts.js` `TicketboxManualDrafts` L106–110。
   - scope 轴：datasetId / clientGeneration / accountId / ledgerId / deviceId。
   - fields：amount_major, currency_code, merchant, category, spent_at, note, home_currency_code。
   - **不含** return_to / return_recurring_public_id / return_month / return_payment_expense_id。
   - 对照旧 #405 `c0279d86` `manual-drafts.js` L109：上述 return_* 字段**曾在** drafts 里。现网删除 → **REGRESSED**。
2. 表单隐藏返回字段：`expense_new.html` L32–34 由 `edit_return_fields` 渲染；创建页当前打开时 POST 会带上。
3. 消费者：`manual-entry.js` 仅在 `[data-manual-draft-scope]` 表单存在时工作。
4. 草稿架重开：`manual-entry.js` `renderShelf` L82：`href = "/web/expenses/new#manual-" + record.clientRef` —— **丢掉** origin query。
5. 提交后不可变：`save` L63–66 submitted snapshot 不可改 body（除非 serverResult=rejected）。
6. 切账本/设备：`_require_manual_form_binding` `web_expense_create.py` L133–150 拒绝错目标，输入可留在草稿。

## 用户后果

从期次「记录本期付款」进入并开始填写，财务草稿可恢复。从草稿架点回同一 clientRef 时，新 GET `/web/expenses/new` 没有原 series/period，成功后可能按普通 pending/confirmed 返回，而不是原期次。

BFCache/多标签：未执行。表单 hidden fields 在当前 document 内会随 POST 走；新 document 依赖 URL。

## 排除解释

不是第二套命令 owner。服务器仍是 `create_manual_expense`。
