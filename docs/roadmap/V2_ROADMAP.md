# 小票夹第二版能力说明

> **定位**：本文聚焦 OCR/分类/重复检测/缩略图/图片清理能力。这些已在 v0.4+ 落地。
> 作为功能上下文参考保留，当前开发路线见 `docs/roadmap/POST_BETA_DEVELOPMENT_ROADMAP.md`。

## 1. 当前定位

本文件记录 OCR、分类规则、重复检测、缩略图、图片生命周期和生活化统计这组能力的现状与后续边界。当前代码已经落地最小闭环，不应再按“未来才做”理解。

核心原则不变：

```text
AI/OCR 只生成草稿和建议，用户确认后才入账。
```

第二版目标：

```text
截图上传
  -> 后端保存图片
  -> OCR/规则引擎生成金额、商家、消费时间、分类建议
  -> 检查是否疑似重复
  -> Android 展示待确认账单、识别结果、置信度、重复提示
  -> 用户确认或修正
  -> 入账
  -> 可选确认后删除原图或保留 N 天
```

## 2. 已落地能力

已落地：

- OCR 识别。
- 自动分类规则。
- 重复截图检测。
- 缩略图生成。
- 图片生命周期管理和维护清理接口。
- 生活化统计。

当前已落地的最小能力：

- OCR retry 可插拔入口，不自动入账。
- `OCR_PROVIDER=empty|mock|rapidocr|local_llm` 配置入口已落地。
- `receipt_parse_service.py` 及 `receipt_parse_*` 子模块已能从 `raw_text` 规则提取金额、商家、消费时间、分类建议。
- `POST /api/expenses/{id}/recognize-text` 已落地，可用于调试文本识别或接入快捷指令文本。
- `OCR_AUTO_RUN` 上传后自动识别开关已落地，默认关闭；失败不影响 pending 创建。
- 自动分类规则表、默认规则、规则增删改接口和 Android 设置页入口。
- `image_hash` 完全重复检测、疑似重复列表和“仍然保留”操作。
- 用户填写金额、商家、消费时间后，会按金额一致、商家一致、24 小时内标记疑似重复。
- 受保护 JPEG 缩略图接口和 Android 缩略图/原图预览。
- `DELETE_IMAGE_AFTER_DAYS` 图片清理维护接口，仅限 admin scope token。
- Android 统计页显示生活化统计。

仍然不建议做：

- 多用户。
- 账号密码。
- 商业云部署。
- 银行接口。
- 支付接口。
- 微信/支付宝自动监听。
- 后台管理大屏。
- 复杂权限系统。
- 自动入账。

## 3. 后端新增模块

```text
backend/app/
  services/
    ocr_service.py
    classify_service.py
    duplicate_service.py
    cleanup_service.py
    thumb_service.py
  routes/
    rules.py
    duplicates.py
    maintenance.py
```

职责：

- `ocr_service.py`：OCR 入口，负责把图片转为结构化识别结果。
- `classify_service.py`：基于商家、OCR 原文和规则生成分类建议。
- `duplicate_service.py`：检查完全重复和疑似重复。
- `cleanup_service.py`：按配置删除已确认原图或过期图片。
- `thumb_service.py`：生成 JPEG 缩略图，解决 Android 列表预览。
- `rules.py`：分类规则管理。
- `duplicates.py`：疑似重复账单查看和处理。
- `maintenance.py`：图片清理维护接口，受 admin scope token 保护，并按当前维护上下文账本执行。

## 4. OCR 架构

不要把某个 OCR 服务写死，建议使用 provider 抽象：

```text
OcrService
  -> EmptyOcrProvider
  -> MockOcrProvider
  -> RapidOcrProvider
  -> LocalLlmOcrProvider
  -> FutureCloudOcrProvider
```

OCR 输出：

```json
{
  "amount_cents": 3680,
  "merchant": "美团外卖",
  "expense_time": "2026-05-03T04:20:00Z",
  "raw_text": "OCR 原文",
  "confidence": 0.82
}
```

写入策略：

- OCR 可以填充 pending 草稿字段。
- 不自动确认入账。
- 如果用户已经手动编辑过字段，要避免 OCR 后台任务覆盖用户修改。
- Android 上标记“识别建议”或显示置信度。

## 5. 自动分类规则

当前先做规则，不急着上大模型。

规则示例：

```text
美团 / 饿了么 / KFC / 麦当劳 -> 餐饮
京东 / 淘宝 / 拼多多 -> 购物
OpenAI / Claude / Gemini / Kimi -> AI订阅
滴滴 / 高德 / 地铁 -> 交通
Steam / TapTap / PlayStation -> 游戏
医院 / 药房 / 美团买药 -> 医疗
```

当前默认分类已经扩展为：

```text
餐饮 / 交通 / 购物 / 娱乐 / 医疗 / 教育 / 住房 / 通讯 / AI订阅 / 数码 / 游戏 / 生活 / 其他
```

旧版 `吃饭` 作为兼容别名归一到 `餐饮`，避免历史数据、统计和筛选口径分裂。

新增表：

```text
CategoryRule
  id: int
  keyword: string
  category: string
  enabled: bool
  priority: int
  created_at: datetime
  updated_at: datetime
```

匹配逻辑：

```text
merchant + raw_text
  -> keyword 规则匹配
  -> 命中最高优先级规则
  -> 生成分类建议
```

第一阶段可以直接填 `category`，但 Android 端应显示它来自自动识别。

## 6. 重复截图检测

