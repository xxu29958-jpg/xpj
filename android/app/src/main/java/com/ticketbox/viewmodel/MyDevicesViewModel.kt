package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.AccountDevice
import com.ticketbox.domain.model.DevicePairingCode
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Account-scoped device lifecycle. Ledger role never decides whether a person
 * may rename, revoke, add, or explicitly recover their own Device.
 */
data class MyDevicesUiState(
    val devices: List<AccountDevice> = emptyList(),
    val loading: Boolean = false,
    /** publicId of the device whose rename/revoke is in flight (禁双击)。 */
    val busyDeviceId: String? = null,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
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

    fun refresh(activeLedgerId: String?) {
        if (_uiState.value.loading) return
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null, messageTone = MessageTone.Neutral) }
            val error = loadDevices(activeLedgerId)
            _uiState.update {
                it.copy(
                    loading = false,
                    message = error,
                    messageTone = if (error == null) MessageTone.Neutral else MessageTone.Danger,
                )
            }
        }
    }

    fun rename(device: AccountDevice, newName: String, activeLedgerId: String?) {
        val cleanName = newName.trim()
        if (cleanName.isEmpty()) {
            _uiState.update {
                it.copy(
                    message = UiText.res(R.string.my_devices_message_name_required),
                    messageTone = MessageTone.Danger,
                )
            }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(busyDeviceId = device.publicId, message = null, messageTone = MessageTone.Neutral) }
            repository.renameDevice(device.publicId, cleanName, activeLedgerId)
                .onSuccess { applyMutationSuccess(activeLedgerId, UiText.res(R.string.my_devices_message_renamed, cleanName)) }
                .onFailure { err -> finishWithError(err) }
        }
    }

    fun revoke(device: AccountDevice, activeLedgerId: String?) {
        viewModelScope.launch {
            _uiState.update { it.copy(busyDeviceId = device.publicId, message = null, messageTone = MessageTone.Neutral) }
            repository.revokeDevice(device.publicId, activeLedgerId)
                .onSuccess { applyMutationSuccess(activeLedgerId, UiText.res(R.string.my_devices_message_revoked, device.deviceName)) }
                .onFailure { err -> finishWithError(err) }
        }
    }

    /** Permanently remove an already-revoked device, then re-list. */
    fun delete(device: AccountDevice, activeLedgerId: String?) {
        viewModelScope.launch {
            _uiState.update { it.copy(busyDeviceId = device.publicId, message = null, messageTone = MessageTone.Neutral) }
            repository.deleteDevice(device.publicId, activeLedgerId)
                .onSuccess { applyMutationSuccess(activeLedgerId, UiText.res(R.string.my_devices_message_deleted, device.deviceName)) }
                .onFailure { err -> finishWithError(err) }
        }
    }

    /** Re-list (so the row reflects the new state) BEFORE surfacing [success] —
     * the reload must not clobber the message the user just earned. */
    private suspend fun applyMutationSuccess(activeLedgerId: String?, success: UiText) {
        val error = loadDevices(activeLedgerId)
        _uiState.update {
            it.copy(
                busyDeviceId = null,
                message = error ?: success,
                messageTone = if (error == null) MessageTone.Success else MessageTone.Danger,
            )
        }
    }

    /** Fetch the device list into state; returns a load-error message or null. */
    private suspend fun loadDevices(activeLedgerId: String?): UiText? {
        var error: UiText? = null
        repository.refreshDevices(activeLedgerId)
            .onSuccess { fetched -> _uiState.update { it.copy(devices = fetched) } }
            .onFailure { err ->
                val fallback = if (_uiState.value.devices.isEmpty()) {
                    R.string.my_devices_message_load_failed
                } else {
                    R.string.my_devices_message_refresh_failed_with_data
                }
                error = if ((err as? RepositoryException)?.errorCode.isNullOrBlank()) {
                    UiText.res(fallback)
                } else {
                    err.toUiText(fallback)
                }
            }
        return error
    }

    fun createPairingCode(activeLedgerId: String?) {
        requestPairingCode(recoveryDevice = null, activeLedgerId = activeLedgerId)
    }

    fun recover(device: AccountDevice, activeLedgerId: String?) {
        if (device.isCurrent) return
        requestPairingCode(recoveryDevice = device, activeLedgerId = activeLedgerId)
    }

    private fun requestPairingCode(
        recoveryDevice: AccountDevice?,
        activeLedgerId: String?,
    ) {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    pairingCreating = true,
                    busyDeviceId = recoveryDevice?.publicId,
                    message = null,
                    messageTone = MessageTone.Neutral,
                )
            }
            repository.createDevicePairingCode(
                recoveryDevice = recoveryDevice,
                ledgerId = activeLedgerId,
            )
                .onSuccess { created ->
                    _uiState.update {
                        it.copy(
                            pairingCreating = false,
                            busyDeviceId = null,
                            createdPairingCode = created,
                            messageTone = MessageTone.Neutral,
                        )
                    }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            pairingCreating = false,
                            busyDeviceId = null,
                            message = err.toUiText(R.string.my_devices_message_pairing_failed),
                            messageTone = MessageTone.Danger,
                        )
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
            it.copy(
                busyDeviceId = null,
                message = err.toUiText(R.string.my_devices_message_action_failed),
                messageTone = MessageTone.Danger,
            )
        }
    }
}
