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
private fun errorCodeStringRes(code: String?): Int? = code?.let(errorCodeStringResByCode::get)

private val errorCodeStringResByCode = mapOf(
    "invalid_token" to R.string.error_invalid_token,
    "legacy_auth_removed" to R.string.error_legacy_auth_removed,
    "invalid_pairing_code" to R.string.error_invalid_pairing_code,
    "device_recovery_platform_mismatch" to R.string.error_device_recovery_platform_mismatch,
    "rate_limited" to R.string.error_rate_limited,
    // Pending intercepts this code to offer retained-image retry; this is the fallback.
    "enrichment_capacity_full" to R.string.error_enrichment_capacity_full,
    "file_too_large" to R.string.error_file_too_large,
    "unsupported_file_type" to R.string.error_unsupported_file_type,
    "expense_not_found" to R.string.error_expense_not_found,
    "amount_required" to R.string.error_amount_required,
    "amount_invalid" to R.string.error_amount_invalid,
    "currency_not_supported" to R.string.error_currency_not_supported,
    "exchange_rate_required" to R.string.error_exchange_rate_required,
    "exchange_rate_pending" to R.string.error_exchange_rate_pending,
    "exchange_rate_invalid" to R.string.error_exchange_rate_invalid,
    "exchange_rate_base_currency" to R.string.error_exchange_rate_base_currency,
    "image_not_found" to R.string.error_image_not_found,
    "rule_not_found" to R.string.error_rule_not_found,
    "rule_in_use" to R.string.error_rule_in_use,
    "permission_denied" to R.string.error_permission_denied,
    "merchant_alias_not_found" to R.string.error_merchant_alias_not_found,
    "merchant_alias_conflict" to R.string.error_merchant_alias_conflict,
    "merchant_catalog_not_found" to R.string.error_merchant_catalog_not_found,
    "tag_not_found" to R.string.error_tag_not_found,
    "tag_conflict" to R.string.error_tag_conflict,
    "tag_undo_not_found" to R.string.error_tag_undo_not_found,
    "recurring_candidate_not_found" to R.string.error_recurring_candidate_not_found,
    "recurring_item_not_found" to R.string.error_recurring_item_not_found,
    "recurring_item_conflict" to R.string.error_recurring_item_conflict,
    "recurring_item_no_changes" to R.string.error_recurring_item_no_changes,
    "recurring_merchant_required" to R.string.error_recurring_merchant_required,
    "recurring_frequency_invalid" to R.string.error_recurring_frequency_invalid,
    "recurring_status_invalid" to R.string.error_recurring_status_invalid,
    "recurring_item_archived" to R.string.error_recurring_item_archived,
    "notification_source_invalid" to R.string.error_notification_source_invalid,
    "server_error" to R.string.error_server_error,
    "invalid_request" to R.string.error_invalid_request,
    "idempotency_key_required" to R.string.error_idempotency_key_required,
    "idempotency_key_in_progress" to R.string.error_idempotency_key_in_progress,
    "idempotency_key_reused" to R.string.error_idempotency_key_reused,
    "route_not_found" to R.string.error_route_not_found,
    "method_not_allowed" to R.string.error_method_not_allowed,
    // Audit #17: bill-split invitation flow + task codes were unmapped, so a
    // routine TOCTOU 409 fell through to each screen's generic fallback copy.
    "invitation_not_found" to R.string.error_invitation_not_found,
    "invitation_not_yours" to R.string.error_invitation_not_yours,
    "invitation_not_acceptable" to R.string.error_invitation_not_acceptable,
    "invitation_not_cancellable" to R.string.error_invitation_not_cancellable,
    "invitation_expired" to R.string.error_invitation_expired,
    "split_invitation_already_pending" to R.string.error_split_invitation_already_pending,
    // ADR-0029 拆账发起（批 13）：发起 sheet 可能命中的 split_* 码。后端虽都带 message，
    // 但用户面文案改走 App 资源以便端内可控（split_receiver_invalid 尤其需要更人话）。
    "split_receiver_invalid" to R.string.error_split_receiver_invalid,
    "split_amount_invalid" to R.string.error_split_amount_invalid,
    "split_amount_exceeds_parent" to R.string.error_split_amount_exceeds_parent,
    "split_total_exceeds_parent" to R.string.error_split_total_exceeds_parent,
    "split_parent_amount_missing" to R.string.error_split_parent_amount_missing,
    "not_found" to R.string.error_not_found,
    "task_not_found" to R.string.error_task_not_found,
)
