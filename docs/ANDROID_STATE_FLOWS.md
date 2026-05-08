# Android 状态流规格

日期：2026-05-06

本文把 Android 端对 `pending`、`confirmed`、`rejected`、`duplicate` 和 OCR 的展示、操作和工程边界收敛成统一口径。后端接口细节以 `docs/API.md` 为准，Android 分层以 `docs/ANDROID_RULES.md` 为准。

## 1. 总原则

状态流要服务“截图等待确认”的用户叙事，而不是把接口字段直接暴露给普通用户。

- 后端 `Expense.status` 是主状态源，只允许 `pending`、`confirmed`、`rejected`。
- `duplicate_status` 是叠加提示，不替代主状态。
- OCR 是草稿建议层，不是入账状态，也不能自动确认。
- Android 普通 UI 使用中文生活化文案，不展示接口名、字段名、id、token、URL 或诊断细节。
- 所有状态变更必须按当前租户执行，不能用 Android 本地过滤替代后端租户隔离。
- 时间由后端保存 UTC，Android 只负责转换为本地展示。

## 2. 状态词映射

| 后端/工程词 | 普通 UI 文案 | 说明 |
| --- | --- | --- |
| `pending` | 待确认 | 截图已经进入账本草稿，需要用户核对后入账。 |
| `confirmed` | 已入账 | 用户已经确认，进入账本、统计和导出。 |
| `rejected` | 已忽略 | 用户决定不入账；普通列表默认不展示。 |
| `duplicate_status=suspected` | 可能重复 | 叠加提示，不能自动拒绝或删除。 |
| OCR | 识别建议 / 自动识别 | 只填草稿和原文，不能自动入账。 |
| `raw_text` | 识别原文 | 默认折叠展示。 |
| `confidence` | 请核对 / 识别较可靠 | 只作为提示，不作为确认依据。 |

## 3. 主状态机

```text
上传截图
  -> 后端保存图片、生成缩略图、计算 hash
  -> 创建 pending
  -> 可选 OCR 草稿
  -> Android 待确认页展示

pending
  -> PATCH 草稿字段
  -> pending

pending
  -> confirm
  -> confirmed

pending
  -> reject
  -> rejected

confirmed
  -> PATCH 修正字段
  -> confirmed

rejected
  -> 终态，普通 UI 不恢复、不展示
```

禁止状态流：

- OCR 成功后直接 `pending -> confirmed`。
- 重复检测后直接 `pending -> rejected`。
- Android 自己生成 `confirmed_at` 或 `rejected_at`。
- 普通 UI 把 `pending`、`confirmed`、`rejected` 原词展示给用户。

## 4. Pending 待确认流

来源：

- iPhone 快捷指令通过 `POST /api/upload-screenshot` 上传。
- Android 通过系统 Photo Picker 和 `POST /api/app/upload-screenshot` 上传。
- 后端成功创建 `pending` 后，Android 待确认页自动刷新。

展示要求：

- 页面标题使用“待确认账单”。
- 卡片展示缩略图、金额草稿、商家草稿、分类、时间、状态提示。
- 金额为空时显示“等待你确认金额”。
- OCR 低置信度时显示“请核对”。
- 疑似重复时显示“这张可能已经记过了”。
- 空状态显示“截图上传后，会出现在这里等你确认。”

工程要求：

- 待确认列表以远端为准；本地可做临时 UI 状态，但不能把 pending 当成 confirmed Room 缓存口径。
- 上传、刷新、OCR retry、确认、忽略都由 ViewModel 发起事件，Repository 调 API 并转换错误。
- Screen 不直接调用 Retrofit、Room、TokenStore 或保存 Token。
- 上传失败只显示生活化中文错误，技术原因进入内部日志或 internal 版诊断。

验收：

- 无待确认账单时不是空白页。
- 上传成功后列表刷新并出现新账单。
- 网络失败时页面不白屏，用户能继续理解当前状态。
- 普通用户看不到 endpoint、HTTP 状态码、token、租户 id 或数据库 id。

## 5. Confirmed 已入账流

进入条件：

- 用户在编辑确认页填写必要字段。
- `amount_cents` 必须非空；为空时后端返回 `amount_required`。
- 用户点击“确认入账”后由后端写入 `confirmed_at`。

展示要求：

- 账本页只默认展示已入账账单。
- 统计、导出、月份筛选和分类筛选只使用已入账账单。
- 用户看到的是金额、商家、分类、消费时间、备注摘要，不需要理解 `page`、`page_size`、`month` 或 `category` 查询参数。

工程要求：

- Android Room 必须缓存 confirmed。
- 同步 confirmed 时按 `serverId` 和 `publicId` 做唯一 upsert，不能重复插入。
- 排序口径保持 `expense_time` 优先，空时使用 `confirmed_at`，再兜底 `created_at`。
- 断网时账本页可展示本地 confirmed 缓存，但不能伪造新确认状态。
- confirmed 允许 PATCH 修正字段，仍保持 confirmed。

验收：

- 确认成功后待确认页不再显示该账单。
- 账本页出现该账单。
- 统计页金额和数量随之变化。
- 重复同步不会产生重复行。
- 断网后账本页不白屏。

## 6. Rejected 已忽略流

进入条件：

