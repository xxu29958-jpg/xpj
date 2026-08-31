package com.ticketbox.viewmodel

import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.data.repository.ItemsAckOutcome
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseCorrectionOutcome
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.ExpenseRevisionPage
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.ItemsSumStatus
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.RepaymentDraft
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain

@OptIn(ExperimentalCoroutinesApi::class)
internal abstract class ExpenseFactViewModelTestBase {
    protected fun edit(block: suspend TestScope.(FakeExpenseFactActions) -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block(FakeExpenseFactActions())
        } finally {
            Dispatchers.resetMain()
        }
    }

    protected fun TestScope.viewModel(fake: FakeExpenseFactActions): ExpenseFactViewModel {
        val viewModel = ExpenseFactViewModel(expenseId = 7L, repository = fake)
        advanceUntilIdle()
        return viewModel
    }
}

/** Shared real-shape repository fake for the confirmed fact ViewModel tests. */
@Suppress("TooManyFunctions")
internal class FakeExpenseFactActions : ExpenseFactActions {
    var canModifyLedgerFlag: Boolean = true

    var baseExpense: Expense = Expense(
        id = 7L,
        publicId = "pub-7",
        amountCents = 1000L,
        homeCurrencyCode = "CNY",
        originalCurrency = CurrencyCode.CNY,
        originalCurrencyCode = CurrencyCode.CNY,
        originalAmountMinor = 1000L,
        merchant = "旧商家",
        category = "餐饮",
        note = null,
        source = "manual",
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "confirmed",
        expenseTime = null,
        createdAt = "2026-08-22T11:38:00Z",
        updatedAt = "2026-08-22T11:38:00Z",
        rowVersion = 1L,
        factRevision = 1L,
        confirmedAt = "2026-08-22T11:38:00Z",
        rejectedAt = null,
    )

    var itemsResult: Result<ExpenseItems> = Result.success(
        ExpenseItems(
            expenseId = 7L,
            parentAmountCents = 1000L,
            itemsTotalAmountCents = null,
            mismatchCents = null,
            items = emptyList(),
        ),
    )
    var splitsResult: Result<ExpenseSplits> = Result.success(
        ExpenseSplits(
            expenseId = 7L,
            parentAmountCents = 1000L,
            splitsTotalAmountCents = null,
            mismatchCents = null,
            splits = emptyList(),
        ),
    )
    var correctResult: (Expense, ExpenseCorrectionDraft) -> Result<ExpenseCorrectionOutcome> =
        { expense, draft ->
            Result.success(
                ExpenseCorrectionOutcome.Synced(
                    expense = expense.copy(
                        originalCurrency = draft.originalCurrencyCode ?: expense.originalCurrency,
                        originalCurrencyCode = draft.originalCurrencyCode ?: expense.originalCurrencyCode,
                        originalCurrencyCodeRaw = draft.originalCurrencyCode?.storageKey
                            ?: expense.originalCurrencyCodeRaw,
                        originalAmountMinor = draft.originalAmountMinor ?: expense.originalAmountMinor,
                        merchant = draft.merchant ?: expense.merchant,
                        category = draft.category ?: expense.category,
                        tags = draft.tags ?: expense.tags,
                        note = draft.note ?: expense.note,
                        expenseTime = if (draft.expenseTimeChanged) {
                            draft.expenseTime
                        } else {
                            expense.expenseTime
                        },
                        valueScore = if (draft.valueScoreChanged) {
                            draft.valueScore
                        } else {
                            expense.valueScore
                        },
                        regretScore = if (draft.regretScoreChanged) {
                            draft.regretScore
                        } else {
                            expense.regretScore
                        },
                        rowVersion = expense.rowVersion + 1,
                        factRevision = expense.factRevision + 1,
                    ),
                    revision = ExpenseRevision(
                        publicId = "rev-2",
                        revisionNumber = 2L,
                        changeKind = "correction",
                        reason = draft.reason,
                        changedFields = listOfNotNull(
                            draft.merchant?.let { "merchant" },
                            draft.category?.let { "category" },
                            draft.items?.let { "items" },
                            draft.splits?.let { "splits" },
                        ),
                        before = null,
                        after = emptyMap(),
                        actorAccountName = "我",
                        actorDeviceName = "这台手机",
                        createdAt = "2026-08-28T20:12:00Z",
                    ),
                ),
            )
        }

