package com.ticketbox.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.SettingsUiState
import org.junit.Rule
import org.junit.Test

/**
 * Pins the 我的设备 entry visibility on the settings root: device management is
 * an account-domain surface (any role can list/rename their own devices and
 * mint pairing codes), so the entry must render for owner/member/viewer alike.
 * 218-B2's settings migration briefly wrapped it in an owner-only gate.
 */
class SettingsRootDeviceEntryTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun myDevicesEntryRendersForOwner() {
        setRootContent(role = "owner")

        composeRule.onNodeWithText("我的设备").assertIsDisplayed()
    }

    @Test
    fun myDevicesEntryRendersForMember() {
        setRootContent(role = "member")

        composeRule.onNodeWithText("我的设备").assertIsDisplayed()
    }

    @Test
    fun myDevicesEntryRendersForViewer() {
        setRootContent(role = "viewer")

        composeRule.onNodeWithText("我的设备").assertIsDisplayed()
    }

    private fun setRootContent(role: String) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                SettingsRootScreen(
                    state = SettingsUiState(
                        serverUrl = "http://localhost",
                        accountName = "验收",
                        ledgerName = "资料库账本",
                        deviceName = "dev",
                        role = role,
                    ),
                    showAdvancedTools = false,
                    navigationActions = settingsRootNavigationActionsNoOp(),
                )
            }
        }
    }

    private fun settingsRootNavigationActionsNoOp(): SettingsRootNavigationActions =
        SettingsRootNavigationActions(
            ledgerFamily = SettingsRootLedgerFamilyNavigationActions(
                onOpenLedgers = {},
                onOpenFamilyMembers = {},
                onOpenMyDevices = {},
                onOpenJoinFamilyLedger = {},
            ),
            dataPrivacy = SettingsRootDataPrivacyNavigationActions(
                onOpenDataExport = {},
            ),
            alertsAppearance = SettingsRootAlertsAppearanceNavigationActions(
                onOpenNotifications = {},
                onOpenAppearance = {},
            ),
            connectionSystem = SettingsRootConnectionSystemNavigationActions(
                onOpenServer = {},
                onOpenSyncStatus = {},
                onOpenBackgroundTasks = {},
                onOpenSecurity = {},
                onOpenAbout = {},
            ),
        )
}
