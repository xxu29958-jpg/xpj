package com.ticketbox.data.repository

import com.ticketbox.domain.model.DebtRepaymentPage

/** The detail history consumes this read-only port; commands stay with DebtActions. */
fun interface DebtRepaymentQueries {
    suspend fun listRepayments(publicId: String, page: Int): Result<DebtRepaymentPage>
}
