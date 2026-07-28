package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class CurrencyCodeTest {

    @Test
    fun fromStorageKeyOrNullParsesKnownCodesStrictly() {
        // PR#255 R7-2：严格变体只认支持集（大小写/空白归一化后与 fromStorageKey 一致）。
        assertEquals(CurrencyCode.CNY, CurrencyCode.fromStorageKeyOrNull("CNY"))
        assertEquals(CurrencyCode.JPY, CurrencyCode.fromStorageKeyOrNull("jpy"))
        assertEquals(CurrencyCode.KRW, CurrencyCode.fromStorageKeyOrNull(" KRW "))
    }

    @Test
    fun fromStorageKeyOrNullRejectsUnknownBlankAndNull() {
        // 未知码归 null（写路径 fail closed 用），不做 fromStorageKey 的静默 Default 回落。
        assertNull(CurrencyCode.fromStorageKeyOrNull("XXX"))
        assertNull(CurrencyCode.fromStorageKeyOrNull(""))
        assertNull(CurrencyCode.fromStorageKeyOrNull("  "))
        assertNull(CurrencyCode.fromStorageKeyOrNull(null))
    }

    @Test
    fun fromStorageKeyKeepsLegacyDefaultFallback() {
        // 既有语义不动（读路径回落 Default）：未知/空白 → CNY。
        assertEquals(CurrencyCode.CNY, CurrencyCode.fromStorageKey("XXX"))
        assertEquals(CurrencyCode.CNY, CurrencyCode.fromStorageKey(null))
    }
}
