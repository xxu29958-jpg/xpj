package com.ticketbox.data.repository

import com.ticketbox.domain.model.DebtRepaymentPage

/** Paged read model only; repayment commands and canonical Debt settlement stay in DebtRepository. */
class DebtRepaymentRepository(apiProvider: ApiServiceProvider) : DebtRepaymentQueries {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "DebtRepayment",
        statusMessages = mapOf(
            403 to "当前账号无法查看这笔欠款的还款记录。",
            404 to "没有找到这笔欠款。",
        ),
    )

    override suspend fun listRepayments(publicId: String, page: Int): Result<DebtRepaymentPage> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api -> api.debtRepayments(publicId, page).toDomain() }
        }
}
