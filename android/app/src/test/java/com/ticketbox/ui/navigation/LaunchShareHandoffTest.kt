package com.ticketbox.ui.navigation

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

internal class LaunchShareHandoffTest {
    @Test
    fun twoPostsBeforeTheRouteRunsPreserveOrderAndConsumeOnce() {
        val state = LaunchActionState()
        state.post(LaunchAction.UploadSharedImages(listOf("a", "b")))
        state.post(LaunchAction.UploadSharedImages(listOf("c", "d")))

        assertEquals(LaunchAction.UploadSharedImages(listOf("a", "b", "c", "d")), state.consume())
        assertNull(state.consume())
    }

    @Test
    fun aPostDuringAcceptanceLeavesOnlyTheUnacceptedTail() {
        val state = LaunchActionState()
        val first = LaunchAction.UploadSharedImages(listOf("a", "b"))
        state.post(first)
        val accepted = state.pending
        state.post(LaunchAction.UploadSharedImages(listOf("c")))

        assertEquals(first, state.consume(accepted))
        assertEquals(LaunchAction.UploadSharedImages(listOf("c")), state.consume())
        assertNull(state.consume())
    }

    @Test
    fun activityHotSharesKeepTheUnhandledPrefixUntilShellAcceptance() {
        val first = LaunchIntentRequest.ShareImages(listOf("a", "b"))
        val second = LaunchIntentRequest.ShareImages(listOf("c"))
        val merged = mergeLaunchRequest(first, second)
        assertEquals(LaunchIntentRequest.ShareImages(listOf("a", "b", "c")), merged)

        val remaining = remainingLaunchRequest(merged, first)
        assertEquals(second, remaining)
        assertNull(remainingLaunchRequest(remaining, requireNotNull(remaining)))
    }

    @Test
    fun nonShareVariantsKeepTheirExistingRouting() {
        val navigate = LaunchIntentRequest.Navigate(ShortcutTarget.ManualEntry)
        assertEquals(navigate, mergeLaunchRequest(LaunchIntentRequest.ShareImages(listOf("a")), navigate))
        assertEquals(navigate, remainingLaunchRequest(navigate, LaunchIntentRequest.ShareImages(listOf("a"))))
        val state = LaunchActionState()
        state.post(LaunchAction.OpenImagePicker)
        state.post(LaunchAction.OpenManualEntry)
        assertEquals(LaunchAction.OpenManualEntry, state.consume())
    }
}
