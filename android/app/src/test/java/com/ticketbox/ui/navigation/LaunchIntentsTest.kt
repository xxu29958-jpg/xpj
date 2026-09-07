package com.ticketbox.ui.navigation

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertNotNull
import kotlin.test.assertNotEquals
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
            shared = LaunchSharedContent(listOf("content://media/1")),
            shortcutTarget = "manual_entry",
        )

        assertEquals(LaunchIntentRequest.Navigate(ShortcutTarget.ManualEntry), request)
    }

    @Test
    fun singleImageSendResolvesToShareWithOneUri() {
        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND,
            mimeType = "image/png",
            shared = LaunchSharedContent(listOf("content://media/42"), batchId = ORIGINAL_UPLOAD_BATCH_ID),
            shortcutTarget = null,
        )

        assertEquals(LaunchIntentRequest.ShareImages(ORIGINAL_UPLOAD_BATCH_ID, listOf("content://media/42")), request)
    }

    @Test
    fun sendMultipleDeduplicatesAndPreservesOrder() {
        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND_MULTIPLE,
            mimeType = "image/*",
            shared = LaunchSharedContent(
                listOf("content://a", " content://b ", "content://a", "", null, "content://c"),
                batchId = ORIGINAL_UPLOAD_BATCH_ID,
            ),
            shortcutTarget = null,
        )

        assertEquals(
            LaunchIntentRequest.ShareImages(ORIGINAL_UPLOAD_BATCH_ID, listOf("content://a", "content://b", "content://c")),
            request,
        )
    }

    @Test
    fun shareWithoutAnyUriIsIgnored() {
        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND,
            mimeType = "image/jpeg",
            shared = LaunchSharedContent(listOf(null, "", "   ")),
            shortcutTarget = null,
        )

        assertNull(request)
    }

    @Test
    fun nonImageMimeShareIsRejected() {
        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND,
            mimeType = "application/pdf",
            shared = LaunchSharedContent(listOf("content://doc/1")),
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
            shared = LaunchSharedContent(listOf("content://media/7"), batchId = ORIGINAL_UPLOAD_BATCH_ID),
            shortcutTarget = null,
        )

        assertEquals(LaunchIntentRequest.ShareImages(ORIGINAL_UPLOAD_BATCH_ID, listOf("content://media/7")), request)
    }

    @Test
    fun plainLaunchWithNoActionOrShortcutIsNull() {
        assertNull(
            resolveLaunchIntent(
                action = "android.intent.action.MAIN",
                mimeType = null,
                shared = LaunchSharedContent(emptyList()),
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

    @Test
    fun anotherShareOfTheSameUriGetsAnotherOriginalIdentity() {
        val first = resolveLaunchIntent(LaunchIntentActions.ACTION_SEND, "image/png", LaunchSharedContent(listOf("content://same")), null)
            as LaunchIntentRequest.ShareImages
        val second = resolveLaunchIntent(LaunchIntentActions.ACTION_SEND, "image/png", LaunchSharedContent(listOf("content://same")), null)
            as LaunchIntentRequest.ShareImages
        assertNotEquals(first.batchId, second.batchId)
        assertEquals(first.uris, second.uris)
    }
}

private const val ORIGINAL_UPLOAD_BATCH_ID = "614ba8eb-253d-4cfa-b59e-c9686c23a843"

class FamilyInvitationLaunchIntentsTest {

    @Test
    fun plainTextInvitationShareRoutesToJoinWithoutExposingTokenInNavigationState() {
        val shared = "https://family.example.com/web/auth/join#invite=inv_abc-123_DEF"

        val request = resolveLaunchIntent(
            action = LaunchIntentActions.ACTION_SEND,
            mimeType = "text/plain",
            shared = LaunchSharedContent(emptyList(), text = shared),
            shortcutTarget = null,
        )

        assertEquals(LaunchIntentRequest.JoinInvitation(shared), request)
        val parsed = assertNotNull(parseFamilyInvitationLink(shared))
        assertEquals("inv_abc-123_DEF", parsed.inviteToken)
        assertEquals("https://family.example.com", parsed.serverUrl)
        assertEquals("family.example.com", parsed.hostLabel)
    }

    @Test
    fun textShareWithInvalidContentStillRoutesToJoinForExplicitFeedback() {
        assertEquals(
            LaunchIntentRequest.JoinInvitation("这不是邀请"),
            resolveLaunchIntent(
                action = LaunchIntentActions.ACTION_SEND,
                mimeType = "text/plain",
                shared = LaunchSharedContent(emptyList(), text = "这不是邀请"),
                shortcutTarget = null,
            ),
        )
    }

    @Test
    fun invitationLinkParserRejectsUntrustedOrAmbiguousLocations() {
        val invalidLinks = listOf(
            "http://family.example.com/web/auth/join#invite=inv_token",
            "https://user@family.example.com/web/auth/join#invite=inv_token",
            "https://family.example.com/other#invite=inv_token",
            "https://family.example.com/web/auth/join?invite=inv_token",
            "https://family.example.com/web/auth/join#invite=inv_one&invite=inv_two",
            "https://family.example.com/web/auth/join#invite=${"x".repeat(129)}",
        )

        invalidLinks.forEach { link -> assertNull(parseFamilyInvitationLink(link), link) }
    }
}
