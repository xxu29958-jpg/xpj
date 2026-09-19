package com.ticketbox.ui.screens

import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.screens.expense.ExpenseTimeForm
import com.ticketbox.ui.screens.expense.toSavedJson
import com.ticketbox.ui.theme.TicketboxTheme
import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

class ManualExpenseAccountingTimeTest {
    @get:Rule val compose = createComposeRule()

    @Test fun dateOnlySurvivesRecreationAndSubmitsTheCapturedRuleWithoutMidnight() {
        val restoration = StateRestorationTester(compose)
        val rule = LedgerCalendarDto("owner", 2, "Asia/Shanghai", "explicit", "2026-09-20T00:00:00Z")
        val captured = ExpenseTimeForm.initial("2026-04-30T16:30:00Z", null, rule, ZoneId.of("Asia/Shanghai"))
        var submitted: ExpenseDraft? = null
        restoration.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ManualExpenseSheet(
                    state = ManualExpenseSheetState(emptyList(), false, initialCurrency = CurrencyCode.CNY),
                    actions = ManualExpenseSheetActions({ submitted = it }, {}),
                    initials = ManualExpenseSheetInitials(amountText = "12", timeFormJson = captured.toSavedJson()),
                )
            }
        }
        compose.onNodeWithText("只记日期").performScrollTo().performClick()
        restoration.emulateSavedInstanceStateRestore()
        compose.onNodeWithText("记入账本").performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals("date_only", submitted?.timeInput?.precision)
            assertEquals(2L, submitted?.timeInput?.calendarRevision)
            assertEquals("2026-05-01", submitted?.timeInput?.userLocalDate)
            assertNull(submitted?.expenseTime)
            assertNull(submitted?.timeInput?.instantUtc)
        }
    }
}
