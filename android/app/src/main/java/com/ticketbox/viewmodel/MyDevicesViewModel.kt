package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.AccountDevice
import com.ticketbox.domain.model.DevicePairingCode
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * issue #65 slice 6b: Settings → My devices. Mirrors [FamilyMembersViewModel]'s
 * shape (Screen → ViewModel → Repository → IO). The list itself is owner-gated
 * on the backend (slice 6a, manager context → 403/404), so the upper-level Root
 * entry is shown only to owners; [deviceIsOwner] re-checks before every mutate
 * (backend stays the final guard).
 */
data class MyDevicesUiState(
    val devices: List<AccountDevice> = emptyList(),
    val loading: Boolean = false,
    /** publicId of the device whose rename/revoke is in flight (禁双击)。 */
    val busyDeviceId: String? = null,
    val message: UiText? = null,
    val pairingCreating: Boolean = false,
    /**
     * 最近一次生成的配对码(明文只在创建响应出现一次,服务端只存哈希)。非 null 时
     * 屏幕渲染结果卡(配对码 + 有效期),收起/再次生成覆盖/离屏即不可再取。
     */
    val createdPairingCode: DevicePairingCode? = null,
)

class MyDevicesViewModel(
    private val repository: LedgerRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(MyDevicesUiState())
    val uiState: StateFlow<MyDevicesUiState> = _uiState.asStateFlow()

    /** True if the bound device's session is OWNER on the active ledger. The
     * screen gates management affordances on this; backend 403/404 兜底. */
    fun deviceIsOwner(): Boolean =
        repository.currentLedgerRole() == LEDGER_ROLE_OWNER

    fun refresh(activeLedgerId: String?) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            val error = loadDevices(activeLedgerId)
            _uiState.update { it.copy(loading = false, message = error) }
        }
    }

    fun rename(device: AccountDevice, newName: String, activeLedgerId: String?) {
        if (!deviceIsOwner()) return
        val cleanName = newName.trim()
        if (cleanName.isEmpty()) {
            _uiState.update { it.copy(message = UiText.res(R.string.my_devices_message_name_required)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busyDeviceId = device.publicId, message = null) }
            repository.renameDevice(device.publicId, cleanName, activeLedgerId)
                .onSuccess { applyMutationSuccess(activeLedgerId, UiText.res(R.string.my_devices_message_renamed, cleanName)) }
                .onFailure { err -> finishWithError(err) }
        }
    }

    fun revoke(device: AccountDevice, activeLedgerId: String?) {
        if (!deviceIsOwner()) return
        viewModelScope.launch {
            _uiState.update { it.copy(busyDeviceId = device.publicId, message = null) }
            repository.revokeDevice(device.publicId, activeLedgerId)
                .onSuccess { applyMutationSuccess(activeLedgerId, UiText.res(R.string.my_devices_message_revoked, device.deviceName)) }
                .onFailure { err -> finishWithError(err) }
        }
    }

    /** Re-list (so the row reflects the new state) BEFORE surfacing [success] —
     * the reload must not clobber the message the user just earned. */
    private suspend fun applyMutationSuccess(activeLedgerId: String?, success: UiText) {
        loadDevices(activeLedgerId)
        _uiState.update { it.copy(busyDeviceId = null, message = success) }
    }

    /** Fetch the device list into state; returns a load-error message or null. */
    private suspend fun loadDevices(activeLedgerId: String?): UiText? {
        var error: UiText? = null
        repository.refreshDevices(activeLedgerId)
            .onSuccess { fetched -> _uiState.update { it.copy(devices = fetched) } }
            .onFailure { err -> error = err.toUiText(R.string.my_devices_message_load_failed) }
        return error
    }

    fun createPairingCode(activeLedgerId: String?) {
        if (!deviceIsOwner()) return
        viewModelScope.launch {
            _uiState.update { it.copy(pairingCreating = true, message = null) }
            repository.createDevicePairingCode(activeLedgerId)
                .onSuccess { created ->
                    _uiState.update { it.copy(pairingCreating = false, createdPairingCode = created) }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(pairingCreating = false, message = err.toUiText(R.string.my_devices_message_pairing_failed))
                    }
                }
        }
    }

    /** 收起配对码结果卡(明文不再展示;服务端只存哈希,收起后不可再取回)。 */
    fun dismissPairingCode() {
        _uiState.update { it.copy(createdPairingCode = null) }
    }

    private fun finishWithError(err: Throwable) {
        _uiState.update {
            it.copy(busyDeviceId = null, message = err.toUiText(R.string.my_devices_message_action_failed))
        }
    }
}
