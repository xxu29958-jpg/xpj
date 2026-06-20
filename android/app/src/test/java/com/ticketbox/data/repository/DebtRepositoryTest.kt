package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtForgiveCreateRequestDto
import com.ticketbox.data.remote.dto.DebtKindSetRequestDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.DebtVoidCreateRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalConfirmRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalCreateRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalListResponseDto
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.MemberProposalStatuses
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.lang.reflect.InvocationHandler
import java.lang.reflect.Method
import java.lang.reflect.Proxy
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DebtRepositoryTest {

    @Test
    fun listDebtsMapsDomainModels() = runTest {
        val handler = DebtApiHandler().apply {
            debtsResult = DebtListResponseDto(items = listOf(debtDto(publicId = "d1", remaining = 4_200L)))
        }

        val debts = repository(handler).listDebts().getOrThrow()

        assertEquals(1, debts.size)
        assertEquals("d1", debts.single().publicId)
        assertEquals(4_200L, debts.single().remainingAmountCents)
        assertTrue(debts.single().isExternal)
    }

    @Test
    fun createDebtSendsExternalManualPayloadWithIdempotencyKey() = runTest {
        val handler = DebtApiHandler()

        val created = repository(handler).createDebt(
            DebtDraft(
                direction = DebtDirections.I_OWE,
                counterpartyLabel = "  房东  ",
                principalAmountCents = 50_000,
            ),
        ).getOrThrow()

        val call = handler.createCalls.single()
        assertEquals(DebtDirections.I_OWE, call.request.direction)
        assertEquals(DebtCounterpartyTypes.EXTERNAL, call.request.counterpartyType)
        assertEquals(DebtSourceTypes.MANUAL, call.request.sourceType)
        // The repository trims the label before the request leaves the client.
        assertEquals("房东", call.request.counterpartyLabel)
        assertEquals(50_000L, call.request.principalAmountCents)
        // 8e-6e: an untouched create carries the default kind (unspecified).
        assertEquals(DebtKinds.UNSPECIFIED, call.request.debtKind)
        // ADR-0042: a fresh single-use intent key per direct call.
        assertTrue(!call.idempotencyKey.isNullOrBlank())
        assertEquals("created", created.publicId)
    }

    @Test
    fun createDebtMintsAFreshIdempotencyKeyPerCall() = runTest {
        val handler = DebtApiHandler()
        val repository = repository(handler)
        val draft = DebtDraft(DebtDirections.I_OWE, "房东", 50_000)

        repository.createDebt(draft).getOrThrow()
        repository.createDebt(draft).getOrThrow()

        // ADR-0042: each direct create is a distinct single-use intent — keys must NOT be reused.
        val keys = handler.createCalls.mapNotNull { it.idempotencyKey }
        assertEquals(2, keys.size)
        assertEquals(2, keys.toSet().size)
    }

    @Test
    fun viewerCreateShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore())
            .createDebt(DebtDraft(DebtDirections.I_OWE, "房东", 50_000))

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(handler.createCalls.isEmpty())
    }

    @Test
    fun createRejectsBlankCounterpartyBeforeApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler).createDebt(DebtDraft(DebtDirections.I_OWE, "   ", 50_000))

        assertTrue(result.isFailure)
        assertTrue(handler.createCalls.isEmpty())
    }

    @Test
    fun createRejectsNonPositiveAmountBeforeApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler).createDebt(DebtDraft(DebtDirections.I_OWE, "房东", 0))

        assertTrue(result.isFailure)
        assertTrue(handler.createCalls.isEmpty())
    }

    @Test
    fun listDebtsErrorSurfacesAsFailure() = runTest {
        val handler = DebtApiHandler().apply {
            debtsError = HttpException(
                Response.error<DebtListResponseDto>(
                    404,
                    """{"error":"not_found","message":"没有找到这笔欠款。"}"""
                        .toResponseBody("application/json".toMediaType()),
                ),
            )
        }

        val result = repository(handler).listDebts()

        assertTrue(result.isFailure)
    }

    @Test
    fun getDebtMapsDomainModel() = runTest {
        val handler = DebtApiHandler().apply { debtResult = debtDto(publicId = "d9", remaining = 1_200L) }

        val debt = repository(handler).getDebt("d9").getOrThrow()

        assertEquals("d9", debt.publicId)
        assertEquals(1_200L, debt.remainingAmountCents)
    }

    // ── ADR-0049 ⑤c (slice ⑤c-2) cross-ledger receivables ──────────────────

    @Test
    fun listReceivablesMapsCrossLedgerMemberRows() = runTest {
        val handler = DebtApiHandler().apply {
            receivablesResult = DebtListResponseDto(
                items = listOf(
                    debtDto(publicId = "r1", remaining = 6_000L).copy(
                        counterpartyType = DebtCounterpartyTypes.MEMBER,
                        counterpartyAccountId = 7L,
                        counterpartyLabel = "小王",
                        ledgerId = null,
                        sourceType = DebtSourceTypes.BILL_SPLIT,
                        viewerIsDebtor = false,
                    ),
                ),
            )
        }

        val receivables = repository(handler).listReceivables().getOrThrow()

        assertEquals(1, receivables.size)
        val row = receivables.single()
        assertEquals("r1", row.publicId)
        assertEquals(6_000L, row.remainingAmountCents)
        // ⑤c contract: every row is a member receivable on the creditor side, ledger redacted (§5.2),
        // counterparty_label = the debtor's name.
        assertTrue(row.isMember)
        assertEquals(false, row.viewerIsDebtor)
        assertNull(row.ledgerId)
        assertEquals("小王", row.counterpartyLabel)
    }

    @Test
    fun listReceivablesErrorSurfacesAsFailure() = runTest {
        val handler = DebtApiHandler().apply {
            receivablesError = HttpException(
                Response.error<DebtListResponseDto>(
                    403,
                    """{"error":"invalid_token","message":"没有权限。"}"""
                        .toResponseBody("application/json".toMediaType()),
                ),
            )
        }

        val result = repository(handler).listReceivables()

        assertTrue(result.isFailure)
    }

    @Test
    fun recordRepaymentSendsAmountVersionKeyAndRefolds() = runTest {
        val handler = DebtApiHandler().apply { writeResult = debtDto(publicId = "d1", remaining = 40_000L) }

        val updated = repository(handler).recordRepayment(
            publicId = "d1",
            expectedRowVersion = 3L,
            amountCents = 10_000L,
        ).getOrThrow()

        val call = handler.repaymentCalls.single()
        assertEquals("d1", call.publicId)
        assertEquals(10_000L, call.request.amountCents)
        assertEquals(3L, call.request.expectedRowVersion)
        assertTrue(!call.idempotencyKey.isNullOrBlank())
        // The fold-after Debt from the response is swapped in (remaining dropped to 40_000).
        assertEquals(40_000L, updated.remainingAmountCents)
    }

    @Test
    fun recordRepaymentRejectsNonPositiveAmountBeforeApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler).recordRepayment("d1", expectedRowVersion = 1L, amountCents = 0L)

        assertTrue(result.isFailure)
        assertTrue(handler.repaymentCalls.isEmpty())
    }

    @Test
    fun recordRepaymentViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore())
            .recordRepayment("d1", expectedRowVersion = 1L, amountCents = 10_000L)

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(handler.repaymentCalls.isEmpty())
    }

    @Test
    fun recordRepaymentMintsFreshKeyPerCall() = runTest {
        val handler = DebtApiHandler()
        val repository = repository(handler)

        repository.recordRepayment("d1", expectedRowVersion = 1L, amountCents = 10_000L).getOrThrow()
        repository.recordRepayment("d1", expectedRowVersion = 2L, amountCents = 10_000L).getOrThrow()

        val keys = handler.repaymentCalls.mapNotNull { it.idempotencyKey }
        assertEquals(2, keys.size)
        assertEquals(2, keys.toSet().size)
    }

    @Test
    fun recordAdjustmentSendsSignedAmountTrimmedReasonAndVersion() = runTest {
        val handler = DebtApiHandler()

        repository(handler).recordAdjustment(
            publicId = "d1",
            expectedRowVersion = 2L,
            amountCents = -5_000L,
            reason = "  减免部分  ",
        ).getOrThrow()

        val call = handler.adjustmentCalls.single()
        assertEquals(-5_000L, call.request.amountCents)
        // The repository trims the reason before the request leaves the client.
        assertEquals("减免部分", call.request.reason)
        assertEquals(2L, call.request.expectedRowVersion)
        assertTrue(!call.idempotencyKey.isNullOrBlank())
    }

    @Test
    fun recordAdjustmentRejectsZeroAmountBeforeApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler).recordAdjustment("d1", expectedRowVersion = 1L, amountCents = 0L, reason = "x")

        assertTrue(result.isFailure)
        assertTrue(handler.adjustmentCalls.isEmpty())
    }

    @Test
    fun recordAdjustmentRejectsBlankReasonBeforeApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler).recordAdjustment("d1", expectedRowVersion = 1L, amountCents = 100L, reason = "   ")

        assertTrue(result.isFailure)
        assertTrue(handler.adjustmentCalls.isEmpty())
    }

    @Test
    fun recordAdjustmentViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore())
            .recordAdjustment("d1", expectedRowVersion = 1L, amountCents = 100L, reason = "x")

        assertTrue(result.isFailure)
        assertTrue(handler.adjustmentCalls.isEmpty())
    }

    @Test
    fun voidDebtSendsTrimmedReasonVersionAndKey() = runTest {
        val handler = DebtApiHandler()

        repository(handler).voidDebt(publicId = "d1", expectedRowVersion = 4L, reason = "  记错了  ").getOrThrow()

        val call = handler.voidCalls.single()
        assertEquals("记错了", call.request.reason)
        assertEquals(4L, call.request.expectedRowVersion)
        assertTrue(!call.idempotencyKey.isNullOrBlank())
    }

    @Test
    fun voidDebtRejectsBlankReasonBeforeApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler).voidDebt("d1", expectedRowVersion = 1L, reason = "   ")

        assertTrue(result.isFailure)
        assertTrue(handler.voidCalls.isEmpty())
    }

    @Test
    fun voidDebtViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore()).voidDebt("d1", expectedRowVersion = 1L, reason = "x")

        assertTrue(result.isFailure)
        assertTrue(handler.voidCalls.isEmpty())
    }

    // ── ADR-0049 §7.0 / 8e-6e debt_kind correction setter ───────────────────

    @Test
    fun setDebtKindSendsKindVersionKeyAndRefolds() = runTest {
        val handler = DebtApiHandler().apply {
            setKindResult = debtDto(publicId = "d1", remaining = 50_000L)
                .copy(debtKind = DebtKinds.REVOLVING, rowVersion = 4)
        }

        val updated = repository(handler).setDebtKind(
            publicId = "d1",
            expectedRowVersion = 3L,
            debtKind = DebtKinds.REVOLVING,
        ).getOrThrow()

        val call = handler.setKindCalls.single()
        assertEquals("d1", call.publicId)
        assertEquals(DebtKinds.REVOLVING, call.request.debtKind)
        assertEquals(3L, call.request.expectedRowVersion)
        assertTrue(!call.idempotencyKey.isNullOrBlank())
        // The fold-after Debt is swapped in (fresh row_version + the new kind).
        assertEquals(DebtKinds.REVOLVING, updated.debtKind)
        assertEquals(4L, updated.rowVersion)
    }

    @Test
    fun setDebtKindViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore())
            .setDebtKind("d1", expectedRowVersion = 1L, debtKind = DebtKinds.ONE_OFF)

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(handler.setKindCalls.isEmpty())
    }

    @Test
    fun setDebtKindMintsFreshKeyPerCall() = runTest {
        val handler = DebtApiHandler()
        val repository = repository(handler)

        // ADR-0042: each direct reclassification is a distinct single-use intent — keys must NOT repeat.
        repository.setDebtKind("d1", expectedRowVersion = 1L, debtKind = DebtKinds.REVOLVING).getOrThrow()
        repository.setDebtKind("d1", expectedRowVersion = 2L, debtKind = DebtKinds.INSTALLMENT).getOrThrow()

        val keys = handler.setKindCalls.mapNotNull { it.idempotencyKey }
        assertEquals(2, keys.size)
        assertEquals(2, keys.toSet().size)
    }

    // ── ADR-0049 §3.2 (slice 8d) member repayment proposals ─────────────────

    @Test
    fun listRepaymentProposalsMapsDomainModels() = runTest {
        val handler = DebtApiHandler().apply {
            proposalsResult = MemberRepaymentProposalListResponseDto(
                items = listOf(proposalDto(publicId = "p1", proposed = 4_200L)),
            )
        }

        val proposals = repository(handler).proposals.listRepaymentProposals("d1").getOrThrow()

        assertEquals(1, proposals.size)
        assertEquals("p1", proposals.single().publicId)
        assertEquals(4_200L, proposals.single().proposedAmountCents)
        assertTrue(proposals.single().isPending)
    }

    @Test
    fun proposeSendsTrimmedAmountNoteKeyAndOmitsSupersedes() = runTest {
        val handler = DebtApiHandler()

        repository(handler).proposals.proposeRepayment(
            debtPublicId = "d1",
            proposedAmountCents = 15_000L,
            note = "  微信转账  ",
            supersedesProposalPublicId = null,
        ).getOrThrow()

        val call = handler.proposeCalls.single()
        assertEquals("d1", call.publicId)
        assertEquals(15_000L, call.request.proposedAmountCents)
        // The repository trims the note and omits a null supersedes target.
        assertEquals("微信转账", call.request.note)
        assertNull(call.request.supersedesProposalPublicId)
        assertTrue(!call.idempotencyKey.isNullOrBlank())
    }

    @Test
    fun proposeViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore())
            .proposals.proposeRepayment("d1", 15_000L, note = null, supersedesProposalPublicId = null)

        assertTrue(result.isFailure)
        assertTrue(handler.proposeCalls.isEmpty())
    }

    @Test
    fun proposeRejectsNonPositiveAmountBeforeApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler).proposals.proposeRepayment("d1", 0L, note = null, supersedesProposalPublicId = null)

        assertTrue(result.isFailure)
        assertTrue(handler.proposeCalls.isEmpty())
    }

    @Test
    fun withdrawSendsKeyAndMapsProposal() = runTest {
        val handler = DebtApiHandler()

        val withdrawn = repository(handler).proposals.withdrawRepaymentProposal("d1", "p1").getOrThrow()

        val call = handler.withdrawProposalCalls.single()
        assertEquals("d1", call.publicId)
        assertEquals("p1", call.proposalPublicId)
        assertTrue(!call.idempotencyKey.isNullOrBlank())
        assertEquals("p1", withdrawn.publicId)
    }

    @Test
    fun confirmFullSendsRowVersionKeyAndReturnsFoldAfterDebt() = runTest {
        val handler = DebtApiHandler().apply { confirmResult = debtDto(publicId = "d1", remaining = 40_000L) }

        val updated = repository(handler).proposals.confirmRepaymentProposal(
            debtPublicId = "d1",
            proposalPublicId = "p1",
            expectedRowVersion = 5L,
            confirmedAmountCents = null,
        ).getOrThrow()

        val call = handler.confirmProposalCalls.single()
        assertEquals("p1", call.proposalPublicId)
        assertEquals(5L, call.request.expectedRowVersion)
        // A full confirm carries no explicit amount.
        assertNull(call.request.confirmedAmountCents)
        assertTrue(!call.idempotencyKey.isNullOrBlank())
        // Confirm replies with the fold-after Debt (remaining dropped to 40_000).
        assertEquals(40_000L, updated.remainingAmountCents)
    }

    @Test
    fun confirmPartialSendsConfirmedAmount() = runTest {
        val handler = DebtApiHandler()

        repository(handler).proposals.confirmRepaymentProposal(
            debtPublicId = "d1",
            proposalPublicId = "p1",
            expectedRowVersion = 5L,
            confirmedAmountCents = 15_000L,
        ).getOrThrow()

        assertEquals(15_000L, handler.confirmProposalCalls.single().request.confirmedAmountCents)
    }

    @Test
    fun confirmRejectsNonPositiveConfirmedAmountBeforeApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler).proposals.confirmRepaymentProposal("d1", "p1", expectedRowVersion = 5L, confirmedAmountCents = 0L)

        assertTrue(result.isFailure)
        assertTrue(handler.confirmProposalCalls.isEmpty())
    }

    @Test
    fun confirmViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore())
            .proposals.confirmRepaymentProposal("d1", "p1", expectedRowVersion = 5L, confirmedAmountCents = null)

        assertTrue(result.isFailure)
        assertTrue(handler.confirmProposalCalls.isEmpty())
    }

    @Test
    fun rejectSendsKeyAndMapsProposal() = runTest {
        val handler = DebtApiHandler()

        repository(handler).proposals.rejectRepaymentProposal("d1", "p1").getOrThrow()

        val call = handler.rejectProposalCalls.single()
        assertEquals("d1", call.publicId)
        assertEquals("p1", call.proposalPublicId)
        assertTrue(!call.idempotencyKey.isNullOrBlank())
    }

    @Test
    fun withdrawViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore()).proposals.withdrawRepaymentProposal("d1", "p1")

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(handler.withdrawProposalCalls.isEmpty())
    }

    @Test
    fun rejectViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore()).proposals.rejectRepaymentProposal("d1", "p1")

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(handler.rejectProposalCalls.isEmpty())
    }

    @Test
    fun proposalWritesMintFreshKeyPerCall() = runTest {
        val handler = DebtApiHandler()
        val repository = repository(handler)

        // ADR-0042: every proposal write (propose/confirm/withdraw/reject) is a distinct single-use
        // intent — each call must mint a fresh, non-repeating key.
        repeat(2) {
            repository.proposals.proposeRepayment("d1", 10_000L, note = null, supersedesProposalPublicId = null).getOrThrow()
            repository.proposals.confirmRepaymentProposal("d1", "p1", expectedRowVersion = 1L, confirmedAmountCents = null).getOrThrow()
            repository.proposals.withdrawRepaymentProposal("d1", "p1").getOrThrow()
            repository.proposals.rejectRepaymentProposal("d1", "p1").getOrThrow()
        }

        assertEquals(2, handler.proposeCalls.mapNotNull { it.idempotencyKey }.toSet().size)
        assertEquals(2, handler.confirmProposalCalls.mapNotNull { it.idempotencyKey }.toSet().size)
        assertEquals(2, handler.withdrawProposalCalls.mapNotNull { it.idempotencyKey }.toSet().size)
        assertEquals(2, handler.rejectProposalCalls.mapNotNull { it.idempotencyKey }.toSet().size)
    }

    @Test
    fun forgiveSendsRowVersionKeyAndReturnsForgivenFoldAfterDebt() = runTest {
        val handler = DebtApiHandler().apply {
            forgiveResult = debtDto(publicId = "d1", remaining = 0L, status = DebtLinkStatuses.CLEARED, isForgiven = true)
        }

        val updated = repository(handler).proposals.forgiveDebt(debtPublicId = "d1", expectedRowVersion = 7L).getOrThrow()

        val call = handler.forgiveCalls.single()
        assertEquals("d1", call.publicId)
        assertEquals(7L, call.request.expectedRowVersion)
        // ADR-0042: a fresh single-use intent key per direct call.
        assertTrue(!call.idempotencyKey.isNullOrBlank())
        // Forgive replies with the fold-after Debt (cleared + is_forgiven carried through the mapper).
        assertTrue(updated.isCleared)
        assertTrue(updated.isForgiven)
    }

    @Test
    fun forgiveViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore())
            .proposals.forgiveDebt("d1", expectedRowVersion = 1L)

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(handler.forgiveCalls.isEmpty())
    }

    @Test
    fun forgiveMintsFreshKeyPerCall() = runTest {
        val handler = DebtApiHandler()
        val repository = repository(handler)

        // ADR-0042: each direct forgive is a distinct single-use intent — keys must NOT be reused.
        repository.proposals.forgiveDebt("d1", expectedRowVersion = 1L).getOrThrow()
        repository.proposals.forgiveDebt("d1", expectedRowVersion = 2L).getOrThrow()

        val keys = handler.forgiveCalls.mapNotNull { it.idempotencyKey }
        assertEquals(2, keys.size)
        assertEquals(2, keys.toSet().size)
    }

    private fun repository(
        handler: DebtApiHandler,
        settings: FakeTicketboxSettingsStore = boundSettingsStore(),
    ): DebtRepository {
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        return DebtRepository(
            apiClient = DebtApiFactory(handler),
            settingsStore = settings,
            tokenStore = tokenStore,
        )
    }

    private fun viewerSettingsStore(): FakeTicketboxSettingsStore =
        FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = "viewer",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
}

