package com.ticketbox.data.repository

import android.util.Log

/** Generic repository failure that callers can map to UI error messages. */
class RepositoryException(message: String) : RuntimeException(message)

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
        "recurring_candidate_not_found" -> "没有找到可确认的固定支出候选。"
        "recurring_item_not_found" -> "固定支出不存在。"
        "recurring_frequency_invalid" -> "固定支出设置不正确。"
        "recurring_status_invalid" -> "固定支出设置不正确。"
        "recurring_item_archived" -> "固定支出已归档，不能继续修改。"
        "notification_source_invalid" -> "通知来源暂不支持。"
        "server_error" -> "暂时处理不了，请稍后再试。"
        "invalid_request" -> "请求参数不正确。"
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
