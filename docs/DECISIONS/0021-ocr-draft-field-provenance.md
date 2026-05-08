# 0021 OCR 草稿字段来源

## Status

Accepted.

## Context

真实联调中出现过这样的错误链路：

```text
OCR 初次识别错金额 -> pending 草稿展示错误金额
后端规则修正 -> OCR retry 再次识别
旧逻辑因为 amount_cents 已经非空，拒绝覆盖
```

如果简单改成 OCR 永远覆盖，又会破坏另一条产品边界：

```text
用户已经手动改过金额、商家、分类或消费时间
OCR retry 不得覆盖用户确认过的字段
```

所以问题不是继续为每张图写特殊 `if`，而是缺少字段级草稿来源。

## Decision

后端 `Expense` 增加内部字段：

```text
ocr_draft_fields: JSON text
```

它只记录哪些业务字段当前仍然来自 OCR 草稿：

```text
amount_cents
merchant
category
expense_time
```

OCR 写入规则：

```text
字段为空或默认值 -> OCR 可以填入，并标记为 OCR 草稿字段。
字段已被 OCR 标记为草稿 -> 新一轮 OCR 可以纠正它。
字段已被用户 PATCH 修改 -> 从 OCR 草稿集合移除，后续 OCR 不再覆盖。
```

`raw_text` 和 `confidence` 是识别结果本身，可以随 OCR retry 更新。它们不是用户确认字段。

## Consequences

- OCR retry 可以纠正旧 OCR 草稿里的错误金额、商家、分类和消费时间。
- 用户手动确认过的字段不会被后续 OCR 覆盖。
- OCR 仍然只更新 pending 草稿，不会自动确认入账。
- 重复检测仍然只提示，不自动删除或拒绝。
- Android 端不需要知道该内部字段；普通用户只看到“识别建议”和待确认账单。
- 旧数据库通过 SQLite 轻量迁移自动增加列，不要求用户手动重建数据库。

## Tests

后端必须覆盖：

```text
1. OCR 第一次写入字段后，第二次 OCR 可以纠正这些草稿字段。
2. 用户 PATCH 修改过的字段不会被 OCR retry / recognize-text 覆盖。
3. OCR 纠错后状态仍然是 pending。
4. OCR 纠错不会设置 confirmed_at。
```

当前测试入口：

```text
backend/tests/test_api_contract.py
```

