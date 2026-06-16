package com.ticketbox.notification

import java.security.MessageDigest

/**
 * 这条通知的稳定**每次投递身份**：`SHA-256( StatusBarNotification.key | postTime )` 的 64 位十六进制。
 *
 * - 含 `postTime` → 个别 App 复用同一通知槽承载不同事件（同 `sbn.key`、新 `postTime`）时各算一笔，
 *   不会因内容相同被吞（codex PR#20 P2#1：本地去重器 + 后端幂等键都靠这个身份区分两笔真账）。
 * - 同一逻辑投递被重发（监听器重新绑定读 active notifications：同 key 同 postTime）→ 同 hash → 仍去重。
 * - 定长 64 hex → 永远落在后端 `notification_key` 长度上限内（长 key 不会 422 让自动捕获静默失败，
 *   codex PR#20 P2#2），且**原始 key（含 App 私有 tag 串）不离开设备**——只把不可逆 hash 透传给后端（隐私）。
 */
internal fun notificationIdentityKey(rawKey: String?, postTimeMillis: Long): String {
    val material = "${rawKey.orEmpty()}|$postTimeMillis"
    return MessageDigest.getInstance("SHA-256")
        .digest(material.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }
}
