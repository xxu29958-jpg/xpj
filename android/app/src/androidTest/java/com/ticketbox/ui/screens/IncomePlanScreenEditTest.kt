package com.ticketbox.ui.screens

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.data.repository.IncomePlanPatch
import com.ticketbox.data.repository.IncomePlanSaveOutcome
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.IncomePlanViewModel
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class IncomePlanScreenEditTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun editActionOpensPrefilledSheetAndSubmitsPatch() {
        val baseline = incomePlan()
        val repository = RecordingIncomePlanActions(baseline)
        val viewModel = IncomePlanViewModel(repository)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val editDescription = context.getString(R.string.income_plan_card_edit_action)
        val editorTitle = context.getString(R.string.income_plan_sheet_edit_title)

        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                IncomePlanScreen(
                    viewModel = viewModel,
                    currency = CurrencyDisplay(CurrencyCode.CNY),
                    onBack = {},
                )
            }
        }

        composeRule.waitUntil {
            composeRule.onAllNodesWithContentDescription(editDescription)
                .fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithContentDescription(editDescription).performClick()
        composeRule.onNodeWithText(editorTitle).assertIsDisplayed()
        composeRule.onNode(hasText("工资") and hasSetTextAction())
            .assertIsDisplayed()
            .performTextReplacement("调薪后工资")
        composeRule.onNodeWithText(context.getString(R.string.income_plan_sheet_update))
            .performScrollTo()
            .performClick()

        composeRule.waitUntil { repository.updateCalls == 1 }
        assertEquals(baseline, repository.lastBaseline)
        assertEquals(baseline.rowVersion, repository.lastPatch?.expectedRowVersion)
        assertEquals("调薪后工资", repository.lastPatch?.label)
        composeRule.waitUntil {
            composeRule.onAllNodesWithText(editorTitle).fetchSemanticsNodes().isEmpty()
        }
    }

    private fun incomePlan() = IncomePlan(
        publicId = "income-1",
        label = "工资",
        sourceType = IncomeSourceType.SALARY,
        frequency = IncomeFrequency.MONTHLY,
        incomeMonth = null,
        amountCents = 800_000L,
        payDay = 10,
        status = IncomePlanStatus.ACTIVE,
        createdAt = "2026-07-01T00:00:00Z",
        updatedAt = "2026-07-01T00:00:00Z",
        rowVersion = 9L,
        archivedAt = null,
    )

    private class RecordingIncomePlanActions(
        private val baseline: IncomePlan,
    ) : IncomePlanActions {
        @Volatile
        var updateCalls = 0
        var lastBaseline: IncomePlan? = null
        var lastPatch: IncomePlanPatch? = null

        override fun canModifyLedger(): Boolean = true

        override val currentHomeCurrency: CurrencyCode = CurrencyCode.CNY

        override suspend fun listActive(): Result<IncomePlanListing> =
            Result.success(IncomePlanListing(listOf(baseline), baseline.amountCents))

        override suspend fun listIncluding(status: IncomePlanStatus): Result<List<IncomePlan>> =
            Result.success(emptyList())

        override suspend fun create(draft: IncomePlanDraft): Result<IncomePlan> =
            Result.failure(AssertionError("create should not run while editing"))

        override suspend fun update(
            publicId: String,
            patch: IncomePlanPatch,
        ): Result<IncomePlan> = Result.failure(AssertionError("direct update should not run"))

        override suspend fun updateAllowingOffline(
            baseline: IncomePlan,
            patch: IncomePlanPatch,
        ): Result<IncomePlanSaveOutcome> {
            updateCalls += 1
            lastBaseline = baseline
            lastPatch = patch
            return Result.success(
                IncomePlanSaveOutcome.Synced(
                    baseline.copy(
                        label = patch.label ?: baseline.label,
                        rowVersion = baseline.rowVersion + 1L,
                    ),
                ),
            )
        }

        override suspend fun archive(
            publicId: String,
            expectedRowVersion: Long,
        ): Result<IncomePlan> = Result.failure(AssertionError("archive should not run"))

        override suspend fun restore(
            publicId: String,
            expectedRowVersion: Long,
        ): Result<IncomePlan> = Result.failure(AssertionError("restore should not run"))
    }
}
