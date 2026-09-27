package com.ticketbox.data.repository

import com.ticketbox.domain.model.DebtActivityPage

fun interface DebtActivityQueries {
    fun observeReadAccessDenials(): kotlinx.coroutines.flow.Flow<SnapshotAccessDenial> = kotlinx.coroutines.flow.emptyFlow()
    fun observeResourceDenials(): kotlinx.coroutines.flow.Flow<DebtReadResourceDenial> = kotlinx.coroutines.flow.emptyFlow()
    suspend fun listActivity(task: DebtTask, page: Int, focusRepayment: String?): Result<ReadSnapshot<DebtActivityPage>>
}
