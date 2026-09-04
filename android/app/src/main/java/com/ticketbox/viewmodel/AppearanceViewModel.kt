package com.ticketbox.viewmodel

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.BackgroundImageRepository
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

class AppearanceViewModel(
    private val settingsStore: TicketboxSettingsStore,
    private val images: BackgroundImageRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(AppearanceUiState())
    val uiState: StateFlow<AppearanceUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            settingsStore.backgroundSettingsFlow.collect { settings ->
                _uiState.update { it.copy(backgroundSettings = settings) }
            }
        }
    }

    fun importBackgroundImage(uri: Uri) {
        if (_uiState.value.importing || _uiState.value.editor != null) return
        _uiState.update { it.copy(importing = true, message = null) }
        viewModelScope.launch {
            try {
                val path = images.importImage(uri)
                val draft = _uiState.value.backgroundSettings.withCustomImage(path)
                _uiState.update { it.copy(editor = BackgroundEditorState(draft)) }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                _uiState.update {
                    it.copy(message = UiText.res(R.string.settings_background_copy_failed), messageTone = MessageTone.Danger)
                }
            } finally {
                _uiState.update { it.copy(importing = false) }
            }
        }
    }

    fun editBackground(settings: BackgroundSettings) {
        if (_uiState.value.importing || _uiState.value.editor != null) return
        _uiState.update { it.copy(editor = BackgroundEditorState(settings), message = null) }
    }

    fun updateBackgroundDraft(settings: BackgroundSettings) {
        if (_uiState.value.editor?.saving != false) return
        _uiState.update { it.copy(editor = it.editor?.copy(settings = settings, message = null)) }
    }

    fun cancelBackgroundEdit() {
        val state = _uiState.value
        val editor = state.editor ?: return
        if (editor.saving) return
        _uiState.update { it.copy(editor = null) }
        val candidate = editor.settings.customImagePath
        if (candidate != null && candidate != state.backgroundSettings.customImagePath) {
            viewModelScope.launch { images.discardImage(candidate) }
        }
    }

    fun applyBackgroundDraft() {
        val editor = _uiState.value.editor ?: return
        if (editor.saving) return
        _uiState.update { it.copy(editor = editor.copy(saving = true, message = null)) }
        publishBackground(editor.settings, R.string.appearance_message_background_applied)
    }

    fun clearBackgroundImage() {
        if (_uiState.value.importing || _uiState.value.editor != null) return
        _uiState.update { it.copy(importing = true) }
        publishBackground(_uiState.value.backgroundSettings.withoutBackground(), R.string.appearance_message_background_theme_restored)
    }

    private fun publishBackground(settings: BackgroundSettings, successMessage: Int) {
        val previous = _uiState.value.backgroundSettings.customImagePath
        viewModelScope.launch {
            try {
                settingsStore.saveBackgroundSettings(settings)
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                val message = UiText.res(R.string.appearance_message_background_save_failed)
                _uiState.update {
                    it.copy(editor = it.editor?.copy(saving = false, message = message), importing = false,
                        message = message, messageTone = MessageTone.Danger)
                }
                return@launch
            }
            _uiState.update {
                it.copy(backgroundSettings = settings, editor = null, importing = false,
                    message = UiText.res(successMessage), messageTone = MessageTone.Success)
            }
            // Only successful preference publication releases the old image.
            if (previous != null && previous != settings.customImagePath) images.discardImage(previous)
        }
    }

    fun setImmersionMode(mode: ImmersionMode) {
        writePreference(UiText.res(R.string.appearance_message_immersion_mode_changed, mode.displayName)) {
            settingsStore.setImmersionMode(mode)
        }
    }

    fun setParallaxEnabled(enabled: Boolean) {
        val message = if (enabled) R.string.appearance_message_parallax_on else R.string.appearance_message_parallax_off
        writePreference(UiText.res(message)) { settingsStore.setParallaxEnabled(enabled) }
    }

    fun setReduceMotion(enabled: Boolean) {
        val message = if (enabled) R.string.appearance_message_reduce_motion_on else R.string.appearance_message_reduce_motion_off
        writePreference(UiText.res(message)) { settingsStore.setReduceMotion(enabled) }
    }

    private fun writePreference(successMessage: UiText, write: suspend () -> Unit) {
        viewModelScope.launch {
            try {
                write()
                _uiState.update { it.copy(message = successMessage, messageTone = MessageTone.Success) }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                _uiState.update {
                    it.copy(message = error.toUiText(R.string.appearance_message_background_save_failed), messageTone = MessageTone.Danger)
                }
            }
        }
    }
}
