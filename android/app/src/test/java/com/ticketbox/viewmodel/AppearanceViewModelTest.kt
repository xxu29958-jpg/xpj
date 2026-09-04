package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.FakeTicketboxSettingsStore
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals

@OptIn(ExperimentalCoroutinesApi::class)
class AppearanceViewModelTest {
    @Test
    fun appliedBackgroundShowsSuccessToneAndUpdatesSettings() = appearanceTest {
        val settingsStore = FakeTicketboxSettingsStore()
        val vm = AppearanceViewModel(settingsStore, FakeBackgroundImages())
        advanceUntilIdle()

        vm.editBackground(BackgroundSettings().withCustomImage("C:\\app\\backgrounds\\custom_background.jpg"))
        vm.applyBackgroundDraft()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(BackgroundSource.CustomImage, state.backgroundSettings.source)
        assertEquals("C:\\app\\backgrounds\\custom_background.jpg", state.backgroundSettings.customImagePath)
        assertEquals(UiText.res(R.string.appearance_message_background_applied), state.message)
        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun immersionWriteFailureShowsDangerToneWithoutChangingSettings() = appearanceTest {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            backgroundWriteFailure = IllegalStateException()
        }
        val vm = AppearanceViewModel(settingsStore, FakeBackgroundImages())
        advanceUntilIdle()

        vm.setImmersionMode(ImmersionMode.Focus)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(ImmersionMode.Balanced, state.backgroundSettings.immersionMode)
        assertEquals(UiText.res(R.string.appearance_message_background_save_failed), state.message)
        assertEquals(MessageTone.Danger, state.messageTone)
    }

    @Test
    fun restoringThemePreservesAppliedBackgroundOnWriteFailure() = appearanceTest {
        val original = BackgroundSettings().withCustomImage("/private/background.image")
        val store = FakeTicketboxSettingsStore()
        store.saveBackgroundSettings(original)
        val vm = AppearanceViewModel(store, FakeBackgroundImages())
        advanceUntilIdle()
        store.backgroundWriteFailure = IllegalStateException()

        vm.clearBackgroundImage()
        advanceUntilIdle()

        assertEquals(original, vm.uiState.value.backgroundSettings)
        assertEquals(UiText.res(R.string.appearance_message_background_save_failed), vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
    }

    private fun appearanceTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }
}
