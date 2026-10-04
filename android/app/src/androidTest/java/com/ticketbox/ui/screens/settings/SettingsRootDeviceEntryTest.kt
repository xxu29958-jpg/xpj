package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.Density
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.saveConsumerArtPreview
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
    private var accountOpened = false
    private val opened = mutableListOf<String>()
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun myDevicesEntryRendersForOwner() {
        setRootContent(role = "owner")
        capture("settings-root-paper")
        composeRule.onNodeWithText("我的设备").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun myDevicesEntryRendersForMember() {
        setRootContent(role = "member", skin = AppSkin.Midnight)
        capture("settings-root-midnight")
        composeRule.onNodeWithText("我的设备").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun myDevicesEntryRendersForViewer() {
        setRootContent(role = "viewer", fontScale = 1.8f)

        composeRule.onNodeWithText("我的设备").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("账本和家庭成员").performScrollTo().performClick()
        composeRule.onNodeWithText("账号名称").performScrollTo().performClick()
        composeRule.runOnIdle { check(accountOpened) }
        capture("settings-root-viewer-large-font")
    }

    @Test
    fun allExistingDestinationsRemainReachableThroughTheDirectory() {
        setRootContent(role = "owner")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val groups = listOf(
            R.string.settings_root_family_directory_title to listOf(
                R.string.account_profile_title, R.string.settings_root_entry_ledgers_title,
                R.string.settings_root_entry_family_members_title, R.string.settings_root_entry_join_family_title,
            ),
            R.string.settings_root_alerts_directory_title to listOf(
                R.string.settings_root_entry_notifications_title, R.string.settings_root_entry_appearance_title,
            ),
            R.string.settings_root_section_data_privacy to listOf(
                R.string.settings_root_entry_data_export_title, R.string.settings_root_entry_security_title,
            ),
            R.string.settings_root_sync_directory_title to listOf(
                R.string.settings_root_connection_title_basic, R.string.settings_root_entry_offline_sync_title,
                R.string.settings_root_entry_background_tasks_title,
            ),
        )
        for ((title, destinations) in groups) {
            composeRule.onNodeWithText(context.getString(title)).performScrollTo().performClick()
            for (destination in destinations) {
                composeRule.onNodeWithText(context.getString(destination)).performScrollTo().performClick()
            }
            if (title == R.string.settings_root_sync_directory_title) capture("settings-root-expanded-system")
            composeRule.onNodeWithText(context.getString(title)).performScrollTo().performClick()
        }
        composeRule.onNodeWithText("我的设备").performScrollTo().performClick()
        composeRule.onNodeWithText("关于").performScrollTo().performClick()
        capture("settings-root-final-destinations")
        composeRule.runOnIdle {
            check(opened.toSet() == setOf("account", "ledgers", "members", "join", "devices", "export",
                "notifications", "appearance", "connection", "sync", "background", "security", "about"))
            check(opened.size == 13)
        }
    }

    private fun capture(name: String) =
        saveConsumerArtPreview(name, composeRule.onRoot().captureToImage().asAndroidBitmap())

    private fun setRootContent(role: String, skin: AppSkin = AppSkin.Paper, fontScale: Float = 1f) {
        composeRule.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale)) {
                TicketboxTheme(skin = skin) {
                    SettingsRootScreen(
                        state = SettingsUiState(
                            serverUrl = "https://family.example.test",
                            accountName = "小林",
                            ledgerName = "我们的家庭账本",
                            deviceName = "我的手机",
                            role = role,
                            serverSettings = ServerSettings(
                                accountName = "小林", ledgerId = "fixture-family", ledgerName = "我们的家庭账本",
                                ledgerIsDefault = true, deviceName = "我的手机", role = role, status = "active",
                                storageStatus = "ok", pendingCount = 2, confirmedCount = 12, rejectedCount = 0,
                                suspectedDuplicateCount = 0, uploadStorageBytes = 1024, latestUploadAt = null,
                            ),
                            serverSettingsFresh = true,
                            lastConfirmedSyncAt = "2026-10-04T00:00:00Z",
                        ),
                        showAdvancedTools = false,
                        navigationActions = settingsRootNavigationActionsNoOp(),
                    )
                }
            }
        }
    }

    private fun settingsRootNavigationActionsNoOp(): SettingsRootNavigationActions =
        SettingsRootNavigationActions(
            ledgerFamily = SettingsRootLedgerFamilyNavigationActions(
                onOpenAccountProfile = { accountOpened = true; opened += "account" },
                onOpenLedgers = { opened += "ledgers" },
                onOpenFamilyMembers = { opened += "members" },
                onOpenMyDevices = { opened += "devices" },
                onOpenJoinFamilyLedger = { opened += "join" },
            ),
            dataPrivacy = SettingsRootDataPrivacyNavigationActions(
                onOpenDataExport = { opened += "export" },
            ),
            alertsAppearance = SettingsRootAlertsAppearanceNavigationActions(
                onOpenNotifications = { opened += "notifications" },
                onOpenAppearance = { opened += "appearance" },
            ),
            connectionSystem = SettingsRootConnectionSystemNavigationActions(
                onOpenServer = { opened += "connection" },
                onOpenSyncStatus = { opened += "sync" },
                onOpenBackgroundTasks = { opened += "background" },
                onOpenSecurity = { opened += "security" },
                onOpenAbout = { opened += "about" },
            ),
        )
}