private fun debtDto(
    publicId: String = "debt-1",
    remaining: Long = 30_000L,
    status: String = DebtLinkStatuses.OPEN,
    isForgiven: Boolean = false,
): DebtDto = DebtDto(
    publicId = publicId,
    ledgerId = "owner",
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyAccountId = null,
    counterpartyLabel = "房东",
    principalAmountCents = 50_000,
    remainingAmountCents = remaining,
    paidAmountCents = 50_000 - remaining,
    status = status,
    sourceType = DebtSourceTypes.MANUAL,
    sourceId = null,
    homeCurrencyCode = "CNY",
    createdAt = "2026-06-15T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = 1,
    isForgiven = isForgiven,
)

private class DebtApiFactory(private val handler: DebtApiHandler) : ApiServiceFactory {
    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = handler.service()
}

private data class CreateDebtCall(val request: DebtCreateRequestDto, val idempotencyKey: String?)
private data class RepaymentCall(val publicId: String, val request: RepaymentCreateRequestDto, val idempotencyKey: String?)
private data class AdjustmentCall(val publicId: String, val request: DebtAdjustmentCreateRequestDto, val idempotencyKey: String?)
private data class VoidCall(val publicId: String, val request: DebtVoidCreateRequestDto, val idempotencyKey: String?)
private data class SetKindCall(val publicId: String, val request: DebtKindSetRequestDto, val idempotencyKey: String?)
private data class ForgiveCall(val publicId: String, val request: DebtForgiveCreateRequestDto, val idempotencyKey: String?)
private data class ProposeProposalCall(
    val publicId: String,
    val request: MemberRepaymentProposalCreateRequestDto,
    val idempotencyKey: String?,
)
private data class WithdrawProposalCall(val publicId: String, val proposalPublicId: String, val idempotencyKey: String?)
private data class ConfirmProposalCall(
    val publicId: String,
    val proposalPublicId: String,
    val request: MemberRepaymentProposalConfirmRequestDto,
    val idempotencyKey: String?,
)
private data class RejectProposalCall(val publicId: String, val proposalPublicId: String, val idempotencyKey: String?)

