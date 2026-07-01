package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.viewmodel.SettingsUiState
import kotlin.test.Test
import kotlin.test.assertNull
import kotlin.test.assertSame

class ServerSettingsScreenStateTest {
    @Test
    fun confirmedServerSettingsRequiresFreshServerSnapshot() {
        val cached = serverSettings()

        val state = SettingsUiState(
            serverSettings = cached,
            serverSettingsFresh = false,
        )

        assertNull(state.confirmedServerSettings())
    }

    @Test
    fun confirmedServerSettingsKeepsFreshServerSnapshot() {
        val confirmed = serverSettings()

        val state = SettingsUiState(
            serverSettings = confirmed,
            serverSettingsFresh = true,
        )

        assertSame(confirmed, state.confirmedServerSettings())
    }

    private fun serverSettings() = ServerSettings(
        accountName = "Me",
        ledgerId = "ledger-1",
        ledgerName = "小票夹",
        ledgerIsDefault = true,
        deviceName = "Phone",
        role = "owner",
        status = "active",
        storageStatus = "normal",
        pendingCount = 1,
        confirmedCount = 2,
        rejectedCount = 0,
        suspectedDuplicateCount = 0,
        uploadStorageBytes = 0L,
        latestUploadAt = "2026-07-02T10:00:00Z",
    )
}
