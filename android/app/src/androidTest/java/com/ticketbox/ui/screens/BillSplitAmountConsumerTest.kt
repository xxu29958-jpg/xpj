package com.ticketbox.ui.screens

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.LedgerAccessContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.ViewModelStore
import androidx.test.core.app.ApplicationProvider
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
            TicketboxTheme(skin = AppSkin.Default) {
                BillSplitScreen(viewModel = viewModel, onBack = {},
                    navigation = BillSplitNavigation(openBill = { _, _, _ -> error("Amount read must not navigate") }))
            }
        }
        assertFrozenAmounts()
        val context = ApplicationProvider.getApplicationContext<Context>()
        compose.onNodeWithText(context.getString(R.string.bill_split_tab_sent, 3)).performScrollTo().performClick()
        assertFrozenAmounts()
    }

    private fun assertFrozenAmounts() {
        listOf("¥1,200", "$12.00", "1200 VND").forEach {
            compose.onNodeWithText(it).performScrollTo().assertIsDisplayed()
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
    private val payloads = listOf("JPY", "USD", "VND").map { currency ->
        """{
          "public_id":"split-$currency","status":"accepted","amount_cents":1200,
          "home_currency_code":"$currency","merchant_snapshot":"Shared meal",
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

    override suspend fun acceptBillSplitInvitation(binding: LogicalSessionBinding, publicId: String, targetLedgerId: String): Result<BillSplitInbox> =
        error("This read-only consumer must not accept a split")

    override suspend fun rejectBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitInbox> =
        error("This read-only consumer must not reject a split")

    override suspend fun cancelBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitSent> =
        error("This read-only consumer must not cancel a split")
}