private fun proposalDto(publicId: String = "p1", proposed: Long = 20_000L): MemberRepaymentProposalDto =
    MemberRepaymentProposalDto(
        publicId = publicId,
        debtPublicId = "d1",
        status = MemberProposalStatuses.PENDING,
        proposedAmountCents = proposed,
        homeCurrencyCode = "CNY",
        paidAt = "2026-06-16T00:00:00Z",
        expiresAt = "2026-07-16T00:00:00Z",
        createdAt = "2026-06-16T00:00:00Z",
    )

private class DebtApiHandler : InvocationHandler {
    val createCalls = mutableListOf<CreateDebtCall>()
    val repaymentCalls = mutableListOf<RepaymentCall>()
    val adjustmentCalls = mutableListOf<AdjustmentCall>()
    val voidCalls = mutableListOf<VoidCall>()
    // ADR-0049 §7.0 / 8e-6e debt_kind correction-setter route recording.
    val setKindCalls = mutableListOf<SetKindCall>()
    var setKindResult: DebtDto? = null
    // ADR-0049 §3.2 (slice 8d) proposal-route recordings.
    val proposeCalls = mutableListOf<ProposeProposalCall>()
    val withdrawProposalCalls = mutableListOf<WithdrawProposalCall>()
    val confirmProposalCalls = mutableListOf<ConfirmProposalCall>()
    val rejectProposalCalls = mutableListOf<RejectProposalCall>()
    // ADR-0049 §3.7 / §4 (slice 8e-3) creditor-forgive route recording.
    val forgiveCalls = mutableListOf<ForgiveCall>()
    var forgiveResult: DebtDto? = null
    var debtsResult: DebtListResponseDto? = null
    var debtsError: Throwable? = null
    // ADR-0049 ⑤c (slice ⑤c-2) cross-ledger receivables read.
    var receivablesResult: DebtListResponseDto? = null
    var receivablesError: Throwable? = null
    // Fold-after Debt returned by getDebt / the write routes (defaults to a fresh sample).
    var debtResult: DebtDto? = null
    var writeResult: DebtDto? = null
    var proposalsResult: MemberRepaymentProposalListResponseDto? = null
    var proposalResult: MemberRepaymentProposalDto? = null
    // Fold-after Debt returned by the confirm route (a DebtResponse, like the slice-2 fact writes).
    var confirmResult: DebtDto? = null

