# B12 return adapter 消费者

扫描：TRACED
当前能力：reject 回原期次 **CHANGED**（工作区）；payment_id 焦点仍见 B10
修复：reject 已接到同一 `resolve_return_to`；B10 仍 PROPOSED
证据：#405 `web_reject` 在 `return_to==recurring_occurrence` 时保留 origin；AUDIT_BASE L173–180 曾写死 `/web/pending`。[Scan B](a6d2345b-9b89-41b5-b6e8-f7f1df6bc52f) 此边主控确认。

## 现网（改后）

`web_expense_lifecycle.py` `web_reject`：origin 为 recurring_occurrence 时 `resolve_return_to` + `return_context_params`；否则仍回 pending（保留 undo banner 合同）。

反例：`test_web_reject_from_recurring_occurrence_returns_to_the_original_period`。

## Owner

未第二套 adapter。未知 `return_to` 仍 fallback。