    var correctCalls = 0
    var lastCorrectionDraft: ExpenseCorrectionDraft? = null
    var fetchExpenseCalls = 0
    var fetchRevisionsCalls = 0
    val revisionRequests = mutableListOf<Pair<Int, Int>>()
    /** 每次 revisions 请求携带的快照锚（null = 进入新快照）。 */
    val revisionSnapshots = mutableListOf<Long?>()
    var fetchBillSplitSentCalls = 0
    var createBillSplitCalls = 0
    var lastCreateBillSplitArgs: Triple<Long, Long, Long>? = null
    var repaymentDraftCalls = 0
    var repaymentDraftExpense: Expense? = null
    var ackCalls = 0
    var lastAckExpense: Expense? = null
    var lastAckItems: ExpenseItems? = null

    /** 默认「原小票如此」结果：服务端确认 + 父行版本随 revision owner 递增。 */
    var ackResult: (Expense, ExpenseItems) -> Result<ItemsAckOutcome> = { expense, items ->
        Result.success(
            ItemsAckOutcome.Synced(
                items.copy(
                    itemsSumStatus = ItemsSumStatus.MISMATCH_ACKNOWLEDGED,
                    parentRowVersion = expense.rowVersion + 1,
                ),
            ),
        )
    }
    var splitMembersResult: () -> Result<List<FamilyMember>> = { Result.success(emptyList()) }
    var revisionsResult: suspend (Int, Int) -> Result<ExpenseRevisionPage> = { page, pageSize ->
        Result.success(
            ExpenseRevisionPage(
                items = listOf(
                    ExpenseRevision(
                        publicId = "rev-1",
                        revisionNumber = 1L,
                        changeKind = "confirmed",
                        reason = "首次确认",
                        changedFields = emptyList(),
                        before = null,
                        after = emptyMap(),
                        actorAccountName = "我",
                        actorDeviceName = "这台手机",
                        createdAt = "2026-08-22T11:38:00Z",
                    ),
                ),
                page = page,
                pageSize = pageSize,
                total = 1,
                snapshotRevision = 1L,
            ),
        )
    }
    var billSplitSentResult: () -> Result<List<BillSplitSent>> = { Result.success(emptyList()) }
    var createBillSplitResult: (Long, Long, Long) -> Result<BillSplitSent> = { _, _, _ ->
        Result.failure(RepositoryException(errorCode = "invalid_request", message = "not under test"))
    }
    var cancelBillSplitResult: (String) -> Result<BillSplitSent> = {
        Result.failure(RepositoryException(errorCode = "invalid_request", message = "not under test"))
    }
    var repaymentDraftResult: (Expense) -> Result<RepaymentDraft> = {
        Result.failure(RepositoryException(errorCode = "invalid_request", message = "not under test"))
    }

    fun member(
        memberId: Long,
        accountId: Long = memberId * 100,
        displayName: String = "成员$memberId",
        isSelf: Boolean = false,
        disabledAt: String? = null,
    ): FamilyMember = FamilyMember(
        memberId = memberId,
        accountId = accountId,
        accountPublicId = "acc-$memberId",
        displayName = displayName,
        role = "member",
        joinedAt = null,
        disabledAt = disabledAt,
        isSelf = isSelf,
    )