    fun service(): ApiService = Proxy.newProxyInstance(
        ApiService::class.java.classLoader,
        arrayOf(ApiService::class.java),
        this,
    ) as ApiService

    override fun invoke(proxy: Any, method: Method, args: Array<out Any?>?): Any? {
        if (method.declaringClass == Any::class.java) {
            return when (method.name) {
                "toString" -> "DebtApiProxy"
                "hashCode" -> System.identityHashCode(proxy)
                "equals" -> proxy === args?.firstOrNull()
                else -> null
            }
        }
        // Suspend methods arrive with a trailing Continuation; real params are the leading ones.
        val values = args.orEmpty()
        return when (method.name) {
            "debts" -> {
                debtsError?.let { throw it }
                debtsResult ?: DebtListResponseDto(items = listOf(debtDto()))
            }
            "debtReceivables" -> {
                receivablesError?.let { throw it }
                receivablesResult ?: DebtListResponseDto(items = listOf(debtDto()))
            }
            "debt" -> debtResult ?: debtDto(publicId = values[0] as String)
            "createDebt" -> {
                createCalls += CreateDebtCall(
                    request = values[0] as DebtCreateRequestDto,
                    idempotencyKey = values[1] as String?,
                )
                debtDto(publicId = "created")
            }
            "recordDebtRepayment" -> {
                repaymentCalls += RepaymentCall(
                    publicId = values[0] as String,
                    request = values[1] as RepaymentCreateRequestDto,
                    idempotencyKey = values[2] as String?,
                )
                writeResult ?: debtDto(publicId = values[0] as String)
            }
            "recordDebtAdjustment" -> {
                adjustmentCalls += AdjustmentCall(
                    publicId = values[0] as String,
                    request = values[1] as DebtAdjustmentCreateRequestDto,
                    idempotencyKey = values[2] as String?,
                )
                writeResult ?: debtDto(publicId = values[0] as String)
            }
            "voidDebt" -> {
                voidCalls += VoidCall(
                    publicId = values[0] as String,
                    request = values[1] as DebtVoidCreateRequestDto,
                    idempotencyKey = values[2] as String?,
                )
                writeResult ?: debtDto(publicId = values[0] as String)
            }
            // ADR-0049 §3.2 (slice 8d) proposal routes are dispatched in a helper so invoke stays
            // under the LongMethod gate (the slice-2 fact arms already fill it).
            else -> proposalCall(method.name, values)
        }
    }

