package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import retrofit2.http.GET
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

class DebtActivityContractTest {
    @Test
    fun existingDebtClientExposesCompleteActivityWithoutRemovingRepaymentCompatibility() {
        val activity = ApiService::class.java.methods.singleOrNull { it.name == "debtActivity" }
        assertNotNull(activity, "Debt details need the complete participant activity endpoint")
        assertEquals("api/debts/{publicId}/activity", activity.getAnnotation(GET::class.java)?.value)
        val legacy = ApiService::class.java.methods.single { it.name == "debtRepayments" }
        assertEquals("api/debts/{publicId}/repayments", legacy.getAnnotation(GET::class.java)?.value)
    }
}
