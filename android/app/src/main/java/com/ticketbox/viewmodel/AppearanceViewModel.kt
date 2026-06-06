package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class AppearanceUiState(
    val backgroundSettings: BackgroundSettings = BackgroundSettings(),
    val message: UiText? = null,
)

class AppearanceViewModel(
    private val settingsStore: TicketboxSettingsStore,
) : ViewModel() {
    private val _uiState = MutableStateFlow(AppearanceUiState())
    val uiState: StateFlow<AppearanceUiState> = _uiState.asStateFlow()

    init {
        observeBackgroundSettings()
    }

    private fun observeBackgroundSettings() {
        viewModelScope.launch {
            settingsStore.backgroundSettingsFlow.collect { settings ->
                _uiState.update { it.copy(backgroundSettings = settings) }
            }
        }
    }

    fun saveBackgroundImage(path: String) {
        viewModelScope.launch {
            runCatching { settingsStore.saveBackgroundImagePath(path) }
                .onSuccess { _uiState.update { it.copy(message = UiText.res(R.string.appearance_message_background_updated)) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.appearance_message_background_save_failed)) } }
        }
    }

    fun applyBackgroundSettings(settings: BackgroundSettings) {
        viewModelScope.launch {
            runCatching { settingsStore.saveBackgroundSettings(settings) }
                .onSuccess { _uiState.update { it.copy(message = UiText.res(R.string.appearance_message_background_applied)) } }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.appearance_message_background_save_failed)) } }
        }
    }

    fun resetThemeBackground() {
        viewModelScope.launch {
            settingsStore.saveBackgroundSettings(_uiState.value.backgroundSettings.withoutBackground())
            _uiState.update { it.copy(message = UiText.res(R.string.appearance_message_background_theme_restored)) }
        }
    }

    fun clearBackgroundImage() {
        viewModelScope.launch {
            settingsStore.clearBackgroundImage()
            _uiState.update {
                it.copy(
                    backgroundSettings = it.backgroundSettings.withoutBackground(),
                    message = UiText.res(R.string.appearance_message_background_theme_restored),
                )
            }
        }
    }

    fun setBackgroundCropMode(mode: BackgroundCropMode) {
        viewModelScope.launch {
            settingsStore.setBackgroundCropMode(mode)
            _uiState.update { it.copy(message = UiText.res(R.string.appearance_message_crop_mode_changed, mode.displayName)) }
        }
    }

    fun setImmersionMode(mode: ImmersionMode) {
        viewModelScope.launch {
            settingsStore.setImmersionMode(mode)
            _uiState.update { it.copy(message = UiText.res(R.string.appearance_message_immersion_mode_changed, mode.displayName)) }
        }
    }

    fun setParallaxEnabled(enabled: Boolean) {
        viewModelScope.launch {
            settingsStore.setParallaxEnabled(enabled)
            val message = if (enabled) {
                UiText.res(R.string.appearance_message_parallax_on)
            } else {
                UiText.res(R.string.appearance_message_parallax_off)
            }
            _uiState.update { it.copy(message = message) }
        }
    }

    fun setReduceMotion(enabled: Boolean) {
        viewModelScope.launch {
            settingsStore.setReduceMotion(enabled)
            val message = if (enabled) {
                UiText.res(R.string.appearance_message_reduce_motion_on)
            } else {
                UiText.res(R.string.appearance_message_reduce_motion_off)
            }
            _uiState.update { it.copy(message = message) }
        }
    }

    fun backgroundImageCopyFailed(message: String) {
        // The host (SettingsDestinationHost) already resolves the failure copy from a
        // string resource via context.getString and passes the resolved text here, so
        // carry it through as an already-resolved UiText.Raw (byte-identical output).
        _uiState.update { it.copy(message = UiText.raw(message)) }
    }
}
