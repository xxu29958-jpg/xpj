package com.ticketbox.data.repository

import com.ticketbox.domain.model.DebtActivityPage

fun interface DebtActivityQueries {
    suspend fun listActivity(task: DebtTask, page: Int, focusRepayment: String?): Result<DebtActivityPage>
}
