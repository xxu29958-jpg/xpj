package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class AppearanceUiState(
    val backgroundSettings: BackgroundSettings = BackgroundSettings(),
    val message: String? = null,
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
                .onSuccess { _uiState.update { it.copy(message = "背景已更新") } }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "背景没有保存成功。") } }
        }
    }

    fun applyBackgroundSettings(settings: BackgroundSettings) {
        viewModelScope.launch {
            runCatching { settingsStore.saveBackgroundSettings(settings) }
                .onSuccess { _uiState.update { it.copy(message = "背景已应用") } }
                .onFailure { error -> _uiState.update { it.copy(message = error.message ?: "背景没有保存成功。") } }
        }
    }

    fun resetThemeBackground() {
        viewModelScope.launch {
            settingsStore.saveBackgroundSettings(_uiState.value.backgroundSettings.withoutBackground())
            _uiState.update { it.copy(message = "已恢复跟随主题背景") }
        }
    }

    fun clearBackgroundImage() {
        viewModelScope.launch {
            settingsStore.clearBackgroundImage()
            _uiState.update {
                it.copy(
                    backgroundSettings = it.backgroundSettings.withoutBackground(),
                    message = "已恢复跟随主题背景",
                )
            }
        }
    }

    fun setBackgroundCropMode(mode: BackgroundCropMode) {
        viewModelScope.launch {
            settingsStore.setBackgroundCropMode(mode)
            _uiState.update { it.copy(message = "构图已切换为${mode.displayName}") }
        }
    }

    fun setImmersionMode(mode: ImmersionMode) {
        viewModelScope.launch {
            settingsStore.setImmersionMode(mode)
            _uiState.update { it.copy(message = "已切换为${mode.displayName}模式") }
        }
    }

    fun setParallaxEnabled(enabled: Boolean) {
        viewModelScope.launch {
            settingsStore.setParallaxEnabled(enabled)
            _uiState.update { it.copy(message = if (enabled) "视差动效已开启" else "视差动效已关闭") }
        }
    }

    fun setReduceMotion(enabled: Boolean) {
        viewModelScope.launch {
            settingsStore.setReduceMotion(enabled)
            _uiState.update { it.copy(message = if (enabled) "已减少背景动效" else "已恢复轻微动效") }
        }
    }

    fun backgroundImageCopyFailed(message: String) {
        _uiState.update { it.copy(message = message) }
    }
}
