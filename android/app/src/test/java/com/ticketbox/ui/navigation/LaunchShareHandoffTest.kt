package com.ticketbox.ui.navigation

import com.ticketbox.data.repository.LogicalSessionBinding
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

internal class LaunchShareHandoffTest {
    @Test
    fun twoSelectionsKeepTheirOwnKeysAndConsumeOnlyAfterAcceptance() {
        val state = LaunchActionState()
        val first = share("first", "a", "b")
        val second = share("second", "c", "d")
        state.post(first)
        state.post(second)

        assertEquals(first, state.pending)
        assertTrue(state.beginUpload(first, binding()))
        assertEquals(first, state.pending)
        state.finishUpload(first, accepted = true)
        assertEquals(second, state.pending)
        assertEquals(second, state.consume(second))
        assertNull(state.consume())
    }

    @Test
    fun aHotShareAndARepeatedHandoffCannotChangeTheAcceptingOriginal() {
        val state = LaunchActionState()
        val first = share("first", "a", "b")
        val second = share("second", "c")
        state.post(first)
        assertTrue(state.beginUpload(first, binding()))
        state.post(second)
        val repeated = share("first", "a", "b")
        state.post(repeated)

        assertEquals(listOf("a", "b"), first.selection.uris)
        assertEquals(binding(), first.selection.expectedBinding)
        assertEquals(binding(), repeated.selection.expectedBinding)
        assertFalse(state.beginUpload(first, binding()))
        state.finishUpload(first, accepted = true)
        assertEquals(second, state.pending)
        assertFalse(state.containsUpload(first.selection.batchId))
    }

    @Test
    fun failureNeedsExplicitRetryAndRestoreKeepsTheOriginalBindingAndBody() {
        val state = LaunchActionState()
        val first = share("first", "a", "b")
        state.post(first)
        assertTrue(state.beginUpload(first, binding()))
        state.finishUpload(first, accepted = false)
        assertFalse(state.beginUpload(first, binding()))

        val restored = LaunchActionState.restore(state.snapshot())
        val original = restored.pending as LaunchAction.UploadSharedImages
        assertEquals(first.selection.batchId, original.selection.batchId)
        assertEquals(first.selection.uris, original.selection.uris)
        assertEquals(binding(), original.selection.expectedBinding)
        assertFalse(restored.beginUpload(original, binding()))
        restored.retryUpload()
        assertTrue(restored.beginUpload(original, binding().copy(ledgerId = "ledger-b")))
        assertEquals(binding(), original.selection.expectedBinding)
        restored.finishUpload(original, accepted = false)
        restored.cancelUploadSelection()
        assertNull(restored.pending)
    }

    @Test
    fun activityAcknowledgesOnlyOneOriginalAndRestoresAnUncertainAcceptance() {
        val first = share("first", "a", "b").selection
        first.freezeBinding(binding())
        val second = share("second", "c").selection
        val requests = mergeLaunchRequest(listOf(first), second)
        val restored = requests.map { restoreLaunchRequest(it.savedFields()) }

        assertEquals(listOf(first.batchId, second.batchId), restored.map { (it as LaunchIntentRequest.ShareImages).batchId })
        assertEquals(binding(), (restored.first() as LaunchIntentRequest.ShareImages).expectedBinding)
        assertEquals(listOf(second), remainingLaunchRequest(restored, first))
        assertEquals(listOf(second), remainingLaunchRequest(listOf(second), first))
        assertTrue(remainingLaunchRequest(listOf(second), second).isEmpty())
    }

    @Test
    fun navigationKeepsItsRoutingWithoutDiscardingAnUnacceptedShare() {
        val first = share("first", "a")
        val navigate = LaunchIntentRequest.Navigate(ShortcutTarget.ManualEntry)
        assertEquals(listOf(navigate, first.selection), mergeLaunchRequest(listOf(first.selection), navigate))
        val state = LaunchActionState()
        state.post(first)
        state.post(LaunchAction.OpenImagePicker)
        state.post(LaunchAction.OpenManualEntry)
        assertEquals(LaunchAction.OpenManualEntry, state.consume())
        assertEquals(first, state.pending)
    }

    private fun share(name: String, vararg uris: String) = LaunchAction.UploadSharedImages(
        LaunchIntentRequest.ShareImages(java.util.UUID.nameUUIDFromBytes(name.toByteArray()).toString(), uris.toList()),
    )

    private fun binding() = LogicalSessionBinding("https://family.example", "ledger-a", "original-owner", "session", "revision")
}