- 用户在待确认或编辑确认流程中选择“忽略这张”。
- 必须有二次确认，避免误删。
- 后端只允许拒绝 `pending`。

展示要求：

- “忽略这张”必须弱化，不能和“确认入账”同等视觉权重。
- 普通账本、统计、导出和待确认列表默认不展示已忽略账单。
- 设置页如果展示数量，只使用“已忽略”这类用户文案，不展示 `rejected`。

工程要求：

- Android 不自行删除远端状态；必须调用 `POST /api/expenses/{id}/reject`。
- 拒绝成功后刷新待确认列表。
- 如果本地曾临时保存该 pending，必须从普通待确认 UI 中移除。
- 已忽略不进入 confirmed Room 统计缓存。

验收：

- 忽略前有二次确认。
- 忽略成功后不会出现在待确认、账本、统计、导出中。
- 用户不会把“忽略”误认为“删除服务器文件”或“清除本地缓存”。

## 7. Duplicate 可能重复流

定位：

`duplicate_status` 是风险提示层，不是账单主状态。疑似重复的账单仍然可以处于 `pending` 或 `confirmed`，但普通优先处理场景集中在 pending。

检测来源：

- 上传时计算 `image_hash`，完全相同则标记疑似重复。
- 用户或 OCR 补充金额、商家、消费时间后，后端重新计算同金额、同商家、24 小时内的相似账单。
- 重复检测必须按租户隔离，不能跨租户比较或提示。

用户动作：

```text
可能重复
  -> 仍然保留
  -> mark-not-duplicate
  -> 清除本次重复提示

可能重复
  -> 忽略这张
  -> rejected

可能重复
  -> 继续确认入账
  -> confirmed
```

展示要求：

- 待确认卡片使用“这张可能已经记过了”。
- 详情页展示相似原因，例如“金额、商家和时间接近”。
- 操作文案使用“仍然保留”“忽略这张”，不使用 `mark-not-duplicate`、`duplicate_of_id`。
- 不能因为疑似重复而禁用确认按钮；用户仍有最终判断权。

工程要求：

- `GET /api/duplicates` 只作为聚合入口；待确认详情仍应从账单详情和列表状态读取必要提示。
- `POST /api/expenses/{id}/mark-not-duplicate` 只清除当前检测类型下的提示，不修改金额、图片或确认状态。
- 重复提示的清除记录必须按租户隔离。
- 重复检测失败不能阻断上传、OCR 或确认。

验收：

- 完全相同截图会提示可能重复，但仍创建待确认账单。
- 用户点“仍然保留”后，该组重复提示消失。
- 用户点“忽略这张”后进入已忽略流。
- 不会跨租户提示重复。

## 8. OCR 识别建议流

定位：

OCR 只负责提高录入效率，不能替用户做入账决定。

触发方式：

- `OCR_AUTO_RUN` 可在上传后自动尝试识别，默认关闭。
- Android 可在编辑页触发 `POST /api/expenses/{id}/ocr/retry`。
- 调试或快捷指令文本可走 `POST /api/expenses/{id}/recognize-text`。

写入规则：

- 可以更新 `raw_text` 和 `confidence`。
- 只能填空的 `amount_cents`、`merchant`、`expense_time`。
- 只能在分类仍为 `其他` 时自动分类。
- 不覆盖用户已经手动编辑的字段。
- 不自动确认入账。
- OCR 失败不影响 pending 创建。

UI 状态：

| OCR 情况 | UI 表达 | 用户下一步 |
| --- | --- | --- |
| 未运行 | 等待你确认金额 | 手动填写或重新识别。 |
| 识别中 | 正在识别，只会更新草稿 | 等待或继续查看。 |
| 成功且置信度正常 | 识别建议 | 核对后确认。 |
| 低置信度 | 请核对 | 重点检查金额、商家、时间。 |
| 失败 | 没有识别成功，可以手动填写 | 不阻断确认流程。 |

展示要求：

- OCR 填出的字段标记为“识别建议”。
- 识别原文默认折叠到“查看识别原文”。
- 重新识别按钮要提示“只更新草稿”。
- 识别失败不得显示 provider 名、模型名、堆栈或接口路径给普通用户。

工程要求：

- Provider 名、模型地址和错误细节只进入配置、日志、internal 版或运维文档。
- OCR retry 的加载、成功、失败状态由 ViewModel 管理。
- Repository 负责把统一错误结构转为中文 UI 文案。
- OCR 写入金额、商家或消费时间后，后端需要重新计算疑似重复状态。

验收：

- OCR 成功后仍停留在待确认状态。
- 用户修改字段后，再次 OCR 不覆盖用户修改。
- 低置信度有明确核对提示。
- OCR 失败仍能手动填写并确认入账。

## 9. 页面联动验收

端到端必须覆盖：

1. Android 上传截图后进入待确认。
2. OCR 只填草稿，待确认仍等待用户确认。
3. 疑似重复只提示，不自动拒绝。
4. 用户选择“仍然保留”后提示消失。
5. 用户确认入账后进入账本和统计。
6. 用户忽略后不进入账本、统计和导出。
7. 断网时账本页展示本地 confirmed 缓存。
8. 多租户 token 互相看不到 pending、confirmed、图片、缩略图、重复提示和统计。

