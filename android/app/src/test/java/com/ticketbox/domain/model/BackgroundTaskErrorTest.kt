package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * 8.3: [shouldGeneralizeTaskError] decides whether a backend task
 * ``error_message`` is safe to show verbatim or must fall back to the generic
 * copy (§10: no raw exception / English diagnostic in the user face).
 */
class BackgroundTaskErrorTest {
    @Test
    fun shortChineseMessagesAreShownVerbatim() {
        // Backend-authored, user-facing Chinese errors pass through untouched.
        assertFalse(shouldGeneralizeTaskError("缺少有效金额。"))
        assertFalse(shouldGeneralizeTaskError("这一行金额无法识别，已跳过。"))
        assertFalse(shouldGeneralizeTaskError("导入了 3 行，2 行有问题。"))
    }

    @Test
    fun englishAndStackLikeMessagesAreGeneralized() {
        // Real backend strings that must NOT leak to the UI.
        assertTrue(shouldGeneralizeTaskError("No handler registered for 'csv_import'."))
        assertTrue(shouldGeneralizeTaskError("CSV row insert failed; row was not imported."))
        assertTrue(shouldGeneralizeTaskError("ValueError: invalid literal for int()"))
        assertTrue(
            shouldGeneralizeTaskError(
                "Traceback (most recent call last):\n  File \"app.py\", line 42",
            ),
        )
        assertTrue(
            shouldGeneralizeTaskError(
                "Task heartbeat exceeded BACKGROUND_TASK_ORPHAN_GRACE_SECONDS; " +
                    "the worker that owned it is assumed dead.",
            ),
        )
    }

    @Test
    fun blankIsGeneralized() {
        assertTrue(shouldGeneralizeTaskError(""))
        assertTrue(shouldGeneralizeTaskError("   "))
    }

    @Test
    fun overlyLongChineseIsGeneralizedEvenWithoutStackMarkers() {
        // A Chinese-looking but pathologically long string is still a diagnostic
        // dump, not a clean user message — generalize it.
        val longChinese = "失败".repeat(BACKGROUND_TASK_ERROR_MAX_DISPLAY_LEN)
        assertTrue(longChinese.length > BACKGROUND_TASK_ERROR_MAX_DISPLAY_LEN)
        assertTrue(shouldGeneralizeTaskError(longChinese))
    }

    @Test
    fun chineseMessageThatEmbedsAStackFeatureIsGeneralized() {
        // "短中文 + 英文异常串" — the marker scan catches the embedded diagnostic
        // even though Chinese is present.
        assertTrue(shouldGeneralizeTaskError("导入失败：NullPointerException at row 5"))
    }
}
