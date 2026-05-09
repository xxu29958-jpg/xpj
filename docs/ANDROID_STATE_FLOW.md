# 小票夹状态流与业务边界

本文是 Android 与后端共同遵守的当前业务状态规范。

## 1. 产品主线

小票夹当前主线必须保持：

```text
上传截图
  ↓
pending 待确认
  ↓
用户编辑金额、商家、分类、备注、消费时间
  ↓
confirmed 入账
  ↓
Android Room confirmed 缓存
  ↓
账本 / 统计展示
```

禁止任何旁路把截图直接变成正式账单：

- 上传后不得自动入账。
- OCR 不得自动入账。
- 重复检测不得自动删除或拒绝。
- 后端不得替 Android 伪造用户确认动作。

## 2. 状态流

必须支持并保持以下状态流：

```text
pending -> editing -> confirmed
pending -> rejected
pending -> suspected_duplicate -> kept_not_duplicate
pending -> ocr_retry -> draft_updated
confirmed -> edited_confirmed
manual -> confirmed
```

文字状态图：

```text
上传截图
  ↓
pending
  ├─ 编辑保存 -> pending 草稿更新
  ├─ OCR retry -> pending 草稿更新
  ├─ 疑似重复 -> duplicate_status = suspected
  ├─ 标记仍然保留 -> 清除当前重复检测类型
  ├─ 确认入账 -> confirmed
  └─ 删除 / 忽略 -> rejected
```

边界：

- `pending` 是截图上传后产生的待确认账单。
- `editing` 只是用户编辑草稿，不是新状态。
- `confirmed` 代表用户手动确认后的正式入账。
- `rejected` 代表用户明确忽略待确认账单。
- `manual` 记一笔必须远端创建成功后才写 Room，并直接进入 `confirmed`。

## 3. 时间口径

后端数据库保存 UTC datetime。

API 返回 ISO 8601 UTC 字符串，统一以 `Z` 结尾，例如：

```text
2026-05-04T08:23:25Z
```

字段语义：

- `created_at`：上传或创建时间。
- `updated_at`：最近业务更新时间。
- `expense_time`：实际消费时间。
- `confirmed_at`：用户确认入账时间。
- `rejected_at`：用户拒绝时间。

统计时间使用：

```text
COALESCE(expense_time, confirmed_at)
```

`GET /api/stats/monthly?month=YYYY-MM` 的 `month` 表示服务端配置时区里的自然月。当前默认时区由 `OCR_DEFAULT_TIMEZONE` 控制，默认 `Asia/Shanghai`。

后端查询时必须把本地自然月转换成 UTC 边界：

```text
2026-05 Asia/Shanghai
  -> [2026-04-30T16:00:00Z, 2026-05-31T16:00:00Z)
```

Android：

- 展示时间时转设备本地时区。
- 账本月份筛选按手机系统时区计算。
- Room 本地趋势、月份筛选和统计补充也按手机系统时区。
- Android 请求 confirmed、months、stats 和 export 时传手机系统 IANA 时区；后端未收到 `timezone` 时才回落到 `OCR_DEFAULT_TIMEZONE`，当前默认是 `Asia/Shanghai`。

这样避免 UTC 月底账单在 Android 显示为下个月，但后端统计仍落在上个月。

## 4. 上传失败补偿

上传接口必须保持：

- iPhone 快捷指令：`POST /u/{upload_key}`，使用 UploadLink URL。
- Android App：`POST /api/app/upload-screenshot`，使用 `Authorization: Bearer <session_token>`。
- 两者都只能创建 `pending`。

上传要求：

- 支持 `multipart/form-data` 和 raw image body。
- raw 和 multipart 使用同一套最大大小限制。
- 必须先校验 UploadLink 或 session token，再读取和保存文件。
- 超限返回 `file_too_large`。
- 不支持类型返回 `unsupported_file_type`。
- 错误统一返回 `{ "error": "...", "message": "..." }`。
- 文件名随机生成，不使用用户原始文件名。
- 数据库只保存相对路径。
- 上传时计算 `image_hash`。

补偿规则：

- 文件保存成功但 pending 创建失败时，必须删除刚保存的原图和缩略图。
- 缩略图生成失败不能导致上传失败。
- HEIC 缩略图失败时仍然创建 pending。

## 5. Pending / Confirmed 刷新

确认入账成功后，Android 必须体现：

- pending 列表移除该账单。
- ledger 同步后能看到该账单。
- stats 刷新后金额变化。
- duplicate 状态以服务端最新响应为准。
- Room 写入 confirmed 缓存。

拒绝成功后：

- pending 列表移除该账单。
- rejected 不进入账本。
- rejected 不参与重复提醒。

## 6. Room 缓存边界

Room 只承担 confirmed 账本缓存，不做复杂离线编辑。

规则：

