package com.ticketbox.ui.screens

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.LedgerAccessContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.ViewModelStore
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import android.content.Context
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.R
import com.ticketbox.data.remote.dto.BillSplitInboxDto
import com.ticketbox.data.remote.dto.BillSplitSentDto
import com.ticketbox.data.repository.BillSplitActions
import com.ticketbox.data.repository.BillSplitLedgerActions
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.viewmodel.BillSplitViewModel
import org.junit.After
import org.junit.Rule
import org.junit.Test

/** Transport DTOs and production mappers feed the real center; no test-side amount projection. */
class BillSplitAmountConsumerTest {
    @get:Rule val compose = createComposeRule()
    private val models = ViewModelStore()

    @After fun close() = compose.runOnIdle { models.clear() }

    @Test fun bothSplitListsUseTheFrozenCurrencyIncludingUnknownCodes() {
        val viewModel = BillSplitViewModel(CurrencySplitActions(), EmptySplitLedgers())
        models.put("splits", viewModel)
        compose.setContent {
            TicketboxTheme(skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
                AppSkin.Midnight else AppSkin.Paper) {
                BillSplitScreen(viewModel = viewModel, onBack = {},
                    navigation = BillSplitNavigation(openBill = { _, _, _ -> error("Amount read must not navigate") }))
            }
        }
        assertFrozenAmounts("inbox")
        val context = ApplicationProvider.getApplicationContext<Context>()
        compose.onNodeWithText(context.getString(R.string.bill_split_tab_sent, 3)).performScrollTo().performClick()
        assertFrozenAmounts("sent")
    }

    private fun assertFrozenAmounts(surface: String) {
        compose.onAllNodesWithText("原定截止", substring = true).assertCountEquals(3)
        listOf("¥1,200", "$12.00", "1200 VND").forEach {
            compose.onNodeWithText(it).performScrollTo().assertIsDisplayed()
        }
        listOf("原消费 JPY ¥2,500", "原消费 JPY ¥5,000", "原消费金额未记录").forEachIndexed { index, label ->
            compose.onNodeWithText(label).performScrollTo().assertIsDisplayed()
            compose.waitForIdle()
            saveConsumerArtPreview("split-$surface-source-$index",
                requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        }
    }
}

private class EmptySplitLedgers : BillSplitLedgerActions {
    override fun cachedLedgers(): List<LedgerSummary> = emptyList()
    override suspend fun refreshLedgers(): Result<List<LedgerSummary>> = Result.success(emptyList())
}

private class CurrencySplitActions : BillSplitActions {
    val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(
        LogicalSessionBinding("https://split-test.example", "owner", "test-owner", "session", "revision"), true))
    override fun currentAccess(): LedgerAccessContext? = access.value
    override fun observeAccess(): Flow<LedgerAccessContext?> = access

    private val moshi = Moshi.Builder().addLast(KotlinJsonAdapterFactory()).build()
    private val payloads = listOf("JPY", "USD", "VND").mapIndexed { index, currency ->
        """{
          "public_id":"split-$currency","status":"accepted","amount_cents":1200,
          "home_currency_code":"$currency","merchant_snapshot":"Shared meal",
          "original_currency_code":"JPY","original_amount_minor":${if (currency == "VND") "null" else ((index + 1) * 2500).toString()},
          "accounting_time_snapshot":{"precision":"date_only","user_local_date":"2026-01-31",
            "accounting_date":"2026-02-01","calendar_revision":7,"basis":"user_date"},
          "category_suggestion":null,"expense_time_snapshot":null,
          "expires_at":"2026-07-02T00:00:00Z","created_at":"2026-07-01T00:00:00Z",
          "accepted_at":"2026-07-01T00:01:00Z","rejected_at":null,"cancelled_at":null,"expired_at":null,
          "sender_account_id":10,"sender_display_name":"Sender",
          "receiver_account_id":20,"receiver_display_name_snapshot":"Receiver","sender_expense_id":30
        }""".trimIndent()
    }

    override suspend fun fetchBillSplitInbox(binding: LogicalSessionBinding): Result<List<BillSplitInbox>> = Result.success(
        payloads.map { requireNotNull(moshi.adapter(BillSplitInboxDto::class.java).fromJson(it)).toDomain() },
    )

    override suspend fun fetchBillSplitSent(binding: LogicalSessionBinding): Result<List<BillSplitSent>> = Result.success(
        payloads.map { requireNotNull(moshi.adapter(BillSplitSentDto::class.java).fromJson(it)).toDomain() },
    )

    override suspend fun acceptBillSplitInvitation(binding: LogicalSessionBinding, original: com.ticketbox.data.repository.BillSplitAcceptPayload): Result<Long> =
        error("This read-only consumer must not accept a split")

    override fun observeAcceptances() = kotlinx.coroutines.flow.flowOf(com.ticketbox.data.repository.BillSplitAcceptanceObservation(access.value))

    override suspend fun recoverAcceptance(binding: LogicalSessionBinding, id: Long, drop: Boolean): Result<Unit> =
        error("This read-only consumer must not recover a split")

    override suspend fun rejectBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitInbox> =
        error("This read-only consumer must not reject a split")

    override suspend fun cancelBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitSent> =
        error("This read-only consumer must not cancel a split")
}