    fun sentInvite(
        publicId: String = "bs-1",
        status: String = "invited",
        amountCents: Long = 500L,
        senderExpenseId: Long = 7L,
    ): BillSplitSent = BillSplitSent(
        publicId = publicId,
        status = status,
        amountCents = amountCents,
        merchantSnapshot = null,
        categorySuggestion = null,
        expenseTimeSnapshot = null,
        expiresAt = "2026-09-01T00:00:00Z",
        createdAt = "2026-08-28T00:00:00Z",
        acceptedAt = null,
        rejectedAt = null,
        cancelledAt = null,
        expiredAt = null,
        receiverAccountId = 200L,
        receiverDisplayNameSnapshot = "家人",
        senderExpenseId = senderExpenseId,
    )

    fun repaymentDraft(publicId: String = "rd-1"): RepaymentDraft = RepaymentDraft(
        publicId = publicId,
        source = "other",
        amountCents = 391363L,
        homeCurrencyCode = "CNY",
        merchantLabel = "旧商家",
        capturedAt = "2026-08-28T13:13:00Z",
        status = "pending",
        suggestedDebtPublicId = null,
        committedDebtPublicId = null,
        committedRepaymentPublicId = null,
        createdAt = "2026-08-28T13:14:00Z",
        resolvedAt = null,
    )

    override fun canModifyLedger(): Boolean = canModifyLedgerFlag

    override fun currentTimezoneId(): String = "Asia/Shanghai"

    override suspend fun fetchExpense(id: Long): Result<Expense> {
        fetchExpenseCalls++
        return Result.success(baseExpense)
    }

    override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> =
        Result.success(baseExpense)

    override suspend fun categories(): Result<List<String>> = Result.success(listOf("餐饮", "居家"))

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> =
        Result.failure(RepositoryException(errorCode = "image_not_found", message = "no image"))

    override suspend fun fetchImage(id: Long): Result<ProtectedImage> =
        Result.failure(RepositoryException(errorCode = "image_not_found", message = "no image"))

    override suspend fun fetchExpenseItems(id: Long): Result<ExpenseItems> = itemsResult

    override suspend fun fetchExpenseSplits(id: Long): Result<ExpenseSplits> = splitsResult

    override suspend fun fetchSplitMembers(): Result<List<FamilyMember>> = splitMembersResult()

    override suspend fun fetchExpenseRevisions(
        id: Long,
        page: Int,
        pageSize: Int,
        snapshotRevision: Long?,
    ): Result<ExpenseRevisionPage> {
        fetchRevisionsCalls++
        revisionRequests += page to pageSize
        revisionSnapshots += snapshotRevision
        return revisionsResult(page, pageSize)
    }

    override suspend fun correctExpenseAllowingOffline(
        expense: Expense,
        correction: ExpenseCorrectionDraft,
    ): Result<ExpenseCorrectionOutcome> {
        correctCalls++
        lastCorrectionDraft = correction
        return correctResult(expense, correction)
    }

    override suspend fun acknowledgeItemsMismatchAllowingOffline(
        expense: Expense,
        currentItems: ExpenseItems,
    ): Result<ItemsAckOutcome> {
        ackCalls++
        lastAckExpense = expense
        lastAckItems = currentItems
        return ackResult(expense, currentItems)
    }

    override suspend fun createRepaymentDraftFromExpense(expense: Expense): Result<RepaymentDraft> {
        repaymentDraftCalls++
        repaymentDraftExpense = expense
        return repaymentDraftResult(expense)
    }

    override suspend fun createBillSplitInvitation(
        expenseId: Long,
        receiverAccountId: Long,
        amountCents: Long,
    ): Result<BillSplitSent> {
        createBillSplitCalls++
        lastCreateBillSplitArgs = Triple(expenseId, receiverAccountId, amountCents)
        return createBillSplitResult(expenseId, receiverAccountId, amountCents)
    }

    override suspend fun fetchBillSplitSent(): Result<List<BillSplitSent>> {
        fetchBillSplitSentCalls++
        return billSplitSentResult()
    }

    override suspend fun cancelBillSplitInvitation(publicId: String): Result<BillSplitSent> =
        cancelBillSplitResult(publicId)
}