- pending 不做复杂离线编辑。
- confirmed 远端成功后写 Room。
- confirmed 同步按 `serverId` upsert，不能重复插入。
- 账本在线时远端优先。
- 远端失败时账本页保留并展示 Room confirmed 缓存。
- 编辑 confirmed 远端成功后更新 Room。
- 编辑 confirmed 远端失败时不改 Room。
- 手动记一笔必须在线成功后才写 Room。

## 7. 重复检测

重复检测只提示，不做处置。

允许：

- 根据 `image_hash` 标记疑似重复。
- 根据金额、商家、消费时间标记相似重复。
- confirmed 可以作为相似参照。

禁止：

- 自动删除。
- 自动拒绝。
- 自动入账。
- 跨租户检测。
- rejected 参与重复提醒。

`mark-not-duplicate` 只清除当前检测类型，不影响其他检测类型。例如用户忽略了同图 hash 重复后，后续仍可根据金额、商家、时间触发相似重复提醒。

## 8. OCR 草稿规则

OCR 只填草稿，不自动入账。

规则：

- OCR retry 只能更新 pending 草稿字段。
- OCR 不得设置 `status = confirmed`。
- OCR 不得设置 `confirmed_at`。
- OCR 不得删除截图。
- OCR 不得绕过用户确认。
- OCR 不得覆盖用户已经手动填写的金额、商家、消费时间。
- 分类只有在当前为“其他”时才允许给出建议。
- 低置信度时 Android 只显示“请核对”。

解析口径：

- OCR 解析使用候选打分模型，不按单张截图堆独立 `if` 分支。
- 金额、商家、消费时间和分类都先生成候选，再按证据加权/降权选择最高分。
- 评分维度包括来源、字段标签、上下文、邻近度、票据场景、结构位置、一致性和噪音；新增样本优先归入这些维度。
- 票据场景只作为候选校准先验，例如支付宝详情、支付成功页、微信支付、银行提醒、出行支付；它不能直接确认账单字段。
- 同一金额多处出现、商家命中分类、交易成功附近的标题等属于互证加分；红包、立减、广告、机构名和状态栏属于噪音降权。
- 候选证据只用于后端测试和调试，不进入普通 Android UI。
- `confidence` 是候选分数的摘要，只提示用户核对优先级，不作为自动入账依据。

### 8.1 OCR 字段来源

后端用内部字段 `ocr_draft_fields` 记录哪些字段仍然是 OCR 草稿。

规则：

- OCR 可以填充空字段或默认分类。
- OCR 可以纠正仍然标记为 OCR 草稿的字段。
- 用户通过 PATCH 修改过的金额、商家、分类或消费时间，会从 OCR 草稿集合移除。
- 后续 OCR retry 或自动识别不得覆盖已经被用户手动修改过的字段。
- `raw_text` 和 `confidence` 属于识别结果本身，可以随 OCR retry 更新。

这个规则解决“初次 OCR 错了，后面更强规则修不回来”的问题，同时保留“用户确认优先”的产品边界。

## 9. 图片清理

图片和账单数据必须解耦。

规则：

- 确认账单后即使原图被清理，账本数据仍能展示。
- 图片不存在时，图片接口返回 `image_not_found`。
- Android 图片预览显示占位，不影响账单卡片、账本和统计。
- 图片清理不得删除账单本身。

## 10. 分类规则

标准分类保持统一：

```text
餐饮、交通、购物、娱乐、医疗、教育、住房、通讯、AI订阅、数码、游戏、生活、其他
```

兼容旧分类：

```text
吃饭 -> 餐饮
```

分类规则：

- `keyword` 可以自由填写。
- `category` 尽量从标准分类选择。
- 后端保存和统计前需要归一化分类。
- 分类规则按租户隔离。
- 避免因为自由文本导致统计分类爆炸。

## 11. 当前测试覆盖

后端测试必须覆盖：

- 上传成功状态必须是 `pending`。
- raw body 上传成功创建 pending。
- multipart 上传成功创建 pending。
- Token 错误时拒绝。
- 文件超限返回 `file_too_large`。
- 不支持类型返回 `unsupported_file_type`。
- 保存成功但 DB 失败时清理文件。
- 缩略图失败不影响 pending。
- 相同 `image_hash` 上传后标记 suspected duplicate。
- OCR retry 不会 confirmed。
- duplicate 不会 rejected。
- confirm 后 pending 消失。
- reject 后不出现在 pending。
- mark-not-duplicate 不影响其他检测类型。
- 月份筛选按配置本地时区。
- 图片清理后账单仍可展示。

Android 测试必须覆盖：

- confirmed 写入 Room 时按 serverId upsert。
- pending / rejected 不进入 confirmed 缓存。
- 账本本地月份筛选按手机系统时区。
- 远端失败时账本页不清空 Room 已有 confirmed 数据。
- 图片路径缺失时域模型仍可展示账本数据。
