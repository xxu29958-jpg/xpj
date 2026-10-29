package com.ticketbox.ui.screens

import android.graphics.Bitmap
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertHasNoClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.local.DebtBillInputEntity
import com.ticketbox.data.remote.dto.DebtBillCaptureDto
import com.ticketbox.data.remote.dto.DebtBillParseOutcomeDto
import com.ticketbox.data.repository.DebtBillActions
import com.ticketbox.data.repository.DebtBillCapturePayload
import com.ticketbox.data.repository.DebtBillInput
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.UploadIntentFileDescriptor
import com.ticketbox.data.repository.UploadIntentFileMetadata
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.viewmodel.DebtListUiState
import com.ticketbox.viewmodel.DebtListViewModel
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.lang.reflect.Proxy
import kotlinx.coroutines.cancel
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Synthetic originals only: Debt detail rows by original state and the creation form's retained originals, incl. large text. */
class DebtBillOriginalRenderTest {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val binding = LogicalSessionBinding("https://bill.example.test", "ledger", "synthetic-owner", "session", "binding")
    private lateinit var viewModel: DebtListViewModel

    @After
    fun stopViewModel() {
        if (::viewModel.isInitialized) compose.runOnIdle { viewModel.viewModelScope.cancel() }
    }

    @Test
    fun detailRowsOpenOnlyReadableOriginals() {
        val sources = DetailSources(Result.success(detailRows()))
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                LazyColumn(Modifier.width(393.dp).padding(horizontal = AppSpacing.screenHorizontal)) {
                    item { DebtBillSourcePanel(DebtDetailUiState(binding = binding, debt = debt()), sources) }
                }
            }
        }
        waitFor("april-bill.jpg")
        compose.onAllNodesWithText(text(R.string.debt_bill_originals)).assertCountEquals(3)
        compose.onNodeWithText("march-bill.jpg").assertHasNoClickAction()
        compose.onNodeWithText(text(R.string.debt_bill_original_cleaned)).assertIsDisplayed()
        compose.onNodeWithText("april-bill.jpg").assertHasNoClickAction()
        compose.onNodeWithText(text(R.string.debt_bill_original_unavailable)).assertIsDisplayed()
        compose.onNodeWithText("bank-statement.jpg").assertHasClickAction()
        saveConsumerArtPreview("debt-bill-detail-rows", compose.onRoot().captureToImage().asAndroidBitmap())

        compose.onNodeWithText("bank-statement.jpg").performClick()
        waitFor(text(R.string.common_confirm))
        compose.runOnIdle { assertEquals(listOf("source-verified"), sources.reads) }
        compose.onNodeWithText(text(R.string.common_confirm)).performClick()
        compose.onNodeWithText(text(R.string.common_confirm)).assertDoesNotExist()
    }

    @Test
    fun detailLoadFailureIsARetryRow() {
        val sources = DetailSources(Result.failure(IOException("synthetic offline")))
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                LazyColumn(Modifier.width(393.dp).padding(horizontal = AppSpacing.screenHorizontal)) {
                    item { DebtBillSourcePanel(DebtDetailUiState(binding = binding, debt = debt()), sources) }
                }
            }
        }
        waitFor(text(R.string.debt_bill_retry_original))
        compose.onNodeWithText(text(R.string.debt_bill_retry_original)).assertHasClickAction()
        saveConsumerArtPreview("debt-bill-detail-retry", compose.onRoot().captureToImage().asAndroidBitmap())

        sources.list = Result.success(detailRows().take(1))
        compose.onNodeWithText(text(R.string.debt_bill_retry_original)).performClick()
        waitFor("bank-statement.jpg")
        compose.onNodeWithText(text(R.string.debt_bill_retry_original)).assertDoesNotExist()
        compose.runOnIdle { assertEquals(2, sources.listCalls) }
    }

    @Test
    fun creationRowsKeepEachOriginalTask() {
        val parsed = input("8c5f1f8e-3c0e-4b1e-9a51-6f0d2a7b9c01", "statement.jpg", failedSource())
        val waiting = input("0b6d4c2a-91e7-4f53-8d2e-3a4b5c6d7e8f", "waiting.jpg", null)
        var state by mutableStateOf(creationState(listOf(parsed, waiting), parsed.captureKey))
        var picked = 0
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                Column(Modifier.width(393.dp).padding(horizontal = AppSpacing.screenHorizontal)) {
                    DebtBillInputPanel(state, sheetModel(), onPickOriginal = { picked++ })
                }
            }
        }
        compose.onNodeWithText(text(R.string.debt_bill_suggestion_failed_kept)).assertIsDisplayed()
        compose.onNodeWithText(text(R.string.debt_bill_capture_waiting)).assertIsDisplayed()
        compose.onAllNodesWithText(text(R.string.debt_bill_continue_original)).assertCountEquals(2)
        compose.onAllNodesWithText(text(R.string.debt_bill_view_original)).assertCountEquals(2)
        compose.onNodeWithText(text(R.string.debt_bill_retry_suggestion)).assertIsEnabled()
        saveConsumerArtPreview("debt-bill-create-rows", compose.onRoot().captureToImage().asAndroidBitmap())

        state = creationState(listOf(waiting), "f47ac10b-58cc-4372-a567-0e02b2c3d479")
        compose.onNodeWithText(text(R.string.debt_bill_local_save_unverified)).assertIsDisplayed()
        compose.onNodeWithText(text(R.string.debt_bill_retry_capture)).assertIsEnabled().performClick()
        compose.runOnIdle { assertEquals(1, picked) }
        saveConsumerArtPreview("debt-bill-create-unverified", compose.onRoot().captureToImage().asAndroidBitmap())

        state = state.copy(isSubmitting = true)
        compose.onNodeWithText(text(R.string.debt_bill_continue_original)).assertIsNotEnabled()
        compose.onNodeWithText(text(R.string.debt_bill_view_original)).assertIsEnabled()
        compose.onNodeWithText(text(R.string.debt_bill_retry_capture)).assertIsNotEnabled()
    }

    @Test
    fun rowsAndActionsFitPhoneWidthAtLargeText() {
        val sources = DetailSources(Result.success(detailRows()))
        val parsed = input("8c5f1f8e-3c0e-4b1e-9a51-6f0d2a7b9c01", "statement.jpg", failedSource())
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                val density = LocalDensity.current
                CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale = 1.3f)) {
                    Column(Modifier.width(360.dp).verticalScroll(rememberScrollState())
                        .padding(horizontal = AppSpacing.screenHorizontal)) {
                        DebtBillSourcePanel(DebtDetailUiState(binding = binding, debt = debt()), sources)
                        DebtBillInputPanel(creationState(listOf(parsed), parsed.captureKey), sheetModel(), onPickOriginal = {})
                    }
                }
            }
        }
        waitFor("april-bill.jpg")
        val width = with(compose.density) { 360.dp.toPx() }
        listOf("bank-statement.jpg", text(R.string.debt_bill_original_unavailable), text(R.string.debt_bill_continue_original),
            text(R.string.debt_bill_view_original), text(R.string.debt_bill_retry_suggestion)).forEach { label ->
            compose.onAllNodesWithText(label).onFirst().assertIsDisplayed()
            compose.onAllNodesWithText(label).fetchSemanticsNodes().forEach { node ->
                assertTrue("$label must stay within 360dp: ${node.boundsInRoot}", node.boundsInRoot.left >= 0f && node.boundsInRoot.right <= width)
            }
        }
        saveConsumerArtPreview("debt-bill-rows-large-text", compose.onRoot().captureToImage().asAndroidBitmap())
    }

    @androidx.compose.runtime.Composable
    private fun sheetModel(): DebtListViewModel {
        val creation = remember { SheetCreationGate() }
        return remember { DebtListViewModel(sheetQueries(), creation, initialAdjustmentReadFixture(creation.currentAccess())) }
            .also { viewModel = it }
    }

    private fun text(resource: Int) = context.getString(resource)
    private fun waitFor(value: String) = compose.waitUntil(5_000) { compose.onAllNodesWithText(value).fetchSemanticsNodes().isNotEmpty() }

    private fun creationState(inputs: List<DebtBillInput>, active: String) = DebtListUiState(billInputs = inputs,
        activeBillCaptureKey = active, homeCurrencyResolved = true, ledgerHomeCurrency = CurrencyCode.CNY)

    private fun detailRows() = listOf(
        capture("source-verified", "bank-statement.jpg", "verified"),
        capture("source-cleaned", "march-bill.jpg", "cleaned"),
        capture("source-missing", "april-bill.jpg", "unavailable"),
    )

    private fun capture(id: String, fileName: String, state: String) = DebtBillCaptureDto(id, "creation-$id", "capture-$id", 2,
        "confirmed", "a".repeat(64), "a".repeat(64), fileName, state, adoptedDebtPublicId = "debt-bill")

    private fun failedSource() = DebtBillCaptureDto("source-parsed", "creation-parsed", "capture-parsed", 2, "pending",
        "a".repeat(64), "a".repeat(64), "statement.jpg", "verified",
        parseOutcome = DebtBillParseOutcomeDto("source-parsed", "parse-1", 2, "failed", "synthetic-provider"))

    private fun input(captureKey: String, fileName: String, source: DebtBillCaptureDto?) = DebtBillInput(
        DebtBillInputEntity(captureKey, binding.ownerKey, binding.ledgerId, "creation-$captureKey", "{}", "{}"),
        DebtBillCapturePayload(1, binding, "creation-$captureKey", captureKey, UploadIntentFileDescriptor(captureKey, 2_048,
            "a".repeat(64), UploadIntentFileMetadata(fileName, "image/jpeg", 0, 2_048))),
        source,
    )

    private fun debt() = Debt(publicId = "debt-bill", ledgerId = "ledger", direction = DebtDirections.I_OWE,
        counterpartyType = DebtCounterpartyTypes.EXTERNAL, counterpartyAccountId = null, counterpartyLabel = "招商银行",
        principalAmountCents = 120_000, remainingAmountCents = 120_000, paidAmountCents = 0, status = DebtLinkStatuses.OPEN,
        sourceType = DebtSourceTypes.MANUAL, sourceId = null, homeCurrencyCode = "CNY", originalCurrencyCode = null,
        originalAmountMinor = null, createdAt = "2026-10-01T00:00:00Z", updatedAt = "2026-10-01T00:00:00Z", rowVersion = 1)
}

/** Detail reads only; every capture or draft command is unexpected here. */
private class DetailSources(
    var list: Result<List<DebtBillCaptureDto>>,
    uncalled: DebtBillActions = Proxy.newProxyInstance(DebtBillActions::class.java.classLoader,
        arrayOf(DebtBillActions::class.java)) { _, method, _ -> error("Unexpected original fixture call: ${method.name}") } as DebtBillActions,
) : DebtBillActions by uncalled {
    var listCalls = 0
    val reads = mutableListOf<String>()
    override suspend fun forDebt(binding: LogicalSessionBinding, publicId: String) = list.also { listCalls++ }
    override suspend fun original(binding: LogicalSessionBinding, publicId: String): Result<ByteArray> {
        reads += publicId
        val bitmap = Bitmap.createBitmap(12, 16, Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.LTGRAY) }
        return Result.success(ByteArrayOutputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it); it.toByteArray() })
    }
}
