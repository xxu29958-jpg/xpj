package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.FakeTicketboxSettingsStore
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundTransform
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import com.ticketbox.data.local.TicketboxSettingsStore
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.test.runCurrent

@OptIn(ExperimentalCoroutinesApi::class)
class AppearanceBackgroundEditorTest {
    private val original = BackgroundSettings().withCustomImage("/private/first.image")
    private val draft = BackgroundSettings().withCustomImage("/private/second.image")
        .copy(transform = BackgroundTransform(scale = 2f, offsetY = 0.5f))

    @Test
    fun successfulApplyPublishesCompositionAndClosesEditor() = editorTest {
        val store = FakeTicketboxSettingsStore()
        store.saveBackgroundSettings(original)
        val images = FakeBackgroundImages()
        val vm = AppearanceViewModel(store, images)
        advanceUntilIdle()
        vm.editBackground(draft)

        vm.applyBackgroundDraft()
        advanceUntilIdle()

        assertEquals(draft, store.backgroundSettingsFlow.first())
        assertNull(vm.uiState.value.editor)
        assertEquals(listOf(original.customImagePath), images.discarded)
    }

    @Test
    fun failedApplyKeepsDraftAndAppliedImage() = editorTest {
        val store = FakeTicketboxSettingsStore()
        store.saveBackgroundSettings(original)
        val images = FakeBackgroundImages()
        val vm = AppearanceViewModel(store, images)
        advanceUntilIdle()
        vm.editBackground(draft)
        store.backgroundWriteFailure = IllegalStateException("Unable to write /private/background.preferences_pb")

        vm.applyBackgroundDraft()
        advanceUntilIdle()

        assertEquals(original, store.backgroundSettingsFlow.first())
        val editor = assertNotNull(vm.uiState.value.editor)
        assertEquals(draft, editor.settings)
        assertFalse(editor.saving)
        assertEquals(UiText.res(R.string.appearance_message_background_save_failed), editor.message)
        assertTrue(images.discarded.isEmpty())
    }

    @Test
    fun cancelDiscardsOnlyUnpublishedImageAndKeepsCurrentComposition() = editorTest {
        val store = FakeTicketboxSettingsStore()
        store.saveBackgroundSettings(original)
        val images = FakeBackgroundImages()
        val vm = AppearanceViewModel(store, images)
        advanceUntilIdle()

        vm.editBackground(draft)
        vm.cancelBackgroundEdit()
        advanceUntilIdle()
        assertEquals(listOf(draft.customImagePath), images.discarded)
        assertEquals(original, store.backgroundSettingsFlow.first())

        vm.editBackground(original.copy(transform = draft.transform))
        vm.cancelBackgroundEdit()
        advanceUntilIdle()
        assertEquals(listOf(draft.customImagePath), images.discarded)
        assertEquals(original, store.backgroundSettingsFlow.first())
    }

    @Test
    fun savingOwnsDraftUntilPublicationAndReleasesOldImageOnlyAfterward() = editorTest {
        val persisted = FakeTicketboxSettingsStore()
        persisted.saveBackgroundSettings(original)
        val release = CompletableDeferred<Unit>()
        var writes = 0
        val store = object : TicketboxSettingsStore by persisted {
            override suspend fun saveBackgroundSettings(settings: BackgroundSettings) {
                writes++
                release.await()
                persisted.saveBackgroundSettings(settings)
            }
        }
        val images = FakeBackgroundImages()
        val vm = AppearanceViewModel(store, images)
        runCurrent()
        vm.editBackground(draft)
        vm.applyBackgroundDraft()
        vm.applyBackgroundDraft()
        vm.cancelBackgroundEdit()
        runCurrent()

        assertEquals(1, writes)
        assertTrue(assertNotNull(vm.uiState.value.editor).saving)
        assertEquals(original, persisted.backgroundSettingsFlow.first())
        assertTrue(images.discarded.isEmpty())

        release.complete(Unit)
        advanceUntilIdle()
        assertNull(vm.uiState.value.editor)
        assertEquals(draft, persisted.backgroundSettingsFlow.first())
        assertEquals(listOf(original.customImagePath), images.discarded)
    }

    private fun editorTest(block: suspend TestScope.() -> Unit) = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            block()
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }
}
