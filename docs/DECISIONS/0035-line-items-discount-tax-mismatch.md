# 0035 Use line item kind enum for discounts, taxes, and service fees

- Status: proposed
- Date: 2026-05-23
- Decision makers: 项目维护者

## Context and Problem Statement

`ExpenseItem` 已在 v0.9 落地，覆盖商品行 OCR 草稿与用户编辑，跟 [Azure Document Intelligence Receipt][azure-di-receipt] `Items[]` 字段结构对齐。

但现实小票还有三类信息**仍无承载**：

- 行级负数（"优惠 -¥3" 整行扣减）
- 行级非商品金额（"服务费 ¥10" / "VAT ¥0.96"）
- items 总和与 expense 总价不一致（OCR 漏行 / 小票本身印错 / 用户编辑中间态）

问题：v1.0 该如何在不破坏现有 `ExpenseItem` API 的前提下表达这三类？

## Decision Drivers

- 与业界 receipt OCR 数据模型对齐（Azure DI / [Veryfi][veryfi-fields]）
- 不破坏现有 `replace_expense_items` 调用方
- aggregation（report / export）逻辑保持简单
- 跟 [[0021]] OCR draft 字段来源语义兼容
- 用户能 acknowledge "原小票就这样"，避免警告反复弹

## Considered Options

- Top-level tax + discount on `Expense` plus a `TaxDetails` child table (Azure DI v3 style)
- Add `kind` enum on `ExpenseItem` with rows for discounts, taxes, service fees (Veryfi line item type style)
- Hybrid: per-item `tax_amount` / `discount_amount` columns **and** independent kind rows
- Leave `ExpenseItem` unchanged; rely on free-text raw_text

## Decision Outcome

Chosen option: **Add `kind` enum on `ExpenseItem`**.

`ExpenseItem.kind` is one of `product / discount / tax / service_fee`. Discounts are negative `amount_cents`; products / taxes / service_fees are non-negative. Backend computes and stores `Expense.items_sum_status` (`matched / mismatch_known / mismatch_acknowledged / no_items`); users can mark `mismatch_acknowledged` when the receipt itself is wrong.

This follows the Veryfi line item type pattern, treats each printed row on the paper receipt as one database row, and lets `sum(amount_cents)` aggregate naturally without per-kind sign juggling.

## Consequences

Good:

- 现实小票"优惠 -¥3" / "服务费 +¥10" 有结构化承载
- `replace_expense_items` 接口不破坏（kind 默认 `product`）
- aggregation 自洽，`sum(amount_cents)` 不需要分类 join
- 跟 [Veryfi line item type][veryfi-fields] 字面对齐，跨产品迁移直觉一致

Bad:

- 跟 Azure DI v3 顶层 tax / discount 字段不直接映射；从 Azure 迁过来要 transform
- 行内 per-item tax（"苹果 ¥10 含税 ¥0.8"）必须拆成 product 行 + tax 行，OCR provider 要相应改造
- v1.0 不引入 [Azure DI v4 `TaxDetails.Rate`][azure-di-receipt] 字段，多税场景 rate 信息丢失

## Confirmation

- kind 与 amount sign 的双重 CHECK constraint 测试
- `items_sum_status` 4 态计算测试（含 product / discount / tax 组合）
- `mismatch_known → acknowledged` 状态迁移测试
- v0.9 → v1.0 backfill 测试：所有现存 item 默认 `kind=product`
- [[0031]] 迁移联动测试：`items_sum_status` backfill 一次性算完

## More Information

- [Azure Document Intelligence — Receipt prebuilt model][azure-di-receipt]
- [Veryfi Receipt OCR Data Extraction Fields][veryfi-fields]（line item type 枚举来源）
- [[0021]] OCR 草稿字段来源（item 级维持 boolean `is_ocr_draft`，本 ADR 不扩展为字段级）
- [[0015]] OCR Provider Pipeline（`ParsedReceiptItem` 加 `kind` 字段属于实现层）

[azure-di-receipt]: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/receipt
[veryfi-fields]: https://faq.veryfi.com/en/articles/5571268-data-extraction-fields-explained-for-receipts-invoices-api
