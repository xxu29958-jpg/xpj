package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.espresso.Espresso.closeSoftKeyboard
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.text.TextLayoutResult
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MerchantCatalogCreateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogListDto
import com.ticketbox.data.remote.dto.MerchantCatalogUpdateRequest
import com.ticketbox.ui.saveConsumerArtPreview
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.util.concurrent.CopyOnWriteArrayList

/** New catalog and alias entries must survive a rejected save in the real library. */
class MerchantManagementContinuationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val catalogRequests = CopyOnWriteArrayList<MerchantCatalogCreateRequest>()
    private val aliasRequests = CopyOnWriteArrayList<MerchantAliasRequest>()
    private val updates = CopyOnWriteArrayList<MerchantCatalogUpdateRequest>()
    @Volatile private var reject = true
    @Volatile private var catalog: MerchantCatalogDto? = null
    @Volatile private var alias: MerchantAliasDto? = null
    private var additionalAliases = emptyList<MerchantAliasDto>()
    @Volatile private var rejectAliasRead = false
    @Volatile private var rejectCatalogRead = false
    private val completedAliasReads = CopyOnWriteArrayList<MerchantAliasListDto>()
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun merchantCatalog(includeHidden: Boolean): MerchantCatalogListDto {
                if (rejectCatalogRead) throw unavailable()
                return MerchantCatalogListDto(listOfNotNull(catalog))
            }
            override suspend fun merchantAliases(): MerchantAliasListDto {
                if (rejectAliasRead) throw unavailable()
                return MerchantAliasListDto(listOfNotNull(alias) + additionalAliases).also { completedAliasReads += it }
            }
            override suspend fun createMerchantCatalog(request: MerchantCatalogCreateRequest): MerchantCatalogDto {
                catalogRequests += request
                if (reject) throw unavailable()
                return MerchantCatalogDto("travel-shop", request.displayName, request.displayName, "active",
                    usageCount = 0, createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 1)
                    .also { catalog = it }
            }

            override suspend fun createMerchantAlias(request: MerchantAliasRequest): MerchantAliasDto {
                aliasRequests += request
                if (reject) throw unavailable()
                val canonical = requireNotNull(request.canonicalMerchant)
                val original = requireNotNull(request.alias)
                return MerchantAliasDto("travel-alias", canonical, canonical, original, original, true,
                    "2026-09-30T00:00:00Z", "2026-09-30T00:00:00Z", 1).also { alias = it }
            }

            override suspend fun updateMerchantCatalog(
                publicId: String,
                request: MerchantCatalogUpdateRequest,
                idempotencyKey: String?,
            ): MerchantCatalogDto {
                assertEquals(catalog?.publicId, publicId)
                updates += request
                if (reject) throw unavailable()
                val current = requireNotNull(catalog)
                if (request.expectedRowVersion != current.rowVersion) throw HttpException(Response.error<Any>(409,
                    """{"error":"state_conflict","message":"商家已被其他设备修改。"}"""
                        .toResponseBody("application/json".toMediaType())))
                return current.copy(displayName = requireNotNull(request.displayName), rowVersion = current.rowVersion + 1)
                    .also { catalog = it }
            }
        }
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun rejectedCatalogCreationKeepsItsNameUntilAccepted() {
        showMerchants()
        clickText(R.string.merchant_management_tools_add_catalog)
        fill(R.string.merchant_catalog_name_label, "九月差旅商家")
        clickText(R.string.merchant_catalog_create_button)
        compose.waitUntil(5_000) { catalogRequests.size == 1 }
        compose.waitForIdle()
        compose.onNode(hasSetTextAction() and hasText("九月差旅商家")).assertIsDisplayed()
        assertEquals(null, catalog)

        reject = false
        clickText(R.string.merchant_catalog_create_button)
        waitForText(R.string.merchant_catalog_added)
        compose.onNodeWithText("九月差旅商家").assertIsDisplayed()
        assertEquals(listOf(MerchantCatalogCreateRequest("九月差旅商家"), MerchantCatalogCreateRequest("九月差旅商家")),
            catalogRequests)
    }

    @Test fun directoryOpensTheOriginalMerchantAndReturnsToItsAliasSearch() {
        catalog = MerchantCatalogDto("corner", "街角小馆", "街角小馆", "active", usageCount = 8,
            createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 7)
        alias = MerchantAliasDto("corner-alias", "街角小馆", "街角小馆", "街角餐饮店", "街角餐饮店", true,
            "2026-09-30T00:00:00Z", "2026-09-30T00:00:00Z", 3)
        additionalAliases = listOf(requireNotNull(alias).copy(publicId = "independent", canonicalMerchant = "独立商家",
            canonicalKey = "独立商家", alias = "独立支付名称", aliasKey = "独立支付名称"))
        showMerchants()
        clickText(R.string.merchant_catalog_card_status_hidden)
        compose.onNodeWithText("街角小馆").assertDoesNotExist()
        clickText(R.string.merchant_catalog_card_status_visible)
        compose.onNodeWithText("街角小馆").performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("merchant-directory", compose.onRoot().captureToImage().asAndroidBitmap())
        compose.onNodeWithText("搜索商家或别名").assertIsDisplayed()
        compose.onNode(hasSetTextAction()).performTextReplacement("街角餐饮店")
        closeSoftKeyboard()
        compose.onNodeWithText("街角小馆").performScrollTo().performTouchInput { click() }
        compose.onNodeWithText("街角餐饮店").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("独立支付名称").assertDoesNotExist()
        saveConsumerArtPreview("merchant-object-aliases", compose.onRoot().captureToImage().asAndroidBitmap())
        for (label in listOf("街角餐饮店", "归到 街角小馆")) {
            val layouts = mutableListOf<TextLayoutResult>()
            compose.onNodeWithText(label).performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
            val layout = layouts.single()
            // Intrinsic paragraph width can exceed shrink-wrapped Text; check the actual glyph bounds.
            assertTrue("The complete identity must fit: $label, size=${layout.size}",
                !layout.didOverflowHeight && (0 until layout.lineCount).all { line ->
                    !layout.isLineEllipsized(line) && layout.getLineLeft(line) >= 0f &&
                        layout.getLineRight(line) <= layout.size.width
                })
        }

        compose.onNodeWithText("商家目录").performScrollTo().performTouchInput { click() }
        compose.onNode(hasSetTextAction() and hasText("街角餐饮店")).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_card_status_visible)).assertIsSelected()
        saveConsumerArtPreview("merchant-directory-search", compose.onRoot().captureToImage().asAndroidBitmap())
        compose.onNodeWithText("全部别名").performScrollTo().performTouchInput { click() }
        compose.onNodeWithText("独立支付名称").performScrollTo().assertIsDisplayed()
        assertEquals(emptyList<MerchantCatalogCreateRequest>(), catalogRequests)
        assertEquals(emptyList<MerchantAliasRequest>(), aliasRequests)
        assertEquals(emptyList<MerchantCatalogUpdateRequest>(), updates)
        assertEquals("corner", catalog?.publicId)
    }

    @Test fun failedAliasReadCanRetryWithoutClearingAnUnsentCatalogForm() {
        alias = MerchantAliasDto("original-alias", "常用商家", "常用商家", "原始别名", "原始别名", true,
            "2026-09-30T00:00:00Z", "2026-09-30T00:00:00Z", 1)
        rejectAliasRead = true
        showMerchants()
        clickText(R.string.merchant_management_tools_add_catalog)
        fill(R.string.merchant_catalog_name_label, "尚未提交商家")
        closeSoftKeyboard()
        compose.waitForIdle()
        clickText(R.string.common_cancel)
        clickText(R.string.merchant_directory_all_aliases)
        waitForText(R.string.merchant_aliases_reload_button)

        rejectAliasRead = false
        clickText(R.string.merchant_aliases_reload_button)
        compose.waitUntil(5_000) { completedAliasReads.isNotEmpty() }
        compose.waitUntil(5_000) { compose.onAllNodesWithText("原始别名").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("原始别名").performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("merchants-reloaded-alias", compose.onRoot().captureToImage().asAndroidBitmap())
        clickText(R.string.merchant_catalog_section_list)
        clickText(R.string.merchant_management_tools_add_catalog)
        compose.onNode(hasSetTextAction() and hasText("尚未提交商家")).performScrollTo().assertIsDisplayed()
        assertEquals(emptyList<MerchantCatalogCreateRequest>(), catalogRequests)
        assertEquals(emptyList<MerchantAliasRequest>(), aliasRequests)
    }

    @Test fun rejectedAliasCreationKeepsBothOriginalNamesUntilAccepted() {
        showMerchants()
        clickText(R.string.merchant_directory_all_aliases)
        clickText(R.string.merchant_management_tools_add_alias)
        fill(R.string.merchant_aliases_canonical_label, "差旅商家")
        fill(R.string.merchant_aliases_alias_label, "PAY-差旅原始商家", index = 1)
        clickText(R.string.merchant_aliases_create_button)
        compose.waitUntil(5_000) { aliasRequests.size == 1 }
        compose.waitForIdle()
        compose.onNode(hasSetTextAction() and hasText("差旅商家")).assertIsDisplayed()
        compose.onNode(hasSetTextAction() and hasText("PAY-差旅原始商家")).assertIsDisplayed()
        assertEquals(null, alias)

        reject = false
        clickText(R.string.merchant_aliases_create_button)
        waitForText(R.string.merchant_alias_added)
        compose.onNodeWithText("PAY-差旅原始商家").assertIsDisplayed()
        assertEquals(2, aliasRequests.size)
        assertEquals(aliasRequests[0], aliasRequests[1])
        assertEquals("差旅商家", alias?.canonicalMerchant)
        assertEquals("PAY-差旅原始商家", alias?.alias)
    }

    @Test fun acceptedRenamePreservesTheSeparateUnsentCatalogForm() {
        catalog = MerchantCatalogDto("existing", "原商家", "原商家", "active", usageCount = 2,
            createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 7)
        showMerchants()
        clickText(R.string.merchant_management_tools_add_catalog)
        fill(R.string.merchant_catalog_name_label, "尚未提交的新商家")
        closeSoftKeyboard()
        clickText(R.string.common_cancel)
        compose.onNodeWithText("原商家").performScrollTo().performTouchInput { click() }
        clickText(R.string.merchant_detail_identity)
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_card_action_rename))
            .performScrollTo().assertIsDisplayed().performTouchInput { click() }
        compose.onNode(hasSetTextAction() and hasText("原商家")).performTextReplacement("改名后的商家")
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm))
            .performTouchInput { click() }
        compose.waitUntil(5_000) { updates.size == 1 }
        compose.waitForIdle()
        compose.onNode(hasSetTextAction() and hasText("改名后的商家")).assertIsDisplayed()
        assertEquals("原商家", catalog?.displayName)

        reject = false
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm))
            .performTouchInput { click() }
        compose.waitUntil(5_000) { catalog?.displayName == "改名后的商家" }
        compose.waitForIdle()
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_title)).assertDoesNotExist()
        clickText(R.string.merchant_catalog_section_list)
        clickText(R.string.merchant_management_tools_add_catalog)
        compose.onNode(hasSetTextAction() and hasText("尚未提交的新商家")).performScrollTo().assertIsDisplayed()
        assertEquals(emptyList<MerchantCatalogCreateRequest>(), catalogRequests)
        assertEquals(2, updates.size)
        assertEquals(updates[0], updates[1])
        assertEquals(7L, updates.first().expectedRowVersion)
    }

    @Test fun conflictedRenameReviewsTheSameMerchantAndKeepsTheOriginalInput() {
        catalog = MerchantCatalogDto("existing", "原商家", "原商家", "active", usageCount = 2,
            createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 7)
        reject = false
        showMerchants()
        compose.onNodeWithText("原商家").performScrollTo().performTouchInput { click() }
        clickText(R.string.merchant_detail_identity)
        clickText(R.string.merchant_catalog_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText("原商家")).performTextReplacement("  我的原稿名称  ")
        closeSoftKeyboard()
        catalog = requireNotNull(catalog).copy(displayName = "另一台设备的名称", rowVersion = 8)
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm))
            .assertIsEnabled().performTouchInput { click() }
        compose.waitUntil(5_000) { updates.size == 1 }
        compose.waitForIdle()
        compose.onNode(hasSetTextAction() and hasText("  我的原稿名称  ")).assertIsDisplayed()
        compose.onNodeWithText("核对最新商家").performScrollTo().assertIsDisplayed()

        rejectCatalogRead = true
        compose.onNodeWithText("核对最新商家").performScrollTo().performTouchInput { click() }
        compose.waitForIdle()
        assertEquals(1, updates.size)
        compose.onNode(hasSetTextAction() and hasText("  我的原稿名称  ")).performScrollTo().assertIsDisplayed()
        rejectCatalogRead = false
        compose.onNodeWithText("核对最新商家").performScrollTo().performTouchInput { click() }
        compose.waitUntil(5_000) {
            compose.onAllNodesWithText("当前名称：另一台设备的名称").fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNode(hasSetTextAction() and hasText("  我的原稿名称  ")).performScrollTo().assertIsDisplayed()
        assertEquals(1, updates.size)
        assertEquals("另一台设备的名称", catalog?.displayName)
        saveConsumerArtPreview("merchant-rename-reviewed",
            requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm))
            .assertIsEnabled().performTouchInput { click() }
        compose.waitUntil(5_000) { catalog?.displayName == "我的原稿名称" }
        assertEquals(listOf(7L, 8L), updates.map { it.expectedRowVersion })
        assertEquals("existing", catalog?.publicId)
        assertEquals(9L, catalog?.rowVersion)
        assertTrue(catalogRequests.isEmpty() && aliasRequests.isEmpty())
    }

    @Test fun missingMerchantKeepsTheRenameInputWithoutSubmittingToAnotherObject() {
        catalog = MerchantCatalogDto("existing", "原商家", "原商家", "active", usageCount = 2,
            createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 7)
        showMerchants()
        compose.onNodeWithText("原商家").performScrollTo().performTouchInput { click() }
        clickText(R.string.merchant_detail_identity)
        clickText(R.string.merchant_catalog_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText("原商家")).performTextReplacement("仍需保留的原稿")
        closeSoftKeyboard()
        catalog = null
        compose.onNodeWithText("核对最新商家").performScrollTo().performTouchInput { click() }
        waitForText(R.string.merchant_rename_unavailable)
        compose.onNode(hasSetTextAction() and hasText("仍需保留的原稿")).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm)).assertIsNotEnabled()
        assertTrue(updates.isEmpty() && catalogRequests.isEmpty() && aliasRequests.isEmpty())
        saveConsumerArtPreview("merchant-rename-unavailable",
            requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }

    private fun showMerchants() {
        compose.setContent {
            if (!mounted.value) return@setContent
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                ReferenceLibraryTestTheme {
                    val outer = rememberNavController()
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) {
                            val navigation = rememberNavController()
                            NavHost(navigation, startDestination = TRANSACTIONS_LIBRARY_ROUTE) {
                                transactionsLibraryGraph(navigation, harness.screenFactory, TransactionsLibraryWrites({}, {}, {}))
                            }
                        }
                    }
                }
            }
        }
        waitForText(R.string.transactions_library_merchants_title)
        clickText(R.string.transactions_library_merchants_title)
        waitForText(R.string.merchant_management_tools_add_catalog)
    }

    private fun clickText(label: Int) = compose.onNodeWithText(context.getString(label))
        .performScrollTo().assertIsEnabled().performTouchInput { click() }

    private fun fill(label: Int, value: String, index: Int = 0) {
        // AppTextInput exposes its label as a sibling, not as editable text.
        compose.onNodeWithText(context.getString(label)).performScrollTo().assertIsDisplayed()
        compose.onAllNodes(hasSetTextAction())[index].performTextReplacement(value)
    }

    private fun waitForText(label: Int) = compose.waitUntil(5_000) {
        compose.onAllNodesWithText(context.getString(label)).fetchSemanticsNodes().isNotEmpty()
    }

    private fun unavailable() = HttpException(Response.error<Any>(503,
        """{"error":"service_unavailable","message":"暂时无法保存，请保留当前填写后重试。"}"""
            .toResponseBody("application/json".toMediaType())))
}
