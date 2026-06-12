package com.ticketbox.ui.navigation

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * W1：系统分享 / 启动器 shortcut 的入口裁决逻辑（[resolveLaunchIntent] /
 * [resolveShortcutTarget]）的纯 JVM 单测。这层不碰 android.net.Uri / Intent，
 * 全部用字符串输入，故 Robolectric-free 可跑。
 */
class LaunchIntentsTest {

    @Test
    fun shortcutTargetTakesPriorityOverShare() {
        // 即便同时带分享 action+图，显式 shortcut 目标优先（确定性最强）。
        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND,
            mimeType = "image/jpeg",
            streamUris = listOf("content://media/1"),
            shortcutTarget = "manual_entry",
        )

        assertEquals(LaunchIntentRequest.Navigate(ShortcutTarget.ManualEntry), request)
    }

    @Test
    fun singleImageSendResolvesToShareWithOneUri() {
        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND,
            mimeType = "image/png",
            streamUris = listOf("content://media/42"),
            shortcutTarget = null,
        )

        assertEquals(LaunchIntentRequest.ShareImages(listOf("content://media/42")), request)
    }

    @Test
    fun sendMultipleDeduplicatesAndPreservesOrder() {
        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND_MULTIPLE,
            mimeType = "image/*",
            streamUris = listOf("content://a", " content://b ", "content://a", "", null, "content://c"),
            shortcutTarget = null,
        )

        assertEquals(
            LaunchIntentRequest.ShareImages(listOf("content://a", "content://b", "content://c")),
            request,
        )
    }

    @Test
    fun shareWithoutAnyUriIsIgnored() {
        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND,
            mimeType = "image/jpeg",
            streamUris = listOf(null, "", "   "),
            shortcutTarget = null,
        )

        assertNull(request)
    }

    @Test
    fun nonImageMimeShareIsRejected() {
        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND,
            mimeType = "application/pdf",
            streamUris = listOf("content://doc/1"),
            shortcutTarget = null,
        )

        assertNull(request)
    }

    @Test
    fun nullMimeShareIsAcceptedTrustingTheDeclaredFilter() {
        // 少数来源不带 MIME；声明的 image/* filter 已是第一道门，type=null 放行。
        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND,
            mimeType = null,
            streamUris = listOf("content://media/7"),
            shortcutTarget = null,
        )

        assertEquals(LaunchIntentRequest.ShareImages(listOf("content://media/7")), request)
    }

    @Test
    fun plainLaunchWithNoActionOrShortcutIsNull() {
        assertNull(
            resolveLaunchIntent(
                action = "android.intent.action.MAIN",
                mimeType = null,
                streamUris = emptyList(),
                shortcutTarget = null,
            ),
        )
    }

    @Test
    fun allThreeShortcutIdsMapToTargets() {
        assertEquals(ShortcutTarget.UploadReceipt, resolveShortcutTarget("upload_receipt"))
        assertEquals(ShortcutTarget.ManualEntry, resolveShortcutTarget("manual_entry"))
        assertEquals(ShortcutTarget.ReviewPending, resolveShortcutTarget("review_pending"))
    }

    @Test
    fun shortcutIdMatchingIsTrimmedAndExact() {
        assertEquals(ShortcutTarget.UploadReceipt, resolveShortcutTarget("  upload_receipt  "))
        assertNull(resolveShortcutTarget("Upload_Receipt"))
        assertNull(resolveShortcutTarget("unknown_target"))
        assertNull(resolveShortcutTarget(""))
        assertNull(resolveShortcutTarget(null))
    }

    @Test
    fun shortcutTargetIdsMatchEnumContract() {
        // shortcuts.xml 的 extra value 是这些字面量；钉住值与枚举不漂移。
        assertEquals("upload_receipt", ShortcutTarget.UploadReceipt.id)
        assertEquals("manual_entry", ShortcutTarget.ManualEntry.id)
        assertEquals("review_pending", ShortcutTarget.ReviewPending.id)
        assertTrue(ShortcutTarget.entries.size == 3)
    }
}
