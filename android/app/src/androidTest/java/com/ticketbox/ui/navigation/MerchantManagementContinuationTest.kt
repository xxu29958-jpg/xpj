package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MerchantCatalogCreateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogListDto
import com.ticketbox.data.remote.dto.MerchantCatalogUpdateRequest
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
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
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun merchantCatalog(includeHidden: Boolean) = MerchantCatalogListDto(listOfNotNull(catalog))
            override suspend fun merchantAliases() = MerchantAliasListDto(listOfNotNull(alias))
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
                return requireNotNull(catalog).copy(displayName = requireNotNull(request.displayName), rowVersion = 8)
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

    @Test fun rejectedAliasCreationKeepsBothOriginalNamesUntilAccepted() {
        showMerchants()
        clickText(R.string.merchant_management_tools_add_alias)
        fill(R.string.merchant_aliases_canonical_label, "差旅商家")
        fill(R.string.merchant_aliases_alias_label, "PAY-差旅原始商家")
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
        compose.onNodeWithContentDescription(context.getString(R.string.merchant_catalog_actions_content_description))
            .performScrollTo().performTouchInput { click() }
        clickText(R.string.merchant_catalog_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText("原商家")).performTextReplacement("改名后的商家")
        clickText(R.string.merchant_catalog_rename_dialog_confirm)
        compose.waitUntil(5_000) { updates.size == 1 }
        compose.waitForIdle()
        compose.onNode(hasSetTextAction() and hasText("改名后的商家")).assertIsDisplayed()
        assertEquals("原商家", catalog?.displayName)

        reject = false
        clickText(R.string.merchant_catalog_rename_dialog_confirm)
        compose.waitUntil(5_000) { catalog?.displayName == "改名后的商家" }
        compose.waitForIdle()
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_title)).assertDoesNotExist()
        compose.onNode(hasSetTextAction() and hasText("尚未提交的新商家")).performScrollTo().assertIsDisplayed()
        assertEquals(emptyList<MerchantCatalogCreateRequest>(), catalogRequests)
        assertEquals(2, updates.size)
        assertEquals(updates[0], updates[1])
        assertEquals(7L, updates.first().expectedRowVersion)
    }

    private fun showMerchants() {
        compose.setContent {
            if (!mounted.value) return@setContent
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    val outer = rememberNavController()
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) {
                            val navigation = rememberNavController()
                            NavHost(navigation, startDestination = TRANSACTIONS_LIBRARY_ROUTE) {
                                transactionsLibraryGraph(navigation, harness.screenFactory, {}, {}, {})
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
        .performScrollTo().performTouchInput { click() }

    private fun fill(label: Int, value: String) = compose.onNode(hasSetTextAction() and hasText(context.getString(label)))
        .performScrollTo().performTextReplacement(value)

    private fun waitForText(label: Int) = compose.waitUntil(5_000) {
        compose.onAllNodesWithText(context.getString(label)).fetchSemanticsNodes().isNotEmpty()
    }

    private fun unavailable() = HttpException(Response.error<Any>(503,
        """{"error":"service_unavailable","message":"暂时无法保存，请保留当前填写后重试。"}"""
            .toResponseBody("application/json".toMediaType())))
}
