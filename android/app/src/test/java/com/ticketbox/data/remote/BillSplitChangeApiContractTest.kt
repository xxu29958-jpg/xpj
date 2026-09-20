package com.ticketbox.data.remote

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import com.ticketbox.data.remote.dto.BillSplitChangeAcceptRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeCreateRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeEmptyRequestDto
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class BillSplitChangeApiContractTest {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    @Test fun agreementPreservesSignedSettlementSeparateFromSharesAndParticipantDebtShells() {
        val adapter = moshi.adapter(BillSplitAgreementDto::class.java)
        val agreement = requireNotNull(adapter.fromJson(agreementJson()))
        assertEquals("invitation-1", agreement.invitationPublicId)
        assertEquals(5_000_000_000L, agreement.originalShareAmountCents)
        assertEquals(3_000_000_000L, agreement.agreedShareAmountCents)
        assertEquals(-2_000_000_000L, agreement.settlementNetAmountCents)
        assertEquals(5_000_000_000L, agreement.originalPaidAmountCents)
        assertEquals(0L, agreement.returnPaidAmountCents)
        assertEquals(0L, agreement.originalForgivenAmountCents)
        assertEquals(0L, agreement.returnForgivenAmountCents)
        assertTrue(agreement.viewerIsParty)
        assertEquals("JPY", agreement.homeCurrencyCode)
        assertEquals(listOf("return-1"), agreement.pendingRepaymentDebtPublicIds)
        assertNull(agreement.originalDebt.ledgerId)
        val returned = requireNotNull(agreement.returnDebt)
        assertNull(returned.ledgerId)
        assertEquals("owed_to_me", returned.direction)
        assertEquals(true, returned.viewerIsDebtor)
        val pending = requireNotNull(agreement.pendingProposal)
        assertEquals(4_294_967_296L, pending.originalDebtRowVersion)
        assertEquals(4_294_967_297L, pending.returnDebtRowVersion)
        assertEquals(-2_000_000_000L, pending.settlementNetAmountCents)
        assertEquals("return-1", pending.returnDebtPublicId)
        assertFalse(pending.proposedByYou)
        assertNull(pending.resolvedAt)
        assertNull(agreement.preview.cashBasedSettlementNetAmountCents)
        assertTrue(agreement.preview.requiresExplicitSettlement)
        assertEquals(agreement, adapter.fromJson(adapter.toJson(agreement)))
    }

    @Test fun commandBodiesKeepBothVersionsSignedSettlementAndExplicitEmptyBody() {
        val create = moshi.adapter(BillSplitChangeCreateRequestDto::class.java)
        assertEquals(
            """{"new_share_amount_cents":0,"settlement_net_amount_cents":-5000000000,"reason":"双方重新约定","expected_row_version":4294967296,"expected_return_row_version":4294967297,"supersedes_proposal_public_id":"previous-1"}""",
            create.toJson(BillSplitChangeCreateRequestDto(0, -5_000_000_000L, "双方重新约定",
                4_294_967_296L, 4_294_967_297L, "previous-1")),
        )
        assertEquals(
            """{"new_share_amount_cents":0,"settlement_net_amount_cents":0,"reason":"取消承担","expected_row_version":7}""",
            create.toJson(BillSplitChangeCreateRequestDto(0, 0, "取消承担", 7)),
        )
        val accept = moshi.adapter(BillSplitChangeAcceptRequestDto::class.java)
        assertEquals("""{"expected_row_version":4294967296,"expected_return_row_version":4294967297}""",
            accept.toJson(BillSplitChangeAcceptRequestDto(4_294_967_296L, 4_294_967_297L)))
        assertEquals("{}", moshi.adapter(BillSplitChangeEmptyRequestDto::class.java)
            .toJson(BillSplitChangeEmptyRequestDto()))
    }

    @Test fun agreementGetOmitsAbsentPreviewAndRetainsZeroShareQuery() = runBlocking {
        val observed = mutableListOf<Request>()
        val api = api { request -> observed += request; agreementJson() }
        assertEquals("invitation-1", api.splitAgreement("original-1").invitationPublicId)
        assertEquals("invitation-1", api.splitAgreement("original-1", 0).invitationPublicId)
        assertEquals(listOf("GET", "GET"), observed.map { it.method })
        observed.forEach {
            assertEquals("/api/debts/original-1/split-agreement", it.url.encodedPath)
            assertNull(it.header("Idempotency-Key"))
        }
        assertNull(observed[0].url.encodedQuery)
        assertEquals("0", observed[1].url.queryParameter("new_share_amount_cents"))
    }

    @Test fun proposalEndpointsPreserveTargetBodyAndOriginalCommandKey() = runBlocking {
        val observed = mutableListOf<Request>()
        val bodies = mutableListOf<String>()
        val api = api { request ->
            observed += request
            bodies += request.body?.let { Buffer().also(it::writeTo).readUtf8() }.orEmpty()
            if (request.url.encodedPath.endsWith("/accept")) agreementJson() else proposalJson()
        }
        assertEquals("change-1", api.createSplitChangeProposal("original-1",
            BillSplitChangeCreateRequestDto(0, -5_000_000_000L, "新约定", 7), "create-key").publicId)
        assertEquals("invitation-1", api.acceptSplitChangeProposal("original-1", "change-1",
            BillSplitChangeAcceptRequestDto(7, 8), "accept-key").invitationPublicId)
        assertEquals("change-1", api.rejectSplitChangeProposal("original-1", "change-1",
            BillSplitChangeEmptyRequestDto(), "reject-key").publicId)
        assertEquals("change-1", api.withdrawSplitChangeProposal("original-1", "change-1",
            BillSplitChangeEmptyRequestDto(), "withdraw-key").publicId)
        assertEquals(List(4) { "POST" }, observed.map { it.method })
        assertEquals(listOf("", "/change-1/accept", "/change-1/reject", "/change-1/withdraw"),
            observed.map { it.url.encodedPath.removePrefix("/api/debts/original-1/split-change-proposals") })
        assertEquals(listOf("create-key", "accept-key", "reject-key", "withdraw-key"),
            observed.map { it.header("Idempotency-Key") })
        assertEquals("""{"new_share_amount_cents":0,"settlement_net_amount_cents":-5000000000,"reason":"新约定","expected_row_version":7}""", bodies[0])
        assertEquals("""{"expected_row_version":7,"expected_return_row_version":8}""", bodies[1])
        assertEquals(listOf("{}", "{}"), bodies.drop(2))
    }

    private fun api(respond: (Request) -> String): ApiService {
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            val request = chain.request()
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("Controlled response")
                .body(respond(request).toResponseBody("application/json".toMediaType())).build()
        }.build()
        return buildApiService("https://example.test/", client)
    }

    private fun agreementJson(): String = """{
        "invitation_public_id":"invitation-1","home_currency_code":"JPY",
        "original_share_amount_cents":5000000000,"agreed_share_amount_cents":3000000000,
        "original_debt":${debtJson("original-1", "i_owe", false)},
        "return_debt":${debtJson("return-1", "owed_to_me", true)},"viewer_is_party":true,
        "original_paid_amount_cents":5000000000,"return_paid_amount_cents":0,
        "original_forgiven_amount_cents":0,"return_forgiven_amount_cents":0,
        "settlement_net_amount_cents":-2000000000,"pending_repayment_debt_public_ids":["return-1"],
        "pending_proposal":${proposalJson()},"preview":{"new_share_amount_cents":3000000000,
        "default_settlement_net_amount_cents":-2000000000,"cash_based_settlement_net_amount_cents":null,
        "requires_explicit_settlement":true}}"""

    private fun proposalJson(): String = """{
        "public_id":"change-1","original_debt_public_id":"original-1","return_debt_public_id":"return-1",
        "status":"pending","proposed_by_you":false,"share_before_amount_cents":5000000000,
        "new_share_amount_cents":3000000000,"settlement_before_net_amount_cents":0,
        "settlement_net_amount_cents":-2000000000,"original_paid_amount_cents":5000000000,
        "return_paid_amount_cents":0,"original_forgiven_amount_cents":0,"return_forgiven_amount_cents":0,
        "original_debt_row_version":4294967296,"return_debt_row_version":4294967297,"reason":"双方重新约定",
        "created_at":"2026-09-20T01:00:00Z","expires_at":"2026-09-27T01:00:00Z","resolved_at":null}"""

    private fun debtJson(publicId: String, direction: String, debtor: Boolean): String = """{
        "public_id":"$publicId","ledger_id":null,"direction":"$direction","counterparty_type":"member",
        "principal_amount_cents":5000000000,"remaining_amount_cents":2000000000,"paid_amount_cents":3000000000,
        "status":"open","source_type":"bill_split","source_id":"invitation-1","home_currency_code":"JPY",
        "created_at":"2026-09-20T01:00:00Z","updated_at":"2026-09-20T01:00:00Z","row_version":4294967296,
        "viewer_is_debtor":$debtor}"""
}