    private fun proposalCall(name: String, values: Array<out Any?>): Any? = when (name) {
        "repaymentProposals" ->
            proposalsResult ?: MemberRepaymentProposalListResponseDto(items = listOf(proposalDto()))
        "createRepaymentProposal" -> {
            proposeCalls += ProposeProposalCall(
                publicId = values[0] as String,
                request = values[1] as MemberRepaymentProposalCreateRequestDto,
                idempotencyKey = values[2] as String?,
            )
            proposalResult ?: proposalDto()
        }
        "withdrawRepaymentProposal" -> {
            withdrawProposalCalls += WithdrawProposalCall(
                publicId = values[0] as String,
                proposalPublicId = values[1] as String,
                idempotencyKey = values[3] as String?,
            )
            proposalResult ?: proposalDto(publicId = values[1] as String)
        }
        "confirmRepaymentProposal" -> {
            confirmProposalCalls += ConfirmProposalCall(
                publicId = values[0] as String,
                proposalPublicId = values[1] as String,
                request = values[2] as MemberRepaymentProposalConfirmRequestDto,
                idempotencyKey = values[3] as String?,
            )
            confirmResult ?: debtDto(publicId = values[0] as String)
        }
        "rejectRepaymentProposal" -> {
            rejectProposalCalls += RejectProposalCall(
                publicId = values[0] as String,
                proposalPublicId = values[1] as String,
                idempotencyKey = values[3] as String?,
            )
            proposalResult ?: proposalDto(publicId = values[1] as String)
        }
        // forgive / setDebtKind are NOT proposals; split into a second helper so neither this
        // dispatch nor invoke trips the CyclomaticComplexMethod / LongMethod gates as routes grow.
        else -> debtFactWriteCall(name, values)
    }

    private fun debtFactWriteCall(name: String, values: Array<out Any?>): Any? = when (name) {
        "forgiveDebt" -> {
            forgiveCalls += ForgiveCall(
                publicId = values[0] as String,
                request = values[1] as DebtForgiveCreateRequestDto,
                idempotencyKey = values[2] as String?,
            )
            forgiveResult ?: debtDto(publicId = values[0] as String)
        }
        "setDebtKind" -> {
            setKindCalls += SetKindCall(
                publicId = values[0] as String,
                request = values[1] as DebtKindSetRequestDto,
                idempotencyKey = values[2] as String?,
            )
            setKindResult ?: debtDto(publicId = values[0] as String)
        }
        else -> error("unexpected ApiService call: $name")
    }
}
