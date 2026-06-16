package com.ticketbox.notification

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class NotificationIdentityTest {
    @Test
    fun sameKeyAndPostTimeProduceSameIdentity() {
        // 同一逻辑投递被重发（监听器重新绑定读 active notifications：同 key 同 postTime）→ 同身份 → 仍去重。
        assertEquals(
            notificationIdentityKey("0|com.tencent.mm|7|null|10", 1_700_000_000_000L),
            notificationIdentityKey("0|com.tencent.mm|7|null|10", 1_700_000_000_000L),
        )
    }

    @Test
    fun sameKeyDifferentPostTimeProduceDifferentIdentity() {
        // codex PR#20 P2#1：复用同一通知槽（同 sbn.key）承载第二笔真账时 postTime 变 → 必须是不同身份，
        // 否则同分钟同金额的第二笔被静默吞掉。
        assertNotEquals(
            notificationIdentityKey("0|com.tencent.mm|7|null|10", 1_700_000_000_000L),
            notificationIdentityKey("0|com.tencent.mm|7|null|10", 1_700_000_060_000L),
        )
    }

    @Test
    fun differentRawKeySamePostTimeProduceDifferentIdentity() {
        // 锁住 rawKey 是 material 的承重轴：若未来 edit 把 rawKey 从 material 去掉、只剩 postTime,
        // 两条同一毫秒投递的不同通知会撞同一身份 → 这条会失败,提前拦住。
        assertNotEquals(
            notificationIdentityKey("0|com.tencent.mm|7|null|10", 1_700_000_000_000L),
            notificationIdentityKey("0|com.eg.android.alipaygphone|7|null|10", 1_700_000_000_000L),
        )
    }

    @Test
    fun identityIsBounded64HexCharsForArbitrarilyLongRawKey() {
        // codex PR#20 P2#2：定长 64 hex → 永远落在后端 notification_key 上限内，原始(可能超长含私有 tag)key 不外传。
        val longRawKey = "0|com.example|1|" + "t".repeat(4_000) + "|10"
        val identity = notificationIdentityKey(longRawKey, 1_700_000_000_000L)
        assertEquals(64, identity.length)
        assertTrue(identity.all { it in "0123456789abcdef" })
    }

    @Test
    fun nullRawKeyIsHandledAndStillBounded() {
        val identity = notificationIdentityKey(null, 1_700_000_000_000L)
        assertEquals(64, identity.length)
    }
}
