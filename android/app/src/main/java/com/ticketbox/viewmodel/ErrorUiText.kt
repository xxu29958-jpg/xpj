package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.UiText

/**
 * ADR-0044 (纯 ②): map a repository failure to a [UiText] in the presentation
 * layer. A known backend error code resolves to its `R.string.error_*`; an
 * unknown/absent code falls back to the (already-resolved) exception message as
 * [UiText.Raw] — and finally a generic string. This moves the code→copy decision
 * out of the data layer (§1).
 *
 * Migration note: while the migration is in progress, repositories still resolve
 * a Chinese message into [RepositoryException.message] (the un-migrated VMs read
 * it). Migrated VMs call this and prefer the code → `R.string`; the resolved
 * message is only used as the Raw fallback for un-coded failures. Once every VM
 * is migrated, the resolution can be dropped from the data layer.
 */
fun Throwable.toUiText(): UiText = toUiText(R.string.error_generic)

/** As [toUiText] but with a screen-specific [fallback] when the failure carries
 *  no known code and no message (preserves each screen's prior fallback copy). */
fun Throwable.toUiText(@StringRes fallback: Int): UiText {
    val code = (this as? RepositoryException)?.errorCode?.trim()
    errorCodeStringRes(code)?.let { return UiText.res(it) }
    val raw = message?.trim().orEmpty()
    return if (raw.isNotEmpty()) UiText.raw(raw) else UiText.res(fallback)
}

@StringRes
private fun errorCodeStringRes(code: String?): Int? = when (code) {
    "invalid_token" -> R.string.error_invalid_token
    "legacy_auth_removed" -> R.string.error_legacy_auth_removed
    "invalid_pairing_code" -> R.string.error_invalid_pairing_code
    "rate_limited" -> R.string.error_rate_limited
    "file_too_large" -> R.string.error_file_too_large
    "unsupported_file_type" -> R.string.error_unsupported_file_type
    "expense_not_found" -> R.string.error_expense_not_found
    "amount_required" -> R.string.error_amount_required
    "amount_invalid" -> R.string.error_amount_invalid
    "currency_not_supported" -> R.string.error_currency_not_supported
    "exchange_rate_required" -> R.string.error_exchange_rate_required
    "exchange_rate_pending" -> R.string.error_exchange_rate_pending
    "exchange_rate_invalid" -> R.string.error_exchange_rate_invalid
    "exchange_rate_base_currency" -> R.string.error_exchange_rate_base_currency
    "image_not_found" -> R.string.error_image_not_found
    "rule_not_found" -> R.string.error_rule_not_found
    "rule_in_use" -> R.string.error_rule_in_use
    "permission_denied" -> R.string.error_permission_denied
    "merchant_alias_not_found" -> R.string.error_merchant_alias_not_found
    "merchant_alias_conflict" -> R.string.error_merchant_alias_conflict
    "tag_not_found" -> R.string.error_tag_not_found
    "tag_conflict" -> R.string.error_tag_conflict
    "tag_undo_not_found" -> R.string.error_tag_undo_not_found
    "recurring_candidate_not_found" -> R.string.error_recurring_candidate_not_found
    "recurring_item_not_found" -> R.string.error_recurring_item_not_found
    "recurring_frequency_invalid" -> R.string.error_recurring_frequency_invalid
    "recurring_status_invalid" -> R.string.error_recurring_status_invalid
    "recurring_item_archived" -> R.string.error_recurring_item_archived
    "notification_source_invalid" -> R.string.error_notification_source_invalid
    "server_error" -> R.string.error_server_error
    "invalid_request" -> R.string.error_invalid_request
    "idempotency_key_required" -> R.string.error_idempotency_key_required
    "idempotency_key_in_progress" -> R.string.error_idempotency_key_in_progress
    "idempotency_key_reused" -> R.string.error_idempotency_key_reused
    "route_not_found" -> R.string.error_route_not_found
    "method_not_allowed" -> R.string.error_method_not_allowed
    // Audit #17: bill-split invitation flow + task codes were unmapped, so a
    // routine TOCTOU 409 fell through to each screen's generic fallback copy.
    "invitation_not_found" -> R.string.error_invitation_not_found
    "invitation_not_yours" -> R.string.error_invitation_not_yours
    "invitation_not_acceptable" -> R.string.error_invitation_not_acceptable
    "invitation_not_cancellable" -> R.string.error_invitation_not_cancellable
    "invitation_expired" -> R.string.error_invitation_expired
    "split_invitation_already_pending" -> R.string.error_split_invitation_already_pending
    "not_found" -> R.string.error_not_found
    "task_not_found" -> R.string.error_task_not_found
    else -> null
}
