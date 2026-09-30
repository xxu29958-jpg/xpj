package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RepaymentDraftListResponseDto
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.ledgerRoleCanModify

/** Reviews personal repayment captures. Durable capture is owned by NotificationCaptureRepository. */
interface RepaymentDraftActions {
    fun canModifyLedger(): Boolean
    suspend fun readDrafts(expectedBinding: LogicalSessionBinding? = null): Result<ReadSnapshot<List<RepaymentDraft>>>
}

class RepaymentDraftRepository internal constructor(
    private val apiProvider: ApiServiceProvider,
    private val queryReader: DebtQueryReader,
) : RepaymentDraftActions {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val listingAdapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
        .adapter(RepaymentDraftListResponseDto::class.java)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "RepaymentDraft",
        statusMessages = mapOf(
            403 to "当前账号无法处理还款草稿。",
            404 to "没有找到这条还款草稿或欠款。",
            409 to "这条还款草稿已被处理，或欠款状态已变化，请刷新后再试。",
            422 to "还款金额超过这笔欠款的剩余，请换一笔欠款。",
        ),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    internal fun captureDeferredLedgerBinding(): LogicalSessionBinding? =
        ledgerRequestGuard.captureLogicalBinding()

    override suspend fun readDrafts(expectedBinding: LogicalSessionBinding?): Result<ReadSnapshot<List<RepaymentDraft>>> =
        errorHandler.safeCall {
            val binding = (expectedBinding?.let(ledgerRequestGuard::bindExact) ?: ledgerRequestGuard.bind()).logicalBinding
            val snapshot = queryReader.read(binding, DebtQueryScope(debtScope(binding, "repayment_draft_list", "all")),
                DebtReadSpec(listingAdapter, { repaymentDrafts(status = "all") },
                    validate = { require(it.items.map { row -> row.publicId }.distinct().size == it.items.size) },
                    isNewer = { _, _ -> false },
                    // These are personal captures, not Debt resources. A denied target must not erase them.
                    project = { value, _ -> value },
                )).getOrThrow()
            ReadSnapshot(snapshot.value.items.map { it.toDomain() }, snapshot.fetchedAt, snapshot.fromCache)
        }

}
