package com.ticketbox.data.repository

import android.util.Log

/**
 * Generic repository failure that callers can map to UI error messages.
 *
 * [errorCode] carries the backend's machine-readable code (e.g. `expense_not_found`,
 * `permission_denied`) when [NetworkErrorHandler.parseErrorMessage] decoded one;
 * it's null for transport/JSON failures and for messages synthesized client-side.
 * VMs branching on specific backend semantics (e.g. ADR-0038 undo's 404-vs-network
 * distinction) should match on [errorCode], not on the localized [message].
 */
class RepositoryException(
    message: String,
    val errorCode: String? = null,
    val conflict: RepositoryConflictDetails = RepositoryConflictDetails(),
) : RuntimeException(message) {
    val conflictTagPublicId: String? get() = conflict.tag.publicId
    val conflictTagRowVersion: Long? get() = conflict.tag.rowVersion
    val conflictMerchantPublicId: String? get() = conflict.merchant.publicId
    val conflictMerchantRowVersion: Long? get() = conflict.merchant.rowVersion
    val conflictMerchantDisplayName: String? get() = conflict.merchant.displayName
    val conflictMerchantStatus: String? get() = conflict.merchant.status
    val conflictMerchantDeleted: Boolean? get() = conflict.merchant.deleted
    val conflictAliasPublicId: String? get() = conflict.alias.publicId
    val conflictAliasRowVersion: Long? get() = conflict.alias.rowVersion
    val conflictAliasEnabled: Boolean? get() = conflict.alias.enabled
    val conflictAliasDeleted: Boolean? get() = conflict.alias.deleted
}

data class RepositoryConflictDetails(
    // ADR-0043 契约 5: present only on a `tag_conflict` — the colliding tag's fresh
    // server identity, so a rename can steer into a merge without reusing a stale
    // local OCC token.
    val tag: TagConflictDetails = TagConflictDetails(),
    // ADR-0054: present when a merchant-catalog key collision can be resolved
    // by a user-confirmed merge. Mirrors the flat ErrorDto fields.
    val merchant: MerchantConflictDetails = MerchantConflictDetails(),
    val alias: AliasConflictDetails = AliasConflictDetails(),
)

data class TagConflictDetails(
    val publicId: String? = null,
    val rowVersion: Long? = null,
)

data class MerchantConflictDetails(
    val publicId: String? = null,
    val rowVersion: Long? = null,
    val displayName: String? = null,
    val status: String? = null,
    val deleted: Boolean? = null,
)

data class AliasConflictDetails(
    val publicId: String? = null,
    val rowVersion: Long? = null,
    val enabled: Boolean? = null,
    val deleted: Boolean? = null,
)

/** Maps backend error codes to user-facing Chinese strings.
 *  Shared by every Repository in this module — kept out of the per-protocol
 *  files so it's the single source of truth for error text. */
internal fun backendErrorUserMessage(errorCode: String, serverMessage: String): String {
    return when (errorCode.trim()) {
        "invalid_token" -> "绑定已失效，请重新绑定账本。"
        "legacy_auth_removed" -> "请使用新版绑定方式。"
        // Backend collapses expired / used / invalid into one code (v1.1, to
        // avoid revealing whether a code existed); guide the user to re-obtain.
        "invalid_pairing_code" -> "绑定码无效，请重新获取。"
        // §4 generic throttle code (currently emitted by the pairing-attempt
        // limiter, 429); also the right copy when a CDN/Worker 429 carries it.
        "rate_limited" -> "尝试太频繁，请稍后再试。"
        "file_too_large" -> "上传文件超过大小限制。"
        "unsupported_file_type" -> "不支持的图片格式。"
        "expense_not_found" -> "账单不存在。"
        "amount_required" -> "请先填写金额。"
        "amount_invalid" -> "金额格式不正确。"
        "currency_not_supported" -> "暂不支持这个币种。"
        "exchange_rate_required" -> "请先填写这一天的汇率。"
        "exchange_rate_pending" -> "汇率还没同步完成，稍后再确认。"
        "exchange_rate_invalid" -> "汇率格式不正确。"
        "exchange_rate_base_currency" -> "人民币是基准币种，不需要维护汇率。"
        "image_not_found" -> "图片不存在。"
        "rule_not_found" -> "分类规则不存在。"
        "rule_in_use" -> "分类规则仍在使用，不能删除。"
        "permission_denied" -> "当前角色为只读，无法修改账本。"
        "merchant_alias_not_found" -> "商家别名不存在。"
        "merchant_alias_conflict" -> "商家别名已指向其他商家。"
        "merchant_catalog_not_found" -> "商家不存在或已删除。"
        // ADR-0043 tag management. tag_conflict steers the user to 合并 (契约 5);
        // tag_undo_not_found is the elapsed 5-minute undo window.
        "tag_not_found" -> "标签不存在或已删除。"
        "tag_conflict" -> "标签名已被占用，请改用合并。"
        "tag_undo_not_found" -> "撤销窗口已过，无法撤销。"
        "recurring_candidate_not_found" -> "没有找到可确认的固定支出候选。"
        "recurring_item_not_found" -> "固定支出不存在。"
        "recurring_frequency_invalid" -> "固定支出设置不正确。"
        "recurring_status_invalid" -> "固定支出设置不正确。"
        "recurring_item_archived" -> "固定支出已归档，不能继续修改。"
        "notification_source_invalid" -> "通知来源暂不支持。"
        "server_error" -> "暂时处理不了，请稍后再试。"
        "invalid_request" -> "请求参数不正确。"
        // ADR-0042 request idempotency (PATCH expense). Protocol-level — the
        // client always mints a key, so these should never reach the user; the
        // text stays jargon-free (no "幂等键") per ENGINEERING_RULES §10 in case
        // the direct path ever surfaces one.
        "idempotency_key_required" -> "操作未能完成，请重试。"
        "idempotency_key_in_progress" -> "操作正在处理，请稍后再试。"
        "idempotency_key_reused" -> "操作已处理，请勿重复提交。"
        "route_not_found" -> "账本版本过旧，请重启电脑上的小票夹后再试。"
        "method_not_allowed" -> "操作方式不正确，请更新 App 后再试。"
        else -> serverMessage.trim().ifBlank { "操作失败。" }
    }
}

internal fun logNetworkWarning(message: String, error: Throwable) {
    // ADR-0038 PR-2g.3 round-8 / codex round-9 follow-up: catch
    // Exception, NOT Throwable. android.util.Log is an unmocked
    // stub in pure-JVM unit tests and throws ``Method w not
    // mocked``; swallowing it here keeps tests honest (they can
    // still assert on the Result the caller returns) while
    // production behaviour is unchanged. JVM-level Errors (OOM /
    // StackOverflow / LinkageError) propagate up by design —
    // same principle as [OutboxDrainEngine]'s round-5 fix.
    try {
        Log.w("TicketboxNetwork", message, error)
    } catch (_: Exception) {
        // logging backend fault / JVM unit-test Android Log stub
    }
}

internal fun defaultAndroidDeviceName(): String {
    val manufacturer = android.os.Build.MANUFACTURER.orEmpty().trim()
    val model = android.os.Build.MODEL.orEmpty().trim()
    return listOf(manufacturer, model)
        .filter { it.isNotBlank() }
        .joinToString(" ")
        .ifBlank { "Android 设备" }
}

internal fun String.toFileNameSegment(): String {
    return trim()
        .replace(Regex("[\\\\/:*?\"<>|\\s]+"), "_")
        .take(40)
        .ifBlank { "tag" }
}