第二版分三层：

```text
1. image_hash 完全一致
2. amount_cents + merchant + expense_time 接近
3. raw_text 相似度
```

新增字段：

```text
duplicate_status: none / suspected / duplicate
duplicate_of_id: int?
duplicate_reason: string?
```

处理策略：

- 不要直接拒绝上传。
- 疑似重复仍创建 pending。
- Android 待确认卡片显示重复提示。
- 用户决定保留或删除。

提示示例：

```text
可能重复：与 5 月 3 日 12:20 的美团外卖 36.80 元相似。
```

Android 操作：

```text
仍然保留
删除这条
```

## 7. 缩略图与 HEIC 处理

后端接受 HEIC 原图，但当前缩略图生成会跳过 HEIC，Android 不能依赖 HEIC 缩略图预览。

当前实现：

- 上传后生成 JPEG 缩略图。
- 列表页加载缩略图。
- 详情页再加载原图。
- JPG、JPEG、PNG、WEBP 会尝试生成 JPEG 缩略图；HEIC 原图保留，缩略图可能为空。

新增字段：

```text
thumbnail_path: string?
```

新增接口：

```http
GET /api/expenses/{id}/thumbnail
Authorization: Bearer <session_token>
```

原图接口继续保留：

```http
GET /api/expenses/{id}/image
Authorization: Bearer <session_token>
```

安全要求不变：

- 不公开 uploads。
- 不返回本机路径。
- 图片读取必须经过鉴权接口。

## 8. 图片生命周期

第二版可以实现图片保留策略：

```env
DELETE_IMAGE_AFTER_CONFIRM=false
DELETE_IMAGE_AFTER_DAYS=30
GENERATE_THUMBNAIL=true
```

新增字段：

```text
image_deleted_at: datetime?
thumbnail_deleted_at: datetime?
```

策略选项：

```text
永久保留原图
确认入账后删除原图
确认后保留 30 天再删除
只保留缩略图
```

第一阶段建议默认：

```text
保留原图
生成缩略图
不自动删除
```

## 9. 生活化统计

第二版统计不要变成财务后台，应保持私人生活账本气质。

新增统计：

```text
本月总支出
分类支出
AI 订阅月花费
数码消费
最大一笔
最近 7 天
比上月多/少
高频商家
真香标签
后悔指数
值不值评分
```

可新增字段：

```text
tags: string?
value_score: int?
regret_score: int?
```

字段含义：

```text
tags           轻量标签，例如 真香、冲动消费、必要支出
value_score    值不值评分，1-5
regret_score   后悔指数，1-5
```

Android 编辑页可增加轻量控件：

```text
值不值
后悔吗
标签
```

## 10. 第二版 API 增量

建议接口：

```http
POST /api/expenses/{id}/ocr/retry
GET  /api/expenses/{id}/thumbnail
GET  /api/duplicates
POST /api/expenses/{id}/mark-not-duplicate
GET  /api/rules/categories
POST /api/rules/categories
PATCH /api/rules/categories/{id}
GET  /api/stats/lifestyle?month=2026-05
```

第二版最小闭环不必一次实现全部。

推荐最小集合：

```http
GET  /api/expenses/{id}/thumbnail
POST /api/expenses/{id}/ocr/retry
GET  /api/duplicates
GET  /api/stats/lifestyle?month=2026-05
```

## 11. Android 第二版变化

待确认页：

- 显示截图缩略图。
- 显示 OCR 置信度。
- 显示疑似重复提示。
- 显示自动分类来源。

编辑页：

- OCR 原文默认折叠。
- 可一键重新 OCR。
- 可编辑值不值评分。
- 可编辑后悔指数。
- 可添加标签。

统计页：

- 增加 AI 订阅月花费。
- 增加高频商家。
- 增加真香/后悔消费列表。
- 增加最近 7 天趋势。

设置页：

- 图片保留策略。
- OCR 开关。
- 自动分类规则管理。
- 清理本地缓存。

## 12. 第二版优先级

1. 上传后异步 OCR，自动填金额、商家、消费时间、raw_text、confidence。
2. 分类规则引擎，自动填分类或生成分类建议。
3. 生成 JPEG 缩略图，Android 列表显示图片。
4. 重复截图检测，先做 `image_hash` 完全重复，再做相似重复。
5. Android 待确认页展示识别置信度和疑似重复。
6. Android 增加值不值、后悔指数、标签。
7. 图片保留策略：确认后删除、保留 30 天、永久保留三选一。

## 13. 第二版验收标准

当前能力验收：

- 上传截图后能生成 OCR 草稿。
- OCR 不会自动入账。
- 用户能看到识别金额、商家、消费时间和置信度。
- 自动分类能覆盖常见商家。
- 完全重复截图能被识别。
- 疑似重复不会被自动删除。
- Android 列表能显示缩略图。
- HEIC 上传后原图仍通过受保护图片接口访问；缩略图可能不存在，客户端需要降级处理。
- 可配置图片保留策略。
- 统计页更生活化，而不是后台报表化。

## 14. 长期方向

第三阶段之后可以考虑：

- 更强 OCR provider。
- 本地规则 + AI 分类组合。
- 月度消费回顾。
- AI 订阅专项统计。
- 数码消费专项统计。
- 值不值复盘。
- Cloudflare Access 保护的轻量 Web 管理页。

但这些都不应破坏当前核心原则：

```text
私人、本地优先、Token 保护、人工确认、不开危险远程接口。
```
