package com.ticketbox.data.local

/**
 * ADR-0038 PR-2f: the catalogue of routes the offline outbox knows
 * how to replay. Persisted as ``wireValue`` so adding a new mutation
 * kind doesn't need a Room schema migration — unknown values map
 * to [Unknown] and the drain worker refuses to dequeue them (the
 * row stays ``PENDING`` until the app catches up with a new build).
 *
 * Mapping to backend routes (one-to-one with the v1.3 PR-2 mutate
 * surface that takes ``expected_row_version``):
 *
 *   PatchExpense                     PATCH  /api/expenses/{id}
 *   ConfirmExpense                   POST   /api/expenses/{id}/confirm
 *   RejectExpense                    POST   /api/expenses/{id}/reject
 *   MarkNotDuplicate                 POST   /api/expenses/{id}/mark-not-duplicate
 *   RetryOcr                         POST   /api/expenses/{id}/ocr/retry
 *   RecognizeText                    POST   /api/expenses/{id}/recognize-text
 *   ReplaceItems                     PUT    /api/expenses/{id}/items
 *   ReplaceSplits                    PUT    /api/expenses/{id}/splits
 *   AcknowledgeItemsMismatch         POST   /api/expenses/{id}/items/acknowledge-mismatch
 *   UpdateCategoryRule               PATCH  /api/rules/categories/{id}
 *   DeleteCategoryRule               DELETE /api/rules/categories/{id}
 *   UpdateMerchantAlias              PATCH  /api/merchants/aliases/{publicId}
 *   DeleteMerchantAlias              DELETE /api/merchants/aliases/{publicId}
 *   UpdateGoal                       PATCH  /api/goals/{publicId}
 *   UpdateIncomePlan                 PATCH  /api/income-plans/{publicId}
 *
 * Routes that legitimately don't take a token (creates / terminal
 * lifecycle / batch with its own preview_token) are NOT in the
 * outbox — they go through the normal online-only ApiService path.
 * See ``ALLOWLIST`` in ``backend/scripts/_audit_mutate_token_coverage.py``.
 */
enum class PendingMutationType(val wireValue: String) {
    PatchExpense("patch_expense"),
    ConfirmExpense("confirm_expense"),
    RejectExpense("reject_expense"),
    MarkNotDuplicate("mark_not_duplicate"),
    RetryOcr("retry_ocr"),
    RecognizeText("recognize_text"),
    ReplaceItems("replace_items"),
    ReplaceSplits("replace_splits"),
    AcknowledgeItemsMismatch("acknowledge_items_mismatch"),
    UpdateCategoryRule("update_category_rule"),
    DeleteCategoryRule("delete_category_rule"),
    UpdateMerchantAlias("update_merchant_alias"),
    DeleteMerchantAlias("delete_merchant_alias"),
    UpdateGoal("update_goal"),
    UpdateIncomePlan("update_income_plan"),
    Unknown("unknown");

    companion object {
        fun fromWire(value: String?): PendingMutationType {
            if (value == null) return Unknown
            return entries.firstOrNull { it.wireValue == value } ?: Unknown
        }
    }
}
