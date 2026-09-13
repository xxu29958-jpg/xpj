package com.ticketbox.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticCheck
import com.ticketbox.domain.model.DiagnosticCheckKind
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.SettingsUiState
import org.junit.Rule
import org.junit.Test

class ConnectionDiagnosticsEntryTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun ordinaryMemberSeesTheFailedCheckAndNextStepWithoutInternalTools() {
        val nextStep = "请将手机应用与服务端更新到配套版本，再重新检测。"
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ServerSettingsScreen(
                    state = ServerSettingsScreenState(
                        settings = SettingsUiState(
                            ledgerName = "家庭账本", role = "member",
                            diagnostics = ConnectionDiagnostics(listOf(
                                DiagnosticCheck(DiagnosticCheckKind.ConfirmedExpenses, DiagnosticStatus.Fail, nextStep, 1),
                            )),
                        ),
                        showAdvancedTools = false,
                    ),
                    actions = ServerSettingsScreenActions(
                        onBack = {}, onRunDiagnostics = {}, onCancelConnectionWork = {},
                        onRefreshServerSettings = {}, onSync = {}, onOpenSyncStatus = {},
                    ),
                )
            }
        }

        composeRule.onNodeWithText(nextStep).performScrollTo().assertIsDisplayed()
    }
}
